"""Phase-1 coordinate-transform analysis tools (pyspedas cotrans backend).

These functions implement the SPEDAS MCP Phase-1 coordinate tools:

- :func:`transform_timeseries_coordinates` (#12) - transform an Nx3 vector
  time-series between GSE/GSM/SM/GEI/GEO/MAG/J2000 (``pyspedas`` ``cotrans``).
- :func:`generate_fac_matrix` (#13) - build per-sample field-aligned-coordinate
  3x3 rotation matrices from a magnetic-field series (``fac_matrix_make``).
- :func:`analyze_minvar_coordinates` (#14) - minimum-variance analysis / LMN
  boundary-normal frame from a vector series (``minvar`` / ``minvar_matrix_make``).

Design contract (see roadmap epic #5/#6):

- **File-in / file-out.** Inputs are paths to fetched CSV/JSON artifacts; bulk
  outputs are written to ``output_file``/``output_dir``. Returns are small,
  JSON-serializable dicts with ``status``, output paths, and compact summaries.
  Full arrays are never returned inline.
- **Lazy backend.** ``pyspedas`` is imported only inside these functions via
  :func:`spedas_mcp.analysis.require_pyspedas`; a missing ``[analysis]`` extra
  yields a clean ``status="error"`` payload.
- **No network.** All computation is local; the tools never download data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import AnalysisDependencyError, require_pyspedas

# Coordinate frames supported by pyspedas cotrans (cotrans_lib.subcotrans).
SUPPORTED_FRAMES = ("gse", "gsm", "sm", "gei", "geo", "mag", "j2000")

# FAC reference modes supported by pyspedas fac_matrix_make, and the subset that
# additionally requires a spacecraft-position series.
FAC_MODES = (
    "xgse",
    "rgeo",
    "mrgeo",
    "phigeo",
    "mphigeo",
    "phism",
    "mphism",
    "ygsm",
)
FAC_MODES_REQUIRING_POS = ("rgeo", "mrgeo", "phigeo", "mphigeo", "phism", "mphism")


def _error(
    message: str,
    *,
    code: str = "invalid_argument",
    hint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the uniform structured error payload for analysis tools.

    Mirrors the server's ``_error_response`` envelope so analysis errors share the
    same ``{status: "error", code, message, ...}`` contract as every other
    user-facing tool error (issue #27) instead of the legacy
    ``{status, error}`` shape. The server wraps these dicts with ``_json`` and the
    ``_safe_tool`` size guard; truly-unexpected exceptions are converted to the
    same envelope by ``_safe_tool``'s exception handler.
    """
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint is not None:
        payload["hint"] = hint
    payload.update(extra)
    return payload


def _load_time_and_vectors(
    input_file: str,
    time_col: str = "time",
    vector_cols: list[str] | None = None,
) -> tuple[Any, Any, list[str]]:
    """Read a time array (Unix seconds) and an Nx3 vector array from an artifact.

    Supports the CSV/JSON shapes written by the data-layer ``fetch_*`` tools as
    well as generic CSVs that carry an explicit time column plus three numeric
    vector columns.

    Returns ``(unix_time_ndarray, nx3_ndarray, resolved_vector_columns)``.

    Raises
    ------
    ValueError
        If the file cannot be parsed into a time array and exactly three vector
        columns.
    """
    import numpy as np
    import pandas as pd

    path = Path(input_file)
    if not path.exists():
        raise ValueError(f"input file does not exist: {input_file}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON input must be an object mapping column -> list")
        df = pd.DataFrame(payload)
    else:
        # CSV: the data-layer writes the DatetimeIndex as the first unnamed
        # column. read_csv then exposes it as "Unnamed: 0" or the index name.
        df = pd.read_csv(path)

    if df.empty:
        raise ValueError("input file contains no rows")

    # Resolve the time column: prefer the named column, else fall back to the
    # first column (the data layer writes the DatetimeIndex as the first,
    # often "Unnamed: 0", column).
    if time_col in df.columns:
        time_series = df[time_col]
    elif len(df.columns) >= 1:
        time_series = df[df.columns[0]]
    else:
        raise ValueError(
            f"could not find time column '{time_col}'; available columns: {list(df.columns)}"
        )

    # Convert times to Unix seconds. Numeric values are assumed to already be
    # Unix seconds; otherwise parse as datetimes.
    if pd.api.types.is_numeric_dtype(time_series):
        unix_time = time_series.to_numpy(dtype="float64")
    else:
        parsed = pd.to_datetime(time_series, utc=True, errors="coerce")
        if parsed.isna().all():
            raise ValueError("time column could not be parsed as numeric or datetime")
        unix_time = parsed.astype("int64").to_numpy() / 1e9

    # Resolve the three vector columns.
    if vector_cols is None:
        candidate_cols = [
            c
            for c in df.columns
            if c != time_series.name
            and pd.api.types.is_numeric_dtype(df[c])
        ]
        if len(candidate_cols) < 3:
            raise ValueError(
                "could not auto-detect 3 numeric vector columns; pass vector_cols "
                f"explicitly. numeric columns found: {candidate_cols}"
            )
        resolved = candidate_cols[:3]
    else:
        missing = [c for c in vector_cols if c not in df.columns]
        if missing:
            raise ValueError(
                f"vector_cols not found in input: {missing}; available: {list(df.columns)}"
            )
        if len(vector_cols) != 3:
            raise ValueError(f"vector_cols must list exactly 3 columns, got {len(vector_cols)}")
        resolved = list(vector_cols)

    vectors = df[resolved].to_numpy(dtype="float64")
    # pandas' single-column ``Series.to_numpy`` can return a read-only view into
    # the underlying block. pyspedas ``store_data`` scrubs non-finite timestamps
    # in place (``times[cond] = 0``), which raises ``assignment destination is
    # read-only`` on such a view (issue #58). Force writeable, owned copies of
    # both arrays we hand to the backend so the in-place write always succeeds.
    unix_time = np.array(unix_time, dtype="float64", copy=True)
    vectors = np.array(vectors, dtype="float64", copy=True)
    return unix_time, vectors, resolved


def _component_summary(array: Any) -> dict[str, list[float]]:
    """Return per-component mean/min/max for an Nx3 array (JSON-friendly)."""
    import numpy as np

    arr = np.asarray(array, dtype="float64")
    with np.errstate(all="ignore"):
        return {
            "mean": [float(np.nanmean(arr[:, i])) for i in range(arr.shape[1])],
            "min": [float(np.nanmin(arr[:, i])) for i in range(arr.shape[1])],
            "max": [float(np.nanmax(arr[:, i])) for i in range(arr.shape[1])],
        }


def transform_timeseries_coordinates(
    input_file: str,
    coord_in: str,
    coord_out: str,
    output_file: str,
    time_col: str = "time",
    vector_cols: list[str] | None = None,
) -> dict[str, Any]:
    """Transform an Nx3 vector time-series between geophysical frames (#12).

    Backend: ``pyspedas.cotrans_tools.cotrans`` (array mode). Writes the
    transformed Nx3 array (with the time column) to ``output_file`` and returns
    paths plus per-component summary stats only.
    """
    coord_in_l = (coord_in or "").strip().lower()
    coord_out_l = (coord_out or "").strip().lower()
    if coord_in_l not in SUPPORTED_FRAMES:
        return _error(
            f"unsupported coord_in '{coord_in}'", supported_frames=list(SUPPORTED_FRAMES)
        )
    if coord_out_l not in SUPPORTED_FRAMES:
        return _error(
            f"unsupported coord_out '{coord_out}'", supported_frames=list(SUPPORTED_FRAMES)
        )

    try:
        pyspedas = require_pyspedas()
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    try:
        import numpy as np
        import pandas as pd

        unix_time, vectors, resolved = _load_time_and_vectors(
            input_file, time_col=time_col, vector_cols=vector_cols
        )
    except ValueError as exc:
        return _error(str(exc))

    from pyspedas.cotrans_tools.cotrans import cotrans

    result = cotrans(
        time_in=unix_time,
        data_in=vectors,
        coord_in=coord_in_l,
        coord_out=coord_out_l,
    )
    # cotrans returns 0 on failure, otherwise the transformed ndarray.
    if isinstance(result, int):
        return _error(
            f"cotrans failed to transform {coord_in_l}->{coord_out_l}; check input data"
        )

    transformed = np.asarray(result, dtype="float64")

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_cols = [f"{coord_out_l}_{axis}" for axis in ("x", "y", "z")]
    out_df = pd.DataFrame({"time": unix_time})
    for i, col in enumerate(out_cols):
        out_df[col] = transformed[:, i]
    if out_path.suffix.lower() == ".json":
        out_path.write_text(out_df.to_json(orient="columns"), encoding="utf-8")
    else:
        out_df.to_csv(out_path, index=False)

    return {
        "status": "success",
        "tool": "transform_timeseries_coordinates",
        "output_file": str(out_path),
        "coord_in": coord_in_l,
        "coord_out": coord_out_l,
        "rows": int(transformed.shape[0]),
        "input_vector_cols": resolved,
        "output_vector_cols": out_cols,
        "summary": _component_summary(transformed),
    }


def generate_fac_matrix(
    mag_file: str,
    output_file: str,
    other_dim: str = "xgse",
    pos_file: str | None = None,
    time_col: str = "time",
    vector_cols: list[str] | None = None,
    mag_coord: str = "gse",
) -> dict[str, Any]:
    """Build per-sample field-aligned-coordinate 3x3 rotation matrices (#13).

    Backend: ``pyspedas.cotrans_tools.fac_matrix_make`` via temporary tplot
    variables. The (N, 3, 3) matrix stack is written to ``output_file`` (``.npy``
    recommended; ``.npz`` also supported) and only shape/mode/path are returned.

    Position-dependent modes (rgeo/mrgeo/phigeo/mphigeo/phism/mphism) require a
    GEI position series via ``pos_file`` and error clearly if it is missing.
    """
    mode = (other_dim or "xgse").strip().lower()
    if mode not in FAC_MODES:
        return _error(
            f"unsupported FAC mode '{other_dim}'", supported_modes=list(FAC_MODES)
        )
    if mode in FAC_MODES_REQUIRING_POS and not pos_file:
        return _error(
            f"FAC mode '{mode}' requires a spacecraft position series; provide pos_file "
            "(position must be in GEI coordinates).",
            modes_requiring_pos=list(FAC_MODES_REQUIRING_POS),
        )

    try:
        pyspedas = require_pyspedas()
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    try:
        import numpy as np

        mag_time, mag_vectors, mag_cols = _load_time_and_vectors(
            mag_file, time_col=time_col, vector_cols=vector_cols
        )
        pos_time = pos_vectors = None
        if pos_file:
            pos_time, pos_vectors, _ = _load_time_and_vectors(
                pos_file, time_col=time_col, vector_cols=None
            )
    except ValueError as exc:
        return _error(str(exc))

    from pyspedas.cotrans_tools.fac_matrix_make import fac_matrix_make
    from pyspedas.tplot_tools import del_data, get_data, set_coords, store_data

    mag_var = "_spedas_mcp_fac_mag"
    pos_var = "_spedas_mcp_fac_pos"
    out_var = "_spedas_mcp_fac_mat"
    created = [mag_var, out_var]
    try:
        store_data(mag_var, data={"x": mag_time, "y": mag_vectors})
        set_coords(mag_var, (mag_coord or "gse").upper())
        pos_arg = None
        if pos_file:
            store_data(pos_var, data={"x": pos_time, "y": pos_vectors})
            set_coords(pos_var, "GEI")
            pos_arg = pos_var
            created.append(pos_var)

        result_name = fac_matrix_make(
            mag_var, other_dim=mode, pos_var_name=pos_arg, newname=out_var
        )
        if result_name is None:
            return _error(
                f"fac_matrix_make failed for mode '{mode}'; verify inputs and coordinates"
            )
        fac_data = get_data(out_var)
        if fac_data is None:
            return _error("fac_matrix_make produced no output matrix")
        matrices = np.asarray(fac_data.y, dtype="float64")
    finally:
        for name in created:
            try:
                del_data(name)
            except Exception:  # pragma: no cover - cleanup best-effort
                pass

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.suffix.lower() == ".npz":
        np.savez(out_path, time=mag_time, fac_matrix=matrices)
    else:
        np.save(out_path, matrices)

    return {
        "status": "success",
        "tool": "generate_fac_matrix",
        "output_file": str(out_path),
        "mode": mode,
        "mag_coord": (mag_coord or "gse").lower(),
        "rows": int(matrices.shape[0]),
        "matrix_shape": list(matrices.shape),
        "mag_vector_cols": mag_cols,
        "used_position": bool(pos_file),
        "note": (
            "FAC rotation matrices stored as an (N, 3, 3) array; rows are the "
            "x/y/z (perp1, perp2, parallel-to-B) FAC axes per sample."
        ),
    }


def analyze_minvar_coordinates(
    input_file: str,
    output_dir: str,
    twindow: float | None = None,
    tslide: float | None = None,
    time_col: str = "time",
    vector_cols: list[str] | None = None,
) -> dict[str, Any]:
    """Minimum-variance analysis / LMN boundary-normal frame (#14).

    Backend: ``pyspedas.cotrans_tools.minvar`` for the full-interval mode and
    ``minvar_matrix_make`` for sliding windows.

    Full-interval mode (``twindow is None``) writes the rotated Nx3 series to
    ``output_dir`` and returns eigenvalues, eigenvectors, the normal vector, and
    the intermediate/minimum eigenvalue ratio as small tables. Sliding-window
    mode writes the per-window rotation matrices to ``output_dir``.
    """
    try:
        pyspedas = require_pyspedas()
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    try:
        import numpy as np
        import pandas as pd

        unix_time, vectors, resolved = _load_time_and_vectors(
            input_file, time_col=time_col, vector_cols=vector_cols
        )
    except ValueError as exc:
        return _error(str(exc))

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if twindow is None:
        from pyspedas.cotrans_tools.minvar import minvar

        vrot, eigvecs, eigvals = minvar(vectors)
        vrot = np.asarray(vrot, dtype="float64")
        eigvecs = np.asarray(eigvecs, dtype="float64")
        eigvals = np.asarray(eigvals, dtype="float64")

        rotated_path = out_dir / "minvar_rotated.csv"
        rot_df = pd.DataFrame(
            {"time": unix_time, "L": vrot[:, 0], "M": vrot[:, 1], "N": vrot[:, 2]}
        )
        rot_df.to_csv(rotated_path, index=False)

        l1, l2, l3 = (float(eigvals[0]), float(eigvals[1]), float(eigvals[2]))
        # Minimum-variance direction (the boundary normal) is the 3rd eigenvector.
        normal = [float(eigvecs[i, 2]) for i in range(3)]
        ratio = float(l2 / l3) if l3 != 0 else None
        return {
            "status": "success",
            "tool": "analyze_minvar_coordinates",
            "mode": "full_interval",
            "rotated_file": str(rotated_path),
            "rows": int(vrot.shape[0]),
            "input_vector_cols": resolved,
            "eigenvalues": [l1, l2, l3],
            "eigenvectors": {
                "maximum": [float(eigvecs[i, 0]) for i in range(3)],
                "intermediate": [float(eigvecs[i, 1]) for i in range(3)],
                "minimum": [float(eigvecs[i, 2]) for i in range(3)],
            },
            "normal_vector": normal,
            "intermediate_to_min_ratio": ratio,
            "windows": 1,
        }

    # Sliding-window mode.
    from pyspedas.cotrans_tools.minvar_matrix_make import minvar_matrix_make
    from pyspedas.tplot_tools import del_data, get_data, store_data

    in_var = "_spedas_mcp_mva_in"
    mat_var = "_spedas_mcp_mva_mat"
    ev_var = "_spedas_mcp_mva_eig"
    created = [in_var, mat_var, ev_var]
    try:
        store_data(in_var, data={"x": unix_time, "y": vectors})
        minvar_matrix_make(
            in_var,
            twindow=twindow,
            tslide=tslide,
            newname=mat_var,
            evname=ev_var,
        )
        mat_data = get_data(mat_var)
        if mat_data is None:
            return _error("minvar_matrix_make produced no rotation matrices")
        matrices = np.asarray(mat_data.y, dtype="float64")
        mat_times = np.asarray(mat_data.times, dtype="float64")
        ev_data = get_data(ev_var)
        eigvals = np.asarray(ev_data.y, dtype="float64") if ev_data is not None else None
    finally:
        for name in created:
            try:
                del_data(name)
            except Exception:  # pragma: no cover - cleanup best-effort
                pass

    matrices_path = out_dir / "minvar_matrices.npz"
    save_kwargs = {"time": mat_times, "matrices": matrices}
    if eigvals is not None:
        save_kwargs["eigenvalues"] = eigvals
    np.savez(matrices_path, **save_kwargs)

    return {
        "status": "success",
        "tool": "analyze_minvar_coordinates",
        "mode": "sliding_window",
        "matrices_file": str(matrices_path),
        "windows": int(matrices.shape[0]),
        "matrix_shape": list(matrices.shape),
        "twindow": float(twindow),
        "tslide": float(tslide) if tslide is not None else None,
        "input_vector_cols": resolved,
    }


__all__ = [
    "SUPPORTED_FRAMES",
    "FAC_MODES",
    "FAC_MODES_REQUIRING_POS",
    "transform_timeseries_coordinates",
    "generate_fac_matrix",
    "analyze_minvar_coordinates",
]
