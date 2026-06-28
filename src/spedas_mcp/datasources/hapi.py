"""HAPI data-source adapter (issue #21).

Browse and fetch from any HAPI-compliant server (CDAWeb, PDS-PPI, ISWA, LISIRD,
university networks) via the lightweight ``hapiclient`` package — the same client
``pyspedas.hapi_tools.hapi`` wraps. We call ``hapiclient`` directly rather than
``pyspedas.hapi`` so the result is an artifact (a written CSV/JSON file plus
compact metadata) instead of in-memory ``tplot`` variables, and so the heavier
full-``pyspedas`` install is not required just to reach a HAPI server.

``hapiclient.hapi`` shapes used here:

- ``hapi(server)`` -> ``dict`` following the HAPI catalog response, with a
  ``catalog`` list of ``{"id", "title"?}`` entries. Some servers (notably CDAWeb) omit titles for every dataset; missing titles are omitted from returned records rather than serialized as ``null``.
- ``hapi(server, dataset, parameters, start, stop)`` -> ``(data, meta)`` where
  ``data`` is a NumPy structured array (first field is the ISO time column) and
  ``meta`` is the HAPI ``info`` dict with a ``parameters`` list carrying
  ``name``/``units``/``description``/``size``/``fill``/``bins``.

Contract: bulk data is written to ``output_dir``; only the file path and compact
``parameters_meta`` are returned (artifact-first).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from . import DataSourceDependencyError, _error, _missing_dependency_error, require_hapiclient


def browse_hapi_catalog(server_url: str, query: str | None = None, max_results: int | None = 500) -> dict[str, Any]:
    """List datasets advertised by a HAPI server.

    Parameters
    ----------
    server_url:
        Base HAPI URL (ends in ``/hapi``), e.g.
        ``https://cdaweb.gsfc.nasa.gov/hapi``.
    query:
        Optional case-insensitive substring filter applied to dataset id and any title provided by the server.
    max_results:
        Maximum number of dataset records to return after filtering. Defaults to
        500 so unfiltered large catalogs remain MCP-size safe. Pass ``None`` to
        request all records from direct Python use.

    Returns
    -------
    dict
        ``{status, server, datasets, dataset_count, title_count, query?, note?}``
        on success, or a structured error payload. ``title`` is included per
        dataset only when the HAPI server provides one.
    """
    if not server_url or not server_url.strip():
        return _error(
            "server_url is required",
            hint="Pass a HAPI base URL, e.g. 'https://cdaweb.gsfc.nasa.gov/hapi'.",
        )
    server = server_url.strip()

    try:
        hapi = require_hapiclient()
    except DataSourceDependencyError as exc:
        return _missing_dependency_error(exc)

    catalog = hapi(server)
    items = catalog.get("catalog", []) if isinstance(catalog, dict) else []
    datasets: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        ds_id = item.get("id")
        if ds_id is None:
            continue
        entry: dict[str, Any] = {"id": ds_id}
        title = item.get("title")
        if title is not None:
            entry["title"] = title
        datasets.append(entry)

    if query:
        needle = query.casefold()
        datasets = [
            d for d in datasets
            if needle in str(d.get("id", "")).casefold()
            or needle in str(d.get("title", "")).casefold()
        ]

    total_dataset_count = len(datasets)
    if max_results is not None:
        try:
            limit = int(max_results)
        except (TypeError, ValueError):
            return _error("max_results must be an integer or null")
        if limit <= 0:
            return _error("max_results must be positive when provided")
        datasets = datasets[:limit]

    title_count = sum(1 for d in datasets if d.get("title") is not None)
    payload: dict[str, Any] = {
        "status": "success",
        "server": server,
        "dataset_count": len(datasets),
        "total_dataset_count": total_dataset_count,
        "datasets_truncated": len(datasets) < total_dataset_count,
        "title_count": title_count,
        "datasets": datasets,
    }
    if datasets and title_count == 0:
        payload["note"] = (
            "This HAPI server's /catalog response did not include dataset titles; "
            "records expose ids only. Use fetch_hapi_data/browse server-specific "
            "metadata tools to inspect parameter descriptions for a chosen dataset."
        )
    if len(datasets) < total_dataset_count:
        payload["note"] = (
            (payload.get("note") + " " if payload.get("note") else "")
            + f"Showing {len(datasets)} of {total_dataset_count} matching datasets; "
            "pass a query to narrow the catalog or increase max_results for direct Python use."
        )
    if query:
        payload["query"] = query
    return payload


def _param_meta(param: dict[str, Any], rows: int) -> dict[str, Any]:
    """Compact, JSON-serializable metadata for one HAPI parameter."""
    size = param.get("size")
    spectral = False
    bins = param.get("bins")
    if isinstance(bins, list) and bins:
        first = bins[0]
        if isinstance(first, dict) and first.get("centers") is not None:
            spectral = True
    return {
        "name": param.get("name"),
        "units": param.get("units"),
        "description": param.get("description"),
        "type": param.get("type"),
        "size": size,
        "spectral": spectral,
        "rows": rows,
    }


def fetch_hapi_data(
    server_url: str,
    dataset_id: str,
    parameters: list[str],
    start: str,
    stop: str,
    output_dir: str,
    format: Literal["csv", "json"] = "csv",
) -> dict[str, Any]:
    """Fetch a HAPI dataset slice to a file and return path + compact metadata.

    Parameters
    ----------
    server_url:
        HAPI base URL.
    dataset_id:
        Dataset id from :func:`browse_hapi_catalog`.
    parameters:
        Parameter names to load. The HAPI time field is always included.
    start, stop:
        ISO-8601 time bounds (``stop`` is exclusive, per the HAPI spec).
    output_dir:
        Directory for the written artifact (created if needed).
    format:
        ``"csv"`` (default) or ``"json"``.

    Returns
    -------
    dict
        ``{status, file_path, format, server, dataset_id, time_range, rows,
        parameters_meta}`` on success, or a structured error payload.
    """
    if not server_url or not server_url.strip():
        return _error(
            "server_url is required",
            hint="Pass a HAPI base URL, e.g. 'https://cdaweb.gsfc.nasa.gov/hapi'.",
        )
    if not dataset_id or not dataset_id.strip():
        return _error(
            "dataset_id is required",
            hint="Discover dataset ids with browse_hapi_catalog(server_url=...).",
        )
    if not parameters:
        return _error(
            "parameters is required and must be a non-empty list",
            hint="Pass one or more HAPI parameter names to fetch.",
        )
    if not start or not stop:
        return _error(
            "start and stop are required",
            hint="Pass ISO-8601 start/stop bounds; stop is exclusive per the HAPI spec.",
        )
    if format not in ("csv", "json"):
        return _error(
            f"unsupported format: {format}",
            hint="Use format='csv' or format='json'.",
        )

    server = server_url.strip()
    dataset = dataset_id.strip()

    try:
        hapi = require_hapiclient()
    except DataSourceDependencyError as exc:
        return _missing_dependency_error(exc)

    # numpy is a base dependency (pulled in by the XHelio backends); import here
    # to keep module import side-effect-free and cheap.
    import numpy as np

    params_csv = ",".join(parameters)
    data, meta = hapi(server, dataset, params_csv, start, stop)

    meta_params = meta.get("parameters", []) if isinstance(meta, dict) else []
    if not isinstance(data, np.ndarray) or data.dtype.names is None:
        return _error(
            "HAPI server returned an unexpected (non-structured) data payload",
            code="backend_error",
            hint="Verify the dataset id, parameter names, and time range against browse_hapi_catalog.",
            server=server,
            dataset_id=dataset,
        )

    field_names = list(data.dtype.names)
    rows = int(data.shape[0])

    # The first field is the HAPI time field; the rest are the requested
    # parameters (scalar or vector). Flatten vector columns into name[i] columns
    # so the written artifact is a flat table, and record per-parameter metadata.
    time_field = field_names[0]
    time_values = data[time_field]
    # HAPI returns ISO timestamps as bytes; decode for a clean text column.
    time_col_out: list[Any] = []
    for value in time_values.tolist():
        time_col_out.append(value.decode("utf-8") if isinstance(value, bytes) else value)

    meta_by_name = {
        p.get("name"): p for p in meta_params if isinstance(p, dict) and p.get("name")
    }

    columns: dict[str, list[Any]] = {"time": time_col_out}
    parameters_meta: dict[str, dict[str, Any]] = {}
    for name in field_names[1:]:
        col = data[name]
        param = meta_by_name.get(name, {"name": name})
        parameters_meta[name] = _param_meta(param, rows)
        if col.ndim == 1:
            columns[name] = _column_values(col)
        else:
            flat = col.reshape(rows, -1)
            for j in range(flat.shape[1]):
                columns[f"{name}[{j}]"] = _column_values(flat[:, j])

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start_short = str(start)[:10].replace("-", "")
    stop_short = str(stop)[:10].replace("-", "")
    base_name = f"{_safe_stem(dataset)}_{start_short}_{stop_short}"
    file_path = out_dir / f"{base_name}.{format}"
    counter = 1
    while file_path.exists():
        file_path = out_dir / f"{base_name}_{counter}.{format}"
        counter += 1

    if format == "json":
        file_path.write_text(json.dumps(columns, default=str), encoding="utf-8")
    else:
        _write_csv(file_path, columns)

    return {
        "status": "success",
        "file_path": str(file_path),
        "format": format,
        "server": server,
        "dataset_id": dataset,
        "time_range": {"start": start, "stop": stop},
        "rows": rows,
        "parameters_meta": parameters_meta,
    }


def _column_values(col: Any) -> list[Any]:
    """Convert a 1-D numpy column to a JSON/CSV-friendly Python list.

    Decodes byte strings and leaves numeric values as native Python scalars.
    """
    out: list[Any] = []
    for value in col.tolist():
        out.append(value.decode("utf-8") if isinstance(value, bytes) else value)
    return out


def _safe_stem(name: str) -> str:
    """Sanitize a dataset id into a filename stem."""
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_") or "hapi_dataset"


def _write_csv(file_path: Path, columns: dict[str, list[Any]]) -> None:
    """Write a column dict to CSV without requiring pandas."""
    import csv

    headers = list(columns.keys())
    n = len(columns[headers[0]]) if headers else 0
    with file_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(headers)
        for i in range(n):
            writer.writerow([columns[h][i] for h in headers])
