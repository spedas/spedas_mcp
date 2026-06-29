"""Unified SPEDAS-oriented MCP server.

The server follows Jason's updated A+B direction:

A. Present one SPEDAS data layer organized by data source categories.
B. Add a SPEDAS science-workflow layer so agents can plan a study before using
   source-specific data and geometry operations.

The focused backend packages remain internal implementation details, not the user-facing mental
model. Outward-facing tools should speak in terms of SPEDAS data sources such as
CDAWeb, PDS, and SPICE/geometry.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import math
import os
import re
from pathlib import Path
from typing import Any, Literal

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised by entrypoint guard
    raise ImportError("Install MCP support with: pip install 'spedas-mcp[mcp]'") from exc

logger = logging.getLogger(__name__)


ANALYSIS_TOOL_NAMES = (
    "transform_timeseries_coordinates",
    "generate_fac_matrix",
    "tvector_rotate",
    "analyze_minvar_coordinates",
    "dynamic_power_spectrum",
    "wavelet_transform",
    "evaluate_magnetic_field",
    "calculate_lshell",
    "build_particle_distribution_artifact",
    "load_particle_distribution_artifact",
    "compute_particle_moments",
    "compute_particle_spectra",
    "render_tplot",
)

HAPI_TOOL_NAMES = ("browse_hapi_catalog", "fetch_hapi_data")
FDSN_TOOL_NAMES = ("browse_fdsn_datasets", "fetch_fdsn_data")

# Modules/attributes exercised by the ten optional analysis tools. This is more
# precise than checking only ``import pyspedas``: several pyspedas builds expose
# mission loaders but not the legacy tplot/cotrans/wavelet/particle helpers that
# these tools call. If any required backend is missing, the server omits the
# whole analysis registration group from MCP ``list_tools``.
_ANALYSIS_REQUIRED_IMPORTS = (
    ("pyspedas", None),
    ("matplotlib", None),
    ("pywt", None),
    ("pyspedas.cotrans_tools.cotrans", "cotrans"),
    ("pyspedas.cotrans_tools.fac_matrix_make", "fac_matrix_make"),
    ("pyspedas.cotrans_tools.minvar", "minvar"),
    ("pyspedas.cotrans_tools.minvar_matrix_make", "minvar_matrix_make"),
    ("pyspedas.tplot_tools", "store_data"),
    ("pyspedas.tplot_tools.tplot_math.dpwrspc", "dpwrspc"),
    ("pyspedas.analysis.wavelet", "idl_wavelet_scales"),
    ("pyspedas.analysis.wave_signif", "wave_signif"),
    ("pyspedas.geopack", None),
    ("pyspedas.particles.moments", "moments_3d"),
    # These spd_pgs_* helpers live in per-function SUBMODULES of
    # spd_part_products (e.g. ...spd_part_products.spd_pgs_make_e_spec), not as
    # attributes of the package itself, and are imported lazily — so probing the
    # package with hasattr() returns False until the submodule is imported,
    # which gated off ALL analysis tools even with [analysis] installed. Probe
    # the submodule path directly, matching how analysis/particles.py imports
    # them and how the other entries above target function-bearing modules.
    ("pyspedas.particles.spd_part_products.spd_pgs_make_e_spec", "spd_pgs_make_e_spec"),
    ("pyspedas.particles.spd_part_products.spd_pgs_make_phi_spec", "spd_pgs_make_phi_spec"),
    ("pyspedas.particles.spd_part_products.spd_pgs_make_theta_spec", "spd_pgs_make_theta_spec"),
    ("pyspedas.particles.spd_part_products.spd_pgs_do_fac", "spd_pgs_do_fac"),
)


_CURATED_CDAWEB_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "omni",
        "name": "OMNI",
        "aliases": ["OMNI", "OMNI_HRO", "OMNI_HRO2", "OMNI2"],
        "description": (
            "Curated CDAWeb discovery entry for OMNI near-Earth solar-wind and "
            "geomagnetic index products. The upstream CDAWeb observatory catalog "
            "does not currently emit an OMNI observatory record, but these dataset "
            "IDs are resolvable by browse_data_parameters/fetch_data_product."
        ),
        "dataset_count": 5,
        "instruments": ["solar_wind", "geomagnetic_indices"],
        "source_label": "CDAWeb curated dataset group",
        "datasets": [
            {"dataset_id": "OMNI_HRO_1MIN", "instrument": "solar_wind_geomagnetic_indices", "cadence": "1 minute", "contains": ["IMF", "plasma", "AE", "AL", "AU", "SYM-H"]},
            {"dataset_id": "OMNI_HRO2_1MIN", "instrument": "solar_wind_geomagnetic_indices", "cadence": "1 minute", "contains": ["IMF", "plasma", "AE", "AL", "AU", "SYM-H"]},
            {"dataset_id": "OMNI_HRO_5MIN", "instrument": "solar_wind_geomagnetic_indices", "cadence": "5 minute", "contains": ["IMF", "plasma", "AE", "AL", "AU", "SYM-H", "GOES proton flux"]},
            {"dataset_id": "OMNI_HRO2_5MIN", "instrument": "solar_wind_geomagnetic_indices", "cadence": "5 minute", "contains": ["IMF", "plasma", "AE", "AL", "AU", "SYM-H", "GOES proton flux"]},
            {"dataset_id": "OMNI2_H0_MRG1HR", "instrument": "solar_wind_geomagnetic_indices", "cadence": "1 hour", "contains": ["IMF", "plasma", "Kp", "Dst", "AE", "AL", "AU"]},
        ],
        "next_tools": [
            "browse_data_parameters(source_type='cdaweb', dataset_id='OMNI_HRO_1MIN')",
            "browse_data_parameters(source_type='cdaweb', dataset_id='OMNI2_H0_MRG1HR')",
            "fetch_data_product(source_type='cdaweb', dataset_id=..., parameters=..., start=..., stop=..., output_dir=...)",
        ],
    },
    {
        "id": "geomagnetic_indices",
        "name": "Geomagnetic indices (Dst/AE/Kp/SYM-H)",
        "aliases": ["dst", "ae", "kp", "sym-h", "sym_h", "symh", "indices", "geomagnetic"],
        "description": (
            "Curated CDAWeb discovery entry for common geomagnetic indices. "
            "Dst and Kp are available in OMNI2_H0_MRG1HR; AE/AL/AU and SYM-H "
            "are available in OMNI high-resolution products."
        ),
        "dataset_count": 6,
        "instruments": ["geomagnetic_indices"],
        "source_label": "CDAWeb curated dataset group",
        "datasets": [
            {"dataset_id": "OMNI2_H0_MRG1HR", "instrument": "geomagnetic_indices", "cadence": "1 hour", "contains": ["Kp", "Dst", "AE", "AL", "AU"]},
            {"dataset_id": "OMNI_HRO_1MIN", "instrument": "geomagnetic_indices", "cadence": "1 minute", "contains": ["AE", "AL", "AU", "SYM-H", "SYM-D"]},
            {"dataset_id": "OMNI_HRO2_1MIN", "instrument": "geomagnetic_indices", "cadence": "1 minute", "contains": ["AE", "AL", "AU", "SYM-H", "SYM-D"]},
            {"dataset_id": "OMNI_HRO_5MIN", "instrument": "geomagnetic_indices", "cadence": "5 minute", "contains": ["AE", "AL", "AU", "SYM-H", "SYM-D"]},
            {"dataset_id": "OMNI_HRO2_5MIN", "instrument": "geomagnetic_indices", "cadence": "5 minute", "contains": ["AE", "AL", "AU", "SYM-H", "SYM-D"]},
            {"dataset_id": "CN_K0_MARI", "instrument": "ground_ae_local", "cadence": "variable", "contains": ["local auroral electrojet indices"]},
        ],
        "next_tools": [
            "browse_data_parameters(source_type='cdaweb', dataset_id='OMNI2_H0_MRG1HR')",
            "browse_data_parameters(source_type='cdaweb', dataset_id='OMNI_HRO_1MIN')",
            "fetch_data_product(source_type='cdaweb', dataset_id=..., parameters=..., start=..., stop=..., output_dir=...)",
        ],
    },
)


def _norm_source_key(value: str) -> str:
    return (value or "").strip().casefold().replace("-", "_")


def _curated_cdaweb_records() -> list[dict[str, Any]]:
    return [dict(record) for record in _CURATED_CDAWEB_SOURCES]


def _curated_cdaweb_lookup(source_id: str) -> dict[str, Any] | None:
    key = _norm_source_key(source_id)
    for record in _CURATED_CDAWEB_SOURCES:
        tokens = [record["id"], record["name"], *record.get("aliases", [])]
        if key in {_norm_source_key(str(token)) for token in tokens}:
            return dict(record)
    return None



def _analysis_dependencies_available() -> bool:
    """Return whether the optional ``spedas-mcp[analysis]`` backend is usable.

    The analysis tools are intentionally not registered unless the optional
    backend APIs are present, which keeps a base ``spedas-mcp[mcp]`` install from
    advertising ten pyspedas/matplotlib-backed tools that can only return
    dependency errors. Use ``create_server(include_analysis_tools=True)`` in
    tests to exercise the registration path without requiring those backends.
    """
    for module_name, attr_name in _ANALYSIS_REQUIRED_IMPORTS:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            return False
        if attr_name is not None and not hasattr(module, attr_name):
            return False
    return True


def _module_available(module_name: str) -> bool:
    """Return whether a module appears importable without importing it fully."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False


def _optional_backend_availability(*, include_analysis_tools: bool) -> dict[str, dict[str, Any]]:
    """Summarize optional backend availability for overview/discovery payloads.

    HAPI/FDSN tools stay registered for backward compatibility, but this metadata
    lets generic MCP clients distinguish callable-but-missing optional backends
    from tools that can perform work in the current base install. Analysis tools
    remain hidden unless their backend is present.
    """
    hapi_modules = ("hapiclient",)
    # Probe only top-level packages here. importlib.find_spec("pyspedas.mth5")
    # imports the pyspedas package as a side effect in some environments, which
    # is too expensive/noisy for a lightweight overview call; the actual tool
    # still performs the authoritative lazy import and returns missing_dependency
    # if pyspedas.mth5 itself is unavailable.
    fdsn_modules = ("pyspedas", "mth5", "obspy")

    def _entry(
        *,
        available: bool,
        extra: str,
        tools: tuple[str, ...],
        registration: str,
        missing_modules: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "available": available,
            "requires_extra": extra,
            "install_hint": f"pip install 'spedas-mcp[{extra}]'",
            "tools": list(tools) if available or registration == "always_registered" else [],
            "all_tools": list(tools),
            "registration": registration,
        }
        if missing_modules:
            payload["missing_modules"] = missing_modules
        if not available:
            payload["call_behavior"] = (
                "tool calls return a structured status='error', "
                "code='missing_dependency' payload until the extra is installed"
                if registration == "always_registered"
                else "tools are not registered in MCP list_tools until the extra is installed"
            )
        return payload

    hapi_missing = [name for name in hapi_modules if not _module_available(name)]
    fdsn_missing = [name for name in fdsn_modules if not _module_available(name)]

    return {
        "analysis": _entry(
            available=include_analysis_tools,
            extra="analysis",
            tools=ANALYSIS_TOOL_NAMES,
            registration="registered_when_available",
            missing_modules=None if include_analysis_tools else ["pyspedas/matplotlib/PyWavelets analysis stack"],
        ),
        "hapi": _entry(
            available=not hapi_missing,
            extra="hapi",
            tools=HAPI_TOOL_NAMES,
            registration="always_registered",
            missing_modules=hapi_missing,
        ),
        "fdsn": _entry(
            available=not fdsn_missing,
            extra="fdsn",
            tools=FDSN_TOOL_NAMES,
            registration="always_registered",
            missing_modules=fdsn_missing,
        ),
    }


def _compat_tools_enabled() -> bool:
    """Return true when legacy CDAWeb/PDS compatibility tools should be advertised."""
    return os.environ.get("SPEDAS_MCP_COMPAT_TOOLS") == "1"


def _json(data: object) -> str:
    return json.dumps(data, indent=2, default=str)


_FILL_LIKE_ABS_THRESHOLD = 1e29


def _infer_coordinate_frame_from_dataset(dataset_id: str | None, parameters: list[str] | None = None) -> str | None:
    """Conservative frame inference from explicit dataset/parameter tokens.

    Used only as provenance for fetched artifacts; it does not claim every dataset
    has a known frame. Tokens such as ``_RTN_``/``_GSE_``/``_GSM_`` are common in
    heliophysics product IDs and are safe enough to surface as a guard signal for
    downstream coordinate transforms.
    """
    import re

    text = " ".join([dataset_id or "", *(parameters or [])]).lower()
    for frame in ("rtn", "rtp", "gse", "gsm", "gei", "geo", "j2000", "sm", "sc", "srf"):
        if re.search(rf"(?<![a-z0-9]){re.escape(frame)}(?![a-z0-9])", text):
            return "spacecraft" if frame in {"sc", "srf"} else frame
        if re.search(rf"[_./-]{re.escape(frame)}([_./-]|$)", text):
            return "spacecraft" if frame in {"sc", "srf"} else frame
    return None


def _write_fetch_provenance_sidecar(
    file_path: Path,
    *,
    source_type: str,
    dataset_id: str,
    parameters: list[str],
    start: str,
    stop: str,
    fmt: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """Write a compact JSON sidecar next to a fetched tabular artifact."""
    coordinate_frame = _infer_coordinate_frame_from_dataset(dataset_id, parameters)
    sidecar = file_path.with_suffix(file_path.suffix + ".provenance.json")
    payload: dict[str, Any] = {
        "source_type": source_type,
        "dataset_id": dataset_id,
        "parameters": list(parameters),
        "time_range": {"start": start, "stop": stop},
        "format": fmt,
        "coordinate_frame": coordinate_frame,
        "coordinate_frame_inference": (
            "explicit frame token parsed from dataset_id/parameters" if coordinate_frame else None
        ),
    }
    if extra:
        payload.update(extra)
    sidecar.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return str(sidecar)


def _safe_float(value: Any) -> float | None:
    """Return a finite float for JSON stats, or ``None`` if unavailable."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _augment_cdaweb_stats(dataframe: Any, backend_stats: Any) -> Any:
    """Add cheap robust/fill/quality signals to CDAWeb per-parameter stats.

    The CDAWeb backend already returns min/max/mean/std/nan_ratio. Those are
    useful but can hide present-but-physically-impossible fill/outlier spikes
    (issue #65). This helper keeps the backend shape intact and adds a
    ``quality_checks`` block with p1/p50/p99 robust stats, common fill-like value
    counts, and generic QUALITY/FLAG column summaries when available. It is
    intentionally dataset-agnostic: it does not mask or claim a sample is bad; it
    surfaces enough compact evidence for an agent to notice suspect products.
    """
    stats: dict[str, Any]
    if isinstance(backend_stats, dict):
        stats = dict(backend_stats)
    elif backend_stats is None:
        stats = {}
    else:
        stats = {"backend_stats": backend_stats}

    try:
        import pandas as pd
    except Exception:  # pragma: no cover - pandas is present for CDAWeb fetches
        return backend_stats

    try:
        numeric = dataframe.apply(pd.to_numeric, errors="coerce").dropna(axis=1, how="all")
    except Exception:
        return backend_stats
    if numeric.empty:
        return backend_stats

    total_values = int(numeric.size)
    finite_or_nan = numeric.replace([float("inf"), -float("inf")], pd.NA)
    nonfinite_count = int(finite_or_nan.isna().sum().sum())
    fill_mask = finite_or_nan.abs().ge(_FILL_LIKE_ABS_THRESHOLD).fillna(False)
    fill_count = int(fill_mask.sum().sum())
    cleaned = finite_or_nan.mask(fill_mask)
    valid_count = int(total_values - cleaned.isna().sum().sum())

    column_stats: dict[str, dict[str, float | int]] = {}
    for column in cleaned.columns:
        series = cleaned[column].dropna()
        if series.empty:
            continue
        quantiles = series.quantile([0.01, 0.5, 0.99])
        summary: dict[str, float | int] = {
            "count": int(series.shape[0]),
        }
        for key, value in {
            "min": series.min(),
            "max": series.max(),
            "p1": quantiles.loc[0.01],
            "p50": quantiles.loc[0.5],
            "p99": quantiles.loc[0.99],
        }.items():
            number = _safe_float(value)
            if number is not None:
                summary[key] = number
        column_stats[str(column)] = summary

    flag_summaries: dict[str, Any] = {}
    for column in numeric.columns:
        name = str(column).lower()
        if "quality" not in name and "flag" not in name:
            continue
        series = finite_or_nan[column].dropna()
        if series.empty:
            continue
        counts = series.value_counts().head(10)
        zero_fraction = _safe_float((series == 0).mean())
        nonzero_fraction = _safe_float((series != 0).mean())
        flag_summary: dict[str, Any] = {
            "counts": {str(key): int(value) for key, value in counts.items()},
        }
        if zero_fraction is not None:
            flag_summary["zero_fraction"] = zero_fraction
        if nonzero_fraction is not None:
            flag_summary["nonzero_fraction"] = nonzero_fraction
        flag_summaries[str(column)] = flag_summary

    quality_checks: dict[str, Any] = {
        "fill_ratio": fill_count / total_values if total_values else 0.0,
        "fill_like_count": fill_count,
        "fill_like_abs_threshold": _FILL_LIKE_ABS_THRESHOLD,
        "nonfinite_ratio": nonfinite_count / total_values if total_values else 0.0,
        "nonfinite_count": nonfinite_count,
        "valid_count_after_fill_mask": valid_count,
        "robust_stats": {
            "columns": column_stats,
            "note": "p1/p50/p99 ignore NaN/non-finite values and common fill-like sentinels with abs(value) >= 1e29.",
        },
    }
    if flag_summaries:
        quality_checks["quality_flags"] = flag_summaries
    stats["quality_checks"] = quality_checks
    return stats


# Maximum serialized size (bytes) for a single MCP tool response. MCP stdio is
# line-delimited JSON and asyncio's StreamReader defaults to a 64KB line buffer
# (65536 bytes); a single response over that limit raises LimitOverrunError and
# crashes conformant clients (issue #28). We keep a margin below 64KB so the
# transport's own framing/escaping never pushes a "safe" payload over the edge.
_MAX_RESPONSE_BYTES = 60000

# Matches absolute filesystem paths so they can be stripped from user-facing
# error text. Backends such as vendored CDAWeb and PDS raise FileNotFoundError
# messages that embed local cache directories (issue #25, issue #27); those must
# never reach an MCP client. Two narrow alternatives keep the match specific:
#   * POSIX absolute paths: a leading ``/`` plus two or more segments.
#   * Windows absolute paths: a drive letter (``C:\``) plus segments.
# Requiring a leading ``/`` (not just any embedded ``/``) and a drive letter for
# the backslash form avoids treating escaped ``\n``/``\t`` in repr'd exception
# text as paths, which would over-redact ordinary multi-line error messages.
_ABS_PATH_RE = re.compile(
    r"""(?:
            /[^\s'"<>]+(?:/[^\s'"<>]+)+        # POSIX: /a/b[/c...]
          |
            [A-Za-z]:\\[^\s'"<>]+(?:\\[^\s'"<>]+)*  # Windows: C:\a[\b...]
        )""",
    re.VERBOSE,
)

# Third-party error-documentation URLs (e.g. Pydantic's per-error doc links)
# that leak the backend/runtime version and add noise to user-facing messages.
_URL_RE = re.compile(r"https?://\S+")


def _sanitize_message(text: object) -> str:
    """Return ``text`` with absolute paths and external URLs redacted.

    Used so structured error responses never expose local cache directories,
    temp paths, or third-party error-doc URLs to MCP clients (issues #25/#27).
    The redaction is conservative: it replaces matched spans with a short
    placeholder rather than dropping surrounding context, so the message stays
    actionable.
    """
    value = text if isinstance(text, str) else str(text)
    # ``str(KeyError(...))`` repr-escapes embedded newlines/tabs as the literal
    # two-character sequences ``\n``/``\t``; turn them back into whitespace so the
    # whitespace collapse below flattens them and they are not mistaken for path
    # separators.
    value = value.replace("\\n", " ").replace("\\t", " ").replace("\\r", " ")
    value = _URL_RE.sub("<url-redacted>", value)
    value = _ABS_PATH_RE.sub("<path>", value)
    # Collapse the whitespace that path/URL removal can leave behind, and keep
    # the message to a single line so it can never overflow the stdio buffer.
    value = re.sub(r"\s+", " ", value).strip()
    return value


def _error_response(
    code: str,
    message: str,
    *,
    hint: str | None = None,
    sanitize: bool = True,
    **extra: Any,
) -> str:
    """Build the uniform structured error envelope returned by MCP tools.

    Every user-facing error shares ``{status: "error", code, message, ...}`` so
    agents can branch on ``status``/``code`` instead of parsing free text
    (issue #27). ``message`` (and any string in ``extra``) is path/URL-redacted
    by default so backend internals never leak (issues #25/#27). Pass
    ``sanitize=False`` only for messages the server itself authored that are
    known to be path-free.
    """
    payload: dict[str, Any] = {
        "status": "error",
        "code": code,
        "message": _sanitize_message(message) if sanitize else message,
    }
    if hint is not None:
        payload["hint"] = hint
    if sanitize:
        # Honor the docstring contract: redact paths/URLs from string extras too,
        # so backend internals cannot leak through context fields (issues
        # #25/#27). _sanitize_message only strips absolute paths/URLs and
        # collapses whitespace, so plain IDs/frame names survive untouched.
        for key, value in extra.items():
            payload[key] = _sanitize_message(value) if isinstance(value, str) else value
    else:
        payload.update(extra)
    return _json(payload)




def _validate_fetch_time_range(start: str, stop: str, *, source_type: str) -> str | None:
    """Return a structured invalid_argument response for malformed fetch times.

    CDAWeb/PDS REST backends otherwise turn caller mistakes (unparseable dates or
    reversed intervals) into opaque HTTP 400/404 backend errors. Validate locally
    so agents can repair their own arguments without a network round-trip.
    """
    try:
        import pandas as pd
    except Exception:  # pragma: no cover - pandas is a data-fetch dependency
        return None

    parsed: dict[str, Any] = {}
    for name, value in (("start", start), ("stop", stop)):
        try:
            timestamp = pd.to_datetime(value, utc=True, errors="coerce")
        except Exception:
            timestamp = pd.NaT
        if pd.isna(timestamp):
            return _error_response(
                "invalid_argument",
                f"could not parse {name} time {value!r}; use ISO-8601 (for example 2025-06-19T08:00:00Z).",
                hint="Pass parseable ISO-8601 start/stop values before fetching data.",
                sanitize=False,
                source_type=source_type,
                invalid_argument=name,
            )
        parsed[name] = timestamp
    if parsed["stop"] <= parsed["start"]:
        return _error_response(
            "invalid_argument",
            "stop must be after start for data fetches.",
            hint="Use a positive time interval (stop > start), or swap the supplied start/stop values.",
            sanitize=False,
            source_type=source_type,
            invalid_argument="stop",
        )
    return None


def _no_data_response(
    *,
    source_type: str,
    dataset_id: str,
    parameters: list[str],
    start: str,
    stop: str,
    parameter_metadata: dict[str, dict],
) -> str:
    """Return a structured, classified no-data response for CDAWeb/PDS fetches.

    Backends currently expose failed fetches primarily as per-parameter messages.
    Keep those messages in ``parameters`` for evidence, but provide a stable
    top-level ``code`` so callers never have to parse free text. Classification is
    intentionally conservative: use specific codes only for common, high-signal
    backend wording, otherwise fall back to ``no_data``.
    """
    messages = [str(meta.get("message", "")) for meta in parameter_metadata.values() if isinstance(meta, dict)]
    combined = " ".join(messages).casefold()
    code = "no_data"
    message = (
        f"No data fetched for dataset {dataset_id!r} in the requested time range "
        f"with {len(parameters)} requested parameter(s)."
    )
    hint = "Check dataset_id, parameter names, and the requested start/stop interval; use discovery tools before retrying."

    has_unknown_dataset = bool(
        combined
        and any(token in combined for token in ("master cdf", "404", "unknown dataset", "dataset not", "not in catalog"))
    )
    has_unknown_parameter = bool(
        combined
        and any(token in combined for token in ("parameter", "variable", "not in dataset", "unknown parameter", "unknown variable"))
    )
    has_no_data_in_range = bool(
        combined
        and any(token in combined for token in ("no cdf files", "no files", "no data", "outside", "coverage", "time range"))
    )

    if has_unknown_dataset:
        # Dataset-level failures are more fundamental than per-parameter misses or
        # generic no-data-in-range wording that may be appended by a backend.
        code = "unknown_dataset"
        message = f"Dataset {dataset_id!r} could not be fetched or was not found by the {source_type.upper()} backend."
        hint = "Call browse_data_sources/load_data_source to discover a valid dataset_id before retrying."
    elif has_unknown_parameter:
        code = "unknown_parameter"
        message = f"One or more requested parameters were not found for dataset {dataset_id!r}."
        hint = "Call browse_data_parameters for this dataset_id and retry with valid parameter names."
    elif has_no_data_in_range:
        code = "no_data_in_range"
        message = f"No data were available for dataset {dataset_id!r} in the requested time range."
        hint = "Try a time range inside the dataset coverage window, or inspect source metadata before retrying."

    return _error_response(
        code,
        message,
        hint=hint,
        sanitize=False,
        source_type=source_type,
        dataset_id=dataset_id,
        time_range={"start": start, "stop": stop},
        requested_parameters=parameters,
        parameters=parameter_metadata,
    )


def _unknown_source_type_error(source_type: str, allowed: list[str]) -> str:
    """Uniform structured error for an unrecognized ``source_type`` routing arg.

    The unified data-layer tools previously returned a bespoke legacy shape with
    no ``code``/``message`` and a duplicate error key, so agents could not branch
    on it like every other error (issue #27). This routes them through
    ``_error_response`` instead.
    """
    return _error_response(
        "invalid_argument",
        f"unknown source_type: {source_type}",
        hint=f"Pass one of: {', '.join(allowed)}.",
        allowed=allowed,
    )


def _size_guarded(raw: str, **context: Any) -> str:
    """Return ``raw`` unchanged, or a compact structured error if it is too big.

    Defends every structured tool response against the asyncio 64KB stdio line
    limit (issue #28). When a serialized payload exceeds ``_MAX_RESPONSE_BYTES``
    the actual bytes are measured (not estimated) and replaced with a small
    ``response_too_large`` envelope that tells the agent how to narrow the query.
    This is a backstop: discovery/listing tools should paginate or write
    artifacts first, but if any response still grows past the limit the client
    receives an actionable error instead of a crash.
    """
    size = len(raw.encode("utf-8"))
    if size <= _MAX_RESPONSE_BYTES:
        return raw
    logger.warning(
        "MCP response exceeded size guard (%d bytes > %d); returning compact error. context=%s",
        size,
        _MAX_RESPONSE_BYTES,
        context,
    )
    return _error_response(
        "response_too_large",
        (
            f"Tool response was {size} bytes, over the {_MAX_RESPONSE_BYTES}-byte "
            "MCP stdio safety limit, and was withheld to avoid crashing the client."
        ),
        hint=(
            "Narrow the request: pass a query/filter, a smaller time range, fewer "
            "parameters, or use a more specific source_id. For bulk data, fetch to "
            "an output_dir/output_file and reference the path instead of inlining."
        ),
        response_bytes=size,
        max_bytes=_MAX_RESPONSE_BYTES,
        **context,
    )


# Maps backend exception classes to a stable error ``code`` and recovery hint so
# tools surface uniform, agent-classifiable errors instead of raw tracebacks
# (issue #27). Ordered most- to least-specific; matched by isinstance.
_EXCEPTION_CODES: tuple[tuple[type[BaseException], str, str | None], ...] = (
    (FileNotFoundError, "resource_not_found",
     "The requested resource is not in the catalog/cache; discover valid IDs first."),
    (NotADirectoryError, "resource_not_found", None),
    (PermissionError, "backend_error", None),
    (TimeoutError, "backend_error", "The backend timed out; retry or narrow the request."),
    (ValueError, "invalid_argument",
     "Check argument values against the tool's documented valid options."),
    (KeyError, "invalid_argument", None),
    (TypeError, "invalid_argument", None),
)


# Hint shared by every geometry/SPICE classification path.
_GEOMETRY_HINT = (
    "Check body/frame names with browse_data_sources(source_type='spice') "
    "and load_data_source(source_type='spice', source_id=...); not every body has loaded kernels."
)

# Substrings that mark a ``KeyError`` as a geometry lookup failure (unresolvable
# body/frame/mission/kernel) raised by the in-tree SPICE backend, rather than a generic dict
# miss. Matched case-insensitively against the exception text.
_GEOMETRY_KEYERROR_SIGNALS = (
    "body name",
    "frame",
    "mission",
    "kernel",
    "ephemeris",
    "observer",
    "target",
)


def _classify_exception(exc: BaseException) -> tuple[str, str | None]:
    """Return a ``(code, hint)`` pair for a backend exception (issue #27).

    SpiceyPy and Pydantic raise their own classes; we match on class *name* as a
    fallback so we do not need to import optional backends just to classify their
    errors. Anything unrecognized degrades to a generic ``backend_error``.
    """
    # A geometry ``KeyError`` (e.g. SPICE backend "Cannot resolve body name 'X'")
    # must reach the geometry-specific code/hint, not the generic
    # ``KeyError -> invalid_argument`` mapping below, so SPICE callers get an
    # actionable recovery path (issue #27). Detect it by message signal before
    # the ordered isinstance table runs.
    if isinstance(exc, KeyError):
        text = str(exc).lower()
        if any(signal in text for signal in _GEOMETRY_KEYERROR_SIGNALS):
            return "geometry_error", _GEOMETRY_HINT
    for exc_type, code, hint in _EXCEPTION_CODES:
        if isinstance(exc, exc_type):
            return code, hint
    name = type(exc).__name__
    if "Spice" in name or name.endswith("SpiceyError"):
        return "geometry_error", _GEOMETRY_HINT
    if "ValidationError" in name:
        return "invalid_argument", "One or more arguments are missing or the wrong type."
    return "backend_error", None


def _safe_tool(func):
    """Wrap a tool callable so it never returns a raw traceback or oversized line.

    Backend functions (CDAWeb/PDS/SPICE) raise ``FileNotFoundError``,
    ``ValueError``, SpiceyPy errors, and multi-line tracebacks that, unwrapped,
    reach MCP clients as inconsistent plain text and can overflow the 64KB stdio
    line buffer (issues #27/#28). This decorator converts any escaped exception
    into the uniform structured error envelope (path/URL redacted) and applies
    the response-size guard to successful returns as a universal backstop.
    """
    import functools

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            result = func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - deliberately convert to envelope
            code, hint = _classify_exception(exc)
            logger.warning("Tool %s failed: %s: %s", func.__name__, type(exc).__name__, exc)
            return _error_response(code, str(exc), hint=hint, tool=func.__name__)
        if isinstance(result, str):
            return _size_guarded(result, tool=func.__name__)
        return result

    return wrapper


def _summarize_pydantic_validation(exc: BaseException) -> str:
    """Render a pydantic argument ``ValidationError`` as a compact, URL-free message.

    The raw ``str(ValidationError)`` embeds the full input dict and a public
    ``errors.pydantic.dev`` doc URL (issue #57). We rebuild a short, deterministic
    one-line summary from the structured ``.errors()`` entries instead, naming only
    the offending parameter(s) and what is wrong — never the input values or a URL.
    """
    try:
        errors = exc.errors()  # type: ignore[attr-defined]
    except Exception:  # pragma: no cover - non-standard ValidationError shape
        return _sanitize_message(str(exc))
    parts: list[str] = []
    for err in errors:
        loc = err.get("loc") or ()
        field = ".".join(str(part) for part in loc) if loc else "(arguments)"
        kind = err.get("type", "")
        if kind == "missing":
            parts.append(f"missing required argument '{field}'")
        elif kind in {"unexpected_keyword_argument", "extra_forbidden", "no_such_attribute"}:
            parts.append(f"unexpected argument '{field}'")
        else:
            # Keep pydantic's short human message but strip any embedded URL/path.
            msg = _sanitize_message(str(err.get("msg", "is invalid")))
            parts.append(f"argument '{field}' {msg}")
    if not parts:
        return _sanitize_message(str(exc))
    return "Invalid arguments: " + "; ".join(parts) + "."


def _find_validation_error(exc: BaseException) -> BaseException | None:
    """Return the underlying pydantic argument ``ValidationError``, if any.

    FastMCP validates tool arguments against a generated pydantic model *before*
    calling the (already ``_safe_tool``-wrapped) tool body, then re-raises the
    failure wrapped in a ``ToolError`` (``Error executing tool <name>: ...``). That
    path bypasses the structured-error contract and leaks the raw pydantic text
    plus an ``errors.pydantic.dev`` URL to the client (issue #57). Walk the
    exception chain and identify a pydantic ``ValidationError`` by class name so we
    do not need to import pydantic here.
    """
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if type(cur).__name__ == "ValidationError" and hasattr(cur, "errors"):
            return cur
        cur = cur.__cause__ or cur.__context__
    return None


# ---------------------------------------------------------------------------
# Geometry/SPICE safety preflight (issues #26, #27, #29).
#
# The in-tree SPICE geometry routines (get_state/get_trajectory/transform_vector)
# resolve body names and *download* SPICE kernels on first use — generic kernels
# (~120 MB, e.g. de440s.bsp) plus per-mission SPK files (PSP ~266 MB, up to
# ~1 GB for some segmented missions). Two problems follow:
#   * #26: an unsupported target (e.g. "MMS1", which is a CDAWeb mission with no
#     SPICE kernels) bubbles up an opaque "Cannot resolve body name" error after
#     touching the backend, with no recovery path.
#   * #29: a supported-but-uncached target silently triggers a large download
#     with no warning or confirmation, bypassing the explicit
#     manage_data_cache(source_type='spice', action='load') gate.
#
# Both are solved by a pure, network-free preflight that runs entirely in this
# process *before* any SPICE backend call: resolve_mission() is an in-memory
# registry lookup, and kernel-cache presence is a stat() on the cache dir. The
# preflight never downloads, so it is safe to run on every geometry call.
# ---------------------------------------------------------------------------

def _spice_resolve_target(name: str) -> dict[str, Any]:
    """Resolve a geometry target/observer name without touching the network.

    Returns a dict describing the resolution outcome::

        {"resolved": True, "key": "PSP", "naif_id": -96, "has_kernels": True}
        {"resolved": False}              # name not in the SPICE registry

    Uses only the in-memory mission registry (no kernel download), so it is safe
    to call on the request hot path. ``resolved=False`` means the name is not a
    SPICE-supported body/mission (issue #26); the caller turns that into a
    structured ``unsupported_spice_target`` error.
    """
    from spedas_mcp.backends.spice.missions import has_kernels, resolve_mission

    try:
        naif_id, key = resolve_mission(name)
    except KeyError:
        return {"resolved": False}
    return {
        "resolved": True,
        "key": key,
        "naif_id": naif_id,
        "has_kernels": has_kernels(key),
    }


def _spice_supported_targets_sample(limit: int = 12) -> list[str]:
    """Return a small sample of supported SPICE mission keys for error hints.

    Kept compact so the ``unsupported_spice_target`` envelope stays well under
    the stdio size limit; the agent is pointed at
    ``browse_data_sources(source_type='spice')`` for the full catalog.
    """
    try:
        from spedas_mcp.backends.spice import list_supported_missions
    except Exception:  # pragma: no cover - backend not installed
        return []
    keys = [m.get("mission_key") for m in list_supported_missions() if m.get("mission_key")]
    return sorted(keys)[:limit]


def _unsupported_spice_target_error(target: str, *, role: str = "target") -> str:
    """Structured error for a geometry name with no SPICE support (issue #26).

    ``MMS``/``MMS1`` is the motivating case: it is a real CDAWeb magnetospheric
    mission but has no SPICE kernels, so SPICE geometry is the wrong tool. The
    response names magnetospheric SPICE alternatives (THEMIS A–E) and routes the
    agent back to CDAWeb for MMS, without leaking a backend traceback or path.
    """
    suggestions = _suggest_spice_targets(target)
    hint = (
        "This name is not a SPICE-supported body/mission. "
        "Use browse_data_sources(source_type='spice') to see supported targets. "
        "For MMS/Cluster-style magnetospheric missions, SPICE has no kernels — "
        "use the CDAWeb data layer (e.g. load_data_source(source_type='cdaweb', "
        "source_id='mms')) for orbit/position products, or THEMIS A–E for "
        "SPICE geometry."
    )
    return _error_response(
        "unsupported_spice_target",
        f"SPICE geometry {role} '{target}' is not a supported SPICE body or mission.",
        hint=hint,
        spice_target=target,
        role=role,
        suggested_targets=suggestions,
        supported_targets_sample=_spice_supported_targets_sample(),
    )


def _suggest_spice_targets(name: str, limit: int = 5) -> list[str]:
    """Best-effort "did you mean" suggestions among supported SPICE missions."""
    import difflib

    candidates = _spice_supported_targets_sample(limit=10_000)
    if not candidates:
        return []

    def _norm(value: str) -> str:
        return value.strip().lower().replace("-", "_")

    cand = _norm(name)
    prefix = [c for c in candidates if _norm(c).startswith(cand) or cand.startswith(_norm(c))]
    if prefix:
        return prefix[:limit]
    close = difflib.get_close_matches(cand, [_norm(c) for c in candidates], n=limit, cutoff=0.6)
    norm_to_orig = {_norm(c): c for c in candidates}
    return [norm_to_orig[c] for c in close if c in norm_to_orig][:limit]




def _spice_frame_catalog() -> dict[str, Any]:
    """Return the programmatic SPICE coordinate-frame catalog.

    The public tool surface intentionally keeps the old ``list_coordinate_frames``
    compatibility tool hidden by default (#109).  This helper lets the unified
    data-layer tools expose the same catalog as structured JSON so agents can
    answer "what frames can I transform between?" without adding another base
    tool.
    """
    try:
        from spedas_mcp.backends.spice import list_frames_with_descriptions
    except Exception:  # pragma: no cover - backend not installed
        return {
            "catalog_type": "spice_coordinate_frames",
            "frames": [],
            "frame_names": [],
            "aliases": [],
            "supported_frame_names": [],
        }

    frames: list[dict[str, Any]] = []
    for entry in list_frames_with_descriptions():
        if isinstance(entry, dict):
            frames.append(dict(entry))

    try:
        from spedas_mcp.backends.spice.frames import FRAME_ALIASES
    except Exception:  # pragma: no cover - backend internals changed
        raw_aliases: dict[str, str] = {}
    else:
        raw_aliases = {str(alias): str(frame) for alias, frame in dict(FRAME_ALIASES).items()}

    frame_names = [str(entry["frame"]) for entry in frames if entry.get("frame")]
    aliases = [
        {"alias": alias, "frame": frame}
        for alias, frame in raw_aliases.items()
        if alias.upper() != frame.upper()
    ]
    supported = list(dict.fromkeys([*frame_names, *raw_aliases.keys()]))

    return {
        "catalog_type": "spice_coordinate_frames",
        "frames": frames,
        "frame_names": frame_names,
        "aliases": aliases,
        "supported_frame_names": supported,
        "frame_count": len(frame_names),
        "alias_count": len(aliases),
        "transform_tool": "transform_coordinates",
        "usage_notes": [
            "Use any supported_frame_names value as from_frame/to_frame in transform_coordinates.",
            "RTN is spacecraft-dependent; pass spacecraft=<mission/target> when transforming to or from RTN.",
            "This catalog describes coordinate frames, not measurement parameters; SPICE geometry calls still require cached/allowed kernels.",
        ],
    }


def _spice_supported_frames() -> list[str]:
    """Return supported SPICE coordinate frame names for validation/errors.

    Uses the same in-tree SPICE frame catalog exposed through the unified SPICE
    data-source responses so geometry tools can reject unknown frame arguments
    before SPICE emits a raw multi-line CSPICE banner (issue #77).
    """
    try:
        return list(_spice_frame_catalog().get("supported_frame_names", []))
    except Exception:  # pragma: no cover - backend not installed
        return []


def _unknown_spice_frame_error(frame: str, *, role: str, tool: str) -> str:
    """Structured error for an unsupported coordinate frame (issue #77)."""
    supported = _spice_supported_frames()
    return _error_response(
        "invalid_argument",
        f"unknown frame '{frame}'",
        hint=(
            "Use one of supported_frames, or call load_data_source(source_type='spice', source_id=...) "
            "for descriptions and usage notes."
        ),
        tool=tool,
        frame=frame,
        role=role,
        supported_frames=supported,
    )


def _spice_frame_preflight(frames: list[tuple[str, str]], *, tool: str) -> str | None:
    """Validate frame arguments before any SPICE backend call (issue #77)."""
    supported = _spice_supported_frames()
    if not supported:
        # If the backend/catalog is unavailable, let the normal backend error path
        # classify the failure rather than rejecting every frame blindly.
        return None
    supported_norm = {frame.upper() for frame in supported}
    for frame, role in frames:
        if frame and frame.upper() not in supported_norm:
            return _unknown_spice_frame_error(frame, role=role, tool=tool)
    return None


def _spice_missing_kernels(mission_keys: list[str]) -> dict[str, Any]:
    """Report which required kernel files are not yet cached (issue #29).

    Pure disk inspection — never downloads. Returns::

        {
          "cached": True/False,           # all required files present?
          "missing_files": [...],         # filenames not on disk
          "missing_missions": [...],      # mission keys needing a download
          "segmented_missions": [...],    # need a time range via manage_data_cache(source_type="spice")
          "cache_dir": "<redacted>",      # cache root (path-redacted for clients)
          "cache_size_mb": 12.3,
        }

    Generic kernels are always required (every geometry call furnishes them), so
    they are folded into the check. A file counts as cached only if it exists on
    disk with non-zero size — the same test the downloader uses.
    """
    from spedas_mcp.backends.spice.kernel_manager import get_kernel_manager
    from spedas_mcp.backends.spice.missions import (
        GENERIC_KERNELS,
        MISSION_KERNELS,
        SEGMENTED_MISSIONS,
    )

    km = get_kernel_manager()
    cache_dir = km.kernel_dir

    def _is_cached(filename: str) -> bool:
        path = cache_dir / filename
        try:
            return path.exists() and path.stat().st_size > 0
        except OSError:
            return False

    missing_missions: list[str] = []
    segmented_missions: list[str] = []

    # Generic kernels belong to the implicit "GENERIC" group.
    generic_missing = [f for f in GENERIC_KERNELS if not _is_cached(f)]

    missing_files: list[str] = list(generic_missing)
    if generic_missing:
        missing_missions.append("GENERIC")

    for key in mission_keys:
        if key in MISSION_KERNELS:
            mission_missing = [f for f in MISSION_KERNELS[key] if not _is_cached(f)]
            if mission_missing:
                missing_files.extend(mission_missing)
                missing_missions.append(key)
        elif key in SEGMENTED_MISSIONS:
            # Segmented missions select files by time range; we cannot know which
            # segment files are needed here without the query window, so we treat
            # them as requiring the explicit, time-aware load gate.
            segmented_missions.append(key)

    cached = not missing_files and not segmented_missions
    return {
        "cached": cached,
        "missing_files": sorted(set(missing_files)),
        "missing_missions": sorted(set(missing_missions)),
        "segmented_missions": sorted(set(segmented_missions)),
        "cache_dir": _sanitize_message(str(cache_dir)),
        "cache_size_mb": round(km.get_cache_size_bytes() / (1024 * 1024), 2),
    }


def _kernel_download_required_error(
    mission_keys: list[str],
    preflight: dict[str, Any],
    *,
    tool: str,
) -> str:
    """Structured ``needs_confirmation`` response for an uncached geometry call (#29).

    Returned instead of proceeding when required kernels are not on disk and the
    caller has not opted in via ``allow_kernel_download=True``. It tells the agent
    exactly which missions need loading and how to opt in, so a quick metadata
    query never silently blocks on a 100 MB–1 GB transfer.
    """
    # Mission keys whose own SPK files are missing (drives the explicit
    # per-mission load step). GENERIC is reported separately because it is loaded
    # implicitly by any geometry call rather than via a mission= argument.
    load_missions = [m for m in preflight["missing_missions"] if m != "GENERIC"]
    load_missions.extend(preflight["segmented_missions"])
    load_missions = sorted(set(load_missions))

    # Surface every group whose download the gate is blocking — including the
    # implicit GENERIC planetary kernels (~120 MB), which a frame transform or a
    # natural-body observer needs even with no mission-specific SPK.
    blocked = sorted(set(preflight["missing_missions"]) | set(preflight["segmented_missions"]))
    if not blocked:
        blocked = sorted(set(mission_keys))

    next_steps = [
        f"manage_data_cache(source_type='spice', action='load', mission='{m}')" for m in load_missions
    ]
    next_steps.append(f"re-call {tool}(..., allow_kernel_download=True) to download and proceed")

    payload: dict[str, Any] = {
        "status": "needs_confirmation",
        "code": "kernel_download_required",
        "message": (
            "Required SPICE kernels are not cached. Proceeding would download "
            "kernel files (commonly 100 MB-1 GB per mission, e.g. PSP ~266 MB) "
            "before any geometry is computed. Confirm before downloading."
        ),
        "tool": tool,
        "missions": blocked,
        "missing_kernel_files": preflight["missing_files"],
        "segmented_missions_need_time_range": preflight["segmented_missions"],
        "cache_dir": preflight["cache_dir"],
        "cache_size_mb": preflight["cache_size_mb"],
        "next_steps": next_steps,
        "hint": (
            "Load the missions explicitly with manage_data_cache(source_type='spice', "
            "action='load', mission=...), or pass allow_kernel_download=True to "
            "this tool to download now. Use manage_data_cache(source_type='spice', "
            "action='check_remote', mission=...) to preview kernel files first."
        ),
    }
    return _size_guarded(_json(payload), tool=tool)


def _spice_geometry_preflight(
    names: list[tuple[str, str]],
    *,
    tool: str,
    allow_kernel_download: bool,
    require_kernels: bool = True,
) -> str | None:
    """Run the #26/#29 preflight for a geometry call; return an error envelope or None.

    ``names`` is a list of ``(name, role)`` pairs for the target/observer/
    spacecraft this call will pass to the SPICE backend; ``role`` (e.g. "target",
    "observer", "spacecraft") is echoed back in an unsupported-target error so
    the agent knows which argument to fix. The preflight:

    1. Resolves each name in-memory; an unresolved name yields an
       ``unsupported_spice_target`` error tagged with its role (issue #26).
    2. If all names resolve and ``require_kernels`` is set, checks the on-disk
       kernel cache; if anything required is missing and the caller has not set
       ``allow_kernel_download=True``, returns a ``kernel_download_required``
       confirmation envelope (issue #29).

    Returns ``None`` when the call is safe to proceed (resolved + cached, or the
    caller opted into downloads). Never performs any network I/O.
    """
    mission_keys: list[str] = []
    for name, role in names:
        if not name:
            continue
        resolution = _spice_resolve_target(name)
        if not resolution["resolved"]:
            return _unsupported_spice_target_error(name, role=role)
        mission_keys.append(resolution["key"])

    if not require_kernels or allow_kernel_download:
        return None

    preflight = _spice_missing_kernels(mission_keys)
    if preflight["cached"]:
        return None
    return _kernel_download_required_error(mission_keys, preflight, tool=tool)


def create_server(*, include_analysis_tools: bool | None = None) -> FastMCP:
    """Create and configure the unified SPEDAS MCP server.

    Analysis tools are registered only when the optional ``analysis`` extra
    dependencies are importable, unless ``include_analysis_tools`` explicitly
    overrides that auto-detection (primarily for tests).
    """
    if include_analysis_tools is None:
        include_analysis_tools = _analysis_dependencies_available()

    mcp = FastMCP(
        "spedas-mcp",
        instructions=(
            "SPEDAS MCP facade for heliophysics workflows. Start with the SPEDAS "
            "science-workflow tools to plan a study, then use the unified data-layer "
            "tools with source_type=cdaweb, pds, or spice. CDAWeb and PDS provide "
            "measurement/archive data; SPICE provides geometry, ephemeris, frames, "
            "and trajectory context. Focus on SPEDAS data sources rather than backend "
            "package names. Plan/discover before fetching; write bulk data to files; "
            "return compact metadata and paths."
        ),
    )

    compat_tools_enabled = _compat_tools_enabled()
    optional_backends = _optional_backend_availability(
        include_analysis_tools=include_analysis_tools
    )

    def _compat_tool(func):
        # Keep the function defined for internal unified-layer calls, but only
        # register/advertise the legacy CDAWeb/PDS entry point when explicitly
        # requested by existing clients.
        if compat_tools_enabled:
            return mcp.tool()(func)
        return func

    @mcp.tool()
    def spedas_overview() -> str:
        """Describe available SPEDAS MCP capabilities and the recommended workflow."""
        return _json({
            "status": "success",
            "server": "spedas-mcp",
            "capability_groups": {
                "data": [
                    "browse_data_sources",
                    "load_data_source",
                    "browse_data_parameters",
                    "fetch_data_product",
                    "manage_data_cache",
                ],
                "science_workflows": [
                    "search_spedas_data_sources",
                    "plan_spedas_observation",
                    "compare_cdaweb_pds_spice",
                    "create_spedas_analysis_bundle",
                ],
                "geometry": [
                    "get_ephemeris",
                    "compute_distance",
                    "transform_coordinates",
                ],
                "analysis": {
                    "status": (
                        "available; optional pyspedas/matplotlib backend installed"
                        if include_analysis_tools
                        else "not registered; install with spedas-mcp[analysis]"
                    ),
                    "tools": list(ANALYSIS_TOOL_NAMES) if include_analysis_tools else [],
                    "install_hint": "pip install 'spedas-mcp[analysis]'",
                    "available": optional_backends["analysis"]["available"],
                    "requires_extra": optional_backends["analysis"]["requires_extra"],
                    "registration": optional_backends["analysis"]["registration"],
                },
                "optional_backends": optional_backends,
                "compatibility_low_level": {
                    "status": (
                        "CDAWeb/PDS compatibility tools advertised because "
                        "SPEDAS_MCP_COMPAT_TOOLS=1"
                        if compat_tools_enabled
                        else "CDAWeb/PDS compatibility tools hidden by default; set "
                        "SPEDAS_MCP_COMPAT_TOOLS=1 for existing clients"
                    ),
                    "env_flag": "SPEDAS_MCP_COMPAT_TOOLS=1",
                    "prefer": [
                        "browse_data_sources",
                        "load_data_source",
                        "browse_data_parameters",
                        "fetch_data_product",
                        "manage_data_cache",
                    ],
                    "hidden_by_default": [
                        "browse_observatories",
                        "load_observatory",
                        "browse_parameters",
                        "fetch_data",
                        "browse_pds_missions",
                        "load_pds_mission",
                        "browse_pds_parameters",
                        "fetch_pds_data",
                    ],
                    "available_for_existing_clients": (
                        [
                            "browse_observatories",
                            "load_observatory",
                            "browse_parameters",
                            "fetch_data",
                            "browse_pds_missions",
                            "load_pds_mission",
                            "browse_pds_parameters",
                            "fetch_pds_data",
                        ]
                        if compat_tools_enabled
                        else []
                    ),
                },
            },
            "workflow": [
                "Start with search_spedas_data_sources or plan_spedas_observation for open-ended science requests.",
                "Use browse_data_sources(source_type='all') to inspect SPEDAS data-source categories.",
                "Use load_data_source, browse_data_parameters, fetch_data_product, and manage_data_cache for the unified data layer.",
                "load_data_source(source_type='cdaweb', ...) enumerates dataset_ids so you can call browse_data_parameters without guessing; pass the science goal to search_spedas_data_sources via question= (query= is accepted as an alias).",
                "Use unified data-layer tools for new workflows; set SPEDAS_MCP_COMPAT_TOOLS=1 only when an existing client requires legacy CDAWeb/PDS browse/load/parameter/fetch tool names; use manage_data_cache for all cache status and maintenance actions.",
                "Use geometry tools directly when the request is SPICE-specific ephemeris, distance, or transform work; discover SPICE missions/frames via browse_data_sources/load_data_source with source_type='spice'.",
                "Use create_spedas_analysis_bundle to preserve request/provenance intent before bulk fetches.",
                "For bulk data, always provide output_dir/output_file and return paths only.",
            ],
            "guided_recipes": {
                "overview_skill": "overview-geomagnetic-indices",
                "geomagnetic_indices": [
                    {
                        "intent": "Dst / ring-current context",
                        "preferred_source": "PySPEDAS Kyoto loader",
                        "dataset_or_loader": "pyspedas.projects.kyoto.dst",
                        "variables": ["kyoto_dst"],
                        "notes": "Kyoto WDC Dst; useful for Tsyganenko dst inputs when the runtime can call PySPEDAS directly.",
                    },
                    {
                        "intent": "AE/AL/AU electrojet context",
                        "preferred_source": "CDAWeb HAPI OMNI or PySPEDAS Kyoto AE",
                        "dataset_or_loader": "OMNI_HRO_1MIN / OMNI_HRO2_1MIN or pyspedas.projects.kyoto.load_ae",
                        "variables": ["AE_INDEX", "AL_INDEX", "AU_INDEX"],
                    },
                    {
                        "intent": "Kp activity index",
                        "preferred_source": "PySPEDAS NOAA/GFZ loader",
                        "dataset_or_loader": "pyspedas.projects.noaa.noaa_load_kp",
                        "variables": ["Kp", "ap"],
                        "notes": "Use pyspedas.geopack.kp2iopt to convert Kp for T89 iopt in PySPEDAS workflows.",
                    },
                    {
                        "intent": "SYM-H / high-cadence storm context",
                        "preferred_source": "CDAWeb HAPI OMNI",
                        "dataset_or_loader": "OMNI_HRO_1MIN / OMNI_HRO2_1MIN",
                        "variables": ["SYM_H", "SYM_D", "ASY_H", "ASY_D"],
                    },
                ],
                "mission_overview_starting_points": {
                    "THEMIS": ["THA_L2_FGM", "THA_L2_ESA", "THA_L2_SST", "THA_OR_SSC"],
                    "MMS": [
                        "MMS1_FGM_SRVY_L2",
                        "MMS1_FPI_FAST_L2_DIS-MOMS",
                        "MMS1_EDP_SRVY_L2_DCE",
                        "MMS1_MEC_SRVY_L2_EPHT89D",
                    ],
                    "Van Allen Probes/RBSP": [
                        "query CDAWeb for RBSP/Van Allen Probes EMFISIS, MagEIS, REPT, HOPE, EFW, RBSPICE, and magnephem products"
                    ],
                },
            },
        })

    @mcp.tool()
    def search_spedas_data_sources(
        question: str = "",
        target: str | None = None,
        observables: list[str] | None = None,
        query: str | None = None,
    ) -> str:
        """Recommend whether a SPEDAS request should start with CDAWeb, PDS, SPICE, or a mix.

        Pass the natural-language science goal as ``question``. ``query`` is accepted
        as a backward-compatible alias so callers familiar with
        ``browse_data_sources(query=...)`` are not silently given empty results;
        ``question`` takes precedence when both are provided.
        """
        from spedas_mcp.workflows import search_data_sources

        return _json(
            search_data_sources(
                question=question,
                target=target,
                observables=observables,
                query=query,
            )
        )

    @mcp.tool()
    @_safe_tool
    def plan_spedas_observation(
        science_goal: str,
        start: str | None = None,
        stop: str | None = None,
        target: str | None = None,
        observables: list[str] | None = None,
        data_sources: list[str] | None = None,
    ) -> str:
        """Plan a SPEDAS science workflow before choosing data-layer or geometry calls.

        Infers ISO dates and mission names from ``science_goal`` when ``start``,
        ``stop``, or ``target`` are omitted; explicit parameters always win and
        inferred values are reported under ``inferred`` for transparency.
        """
        from spedas_mcp.workflows import plan_observation

        return _json(plan_observation(
            science_goal=science_goal,
            start=start,
            stop=stop,
            target=target,
            observables=observables,
            data_sources=data_sources,
        ))

    @mcp.tool()
    def compare_cdaweb_pds_spice(science_goal: str = "") -> str:
        """Compare CDAWeb, PDS, and SPICE roles for a SPEDAS MCP science request."""
        from spedas_mcp.workflows import compare_sources

        return _json(compare_sources(science_goal=science_goal))

    @mcp.tool()
    def create_spedas_analysis_bundle(
        study_name: str,
        output_dir: str,
        science_goal: str = "",
        target: str | None = None,
        start: str | None = None,
        stop: str | None = None,
        data_sources: list[str] | None = None,
    ) -> str:
        """Create a lightweight request/provenance bundle for a planned SPEDAS analysis."""
        from spedas_mcp.workflows import create_analysis_bundle

        return _json(create_analysis_bundle(
            study_name=study_name,
            output_dir=output_dir,
            science_goal=science_goal,
            target=target,
            start=start,
            stop=stop,
            data_sources=data_sources,
        ))

    @_compat_tool
    def browse_observatories() -> str:
        """Compatibility: list CDAWeb observatories. Prefer browse_data_sources(source_type="cdaweb") for new workflows."""
        from spedas_mcp.backends.cdaweb.catalog import browse_observatories as _browse_observatories

        return _json(_browse_observatories())

    @_compat_tool
    @_safe_tool
    def load_observatory(observatory_id: str) -> str:
        """Compatibility: load CDAWeb observatory context. Prefer load_data_source(source_type="cdaweb", source_id=...)."""
        from spedas_mcp.backends.cdaweb.prompts import build_observatory_prompt

        return build_observatory_prompt(observatory_id)

    @_compat_tool
    def browse_parameters(dataset_id: str, dataset_ids: list[str] | None = None) -> str:
        """Compatibility: browse CDAWeb variables. Prefer browse_data_parameters(source_type="cdaweb", ...)."""
        from spedas_mcp.backends.cdaweb.metadata import browse_parameters as _browse_parameters

        return _json(_browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids))

    @_compat_tool
    @_safe_tool
    def fetch_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
        limit: int | None = None,
    ) -> str:
        """Compatibility: fetch CDAWeb time-series data. Prefer fetch_data_product(source_type="cdaweb", ...)."""
        import pandas as pd
        from spedas_mcp.backends.cdaweb.fetch import fetch_data as _fetch_data

        time_error = _validate_fetch_time_range(start, stop, source_type="cdaweb")
        if time_error is not None:
            return time_error
        lib_result = _fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_short = start[:10].replace("-", "")
        stop_short = stop[:10].replace("-", "")
        if limit is not None and limit <= 0:
            return _error_response(
                "invalid_argument",
                "CDAWeb fetch_data limit must be a positive integer when provided.",
                hint="Pass limit >= 1, or omit limit and narrow start/stop/parameters instead.",
                sanitize=False,
                source_type="cdaweb",
                unsupported_argument="limit",
            )
        frames = []
        param_meta: dict[str, dict] = {}
        param_columns: dict[str, list[str]] = {}
        for param_id, entry in lib_result.items():
            if "error" in entry:
                param_meta[param_id] = {"status": "error", "message": entry["error"]}
                continue
            df = entry["data"]
            augmented_stats = _augment_cdaweb_stats(df, entry.get("stats"))
            df = df.copy()
            df.columns = [f"{param_id}.{c}" for c in df.columns]
            frames.append(df)
            param_columns[param_id] = list(df.columns)
            param_meta[param_id] = {
                "status": "success",
                "units": entry.get("units"),
                "description": entry.get("description"),
                "rows": len(df),
                "columns": list(df.columns),
                "stats": augmented_stats,
            }
        if not frames:
            return _no_data_response(
                source_type="cdaweb",
                dataset_id=dataset_id,
                parameters=parameters,
                start=start,
                stop=stop,
                parameter_metadata=param_meta,
            )
        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.join(frame, how="outer")
        rows_before_limit = len(merged)
        if limit is not None:
            merged_to_write = merged.head(limit)
        else:
            merged_to_write = merged
        rows_written = len(merged_to_write)
        rows_truncated = max(rows_before_limit - rows_written, 0)
        for param_id, columns in param_columns.items():
            present = [column for column in columns if column in merged_to_write.columns]
            if present:
                param_meta[param_id]["rows_written"] = int(merged_to_write[present].dropna(how="all").shape[0])
            else:
                param_meta[param_id]["rows_written"] = 0
            if limit is not None:
                param_meta[param_id]["limit_applied"] = rows_truncated > 0
                param_meta[param_id]["rows_before_limit"] = int(param_meta[param_id]["rows"])
                param_meta[param_id]["rows_truncated"] = max(int(param_meta[param_id]["rows"]) - int(param_meta[param_id]["rows_written"]), 0)
        base_name = f"{dataset_id}_{start_short}_{stop_short}"
        file_path = out_dir / f"{base_name}.{format}"
        counter = 1
        while file_path.exists():
            file_path = out_dir / f"{base_name}_{counter}.{format}"
            counter += 1
        if format == "json":
            data = {"time": merged_to_write.index.strftime("%Y-%m-%dT%H:%M:%S.%f").tolist()}
            for col in merged_to_write.columns:
                data[col] = [None if pd.isna(v) else v for v in merged_to_write[col].tolist()]
            file_path.write_text(json.dumps(data), encoding="utf-8")
        else:
            merged_to_write.to_csv(file_path)
        provenance_sidecar = _write_fetch_provenance_sidecar(
            file_path,
            source_type="cdaweb",
            dataset_id=dataset_id,
            parameters=parameters,
            start=start,
            stop=stop,
            fmt=format,
            extra={"rows_written": rows_written, "rows_before_limit": rows_before_limit},
        )
        return _json({
            "status": "success",
            "file_path": str(file_path),
            "provenance_sidecar": provenance_sidecar,
            "source_frame": _infer_coordinate_frame_from_dataset(dataset_id, parameters),
            "format": format,
            "dataset_id": dataset_id,
            "time_range": {"start": start, "stop": stop},
            "total_rows": rows_written,
            "rows_before_limit": rows_before_limit,
            "rows_written": rows_written,
            "rows_truncated": rows_truncated,
            "limit": limit,
            "limit_applied": limit is not None and rows_truncated > 0,
            "parameters": param_meta,
        })

    @_compat_tool
    def browse_pds_missions(query: str | None = None) -> str:
        """Compatibility: list PDS PPI missions. Prefer browse_data_sources(source_type="pds") for new workflows."""
        from spedas_mcp.backends.pds.catalog import browse_missions as _browse_missions

        return _json(_browse_missions(query=query))

    @_compat_tool
    @_safe_tool
    def load_pds_mission(mission_id: str) -> str:
        """Compatibility: load PDS mission context. Prefer load_data_source(source_type="pds", source_id=...)."""
        from spedas_mcp.backends.pds.prompts import build_mission_prompt

        return build_mission_prompt(mission_id)

    @_compat_tool
    def browse_pds_parameters(dataset_id: str | None = None, dataset_ids: list[str] | None = None) -> str:
        """Compatibility: browse PDS variables. Prefer browse_data_parameters(source_type="pds", ...)."""
        from spedas_mcp.backends.pds.metadata import browse_parameters as _browse_parameters

        return _json(_browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids))

    @_compat_tool
    @_safe_tool
    def fetch_pds_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
    ) -> str:
        """Compatibility: fetch PDS archive data. Prefer fetch_data_product(source_type="pds", ...)."""
        import re

        import pandas as pd
        from spedas_mcp.backends.pds.fetch import fetch_data as _fetch_data

        time_error = _validate_fetch_time_range(start, stop, source_type="pds")
        if time_error is not None:
            return time_error
        lib_result = _fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_short = start[:10].replace("-", "")
        stop_short = stop[:10].replace("-", "")
        frames = []
        param_meta: dict[str, dict] = {}
        for param_id, entry in lib_result.items():
            if "error" in entry:
                param_meta[param_id] = {"status": "error", "message": entry["error"]}
                continue
            df = entry["data"]
            df.columns = [f"{param_id}.{c}" for c in df.columns]
            frames.append(df)
            param_meta[param_id] = {
                "status": "success",
                "units": entry.get("units"),
                "description": entry.get("description"),
                "rows": len(df),
                "columns": list(df.columns),
                "stats": entry.get("stats"),
            }
        if not frames:
            return _no_data_response(
                source_type="pds",
                dataset_id=dataset_id,
                parameters=parameters,
                start=start,
                stop=stop,
                parameter_metadata=param_meta,
            )
        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.join(frame, how="outer")
        safe_dataset = re.sub(r"[^A-Za-z0-9_.-]+", "_", dataset_id).strip("_") or "pds_dataset"
        base_name = f"{safe_dataset}_{start_short}_{stop_short}"
        file_path = out_dir / f"{base_name}.{format}"
        counter = 1
        while file_path.exists():
            file_path = out_dir / f"{base_name}_{counter}.{format}"
            counter += 1
        if format == "json":
            data = {"time": merged.index.strftime("%Y-%m-%dT%H:%M:%S.%f").tolist()}
            for col in merged.columns:
                data[col] = [None if pd.isna(v) else v for v in merged[col].tolist()]
            file_path.write_text(json.dumps(data), encoding="utf-8")
        else:
            merged.to_csv(file_path)
        provenance_sidecar = _write_fetch_provenance_sidecar(
            file_path,
            source_type="pds",
            dataset_id=dataset_id,
            parameters=parameters,
            start=start,
            stop=stop,
            fmt=format,
            extra={"rows_written": len(merged)},
        )
        return _json({
            "status": "success",
            "file_path": str(file_path),
            "provenance_sidecar": provenance_sidecar,
            "source_frame": _infer_coordinate_frame_from_dataset(dataset_id, parameters),
            "format": format,
            "dataset_id": dataset_id,
            "time_range": {"start": start, "stop": stop},
            "total_rows": len(merged),
            "parameters": param_meta,
        })

    @_safe_tool
    def list_spice_missions() -> str:
        """List supported SPICE spacecraft/body missions with NAIF IDs and kernel status."""
        from spedas_mcp.backends.spice import list_supported_missions

        return _json(list_supported_missions())

    @mcp.tool()
    @_safe_tool
    def get_ephemeris(
        target: str,
        time: str,
        frame: str = "ECLIPJ2000",
        observer: str = "SUN",
        output_file: str = "",
        time_end: str = "",
        step: str = "1h",
        allow_kernel_download: bool = False,
    ) -> str:
        """Get single-time state inline or timeseries trajectory written to CSV.

        Validates ``target``/``observer`` against the SPICE mission registry
        before any backend call: an unsupported name (e.g. ``MMS1``) returns a
        structured ``unsupported_spice_target`` error with alternatives instead of
        an opaque "Cannot resolve body name" (issue #26). If the required SPICE
        kernels are not already cached, the call returns a ``needs_confirmation``
        ``kernel_download_required`` response rather than silently downloading
        100 MB-1 GB of kernels; pass ``allow_kernel_download=True`` (or pre-load
        with ``manage_data_cache(source_type='spice', action='load', mission=...)``) to proceed
        (issue #29).
        """
        from spedas_mcp.backends.spice import get_state, get_trajectory
        from spedas_mcp.backends.spice.kernel_manager import get_kernel_manager

        frame_preflight = _spice_frame_preflight(
            [(frame, "frame")],
            tool="get_ephemeris",
        )
        if frame_preflight is not None:
            return frame_preflight

        preflight = _spice_geometry_preflight(
            [(target, "target"), (observer, "observer")],
            tool="get_ephemeris",
            allow_kernel_download=allow_kernel_download,
        )
        if preflight is not None:
            return preflight

        if time_end:
            if not output_file:
                return _error_response(
                    "invalid_argument",
                    "output_file is required when time_end is provided",
                    hint="Provide an output_file path for the trajectory CSV when time_end is set.",
                    sanitize=False,
                    tool="get_ephemeris",
                )
            df = get_trajectory(
                target=target,
                observer=observer,
                time_start=time,
                time_end=time_end,
                step=step,
                frame=frame,
                include_velocity=True,
            )
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_file, index=False)
            return _json({
                "status": "success",
                "mode": "timeseries",
                "target": target,
                "observer": observer,
                "frame": frame,
                "time_start": time,
                "time_end": time_end,
                "step": step,
                "rows": len(df),
                "output_file": output_file,
                "cache_size_mb": round(get_kernel_manager().get_cache_size_bytes() / (1024 * 1024), 2),
            })
        state = get_state(target=target, observer=observer, time=time, frame=frame)
        state["status"] = "success"
        state["cache_size_mb"] = round(get_kernel_manager().get_cache_size_bytes() / (1024 * 1024), 2)
        return _json(state)

    @mcp.tool()
    @_safe_tool
    def compute_distance(
        target1: str,
        target2: str,
        time_start: str,
        time_end: str,
        step: str = "1h",
        allow_kernel_download: bool = False,
    ) -> str:
        """Compute distance between two SPICE targets over a time range.

        Both targets are validated against the SPICE registry before any backend
        call (unsupported names return ``unsupported_spice_target``, issue #26),
        and the call returns a ``kernel_download_required`` confirmation rather
        than silently downloading uncached kernels unless
        ``allow_kernel_download=True`` (issue #29).
        """
        import numpy as np
        from spedas_mcp.backends.spice import get_trajectory

        preflight = _spice_geometry_preflight(
            [(target1, "target1"), (target2, "target2"), ("SUN", "observer")],
            tool="compute_distance",
            allow_kernel_download=allow_kernel_download,
        )
        if preflight is not None:
            return preflight

        df1 = get_trajectory(target1, observer="SUN", time_start=time_start, time_end=time_end, step=step)
        df2 = get_trajectory(target2, observer="SUN", time_start=time_start, time_end=time_end, step=step)
        distances = np.sqrt((df1["x_km"] - df2["x_km"]) ** 2 + (df1["y_km"] - df2["y_km"]) ** 2 + (df1["z_km"] - df2["z_km"]) ** 2)
        return _json({
            "status": "success",
            "target1": target1,
            "target2": target2,
            "time_start": time_start,
            "time_end": time_end,
            "step": step,
            "min_distance_km": float(distances.min()),
            "max_distance_km": float(distances.max()),
            "mean_distance_km": float(distances.mean()),
            "samples": len(distances),
        })

    @mcp.tool()
    @_safe_tool
    def transform_coordinates(
        vector: list[float],
        time: str,
        from_frame: str,
        to_frame: str,
        spacecraft: str | None = None,
        allow_kernel_download: bool = False,
    ) -> str:
        """Transform a 3D vector between SPICE coordinate frames.

        Frame transforms always furnish the generic SPICE kernels, and RTN
        transforms additionally need the ``spacecraft`` mission's kernels. To
        avoid a silent 100 MB+ generic-kernel download on first use, the call
        returns a ``kernel_download_required`` confirmation when required kernels
        are not cached unless ``allow_kernel_download=True`` (issue #29). A named
        ``spacecraft`` that is not SPICE-supported returns
        ``unsupported_spice_target`` (issue #26).
        """
        import numpy as np
        from spedas_mcp.backends.spice import transform_vector

        frame_preflight = _spice_frame_preflight(
            [(from_frame, "from_frame"), (to_frame, "to_frame")],
            tool="transform_coordinates",
        )
        if frame_preflight is not None:
            return frame_preflight

        # Only ``spacecraft`` is a body name; from_frame/to_frame are frames.
        # Generic kernels are required regardless, so the cache gate runs even
        # when no spacecraft is given.
        preflight = _spice_geometry_preflight(
            [(spacecraft, "spacecraft")] if spacecraft else [],
            tool="transform_coordinates",
            allow_kernel_download=allow_kernel_download,
        )
        if preflight is not None:
            return preflight

        result = transform_vector(vector, time, from_frame=from_frame, to_frame=to_frame, spacecraft=spacecraft)
        output_vector = np.asarray(result, dtype=float).tolist()
        return _json({
            "status": "success",
            "input_vector": vector,
            "output_vector": output_vector,
            "from_frame": from_frame,
            "to_frame": to_frame,
            "time": time,
            "spacecraft": spacecraft,
        })

    @_safe_tool
    def list_coordinate_frames() -> str:
        """Compatibility: list supported SPICE coordinate frames and usage notes."""
        return _json(_spice_frame_catalog()["frames"])

    def manage_cdaweb_cache(
        action: Literal["status", "clean", "refresh_metadata", "refresh_time_ranges", "rebuild_catalog"],
        category: Literal["metadata", "cdf_cache", "all"] = "all",
        observatory: str | None = None,
        dataset_ids: list[str] | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
        detail: bool = False,
    ) -> str:
        """Compatibility: manage CDAWeb cache. Prefer manage_data_cache(source_type="cdaweb", ...)."""
        from spedas_mcp.backends.cdaweb.cache import cache_clean, cache_status, rebuild_catalog, refresh_metadata, refresh_time_ranges

        if action == "status":
            return _json(cache_status(detail=detail))
        if action == "clean":
            return _json(cache_clean(category=category, observatories=[observatory] if observatory else None, older_than_days=older_than_days, dry_run=dry_run))
        if action == "refresh_metadata":
            return _json(refresh_metadata(dataset_ids=dataset_ids, observatory=observatory))
        if action == "refresh_time_ranges":
            return _json(refresh_time_ranges(observatory=observatory))
        if action == "rebuild_catalog":
            return _json(rebuild_catalog(observatory=observatory))
        return _json({"status": "error", "message": f"Unknown action: {action}"})

    def manage_pds_cache(
        action: Literal["status", "clean", "refresh_metadata", "build_metadata", "refresh_time_ranges", "rebuild_catalog"],
        category: Literal["metadata", "data_cache", "all"] = "all",
        mission: str | None = None,
        dataset_ids: list[str] | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
        detail: bool = False,
        force: bool = False,
    ) -> str:
        """Compatibility: manage PDS cache. Prefer manage_data_cache(source_type="pds", ...)."""
        from spedas_mcp.backends.pds.cache import build_metadata, cache_clean, cache_status, refresh_metadata, refresh_time_ranges, rebuild_catalog

        if action == "status":
            return _json(cache_status(detail=detail))
        if action == "clean":
            missions = [mission] if mission else None
            return _json(cache_clean(category=category, missions=missions, older_than_days=older_than_days, dry_run=dry_run))
        if action == "refresh_metadata":
            return _json(refresh_metadata(dataset_ids=dataset_ids, mission=mission))
        if action == "build_metadata":
            return _json(build_metadata(mission=mission, force=force))
        if action == "refresh_time_ranges":
            return _json(refresh_time_ranges(mission=mission))
        if action == "rebuild_catalog":
            return _json(rebuild_catalog(mission=mission))
        return _json({"status": "error", "message": f"Unknown action: {action}"})

    def manage_spice_kernels(
        action: Literal["status", "load", "clean", "check_remote", "purge"],
        mission: str | None = None,
        filenames: list[str] | None = None,
    ) -> str:
        """Manage SPICE kernels/cache; use manage_data_cache(source_type="spice") for data-layer cache status."""
        from spedas_mcp.backends.spice.kernel_manager import check_remote_kernels, get_kernel_manager

        km = get_kernel_manager()
        if action == "status":
            return _json(km.get_cache_info())
        if action == "load":
            if not mission:
                return _json({"status": "error", "message": "mission is required for load"})
            km.ensure_mission_kernels(mission)
            return _json({"status": "success", "mission": mission, "cache_info": km.get_cache_info()})
        if action == "clean":
            if not mission and not filenames:
                return _json({"status": "error", "message": "mission or filenames required for clean"})
            deleted = km.delete_cached_files(filenames) if filenames else km.delete_mission_cache(mission or "")
            return _json({"status": "success", "deleted_files": deleted, "cache_info": km.get_cache_info()})
        if action == "check_remote":
            return _json(check_remote_kernels(mission) if mission else {"status": "error", "message": "mission is required for check_remote"})
        if action == "purge":
            deleted = km.purge_cache()
            return _json({"status": "success", "deleted_files": deleted})
        return _json({"status": "error", "message": f"Unknown action: {action}"})


    def _normalize_source_type(source_type: str | None) -> str:
        value = (source_type or "all").strip().lower().replace("-", "_")
        aliases = {
            "all_sources": "all",
            "all": "all",
            "cda": "cdaweb",
            "cda_web": "cdaweb",
            "cdaweb": "cdaweb",
            "pds_ppi": "pds",
            "pds": "pds",
            "spice_geometry": "spice",
            "geometry": "spice",
            "spice": "spice",
            "hapi": "hapi",
            "hapi_server": "hapi",
            "fdsn": "fdsn",
            "mth5": "fdsn",
            "magnetotelluric": "fdsn",
        }
        return aliases.get(value, value)

    def _payload_has_error(payload: Any) -> bool:
        if isinstance(payload, dict):
            status = str(payload.get("status", "")).lower()
            if status in {"error", "failed", "failure"}:
                return True
            if payload.get("error"):
                return True
            return any(_payload_has_error(value) for value in payload.values())
        if isinstance(payload, list):
            return any(_payload_has_error(value) for value in payload)
        return False

    def _translate_facade_guidance(raw: str, source_type: str) -> str:
        """Rewrite backend how-to prose into the unified facade vocabulary.

        Backend prompts are useful, but their embedded workflow text can name
        low-level compatibility tools (browse_parameters/fetch_data/manage_cache).
        load_data_source is the primary facade entry point, so payload guidance
        should keep agents on browse_data_parameters/fetch_data_product/
        manage_data_cache with an explicit source_type (issues #66/#73).
        """
        source = _normalize_source_type(source_type)
        replacements = {
            "browse_parameters(dataset_id)": f"browse_data_parameters(source_type=\"{source}\", dataset_id=...)",
            "browse_parameters(dataset_id=dataset_id)": f"browse_data_parameters(source_type=\"{source}\", dataset_id=dataset_id)",
            "browse_parameters(dataset_id=...)": f"browse_data_parameters(source_type=\"{source}\", dataset_id=...)",
            "fetch_data(dataset_id, parameters, start, stop, output_dir)": f"fetch_data_product(source_type=\"{source}\", dataset_id=..., parameters=..., start=..., stop=..., output_dir=...)",
            "fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop, output_dir=output_dir)": f"fetch_data_product(source_type=\"{source}\", dataset_id=dataset_id, parameters=parameters, start=start, stop=stop, output_dir=output_dir)",
            "manage_cache(action=\"rebuild_catalog\")": f"manage_data_cache(source_type=\"{source}\", action=\"status\")",
            "manage_cache(action='rebuild_catalog')": f"manage_data_cache(source_type=\"{source}\", action=\"status\")",
            "manage_cache": "manage_data_cache",
        }
        translated = raw
        for old_text, new_text in replacements.items():
            translated = translated.replace(old_text, new_text)
        # Catch remaining bare function names without altering already translated
        # facade calls.
        translated = re.sub(
            r"(?<!data_)\bbrowse_parameters\b(?!\s*\(source_type=)",
            f"browse_data_parameters(source_type=\"{source}\", dataset_id=...)",
            translated,
        )
        translated = re.sub(
            r"(?<!_)\bfetch_data\b(?!_product)(?!\s*\(source_type=)",
            f"fetch_data_product(source_type=\"{source}\", dataset_id=..., parameters=..., start=..., stop=..., output_dir=...)",
            translated,
        )
        translated = re.sub(
            r"\bmanage_cache\b(?!\s*\(source_type=)",
            f"manage_data_cache(source_type=\"{source}\", action=\"status\")",
            translated,
        )
        return translated

    def _translate_cdaweb_facade_guidance(raw: str) -> str:
        """Backward-compatible wrapper for CDAWeb prompt translation."""
        return _translate_facade_guidance(raw, "cdaweb")


    def _wrap_data_payload(source_type: str, raw: str, **extra: Any) -> str:
        try:
            payload = json.loads(raw)
        except Exception:
            # A non-JSON backend string is almost always a raw error/traceback
            # (e.g. a FileNotFoundError carrying a local cache path). Sanitize it
            # instead of forwarding raw filesystem paths to the client
            # (issues #25/#27).
            payload = _sanitize_message(raw)
        if (
            isinstance(payload, dict)
            and str(payload.get("status", "")).lower() == "error"
        ):
            # If a compatibility fetch already returned the uniform structured
            # envelope, keep code/message at the top level for fetch_data_product
            # callers instead of burying them under payload (issues #75/#76).
            return _size_guarded(_json({**payload, "source_type": source_type, **extra}), source_type=source_type)
        status = "error" if _payload_has_error(payload) else "success"
        return _size_guarded(
            _json({"status": status, "source_type": source_type, "payload": payload, **extra}),
            source_type=source_type,
        )

    def _filter_json_records(raw: str, query: str | None) -> str:
        """Apply a compact query filter to list-shaped backend JSON payloads."""
        if not query:
            return raw
        try:
            payload = json.loads(raw)
        except Exception:
            return raw
        if not isinstance(payload, list):
            return raw
        needle = query.casefold()
        filtered = [
            entry for entry in payload
            if needle in json.dumps(entry, default=str).casefold()
        ]
        return _json(filtered)

    _CDAWEB_PRODUCT_ALIASES: dict[str, tuple[str, ...]] = {
        "fgm": ("fgm", "flux gate", "fluxgate", "magnetic field", "magnetometer", "mag"),
        "mag": ("mag", "magnetic field", "magnetometer", "b-field", "imf"),
        "imf": ("imf", "interplanetary magnetic field", "magnetic field"),
        "fpi": ("fpi", "fast plasma investigation", "plasma", "ion", "electron"),
        "esa": ("esa", "electrostatic analyzer", "plasma", "particle"),
        "mec": ("mec", "ephemeris", "orbit", "position", "spacecraft position"),
        "rtn": ("rtn",),
        "srvy": ("srvy", "survey"),
        "brst": ("brst", "burst"),
    }

    def _query_terms(query: str | None) -> list[str]:
        if not query:
            return []
        raw_terms = re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", query.casefold())
        terms: list[str] = []
        for term in raw_terms:
            variants = {term, term.replace("-", "_"), term.replace("_", "-")}
            variants.update(_CDAWEB_PRODUCT_ALIASES.get(term, ()))
            for variant in variants:
                variant = variant.casefold()
                if variant and variant not in terms:
                    terms.append(variant)
        return terms

    def _text_matches(text: str, term: str) -> bool:
        text = text.casefold()
        term = term.casefold()
        if " " in term or "-" in term or "_" in term:
            return term in text or term.replace(" ", "_") in text or term.replace(" ", "-") in text
        return bool(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text)) or term in text.replace("_", " ").replace("-", " ")

    def _cdaweb_dataset_query_candidates(raw_records: str, query: str | None, *, limit: int = 12) -> list[dict[str, Any]]:
        """Search CDAWeb observatory dataset catalogs for mission+instrument queries.

        ``browse_observatories`` only lists observatory-level rows, so a natural
        query such as ``MMS FGM`` previously filtered the observatory list to an
        empty success. This helper searches the per-observatory dataset catalogs
        when the query has product/instrument terms and returns ranked dataset
        candidates with exact facade follow-up calls.
        """
        terms = _query_terms(query)
        if not terms:
            return []
        try:
            records = json.loads(raw_records)
        except Exception:
            return []
        if not isinstance(records, list):
            return []
        try:
            from spedas_mcp.backends.cdaweb.catalog import load_observatory_json
        except Exception:  # pre-#111 backend layout / backend not installed
            try:
                from cdawebmcp.catalog import load_observatory_json
            except Exception:  # pragma: no cover - backend not installed
                return []

        mission_terms = [term for term in terms if term not in {alias for aliases in _CDAWEB_PRODUCT_ALIASES.values() for alias in aliases}]
        observatories: list[tuple[str, dict[str, Any]]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            source_id = str(record.get("id") or "").strip()
            if not source_id:
                continue
            source_text = json.dumps({k: record.get(k) for k in ("id", "name", "aliases", "description")}, default=str)
            source_hits = [term for term in mission_terms if _text_matches(source_text, term)]
            # If no observatory/mission token was identified, allow a bounded
            # cross-catalog product search; otherwise keep the search focused.
            if source_hits or not mission_terms:
                observatories.append((source_id, record))
        if not observatories:
            return []

        candidates: list[dict[str, Any]] = []
        for source_id, record in observatories[:30]:
            try:
                observatory = load_observatory_json(source_id.strip().lower().replace("-", "_"))
            except Exception:
                continue
            instruments = observatory.get("instruments", {})
            if not isinstance(instruments, dict):
                continue
            source_name = str(observatory.get("name") or record.get("name") or source_id)
            source_text = json.dumps({"id": source_id, "name": source_name, "record": record}, default=str)
            source_hits = [term for term in terms if _text_matches(source_text, term)]
            for inst_key, inst_data in sorted(instruments.items()):
                if not isinstance(inst_data, dict):
                    continue
                inst_name = str(inst_data.get("name") or inst_key)
                inst_text = json.dumps({
                    "instrument": inst_key,
                    "name": inst_name,
                    "keywords": inst_data.get("keywords", []),
                }, default=str)
                inst_hits = [term for term in terms if _text_matches(inst_text, term)]
                datasets = inst_data.get("datasets", {})
                if not isinstance(datasets, dict):
                    continue
                for dataset_id, ds_info in sorted(datasets.items()):
                    info = ds_info if isinstance(ds_info, dict) else {}
                    dataset_text = json.dumps({"dataset_id": dataset_id, **info}, default=str)
                    dataset_hits = [term for term in terms if _text_matches(dataset_text, term)]
                    hits = []
                    for hit in [*source_hits, *inst_hits, *dataset_hits]:
                        if hit not in hits:
                            hits.append(hit)
                    raw_query_terms = re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", (query or "").casefold())
                    matched_raw = [
                        term for term in raw_query_terms
                        if any(_text_matches(text, term) for text in (source_text, inst_text, dataset_text))
                        or any(_text_matches(text, alias) for alias in _CDAWEB_PRODUCT_ALIASES.get(term, ()) for text in (source_text, inst_text, dataset_text))
                    ]
                    if len(set(matched_raw)) < min(2, len(set(raw_query_terms))):
                        continue
                    score = 10 * len(set(source_hits)) + 5 * len(set(dataset_hits)) + 3 * len(set(inst_hits))
                    if any(term in str(dataset_id).casefold() for term in raw_query_terms):
                        score += 4
                    if "srvy" in str(dataset_id).casefold() or "survey" in dataset_text.casefold():
                        score += 1
                    why = []
                    if source_hits:
                        why.append(f"matched CDAWeb observatory/source {source_id!r}")
                    if inst_hits:
                        why.append(f"matched instrument {inst_name!r}")
                    if dataset_hits:
                        why.append(f"matched dataset metadata/id {dataset_id!r}")
                    candidates.append({
                        "source_type": "cdaweb",
                        "source_id": source_id,
                        "source_name": source_name,
                        "dataset_id": dataset_id,
                        "instrument": inst_key,
                        "instrument_name": inst_name,
                        "start_date": info.get("start_date"),
                        "stop_date": info.get("stop_date"),
                        "score": score,
                        "why": "; ".join(why) if why else "matched query terms in CDAWeb dataset catalog",
                        "next_tools": [
                            f"browse_data_parameters(source_type='cdaweb', dataset_id='{dataset_id}')",
                            f"fetch_data_product(source_type='cdaweb', dataset_id='{dataset_id}', parameters=..., start=..., stop=..., output_dir=...)",
                        ],
                    })

        candidates.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("dataset_id", ""))))
        seen: set[str] = set()
        deduped = []
        for item in candidates:
            dataset_id = str(item.get("dataset_id"))
            if dataset_id in seen:
                continue
            seen.add(dataset_id)
            deduped.append(item)
            if len(deduped) >= limit:
                break
        return deduped

    def _normalize_pds_source_id(source_id: str) -> str:
        value = (source_id or "").strip().lower().replace("-", "_")
        if value.endswith("_ppi"):
            value = value[:-4]
        return value

    def _catalog_ids(raw: str) -> list[str]:
        """Extract canonical ``id`` values from a list-shaped catalog JSON string.

        Returns an empty list if the backend payload is unavailable or not the
        expected list-of-records shape, so callers degrade gracefully rather than
        raising (which would defeat the path-leak protection in issue #25).
        """
        try:
            payload = json.loads(raw)
        except Exception:
            return []
        if not isinstance(payload, list):
            return []
        ids: list[str] = []
        for entry in payload:
            if isinstance(entry, dict):
                value = entry.get("id")
                if isinstance(value, str) and value:
                    ids.append(value)
        return ids

    def _suggest_ids(candidate: str, valid_ids: list[str], limit: int = 3) -> list[str]:
        """Best-effort "did you mean" suggestions for an unknown source_id.

        Matches case-insensitively and tolerates ``-``/``_`` differences, then
        falls back to difflib fuzzy matching so typos like ``MMS1`` -> ``mms``
        surface a recovery path (issues #25/#27).
        """
        import difflib

        def _norm(value: str) -> str:
            return value.strip().lower().replace("-", "_")

        cand = _norm(candidate)
        scored: list[str] = []
        # Prefix/substring matches first (e.g. "MMS1" -> "mms").
        for vid in valid_ids:
            nid = _norm(vid)
            if nid == cand or nid.startswith(cand) or cand.startswith(nid):
                scored.append(vid)
        if not scored:
            close = difflib.get_close_matches(
                cand, [_norm(v) for v in valid_ids], n=limit, cutoff=0.6
            )
            norm_to_orig = {_norm(v): v for v in valid_ids}
            scored = [norm_to_orig[c] for c in close if c in norm_to_orig]
        # De-duplicate while preserving order.
        seen: set[str] = set()
        ordered = [s for s in scored if not (s in seen or seen.add(s))]
        return ordered[:limit]

    def _validate_source_id(
        source_type: str,
        source_id: str,
        valid_ids: list[str],
        match: str,
        discover_tool: str,
        normalizer=None,
    ) -> str | None:
        """Return a structured error envelope if ``source_id`` is unknown, else None.

        ``match`` is the already-normalized id the backend would look up; it is
        compared against the canonical catalog after applying ``normalizer`` (the
        same backend-specific normalization, defaulting to lowercase + ``-``/``_``
        folding) to each valid id so equivalent forms compare equal. On a miss
        the response carries suggestions and a sample of valid ids so the agent
        can recover without ever seeing a filesystem path (issue #25). When the
        catalog is unavailable (``valid_ids`` empty) validation is skipped and the
        backend call proceeds — the size guard and payload sanitizer remain the
        backstop.
        """
        if not valid_ids:
            return None
        if normalizer is None:
            def normalizer(value: str) -> str:
                return value.strip().lower().replace("-", "_")
        normalized = {normalizer(vid) for vid in valid_ids}
        if normalizer(match) in normalized:
            return None
        suggestions = _suggest_ids(source_id, valid_ids)
        hint_parts: list[str] = []
        if suggestions:
            hint_parts.append("Did you mean: " + ", ".join(repr(s) for s in suggestions) + "?")
        hint_parts.append(f"Use {discover_tool} to list valid IDs.")
        return _error_response(
            "unknown_source_id",
            f"Source ID '{source_id}' not found in {source_type} catalog.",
            hint=" ".join(hint_parts),
            source_type=source_type,
            source_id=source_id,
            suggestions=suggestions,
            valid_ids_sample=sorted(valid_ids)[:8],
        )

    # Default page size for compact CDAWeb dataset catalogs. Keep the complete
    # load_data_source(cdaweb, source_id="mms") response under ~12 KB by default
    # while still returning enough concrete dataset IDs for agents to proceed.
    _DATASET_ENUM_DEFAULT_LIMIT = 10
    _DATASET_ENUM_MAX_LIMIT = 100

    def _bounded_int(value: int | None, *, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value) if value is not None else default
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def _dataset_matches_query(entry: dict[str, Any], query: str | None) -> bool:
        if not query:
            return True
        haystack = json.dumps(entry, default=str).casefold()
        raw_terms = re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", query.casefold()) or [query.casefold()]
        for term in raw_terms:
            variants = [term, term.replace("-", "_"), term.replace("_", "-")]
            variants.extend(_CDAWEB_PRODUCT_ALIASES.get(term, ()))
            if not any(_text_matches(haystack, variant) for variant in variants if variant):
                return False
        return True

    def _dataset_matches_instrument(entry: dict[str, Any], instrument: str | None) -> bool:
        if not instrument:
            return True
        # CDAWeb observatory JSON sometimes groups product-specific datasets under
        # a broader instrument bucket (for example MMS FGM datasets live under the
        # ``mag`` / Magnetic Fields bucket). Match the user's raw instrument terms
        # against both the bucket metadata and dataset id, but do not expand broad
        # aliases such as fgm -> magnetic field here or FGM would accidentally
        # include SCM/DSP magnetic-field products from the same bucket.
        haystack = " ".join(
            str(entry.get(key) or "")
            for key in ("dataset_id", "instrument", "instrument_name")
        ).casefold()
        raw_terms = re.findall(r"[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)*", instrument.casefold()) or [instrument.casefold()]
        for term in raw_terms:
            variants = [term, term.replace("-", "_"), term.replace("_", "-")]
            if not any(_text_matches(haystack, variant) for variant in variants if variant):
                return False
        return True

    def _enumerate_cdaweb_datasets(
        source_id: str,
        *,
        limit: int | None = None,
        offset: int = 0,
        instrument: str | None = None,
        dataset_query: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a paginated, JSON-serializable CDAWeb dataset catalog.

        Reads the observatory JSON directly so agents can move from
        ``load_data_source`` to ``browse_data_parameters`` without guessing
        dataset IDs. The default compact page intentionally omits the large human
        prompt and returns pagination/filter metadata so large observatories such
        as MMS stay small and agent-friendly (issue #113).
        """
        try:
            from spedas_mcp.backends.cdaweb.catalog import load_observatory_json
        except Exception:  # pragma: no cover - backend not installed
            return None
        stem = (source_id or "").strip().lower().replace("-", "_")
        try:
            observatory = load_observatory_json(stem)
        except Exception:
            return None

        instruments = observatory.get("instruments", {})
        if not isinstance(instruments, dict):
            return None

        instrument_names = sorted(instruments.keys())
        instrument_filter = instrument.strip().casefold() if isinstance(instrument, str) and instrument.strip() else None
        all_entries: list[dict[str, Any]] = []
        for inst_key, inst_data in sorted(instruments.items()):
            if not isinstance(inst_data, dict):
                continue
            inst_name = str(inst_data.get("name") or inst_key)
            for ds_id, ds_info in sorted(inst_data.get("datasets", {}).items()):
                ds_info = ds_info if isinstance(ds_info, dict) else {}
                entry = {
                    "dataset_id": ds_id,
                    "instrument": inst_key,
                    "instrument_name": inst_name,
                    "start_date": ds_info.get("start_date"),
                    "stop_date": ds_info.get("stop_date"),
                    "next_tools": [
                        f"browse_data_parameters(source_type='cdaweb', dataset_id='{ds_id}')",
                        f"fetch_data_product(source_type='cdaweb', dataset_id='{ds_id}', parameters=..., start=..., stop=..., output_dir=...)",
                    ],
                }
                if _dataset_matches_instrument(entry, instrument_filter) and _dataset_matches_query(entry, dataset_query):
                    all_entries.append(entry)

        filtered_count = len(all_entries)
        page_limit = _bounded_int(limit, default=_DATASET_ENUM_DEFAULT_LIMIT, minimum=1, maximum=_DATASET_ENUM_MAX_LIMIT)
        page_offset = _bounded_int(offset, default=0, minimum=0, maximum=max(filtered_count, 0))
        page_entries = all_entries[page_offset:page_offset + page_limit]
        next_offset = page_offset + len(page_entries) if page_offset + len(page_entries) < filtered_count else None

        grouped: dict[str, list[dict[str, Any]]] = {}
        for entry in page_entries:
            compact_entry = {k: entry[k] for k in ("dataset_id", "start_date", "stop_date", "next_tools")}
            grouped.setdefault(str(entry["instrument"]), []).append(compact_entry)

        payload: dict[str, Any] = {
            "dataset_count": sum(
                len(inst_data.get("datasets", {}))
                for inst_data in instruments.values()
                if isinstance(inst_data, dict) and isinstance(inst_data.get("datasets", {}), dict)
            ),
            "filtered_dataset_count": filtered_count,
            "datasets": page_entries,
            "datasets_truncated": next_offset is not None,
            "datasets_limit": page_limit,
            "datasets_offset": page_offset,
            "datasets_next_offset": next_offset,
            "instruments": instrument_names,
            "dataset_candidates_by_instrument": grouped,
        }
        if instrument_filter:
            payload["instrument_filter"] = instrument
        if dataset_query:
            payload["dataset_query"] = dataset_query
        if next_offset is not None:
            payload["datasets_note"] = (
                f"Showing datasets {page_offset + 1}-{page_offset + len(page_entries)} of {filtered_count} "
                f"matching datasets. Continue with load_data_source(source_type='cdaweb', "
                f"source_id='{source_id}', limit={page_limit}, offset={next_offset}) or narrow with "
                "instrument=... / dataset_query=...."
            )
        elif page_offset:
            payload["datasets_note"] = (
                f"Showing final page starting at offset {page_offset} for {filtered_count} "
                "matching datasets. Reduce offset or narrow with instrument=... / dataset_query=...."
            )
        return payload

    @mcp.tool()
    def browse_data_sources(source_type: str = "all", query: str | None = None) -> str:
        """Primary data layer: browse SPEDAS source categories (CDAWeb, PDS, SPICE)."""
        source = _normalize_source_type(source_type)
        if source == "all":
            return _json({
                "status": "success",
                "data_layer": "spedas",
                "source_types": [
                    {
                        "source_type": "cdaweb",
                        "label": "CDAWeb heliophysics time-series",
                        "best_for": "observatory/dataset/parameter discovery and measurement fetches",
                        "next_tools": ["browse_data_sources(source_type='cdaweb')", "load_data_source", "browse_data_parameters", "fetch_data_product"],
                    },
                    {
                        "source_type": "pds",
                        "label": "PDS Planetary Plasma Interactions archive",
                        "best_for": "planetary mission/dataset/parameter discovery and archive-backed fetches",
                        "next_tools": ["browse_data_sources(source_type='pds')", "load_data_source", "browse_data_parameters", "fetch_data_product"],
                    },
                    {
                        "source_type": "spice",
                        "label": "SPICE geometry and ephemeris",
                        "best_for": "trajectory, distance, frames, coordinate transforms, and geometry context",
                        "next_tools": ["browse_data_sources(source_type='spice')", "load_data_source", "get_ephemeris", "compute_distance", "transform_coordinates"],
                    },
                    {
                        "source_type": "hapi",
                        "label": "HAPI time-series servers (CDAWeb, PDS-PPI, ISWA, LISIRD, ...)",
                        "best_for": "any HAPI-compliant server; generic catalog discovery and time-series fetch",
                        "optional_extra": "spedas-mcp[hapi]",
                        "available": optional_backends["hapi"]["available"],
                        "requires_extra": optional_backends["hapi"]["requires_extra"],
                        "install_hint": optional_backends["hapi"]["install_hint"],
                        "registration": optional_backends["hapi"]["registration"],
                        "missing_modules": optional_backends["hapi"].get("missing_modules", []),
                        "next_tools": ["browse_hapi_catalog(server_url=...)", "fetch_hapi_data(server_url=..., dataset_id=..., parameters=[...])"],
                    },
                    {
                        "source_type": "fdsn",
                        "label": "FDSN/MTH5 magnetotelluric magnetic-field stations (EarthScope)",
                        "best_for": "ground-based 3-component MT magnetic observations for ground-magnetosphere coupling",
                        "optional_extra": "spedas-mcp[fdsn]",
                        "available": optional_backends["fdsn"]["available"],
                        "requires_extra": optional_backends["fdsn"]["requires_extra"],
                        "install_hint": optional_backends["fdsn"]["install_hint"],
                        "registration": optional_backends["fdsn"]["registration"],
                        "missing_modules": optional_backends["fdsn"].get("missing_modules", []),
                        "next_tools": ["browse_fdsn_datasets(trange=[...])", "fetch_fdsn_data(trange=[...], network=..., station=...)"],
                    },
                ],
                "query": query,
                "note": "Use source_type to drill into one category. Backend package names are internal details. hapi/fdsn require their optional extras.",
            })
        if source == "cdaweb":
            # Add a small source-labeled overlay for CDAWeb dataset groups that
            # are resolvable by dataset_id but absent from the upstream
            # observatory-stem catalog (issue #102: OMNI and geomagnetic indices).
            try:
                records = json.loads(browse_observatories())
            except Exception:
                records = []
            if isinstance(records, list):
                records = [*records, *_curated_cdaweb_records()]
                raw_records = _json(records)
            else:
                raw_records = browse_observatories()
            filtered_records = _filter_json_records(raw_records, query)
            try:
                filtered_payload = json.loads(filtered_records)
            except Exception:
                filtered_payload = None
            if query and filtered_payload == []:
                dataset_candidates = _cdaweb_dataset_query_candidates(raw_records, query)
                if dataset_candidates:
                    return _wrap_data_payload(
                        source,
                        _json(dataset_candidates),
                        query=query,
                        discovery_mode="dataset_query",
                        note=(
                            "No observatory row matched the full query; returned ranked "
                            "CDAWeb dataset candidates from per-observatory catalogs."
                        ),
                    )
            return _wrap_data_payload(source, filtered_records, query=query)
        if source == "pds":
            return _wrap_data_payload(source, browse_pds_missions(query=query), query=query)
        if source == "spice":
            frame_catalog = _spice_frame_catalog()
            return _wrap_data_payload(
                source,
                _filter_json_records(list_spice_missions(), query),
                query=query,
                note=(
                    "SPICE is exposed as the geometry data-source category. "
                    "The frame_catalog field lists transform_coordinates from_frame/to_frame values with descriptions."
                ),
                frame_catalog=frame_catalog,
                frame_names=frame_catalog["frame_names"],
                supported_frame_names=frame_catalog["supported_frame_names"],
            )
        if source == "hapi":
            return _json({
                "status": "success",
                "source_type": "hapi",
                "note": (
                    "HAPI catalogs are server-specific; pass a server URL to "
                    "browse_hapi_catalog. Example servers: "
                    "https://cdaweb.gsfc.nasa.gov/hapi, "
                    "https://pds-ppi.igpp.ucla.edu/hapi, "
                    "https://iswa.gsfc.nasa.gov/IswaSystemWebApp/hapi, "
                    "https://lasp.colorado.edu/lisird/hapi."
                ),
                "next_tools": [
                    "browse_hapi_catalog(server_url=..., query=...)",
                    "fetch_hapi_data(server_url=..., dataset_id=..., parameters=[...], start=..., stop=..., output_dir=...)",
                ],
                "optional_extra": "spedas-mcp[hapi]",
                "available": optional_backends["hapi"]["available"],
                "requires_extra": optional_backends["hapi"]["requires_extra"],
                "install_hint": optional_backends["hapi"]["install_hint"],
                "registration": optional_backends["hapi"]["registration"],
                "missing_modules": optional_backends["hapi"].get("missing_modules", []),
                "query": query,
            })
        if source == "fdsn":
            return _json({
                "status": "success",
                "source_type": "fdsn",
                "note": (
                    "FDSN/MTH5 station availability is time-range specific; pass a "
                    "trange to browse_fdsn_datasets to list 3-component magnetic "
                    "magnetotelluric stations from EarthScope."
                ),
                "next_tools": [
                    "browse_fdsn_datasets(trange=[...], network=..., station=..., usa_only=...)",
                    "fetch_fdsn_data(trange=[...], network=..., station=..., output_dir=...)",
                ],
                "optional_extra": "spedas-mcp[fdsn]",
                "available": optional_backends["fdsn"]["available"],
                "requires_extra": optional_backends["fdsn"]["requires_extra"],
                "install_hint": optional_backends["fdsn"]["install_hint"],
                "registration": optional_backends["fdsn"]["registration"],
                "missing_modules": optional_backends["fdsn"].get("missing_modules", []),
                "query": query,
            })
        return _unknown_source_type_error(source_type, ["all", "cdaweb", "pds", "spice", "hapi", "fdsn"])

    @mcp.tool()
    def load_data_source(
        source_type: str,
        source_id: str,
        mode: Literal["compact", "full"] = "compact",
        limit: int | None = None,
        offset: int = 0,
        instrument: str | None = None,
        dataset_query: str | None = None,
        include_full_prompt: bool = False,
    ) -> str:
        """Primary data layer: load source context for a CDAWeb observatory, PDS mission, or SPICE mission/frame.

        CDAWeb defaults to a compact, paginated structured catalog so agents can
        pick concrete ``dataset_id`` values without receiving the large legacy
        human prompt. Pass ``mode="full"`` or ``include_full_prompt=True`` to
        opt into the previous full prompt payload. Use ``limit``/``offset`` plus
        ``instrument`` or ``dataset_query`` to page/filter large observatories.
        """
        source = _normalize_source_type(source_type)
        if source == "cdaweb":
            curated = _curated_cdaweb_lookup(source_id)
            # Validate against the canonical catalog plus the curated overlay before
            # touching the backend so invalid ids return structured suggestions
            # instead of a FileNotFoundError that leaks a local cache path
            # (issues #25/#27/#102).
            valid_ids = [*_catalog_ids(browse_observatories())]
            for record in _CURATED_CDAWEB_SOURCES:
                valid_ids.extend([record["id"], *record.get("aliases", [])])
            invalid = _validate_source_id(
                "cdaweb",
                source_id,
                valid_ids,
                match=(source_id or "").strip().lower().replace("-", "_"),
                discover_tool="browse_data_sources(source_type='cdaweb')",
            )
            if invalid is not None:
                return invalid
            if curated is not None:
                datasets = list(curated.get("datasets", []))
                return _wrap_data_payload(
                    source,
                    _json(curated),
                    source_id=source_id,
                    normalized_source_id=curated["id"],
                    dataset_count=len(datasets),
                    datasets=datasets,
                    datasets_truncated=False,
                    instruments=list(curated.get("instruments", [])),
                    note=(
                        "Curated CDAWeb dataset-group overlay for products absent "
                        "from the upstream observatory catalog; dataset_ids resolve "
                        "through browse_data_parameters/fetch_data_product."
                    ),
                )
            enumeration = _enumerate_cdaweb_datasets(
                source_id,
                limit=limit,
                offset=offset,
                instrument=instrument,
                dataset_query=dataset_query,
            )
            extra: dict[str, Any] = {
                "source_id": source_id,
                "mode": "full" if mode == "full" or include_full_prompt else "compact",
            }
            if enumeration is not None:
                extra.update(enumeration)
            if mode == "full" or include_full_prompt:
                return _wrap_data_payload(source, _translate_cdaweb_facade_guidance(load_observatory(source_id)), **extra)
            if enumeration is None:
                # If direct structured enumeration is unavailable, fall back to the
                # legacy backend prompt rather than returning an empty success.
                return _wrap_data_payload(source, _translate_cdaweb_facade_guidance(load_observatory(source_id)), **extra)
            return _size_guarded(
                _json({
                    "status": "success",
                    "source_type": source,
                    **extra,
                    "payload": {
                        "source_id": source_id,
                        "catalog_mode": "compact",
                        "summary": (
                            "Compact CDAWeb dataset catalog. Use datasets[*].dataset_id with "
                            "browse_data_parameters, paginate with limit/offset, or pass "
                            "mode='full' / include_full_prompt=True for the legacy full prompt."
                        ),
                    },
                    "next_tools": [
                        "browse_data_parameters(source_type='cdaweb', dataset_id=...)",
                        "fetch_data_product(source_type='cdaweb', dataset_id=..., parameters=..., start=..., stop=..., output_dir=...)",
                    ],
                }),
                source_type=source,
            )
        if source == "pds":
            normalized_source_id = _normalize_pds_source_id(source_id)
            invalid = _validate_source_id(
                "pds",
                source_id,
                _catalog_ids(browse_pds_missions()),
                match=normalized_source_id,
                discover_tool="browse_data_sources(source_type='pds')",
                normalizer=_normalize_pds_source_id,
            )
            if invalid is not None:
                return invalid
            return _wrap_data_payload(
                source,
                _translate_facade_guidance(load_pds_mission(normalized_source_id), "pds"),
                source_id=source_id,
                normalized_source_id=normalized_source_id,
            )
        if source == "spice":
            frame_catalog = _spice_frame_catalog()
            return _wrap_data_payload(
                source,
                _json(frame_catalog["frames"]),
                source_id=source_id,
                frame_catalog=frame_catalog,
                frame_names=frame_catalog["frame_names"],
                supported_frame_names=frame_catalog["supported_frame_names"],
                note=(
                    "SPICE source loading returns the global coordinate-frame catalog; "
                    "use frame_catalog.frames for descriptions and supported_frame_names as "
                    "transform_coordinates from_frame/to_frame values. Use geometry tools "
                    "with mission/target arguments for mission-specific context."
                ),
            )
        if source == "hapi":
            return _error_response(
                "use_dedicated_tool",
                "HAPI source context is a per-server dataset catalog; load_data_source has no server_url argument.",
                hint="Call browse_hapi_catalog(server_url=...) to list datasets for a specific HAPI server.",
                sanitize=False,
                source_type="hapi",
                source_id=source_id,
                recommended_tools=["browse_hapi_catalog", "fetch_hapi_data"],
            )
        if source == "fdsn":
            return _error_response(
                "use_dedicated_tool",
                "FDSN/MTH5 station context is time-range specific; load_data_source has no trange argument.",
                hint="Call browse_fdsn_datasets(trange=[...], network=..., station=...) to list available stations.",
                sanitize=False,
                source_type="fdsn",
                source_id=source_id,
                recommended_tools=["browse_fdsn_datasets", "fetch_fdsn_data"],
            )
        return _unknown_source_type_error(source_type, ["cdaweb", "pds", "spice", "hapi", "fdsn"])

    @mcp.tool()
    def browse_data_parameters(
        source_type: str,
        dataset_id: str,
        dataset_ids: list[str] | None = None,
    ) -> str:
        """Primary data layer: browse parameters/metadata using source_type rather than source-specific tool names."""
        source = _normalize_source_type(source_type)
        if source == "cdaweb":
            return _wrap_data_payload(source, browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids), dataset_id=dataset_id)
        if source == "pds":
            return _wrap_data_payload(source, browse_pds_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids), dataset_id=dataset_id)
        if source == "spice":
            frame_catalog = _spice_frame_catalog()
            return _wrap_data_payload(
                source,
                _json(frame_catalog["frames"]),
                dataset_id=dataset_id,
                frame_catalog=frame_catalog,
                frame_names=frame_catalog["frame_names"],
                supported_frame_names=frame_catalog["supported_frame_names"],
                note=(
                    "SPICE does not expose measurement parameters; this response is the "
                    "coordinate-frame catalog. Use supported_frame_names with "
                    "transform_coordinates and use frames entries for descriptions."
                ),
            )
        if source == "hapi":
            return _error_response(
                "use_dedicated_tool",
                "HAPI parameter metadata is part of a server's dataset catalog; use browse_hapi_catalog to discover datasets, then pass parameters to fetch_hapi_data.",
                hint="Call browse_hapi_catalog(server_url=...) to list datasets; HAPI parameter names are fetched via fetch_hapi_data.",
                sanitize=False,
                source_type="hapi",
                dataset_id=dataset_id,
                recommended_tools=["browse_hapi_catalog", "fetch_hapi_data"],
            )
        if source == "fdsn":
            return _error_response(
                "use_dedicated_tool",
                "FDSN/MTH5 datasets expose fixed 3-component magnetic channels (Hx/Hy/Hz); there is no separate parameter catalog.",
                hint="Use browse_fdsn_datasets(trange=[...]) to find stations/channels, then fetch_fdsn_data.",
                sanitize=False,
                source_type="fdsn",
                dataset_id=dataset_id,
                recommended_tools=["browse_fdsn_datasets", "fetch_fdsn_data"],
            )
        return _unknown_source_type_error(source_type, ["cdaweb", "pds", "spice", "hapi", "fdsn"])

    @mcp.tool()
    def fetch_data_product(
        source_type: str,
        dataset_id: str,
        parameters: list[str],
        start: str | None = None,
        stop: str | None = None,
        output_dir: str | None = None,
        format: Literal["csv", "json"] = "csv",
        limit: int | None = None,
    ) -> str:
        """Primary data layer: fetch CDAWeb/PDS measurement or archive products; route SPICE geometry to geometry tools."""
        source = _normalize_source_type(source_type)
        if source == "cdaweb":
            if start is None or stop is None or output_dir is None:
                return _error_response(
                    "invalid_argument",
                    "cdaweb fetch requires start, stop, and output_dir",
                    hint="Provide start, stop (ISO timestamps) and an output_dir for the written product.",
                    sanitize=False,
                    source_type="cdaweb",
                )
            if limit is not None and limit <= 0:
                return _error_response(
                    "invalid_argument",
                    "CDAWeb fetch_data_product limit must be a positive integer when provided.",
                    hint="Pass limit >= 1, or omit limit and narrow start/stop/parameters instead.",
                    sanitize=False,
                    source_type="cdaweb",
                    unsupported_argument="limit",
                )
            return _wrap_data_payload(source, fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop, output_dir=output_dir, format=format, limit=limit), dataset_id=dataset_id)
        if source == "pds":
            if start is None or stop is None or output_dir is None:
                return _error_response(
                    "invalid_argument",
                    "pds fetch requires start, stop, and output_dir",
                    hint="Provide start, stop (ISO timestamps) and an output_dir for the written product.",
                    sanitize=False,
                    source_type="pds",
                )
            if limit is not None:
                return _error_response(
                    "invalid_argument",
                    "PDS fetch_data_product does not support a limit argument yet; narrow start/stop/parameters or omit limit.",
                    hint="Omit limit and narrow start/stop/parameters instead.",
                    sanitize=False,
                    source_type="pds",
                    unsupported_argument="limit",
                )
            return _wrap_data_payload(source, fetch_pds_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop, output_dir=output_dir, format=format), dataset_id=dataset_id)
        if source == "spice":
            return _error_response(
                "invalid_argument",
                "SPICE is geometry/ephemeris, not a measurement product fetch. Use get_ephemeris, compute_distance, or transform_coordinates.",
                hint="Route SPICE requests to get_ephemeris, compute_distance, or transform_coordinates.",
                sanitize=False,
                source_type="spice",
                recommended_tools=["get_ephemeris", "compute_distance", "transform_coordinates"],
            )
        if source == "hapi":
            return _error_response(
                "use_dedicated_tool",
                "HAPI fetches need a server_url, which fetch_data_product does not carry. Use fetch_hapi_data.",
                hint="Call fetch_hapi_data(server_url=..., dataset_id=..., parameters=[...], start=..., stop=..., output_dir=...).",
                sanitize=False,
                source_type="hapi",
                dataset_id=dataset_id,
                recommended_tools=["browse_hapi_catalog", "fetch_hapi_data"],
            )
        if source == "fdsn":
            return _error_response(
                "use_dedicated_tool",
                "FDSN/MTH5 fetches are addressed by trange/network/station, not dataset_id. Use fetch_fdsn_data.",
                hint="Call fetch_fdsn_data(trange=[...], network=..., station=..., output_dir=...).",
                sanitize=False,
                source_type="fdsn",
                dataset_id=dataset_id,
                recommended_tools=["browse_fdsn_datasets", "fetch_fdsn_data"],
            )
        return _unknown_source_type_error(source_type, ["cdaweb", "pds", "spice", "hapi", "fdsn"])

    @mcp.tool()
    def manage_data_cache(
        source_type: str = "all",
        action: str = "status",
        cache_dir: str | None = None,
        mission: str | None = None,
        category: str = "all",
        observatory: str | None = None,
        dataset_ids: list[str] | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
        detail: bool = False,
        force: bool = False,
        filenames: list[str] | None = None,
    ) -> str:
        """Primary data layer: manage cache status/maintenance by source_type.

        This unified cache manager covers the source-specific cache-manager
        kwargs: CDAWeb uses ``category``, ``observatory``, ``dataset_ids``,
        ``older_than_days``, ``dry_run``, and ``detail``; PDS uses
        ``category``, ``mission``, ``dataset_ids``, ``older_than_days``,
        ``dry_run``, ``detail``, and ``force``; SPICE uses ``mission`` and
        ``filenames``. Backend cache roots are still configured by the MCP
        server environment, not per call.
        """
        source = _normalize_source_type(source_type)
        cache_note = None
        if cache_dir:
            cache_note = "cache_dir is configured by the MCP server/environment; unified manage_data_cache does not override backend cache roots per call."

        cdaweb_kwargs = {
            "category": category,
            "observatory": observatory,
            "dataset_ids": dataset_ids,
            "older_than_days": older_than_days,
            "dry_run": dry_run,
            "detail": detail,
        }
        pds_kwargs = {
            "category": category,
            "mission": mission,
            "dataset_ids": dataset_ids,
            "older_than_days": older_than_days,
            "dry_run": dry_run,
            "detail": detail,
            "force": force,
        }
        spice_kwargs = {"mission": mission, "filenames": filenames}

        if source == "all":
            return _json({
                "status": "success",
                "source_type": "all",
                "caches": {
                    "cdaweb": json.loads(manage_cdaweb_cache(action=action, **cdaweb_kwargs)),
                    "pds": json.loads(manage_pds_cache(action=action, **pds_kwargs)),
                    "spice": json.loads(manage_spice_kernels(action=action, **spice_kwargs)),
                },
                "note": cache_note,
            })
        if source == "cdaweb":
            return _wrap_data_payload(source, manage_cdaweb_cache(action=action, **cdaweb_kwargs), note=cache_note)
        if source == "pds":
            return _wrap_data_payload(source, manage_pds_cache(action=action, **pds_kwargs), note=cache_note)
        if source == "spice":
            return _wrap_data_payload(source, manage_spice_kernels(action=action, **spice_kwargs), note=cache_note)
        return _unknown_source_type_error(source_type, ["all", "cdaweb", "pds", "spice"])

    if include_analysis_tools:
        # ------------------------------------------------------------------
        # Analysis layer (Phase 1: coordinate transforms). Optional pyspedas
        # backend via the spedas-mcp[analysis] extra; tools import it lazily and
        # return a clear install error when the extra is missing.
        # ------------------------------------------------------------------

        @mcp.tool()
        @_safe_tool
        def transform_timeseries_coordinates(
            input_file: str,
            coord_in: str,
            coord_out: str,
            output_file: str,
            time_col: str = "time",
            vector_cols: list[str] | None = None,
        ) -> str:
            """Analysis: transform an Nx3 vector time-series between GSE/GSM/SM/GEI/GEO/MAG/J2000.

            Reads a fetched CSV/JSON artifact, transforms with pyspedas cotrans,
            writes the transformed series to output_file, and returns paths plus
            per-component summary stats only. Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.coords import transform_timeseries_coordinates as _impl

            return _json(_impl(
                input_file=input_file,
                coord_in=coord_in,
                coord_out=coord_out,
                output_file=output_file,
                time_col=time_col,
                vector_cols=vector_cols,
            ))

        @mcp.tool()
        @_safe_tool
        def generate_fac_matrix(
            mag_file: str,
            output_file: str,
            other_dim: str = "xgse",
            pos_file: str | None = None,
            time_col: str = "time",
            vector_cols: list[str] | None = None,
            mag_coord: str = "gse",
        ) -> str:
            """Analysis: build per-sample field-aligned-coordinate (FAC) 3x3 rotation matrices.

            Backend: pyspedas fac_matrix_make. Writes the (N,3,3) matrix stack to
            output_file (.npy/.npz) and returns shape + mode + path only. Position-
            dependent modes (rgeo/mrgeo/phigeo/mphigeo/phism/mphism) require a GEI
            position series via pos_file. Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.coords import generate_fac_matrix as _impl

            return _json(_impl(
                mag_file=mag_file,
                output_file=output_file,
                other_dim=other_dim,
                pos_file=pos_file,
                time_col=time_col,
                vector_cols=vector_cols,
                mag_coord=mag_coord,
            ))

        @mcp.tool()
        @_safe_tool
        def tvector_rotate(
            vector_file: str,
            matrix_file: str,
            output_file: str,
            time_col: str = "time",
            vector_cols: list[str] | None = None,
            output_cols: list[str] | None = None,
        ) -> str:
            """Analysis: apply an (N,3,3) rotation-matrix stack to an Nx3 vector series.

            Reads a vector CSV/JSON artifact plus a saved matrix .npy/.npz artifact
            from generate_fac_matrix or sliding-window MVA, writes the rotated
            series to output_file, and returns paths plus compact summaries only.
            """
            from spedas_mcp.analysis.coords import tvector_rotate as _impl

            return _json(_impl(
                vector_file=vector_file,
                matrix_file=matrix_file,
                output_file=output_file,
                time_col=time_col,
                vector_cols=vector_cols,
                output_cols=output_cols,
            ))

        @mcp.tool()
        @_safe_tool
        def analyze_minvar_coordinates(
            input_file: str,
            output_dir: str | None = None,
            twindow: float | None = None,
            tslide: float | None = None,
            time_col: str = "time",
            vector_cols: list[str] | None = None,
            output_file: str | None = None,
        ) -> str:
            """Analysis: minimum-variance analysis (MVA) / LMN boundary-normal frame.

            Backend: pyspedas minvar / minvar_matrix_make. Full-interval mode
            (twindow=None) returns eigenvalues, eigenvectors, the normal vector, and
            the intermediate/min ratio plus a rotated-series file path. Use
            output_file for an explicit single artifact path, or output_dir for
            the default filename; output_dir remains supported for existing
            callers. Sliding-window mode writes per-window rotation matrices.
            Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.coords import analyze_minvar_coordinates as _impl

            return _json(_impl(
                input_file=input_file,
                output_dir=output_dir,
                twindow=twindow,
                tslide=tslide,
                time_col=time_col,
                vector_cols=vector_cols,
                output_file=output_file,
            ))

        # ------------------------------------------------------------------
        # Analysis layer (Phase 2: spectral & wave analysis, issue #15). Same
        # optional pyspedas backend; the wavelet tool additionally needs PyWavelets
        # (pulled in by spedas-mcp[analysis]). Both are file-in / file-out: the bulk
        # time x frequency spectrogram is written to output_dir and only paths plus
        # compact ranges/shape are returned (artifact-first).
        # ------------------------------------------------------------------

        @mcp.tool()
        @_safe_tool
        def dynamic_power_spectrum(
            input_file: str,
            output_dir: str,
            data_col: str | None = None,
            nboxpoints: int = 256,
            nshiftpoints: int = 128,
            bin: int = 3,
            nohanning: bool = False,
            time_col: str = "time",
        ) -> str:
            """Analysis: sliding-window Welch dynamic power spectrum of a scalar channel.

            Backend: pyspedas dpwrspc. Reads a fetched CSV/JSON artifact, computes a
            time x frequency power matrix over the selected data_col, writes it to
            output_dir/dynamic_power_spectrum.npz, and returns only paths plus
            time/frequency ranges and shape. Pair with a renderer to view the
            spectrogram. Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.spectral import dynamic_power_spectrum as _impl

            return _json(_impl(
                input_file=input_file,
                output_dir=output_dir,
                data_col=data_col,
                nboxpoints=nboxpoints,
                nshiftpoints=nshiftpoints,
                bin=bin,
                nohanning=nohanning,
                time_col=time_col,
            ))

        @mcp.tool()
        @_safe_tool
        def wavelet_transform(
            input_file: str,
            output_dir: str,
            data_col: str | None = None,
            wavename: str = "morl",
            min_period: float | None = None,
            max_period: float | None = None,
            compute_significance: bool = False,
            siglvl: float = 0.95,
            time_col: str = "time",
        ) -> str:
            """Analysis: continuous wavelet transform (Morlet/Paul/DOG) of a scalar channel.

            Backend: PyWavelets cwt over Torrence & Compo scales, optionally limited
            to [min_period, max_period]. With compute_significance=True, per-scale
            95% red-noise significance (pyspedas wave_signif) is saved alongside the
            power so a renderer can contour significant regions. The time x frequency
            power matrix is written to output_dir/wavelet_transform.npz; only paths
            plus frequency/period ranges and shape are returned. Significance and
            wide scale ranges are compute-heavy, so significance is opt-in. Requires
            spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.spectral import wavelet_transform as _impl

            return _json(_impl(
                input_file=input_file,
                output_dir=output_dir,
                data_col=data_col,
                wavename=wavename,
                min_period=min_period,
                max_period=max_period,
                compute_significance=compute_significance,
                siglvl=siglvl,
                time_col=time_col,
            ))

        # ------------------------------------------------------------------
        # Analysis layer (Phase 2: magnetic field models & L-shell, issues #16/#17).
        # Same optional pyspedas (geopack) backend. File-in / file-out: the input is
        # an Nx3 geocentric GSM positions artifact (preferably .npz with 'positions'
        # and optional 'times'); radii must be in the near-Earth 1..30 Re domain to
        # catch heliocentric/planet-centered vectors before backend evaluation.
        # Per-sample B vectors / footpoints / L series are written to output_file as a
        # compressed .npz and only summary stats plus paths are returned
        # (artifact-first). IGRF is cheap and parameter-free; distorted Tsyganenko
        # models require explicit parameters rather than hidden network I/O.
        # ------------------------------------------------------------------

        @mcp.tool()
        @_safe_tool
        def evaluate_magnetic_field(
            positions_file: str,
            output_file: str,
            model: str = "igrf",
            parameters: dict[str, Any] | None = None,
            trace: str = "none",
            time_col: str = "time",
            position_cols: list[str] | None = None,
        ) -> str:
            """Analysis: evaluate IGRF/T89/T96/T01/TS04 B (nT) at Nx3 GSM positions, optional tracing.

            Backend: pyspedas geopack tigrf/tt89/tt96/tt01/tts04 (field) and
            ttrace2endpoint (trace in {none, ionosphere, equator}). Reads a positions
            artifact (.npz with 'positions' Nx3 geocentric GSM km and optional
            'times'; .npy; or CSV/JSON). Radii must be within 1..30 Re; out-of-domain
            inputs return position_domain_error with a coordinate-conversion hint
            instead of backend junk. Writes per-sample B (and any footpoints/L series)
            to output_file as .npz, and returns the model, field_strength_nT
            min/max/mean, paths, and (for equator traces) an lshell_summary only.
            IGRF is fast and parameter-free; distorted models require explicit
            parameters (no hidden network I/O). Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.fieldmodels import evaluate_magnetic_field as _impl

            return _json(_impl(
                positions_file=positions_file,
                output_file=output_file,
                model=model,
                parameters=parameters,
                trace=trace,
                time_col=time_col,
                position_cols=position_cols,
            ))

        @mcp.tool()
        @_safe_tool
        def calculate_lshell(
            positions_file: str,
            output_file: str,
            model: str = "igrf",
            geomag_parameters: dict[str, Any] | None = None,
            footprint: bool = False,
            time_col: str = "time",
            position_cols: list[str] | None = None,
            parameters: dict[str, Any] | None = None,
        ) -> str:
            """Analysis: McIlwain L-shell (+ optional ionospheric footprint) for Nx3 GSM positions.

            Backend: pyspedas geopack ttrace2endpoint (trace to the magnetic equator;
            the equatorial foot radius in Re is L). Reads a positions artifact (.npz
            with 'positions' Nx3 geocentric GSM km and optional 'times'; .npy; or
            CSV/JSON). Radii must be within 1..30 Re; out-of-domain inputs return
            position_domain_error with a coordinate-conversion hint instead of
            meaningless large L values. Writes the per-sample L series (and any
            ionospheric footprint when footprint=True) to output_file as .npz, and
            returns the L summary {min_L, max_L, mean_L} plus paths only. IGRF
            (default) is fast and
            parameter-free; distorted models require geomag_parameters (no hidden
            network I/O). 'parameters' is accepted as an alias for 'geomag_parameters'
            (same name as evaluate_magnetic_field); supplying both with different
            values is an invalid_argument error. Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.fieldmodels import calculate_lshell as _impl

            return _json(_impl(
                positions_file=positions_file,
                output_file=output_file,
                model=model,
                geomag_parameters=geomag_parameters,
                footprint=footprint,
                time_col=time_col,
                position_cols=position_cols,
                parameters=parameters,
            ))

        # ------------------------------------------------------------------
        # Analysis layer (Phase 2: particle moments & spectra, issues #18/#19).
        # Same optional pyspedas backend. File-in / file-out: the input is an explicit
        # distribution artifact (.npz preferred, JSON accepted) holding per-slice
        # energy/angle cubes; moment time series and spectrogram matrices are written
        # to output_dir and only scalar summaries / paths / ranges are returned
        # (artifact-first; never inline full cubes/tensors). Each pyspedas particle
        # function is gated on exact availability before use (some builds lack e.g.
        # spd_pgs_make_pad_spec), so a missing backend yields a structured
        # unsupported/needs_input entry rather than a raw ImportError.
        # ------------------------------------------------------------------

        @mcp.tool()
        @_safe_tool
        def build_particle_distribution_artifact(
            tplot_name: str,
            output_file: str,
            converter: str = "mms_fpi",
            index: int | list[int] | None = None,
            probe: str | None = None,
            data_rate: str | None = None,
            species: str | None = None,
            level: str | None = None,
            units: str | None = None,
            trange: list[str] | None = None,
            single_time: str | None = None,
            magf: list[float] | list[list[float]] | None = None,
            max_slices: int | None = 32,
        ) -> str:
            """Analysis: bridge real pyspedas mission particle distributions into the MCP .npz schema.

            Real mission CDFs should first be loaded by the appropriate pyspedas mission
            loader into tplot variables. This tool then calls a pyspedas particle
            converter (converter keys include mms_fpi, mms_hpca, and ERG particle
            products such as erg_mepi) for the named distribution tplot variable,
            flattens each energy/angle slice into the documented distribution schema,
            writes output_file (.npz), and validates it for downstream
            compute_particle_moments / compute_particle_spectra. Supply magf as either
            [Bx,By,Bz] or one vector per output slice; the moments schema requires it.
            Returns only compact shape/range/provenance metadata plus the artifact path.
            Requires spedas-mcp[analysis] and pre-loaded tplot data; it does not itself
            download CDFs.
            """
            from spedas_mcp.analysis.particles import build_particle_distribution_artifact as _impl

            return _json(_impl(
                tplot_name=tplot_name,
                output_file=output_file,
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
                max_slices=max_slices,
            ))


        @mcp.tool()
        @_safe_tool
        def load_particle_distribution_artifact(
            output_file: str,
            converter: str = "mms_fpi",
            trange: list[str] | None = None,
            tplot_name: str | None = None,
            loader_module: str | None = None,
            loader_function: str | None = None,
            loader_kwargs: dict[str, Any] | None = None,
            index: int | list[int] | None = None,
            probe: str | None = None,
            data_rate: str | None = None,
            species: str | None = None,
            level: str | None = None,
            units: str | None = None,
            single_time: str | None = None,
            magf: list[float] | list[list[float]] | None = None,
            max_slices: int | None = 32,
        ) -> str:
            """Analysis: end-to-end pyspedas loader/CDF -> distribution artifact bridge.

            Calls a pyspedas mission loader (default mappings include MMS FPI/HPCA and
            ERG particle products, or pass loader_module/loader_function/loader_kwargs),
            selects tplot_name or a best-effort loaded distribution tplot variable, then
            writes the same validated .npz schema consumed by compute_particle_moments
            and compute_particle_spectra. Returns only compact paths/shapes/ranges and
            loader/converter provenance; CDF/tplot arrays stay on disk/in memory. Supply
            magf as [Bx,By,Bz] or one vector per slice because the downstream schema
            requires magnetic-field context. Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.particles import load_particle_distribution_artifact as _impl

            return _json(_impl(
                output_file=output_file,
                converter=converter,
                trange=trange,
                tplot_name=tplot_name,
                loader_module=loader_module,
                loader_function=loader_function,
                loader_kwargs=loader_kwargs,
                index=index,
                probe=probe,
                data_rate=data_rate,
                species=species,
                level=level,
                units=units,
                single_time=single_time,
                magf=magf,
                max_slices=max_slices,
            ))

        @mcp.tool()
        @_safe_tool
        def compute_particle_moments(
            dist_file: str,
            output_dir: str,
            sc_potential_v: float = 0.0,
            energy_range_ev: list[float] | None = None,
            output_format: str = "json",
            no_unit_conversion: bool = False,
        ) -> str:
            """Analysis: plasma moments (density/velocity/temperature/pressure) from 3D distributions.

            Backend: pyspedas moments_3d applied per time slice. Reads an explicit
            distribution artifact (.npz preferred, or JSON) with per-slice energy/angle
            cubes ('data','energy','denergy','theta','dtheta','phi','dphi','bins' plus
            scalars 'charge','mass'); a single (E,A) slice is broadcast across time.
            Optionally restricts to energy_range_ev=[min,max] eV and applies
            sc_potential_v. Writes the full moment time series to
            output_dir/particle_moments.{json,csv} and returns scalar density/velocity/
            temperature summaries plus the pressure-trace summary and path only — full
            pressure/temperature tensors and particle cubes are never returned inline.
            Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.particles import compute_particle_moments as _impl

            return _json(_impl(
                dist_file=dist_file,
                output_dir=output_dir,
                sc_potential_v=sc_potential_v,
                energy_range_ev=energy_range_ev,
                output_format=output_format,
                no_unit_conversion=no_unit_conversion,
            ))

        @mcp.tool()
        @_safe_tool
        def compute_particle_spectra(
            dist_file: str,
            output_dir: str,
            spectrum_types: list[str] | None = None,
            mag_file: str | None = None,
            resolution: int | None = None,
        ) -> str:
            """Analysis: energy / azimuth / elevation / pitch-angle spectrograms from 3D distributions.

            Backends: pyspedas spd_pgs_make_e_spec (energy), spd_pgs_make_phi_spec
            (azimuth/phi), spd_pgs_make_theta_spec (elevation/theta), each averaging the
            distribution over complementary dimensions per time slice into a
            (n_time, n_bin) spectrogram. spectrum_types defaults to
            ['energy','pitch_angle']; 'azimuth'->'phi' and 'elevation'->'theta' aliases
            are accepted. Field-aligned 'pitch_angle' spectra need a mag_file (B-field
            reference): each slice is rotated into field-aligned coordinates with
            spd_pgs_do_fac (B as +z) and the polar (pitch) angle binned over 0-180 deg
            via spd_pgs_make_theta_spec in colatitude mode (no optional pad backend
            required). Without mag_file that entry reports needs_input while the other
            requested spectra still compute. mag_file is an .npz/.json with 'b' as
            (T,3) (one B vector per slice) or (3,) (broadcast), in the distribution's
            coordinate frame. Each spectrogram is written to
            output_dir/particle_spectra_<type>.npz; only paths/ranges/shapes are
            returned (artifact-first). Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.particles import compute_particle_spectra as _impl

            return _json(_impl(
                dist_file=dist_file,
                output_dir=output_dir,
                spectrum_types=spectrum_types,
                mag_file=mag_file,
                resolution=resolution,
            ))

        # ------------------------------------------------------------------
        # Analysis layer (Phase 2: artifact rendering / visualization, issue #20,
        # plotting epic #10). Optional matplotlib backend (installed via the same
        # spedas-mcp[analysis] extra). File-in / file-out: inputs are paths to the
        # spectral/particle/data artifacts above, the output is a PNG written to
        # output_file, and only the path plus compact per-panel metadata is returned
        # — never inline image bytes (artifact-first). Rendering is headless (Agg)
        # and never fetches remote data.
        # ------------------------------------------------------------------

        @mcp.tool()
        @_safe_tool
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
        ) -> str:
            """Analysis: render a multi-panel tplot-style PNG from analysis artifacts.

            Backend: matplotlib (headless Agg). Consumes the file artifacts written
            by the data/spectral/particle tools — spectrogram .npz matrices (keys
            'power'/'spectrogram' with 'time' + 'freq'/'axis' axes) and CSV/JSON or
            .npz/.npy time-series — and stacks one panel per input_file (top to
            bottom). Spectrogram artifacts render as pcolormesh panels with a
            colorbar; time-series render as line panels; explicit 'scatter'/'xy'
            panels render one 2-D matrix per input as a parametric x-y/hodogram plot
            using x_component/y_component column indices (default 0 vs 1).
            panel_types overrides the per-file auto-detection (each of 'auto',
            'line'/'timeseries', 'spectrogram', or 'scatter'/'xy'); it may be None
            (all auto), a single token (broadcast), or a list matching input_files.
            trange (2-element ISO-8601 or Unix-second
            bounds) filters samples; ylog/zlog (per-panel booleans or a scalar
            broadcast) set log y / log color scales and are rejected when values are
            non-positive. xsize/ysize are inches; dpi is bounded to avoid absurd
            canvases. The PNG is written to output_file (parent dirs created) and
            only {status, output_file, n_panels, trange, size_px, panels[...]} is
            returned — image bytes are never inlined. Does not fetch remote data.
            Requires spedas-mcp[analysis].
            """
            from spedas_mcp.analysis.plotting import render_tplot as _impl

            return _json(_impl(
                input_files=input_files,
                output_file=output_file,
                panel_types=panel_types,
                trange=trange,
                xsize=xsize,
                ysize=ysize,
                dpi=dpi,
                ylog=ylog,
                zlog=zlog,
                x_component=x_component,
                y_component=y_component,
            ))

        # ------------------------------------------------------------------
        # External data-source layer (issues #21, #22). Optional backends reached
        # via the spedas-mcp[hapi] / spedas-mcp[fdsn] extras; tools import them
        # lazily and return a structured missing_dependency error (with the extra to
        # install) when absent, so base install and MCP list-tools work without them.
        # Artifact-first: bulk time-series are written to output_dir and only paths +
        # compact metadata are returned. source_type="hapi"/"fdsn" are recognized by
        # the unified data layer, which routes here.
        # ------------------------------------------------------------------

    @mcp.tool()
    @_safe_tool
    def browse_hapi_catalog(server_url: str, query: str | None = None, max_results: int | None = 500) -> str:
        """Data layer (HAPI): list datasets advertised by any HAPI-compliant server.

        Backend: hapiclient (optional spedas-mcp[hapi] extra). Works against
        CDAWeb, PDS-PPI, ISWA, LISIRD, and university HAPI servers. Pass the HAPI
        base URL (ends in /hapi), e.g. 'https://cdaweb.gsfc.nasa.gov/hapi';
        optionally filter ids/titles with query. ``max_results`` defaults to 500
        so unfiltered large catalogs stay response-size safe. Returns
        {status, server, dataset_count, total_dataset_count, datasets_truncated,
        title_count, datasets}. ``title`` is present only when the server
        provides it. Returns a missing_dependency error (install
        spedas-mcp[hapi]) when hapiclient is absent — base install and list_tools
        still work without it.
        """
        from spedas_mcp.datasources.hapi import browse_hapi_catalog as _impl

        return _json(_impl(server_url=server_url, query=query, max_results=max_results))

    @mcp.tool()
    @_safe_tool
    def fetch_hapi_data(
        server_url: str,
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
    ) -> str:
        """Data layer (HAPI): fetch a HAPI dataset slice to a file (artifact-first).

        Backend: hapiclient (optional spedas-mcp[hapi] extra). Loads the named
        parameters from dataset_id on server_url over [start, stop) (stop is
        exclusive per the HAPI spec), writes a flat CSV/JSON table (time column
        plus one column per scalar parameter and name[i] columns for vector/
        spectral parameters) to output_dir, and returns only
        {status, file_path, format, server, dataset_id, time_range, rows,
        parameters_meta} — never inline arrays. parameters_meta carries per-
        parameter units/description/type/size/spectral flags. Discover dataset_id
        with browse_hapi_catalog. Returns a missing_dependency error (install
        spedas-mcp[hapi]) when hapiclient is absent.
        """
        from spedas_mcp.datasources.hapi import fetch_hapi_data as _impl

        return _json(_impl(
            server_url=server_url,
            dataset_id=dataset_id,
            parameters=parameters,
            start=start,
            stop=stop,
            output_dir=output_dir,
            format=format,
        ))

    @mcp.tool()
    @_safe_tool
    def browse_fdsn_datasets(
        trange: list[str],
        network: str | None = None,
        station: str | None = None,
        usa_only: bool = False,
    ) -> str:
        """Data layer (FDSN/MTH5): list magnetotelluric magnetic stations in a time range.

        Backend: pyspedas.mth5 (optional spedas-mcp[fdsn] extra; wraps mth5 +
        obspy). Queries EarthScope FDSN for stations that expose three same-band
        magnetic channels (e.g. LFE/LFN/LFZ) within trange=['YYYY-MM-DD',
        'YYYY-MM-DD']; optional network/station code filters and usa_only restrict
        the search. Returns {status, trange, station_count, stations: [{network,
        station, time_range, channels}...]}. Returns a missing_dependency error
        (install spedas-mcp[fdsn]) when mth5/obspy are absent.
        """
        from spedas_mcp.datasources.fdsn import browse_fdsn_datasets as _impl

        return _json(_impl(
            trange=trange,
            network=network,
            station=station,
            usa_only=usa_only,
        ))

    @mcp.tool()
    @_safe_tool
    def fetch_fdsn_data(
        trange: list[str],
        network: str,
        station: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
    ) -> str:
        """Data layer (FDSN/MTH5): fetch a calibrated 3-component MT magnetic series to a file.

        Backend: pyspedas.mth5 load_fdsn (optional spedas-mcp[fdsn] extra). Downloads
        an MTH5 file from EarthScope for network/station over trange, calibrates
        counts -> nT, enforces 3-component Hx/Hy/Hz geometry, writes the time-series
        (time column plus one column per channel) to output_dir as CSV/JSON, and
        returns only {status, file_path, format, network, station, trange, rows,
        channels, units?} — never inline arrays or the raw MTH5 payload. Discover
        network/station with browse_fdsn_datasets. Returns resource_not_found when
        no qualifying 3-component data exist in the window, or a missing_dependency
        error (install spedas-mcp[fdsn]) when mth5/obspy are absent.
        """
        from spedas_mcp.datasources.fdsn import fetch_fdsn_data as _impl

        return _json(_impl(
            trange=trange,
            network=network,
            station=station,
            output_dir=output_dir,
            format=format,
        ))

    _install_argument_validation_guard(mcp)
    return mcp


def _install_argument_validation_guard(mcp: FastMCP) -> None:
    """Route FastMCP argument-validation failures through the structured contract.

    ``_safe_tool`` only wraps a tool's *body*, but FastMCP validates arguments
    against a generated pydantic model and raises *before* the body runs, so a
    bad/missing/misnamed argument escapes as a raw ``ToolError`` carrying the
    pydantic text and an ``errors.pydantic.dev`` URL (issue #57). We wrap the
    server's ``call_tool`` entry point: when the failure is an argument
    ``ValidationError`` we return the same ``{status:"error", code, message, hint}``
    envelope every other error uses (sanitized, naming the offending argument and
    pointing at the tool's documented parameters). Non-validation errors are left
    untouched — the tool body already converts those via ``_safe_tool``.
    """
    import functools

    from mcp.server.fastmcp.utilities.func_metadata import _convert_to_content

    original_call_tool = mcp.call_tool

    def _convert_like_tool(name: str, envelope: str) -> Any:
        """Convert an error string to the same content shape the named tool emits.

        Tools annotated ``-> str`` get an inferred output schema, so a successful
        return is converted to a ``(content, structured)`` tuple; reusing the tool's
        own ``convert_result`` keeps our injected error response shape-identical to a
        normal response (so clients and the test helper unpack it the same way).
        """
        tool = mcp._tool_manager.get_tool(name)
        if tool is not None:
            try:
                return tool.fn_metadata.convert_result(envelope)
            except Exception:  # pragma: no cover - fall back to bare content
                pass
        return _convert_to_content(envelope)

    @functools.wraps(original_call_tool)
    async def call_tool(name: str, arguments: dict[str, Any]) -> Any:
        try:
            return await original_call_tool(name, arguments)
        except Exception as exc:  # noqa: BLE001 - convert arg-validation to envelope
            validation = _find_validation_error(exc)
            if validation is None:
                raise
            logger.warning("Tool %s argument validation failed: %s", name, validation)
            envelope = _error_response(
                "invalid_arguments",
                _summarize_pydantic_validation(validation),
                hint=(
                    "Check the argument names/types against the tool's documented "
                    "parameters; analysis tools that emit a single artifact take "
                    "output_file (analyze_minvar_coordinates also accepts output_dir "
                    "for backward compatibility), those that emit multiple files take output_dir."
                ),
                sanitize=False,  # already sanitized by _summarize_pydantic_validation
                tool=name,
            )
            return _convert_like_tool(name, envelope)

    mcp.call_tool = call_tool  # type: ignore[method-assign]


def serve() -> None:
    """Run the MCP server over stdio transport."""
    parser = argparse.ArgumentParser(description="Unified SPEDAS MCP server")
    parser.add_argument("--cdaweb-cache-dir", default=None, help="Override CDAWeb cache root directory")
    parser.add_argument("--spice-kernel-dir", default=None, help="Override SPICE kernel cache directory")
    parser.add_argument("--pds-cache-dir", default=None, help="Override PDS PPI cache root directory")
    args = parser.parse_args()

    import os

    cdaweb_cache_dir = args.cdaweb_cache_dir or os.environ.get("XHELIO_CDAWEB_CACHE_DIR")
    if cdaweb_cache_dir:
        from spedas_mcp.backends.cdaweb import configure
        configure(cache_dir=cdaweb_cache_dir)

    spice_kernel_dir = args.spice_kernel_dir or os.environ.get("XHELIO_SPICE_KERNEL_DIR")
    if spice_kernel_dir:
        os.environ["XHELIO_SPICE_KERNEL_DIR"] = spice_kernel_dir

    pds_cache_dir = args.pds_cache_dir or os.environ.get("PDSMCP_CACHE_DIR")
    if pds_cache_dir:
        from spedas_mcp.backends.pds.config import configure as configure_pds
        configure_pds(cache_dir=pds_cache_dir)

    logging.basicConfig(level=logging.INFO)
    create_server().run()
