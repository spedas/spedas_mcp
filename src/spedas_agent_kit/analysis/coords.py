"""Phase-1 coordinate-transform analysis tools (pyspedas cotrans backend).

These functions implement the SPEDAS Agent Kit Phase-1 coordinate tools:

- :func:`transform_timeseries_coordinates` (#12) - transform an Nx3 vector
  time-series between GSE/GSM/SM/GEI/GEO/MAG/J2000 (``pyspedas`` ``cotrans``).
- :func:`generate_fac_matrix` (#13) - build per-sample field-aligned-coordinate
  3x3 rotation matrices from a magnetic-field series (``fac_matrix_make``).
- :func:`analyze_minvar_coordinates` (#14) - minimum-variance analysis / LMN
  boundary-normal frame from a vector series (``minvar`` / ``minvar_matrix_make``).
- :func:`tvector_rotate` (#97) - apply a saved per-sample ``(N, 3, 3)``
  rotation-matrix stack to an ``Nx3`` vector series (IDL/PySPEDAS tvector_rotate
  equivalent last step).

Design contract (see roadmap epic #5/#6):

- **File-in / file-out.** Inputs are paths to fetched CSV/JSON artifacts; bulk
  outputs are written to ``output_file``/``output_dir``. Returns are small,
  JSON-serializable dicts with ``status``, output paths, and compact summaries.
  Full arrays are never returned inline.
- **Lazy backend.** ``pyspedas`` is imported only inside these functions via
  :func:`spedas_agent_kit.analysis.require_pyspedas`; a missing ``[analysis]`` extra
  yields a clean ``status="error"`` payload.
- **No network.** All computation is local; the tools never download data.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import AnalysisDependencyError, require_pyspedas

# Coordinate frames supported by pyspedas cotrans (cotrans_lib.subcotrans). These
# are geocentric / near-Earth frames; this tool deliberately does not implement
# heliospheric RTN/spacecraft-frame rotations.
SUPPORTED_FRAMES = ("gse", "gsm", "sm", "gei", "geo", "mag", "j2000")
UNSUPPORTED_HELIOSPHERIC_FRAMES = ("rtn", "rtp", "sc", "spacecraft", "srf")
EARTH_FRAME_DOMAIN_NOTE = (
    "transform_timeseries_coordinates uses pyspedas cotrans geophysical Earth-frame "
    "rotations (GSE/GSM/SM/GEI/GEO/MAG/J2000). It is not valid for heliospheric "
    "RTN/RTP or instrument/spacecraft-frame vectors such as PSP/Solar Orbiter MAG "
    "products unless those vectors were first converted into a supported Earth frame "
    "with explicit provenance."
)

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


def _candidate_sidecars(input_path: Path) -> list[Path]:
    """Return sidecar filenames that may carry fetch/data provenance."""
    return [
        input_path.with_suffix(input_path.suffix + ".provenance.json"),
        input_path.with_suffix(input_path.suffix + ".metadata.json"),
        input_path.with_suffix(".provenance.json"),
        input_path.with_suffix(".metadata.json"),
    ]


def _frame_from_text(text: str | None) -> str | None:
    """Best-effort frame inference from dataset IDs, filenames, or column names."""
    if not text:
        return None
    import re

    lowered = text.lower()
    # Match frame-like tokens at separators/boundaries. This intentionally avoids
    # guessing plain "mag" as MAG, because mission/product names often contain it
    # as an instrument noun rather than a coordinate frame.
    for frame in ("rtn", "rtp", "gse", "gsm", "gei", "geo", "j2000", "sm", "sc", "srf"):
        if re.search(rf"(?<![a-z0-9]){re.escape(frame)}(?![a-z0-9])", lowered):
            return "spacecraft" if frame in {"sc", "srf"} else frame
        if re.search(rf"[_./-]{re.escape(frame)}([_./-]|$)", lowered):
            return "spacecraft" if frame in {"sc", "srf"} else frame
    return None


def _load_frame_provenance(input_file: str, vector_cols: list[str] | None = None) -> dict[str, Any] | None:
    """Load/infer source coordinate-frame provenance for a fetched artifact.

    This is deliberately conservative: it only returns a frame when the sidecar,
    dataset/file name, or vector column names contain an explicit frame token such
    as ``RTN``/``GSE``/``GSM``/``SC``. Unknown provenance remains ``None`` so generic
    user CSVs are not blocked.
    """
    path = Path(input_file)
    evidence: dict[str, Any] = {}
    for sidecar in _candidate_sidecars(path):
        if not sidecar.exists():
            continue
        try:
            payload = json.loads(sidecar.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, dict):
            frame = payload.get("coordinate_frame") or payload.get("source_frame")
            if isinstance(frame, str) and frame.strip():
                return {"frame": frame.strip().lower(), "source": "sidecar", "sidecar": str(sidecar), "provenance": payload}
            for key in ("dataset_id", "product_id", "source_dataset", "parameters"):
                candidate = payload.get(key)
                frame = _frame_from_text(json.dumps(candidate, default=str))
                if frame:
                    return {"frame": frame, "source": f"sidecar.{key}", "sidecar": str(sidecar), "provenance": payload}
            evidence["sidecar"] = str(sidecar)

    for label, text in (
        ("filename", path.name),
        ("parent", path.parent.name),
        ("vector_cols", " ".join(vector_cols or [])),
    ):
        frame = _frame_from_text(text)
        if frame:
            return {"frame": frame, "source": label, **evidence}
    return None


def _provenance_frame_guard(input_file: str, coord_in_l: str, vector_cols: list[str] | None = None) -> dict[str, Any] | None:
    """Return a structured error if source-frame provenance contradicts coord_in."""
    prov = _load_frame_provenance(input_file, vector_cols)
    if prov is None:
        return None
    frame = str(prov.get("frame", "")).lower()
    if frame in UNSUPPORTED_HELIOSPHERIC_FRAMES:
        return _error(
            f"input artifact appears to be in unsupported heliospheric/spacecraft frame '{frame}', "
            f"but coord_in='{coord_in_l}' requests an Earth-frame cotrans rotation",
            hint=EARTH_FRAME_DOMAIN_NOTE,
            supported_frames=list(SUPPORTED_FRAMES),
            unsupported_heliospheric_frames=list(UNSUPPORTED_HELIOSPHERIC_FRAMES),
            input_frame_provenance=prov,
        )
    if frame in SUPPORTED_FRAMES and frame != coord_in_l:
        return _error(
            f"coord_in='{coord_in_l}' does not match input artifact frame provenance '{frame}'",
            hint="Pass the true coord_in from the artifact provenance or regenerate the input with explicit frame metadata.",
            supported_frames=list(SUPPORTED_FRAMES),
            input_frame_provenance=prov,
        )
    return None


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


def _load_matrix_stack(matrix_file: str) -> tuple[Any, dict[str, Any]]:
    """Read a saved ``(N, 3, 3)`` rotation-matrix stack from ``.npy``/``.npz``.

    ``generate_fac_matrix`` writes ``fac_matrix`` for its ``.npz`` output, while
    sliding-window MVA writes ``matrices``.  Accept those keys first; otherwise
    use the single 3-D array in the archive when it is unambiguous.  The optional
    ``time`` array is returned as metadata only; row matching remains strict and
    is checked by the caller.
    """
    import numpy as np

    path = Path(matrix_file)
    if not path.exists():
        raise ValueError(f"matrix file does not exist: {matrix_file}")
    suffix = path.suffix.lower()
    metadata: dict[str, Any] = {"matrix_file": str(path)}
    if suffix == ".npz":
        with np.load(path) as data:
            keys = list(data.files)
            metadata["matrix_file_keys"] = keys
            selected = None
            for key in ("fac_matrix", "matrices", "matrix"):
                if key in data:
                    selected = key
                    break
            if selected is None:
                candidates = [k for k in keys if np.asarray(data[k]).ndim == 3]
                if len(candidates) != 1:
                    raise ValueError(
                        "could not identify a unique 3-D matrix stack in npz; "
                        "expected key 'fac_matrix' or 'matrices'"
                    )
                selected = candidates[0]
            matrices = np.array(data[selected], dtype="float64", copy=True)
            metadata["matrix_key"] = selected
            if "time" in data:
                metadata["matrix_time_rows"] = int(np.asarray(data["time"]).shape[0])
    elif suffix == ".npy":
        matrices = np.array(np.load(path), dtype="float64", copy=True)
        metadata["matrix_key"] = None
    else:
        raise ValueError("matrix_file must be a .npy or .npz artifact")

    if matrices.ndim != 3 or matrices.shape[1:] != (3, 3):
        raise ValueError(f"matrix stack must have shape (N, 3, 3), got {matrices.shape}")
    if matrices.shape[0] == 0:
        raise ValueError("matrix stack contains no rows")
    return matrices, metadata


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
        extra = {}
        hint = None
        if coord_in_l in UNSUPPORTED_HELIOSPHERIC_FRAMES:
            hint = EARTH_FRAME_DOMAIN_NOTE
            extra["unsupported_heliospheric_frames"] = list(UNSUPPORTED_HELIOSPHERIC_FRAMES)
        return _error(
            f"unsupported coord_in '{coord_in}'",
            hint=hint,
            supported_frames=list(SUPPORTED_FRAMES),
            **extra,
        )
    if coord_out_l not in SUPPORTED_FRAMES:
        extra = {}
        hint = None
        if coord_out_l in UNSUPPORTED_HELIOSPHERIC_FRAMES:
            hint = EARTH_FRAME_DOMAIN_NOTE
            extra["unsupported_heliospheric_frames"] = list(UNSUPPORTED_HELIOSPHERIC_FRAMES)
        return _error(
            f"unsupported coord_out '{coord_out}'",
            hint=hint,
            supported_frames=list(SUPPORTED_FRAMES),
            **extra,
        )

    guard = _provenance_frame_guard(input_file, coord_in_l, vector_cols)
    if guard is not None:
        return guard

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
        "domain_note": EARTH_FRAME_DOMAIN_NOTE,
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

    position_metadata: dict[str, Any] = {
        "mag_rows": int(mag_vectors.shape[0]),
        "position_interpolated": False,
    }
    position_warnings: list[str] = []
    if pos_file and pos_time is not None and pos_vectors is not None:
        pos_rows = int(pos_vectors.shape[0])
        mag_rows = int(mag_vectors.shape[0])
        same_grid = bool(
            pos_rows == mag_rows
            and np.allclose(pos_time, mag_time, rtol=0.0, atol=1e-9, equal_nan=True)
        )
        position_interpolated = not same_grid
        position_metadata.update(
            {
                "pos_rows_in": pos_rows,
                "position_time_grid_matches_mag": same_grid,
                "position_interpolated": position_interpolated,
            }
        )
        if pos_rows > 0:
            position_metadata["position_upsample_ratio"] = float(mag_rows / pos_rows)
        if position_interpolated:
            detail = (
                f"position time grid differs from magnetic-field time grid; "
                f"pyspedas fac_matrix_make will align/interpolate position data "
                f"from {pos_rows} samples to {mag_rows} magnetic samples"
            )
            position_metadata["position_alignment_note"] = detail
            if pos_rows == 0:
                position_warnings.append(
                    "position file contains no rows; FAC position alignment cannot be validated"
                )
            elif mag_rows / pos_rows > 2.0:
                position_warnings.append(
                    f"position series is sparse relative to magnetic field "
                    f"({pos_rows} position rows for {mag_rows} magnetic rows; "
                    f"{mag_rows / pos_rows:.2f}x upsampling before FAC generation)"
                )
            else:
                position_warnings.append(detail)

    from pyspedas.cotrans_tools.fac_matrix_make import fac_matrix_make
    from pyspedas.tplot_tools import del_data, get_data, set_coords, store_data

    mag_var = "_spedas_agent_kit_fac_mag"
    pos_var = "_spedas_agent_kit_fac_pos"
    out_var = "_spedas_agent_kit_fac_mat"
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

    response = {
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
    response.update(position_metadata)
    if position_metadata.get("position_alignment_note"):
        response["note"] = f"{response['note']} {position_metadata['position_alignment_note']}."
    if position_warnings:
        response["warnings"] = position_warnings
    return response


def tvector_rotate(
    vector_file: str,
    matrix_file: str,
    output_file: str,
    time_col: str = "time",
    vector_cols: list[str] | None = None,
    output_cols: list[str] | None = None,
) -> dict[str, Any]:
    """Apply an ``(N,3,3)`` rotation-matrix stack to an ``Nx3`` vector series (#97).

    This is the file-in/file-out counterpart of IDL/PySPEDAS ``tvector_rotate``:
    each output row is ``matrix[i] @ vector[i]``.  It closes the workflow loop for
    matrix artifacts emitted by :func:`generate_fac_matrix` (``fac_matrix`` key)
    and sliding-window :func:`analyze_minvar_coordinates` (``matrices`` key).
    The matrix stack and vector series must already be on the same cadence/time
    grid; this utility deliberately rejects row-count mismatches instead of
    silently interpolating.
    """
    try:
        import numpy as np
        import pandas as pd

        unix_time, vectors, resolved = _load_time_and_vectors(
            vector_file, time_col=time_col, vector_cols=vector_cols
        )
        matrices, matrix_metadata = _load_matrix_stack(matrix_file)
    except ValueError as exc:
        return _error(str(exc))

    if vectors.shape != (vectors.shape[0], 3):
        return _error(f"vector series must have shape (N, 3), got {vectors.shape}")
    if matrices.shape[0] != vectors.shape[0]:
        return _error(
            "matrix stack row count must match vector row count; "
            f"got {matrices.shape[0]} matrices for {vectors.shape[0]} vectors",
            matrix_rows=int(matrices.shape[0]),
            vector_rows=int(vectors.shape[0]),
        )

    cols = output_cols or ["rot_x", "rot_y", "rot_z"]
    if len(cols) != 3:
        return _error(f"output_cols must list exactly 3 columns, got {len(cols)}")

    rotated = np.einsum("nij,nj->ni", matrices, vectors)

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_df = pd.DataFrame({"time": unix_time})
    for i, col in enumerate(cols):
        out_df[col] = rotated[:, i]
    if out_path.suffix.lower() == ".json":
        out_path.write_text(out_df.to_json(orient="columns"), encoding="utf-8")
    else:
        out_df.to_csv(out_path, index=False)

    return {
        "status": "success",
        "tool": "tvector_rotate",
        "output_file": str(out_path),
        "rows": int(rotated.shape[0]),
        "matrix_shape": list(matrices.shape),
        "input_vector_cols": resolved,
        "output_vector_cols": cols,
        "summary": _component_summary(rotated),
        "note": "Applied each rotation as matrix[i] @ vector[i]; inputs must be pre-aligned on the same time grid.",
        **matrix_metadata,
    }


def analyze_minvar_coordinates(
    input_file: str,
    output_dir: str | None = None,
    twindow: float | None = None,
    tslide: float | None = None,
    time_col: str = "time",
    vector_cols: list[str] | None = None,
    output_file: str | None = None,
) -> dict[str, Any]:
    """Minimum-variance analysis / LMN boundary-normal frame (#14).

    Backend: ``pyspedas.cotrans_tools.minvar`` for the full-interval mode and
    ``minvar_matrix_make`` for sliding windows.

    Full-interval mode (``twindow is None``) writes the rotated Nx3 series to
    ``output_file`` when supplied, otherwise to ``output_dir/minvar_rotated.csv``,
    and returns eigenvalues, eigenvectors, the normal vector, and the
    intermediate/minimum eigenvalue ratio as small tables. Sliding-window mode
    writes the per-window rotation matrices to ``output_file`` when supplied,
    otherwise to ``output_dir/minvar_matrices.npz``. ``output_file`` is accepted
    as a compatibility alias for users following the single-artifact convention;
    ``output_dir`` remains supported for existing callers.
    """
    if output_file is None and output_dir is None:
        return _error(
            "analyze_minvar_coordinates requires either output_file or output_dir",
            hint=(
                "Use output_file for a single explicit artifact path, or output_dir "
                "to keep the default minvar_rotated.csv/minvar_matrices.npz name."
            ),
        )
    if output_file is not None and output_dir is not None:
        return _error(
            "provide only one of output_file or output_dir",
            hint="Choose output_file for an explicit artifact path or output_dir for the default filename.",
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

    if output_file is not None:
        out_path = Path(output_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_dir = out_path.parent
    else:
        out_dir = Path(output_dir or "")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = None

    if twindow is None:
        from pyspedas.cotrans_tools.minvar import minvar

        vrot, eigvecs, eigvals = minvar(vectors)
        vrot = np.asarray(vrot, dtype="float64")
        eigvecs = np.asarray(eigvecs, dtype="float64")
        eigvals = np.asarray(eigvals, dtype="float64")

        rotated_path = out_path if out_path is not None else out_dir / "minvar_rotated.csv"
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
            "output_file": str(rotated_path),
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

    in_var = "_spedas_agent_kit_mva_in"
    mat_var = "_spedas_agent_kit_mva_mat"
    ev_var = "_spedas_agent_kit_mva_eig"
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

    matrices_path = out_path if out_path is not None else out_dir / "minvar_matrices.npz"
    save_kwargs = {"time": mat_times, "matrices": matrices}
    if eigvals is not None:
        save_kwargs["eigenvalues"] = eigvals
    np.savez(matrices_path, **save_kwargs)

    return {
        "status": "success",
        "tool": "analyze_minvar_coordinates",
        "mode": "sliding_window",
        "matrices_file": str(matrices_path),
        "output_file": str(matrices_path),
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
    "tvector_rotate",
    "analyze_minvar_coordinates",
]
