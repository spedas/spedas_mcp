"""FDSN/MTH5 magnetotelluric data-source adapter (issue #22).

Browse and fetch ground-based magnetotelluric (MT) magnetic-field observations
from EarthScope's FDSN service via ``pyspedas.mth5`` (which wraps the optional
``mth5`` + ``obspy`` stack):

- :func:`browse_fdsn_datasets` wraps ``pyspedas.mth5.utilities.datasets`` to list
  stations that expose three same-band magnetic channels (e.g. ``LFE/LFN/LFZ``).
- :func:`fetch_fdsn_data` wraps ``pyspedas.mth5.load_fdsn``, which downloads an
  MTH5 file from EarthScope, calibrates counts -> nT, and enforces the
  3-component Hx/Hy/Hz geometry. ``load_fdsn`` returns a ``tplot`` variable; we
  read it back, write the time-series to an artifact file, and return only the
  path plus station/channel metadata (artifact-first).

The heavy MTH5/time-series payload is written to ``output_dir``; tool return
values stay compact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from . import DataSourceDependencyError, _error, _missing_dependency_error, require_mth5


def _validate_trange(trange: Any) -> str | None:
    """Return an error message if ``trange`` is not a 2-element list, else None."""
    if not isinstance(trange, (list, tuple)) or len(trange) != 2:
        return "trange must be a 2-element list [start, stop]"
    if not all(isinstance(t, str) and t.strip() for t in trange):
        return "trange entries must be non-empty date strings (e.g. '2015-06-22')"
    return None


def browse_fdsn_datasets(
    trange: list[str],
    network: str | None = None,
    station: str | None = None,
    usa_only: bool = False,
) -> dict[str, Any]:
    """List FDSN MT magnetic stations with 3-component coverage in a time range.

    Parameters
    ----------
    trange:
        ``[start, stop]`` date strings, e.g. ``["2015-06-22", "2015-06-23"]``.
    network, station:
        Optional FDSN network/station code filters.
    usa_only:
        Restrict the query to the continental-US bounding box.

    Returns
    -------
    dict
        ``{status, trange, stations: [{network, station, time_range:
        {start, end}, channels}...], station_count, ...}`` on success, or a
        structured error payload.
    """
    err = _validate_trange(trange)
    if err is not None:
        return _error(
            err,
            hint="Pass trange as ['YYYY-MM-DD', 'YYYY-MM-DD'].",
        )

    try:
        mth5_module = require_mth5()
    except DataSourceDependencyError as exc:
        return _missing_dependency_error(exc)

    result = mth5_module.utilities.datasets(
        trange=list(trange),
        network=network,
        station=station,
        USAarea=usa_only,
    )
    result = result or {}

    stations: list[dict[str, Any]] = []
    for net, net_data in sorted(result.items()):
        if not isinstance(net_data, dict):
            continue
        for sta, sta_data in sorted(net_data.items()):
            if not isinstance(sta_data, dict):
                continue
            for time_key, channels in sta_data.items():
                start, end = (time_key if isinstance(time_key, (tuple, list)) and len(time_key) == 2
                              else (None, None))
                stations.append({
                    "network": net,
                    "station": sta,
                    "time_range": {"start": start, "end": end},
                    "channels": list(channels) if isinstance(channels, (list, tuple)) else channels,
                })

    payload: dict[str, Any] = {
        "status": "success",
        "trange": list(trange),
        "station_count": len(stations),
        "stations": stations,
    }
    if network is not None:
        payload["network"] = network
    if station is not None:
        payload["station"] = station
    if usa_only:
        payload["usa_only"] = True
    return payload


def fetch_fdsn_data(
    trange: list[str],
    network: str,
    station: str,
    output_dir: str,
    format: Literal["csv", "json"] = "csv",
) -> dict[str, Any]:
    """Fetch a calibrated 3-component MT magnetic time-series to a file.

    Parameters
    ----------
    trange:
        ``[start, stop]`` date strings.
    network, station:
        FDSN network/station codes (from :func:`browse_fdsn_datasets`).
    output_dir:
        Directory for the written artifact (created if needed).
    format:
        ``"csv"`` (default) or ``"json"``.

    Returns
    -------
    dict
        ``{status, file_path, format, network, station, trange, rows, channels,
        units?}`` on success, or a structured error payload.
    """
    err = _validate_trange(trange)
    if err is not None:
        return _error(err, hint="Pass trange as ['YYYY-MM-DD', 'YYYY-MM-DD'].")
    if not network or not network.strip():
        return _error(
            "network is required",
            hint="Discover network/station with browse_fdsn_datasets(trange=...).",
        )
    if not station or not station.strip():
        return _error(
            "station is required",
            hint="Discover network/station with browse_fdsn_datasets(trange=...).",
        )
    if format not in ("csv", "json"):
        return _error(
            f"unsupported format: {format}",
            hint="Use format='csv' or format='json'.",
        )

    try:
        mth5_module = require_mth5()
    except DataSourceDependencyError as exc:
        return _missing_dependency_error(exc)

    import numpy as np

    # load_fdsn downloads + calibrates and stores a tplot variable; it returns
    # the variable name (or None when no qualifying 3-component data exist).
    var_name = mth5_module.load_fdsn(
        trange=list(trange),
        network=network.strip(),
        station=station.strip(),
    )
    if not var_name:
        return _error(
            "No 3-component magnetic data returned for this network/station/time range",
            code="resource_not_found",
            hint="Confirm coverage with browse_fdsn_datasets; not every station has 3 magnetic components in the window.",
            network=network,
            station=station,
            trange=list(trange),
        )

    # Read the stored series back as (times, y[N,3]) plus any attached metadata.
    from pyspedas import get_data

    series = get_data(var_name)
    if series is None:
        return _error(
            "FDSN load produced no readable time-series",
            code="backend_error",
            hint="Retry, or verify the station/time range with browse_fdsn_datasets.",
            network=network,
            station=station,
        )

    times = np.asarray(series.times)
    values = np.asarray(series.y)
    if values.ndim == 1:
        values = values.reshape(-1, 1)
    rows = int(times.shape[0])

    metadata = get_data(var_name, metadata=True) or {}
    channel_names = _channel_names(metadata, values.shape[1])
    units = _units(metadata)

    columns: dict[str, list[Any]] = {"time": [float(t) for t in times.tolist()]}
    for idx, channel in enumerate(channel_names):
        columns[channel] = [
            None if (v is None or (isinstance(v, float) and np.isnan(v))) else float(v)
            for v in values[:, idx].tolist()
        ]

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    start_short = str(trange[0])[:10].replace("-", "")
    stop_short = str(trange[1])[:10].replace("-", "")
    base_name = f"fdsn_{_safe(network)}_{_safe(station)}_{start_short}_{stop_short}"
    file_path = out_dir / f"{base_name}.{format}"
    counter = 1
    while file_path.exists():
        file_path = out_dir / f"{base_name}_{counter}.{format}"
        counter += 1

    if format == "json":
        file_path.write_text(json.dumps(columns, default=str), encoding="utf-8")
    else:
        _write_csv(file_path, columns)

    payload: dict[str, Any] = {
        "status": "success",
        "file_path": str(file_path),
        "format": format,
        "network": network,
        "station": station,
        "trange": list(trange),
        "rows": rows,
        "channels": channel_names,
    }
    if units:
        payload["units"] = units
    return payload


def _channel_names(metadata: dict[str, Any], n_cols: int) -> list[str]:
    """Resolve human-readable channel names, defaulting to Hx/Hy/Hz/...."""
    names = metadata.get("legend_names") if isinstance(metadata, dict) else None
    if isinstance(names, (list, tuple)) and len(names) == n_cols and all(names):
        return [str(name) for name in names]
    default = ["hx", "hy", "hz"]
    if n_cols <= len(default):
        return default[:n_cols]
    return default + [f"c{idx}" for idx in range(len(default), n_cols)]


def _units(metadata: dict[str, Any]) -> str | None:
    """Best-effort units string from the stored tplot metadata."""
    if not isinstance(metadata, dict):
        return None
    plot_options = metadata.get("plot_options")
    if isinstance(plot_options, dict):
        yaxis = plot_options.get("yaxis_opt")
        if isinstance(yaxis, dict):
            sub = yaxis.get("axis_subtitle")
            if isinstance(sub, str) and sub.strip():
                return sub.strip()
    sub = metadata.get("ysubtitle")
    if isinstance(sub, str) and sub.strip():
        return sub.strip()
    return None


def _safe(name: str) -> str:
    """Sanitize a network/station code into a filename fragment."""
    import re

    return re.sub(r"[^A-Za-z0-9._-]+", "_", str(name)).strip("_") or "x"


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
