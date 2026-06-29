"""Phase-2 particle analysis tools (issues #18, #19).

Two MCP tools that turn 3D particle velocity distributions into the standard
thermodynamic and spectral observables:

- :func:`compute_particle_moments` (#18) - plasma moments (density, velocity,
  temperature, pressure tensor, heat-flux summaries) from a time series of 3D
  distributions, via ``pyspedas.particles.moments.moments_3d``.
- :func:`build_particle_distribution_artifact` (#95) - bridge pyspedas
  mission distribution converters (MMS FPI/HPCA and ERG particle products) from
  already-loaded real mission tplot/CDF variables into the explicit .npz schema
  these particle tools consume.
- :func:`compute_particle_spectra` (#19) - energy / azimuth (phi) / elevation
  (theta) / pitch-angle spectrograms. Energy/phi/theta use ``pyspedas``
  ``spd_pgs_make_e_spec`` / ``spd_pgs_make_phi_spec`` /
  ``spd_pgs_make_theta_spec``. Field-aligned **pitch-angle** spectra are computed
  by rotating each slice into field-aligned coordinates with
  ``spd_pgs_do_fac`` (B as the +z axis) and binning the resulting polar
  (pitch) angle via ``spd_pgs_make_theta_spec`` in colatitude mode. This path
  needs a magnetic-field reference: an explicit ``mag_file`` (override) or,
  failing that, the ``magf`` vectors embedded in the distribution artifact by the
  #95 bridge (issue #148). When neither is available the pitch-angle entry
  reports ``needs_input`` instead of failing the whole call, and its
  ``mag_source`` field records which reference was used.
  It depends only on ``spd_pgs_do_fac`` + ``spd_pgs_make_theta_spec`` (present
  in every pyspedas build), not on the optional ``spd_pgs_make_pad_spec``.

Design contract (mirrors :mod:`spedas_agent_kit.analysis.spectral` /
:mod:`spedas_agent_kit.analysis.fieldmodels`, roadmap epics #5/#9):

- **File-in / file-out, artifact-first.** The input is a path to an explicit
  distribution artifact (``.npz`` preferred; JSON accepted) holding the
  per-slice cubes. Bulk moment time-series and spectrogram matrices are written
  to ``output_dir`` (CSV/JSON for moments, ``.npz`` for spectra). Returns are
  small JSON-serializable dicts with ``status``, file paths, and **scalar
  summaries / ranges / shapes only**. Full particle cubes, pressure tensors, and
  spectrogram matrices are never returned inline.
- **Explicit, documented distribution schema.** Rather than pretend to ingest
  every mission's CDF distribution struct, this module defines one explicit
  schema (see :data:`DIST_SCHEMA_DOC`) that maps 1:1 onto the ``data_in`` dict
  ``moments_3d`` / the ``spd_pgs_make_*`` functions consume. Mission CDFs can be
  bridged into this schema either by ``load_particle_distribution_artifact``
  (loader/fetch plus converter) or by ``build_particle_distribution_artifact``
  from already-loaded tplot variables; the pyspedas algorithms themselves run on
  the real arrays.
- **Lazy, gated backends.** ``pyspedas`` is imported only inside these
  functions; a missing ``[analysis]`` extra yields a clean
  ``status="error", code="dependency_missing"`` payload. Each pyspedas function
  is additionally checked for *exact* availability before use, because installed
  ``pyspedas`` builds vary (e.g. ``spd_pgs_make_pad_spec`` is absent in some
  releases). A missing-but-required backend yields ``code="unsupported"`` rather
  than a raw ``ImportError``.
- **Artifact-first I/O with explicit loader side effects.** Most functions are
  file/tplot-in and file-out, returning only compact summaries and artifact
  paths. ``load_particle_distribution_artifact`` is the explicit exception that
  may invoke a pyspedas mission loader/fetch; any archive download/cache behavior
  is owned by that loader and reported in returned provenance.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import AnalysisDependencyError, require_pyspedas

# Per-slice distribution fields consumed by the pyspedas particle algorithms.
# ``data``/``energy``/``theta``/``phi``/``dtheta``/``dphi``/``denergy``/``bins``
# are per-slice 2D arrays of shape ``(n_energy, n_angle)``; stacked over time
# they are 3D ``(n_time, n_energy, n_angle)``. ``magf`` is the per-slice
# magnetic-field vector consumed by ``moments_3d`` for field-aligned tensor
# decomposition; it may be supplied as ``(3,)`` or ``(T,3)``. ``charge``/``mass``
# are scalars.
_SLICE_FIELDS = (
    "data",
    "energy",
    "denergy",
    "theta",
    "dtheta",
    "phi",
    "dphi",
    "bins",
)
_SCALAR_FIELDS = ("charge", "mass")
_VECTOR_FIELDS = ("magf",)

# Fields each backend strictly requires. moments_3d needs the full set; the
# spectra functions need only the geometry + data they average over.
_MOMENTS_REQUIRED = set(_SLICE_FIELDS) | set(_SCALAR_FIELDS) | set(_VECTOR_FIELDS)
_SPECTRA_REQUIRED = {
    "energy": {"data", "energy", "bins"},
    "phi": {"data", "theta", "dtheta", "phi", "dphi", "bins"},
    "theta": {"data", "theta", "dtheta", "dphi", "bins"},
    # pitch_angle: FAC rotation needs the full angular geometry. The B reference
    # is NOT a hard-required field here: it is resolved at run time from an
    # explicit mag_file or, failing that, the embedded 'magf' the #95 bridge
    # writes into the artifact (issue #148). 'magf' is loaded opportunistically by
    # _normalize_distribution whenever present, so it need not be listed as
    # required for the pitch-angle entry to find it.
    "pitch_angle": {"data", "theta", "dtheta", "phi", "dphi", "bins"},
}

# Spectrum types this tool knows about. "azimuth" is accepted as an alias for
# "phi" and "elevation" for "theta" (mission-neutral naming).
_SPECTRUM_ALIASES = {
    "azimuth": "phi",
    "elevation": "theta",
    "pad": "pitch_angle",
    "pitchangle": "pitch_angle",
}
_KNOWN_SPECTRA = ("energy", "phi", "theta", "pitch_angle")

DIST_SCHEMA_DOC = (
    "Distribution artifact schema (file-in). Provide an .npz (preferred) or a "
    "JSON object with these keys: 'times' (T Unix seconds), 'data' (T,E,A flux), "
    "'energy' (T,E,A or E,A eV), 'denergy', 'theta', 'dtheta', 'phi', 'dphi', "
    "'bins' (same shape as 'data'; 1=active, 0=inactive), 'magf' ((T,3) "
    "magnetic-field vector per distribution slice, or (3,) broadcast to all "
    "slices; required by moments_3d for field-aligned temperature/pressure "
    "decomposition), and scalars 'charge' (in e) and 'mass' (in eV/(km/s)^2, "
    "pyspedas convention). E=energy bins, A=solid-angle bins. Per-slice 2D "
    "fields may be given once (E,A) and are broadcast across all T slices."
)

MAG_SCHEMA_DOC = (
    "Magnetic-field reference schema (file-in, for pitch-angle spectra). Provide "
    "an .npz (preferred) or a JSON object with key 'b' holding the B-field "
    "vectors and an optional 'times' axis. 'b' is either (T,3) - one B vector per "
    "distribution time slice (matched by index; T must equal the number of "
    "distribution slices) - or (3,), a single B vector broadcast across all "
    "slices. B must be in the SAME coordinate frame as the distribution's "
    "theta/phi look directions (only B's direction is used; magnitude is "
    "ignored). The pitch angle is the angle between each bin's look direction "
    "and +B."
)

# Default number of pitch-angle bins over 0-180 deg when 'resolution' is unset.
_DEFAULT_PAD_BINS = 18


class ParticleBackendError(AnalysisDependencyError):
    """Raised when a required pyspedas particle backend function is unavailable."""


def _error(
    message: str,
    *,
    code: str = "invalid_argument",
    hint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the uniform structured error payload for analysis tools.

    Mirrors :func:`spedas_agent_kit.analysis.spectral._error` and the server's
    ``_error_response`` envelope so particle errors share the same
    ``{status: "error", code, message, ...}`` contract (issue #27).
    """
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint is not None:
        payload["hint"] = hint
    payload.update(extra)
    return payload


def _load_distribution(dist_file: str) -> dict[str, Any]:
    """Load the explicit distribution artifact into a dict of numpy arrays/scalars.

    Supports ``.npz`` / ``.npy`` (via numpy) and ``.json`` (object of lists).
    Returns the raw mapping; shape validation/normalization happens in
    :func:`_normalize_distribution`.

    Raises
    ------
    ValueError
        If the file is missing or cannot be parsed into a mapping.
    """
    import numpy as np

    path = Path(dist_file)
    if not path.exists():
        raise ValueError(f"distribution file does not exist: {dist_file}")

    suffix = path.suffix.lower()
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON distribution must be an object mapping field -> values")
        return {k: (np.asarray(v) if isinstance(v, list) else v) for k, v in payload.items()}

    if suffix in (".npz",):
        with np.load(path, allow_pickle=False) as npz:
            return {k: npz[k] for k in npz.files}

    if suffix in (".npy",):
        raise ValueError(
            ".npy holds a single array; the distribution needs multiple named "
            "fields. Provide an .npz or .json (see schema)."
        )

    raise ValueError(
        f"unsupported distribution file type '{suffix}'; use .npz or .json"
    )


def _normalize_distribution(
    raw: dict[str, Any], required: set[str]
) -> tuple[Any, dict[str, Any], dict[str, Any], int]:
    """Validate fields and reshape per-slice cubes to ``(n_time, n_energy, n_angle)``.

    Returns ``(times, slice_cubes, scalars, n_time)`` where ``slice_cubes`` maps
    each present slice field to a 3D ``(T, E, A)`` array (a single 2D ``(E, A)``
    field is broadcast across T) and ``scalars`` holds charge/mass when present.

    Raises
    ------
    ValueError
        On missing required fields or inconsistent shapes.
    """
    import numpy as np

    missing = sorted(required - set(raw.keys()))
    if missing:
        raise ValueError(
            f"distribution is missing required field(s): {missing}. {DIST_SCHEMA_DOC}"
        )

    data = np.asarray(raw["data"], dtype="float64")
    if data.ndim == 2:
        data = data[np.newaxis, ...]  # single time slice -> (1, E, A)
    if data.ndim != 3:
        raise ValueError(
            f"'data' must be 2D (E,A) or 3D (T,E,A); got shape {tuple(np.shape(raw['data']))}"
        )
    n_time, n_energy, n_angle = data.shape

    # Resolve the time axis (default to an index range when absent).
    if "times" in raw:
        times = np.asarray(raw["times"], dtype="float64").reshape(-1)
        if times.shape[0] != n_time:
            raise ValueError(
                f"'times' length {times.shape[0]} != number of data slices {n_time}"
            )
    else:
        times = np.arange(n_time, dtype="float64")

    cubes: dict[str, Any] = {"data": data}
    for field in _SLICE_FIELDS:
        if field == "data":
            continue
        if field not in raw:
            continue
        arr = np.asarray(raw[field], dtype="float64")
        if arr.ndim == 2:
            if arr.shape != (n_energy, n_angle):
                raise ValueError(
                    f"field '{field}' has 2D shape {arr.shape}; expected "
                    f"({n_energy}, {n_angle}) to match 'data' bins"
                )
            arr = np.broadcast_to(arr, (n_time, n_energy, n_angle)).copy()
        elif arr.ndim == 3:
            if arr.shape != (n_time, n_energy, n_angle):
                raise ValueError(
                    f"field '{field}' has 3D shape {arr.shape}; expected "
                    f"{(n_time, n_energy, n_angle)} to match 'data'"
                )
        else:
            raise ValueError(
                f"field '{field}' must be 2D (E,A) or 3D (T,E,A); got ndim {arr.ndim}"
            )
        cubes[field] = arr

    for field in _VECTOR_FIELDS:
        if field not in raw:
            continue
        arr = np.asarray(raw[field], dtype="float64")
        if arr.ndim == 1:
            if arr.shape[0] != 3:
                raise ValueError(
                    f"field '{field}' 1D vector must have length 3; got {arr.shape[0]}"
                )
            arr = np.broadcast_to(arr, (n_time, 3)).copy()
        elif arr.ndim == 2:
            if arr.shape != (n_time, 3):
                raise ValueError(
                    f"field '{field}' must have shape (T,3) matching data slices; "
                    f"got {arr.shape}, expected {(n_time, 3)}"
                )
        else:
            raise ValueError(
                f"field '{field}' must be 1D (3,) or 2D (T,3); got ndim {arr.ndim}"
            )
        cubes[field] = arr

    scalars: dict[str, Any] = {}
    for field in _SCALAR_FIELDS:
        if field in raw:
            scalars[field] = float(np.asarray(raw[field]).reshape(-1)[0])

    return times, cubes, scalars, n_time


def _slice_dict(
    cubes: dict[str, Any], scalars: dict[str, Any], index: int
) -> dict[str, Any]:
    """Assemble the per-slice ``data_in`` dict pyspedas particle functions expect."""
    out: dict[str, Any] = {field: cubes[field][index] for field in cubes}
    out.update(scalars)
    return out


def _finite_range(array: Any) -> list[float] | None:
    """Return ``[min, max]`` over finite values, or ``None`` if none are finite."""
    import numpy as np

    arr = np.asarray(array, dtype="float64")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return [float(finite.min()), float(finite.max())]


def _finite_stats(array: Any) -> dict[str, float] | None:
    """Return ``{min, max, mean}`` over finite values, or ``None`` if none finite."""
    import numpy as np

    arr = np.asarray(array, dtype="float64")
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None
    return {
        "min": float(finite.min()),
        "max": float(finite.max()),
        "mean": float(finite.mean()),
    }


def _require_attr(module_path: str, attr: str) -> Any:
    """Import ``module_path`` and return ``attr``; raise ParticleBackendError if absent.

    Used to gate on the *exact* pyspedas function being present (Batch O lesson:
    package presence does not imply a given function exists in this build).
    """
    import importlib

    try:
        module = importlib.import_module(module_path)
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch
        raise ParticleBackendError(
            f"required pyspedas backend '{module_path}' is unavailable in this "
            f"install (import error: {exc}); upgrade pyspedas (spedas-agent-kit[analysis])"
        ) from exc
    fn = getattr(module, attr, None)
    if fn is None:
        raise ParticleBackendError(
            f"installed pyspedas lacks '{module_path}.{attr}'; upgrade pyspedas "
            "(spedas-agent-kit[analysis]) to a build that provides it"
        )
    return fn


# Verified upstream converter inventory (issue #95).
#
# As of pyspedas 1.7.x the ONLY mission ``*_get_dist`` converters that emit the
# per-slice ``data/energy/theta/phi/...`` record dicts this bridge consumes are:
#
#   * MMS:  mms_get_fpi_dist, mms_get_hpca_dist
#   * ERG:  erg_{lepi,lepe,mepi,mepe,hep,xep}_get_dist  (all 6)
#
# THEMIS and PSP have NO Python distribution converter in pyspedas 1.7.x and are
# therefore deliberately NOT wired here:
#   * THEMIS: the converter (thm_part_dist_array / thm_part_dist2tplot) exists
#     only in IDL and has not been ported to Python. A from-scratch port carries
#     calibration / spin-phase logic and belongs upstream, not in this kit.
#   * PSP: SWEAP/SPAN loaders expose only reduced L3 moments / EFLUX spectra, not
#     a 3D ``data_in`` distribution struct; there is no ``get_dist`` to call.
# Do NOT add THEMIS/PSP keys until upstream pyspedas exposes a real ``*_get_dist``
# for them. When it does, the ``_require_attr`` gating already degrades cleanly
# (``code="unsupported"``) for any not-yet-present function, so a later mapping is
# low-risk to add. Note the ERG signatures differ from the MMS template
# (``units=`` / ``species=`` defaults, ``trange=``; no ``probe`` / ``data_rate``);
# ``_converter_kwargs`` filters by signature so MMS-only kwargs are dropped safely.
_DIST_CONVERTERS = {
    # Real mission CDF -> tplot -> pyspedas particle distribution converters.
    # The MCP tool intentionally exposes these through one neutral "converter"
    # argument rather than as per-mission tools.
    "mms_fpi": ("pyspedas.projects.mms.fpi_tools.mms_get_fpi_dist", "mms_get_fpi_dist"),
    "mms_hpca": ("pyspedas.projects.mms.hpca_tools.mms_get_hpca_dist", "mms_get_hpca_dist"),
    "erg_lepi": ("pyspedas.projects.erg.satellite.erg.particle.erg_lepi_get_dist", "erg_lepi_get_dist"),
    "erg_lepe": ("pyspedas.projects.erg.satellite.erg.particle.erg_lepe_get_dist", "erg_lepe_get_dist"),
    "erg_mepi": ("pyspedas.projects.erg.satellite.erg.particle.erg_mepi_get_dist", "erg_mepi_get_dist"),
    "erg_mepe": ("pyspedas.projects.erg.satellite.erg.particle.erg_mepe_get_dist", "erg_mepe_get_dist"),
    "erg_hep": ("pyspedas.projects.erg.satellite.erg.particle.erg_hep_get_dist", "erg_hep_get_dist"),
    "erg_xep": ("pyspedas.projects.erg.satellite.erg.particle.erg_xep_get_dist", "erg_xep_get_dist"),
}

_DIST_LOADERS = {
    # Optional end-to-end CDF/tplot loaders for the same neutral converter keys.
    # These are deliberately small, documented defaults; callers can override
    # loader_module/loader_function/loader_kwargs for mission products whose
    # pyspedas signatures differ across releases.
    "mms_fpi": (
        "pyspedas.projects.mms",
        "mms_load_fpi",
        {"datatype": "dis-dist", "data_rate": "fast", "level": "l2", "get_support_data": True},
    ),
    "mms_hpca": (
        "pyspedas.projects.mms",
        "mms_load_hpca",
        {"datatype": "ion", "data_rate": "srvy", "level": "l2", "get_support_data": True},
    ),
    "erg_lepi": ("pyspedas.projects.erg", "lepi", {"datatype": "3dflux", "level": "l2", "get_support_data": True}),
    "erg_lepe": ("pyspedas.projects.erg", "lepe", {"datatype": "3dflux", "level": "l2", "get_support_data": True}),
    "erg_mepi": ("pyspedas.projects.erg", "mepi_nml", {"datatype": "3dflux", "level": "l2", "get_support_data": True}),
    "erg_mepe": ("pyspedas.projects.erg", "mepe", {"datatype": "3dflux", "level": "l2", "get_support_data": True}),
    "erg_hep": ("pyspedas.projects.erg", "hep", {"datatype": "3dflux", "level": "l2", "get_support_data": True}),
    "erg_xep": ("pyspedas.projects.erg", "xep", {"datatype": "omniflux", "level": "l2", "get_support_data": True}),
}

# Default B-field loaders used only when load_particle_distribution_artifact needs
# to populate magf automatically. The selected tplot variable is still extracted
# by name and interpolated to distribution-slice times before writing the artifact.
# Keep these mappings conservative and overrideable: mission loaders vary by
# pyspedas release and archive product.
_DIST_MAG_LOADERS = {
    "mms_fpi": (
        "pyspedas.projects.mms",
        "mms_load_fgm",
        {"datatype": "", "data_rate": "srvy", "level": "l2", "get_support_data": True},
    ),
    "mms_hpca": (
        "pyspedas.projects.mms",
        "mms_load_fgm",
        {"datatype": "", "data_rate": "srvy", "level": "l2", "get_support_data": True},
    ),
    "erg_lepi": ("pyspedas.projects.erg", "mgf", {"datatype": "8sec", "level": "l2"}),
    "erg_lepe": ("pyspedas.projects.erg", "mgf", {"datatype": "8sec", "level": "l2"}),
    "erg_mepi": ("pyspedas.projects.erg", "mgf", {"datatype": "8sec", "level": "l2"}),
    "erg_mepe": ("pyspedas.projects.erg", "mgf", {"datatype": "8sec", "level": "l2"}),
    "erg_hep": ("pyspedas.projects.erg", "mgf", {"datatype": "8sec", "level": "l2"}),
    "erg_xep": ("pyspedas.projects.erg", "mgf", {"datatype": "8sec", "level": "l2"}),
}


def _merge_loader_kwargs(defaults: dict[str, Any], overrides: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(defaults)
    if overrides:
        merged.update({k: v for k, v in overrides.items() if v is not None})
    return merged


def _coerce_loaded_tplot_names(result: Any) -> list[str]:
    if result is None or result == 0:
        return []
    if isinstance(result, str):
        return [result]
    if isinstance(result, dict):
        return [str(k) for k in result.keys()]
    if isinstance(result, (list, tuple, set)):
        return [str(x) for x in result if isinstance(x, (str, bytes)) or x is not None]
    return []


def _guess_distribution_tplot_name(loaded: list[str], converter: str) -> str | None:
    if not loaded:
        return None
    lowered = [(name, name.lower()) for name in loaded]
    converter_hints = {
        "mms_fpi": ("dist", "des", "dis"),
        "mms_hpca": ("dist", "hpca", "ion"),
        "erg_lepi": ("lepi", "3d", "flux"),
        "erg_lepe": ("lepe", "3d", "flux"),
        "erg_mepi": ("mepi", "3d", "flux"),
        "erg_mepe": ("mepe", "3d", "flux"),
        "erg_hep": ("hep", "3d", "flux"),
        "erg_xep": ("xep", "flux"),
    }.get(converter, ("dist",))
    for name, low in lowered:
        if "dist" in low:
            return name
    for hint in converter_hints:
        for name, low in lowered:
            if hint in low:
                return name
    return loaded[0]



def _guess_mag_tplot_name(loaded: list[str], converter: str) -> str | None:
    """Pick a likely B-field tplot variable from loader-returned names."""
    if not loaded:
        return None
    lowered = [(name, name.lower()) for name in loaded]
    # Prefer names that look like magnetic-field vectors rather than magnitudes,
    # status flags, or particle moments. MMS commonly exposes
    # mms1_fgm_b_gse_srvy_l2 with 4 columns (Bx, By, Bz, |B|); ERG MGF names
    # contain mgf/mag plus coordinate labels.
    preferred_groups = [
        ("fgm", "_b_"),
        ("fgm", "b_gse"),
        ("fgm", "b_gsm"),
        ("mgf",),
        ("mag",),
        ("_b_",),
    ]
    for hints in preferred_groups:
        for name, low in lowered:
            if all(hint in low for hint in hints) and not any(bad in low for bad in ("btotal", "b_total", "flag", "status")):
                return name
    # Last resort: any vector-looking B name.
    for name, low in lowered:
        if low.startswith("b_") or "_b" in low or "mag" in low:
            return name
    return None


def _extract_tplot_time_values(payload: Any, tplot_name: str) -> tuple[Any | None, Any]:
    """Return (times, values) from common pyspedas/pytplot get_data shapes."""
    times = None
    values = None
    if isinstance(payload, dict):
        for key in ("times", "time", "x"):
            if key in payload:
                times = payload[key]
                break
        for key in ("y", "data", "values", "b"):
            if key in payload:
                values = payload[key]
                break
    else:
        for key in ("times", "time", "x"):
            if hasattr(payload, key):
                times = getattr(payload, key)
                break
        for key in ("y", "data", "values", "b"):
            if hasattr(payload, key):
                values = getattr(payload, key)
                break
        if (times is None or values is None) and isinstance(payload, (list, tuple)) and len(payload) >= 2:
            times = payload[0]
            values = payload[1]
    if values is None:
        raise ValueError(
            f"tplot variable '{tplot_name}' did not expose numeric y/data values via get_data"
        )
    return times, values


def _coerce_mag_values(values: Any, tplot_name: str, n_source_times: int | None = None) -> Any:
    import numpy as np

    arr = np.asarray(values, dtype="float64")
    if arr.size == 0:
        raise ValueError(f"magnetic tplot variable '{tplot_name}' is empty")
    if arr.ndim > 2:
        arr = arr.reshape(arr.shape[0], -1)
    if arr.ndim == 1:
        if arr.shape == (3,):
            return arr.reshape(1, 3)
        raise ValueError(
            f"magnetic tplot variable '{tplot_name}' must provide vector B data; got 1D length {arr.shape[0]}"
        )
    if arr.ndim != 2:
        raise ValueError(f"magnetic tplot variable '{tplot_name}' has unsupported ndim {arr.ndim}")
    if n_source_times is not None:
        if arr.shape[0] == n_source_times and arr.shape[1] >= 3:
            return arr[:, :3]
        if arr.shape[1] == n_source_times and arr.shape[0] >= 3:
            return arr[:3, :].T
    if arr.shape[1] >= 3:
        return arr[:, :3]
    if arr.shape[0] >= 3:
        return arr[:3, :].T
    raise ValueError(
        f"magnetic tplot variable '{tplot_name}' must have at least 3 vector components; got shape {arr.shape}"
    )


def _magf_from_tplot(tplot_name: str, target_times: Any) -> tuple[Any, dict[str, Any]]:
    """Extract/interpolate a tplot B variable to distribution-slice times."""
    import numpy as np

    try:
        from pyspedas import get_data
    except Exception as exc:  # pragma: no cover - exercised through dependency gate
        raise ParticleBackendError(
            f"pyspedas get_data is unavailable; cannot read magnetic tplot variable '{tplot_name}'"
        ) from exc

    payload = get_data(tplot_name)
    if payload is None or (isinstance(payload, (int, float)) and payload == 0):
        raise ValueError(
            f"mag_tplot_name '{tplot_name}' is not loaded or has no retrievable tplot data"
        )
    raw_times, raw_values = _extract_tplot_time_values(payload, tplot_name)
    source_times = None
    if raw_times is not None:
        source_times = np.asarray(raw_times, dtype="float64").reshape(-1)
        if source_times.size == 0:
            source_times = None
        elif not np.all(np.isfinite(source_times)):
            raise ValueError(f"mag_tplot_name '{tplot_name}' has non-finite time values")

    mag = _coerce_mag_values(
        raw_values,
        tplot_name,
        n_source_times=None if source_times is None else int(source_times.size),
    )
    if not np.all(np.isfinite(mag)):
        raise ValueError(f"mag_tplot_name '{tplot_name}' contains non-finite B values")

    target = np.asarray(target_times, dtype="float64").reshape(-1)
    if target.size == 0:
        raise ValueError("cannot interpolate magnetic field for zero distribution slices")
    if not np.all(np.isfinite(target)):
        raise ValueError("distribution times contain non-finite values; cannot align magnetic field")

    meta: dict[str, Any] = {
        "mode": "tplot",
        "tplot_name": tplot_name,
        "target_time_range": _finite_range(target),
    }

    if source_times is None:
        if mag.shape[0] == 1:
            out = np.broadcast_to(mag[0], (target.size, 3)).copy()
            meta.update({"n_source_samples": 1, "interpolated": False, "broadcast": True})
            return out, meta
        if mag.shape[0] != target.size:
            raise ValueError(
                f"mag_tplot_name '{tplot_name}' has {mag.shape[0]} B samples and no time axis; "
                f"expected 1 or {target.size} samples"
            )
        meta.update({"n_source_samples": int(mag.shape[0]), "interpolated": False, "matched_by_index": True})
        return mag, meta

    if source_times.size != mag.shape[0]:
        raise ValueError(
            f"mag_tplot_name '{tplot_name}' has {source_times.size} times but {mag.shape[0]} B samples"
        )
    if source_times.size == 1:
        out = np.broadcast_to(mag[0], (target.size, 3)).copy()
        meta.update({
            "n_source_samples": 1,
            "source_time_range": _finite_range(source_times),
            "interpolated": False,
            "broadcast": True,
        })
        return out, meta

    order = np.argsort(source_times)
    source_times = source_times[order]
    mag = mag[order]
    keep = np.concatenate(([True], np.diff(source_times) > 0))
    source_times = source_times[keep]
    mag = mag[keep]
    if source_times.size == 1:
        out = np.broadcast_to(mag[0], (target.size, 3)).copy()
        meta.update({
            "n_source_samples": 1,
            "source_time_range": _finite_range(source_times),
            "interpolated": False,
            "broadcast": True,
        })
        return out, meta

    outside = bool(np.any((target < source_times[0]) | (target > source_times[-1])))
    if outside:
        raise ValueError(
            f"mag_tplot_name '{tplot_name}' time coverage {_finite_range(source_times)} "
            f"does not bracket distribution times {_finite_range(target)}; pass a B-field "
            "tplot/loader interval that covers every output slice"
        )
    out = np.column_stack([np.interp(target, source_times, mag[:, i]) for i in range(3)])
    same_grid = source_times.size == target.size and bool(np.allclose(source_times, target, rtol=0.0, atol=1e-9))
    meta.update({
        "n_source_samples": int(source_times.size),
        "source_time_range": _finite_range(source_times),
        "interpolated": not same_grid,
        "outside_source_time_range": False,
    })
    return out, meta


def _as_float_array(value: Any, field: str) -> Any:
    import numpy as np

    arr = np.asarray(value, dtype="float64")
    if arr.size == 0:
        raise ValueError(f"converter field '{field}' is empty")
    return arr


def _flatten_particle_grid(value: Any, field: str) -> Any:
    """Return one per-slice field as an ``(E,A)`` array.

    PySPEDAS mission converters commonly return per-slice arrays as
    ``(energy, phi, theta)``. The MCP distribution schema stores all angular bins
    in one flattened ``A`` dimension, which is exactly what the downstream
    particle routines already accept.
    """
    arr = _as_float_array(value, field)
    if arr.ndim == 2:
        return arr
    if arr.ndim == 3:
        return arr.reshape(arr.shape[0], -1)
    raise ValueError(
        f"converter field '{field}' must be 2D (E,A) or 3D (E,*,*); got shape {arr.shape}"
    )


def _coerce_distribution_records(result: Any) -> list[dict[str, Any]]:
    if result is None or (isinstance(result, (int, float)) and result == 0):
        raise ValueError("pyspedas distribution converter returned no data")
    if isinstance(result, dict):
        records = [result]
    elif isinstance(result, (list, tuple)):
        records = list(result)
    else:
        raise ValueError(
            f"pyspedas distribution converter returned {type(result).__name__}; expected dict or list[dict]"
        )
    if not records or not all(isinstance(r, dict) for r in records):
        raise ValueError("pyspedas distribution converter output must be a non-empty dict/list of dicts")
    return records


def _converter_kwargs(fn: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Filter optional kwargs to those accepted by the selected converter."""
    import inspect

    sig = inspect.signature(fn)
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
        return {k: v for k, v in kwargs.items() if v is not None}
    return {k: v for k, v in kwargs.items() if v is not None and k in sig.parameters}


def build_particle_distribution_artifact(
    tplot_name: str,
    output_file: str,
    converter: str = "mms_fpi",
    *,
    index: int | list[int] | None = None,
    probe: str | None = None,
    data_rate: str | None = None,
    species: str | None = None,
    level: str | None = None,
    units: str | None = None,
    trange: list[str] | None = None,
    single_time: str | None = None,
    magf: list[float] | list[list[float]] | None = None,
    mag_tplot_name: str | None = None,
    max_slices: int | None = 32,
) -> dict[str, Any]:
    """Bridge pyspedas mission distribution converters into ``DIST_SCHEMA_DOC``.

    This is the small issue-#95 gate: real mission CDFs are still loaded by the
    normal pyspedas mission loaders into tplot variables, then this helper calls
    the mission's particle ``*_get_dist`` converter and writes the MCP-standard
    ``.npz`` distribution artifact consumed by :func:`compute_particle_moments`
    and :func:`compute_particle_spectra`. Bulk arrays are written to disk; the
    return value contains paths, shapes, ranges, and provenance only.

    The downstream distribution schema requires ``magf``. Supply it directly as
    one ``[Bx,By,Bz]`` vector or one vector per output slice, or pass
    ``mag_tplot_name`` for an already-loaded B-field tplot variable that will be
    interpolated to the output slice times. The B-field time coverage must bracket
    every output slice; the bridge does not silently extrapolate endpoint values.
    """
    import numpy as np

    if converter not in _DIST_CONVERTERS:
        return _error(
            f"unsupported particle distribution converter '{converter}'",
            valid_converters=sorted(_DIST_CONVERTERS),
            hint="Use one of the pyspedas-backed converter keys, e.g. mms_fpi, mms_hpca, erg_mepi.",
        )
    if not tplot_name:
        return _error("tplot_name is required")
    if max_slices is not None and max_slices <= 0:
        return _error("max_slices must be positive or null")
    if magf is None and not mag_tplot_name:
        return _error(
            "magf or mag_tplot_name is required to write a valid particle distribution artifact",
            hint="Pass magf=[Bx,By,Bz], magf=[[...], ...] with one vector per slice, or mag_tplot_name='...' for a loaded B-field tplot variable.",
        )

    try:
        require_pyspedas()
        module_path, attr = _DIST_CONVERTERS[converter]
        fn = _require_attr(module_path, attr)
        kwargs = _converter_kwargs(fn, {
            "index": index,
            "probe": probe,
            "data_rate": data_rate,
            "species": species,
            "level": level,
            "units": units,
            "trange": trange,
            "single_time": single_time,
        })
        result = fn(tplot_name, **kwargs)
        records = _coerce_distribution_records(result)
        original_n_records = len(records)
        if max_slices is not None and len(records) > max_slices:
            records = records[:max_slices]

        fields = ("data", "energy", "denergy", "theta", "dtheta", "phi", "dphi", "bins")
        missing = sorted({f for f in fields if f not in records[0]})
        missing += [f for f in ("charge", "mass") if f not in records[0]]
        if missing:
            raise ValueError(
                f"converter '{converter}' ({module_path}.{attr}) output record is "
                f"missing required field(s): {sorted(set(missing))}. Present keys: "
                f"{sorted(records[0].keys())}. A real *_get_dist record must supply "
                f"{sorted(set(fields) | {'charge', 'mass'})}."
            )

        stacked = {field: np.stack([_flatten_particle_grid(r[field], field) for r in records], axis=0) for field in fields}
        shape = stacked["data"].shape
        for field, arr in stacked.items():
            if arr.shape != shape:
                raise ValueError(f"converter field '{field}' shape {arr.shape} does not match data shape {shape}")

        times = np.asarray([r.get("start_time", r.get("time", i)) for i, r in enumerate(records)], dtype="float64")
        if magf is None:
            mag, magf_source = _magf_from_tplot(str(mag_tplot_name), times)
        else:
            mag = np.asarray(magf, dtype="float64")
            if mag.ndim == 1:
                if mag.shape != (3,):
                    raise ValueError(f"magf must be a (3,) vector or (T,3) array; got {mag.shape}")
                mag = np.broadcast_to(mag, (len(records), 3)).copy()
            elif mag.ndim == 2:
                if mag.shape != (len(records), 3):
                    raise ValueError(f"magf must have one (Bx,By,Bz) vector per slice; got {mag.shape}, expected {(len(records), 3)}")
            else:
                raise ValueError(f"magf must be a (3,) vector or (T,3) array; got ndim {mag.ndim}")
            if not np.all(np.isfinite(mag)):
                raise ValueError("magf contains non-finite values")
            magf_source = {"mode": "argument", "broadcast": bool(np.asarray(magf).ndim == 1)}

        out_path = Path(output_file)
        if out_path.suffix.lower() != ".npz":
            raise ValueError("output_file must end with .npz")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        np.savez(
            out_path,
            times=times,
            magf=mag,
            charge=float(np.asarray(records[0]["charge"]).reshape(-1)[0]),
            mass=float(np.asarray(records[0]["mass"]).reshape(-1)[0]),
            **stacked,
        )
        # Validate the written artifact against the same schema used by the
        # downstream tools, catching bridge drift before returning success.
        raw = _load_distribution(str(out_path))
        _normalize_distribution(raw, _MOMENTS_REQUIRED)

        meta = {
            "tool": "build_particle_distribution_artifact",
            "converter": converter,
            "converter_backend": f"{module_path}.{attr}",
            "tplot_name": tplot_name,
            "n_time": len(records),
            "shape": list(shape),
            "time_range": _finite_range(times),
            "energy_range_ev": _finite_range(stacked["energy"]),
            "data_range": _finite_range(stacked["data"]),
            "output_file": str(out_path),
            "schema": "DIST_SCHEMA_DOC",
            "schema_keys": ["times", *fields, "magf", "charge", "mass"],
            "magf_source": magf_source,
            "truncated_to_max_slices": bool(max_slices is not None and original_n_records > len(records)),
            "converter_kwargs": kwargs,
        }
        meta_path = out_path.with_suffix(".json")
        meta_path.write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")
        return {"status": "success", **meta, "metadata_file": str(meta_path)}
    except AnalysisDependencyError as exc:
        return _error(
            str(exc),
            code="dependency_missing",
            hint="Install optional analysis dependencies with: pip install 'spedas-agent-kit[analysis]'",
        )
    except ParticleBackendError as exc:
        return _error(str(exc), code="unsupported", valid_converters=sorted(_DIST_CONVERTERS))
    except Exception as exc:
        return _error(str(exc), code="invalid_argument", schema=DIST_SCHEMA_DOC)


def _load_mag(mag_file: str, n_time: int) -> Any:
    """Load the B-field reference into a ``(n_time, 3)`` float array.

    Accepts the same .npz/.json containers as the distribution (see
    :data:`MAG_SCHEMA_DOC`). A single ``(3,)`` vector is broadcast across all
    slices; a ``(T, 3)`` array must have ``T == n_time``.

    Raises
    ------
    ValueError
        If the file is missing/unparseable, lacks ``'b'``, or has an
        incompatible shape.
    """
    import numpy as np

    raw = _load_distribution(mag_file)  # reuses the .npz/.json loader + checks
    if "b" not in raw:
        raise ValueError(f"mag_file is missing required field 'b'. {MAG_SCHEMA_DOC}")
    b = np.asarray(raw["b"], dtype="float64")
    if b.ndim == 1:
        if b.shape[0] != 3:
            raise ValueError(
                f"mag_file 'b' 1D vector must have length 3; got {b.shape[0]}. "
                f"{MAG_SCHEMA_DOC}"
            )
        b = np.broadcast_to(b, (n_time, 3)).copy()
    elif b.ndim == 2:
        if b.shape[1] != 3:
            raise ValueError(
                f"mag_file 'b' 2D array must be (T,3); got {b.shape}. {MAG_SCHEMA_DOC}"
            )
        if b.shape[0] != n_time:
            raise ValueError(
                f"mag_file 'b' has {b.shape[0]} time samples but the distribution "
                f"has {n_time}; supply one B vector per slice (or a single (3,) "
                "vector to broadcast)."
            )
    else:
        raise ValueError(
            f"mag_file 'b' must be 1D (3,) or 2D (T,3); got ndim {b.ndim}. "
            f"{MAG_SCHEMA_DOC}"
        )
    return b


def _fac_matrix(b_vec: Any) -> Any:
    """Build a 3x3 field-aligned rotation matrix with +z along ``b_vec``.

    Rows are the FAC basis vectors (x, y, z) expressed in the input frame, so
    ``mat @ v`` rotates a vector ``v`` into FAC. The x/y reference axes are
    chosen by a stable Gram-Schmidt against a fixed seed; only the polar
    (pitch) angle about +z = B is used downstream, and that is invariant to the
    azimuthal reference, so the seed choice does not affect pitch-angle results.

    Raises
    ------
    ValueError
        If ``b_vec`` has (near) zero magnitude (no defined direction).
    """
    import numpy as np

    b = np.asarray(b_vec, dtype="float64").reshape(-1)
    norm = float(np.linalg.norm(b))
    if not np.isfinite(norm) or norm == 0.0:
        raise ValueError(
            "mag_file contains a zero or non-finite B vector; cannot define a "
            "field-aligned direction for the pitch-angle rotation."
        )
    z = b / norm
    seed = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(z, seed))) > 0.99:  # B nearly parallel to seed: re-seed
        seed = np.array([0.0, 1.0, 0.0])
    x = np.cross(seed, z)
    x = x / np.linalg.norm(x)
    y = np.cross(z, x)
    return np.vstack([x, y, z])


# --------------------------------------------------------------------------


def load_particle_distribution_artifact(
    output_file: str,
    converter: str = "mms_fpi",
    *,
    trange: list[str] | None = None,
    tplot_name: str | None = None,
    loader_module: str | None = None,
    loader_function: str | None = None,
    loader_kwargs: dict[str, Any] | None = None,
    mag_tplot_name: str | None = None,
    mag_loader_module: str | None = None,
    mag_loader_function: str | None = None,
    mag_loader_kwargs: dict[str, Any] | None = None,
    index: int | list[int] | None = None,
    probe: str | None = None,
    data_rate: str | None = None,
    species: str | None = None,
    level: str | None = None,
    units: str | None = None,
    single_time: str | None = None,
    magf: list[float] | list[list[float]] | None = None,
    max_slices: int | None = 32,
) -> dict[str, Any]:
    """Load/fetch mission CDFs, convert tplot distribution, and write schema artifact."""
    if converter not in _DIST_CONVERTERS:
        return _error(
            f"unsupported particle distribution converter '{converter}'",
            valid_converters=sorted(_DIST_CONVERTERS),
        )
    if max_slices is not None and max_slices <= 0:
        return _error("max_slices must be positive or null")
    if (loader_module is None) != (loader_function is None):
        return _error(
            "loader_module and loader_function must be provided together",
            code="invalid_argument",
            hint="Pass both loader_module and loader_function, or omit both to use the default loader mapping.",
        )
    if (mag_loader_module is None) != (mag_loader_function is None):
        return _error(
            "mag_loader_module and mag_loader_function must be provided together",
            code="invalid_argument",
            hint="Pass both mag_loader_module and mag_loader_function, or omit both to use the default magnetic-field loader mapping.",
        )
    try:
        require_pyspedas()
        if loader_module is None or loader_function is None:
            if converter not in _DIST_LOADERS:
                return _error(
                    f"no default pyspedas loader is registered for converter '{converter}'",
                    code="unsupported",
                    hint="Pass loader_module and loader_function to use a mission/product-specific pyspedas loader.",
                )
            default_module, default_function, defaults = _DIST_LOADERS[converter]
            loader_module = loader_module or default_module
            loader_function = loader_function or default_function
            defaults = dict(defaults)
        else:
            defaults = {}

        load_fn = _require_attr(loader_module, loader_function)
        effective_loader_kwargs = _merge_loader_kwargs(defaults, loader_kwargs)
        if trange is not None:
            effective_loader_kwargs["trange"] = trange
        effective_loader_kwargs = _merge_loader_kwargs(
            effective_loader_kwargs,
            {"probe": probe, "data_rate": data_rate, "level": level},
        )
        effective_loader_kwargs = _converter_kwargs(load_fn, effective_loader_kwargs)
        loaded_result = load_fn(**effective_loader_kwargs)
        loaded_tplot_names = _coerce_loaded_tplot_names(loaded_result)
        selected_tplot = tplot_name or _guess_distribution_tplot_name(loaded_tplot_names, converter)
        if not selected_tplot:
            raise ValueError(
                "pyspedas loader did not report any tplot variables; pass tplot_name "
                "explicitly or adjust loader_kwargs/varformat/varnames"
            )

        selected_mag_tplot = mag_tplot_name
        loaded_mag_tplot_names: list[str] = []
        mag_loader_backend = None
        effective_mag_loader_kwargs: dict[str, Any] = {}
        if magf is None and selected_mag_tplot is None:
            selected_mag_tplot = _guess_mag_tplot_name(loaded_tplot_names, converter)
        if magf is None and selected_mag_tplot is None:
            if mag_loader_module is None or mag_loader_function is None:
                if converter in _DIST_MAG_LOADERS:
                    mag_loader_module, mag_loader_function, mag_defaults = _DIST_MAG_LOADERS[converter]
                    mag_defaults = dict(mag_defaults)
                else:
                    mag_defaults = {}
            else:
                mag_defaults = {}
            if mag_loader_module and mag_loader_function:
                mag_load_fn = _require_attr(mag_loader_module, mag_loader_function)
                effective_mag_loader_kwargs = _merge_loader_kwargs(mag_defaults, mag_loader_kwargs)
                if trange is not None:
                    effective_mag_loader_kwargs["trange"] = trange
                effective_mag_loader_kwargs = _merge_loader_kwargs(
                    effective_mag_loader_kwargs,
                    {"probe": probe, "level": level},
                )
                effective_mag_loader_kwargs = _converter_kwargs(mag_load_fn, effective_mag_loader_kwargs)
                loaded_mag_result = mag_load_fn(**effective_mag_loader_kwargs)
                loaded_mag_tplot_names = _coerce_loaded_tplot_names(loaded_mag_result)
                selected_mag_tplot = _guess_mag_tplot_name(loaded_mag_tplot_names, converter)
                mag_loader_backend = f"{mag_loader_module}.{mag_loader_function}"
        if magf is None and selected_mag_tplot is None:
            return _error(
                "no magnetic-field tplot variable was available to populate magf",
                code="needs_input",
                hint="Pass magf, mag_tplot_name, or mag_loader_module/mag_loader_function/mag_loader_kwargs so the bridge can write the required magf field.",
                loaded_tplot_names=loaded_tplot_names,
                loaded_mag_tplot_names=loaded_mag_tplot_names,
            )

        bridge = build_particle_distribution_artifact(
            selected_tplot,
            output_file,
            converter=converter,
            index=index,
            probe=probe,
            data_rate=data_rate,
            species=species,
            level=level,
            units=units,
            trange=trange,
            single_time=single_time,
            magf=magf,
            mag_tplot_name=selected_mag_tplot,
            max_slices=max_slices,
        )
        provenance = {
            "loader_backend": f"{loader_module}.{loader_function}",
            "loader_kwargs": effective_loader_kwargs,
            "loaded_tplot_names": loaded_tplot_names,
            "selected_tplot_name": selected_tplot,
            "mag_loader_backend": mag_loader_backend,
            "mag_loader_kwargs": effective_mag_loader_kwargs,
            "loaded_mag_tplot_names": loaded_mag_tplot_names,
            "selected_mag_tplot_name": selected_mag_tplot,
        }
        if bridge.get("status") != "success":
            return {**bridge, **provenance}
        metadata_file = bridge.get("metadata_file")
        if metadata_file:
            meta_path = Path(str(metadata_file))
            if meta_path.exists():
                sidecar = json.loads(meta_path.read_text(encoding="utf-8"))
                sidecar.update({"tool": "load_particle_distribution_artifact", **provenance})
                meta_path.write_text(json.dumps(sidecar, indent=2, default=str), encoding="utf-8")
        return {**bridge, "tool": "load_particle_distribution_artifact", **provenance}
    except AnalysisDependencyError as exc:
        return _error(
            str(exc),
            code="dependency_missing",
            hint="Install optional analysis dependencies with: pip install 'spedas-agent-kit[analysis]'",
        )
    except ParticleBackendError as exc:
        return _error(str(exc), code="unsupported", valid_converters=sorted(_DIST_CONVERTERS))
    except Exception as exc:
        return _error(str(exc), code="invalid_argument", schema=DIST_SCHEMA_DOC)

# Issue #18 - particle moments
# --------------------------------------------------------------------------

# Per-column units for the moments artifact (pyspedas ``moments_3d`` units, the
# same ones echoed in the return note). Velocity/temperature/pressure/flux are
# vector/tensor components that share a unit. Used to write the self-describing
# sidecar consumed by render_tplot (issue #154).
_MOMENTS_COLUMN_UNITS: dict[str, str] = {
    "time": "s",
    "density": "cm^-3",
    "vx": "km/s",
    "vy": "km/s",
    "vz": "km/s",
    "avgtemp": "eV",
    "txx": "eV",
    "tyy": "eV",
    "tzz": "eV",
    "pxx": "eV/cm^3",
    "pyy": "eV/cm^3",
    "pzz": "eV/cm^3",
    "pxy": "eV/cm^3",
    "pxz": "eV/cm^3",
    "pyz": "eV/cm^3",
    "fx": "eV/(cm^2 s sr)",
    "fy": "eV/(cm^2 s sr)",
    "fz": "eV/(cm^2 s sr)",
}


def _write_moments_labels_sidecar(
    moments_path: Path, columns: list[str], *, no_unit_conversion: bool
) -> Path:
    """Write a ``<artifact>.labels.json`` sidecar describing moments columns.

    The sidecar carries a per-column ``units`` map plus top-level
    ``axis_label`` / ``axis_units`` hints. Because the moments artifact mixes
    physically different quantities (density, velocity, temperature, pressure)
    on its columns, no single y-axis label is correct; ``axis_label`` therefore
    names the multi-quantity nature and ``axis_units`` is intentionally omitted
    so ``render_tplot`` does not stamp a misleading single unit on the axis. The
    per-column ``units`` map is the recoverable source of truth (issue #154).

    When ``no_unit_conversion`` is set the backend returns raw counts-based
    units, so the unit strings are flagged as such rather than asserted.
    """
    sidecar_path = moments_path.with_name(moments_path.name + ".labels.json")
    if no_unit_conversion:
        units = {col: "raw (no_unit_conversion)" for col in columns}
        axis_label = "particle moments (raw, multiple quantities)"
    else:
        units = {col: _MOMENTS_COLUMN_UNITS.get(col, "") for col in columns}
        axis_label = "particle moments (multiple quantities)"
    payload = {
        "axis_label": axis_label,
        # No single axis_units: the columns carry distinct units (see below).
        "value_label": "particle moments",
        "columns": units,
        "note": (
            "Per-column units for the moments time series. Density cm^-3, "
            "velocity km/s, temperature eV, pressure eV/cm^3, flux "
            "eV/(cm^2 s sr) under pyspedas moments_3d unit conversion. Multiple "
            "quantities share one artifact, so render_tplot intentionally does "
            "not stamp a single y-axis unit; use this map to label individual "
            "channels."
        ),
    }
    sidecar_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return sidecar_path


def compute_particle_moments(
    dist_file: str,
    output_dir: str,
    sc_potential_v: float = 0.0,
    energy_range_ev: list[float] | None = None,
    output_format: str = "json",
    no_unit_conversion: bool = False,
) -> dict[str, Any]:
    """Plasma moments (n, V, T, P, q) from a 3D distribution time series (#18).

    Backend: ``pyspedas.particles.moments.moments_3d`` applied per time slice.
    Reads the explicit distribution artifact (see the module ``DIST_SCHEMA_DOC``),
    optionally restricts to ``energy_range_ev`` and applies the spacecraft
    potential ``sc_potential_v``, computes density / velocity / temperature /
    pressure tensor (and heat-flux-related quantities) for each slice, writes the
    full moment time series to ``output_dir`` (CSV or JSON), and returns compact
    **scalar summaries** plus the artifact path only. Full pressure/temperature
    tensors and particle cubes are never returned inline. Requires
    ``spedas-agent-kit[analysis]``.
    """
    fmt = (output_format or "").strip().lower()
    if fmt not in ("csv", "json"):
        return _error(
            f"unsupported output_format '{output_format}'; use 'csv' or 'json'",
            valid_formats=["csv", "json"],
        )
    if energy_range_ev is not None:
        if len(energy_range_ev) != 2:
            return _error("energy_range_ev must be [min_ev, max_ev]")
        lo, hi = float(energy_range_ev[0]), float(energy_range_ev[1])
        if not (lo < hi):
            return _error(
                f"energy_range_ev min ({lo}) must be < max ({hi})"
            )

    try:
        require_pyspedas()
        moments_3d = _require_attr(
            "pyspedas.particles.moments.moments_3d", "moments_3d"
        )
    except AnalysisDependencyError as exc:
        code = "unsupported" if isinstance(exc, ParticleBackendError) else "dependency_missing"
        return _error(str(exc), code=code)

    try:
        import numpy as np

        raw = _load_distribution(dist_file)
        times, cubes, scalars, n_time = _normalize_distribution(raw, _MOMENTS_REQUIRED)
    except ValueError as exc:
        return _error(str(exc))

    # Pre-compute an energy mask (per-slice) when a range is requested. moments_3d
    # honors only the bins flagged active, so we restrict by zeroing the 'bins'
    # flag outside the band rather than mutating the physical arrays.
    energy_mask_band = None
    if energy_range_ev is not None:
        lo, hi = float(energy_range_ev[0]), float(energy_range_ev[1])
        energy_mask_band = (lo, hi)

    rows: list[dict[str, Any]] = []
    for i in range(n_time):
        slice_in = _slice_dict(cubes, scalars, i)
        if energy_mask_band is not None:
            lo, hi = energy_mask_band
            energy = np.asarray(slice_in["energy"], dtype="float64")
            band = (energy >= lo) & (energy <= hi)
            slice_in["bins"] = np.asarray(slice_in["bins"], dtype="float64") * band

        try:
            m = moments_3d(slice_in, sc_pot=float(sc_potential_v),
                           no_unit_conversion=bool(no_unit_conversion))
        except Exception as exc:  # noqa: BLE001 - convert backend failure to envelope
            return _error(
                f"moments_3d failed on slice {i}: {exc}",
                code="backend_error",
                slice_index=i,
            )

        velocity = np.asarray(m["velocity"], dtype="float64").reshape(-1)
        ptens = np.asarray(m["ptens"], dtype="float64").reshape(-1)  # 6: xx,yy,zz,xy,xz,yz
        ttens = np.asarray(m["ttens"], dtype="float64")  # 3x3
        flux = np.asarray(m["flux"], dtype="float64").reshape(-1)
        rows.append(
            {
                "time": float(times[i]),
                "density": float(m["density"]),
                "vx": float(velocity[0]),
                "vy": float(velocity[1]),
                "vz": float(velocity[2]),
                "avgtemp": float(m["avgtemp"]),
                "txx": float(ttens[0, 0]),
                "tyy": float(ttens[1, 1]),
                "tzz": float(ttens[2, 2]),
                "pxx": float(ptens[0]),
                "pyy": float(ptens[1]),
                "pzz": float(ptens[2]),
                "pxy": float(ptens[3]),
                "pxz": float(ptens[4]),
                "pyz": float(ptens[5]),
                "fx": float(flux[0]),
                "fy": float(flux[1]),
                "fz": float(flux[2]),
            }
        )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "json":
        moments_path = out_dir / "particle_moments.json"
        columns: dict[str, list[float]] = {k: [r[k] for r in rows] for k in rows[0]}
        moments_path.write_text(json.dumps(columns), encoding="utf-8")
    else:
        moments_path = out_dir / "particle_moments.csv"
        import csv

        with moments_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)

    # Persist a self-describing units/labels sidecar next to the artifact so a
    # renderer (render_tplot) or a human can recover per-column units instead of
    # reading multiple physical quantities off one unlabeled axis (issue #154).
    # The convention is a sibling ``<artifact-name>.labels.json``; moments_3d
    # uses the units echoed in this tool's return note.
    sidecar_path = _write_moments_labels_sidecar(
        moments_path, list(rows[0].keys()), no_unit_conversion=bool(no_unit_conversion)
    )

    density = np.array([r["density"] for r in rows], dtype="float64")
    speed = np.array(
        [float(np.sqrt(r["vx"] ** 2 + r["vy"] ** 2 + r["vz"] ** 2)) for r in rows],
        dtype="float64",
    )
    avgtemp = np.array([r["avgtemp"] for r in rows], dtype="float64")
    p_trace = np.array([r["pxx"] + r["pyy"] + r["pzz"] for r in rows], dtype="float64")

    return {
        "status": "success",
        "tool": "compute_particle_moments",
        "moments_file": str(moments_path),
        "labels_file": str(sidecar_path),
        "output_format": fmt,
        "n_time": int(n_time),
        "time_range": _finite_range(times),
        "sc_potential_v": float(sc_potential_v),
        "energy_range_ev": [float(energy_range_ev[0]), float(energy_range_ev[1])]
        if energy_range_ev is not None
        else None,
        "density_summary": _finite_stats(density),
        "velocity_summary": _finite_stats(speed),
        "temperature_summary": _finite_stats(avgtemp),
        "pressure_tensor_summary": {
            "components": ["pxx", "pyy", "pzz", "pxy", "pxz", "pyz"],
            "trace": _finite_stats(p_trace),
            "note": (
                "Per-slice pressure tensor (6 components) and full 3x3 temperature "
                "tensor are written to the moments artifact; only the scalar "
                "pressure-trace summary is returned inline."
            ),
        },
        "columns": list(rows[0].keys()),
        "note": (
            "Density in cm^-3, velocity in km/s, temperature in eV, pressure in "
            "eV/cm^3 (pyspedas moments_3d units). Full time series in the artifact; "
            "this tool returns scalar summaries only."
        ),
    }


# --------------------------------------------------------------------------
# Issue #19 - particle spectra
# --------------------------------------------------------------------------

def _resolve_spectrum_types(spectrum_types: list[str]) -> tuple[list[str], list[str]]:
    """Map requested spectrum types through aliases; return (resolved, unknown)."""
    resolved: list[str] = []
    unknown: list[str] = []
    for raw in spectrum_types:
        key = (raw or "").strip().lower()
        key = _SPECTRUM_ALIASES.get(key, key)
        if key in _KNOWN_SPECTRA:
            if key not in resolved:
                resolved.append(key)
        else:
            unknown.append(raw)
    return resolved, unknown


def compute_particle_spectra(
    dist_file: str,
    output_dir: str,
    spectrum_types: list[str] | None = None,
    mag_file: str | None = None,
    resolution: int | None = None,
) -> dict[str, Any]:
    """Energy / azimuth / elevation / pitch-angle spectrograms from a distribution (#19).

    Backends: ``pyspedas`` ``spd_pgs_make_e_spec`` (energy), ``spd_pgs_make_phi_spec``
    (azimuth/phi), ``spd_pgs_make_theta_spec`` (elevation/theta). Each averages the
    distribution over the complementary dimensions per time slice to build a
    ``(n_time, n_bin)`` spectrogram. Field-aligned **pitch_angle** spectra need a
    magnetic-field reference, resolved in priority order (issue #148): an explicit
    ``mag_file`` (see :data:`MAG_SCHEMA_DOC`) if given, otherwise the ``magf``
    vectors embedded in the distribution artifact by the #95 bridge. Each slice is
    rotated into field-aligned coordinates with ``spd_pgs_do_fac`` (B as +z) and
    the resulting polar (pitch) angle is binned over 0-180 deg via
    ``spd_pgs_make_theta_spec`` in colatitude mode. When neither a ``mag_file``
    nor embedded ``magf`` is available the pitch-angle entry reports
    ``needs_input`` instead of failing the whole call; the rest of the requested
    spectra still compute. The pitch-angle entry's ``mag_source`` field records
    which B reference was used (``mag_file`` / ``distribution_artifact_magf`` /
    ``missing``).

    Each spectrogram matrix (with its axes) is written to ``output_dir`` as a
    compressed ``.npz``; only paths plus ranges/shapes are returned (artifact-
    first). Requires ``spedas-agent-kit[analysis]``.
    """
    requested = spectrum_types if spectrum_types is not None else ["energy", "pitch_angle"]
    if not isinstance(requested, list) or not requested:
        return _error("spectrum_types must be a non-empty list of strings")

    resolved, unknown = _resolve_spectrum_types(requested)
    if unknown:
        return _error(
            f"unknown spectrum_type(s): {unknown}",
            code="invalid_argument",
            valid_spectrum_types=list(_KNOWN_SPECTRA),
            accepted_aliases=_SPECTRUM_ALIASES,
        )
    if not resolved:
        return _error("no valid spectrum types requested")
    if resolution is not None and resolution <= 0:
        return _error("resolution must be a positive integer when provided")

    try:
        require_pyspedas()
    except AnalysisDependencyError as exc:
        return _error(str(exc), code="dependency_missing")

    try:
        import numpy as np

        # Only the union of fields actually needed by the resolved spectra is
        # required; this lets a caller compute an energy spectrum from a leaner
        # artifact than a full pitch-angle pipeline would demand.
        needed: set[str] = set()
        for stype in resolved:
            needed |= _SPECTRA_REQUIRED[stype]
        raw = _load_distribution(dist_file)
        times, cubes, scalars, n_time = _normalize_distribution(raw, needed)
    except ValueError as exc:
        return _error(str(exc))

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Map each spectrum type to (module_path, attr, axis_label, axis_units,
    # extra-kwargs builder). Energy/phi/theta are always-present backends; we
    # still gate each on exact availability.
    spec_backends = {
        "energy": (
            "pyspedas.particles.spd_part_products.spd_pgs_make_e_spec",
            "spd_pgs_make_e_spec",
            "energy",
            "eV",
        ),
        "phi": (
            "pyspedas.particles.spd_part_products.spd_pgs_make_phi_spec",
            "spd_pgs_make_phi_spec",
            "phi",
            "deg",
        ),
        "theta": (
            "pyspedas.particles.spd_part_products.spd_pgs_make_theta_spec",
            "spd_pgs_make_theta_spec",
            "theta",
            "deg",
        ),
    }

    spectra_out: dict[str, Any] = {}

    for stype in resolved:
        if stype == "pitch_angle":
            spectra_out["pitch_angle"] = _pitch_angle_entry(
                cubes, scalars, times, n_time, mag_file, resolution, out_dir
            )
            continue

        module_path, attr, axis_label, axis_units = spec_backends[stype]
        try:
            fn = _require_attr(module_path, attr)
        except ParticleBackendError as exc:
            spectra_out[stype] = {"status": "unsupported", "message": str(exc)}
            continue

        rows: list[Any] = []
        axis_ref: Any = None
        try:
            for i in range(n_time):
                slice_in = _slice_dict(cubes, scalars, i)
                if stype == "energy":
                    y, ave = fn(slice_in)
                else:
                    y, ave = fn(slice_in, resolution=resolution)
                if axis_ref is None:
                    axis_ref = np.asarray(y, dtype="float64")
                rows.append(np.asarray(ave, dtype="float64"))
        except Exception as exc:  # noqa: BLE001 - convert backend failure to envelope
            spectra_out[stype] = {
                "status": "error",
                "code": "backend_error",
                "message": f"{attr} failed: {exc}",
            }
            continue

        spectrogram = np.vstack(rows)  # (n_time, n_bin)
        spec_path = out_dir / f"particle_spectra_{stype}.npz"
        # Persist the axis label/units and a flux (z) label so the standalone
        # artifact is self-describing: render_tplot can label the y-axis and
        # colorbar from these keys instead of falling back to the filename stem
        # (issue #150). Stored as 0-d string arrays; back-compat for older
        # artifacts that omit them is handled on the reader side.
        np.savez_compressed(
            spec_path,
            time=times,
            axis=axis_ref,
            spectrogram=spectrogram,
            axis_label=axis_label,
            axis_units=axis_units,
            value_label="flux",
        )
        spectra_out[stype] = {
            "status": "success",
            "spectrogram_file": str(spec_path),
            "axis_label": axis_label,
            "axis_units": axis_units,
            "shape": list(spectrogram.shape),
            "axis_range": _finite_range(axis_ref),
            "value_range": _finite_range(spectrogram),
        }

    succeeded = [s for s, v in spectra_out.items() if v.get("status") == "success"]

    return {
        "status": "success" if succeeded else "error",
        "tool": "compute_particle_spectra",
        "spectra": spectra_out,
        "requested": resolved,
        "succeeded": succeeded,
        "n_time": int(n_time),
        "time_range": _finite_range(times),
        "resolution": int(resolution) if resolution is not None else None,
        "note": (
            "Each successful spectrum writes a (n_time, n_bin) matrix to its .npz "
            "under key 'spectrogram' with axes 'time' (Unix seconds) and 'axis' "
            "(energy eV / phi deg / theta deg / pitch_angle deg). Pitch-angle "
            "spectra need a B reference: an explicit mag_file (override) or the "
            "'magf' embedded in the distribution artifact; without either, that "
            "entry is 'needs_input'. The pitch_angle entry's 'mag_source' records "
            "which was used. Pair with a renderer to view; this tool returns "
            "paths/ranges/shapes only."
        ),
    }


def _pitch_angle_entry(
    cubes: dict[str, Any],
    scalars: dict[str, Any],
    times: Any,
    n_time: int,
    mag_file: str | None,
    resolution: int | None,
    out_dir: Path,
) -> dict[str, Any]:
    """Compute the field-aligned pitch-angle spectrogram for a distribution (#19).

    Algorithm (per time slice):

    1. Build a field-aligned rotation matrix with +z along that slice's B vector
       (:func:`_fac_matrix`).
    2. Rotate the slice's ``theta``/``phi`` look directions into FAC with
       ``pyspedas`` ``spd_pgs_do_fac``.
    3. Convert the rotated latitude ``theta`` to colatitude (``90 - theta``); the
       colatitude from +z = B *is* the pitch angle. Bin it over 0-180 deg with
       ``spd_pgs_make_theta_spec(..., colatitude=True)``.

    B-field resolution (issue #148). The FAC rotation needs a B reference. It is
    resolved in priority order:

    1. An explicit ``mag_file`` (always wins; ``mag_source="mag_file"``).
    2. The ``magf`` vectors embedded in the distribution artifact when present -
       the #95 bridge already populates ``(T,3)`` ``magf`` from
       ``mag_tplot_name`` / ``magf=`` (``mag_source="distribution_artifact_magf"``).
    3. Neither available -> ``needs_input`` (``mag_source="missing"``).

    Returns a structured per-spectrum entry (this function never raises into the
    caller):

    - ``needs_input`` when no B reference is available (neither ``mag_file`` nor
      embedded ``magf``). This is the documented, valid response - not a stub.
    - ``unsupported`` when this pyspedas build lacks ``spd_pgs_do_fac`` /
      ``spd_pgs_make_theta_spec`` (exact-availability gate, Batch O lesson).
    - ``error`` for a bad/missing ``mag_file`` / unusable embedded ``magf`` or a
      backend failure.
    - ``success`` (with the ``.npz`` artifact path + ranges/shape + provenance)
      otherwise.
    """
    import numpy as np

    embedded_magf = cubes.get("magf")
    mag_source = (
        "mag_file"
        if mag_file is not None
        else ("distribution_artifact_magf" if embedded_magf is not None else "missing")
    )

    if mag_source == "missing":
        return {
            "status": "needs_input",
            "code": "needs_input",
            "mag_source": "missing",
            "message": (
                "pitch-angle spectra require a magnetic-field reference for the "
                "field-aligned-coordinate rotation. None was found: the "
                "distribution artifact carries no embedded 'magf' and no mag_file "
                "was supplied. Provide a distribution artifact with embedded magf "
                "(build_particle_distribution_artifact / "
                "load_particle_distribution_artifact with magf=/mag_tplot_name=) or "
                "pass mag_file (an Nx3 B time series in the distribution's "
                "coordinate frame). " + MAG_SCHEMA_DOC
            ),
        }
    if mag_file is not None and not Path(mag_file).exists():
        return {
            "status": "error",
            "code": "invalid_argument",
            "mag_source": "mag_file",
            "message": f"mag_file does not exist: {mag_file}",
        }

    # Exact-availability gate on the two backends this path actually uses. Both
    # ship in every pyspedas build that has the spectra functions, but gate
    # anyway (package presence != function presence).
    try:
        do_fac = _require_attr(
            "pyspedas.particles.spd_part_products.spd_pgs_do_fac", "spd_pgs_do_fac"
        )
        theta_spec = _require_attr(
            "pyspedas.particles.spd_part_products.spd_pgs_make_theta_spec",
            "spd_pgs_make_theta_spec",
        )
    except ParticleBackendError as exc:
        return {
            "status": "unsupported",
            "code": "unsupported",
            "mag_source": mag_source,
            "message": str(exc),
        }

    try:
        if mag_file is not None:
            # Explicit override: the separate B-field file wins over embedded magf.
            b = _load_mag(mag_file, n_time)
        else:
            # Fall back to the (T,3) magf already normalized into the cubes by
            # _normalize_distribution (issue #148). Shape was validated there.
            b = np.asarray(embedded_magf, dtype="float64")
    except ValueError as exc:
        return {
            "status": "error",
            "code": "invalid_argument",
            "mag_source": mag_source,
            "message": str(exc),
        }

    n_pa = resolution if resolution is not None else _DEFAULT_PAD_BINS

    rows: list[Any] = []
    axis_ref: Any = None
    try:
        for i in range(n_time):
            mat = _fac_matrix(b[i])
            slice_in = _slice_dict(cubes, scalars, i)
            rotated = do_fac(slice_in, mat)
            # FAC latitude theta (-90..90 from the B-perp plane) -> pitch-angle
            # colatitude (0..180 from +B).
            rotated = dict(rotated)
            rotated["theta"] = 90.0 - np.asarray(rotated["theta"], dtype="float64")
            y, ave = theta_spec(rotated, resolution=n_pa, colatitude=True)
            if axis_ref is None:
                axis_ref = np.asarray(y, dtype="float64")
            rows.append(np.asarray(ave, dtype="float64"))
    except ValueError as exc:
        # _fac_matrix raises ValueError on a zero/non-finite B vector.
        return {
            "status": "error",
            "code": "invalid_argument",
            "mag_source": mag_source,
            "message": str(exc),
        }
    except Exception as exc:  # noqa: BLE001 - convert backend failure to envelope
        return {
            "status": "error",
            "code": "backend_error",
            "mag_source": mag_source,
            "message": f"pitch-angle FAC pipeline failed: {exc}",
        }

    spectrogram = np.vstack(rows)  # (n_time, n_pa)
    spec_path = out_dir / "particle_spectra_pitch_angle.npz"
    # Self-describing labels so render_tplot can label the PAD y-axis as
    # "pitch_angle [deg]" (0-180) and the colorbar as flux, instead of the
    # filename stem (issue #150). See the energy/phi/theta save above.
    np.savez_compressed(
        spec_path,
        time=times,
        axis=axis_ref,
        spectrogram=spectrogram,
        axis_label="pitch_angle",
        axis_units="deg",
        value_label="flux",
    )
    return {
        "status": "success",
        "spectrogram_file": str(spec_path),
        "axis_label": "pitch_angle",
        "axis_units": "deg",
        "shape": list(spectrogram.shape),
        "axis_range": _finite_range(axis_ref),
        "value_range": _finite_range(spectrogram),
        "n_pitch_angle_bins": int(n_pa),
        "mag_source": mag_source,
        "note": (
            "Pitch angle = angle between each look direction and +B, via "
            "spd_pgs_do_fac (B as +z) then spd_pgs_make_theta_spec in colatitude "
            "mode. Axis spans 0-180 deg. mag_source records where the B reference "
            "came from: 'mag_file' (explicit override), "
            "'distribution_artifact_magf' (embedded magf from the #95 bridge), or "
            "'missing' (no B; needs_input)."
        ),
    }


__all__ = [
    "DIST_SCHEMA_DOC",
    "MAG_SCHEMA_DOC",
    "ParticleBackendError",
    "build_particle_distribution_artifact",
    "load_particle_distribution_artifact",
    "compute_particle_moments",
    "compute_particle_spectra",
]
