"""Artifact rendering for the SPEDAS Agent Kit analysis layer (issue #20).

This module closes the explore/visualize gap in the research loop: the data,
spectral, field-model, and particle tools all write bulk arrays to disk as
artifacts (CSV/JSON time-series and ``.npz`` spectrogram matrices) and return
only compact summaries, but nothing in the server could turn those artifacts
into a picture. :func:`render_tplot` consumes one or more of those artifacts and
renders a multi-panel, tplot-style stacked PNG (line panels, spectrogram panels
with colorbars, and scatter/xy hodogram panels).

Design contract (mirrors :mod:`spedas_agent_kit.analysis.spectral` and the rest of the
analysis layer, roadmap epic #10):

- **File-in / file-out.** Inputs are paths to local artifacts; the output is a
  PNG written to ``output_file``. The return is a small, JSON-serializable dict
  with ``status``, the output path, ``n_panels``, ``trange``, ``size_px``, and
  compact per-panel metadata. **Image bytes are never returned inline** and no
  giant arrays are echoed back (artifact-first discipline).
- **Lazy, gated backend.** ``matplotlib`` is imported only inside the renderer
  and forced onto the headless ``Agg`` backend (no GUI/display); a missing
  ``[analysis]`` extra yields a clean ``status="error"`` payload. ``pyspedas`` is
  *not* required — rendering is pure NumPy + Matplotlib over already-fetched
  artifacts.
- **No network.** All computation is local; the tool never downloads data.

Supported input artifacts (auto-detected by content, then extension):

- Spectrogram ``.npz`` from the spectral tools (``power`` matrix with ``time`` /
  ``freq`` axes) and the particle spectra tool (``spectrogram`` matrix with
  ``time`` / ``axis`` axes).
- Line time-series: CSV / JSON objects with a time column/key plus one or more
  numeric value columns (the same shapes the data layer writes), or a 1-D/2-D
  ``.npz``/``.npy`` value array with an optional time axis.
- Scatter/xy panels (explicit ``panel_types="scatter"`` or ``"xy"``): one
  2-D numeric matrix per input artifact, with ``x_component`` / ``y_component``
  selecting columns for hodograms or other parametric x-y plots.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import AnalysisDependencyError, require_matplotlib

# Panel-type tokens the caller may pass per input file. ``auto`` (default) lets
# the loader decide spectrogram vs line from the artifact's content.
_PANEL_AUTO = "auto"
_PANEL_LINE = "line"
_PANEL_SPECTROGRAM = "spectrogram"
_PANEL_SCATTER = "scatter"
# Accepted aliases -> canonical token.
_PANEL_ALIASES: dict[str, str] = {
    "auto": _PANEL_AUTO,
    "line": _PANEL_LINE,
    "timeseries": _PANEL_LINE,
    "time_series": _PANEL_LINE,
    "lineplot": _PANEL_LINE,
    "spectrogram": _PANEL_SPECTROGRAM,
    "spectra": _PANEL_SPECTROGRAM,
    "spec": _PANEL_SPECTROGRAM,
    "scatter": _PANEL_SCATTER,
    "xy": _PANEL_SCATTER,
    "x-y": _PANEL_SCATTER,
    "hodogram": _PANEL_SCATTER,
    "parametric": _PANEL_SCATTER,
}

# Bounds that keep a single render from producing an absurd / memory-blowing
# canvas. Inches for figure size, plus a hard pixel ceiling per dimension.
_MIN_SIZE_IN = 1.0
_MAX_SIZE_IN = 100.0
_MIN_DPI = 10
_MAX_DPI = 600
_MAX_PIXELS_PER_DIM = 20_000

# .npz/.npy keys that look like a spectrogram matrix or its axes.
_SPECTROGRAM_KEYS = ("power", "spectrogram", "spec", "z")
_TIME_KEYS = ("time", "times", "t", "x")
_YAXIS_KEYS = ("freq", "frequency", "period", "axis", "energy", "y")
# Optional string-valued .npz keys that make a spectra artifact self-describing
# (issue #150): when present, render_tplot prefers them for the y-axis label and
# the colorbar label over the filename-stem fallback. Older artifacts that omit
# them keep the legacy stem behavior.
_AXIS_LABEL_KEYS = ("axis_label",)
_AXIS_UNITS_KEYS = ("axis_units",)
_VALUE_LABEL_KEYS = ("value_label", "z_label")


def _error(
    message: str,
    *,
    code: str = "invalid_argument",
    hint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the uniform structured error payload for analysis tools.

    Mirrors :func:`spedas_agent_kit.analysis.spectral._error` and the server's
    ``_error_response`` envelope so plotting errors share the same
    ``{status: "error", code, message, ...}`` contract (issue #27).
    """
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint is not None:
        payload["hint"] = hint
    payload.update(extra)
    return payload


def _finite_range(array: Any) -> list[float] | None:
    """Return ``[min, max]`` over finite values, or ``None`` if none are finite."""
    import numpy as np

    arr = np.asarray(array, dtype="float64")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return [float(finite.min()), float(finite.max())]


def _read_label_keys(loaded: Any) -> dict[str, str]:
    """Extract optional self-describing string labels from a loaded ``.npz``.

    Reads ``axis_label`` / ``axis_units`` / ``value_label`` (issue #150) when
    present, decoding 0-d/bytes/str values to plain strings. Missing or blank
    values are omitted so callers can fall back cleanly (e.g. to the filename
    stem) for older artifacts that never wrote these keys.
    """
    out: dict[str, str] = {}
    for canonical, keys in (
        ("axis_label", _AXIS_LABEL_KEYS),
        ("axis_units", _AXIS_UNITS_KEYS),
        ("value_label", _VALUE_LABEL_KEYS),
    ):
        for key in keys:
            if key not in loaded.files:
                continue
            text = _coerce_label(loaded[key])
            if text:
                out[canonical] = text
                break
    return out


def _coerce_label(value: Any) -> str | None:
    """Decode an ``.npz`` label entry (0-d array / bytes / str) to a string."""
    import numpy as np

    arr = np.asarray(value)
    try:
        item = arr.item() if arr.ndim == 0 else (arr.tolist()[0] if arr.size else None)
    except (ValueError, IndexError):
        item = None
    if item is None:
        return None
    if isinstance(item, bytes):
        item = item.decode("utf-8", "replace")
    text = str(item).strip()
    return text or None


def _read_sidecar_labels(path: Path) -> dict[str, str]:
    """Read a ``<artifact>.labels.json`` sidecar describing a table artifact.

    Table artifacts (CSV/JSON) cannot embed string label keys the way ``.npz``
    files can, so the writer convention (issue #154) is a sibling JSON sidecar
    named ``<artifact-name>.labels.json`` (e.g. ``particle_moments.csv`` ->
    ``particle_moments.csv.labels.json``). It may carry ``axis_label`` /
    ``axis_units`` / ``value_label`` strings used the same way as the embedded
    ``.npz`` keys. Missing/unreadable/blank entries are simply omitted so a
    sidecar-less artifact keeps the filename-stem fallback. Per-column metadata
    (e.g. a ``columns`` map) is allowed in the file but ignored here.
    """
    sidecar = path.with_name(path.name + ".labels.json")
    if not sidecar.exists():
        return {}
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("axis_label", "axis_units", "value_label"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def _axis_ylabel(panel: dict[str, Any]) -> str:
    """Resolve a y-axis label, preferring embedded/sidecar artifact labels.

    Uses ``"<axis_label> [<axis_units>]"`` when the artifact carries them
    (issue #150 for ``.npz``, issue #154 for line/scatter + table sidecars),
    ``"<axis_label>"`` if only the label is present, and falls back to the
    filename stem for older label-less artifacts. Shared by spectrogram, line,
    and scatter panels so every panel type labels its y-axis the same way.
    """
    label = panel.get("axis_label")
    units = panel.get("axis_units")
    if label and units:
        return f"{label} [{units}]"
    if label:
        return str(label)
    return Path(panel["file"]).stem


# Backwards-compatible alias: the spectrogram path historically called this
# helper by a spectrogram-specific name. Line/scatter share the same logic now.
_spectrogram_ylabel = _axis_ylabel


def _normalize_panel_types(
    panel_types: list[str] | str | None, n_inputs: int
) -> tuple[list[str] | None, dict[str, Any] | None]:
    """Resolve ``panel_types`` to one canonical token per input file.

    Accepts ``None`` (all ``auto``), a single scalar string (broadcast to every
    panel), or a list matching ``input_files`` in length. Returns
    ``(resolved_list, None)`` on success or ``(None, error_payload)`` on failure.
    """
    if panel_types is None:
        return [_PANEL_AUTO] * n_inputs, None

    if isinstance(panel_types, str):
        panel_types = [panel_types] * n_inputs

    if len(panel_types) != n_inputs:
        return None, _error(
            "panel_types length must match input_files: "
            f"{len(panel_types)} panel_types vs {n_inputs} input_files",
            n_panel_types=len(panel_types),
            n_input_files=n_inputs,
        )

    resolved: list[str] = []
    for raw in panel_types:
        key = (raw or "").strip().lower()
        canonical = _PANEL_ALIASES.get(key)
        if canonical is None:
            return None, _error(
                f"unsupported panel type '{raw}'",
                supported_panel_types=sorted(set(_PANEL_ALIASES)),
            )
        resolved.append(canonical)
    return resolved, None


def _parse_trange(trange: list[str] | None) -> tuple[tuple[float, float] | None, dict[str, Any] | None]:
    """Parse an optional 2-element time range into ``(start, stop)`` Unix seconds.

    Accepts ISO-8601 strings or numeric (Unix-second) bounds. Returns
    ``(bounds_or_None, None)`` on success or ``(None, error_payload)`` on a
    structured failure (wrong length / unparseable / start >= stop).
    """
    if trange is None:
        return None, None

    if len(trange) != 2:
        return None, _error(
            f"trange must have exactly 2 elements [start, stop]; got {len(trange)}",
            code="invalid_argument",
        )

    import numpy as np
    import pandas as pd

    bounds: list[float] = []
    for value in trange:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            bounds.append(float(value))
            continue
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        if parsed is pd.NaT or (hasattr(parsed, "value") and pd.isna(parsed)):
            return None, _error(
                f"could not parse trange bound '{value}' as a time; "
                "use ISO-8601 (e.g. '2020-01-01T00:00:00Z') or Unix seconds",
                code="invalid_argument",
            )
        bounds.append(float(np.int64(parsed.value)) / 1e9)

    start, stop = bounds
    if not (np.isfinite(start) and np.isfinite(stop)):
        return None, _error("trange bounds must be finite", code="invalid_argument")
    if start >= stop:
        return None, _error(
            f"trange start ({start}) must be < stop ({stop})", code="invalid_argument"
        )
    return (start, stop), None


def _broadcast_logflags(
    flags: list[bool] | bool | None, n_panels: int, name: str
) -> tuple[list[bool], dict[str, Any] | None]:
    """Resolve ``ylog`` / ``zlog`` to one boolean per panel (scalar broadcasts)."""
    if flags is None:
        return [False] * n_panels, None
    if isinstance(flags, bool):
        return [flags] * n_panels, None
    if len(flags) != n_panels:
        return [], _error(
            f"{name} length must match input_files: {len(flags)} vs {n_panels}",
            code="invalid_argument",
        )
    return [bool(f) for f in flags], None


def _broadcast_components(
    components: list[int] | int | None, n_panels: int, name: str
) -> tuple[list[int | None], dict[str, Any] | None]:
    """Resolve scatter component selectors to one optional int per input file."""
    if components is None:
        return [None] * n_panels, None
    if isinstance(components, int) and not isinstance(components, bool):
        return [components] * n_panels, None
    if isinstance(components, list):
        if len(components) != n_panels:
            return [], _error(
                f"{name} length must match input_files: {len(components)} vs {n_panels}",
                code="invalid_argument",
            )
        out: list[int | None] = []
        for value in components:
            if value is None:
                out.append(None)
            elif isinstance(value, int) and not isinstance(value, bool):
                out.append(value)
            else:
                return [], _error(
                    f"{name} entries must be integer column indices",
                    code="invalid_argument",
                )
        return out, None
    return [], _error(
        f"{name} must be an integer, a list of integers, or null",
        code="invalid_argument",
    )


def _load_artifact(
    path: Path,
    panel_type: str,
    x_component: int | None = None,
    y_component: int | None = None,
) -> dict[str, Any]:
    """Load one artifact into a normalized panel descriptor.

    Returns a dict with at least ``kind`` (``"line"``, ``"spectrogram"``, or
    ``"scatter"``) plus the arrays needed to draw it. Raises ``ValueError`` with
    an actionable message when the artifact cannot be parsed or is ambiguous for
    the requested ``panel_type``.
    """
    suffix = path.suffix.lower()
    if suffix in (".npz", ".npy"):
        return _load_array_artifact(path, suffix, panel_type, x_component, y_component)
    if suffix in (".csv", ".json"):
        return _load_table_artifact(path, suffix, panel_type, x_component, y_component)
    raise ValueError(
        f"unsupported artifact extension '{suffix}' for {path.name}; "
        "expected one of .npz, .npy, .csv, .json"
    )


def _load_array_artifact(
    path: Path,
    suffix: str,
    panel_type: str,
    x_component: int | None = None,
    y_component: int | None = None,
) -> dict[str, Any]:
    """Load a ``.npz`` / ``.npy`` artifact (matrix or value array)."""
    import numpy as np

    labels: dict[str, str] = {}
    if suffix == ".npy":
        data = np.asarray(np.load(path), dtype="float64")
        npz = {"_array": data}
    else:
        loaded = np.load(path)
        # Optional self-describing string keys (issue #150) must be read before
        # the float64 cast below, which would raise on a non-numeric value.
        labels = _read_label_keys(loaded)
        label_keys = set(_AXIS_LABEL_KEYS) | set(_AXIS_UNITS_KEYS) | set(_VALUE_LABEL_KEYS)
        npz = {
            k: np.asarray(loaded[k], dtype="float64")
            for k in loaded.files
            if k not in label_keys
        }

    # Locate a 2-D spectrogram matrix by known key, else any 2-D array.
    spec_key = next((k for k in _SPECTROGRAM_KEYS if k in npz and npz[k].ndim == 2), None)
    if spec_key is None:
        spec_key = next((k for k in npz if npz[k].ndim == 2), None)

    want_spec = panel_type == _PANEL_SPECTROGRAM
    want_line = panel_type == _PANEL_LINE
    want_scatter = panel_type == _PANEL_SCATTER

    if want_scatter:
        matrix_key = _select_scatter_matrix_key(npz)
        if matrix_key is None:
            raise ValueError(
                f"{path.name}: requested a scatter/xy panel but no 2-D matrix was "
                "found in the artifact"
            )
        return _build_scatter_panel(
            path.name, npz[matrix_key], matrix_key, npz, x_component, y_component, labels
        )

    if spec_key is not None and not want_line:
        z = npz[spec_key]
        time = _first_present(npz, _TIME_KEYS)
        yaxis = _first_present(npz, _YAXIS_KEYS, exclude={spec_key})
        # Orient so z is (n_time, n_y).
        if time is not None and z.shape[0] != time.shape[0] and z.shape[1] == time.shape[0]:
            z = z.T
        n_time, n_y = z.shape
        if time is None:
            time = np.arange(n_time, dtype="float64")
        if yaxis is None or yaxis.shape[0] != n_y:
            yaxis = np.arange(n_y, dtype="float64")
        return {
            "kind": _PANEL_SPECTROGRAM,
            "time": time,
            "yaxis": yaxis,
            "z": z,
            "shape": [int(n_time), int(n_y)],
            "value_range": _finite_range(z),
            # Optional self-describing labels (issue #150); empty for older npz.
            "axis_label": labels.get("axis_label"),
            "axis_units": labels.get("axis_units"),
            "value_label": labels.get("value_label"),
        }

    if want_spec:
        raise ValueError(
            f"{path.name}: requested a spectrogram panel but no 2-D matrix was "
            "found in the artifact"
        )

    # Line artifact: pick a 1-D value array (and an optional time axis).
    value_key = next(
        (k for k in npz if k not in _TIME_KEYS and npz[k].ndim == 1 and npz[k].size > 0),
        None,
    )
    if value_key is None and "_array" in npz and npz["_array"].ndim <= 2:
        value_key = "_array"
    if value_key is None:
        raise ValueError(
            f"{path.name}: could not find a 1-D value array to plot as a line panel"
        )
    values = npz[value_key]
    time = _first_present(npz, _TIME_KEYS)
    if values.ndim == 2:
        # Treat a 2-D (n_time, n_series) array as multiple line series.
        series = [values[:, i] for i in range(values.shape[1])]
    else:
        series = [values]
    n_time = series[0].shape[0]
    if time is None or time.shape[0] != n_time:
        time = np.arange(n_time, dtype="float64")
    return {
        "kind": _PANEL_LINE,
        "time": time,
        "series": series,
        "labels": [value_key] if len(series) == 1 else [f"{value_key}[{i}]" for i in range(len(series))],
        "shape": [int(n_time), len(series)],
        "value_range": _finite_range(np.concatenate([s.ravel() for s in series])),
        # Optional self-describing labels (issue #154); empty for older npz.
        "axis_label": labels.get("axis_label"),
        "axis_units": labels.get("axis_units"),
        "value_label": labels.get("value_label"),
    }


def _select_scatter_matrix_key(npz: dict[str, Any]) -> str | None:
    """Pick the one 2-D value matrix used by an explicit scatter/xy panel."""
    preferred = ("values", "data", "matrix", "b", "b_gsm", "positions", "xyz", "_array")
    for key in preferred:
        if key in npz and npz[key].ndim == 2:
            return key
    axis_like = set(_TIME_KEYS) | set(_YAXIS_KEYS)
    return next((k for k in npz if k not in axis_like and npz[k].ndim == 2), None)


def _build_scatter_panel(
    name: str,
    matrix: Any,
    matrix_key: str,
    npz: dict[str, Any],
    x_component: int | None,
    y_component: int | None,
    artifact_labels: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Normalize one 2-D matrix into x/y arrays for a hodogram panel."""
    import numpy as np

    values = np.asarray(matrix, dtype="float64")
    if values.ndim != 2 or min(values.shape) == 0:
        raise ValueError(f"{name}: scatter/xy panels require a non-empty 2-D matrix")

    time = _first_present(npz, _TIME_KEYS)
    had_time_axis = time is not None
    if time is not None and values.shape[0] != time.shape[0] and values.shape[1] == time.shape[0]:
        values = values.T

    n_samples, n_components = values.shape
    x_idx = 0 if x_component is None else int(x_component)
    y_idx = 1 if y_component is None else int(y_component)
    for label, idx in (("x_component", x_idx), ("y_component", y_idx)):
        if idx < 0 or idx >= n_components:
            raise ValueError(
                f"{name}: {label}={idx} is out of bounds for matrix '{matrix_key}' "
                f"with {n_components} columns"
            )
    if x_idx == y_idx:
        raise ValueError(f"{name}: x_component and y_component must be different")

    if time is None or time.shape[0] != n_samples:
        time = np.arange(n_samples, dtype="float64")
        had_time_axis = False

    x = values[:, x_idx]
    y = values[:, y_idx]
    artifact_labels = artifact_labels or {}
    return {
        "kind": _PANEL_SCATTER,
        "time": time,
        "x": x,
        "y": y,
        "shape": [int(n_samples), int(n_components)],
        "matrix_key": matrix_key,
        "components": [int(x_idx), int(y_idx)],
        "labels": [f"{matrix_key}[{x_idx}]", f"{matrix_key}[{y_idx}]"],
        "value_range": _finite_range(np.concatenate([x.ravel(), y.ravel()])),
        "x_range": _finite_range(x),
        "y_range": _finite_range(y),
        "has_time_axis": bool(had_time_axis),
        # Optional self-describing labels (issue #154); empty for older artifacts.
        # For scatter panels these describe the matrix as a whole; the per-axis
        # column labels above remain the x/y tick labels.
        "axis_label": artifact_labels.get("axis_label"),
        "axis_units": artifact_labels.get("axis_units"),
        "value_label": artifact_labels.get("value_label"),
    }


def _first_present(npz: dict[str, Any], keys: tuple[str, ...], exclude: set[str] | None = None) -> Any:
    """Return the first 1-D array among ``keys`` present in ``npz`` (or ``None``)."""
    exclude = exclude or set()
    for key in keys:
        if key in npz and key not in exclude and npz[key].ndim == 1:
            return npz[key]
    return None


def _load_table_artifact(
    path: Path,
    suffix: str,
    panel_type: str,
    x_component: int | None = None,
    y_component: int | None = None,
) -> dict[str, Any]:
    """Load a CSV / JSON time-series artifact as a line or scatter panel."""
    import numpy as np
    import pandas as pd

    if panel_type == _PANEL_SPECTROGRAM:
        raise ValueError(
            f"{path.name}: spectrogram panels require a 2-D matrix artifact "
            "(.npz/.npy), not a CSV/JSON table"
        )

    # Optional self-describing labels via a sibling sidecar (issue #154).
    sidecar_labels = _read_sidecar_labels(path)

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path.name}: JSON input must be an object mapping column -> list")
        df = pd.DataFrame(payload)
    else:
        df = pd.read_csv(path)

    if df.empty:
        raise ValueError(f"{path.name}: input file contains no rows")

    # Resolve the time column: prefer a named "time", else the first column.
    if "time" in df.columns:
        time_series = df["time"]
    else:
        time_series = df[df.columns[0]]

    if pd.api.types.is_numeric_dtype(time_series):
        time = time_series.to_numpy(dtype="float64")
    else:
        parsed = pd.to_datetime(time_series, utc=True, errors="coerce")
        if parsed.isna().all():
            raise ValueError(
                f"{path.name}: time column could not be parsed as numeric or datetime"
            )
        time = parsed.astype("int64").to_numpy() / 1e9

    value_cols = [
        c
        for c in df.columns
        if c != time_series.name and pd.api.types.is_numeric_dtype(df[c])
    ]
    if not value_cols:
        raise ValueError(
            f"{path.name}: no numeric value columns found to plot; "
            f"columns: {list(df.columns)}"
        )

    if panel_type == _PANEL_SCATTER:
        values = df[value_cols].to_numpy(dtype="float64")
        npz = {"values": values, "time": time}
        panel = _build_scatter_panel(
            path.name, values, "values", npz, x_component, y_component, sidecar_labels
        )
        panel["labels"] = [
            str(value_cols[panel["components"][0]]),
            str(value_cols[panel["components"][1]]),
        ]
        return panel

    series = [df[c].to_numpy(dtype="float64") for c in value_cols]
    return {
        "kind": _PANEL_LINE,
        "time": time,
        "series": series,
        "labels": list(value_cols),
        "shape": [int(time.shape[0]), len(series)],
        "value_range": _finite_range(np.concatenate([s.ravel() for s in series])),
        # Optional self-describing labels from a sidecar (issue #154); empty
        # for tables without one.
        "axis_label": sidecar_labels.get("axis_label"),
        "axis_units": sidecar_labels.get("axis_units"),
        "value_label": sidecar_labels.get("value_label"),
    }


def _apply_trange(panel: dict[str, Any], bounds: tuple[float, float]) -> dict[str, Any]:
    """Filter a panel's samples to ``bounds`` (start, stop) along the time axis."""
    import numpy as np

    start, stop = bounds
    time = np.asarray(panel["time"], dtype="float64")
    mask = (time >= start) & (time <= stop)
    if not mask.any():
        return panel  # leave untouched; caller records an empty-after-filter note
    out = dict(panel)
    out["time"] = time[mask]
    if panel["kind"] == _PANEL_SPECTROGRAM:
        out["z"] = np.asarray(panel["z"])[mask, :]
        out["shape"] = [int(out["z"].shape[0]), int(out["z"].shape[1])]
        out["value_range"] = _finite_range(out["z"])
    elif panel["kind"] == _PANEL_SCATTER:
        out["x"] = np.asarray(panel["x"])[mask]
        out["y"] = np.asarray(panel["y"])[mask]
        out["shape"] = [int(out["time"].shape[0]), int(panel["shape"][1])]
        out["value_range"] = _finite_range(np.concatenate([out["x"].ravel(), out["y"].ravel()]))
        out["x_range"] = _finite_range(out["x"])
        out["y_range"] = _finite_range(out["y"])
    else:
        out["series"] = [np.asarray(s)[mask] for s in panel["series"]]
        out["shape"] = [int(out["time"].shape[0]), len(out["series"])]
        out["value_range"] = _finite_range(
            np.concatenate([s.ravel() for s in out["series"]])
        )
    return out


def render_tplot(
    input_files: list[str],
    output_file: str,
    panel_types: list[str] | str | None = None,
    trange: list[str] | None = None,
    xsize: int = 12,
    ysize: int | None = None,
    dpi: int = 200,
    ylog: list[bool] | bool | None = None,
    zlog: list[bool] | bool | None = None,
    x_component: list[int] | int | None = None,
    y_component: list[int] | int | None = None,
) -> dict[str, Any]:
    """Render a multi-panel tplot-style PNG from analysis artifacts (#20).

    One stacked panel per input file (top to bottom). Spectrogram artifacts
    (``.npz`` ``power``/``spectrogram`` matrices) render as pcolormesh panels with
    a colorbar; time-series artifacts (CSV/JSON tables, 1-D/2-D arrays) render as
    line panels. Explicit ``scatter``/``xy`` panels render one 2-D matrix per
    input file as a parametric x-y plot using ``x_component`` / ``y_component``
    column indices (default 0 vs 1). ``panel_types`` overrides the per-file
    auto-detection. The PNG is
    written to ``output_file`` (parent dirs created) and only the path plus
    compact per-panel metadata is returned — **never image bytes or bulk arrays**.

    Requires ``spedas-agent-kit[analysis]`` for ``matplotlib`` (rendering uses the
    headless ``Agg`` backend and never opens a display or fetches remote data).
    """
    # --- Argument validation (before any backend import) --------------------
    if not input_files:
        return _error("input_files must be a non-empty list of artifact paths")
    if isinstance(input_files, str):
        return _error("input_files must be a list of paths, not a single string")

    if not output_file or not str(output_file).strip():
        return _error("output_file must be a non-empty PNG path")
    out_path = Path(output_file)
    if out_path.suffix.lower() != ".png":
        return _error(
            f"output_file must have a .png extension; got '{out_path.suffix}'",
            code="invalid_argument",
        )

    if not (_MIN_SIZE_IN <= xsize <= _MAX_SIZE_IN):
        return _error(
            f"xsize must be between {_MIN_SIZE_IN} and {_MAX_SIZE_IN} inches; got {xsize}"
        )
    if ysize is not None and not (_MIN_SIZE_IN <= ysize <= _MAX_SIZE_IN):
        return _error(
            f"ysize must be between {_MIN_SIZE_IN} and {_MAX_SIZE_IN} inches; got {ysize}"
        )
    if not (_MIN_DPI <= dpi <= _MAX_DPI):
        return _error(f"dpi must be between {_MIN_DPI} and {_MAX_DPI}; got {dpi}")

    n_panels = len(input_files)
    panels_resolved, err = _normalize_panel_types(panel_types, n_panels)
    if err is not None:
        return err

    bounds, err = _parse_trange(trange)
    if err is not None:
        return err

    ylog_flags, err = _broadcast_logflags(ylog, n_panels, "ylog")
    if err is not None:
        return err
    zlog_flags, err = _broadcast_logflags(zlog, n_panels, "zlog")
    if err is not None:
        return err
    x_components, err = _broadcast_components(x_component, n_panels, "x_component")
    if err is not None:
        return err
    y_components, err = _broadcast_components(y_component, n_panels, "y_component")
    if err is not None:
        return err

    # Resolve final figure height: default 2.5 in per panel, clamped.
    fig_h = ysize if ysize is not None else min(_MAX_SIZE_IN, max(_MIN_SIZE_IN, 2.5 * n_panels))
    if xsize * dpi > _MAX_PIXELS_PER_DIM or fig_h * dpi > _MAX_PIXELS_PER_DIM:
        return _error(
            f"requested canvas exceeds {_MAX_PIXELS_PER_DIM}px per dimension "
            f"(xsize*dpi={int(xsize * dpi)}, ysize*dpi={int(fig_h * dpi)}); "
            "reduce xsize/ysize or dpi",
            code="invalid_argument",
        )

    # --- Verify inputs exist before importing the heavy backend -------------
    paths: list[Path] = []
    for f in input_files:
        p = Path(f)
        if not p.exists():
            return _error(f"input file does not exist: {f}", code="resource_not_found")
        paths.append(p)

    try:
        require_matplotlib()
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    # --- Load every artifact into a normalized panel descriptor -------------
    try:
        import numpy as np

        panels: list[dict[str, Any]] = []
        for path, ptype in zip(paths, panels_resolved):
            panel = _load_artifact(path, ptype, x_components[len(panels)], y_components[len(panels)])
            panel["file"] = str(path)
            panels.append(panel)
    except ValueError as exc:
        return _error(str(exc), code="invalid_argument")

    # Apply trange filtering and validate log-scaling requests per panel.
    empty_after_filter: list[str] = []
    for idx, panel in enumerate(panels):
        if bounds is not None:
            filtered = _apply_trange(panel, bounds)
            time = np.asarray(filtered["time"], dtype="float64")
            if time.size == 0 or not ((time >= bounds[0]) & (time <= bounds[1])).any():
                empty_after_filter.append(panel["file"])
            else:
                panels[idx] = filtered
                panel = filtered

        if panel["kind"] == _PANEL_SCATTER and (ylog_flags[idx] or zlog_flags[idx]):
            return _error(
                f"log scaling is not supported for scatter/xy panel {idx}; "
                "use linear components or pre-transform the input matrix",
                code="invalid_argument",
                panel_index=idx,
            )
        if panel["kind"] == _PANEL_LINE and ylog_flags[idx]:
            vr = panel.get("value_range")
            if vr is not None and vr[0] <= 0:
                return _error(
                    f"ylog requested for panel {idx} but its values include "
                    f"non-positive numbers (min={vr[0]}); a log y-axis is undefined",
                    code="invalid_argument",
                    panel_index=idx,
                )
        if panel["kind"] == _PANEL_SPECTROGRAM and zlog_flags[idx]:
            vr = panel.get("value_range")
            if vr is not None and vr[1] <= 0:
                return _error(
                    f"zlog requested for panel {idx} but its values are all "
                    f"non-positive (max={vr[1]}); a log color scale is undefined",
                    code="invalid_argument",
                    panel_index=idx,
                )

    if empty_after_filter and len(empty_after_filter) == n_panels:
        return _error(
            "the requested trange excludes all samples from every input file",
            code="invalid_argument",
            trange=[bounds[0], bounds[1]] if bounds else None,
        )

    # --- Render -------------------------------------------------------------
    out_path.parent.mkdir(parents=True, exist_ok=True)
    panel_meta = _draw_figure(
        panels,
        out_path,
        xsize=float(xsize),
        ysize=float(fig_h),
        dpi=int(dpi),
        ylog_flags=ylog_flags,
        zlog_flags=zlog_flags,
    )

    # Overall actual time range across rendered panels.
    all_times = [np.asarray(p["time"], dtype="float64") for p in panels if np.asarray(p["time"]).size]
    actual_trange = _finite_range(np.concatenate(all_times)) if all_times else None

    result: dict[str, Any] = {
        "status": "success",
        "tool": "render_tplot",
        "output_file": str(out_path),
        "n_panels": n_panels,
        "trange": {
            "requested": [bounds[0], bounds[1]] if bounds else None,
            "actual": actual_trange,
        },
        "size_px": [int(round(xsize * dpi)), int(round(fig_h * dpi))],
        "dpi": int(dpi),
        "panels": panel_meta,
        "note": (
            "Rendered a stacked multi-panel PNG to output_file (one panel per "
            "input). This tool returns the path plus compact per-panel metadata "
            "only; the image bytes are never inlined."
        ),
    }
    if empty_after_filter:
        result["warnings"] = [
            {
                "code": "empty_after_trange",
                "message": "trange excluded all samples for these inputs; "
                "they were rendered unfiltered",
                "files": empty_after_filter,
            }
        ]
    return result


def _draw_figure(
    panels: list[dict[str, Any]],
    out_path: Path,
    *,
    xsize: float,
    ysize: float,
    dpi: int,
    ylog_flags: list[bool],
    zlog_flags: list[bool],
) -> list[dict[str, Any]]:
    """Draw the stacked panels with Matplotlib (Agg) and save the PNG.

    Returns compact per-panel metadata (type/file/shape/value_range/axis_range).
    Kept separate from :func:`render_tplot` so all validation stays backend-free
    and testable, and so the figure is always closed.
    """
    import matplotlib

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.colors import LogNorm

    n = len(panels)
    has_scatter = any(panel["kind"] == _PANEL_SCATTER for panel in panels)
    fig, axes = plt.subplots(n, 1, figsize=(xsize, ysize), squeeze=False, sharex=not has_scatter)
    axes = [row[0] for row in axes]

    meta: list[dict[str, Any]] = []
    try:
        for idx, (panel, ax) in enumerate(zip(panels, axes)):
            entry: dict[str, Any] = {
                "index": idx,
                "type": panel["kind"],
                "file": panel["file"],
                "shape": panel.get("shape"),
                "value_range": panel.get("value_range"),
                "time_range": _finite_range(panel["time"]),
            }
            if panel["kind"] == _PANEL_SPECTROGRAM:
                _draw_spectrogram(fig, ax, panel, zlog_flags[idx], LogNorm, mdates)
                entry["axis_range"] = _finite_range(panel["yaxis"])
                entry["zlog"] = bool(zlog_flags[idx])
                # Surface the resolved axis/colorbar labels so callers can see
                # the artifact was self-describing (issue #150).
                entry["axis_label"] = _axis_ylabel(panel)
                if panel.get("value_label"):
                    entry["value_label"] = panel["value_label"]
            elif panel["kind"] == _PANEL_SCATTER:
                _draw_scatter(ax, panel)
                entry["components"] = panel.get("components")
                entry["matrix_key"] = panel.get("matrix_key")
                entry["x_range"] = panel.get("x_range")
                entry["y_range"] = panel.get("y_range")
                entry["has_time_axis"] = bool(panel.get("has_time_axis"))
                # Surface any embedded/sidecar labels (issue #154). The scatter
                # axes are labeled by column, so this is descriptive metadata
                # only and does not override the x/y tick labels.
                if panel.get("axis_label") or panel.get("axis_units"):
                    entry["axis_label"] = _axis_ylabel(panel)
                if panel.get("value_label"):
                    entry["value_label"] = panel["value_label"]
            else:
                _draw_line(ax, panel, ylog_flags[idx], mdates)
                entry["ylog"] = bool(ylog_flags[idx])
                entry["n_series"] = len(panel.get("series", []))
                # Surface the resolved y-axis label (embedded/sidecar or stem),
                # mirroring the spectrogram branch (issue #154).
                entry["axis_label"] = _axis_ylabel(panel)
                if panel.get("value_label"):
                    entry["value_label"] = panel["value_label"]
            if panel["kind"] == _PANEL_SPECTROGRAM:
                # Prefer the embedded axis label/units; fall back to the stem.
                ax.set_ylabel(_axis_ylabel(panel), fontsize=8)
            elif panel["kind"] != _PANEL_SCATTER:
                # Line panels: prefer embedded/sidecar labels, else the stem.
                ax.set_ylabel(_axis_ylabel(panel), fontsize=8)
            meta.append(entry)

        if has_scatter:
            for ax, panel in zip(axes, panels):
                if panel["kind"] != _PANEL_SCATTER:
                    _format_time_axis(ax, mdates)
                    ax.set_xlabel("time (UT)")
        else:
            _format_time_axis(axes[-1], mdates)
            axes[-1].set_xlabel("time (UT)")
        fig.tight_layout()
        fig.savefig(out_path, dpi=dpi, format="png")
    finally:
        plt.close(fig)
    return meta


def _unix_seconds_to_mpl_dates(time: Any, mdates: Any) -> Any:
    """Convert Unix-second samples to Matplotlib date coordinates in UTC.

    ``render_tplot`` keeps all returned metadata and exported machine-readable
    artifacts in Unix seconds, but the rendered x-axis should use Matplotlib's
    date unit system so tick labels are human-readable UT timestamps instead of
    raw epoch-second offsets. Non-finite samples are preserved as NaN gaps.
    """
    import numpy as np

    seconds = np.asarray(time, dtype="float64")
    converted = np.full(seconds.shape, np.nan, dtype="float64")
    finite = np.isfinite(seconds)
    if finite.any():
        converted[finite] = mdates.date2num(
            [datetime.fromtimestamp(float(value), tz=timezone.utc) for value in seconds[finite]]
        )
    return converted


def _format_time_axis(ax: Any, mdates: Any) -> None:
    """Apply a compact UTC date locator/formatter to the shared x-axis."""
    locator = mdates.AutoDateLocator(minticks=3, maxticks=8, tz=timezone.utc)
    ax.xaxis.set_major_locator(locator)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M\n%m-%d", tz=timezone.utc))


def _draw_line(ax: Any, panel: dict[str, Any], ylog: bool, mdates: Any) -> None:
    """Draw a (possibly multi-series) line panel."""
    time = _unix_seconds_to_mpl_dates(panel["time"], mdates)
    labels = panel.get("labels") or [f"series{i}" for i in range(len(panel["series"]))]
    for series, label in zip(panel["series"], labels):
        ax.plot(time, series, linewidth=0.8, label=str(label))
    if ylog:
        ax.set_yscale("log")
    if len(panel["series"]) > 1:
        ax.legend(fontsize=6, loc="upper right", ncol=2)


def _draw_scatter(ax: Any, panel: dict[str, Any]) -> None:
    """Draw a parametric x-y / hodogram panel from two selected columns."""
    x = panel["x"]
    y = panel["y"]
    labels = panel.get("labels") or ["x", "y"]
    # Use both a thin connecting path and small points: the path preserves
    # temporal ordering visually, while points make sparse samples visible.
    ax.plot(x, y, linewidth=0.6, alpha=0.8)
    ax.scatter(x, y, s=8, alpha=0.8)
    ax.set_xlabel(str(labels[0]))
    ax.set_ylabel(str(labels[1]))


def _draw_spectrogram(
    fig: Any, ax: Any, panel: dict[str, Any], zlog: bool, log_norm: Any, mdates: Any
) -> None:
    """Draw a spectrogram panel (pcolormesh + colorbar)."""
    import numpy as np

    time = _unix_seconds_to_mpl_dates(panel["time"], mdates)
    yaxis = np.asarray(panel["yaxis"], dtype="float64")
    z = np.asarray(panel["z"], dtype="float64")  # (n_time, n_y)

    norm = None
    if zlog:
        positive = z[np.isfinite(z) & (z > 0)]
        if positive.size:
            norm = log_norm(vmin=float(positive.min()), vmax=float(positive.max()))

    # pcolormesh expects z as (n_y, n_time) with matching axis coordinates.
    mesh = ax.pcolormesh(time, yaxis, z.T, shading="auto", norm=norm)
    # Label the colorbar from the embedded flux/z label when present (issue
    # #150); older artifacts without it get an unlabeled colorbar as before.
    value_label = panel.get("value_label")
    if value_label:
        fig.colorbar(mesh, ax=ax, pad=0.01, label=str(value_label))
    else:
        fig.colorbar(mesh, ax=ax, pad=0.01)


__all__ = ["render_tplot"]
