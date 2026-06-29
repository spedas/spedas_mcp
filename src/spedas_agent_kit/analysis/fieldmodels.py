"""Phase-2 magnetic-field-model / L-shell tools (issues #16, #17).

These functions add the first magnetospheric field-model evaluation and
radiation-belt coordinate tools to the SPEDAS Agent Kit:

- :func:`evaluate_magnetic_field` (#16) - evaluate IGRF / Tsyganenko
  (T89/T96/T01/TS04) B (nT) at an Nx3 GSM position series, with optional
  field-line tracing to the ionosphere or magnetic equator (``pyspedas`` geopack
  ``tigrf`` / ``tt89`` / ``tt96`` / ``tt01`` / ``tts04`` / ``ttrace2endpoint``).
- :func:`calculate_lshell` (#17) - McIlwain L-shell (equatorial field-line apex
  radius, Re) by tracing each position to the magnetic equator, with optional
  ionospheric footprint (``pyspedas`` geopack ``calculate_lshell`` /
  ``ttrace2endpoint``).

Design contract (mirrors :mod:`spedas_agent_kit.analysis.coords` /
:mod:`spedas_agent_kit.analysis.spectral`, roadmap epic #5/#8):

- **File-in / file-out.** The input is a positions artifact (preferably an
  ``.npz`` with an Nx3 ``positions`` array in **GSM, km**, plus an optional
  ``times`` array of Unix seconds; CSV/JSON with three numeric columns are also
  accepted). The bulk per-sample B vectors / footpoints / L series are written to
  a compressed ``.npz``; returns are small, JSON-serializable dicts with
  ``status``, file paths, and compact summary stats only. Full arrays are never
  returned inline (artifact-first discipline).
- **Lazy, gated backends.** ``pyspedas`` (geopack) is imported only inside these
  functions; a missing ``[analysis]`` extra yields a clean
  ``status="error"`` payload.
- **No hidden heavy I/O.** IGRF is cheap and parameter-free. The distorted
  Tsyganenko models (T96/T01/TS04, and T89 without an index) require external
  geomagnetic indices: rather than silently downloading them, these tools require
  the caller to pass the relevant ``parameters`` and return a structured
  ``parameters_required`` error when they are missing. T89 accepts a simple
  ``iopt``/``kp`` and defaults to a quiet ``iopt=2`` only when explicitly chosen.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import AnalysisDependencyError, require_pyspedas

# Field models exposed by these tools, mapped to their geopack tplot wrappers.
# IGRF is the cheap, parameter-free intrinsic field; the Tsyganenko models add an
# external-current correction and need geomagnetic indices.
FIELD_MODELS = ("igrf", "t89", "t96", "t01", "ts04")

# Models that require external geomagnetic parameters (and would otherwise pull
# them from the network). IGRF needs none; T89 needs only a single index
# (iopt/kp) which the caller may pass explicitly.
DISTORTED_MODELS = ("t96", "t01", "ts04")

# Trace targets accepted by evaluate_magnetic_field, mapped onto the
# ttrace2endpoint endpoint strings.
TRACE_TARGETS: dict[str, str | None] = {
    "none": None,
    "ionosphere": "ionosphere-north",
    "equator": "equator",
}

# Earth radius (km) used by geopack to convert km <-> Re.
R_E_KM = 6371.2

# These wrappers are for near-Earth magnetospheric field models in geocentric
# GSM coordinates.  A 30 Re outer limit covers common inner/middle
# magnetosphere, ring-current/radiation-belt, and many magnetopause-tail use
# cases while catching heliocentric/SPICE vectors accidentally supplied as
# Earth-centered GSM km (issue #85).
FIELD_MODEL_MIN_RADIUS_RE = 1.0
FIELD_MODEL_MAX_RADIUS_RE = 30.0


def _error(
    message: str,
    *,
    code: str = "invalid_argument",
    hint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the uniform structured error payload for analysis tools.

    Mirrors :func:`spedas_agent_kit.analysis.coords._error` and the server's
    ``_error_response`` envelope so field-model errors share the same
    ``{status: "error", code, message, ...}`` contract (issue #27).
    """
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint is not None:
        payload["hint"] = hint
    payload.update(extra)
    return payload


class GeopackVersionError(AnalysisDependencyError):
    """Raised when the installed ``pyspedas`` lacks a required geopack API.

    ``pyspedas`` is importable but is an older release whose ``pyspedas.geopack``
    package does not expose the field-model / field-line-tracing entry points
    these tools need (e.g. ``ttrace2endpoint`` / ``tigrf``). This is distinct from
    ``pyspedas`` being absent entirely (:class:`AnalysisDependencyError`).
    """

    def __init__(self, missing: list[str]) -> None:
        self.missing = list(missing)
        super().__init__(
            "The installed pyspedas is missing required geopack APIs: "
            f"{self.missing}. These field-model / tracing entry points were added "
            "in newer pyspedas releases. Update with: pip install -U "
            "'spedas-agent-kit[analysis]' (pyspedas>=2.0 with geopack ttrace2endpoint / "
            "tigrf)."
        )


# Geopack symbols these tools resolve. Each maps a logical name to the dotted
# submodule path it lives in for modern pyspedas, so we can import the symbol
# from its own module first (the modern source layout) and fall back to the
# pyspedas.geopack package namespace where the symbol is re-exported.
_GEOPACK_SYMBOLS: dict[str, str] = {
    "tigrf": "pyspedas.geopack.igrf",
    "tt89": "pyspedas.geopack.t89",
    "tt96": "pyspedas.geopack.t96",
    "tt01": "pyspedas.geopack.t01",
    "tts04": "pyspedas.geopack.ts04",
    "ttrace2endpoint": "pyspedas.geopack.ttrace2endpoint",
}


def _resolve_geopack(required: list[str]) -> dict[str, Any]:
    """Import the requested geopack symbols, compatible with old/new layouts.

    For each name in ``required`` the symbol is imported from its dedicated
    submodule (the modern ``pyspedas/geopack/<model>.py`` layout) and, failing
    that, looked up as an attribute on the ``pyspedas.geopack`` package (older
    releases that re-export a subset). Anything still missing is collected and a
    single :class:`GeopackVersionError` is raised, so callers never see a raw
    ``ImportError`` for an outdated pyspedas.

    Returns a ``{name: callable}`` dict for the resolved symbols.
    """
    import importlib

    resolved: dict[str, Any] = {}
    missing: list[str] = []
    try:
        geopack_pkg = importlib.import_module("pyspedas.geopack")
    except Exception:  # pragma: no cover - require_pyspedas already gates this
        raise GeopackVersionError(list(required)) from None

    for name in required:
        module_path = _GEOPACK_SYMBOLS.get(name)
        symbol = None
        if module_path is not None:
            try:
                symbol = getattr(importlib.import_module(module_path), name, None)
            except Exception:
                symbol = None
        if symbol is None:
            symbol = getattr(geopack_pkg, name, None)
        if symbol is None:
            missing.append(name)
        else:
            resolved[name] = symbol

    if missing:
        raise GeopackVersionError(missing)
    return resolved


def _load_positions(
    positions_file: str,
    time_col: str = "time",
    position_cols: list[str] | None = None,
) -> tuple[Any, Any]:
    """Read a (times, Nx3 positions) pair from a positions artifact.

    Supported shapes
    ----------------
    - ``.npz`` (preferred): a ``positions`` array of shape ``(N, 3)`` and an
      optional ``times`` array of length ``N`` (Unix seconds). When ``times`` is
      absent, a synthetic monotonically increasing 1 s cadence is used (geopack
      only needs the timestamps to evaluate the IGRF epoch; the cadence does not
      affect a static-position evaluation, but a real epoch matters for the model
      year, so callers should include ``times`` for science use).
    - ``.npy``: a bare ``(N, 3)`` array (synthetic times as above).
    - ``.csv`` / ``.json``: a time column plus three numeric position columns,
      matching the data-layer ``fetch_*`` artifact shapes.

    Positions are interpreted as **geocentric GSM coordinates in km** (the
    geopack input convention). Field-model callers additionally reject radii
    outside 1..30 Re to catch heliocentric or otherwise Earth-invalid inputs.

    Returns ``(unix_time_ndarray, nx3_position_ndarray)``.

    Raises
    ------
    ValueError
        If the file cannot be parsed into a time array and an Nx3 position array.
    """
    import numpy as np

    path = Path(positions_file)
    if not path.exists():
        raise ValueError(f"positions file does not exist: {positions_file}")

    suffix = path.suffix.lower()

    if suffix == ".npz":
        with np.load(path, allow_pickle=False) as npz:
            keys = list(npz.keys())
            pos_key = "positions" if "positions" in npz else None
            if pos_key is None:
                raise ValueError(
                    "npz positions file must contain a 'positions' array (Nx3); "
                    f"found keys: {keys}"
                )
            positions = np.asarray(npz[pos_key], dtype="float64")
            if "times" in npz:
                times = np.asarray(npz["times"], dtype="float64").reshape(-1)
            else:
                times = None
        return _finalize_positions(times, positions)

    if suffix == ".npy":
        positions = np.asarray(np.load(path, allow_pickle=False), dtype="float64")
        return _finalize_positions(None, positions)

    # CSV / JSON: time column + 3 numeric position columns.
    import json

    import pandas as pd

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON input must be an object mapping column -> list")
        df = pd.DataFrame(payload)
    else:
        df = pd.read_csv(path)

    if df.empty:
        raise ValueError("positions file contains no rows")

    if time_col in df.columns:
        time_series = df[time_col]
    elif len(df.columns) >= 1:
        time_series = df[df.columns[0]]
    else:
        raise ValueError(
            f"could not find time column '{time_col}'; available columns: {list(df.columns)}"
        )

    if pd.api.types.is_numeric_dtype(time_series):
        times = time_series.to_numpy(dtype="float64")
    else:
        parsed = pd.to_datetime(time_series, utc=True, errors="coerce")
        if parsed.isna().all():
            raise ValueError("time column could not be parsed as numeric or datetime")
        times = parsed.astype("int64").to_numpy() / 1e9

    if position_cols is None:
        candidate_cols = [
            c
            for c in df.columns
            if c != time_series.name and pd.api.types.is_numeric_dtype(df[c])
        ]
        if len(candidate_cols) < 3:
            raise ValueError(
                "could not auto-detect 3 numeric position columns; pass "
                f"position_cols explicitly. numeric columns found: {candidate_cols}"
            )
        resolved = candidate_cols[:3]
    else:
        missing = [c for c in position_cols if c not in df.columns]
        if missing:
            raise ValueError(
                f"position_cols not found in input: {missing}; available: {list(df.columns)}"
            )
        if len(position_cols) != 3:
            raise ValueError(
                f"position_cols must list exactly 3 columns, got {len(position_cols)}"
            )
        resolved = list(position_cols)

    positions = df[resolved].to_numpy(dtype="float64")
    return _finalize_positions(times, positions)


def _finalize_positions(times: Any, positions: Any) -> tuple[Any, Any]:
    """Validate an Nx3 position array and pair it with a time axis."""
    import numpy as np

    positions = np.asarray(positions, dtype="float64")
    if positions.ndim != 2 or positions.shape[1] != 3:
        raise ValueError(
            "positions must be an (N, 3) array of GSM coordinates (km); got shape "
            f"{tuple(positions.shape)}"
        )
    if positions.shape[0] == 0:
        raise ValueError("positions array is empty")
    if not np.isfinite(positions).all():
        raise ValueError("positions array contains non-finite values")

    n = positions.shape[0]
    if times is None:
        # Synthetic 1 s cadence anchored at a fixed epoch. Callers that need a
        # real IGRF model year must supply 'times'.
        times = np.arange(n, dtype="float64") + 1_600_000_000.0
    else:
        times = np.asarray(times, dtype="float64").reshape(-1)
        if times.shape[0] != n:
            raise ValueError(
                f"times length ({times.shape[0]}) does not match number of "
                f"positions ({n})"
            )
    # pandas' single-column ``Series.to_numpy`` (and some ``np.load`` views) can
    # return read-only arrays. pyspedas ``store_data`` scrubs non-finite
    # timestamps in place (``times[cond] = 0``), which raises ``assignment
    # destination is read-only`` on such an array (issue #58). Hand the backend
    # writeable, owned copies so the in-place write always succeeds.
    times = np.array(times, dtype="float64", copy=True)
    positions = np.array(positions, dtype="float64", copy=True)
    return times, positions


def _position_domain_error(positions: Any) -> dict[str, Any] | None:
    """Return a structured error if GSM positions are outside the tool domain.

    The geopack wrappers expect geocentric GSM coordinates in km and are exposed
    here for near-Earth magnetospheric use. Accidentally passing heliocentric
    positions (for example SPICE Sun-centered vectors) can produce numerically
    finite but physically meaningless field values or L shells. Reject obvious
    out-of-domain radii before invoking the backend.
    """
    import numpy as np

    radii_re = np.linalg.norm(np.asarray(positions, dtype="float64"), axis=1) / R_E_KM
    min_radius = float(np.nanmin(radii_re))
    max_radius = float(np.nanmax(radii_re))
    bad_small = np.where(radii_re < FIELD_MODEL_MIN_RADIUS_RE)[0]
    bad_large = np.where(radii_re > FIELD_MODEL_MAX_RADIUS_RE)[0]
    if bad_small.size == 0 and bad_large.size == 0:
        return None

    examples = sorted(
        set(int(i) for i in np.concatenate([bad_small[:3], bad_large[:3]]))
    )
    return _error(
        "positions are outside the supported near-Earth field-model domain: "
        f"radii must be between {FIELD_MODEL_MIN_RADIUS_RE:g} and "
        f"{FIELD_MODEL_MAX_RADIUS_RE:g} Re from Earth's center; observed range "
        f"is {min_radius:.3g}..{max_radius:.3g} Re",
        code="position_domain_error",
        hint=(
            "Input positions must be geocentric GSM coordinates in km for an "
            "Earth magnetospheric interval. If these are heliocentric/SPICE or "
            "planet-centered vectors, first transform them to Earth-centered GSM "
            "km or choose a heliophysics/planetary geometry tool instead."
        ),
        min_radius_re=min_radius,
        max_radius_re=max_radius,
        min_allowed_radius_re=FIELD_MODEL_MIN_RADIUS_RE,
        max_allowed_radius_re=FIELD_MODEL_MAX_RADIUS_RE,
        invalid_sample_indices=examples,
    )


def _vector_stats(array: Any) -> dict[str, Any]:
    """Per-component and magnitude min/max/mean for an Nx3 array (JSON-friendly)."""
    import numpy as np

    arr = np.asarray(array, dtype="float64")
    mag = np.linalg.norm(arr, axis=1)
    with np.errstate(all="ignore"):
        return {
            "components": {
                "min": [float(np.nanmin(arr[:, i])) for i in range(3)],
                "max": [float(np.nanmax(arr[:, i])) for i in range(3)],
                "mean": [float(np.nanmean(arr[:, i])) for i in range(3)],
            },
            "min": float(np.nanmin(mag)),
            "max": float(np.nanmax(mag)),
            "mean": float(np.nanmean(mag)),
        }


def _scalar_stats(array: Any) -> dict[str, float]:
    """min/max/mean over finite values of a 1d array (JSON-friendly)."""
    import numpy as np

    arr = np.asarray(array, dtype="float64").reshape(-1)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return {"min": float("nan"), "max": float("nan"), "mean": float("nan")}
    return {
        "min": float(finite.min()),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
    }


def _resolve_model(model: str) -> tuple[str | None, dict[str, Any] | None]:
    """Normalize a model name; return ``(normalized, error)``."""
    model_l = (model or "").strip().lower()
    if model_l not in FIELD_MODELS:
        return None, _error(
            f"unsupported model '{model}'", supported_models=list(FIELD_MODELS)
        )
    return model_l, None


def _require_parameters(
    model: str, parameters: dict[str, Any] | None
) -> dict[str, Any] | None:
    """Return a ``parameters_required`` error when a model needs indices we lack.

    IGRF needs nothing. The distorted Tsyganenko models (T96/T01/TS04) need a full
    solar-wind / IMF index set; T89 needs only a single ``iopt``/``kp`` index. We
    never auto-download these (that would be hidden heavy network I/O), so a
    missing set is a deterministic error rather than an implicit fetch.
    """
    if model == "igrf":
        return None
    params = parameters or {}
    if model == "t89":
        if not any(k in params for k in ("iopt", "kp", "parmod")):
            return _error(
                "model 't89' needs a geomagnetic activity index. Pass "
                "parameters={'iopt': <1-7>} or {'kp': <value>} (or a precomputed "
                "'parmod'). Auto-downloading Kp is intentionally disabled to avoid "
                "hidden network I/O; use 'igrf' for a fast, parameter-free field.",
                code="parameters_required",
                model=model,
                required_one_of=["iopt", "kp", "parmod"],
            )
        return None
    # T96 / T01 / TS04
    required = {
        "t96": ["pdyn", "dst", "byimf", "bzimf"],
        "t01": ["pdyn", "dst", "byimf", "bzimf", "g1", "g2"],
        "ts04": ["pdyn", "dst", "byimf", "bzimf", "w1", "w2", "w3", "w4", "w5", "w6"],
    }[model]
    if "parmod" in params:
        return None
    missing = [k for k in required if k not in params]
    if missing:
        return _error(
            f"model '{model}' requires solar-wind / IMF parameters; missing: "
            f"{missing}. Pass them via parameters={{...}} (or a precomputed "
            "'parmod'). Auto-downloading geomagnetic indices is intentionally "
            "disabled to avoid hidden network I/O; use 'igrf' for a fast, "
            "parameter-free field.",
            code="parameters_required",
            model=model,
            required=required,
            missing=missing,
        )
    return None


def _model_kwargs(model: str, parameters: dict[str, Any] | None) -> dict[str, Any]:
    """Translate a validated ``parameters`` dict into geopack tt*/trace kwargs."""
    params = dict(parameters or {})
    allowed = {
        "igrf": [],
        "t89": ["iopt", "kp", "parmod"],
        "t96": ["pdyn", "dst", "byimf", "bzimf", "parmod"],
        "t01": ["pdyn", "dst", "byimf", "bzimf", "g1", "g2", "parmod"],
        "ts04": [
            "pdyn", "dst", "byimf", "bzimf",
            "w1", "w2", "w3", "w4", "w5", "w6", "parmod",
        ],
    }[model]
    return {k: params[k] for k in allowed if k in params}


def evaluate_magnetic_field(
    positions_file: str,
    output_file: str,
    model: str = "igrf",
    parameters: dict[str, Any] | None = None,
    trace: str = "none",
    time_col: str = "time",
    position_cols: list[str] | None = None,
) -> dict[str, Any]:
    """Evaluate a magnetic field model at Nx3 GSM positions, optionally tracing (#16).

    Backend: ``pyspedas`` geopack ``tigrf`` / ``tt89`` / ``tt96`` / ``tt01`` /
    ``tts04`` for the field, ``ttrace2endpoint`` for optional field-line tracing.
    Reads a positions artifact (``.npz`` with ``positions`` Nx3 in GSM km and an
    optional ``times`` array; ``.npy``; or CSV/JSON), writes the per-sample B
    vectors (and any trace footpoints/L series) to ``output_file`` as a compressed
    ``.npz``, and returns the model, ``field_strength_nT`` summary stats, output
    paths, and (when tracing to the equator) an L-shell summary only. The bulk
    arrays never appear inline. Requires ``spedas-agent-kit[analysis]``.
    """
    model_l, err = _resolve_model(model)
    if err is not None:
        return err

    trace_l = (trace or "none").strip().lower()
    if trace_l not in TRACE_TARGETS:
        return _error(
            f"unsupported trace '{trace}'", supported_trace=sorted(TRACE_TARGETS)
        )
    endpoint = TRACE_TARGETS[trace_l]

    param_err = _require_parameters(model_l, parameters)
    if param_err is not None:
        return param_err

    try:
        import numpy as np

        times, positions = _load_positions(
            positions_file, time_col=time_col, position_cols=position_cols
        )
    except ValueError as exc:
        return _error(str(exc))

    domain_err = _position_domain_error(positions)
    if domain_err is not None:
        return domain_err

    # Resolve only the geopack APIs this call needs: the chosen model's wrapper,
    # plus ttrace2endpoint when tracing. A missing pyspedas yields
    # dependency_missing; an older pyspedas that lacks the specific entry points
    # yields backend_outdated -- never a raw ImportError.
    model_symbol = {
        "igrf": "tigrf",
        "t89": "tt89",
        "t96": "tt96",
        "t01": "tt01",
        "ts04": "tts04",
    }[model_l]
    required_apis = [model_symbol]
    if endpoint is not None:
        required_apis.append("ttrace2endpoint")
    try:
        require_pyspedas()
        gp = _resolve_geopack(required_apis)
    except GeopackVersionError as exc:
        return _error(str(exc), code="backend_outdated", missing=exc.missing)
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    from pyspedas import del_data, get_data, set_coords, set_units, store_data

    pos_var = "_spedas_agent_kit_eval_pos_gsm"
    model_kwargs = _model_kwargs(model_l, parameters)
    b_var = None

    try:
        store_data(pos_var, data={"x": times, "y": positions})
        set_coords(pos_var, "GSM")
        set_units(pos_var, "km")

        if model_l == "igrf":
            # tigrf() returns a '<pos>_igrf' name but actually stores the field
            # under '<pos>_btigrf' (known upstream inconsistency), so read from
            # the variable that was actually written.
            gp["tigrf"](pos_var)
            b_var = pos_var + "_btigrf"
        else:
            b_var = gp[model_symbol](pos_var, **model_kwargs)

        if not b_var:
            return _error(
                f"geopack model '{model_l}' returned no field variable; check that "
                "positions are valid GSM coordinates in km",
                code="backend_error",
                model=model_l,
            )
        b_data = get_data(b_var)
        if b_data is None:
            return _error(
                f"could not read modeled field from geopack variable '{b_var}'",
                code="backend_error",
                model=model_l,
            )
        bvec = np.asarray(b_data.y, dtype="float64")

        save_kwargs: dict[str, Any] = {
            "time": np.asarray(times, dtype="float64"),
            "positions": positions,
            "b_gsm": bvec,
        }

        footpoints = None
        lshell = None
        if endpoint is not None:
            foot_var = "_spedas_agent_kit_eval_foot"
            trace_model = model_l
            trace_kwargs = _model_kwargs(model_l, parameters)
            gp["ttrace2endpoint"](
                pos_var,
                trace_model,
                endpoint,
                foot_name=foot_var,
                km=True,
                **trace_kwargs,
            )
            foot_data = get_data(foot_var)
            if foot_data is not None:
                footpoints = np.asarray(foot_data.y, dtype="float64")
                save_kwargs["footpoints_gsm"] = footpoints
                if endpoint == "equator":
                    # The equatorial foot radius (in Re) is the McIlwain L apex.
                    lshell = np.linalg.norm(footpoints, axis=1) / R_E_KM
                    save_kwargs["lshell"] = lshell
            del_data(foot_var)
    finally:
        del_data(pos_var)
        # tigrf has a known upstream bug: it stores '<pos>_btigrf' but returns a
        # '<pos>_igrf' name, so b_var won't match the stored variable for IGRF.
        del_data(pos_var + "_btigrf")
        if b_var:
            del_data(b_var)

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, **save_kwargs)

    result: dict[str, Any] = {
        "status": "success",
        "tool": "evaluate_magnetic_field",
        "result_file": str(out_path),
        "model": model_l,
        "n_samples": int(positions.shape[0]),
        "trace": trace_l,
        "field_strength_nT": _vector_stats(bvec),
    }
    if footpoints is not None:
        result["footpoints_file"] = str(out_path)
        result["footpoints_summary"] = _vector_stats(footpoints)
    if lshell is not None:
        result["lshell_summary"] = {
            "min_L": _scalar_stats(lshell)["min"],
            "max_L": _scalar_stats(lshell)["max"],
            "mean_L": _scalar_stats(lshell)["mean"],
        }
    result["note"] = (
        "Per-sample B (nT, GSM) saved under key 'b_gsm' in the .npz alongside "
        "'positions' (GSM km) and 'time' (Unix s)"
        + (", plus 'footpoints_gsm'" if footpoints is not None else "")
        + (" and 'lshell' (Re)" if lshell is not None else "")
        + ". This tool returns summary stats and paths only."
    )
    return result


def calculate_lshell(
    positions_file: str,
    output_file: str,
    model: str = "igrf",
    geomag_parameters: dict[str, Any] | None = None,
    footprint: bool = False,
    time_col: str = "time",
    position_cols: list[str] | None = None,
    parameters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """McIlwain L-shell (+ optional ionospheric footprint) for Nx3 GSM positions (#17).

    Backend: ``pyspedas`` geopack ``ttrace2endpoint`` (trace to the magnetic
    equator; the equatorial foot radius in Re is L). IGRF is fast and
    parameter-free (the default); distorted models require ``geomag_parameters``
    and return a ``parameters_required`` error otherwise (no hidden network I/O).
    Writes the per-sample L series (and any ionospheric footprint) to
    ``output_file`` as a compressed ``.npz`` and returns the L summary stats and
    paths only. Requires ``spedas-agent-kit[analysis]``.

    ``parameters`` is accepted as an alias for ``geomag_parameters`` so the
    geomagnetic-index argument has the same name as in
    :func:`evaluate_magnetic_field`; ``geomag_parameters`` remains supported for
    backward compatibility. Supplying both with different values is rejected with
    a structured ``invalid_argument`` error.
    """
    # Resolve the geomag_parameters / parameters alias. They name the same
    # concept; allow either, but reject conflicting both-provided values.
    if parameters is not None and geomag_parameters is not None:
        if parameters != geomag_parameters:
            return _error(
                "'parameters' and 'geomag_parameters' were both provided with "
                "different values; they are aliases for the same geomagnetic "
                "index set. Pass only one (prefer 'geomag_parameters').",
                code="invalid_argument",
            )
        resolved_params = geomag_parameters
    else:
        resolved_params = (
            geomag_parameters if geomag_parameters is not None else parameters
        )

    model_l, err = _resolve_model(model)
    if err is not None:
        return err

    param_err = _require_parameters(model_l, resolved_params)
    if param_err is not None:
        return param_err

    try:
        import numpy as np

        times, positions = _load_positions(
            positions_file, time_col=time_col, position_cols=position_cols
        )
    except ValueError as exc:
        return _error(str(exc))

    domain_err = _position_domain_error(positions)
    if domain_err is not None:
        return domain_err

    # L-shell always traces field lines, so ttrace2endpoint is mandatory here.
    # A missing pyspedas yields dependency_missing; an older pyspedas lacking
    # the tracer yields backend_outdated -- never a raw ImportError.
    try:
        require_pyspedas()
        gp = _resolve_geopack(["ttrace2endpoint"])
    except GeopackVersionError as exc:
        return _error(str(exc), code="backend_outdated", missing=exc.missing)
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    from pyspedas import del_data, get_data, set_coords, set_units, store_data

    ttrace2endpoint = gp["ttrace2endpoint"]
    pos_var = "_spedas_agent_kit_lshell_pos_gsm"
    eq_foot = "_spedas_agent_kit_lshell_eq_foot"
    iono_foot = "_spedas_agent_kit_lshell_iono_foot"
    trace_kwargs = _model_kwargs(model_l, resolved_params)

    footprint_arr = None
    try:
        store_data(pos_var, data={"x": times, "y": positions})
        set_coords(pos_var, "GSM")
        set_units(pos_var, "km")

        ttrace2endpoint(
            pos_var, model_l, "equator", foot_name=eq_foot, km=True, **trace_kwargs
        )
        eq_data = get_data(eq_foot)
        if eq_data is None:
            return _error(
                f"geopack equator trace ('{model_l}') produced no foot points; "
                "check that positions are valid GSM coordinates in km",
                code="backend_error",
                model=model_l,
            )
        eq_foot_gsm = np.asarray(eq_data.y, dtype="float64")
        lshell = np.linalg.norm(eq_foot_gsm, axis=1) / R_E_KM

        save_kwargs: dict[str, Any] = {
            "time": np.asarray(times, dtype="float64"),
            "positions": positions,
            "lshell": lshell,
            "equatorial_foot_gsm": eq_foot_gsm,
        }

        if footprint:
            ttrace2endpoint(
                pos_var,
                model_l,
                "ionosphere-north",
                foot_name=iono_foot,
                km=True,
                **trace_kwargs,
            )
            iono_data = get_data(iono_foot)
            if iono_data is not None:
                footprint_arr = np.asarray(iono_data.y, dtype="float64")
                save_kwargs["ionospheric_footprint_gsm"] = footprint_arr
            del_data(iono_foot)
    finally:
        del_data(pos_var)
        del_data(eq_foot)

    out_path = Path(output_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out_path, **save_kwargs)

    stats = _scalar_stats(lshell)
    result: dict[str, Any] = {
        "status": "success",
        "tool": "calculate_lshell",
        "lshell_file": str(out_path),
        "model": model_l,
        "n_samples": int(positions.shape[0]),
        "summary": {
            "min_L": stats["min"],
            "max_L": stats["max"],
            "mean_L": stats["mean"],
        },
    }
    if footprint_arr is not None:
        result["footprint_file"] = str(out_path)
        result["footprint_summary"] = _vector_stats(footprint_arr)
    result["note"] = (
        "Per-sample L saved under key 'lshell' (Re) in the .npz alongside "
        "'positions' (GSM km), 'time' (Unix s), and 'equatorial_foot_gsm'"
        + (
            ", plus 'ionospheric_footprint_gsm'"
            if footprint_arr is not None
            else ""
        )
        + ". This tool returns L summary stats and the path only."
    )
    return result


__all__ = [
    "FIELD_MODELS",
    "DISTORTED_MODELS",
    "TRACE_TARGETS",
    "FIELD_MODEL_MIN_RADIUS_RE",
    "FIELD_MODEL_MAX_RADIUS_RE",
    "GeopackVersionError",
    "evaluate_magnetic_field",
    "calculate_lshell",
]
