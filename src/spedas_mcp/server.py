"""Unified SPEDAS-oriented MCP server.

The server follows Jason's updated A+B direction:

A. Present one SPEDAS data layer organized by data source categories.
B. Add a SPEDAS science-workflow layer so agents can plan a study before using
   source-specific data and geometry operations.

The focused XHelio packages remain internal backends, not the user-facing mental
model. Outward-facing tools should speak in terms of SPEDAS data sources such as
CDAWeb, PDS, and SPICE/geometry.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised by entrypoint guard
    raise ImportError("Install MCP support with: pip install 'spedas-mcp[mcp]'") from exc

logger = logging.getLogger(__name__)


def _json(data: object) -> str:
    return json.dumps(data, indent=2, default=str)


# Maximum serialized size (bytes) for a single MCP tool response. MCP stdio is
# line-delimited JSON and asyncio's StreamReader defaults to a 64KB line buffer
# (65536 bytes); a single response over that limit raises LimitOverrunError and
# crashes conformant clients (issue #28). We keep a margin below 64KB so the
# transport's own framing/escaping never pushes a "safe" payload over the edge.
_MAX_RESPONSE_BYTES = 60000

# Matches absolute filesystem paths so they can be stripped from user-facing
# error text. Backends such as xhelio-cdaweb / pdsmcp raise FileNotFoundError
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
    "Check body/frame names against list_spice_missions and "
    "list_coordinate_frames; not every body has loaded kernels."
)

# Substrings that mark a ``KeyError`` as a geometry lookup failure (unresolvable
# body/frame/mission/kernel) raised by xhelio_spice, rather than a generic dict
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
    # A geometry ``KeyError`` (e.g. xhelio_spice "Cannot resolve body name 'X'")
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


# ---------------------------------------------------------------------------
# Geometry/SPICE safety preflight (issues #26, #27, #29).
#
# The xhelio_spice geometry routines (get_state/get_trajectory/transform_vector)
# resolve body names and *download* SPICE kernels on first use — generic kernels
# (~120 MB, e.g. de440s.bsp) plus per-mission SPK files (PSP ~266 MB, up to
# ~1 GB for some segmented missions). Two problems follow:
#   * #26: an unsupported target (e.g. "MMS1", which is a CDAWeb mission with no
#     SPICE kernels) bubbles up an opaque "Cannot resolve body name" error after
#     touching the backend, with no recovery path.
#   * #29: a supported-but-uncached target silently triggers a large download
#     with no warning or confirmation, bypassing the explicit
#     manage_spice_kernels(action='load') gate.
#
# Both are solved by a pure, network-free preflight that runs entirely in this
# process *before* any xhelio_spice call: resolve_mission() is an in-memory
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
    from xhelio_spice.missions import has_kernels, resolve_mission

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
    the stdio size limit; the agent is pointed at ``list_spice_missions`` for the
    full catalog.
    """
    try:
        from xhelio_spice import list_supported_missions
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
        "Use list_spice_missions to see supported targets. "
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


def _spice_missing_kernels(mission_keys: list[str]) -> dict[str, Any]:
    """Report which required kernel files are not yet cached (issue #29).

    Pure disk inspection — never downloads. Returns::

        {
          "cached": True/False,           # all required files present?
          "missing_files": [...],         # filenames not on disk
          "missing_missions": [...],      # mission keys needing a download
          "segmented_missions": [...],    # need a time range via manage_spice_kernels
          "cache_dir": "<redacted>",      # cache root (path-redacted for clients)
          "cache_size_mb": 12.3,
        }

    Generic kernels are always required (every geometry call furnishes them), so
    they are folded into the check. A file counts as cached only if it exists on
    disk with non-zero size — the same test the downloader uses.
    """
    from xhelio_spice.kernel_manager import get_kernel_manager
    from xhelio_spice.missions import (
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
        f"manage_spice_kernels(action='load', mission='{m}')" for m in load_missions
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
            "Load the missions explicitly with manage_spice_kernels(action='load', "
            "mission=...), or pass allow_kernel_download=True to this tool to "
            "download now. Use manage_spice_kernels(action='check_remote', "
            "mission=...) to preview available kernel files first."
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
    spacecraft this call will pass to xhelio_spice; ``role`` (e.g. "target",
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


def create_server() -> FastMCP:
    """Create and configure the unified SPEDAS MCP server."""
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
                    "list_spice_missions",
                    "get_ephemeris",
                    "compute_distance",
                    "transform_coordinates",
                    "list_coordinate_frames",
                ],
                "analysis": {
                    "status": "optional pyspedas backend; install with spedas-mcp[analysis]",
                    "tools": [
                        "transform_timeseries_coordinates",
                        "generate_fac_matrix",
                        "analyze_minvar_coordinates",
                    ],
                },
                "compatibility_low_level": {
                    "status": "supported compatibility surface; not the preferred starting point",
                    "prefer": [
                        "browse_data_sources",
                        "load_data_source",
                        "browse_data_parameters",
                        "fetch_data_product",
                        "manage_data_cache",
                    ],
                    "available_for_existing_clients": [
                        "browse_observatories",
                        "load_observatory",
                        "browse_parameters",
                        "fetch_data",
                        "browse_pds_missions",
                        "load_pds_mission",
                        "browse_pds_parameters",
                        "fetch_pds_data",
                        "manage_cdaweb_cache",
                        "manage_pds_cache",
                        "manage_spice_kernels",
                    ],
                },
            },
            "workflow": [
                "Start with search_spedas_data_sources or plan_spedas_observation for open-ended science requests.",
                "Use browse_data_sources(source_type='all') to inspect SPEDAS data-source categories.",
                "Use load_data_source, browse_data_parameters, fetch_data_product, and manage_data_cache for the unified data layer.",
                "load_data_source(source_type='cdaweb', ...) enumerates dataset_ids so you can call browse_data_parameters without guessing; pass the science goal to search_spedas_data_sources via question= (query= is accepted as an alias).",
                "Treat source-specific CDAWeb/PDS cache/fetch/browse tools as compatibility tools for existing clients; do not choose them first for new agent workflows.",
                "Use geometry tools directly when the request is SPICE-specific ephemeris, frame, distance, or transform work.",
                "Use create_spedas_analysis_bundle to preserve request/provenance intent before bulk fetches.",
                "For bulk data, always provide output_dir/output_file and return paths only.",
            ],
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

    @mcp.tool()
    def browse_observatories() -> str:
        """Compatibility: list CDAWeb observatories. Prefer browse_data_sources(source_type="cdaweb") for new workflows."""
        from cdawebmcp.catalog import browse_observatories as _browse_observatories

        return _json(_browse_observatories())

    @mcp.tool()
    @_safe_tool
    def load_observatory(observatory_id: str) -> str:
        """Compatibility: load CDAWeb observatory context. Prefer load_data_source(source_type="cdaweb", source_id=...)."""
        from cdawebmcp.prompts import build_observatory_prompt

        return build_observatory_prompt(observatory_id)

    @mcp.tool()
    def browse_parameters(dataset_id: str, dataset_ids: list[str] | None = None) -> str:
        """Compatibility: browse CDAWeb variables. Prefer browse_data_parameters(source_type="cdaweb", ...)."""
        from cdawebmcp.metadata import browse_parameters as _browse_parameters

        return _json(_browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids))

    @mcp.tool()
    @_safe_tool
    def fetch_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
    ) -> str:
        """Compatibility: fetch CDAWeb time-series data. Prefer fetch_data_product(source_type="cdaweb", ...)."""
        import pandas as pd
        from cdawebmcp.fetch import fetch_data as _fetch_data

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
            return _json({"status": "error", "message": "No data fetched", "parameters": param_meta})
        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.join(frame, how="outer")
        base_name = f"{dataset_id}_{start_short}_{stop_short}"
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
        return _json({
            "status": "success",
            "file_path": str(file_path),
            "format": format,
            "dataset_id": dataset_id,
            "time_range": {"start": start, "stop": stop},
            "total_rows": len(merged),
            "parameters": param_meta,
        })

    @mcp.tool()
    def browse_pds_missions(query: str | None = None) -> str:
        """Compatibility: list PDS PPI missions. Prefer browse_data_sources(source_type="pds") for new workflows."""
        from pdsmcp.catalog import browse_missions as _browse_missions

        return _json(_browse_missions(query=query))

    @mcp.tool()
    @_safe_tool
    def load_pds_mission(mission_id: str) -> str:
        """Compatibility: load PDS mission context. Prefer load_data_source(source_type="pds", source_id=...)."""
        from pdsmcp.prompts import build_mission_prompt

        return build_mission_prompt(mission_id)

    @mcp.tool()
    def browse_pds_parameters(dataset_id: str | None = None, dataset_ids: list[str] | None = None) -> str:
        """Compatibility: browse PDS variables. Prefer browse_data_parameters(source_type="pds", ...)."""
        from pdsmcp.metadata import browse_parameters as _browse_parameters

        return _json(_browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids))

    @mcp.tool()
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
        from pdsmcp.fetch import fetch_data as _fetch_data

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
            return _json({"status": "error", "message": "No data fetched", "parameters": param_meta})
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
        return _json({
            "status": "success",
            "file_path": str(file_path),
            "format": format,
            "dataset_id": dataset_id,
            "time_range": {"start": start, "stop": stop},
            "total_rows": len(merged),
            "parameters": param_meta,
        })

    @mcp.tool()
    @_safe_tool
    def list_spice_missions() -> str:
        """List supported SPICE spacecraft/body missions with NAIF IDs and kernel status."""
        from xhelio_spice import list_supported_missions

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
        with ``manage_spice_kernels(action='load', mission=...)``) to proceed
        (issue #29).
        """
        from xhelio_spice import get_state, get_trajectory
        from xhelio_spice.kernel_manager import get_kernel_manager

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
        from xhelio_spice import get_trajectory

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
        from xhelio_spice import transform_vector

        # Only ``spacecraft`` is a body name; from_frame/to_frame are frames and
        # are validated by the backend. Generic kernels are required regardless,
        # so the cache gate runs even when no spacecraft is given.
        preflight = _spice_geometry_preflight(
            [(spacecraft, "spacecraft")] if spacecraft else [],
            tool="transform_coordinates",
            allow_kernel_download=allow_kernel_download,
        )
        if preflight is not None:
            return preflight

        result = transform_vector(vector, time, from_frame=from_frame, to_frame=to_frame, spacecraft=spacecraft)
        return _json({
            "status": "success",
            "input_vector": vector,
            "output_vector": result,
            "from_frame": from_frame,
            "to_frame": to_frame,
            "time": time,
            "spacecraft": spacecraft,
        })

    @mcp.tool()
    @_safe_tool
    def list_coordinate_frames() -> str:
        """List supported SPICE coordinate frames and usage notes."""
        from xhelio_spice import list_frames_with_descriptions

        return _json(list_frames_with_descriptions())

    @mcp.tool()
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
        from cdawebmcp.cache import cache_clean, cache_status, rebuild_catalog, refresh_metadata, refresh_time_ranges

        if action == "status":
            return _json(cache_status(detail=detail))
        if action == "clean":
            return _json(cache_clean(category=category, observatory=observatory, older_than_days=older_than_days, dry_run=dry_run))
        if action == "refresh_metadata":
            return _json(refresh_metadata(dataset_ids=dataset_ids, observatory=observatory))
        if action == "refresh_time_ranges":
            return _json(refresh_time_ranges(observatory=observatory))
        if action == "rebuild_catalog":
            return _json(rebuild_catalog(observatory=observatory))
        return _json({"status": "error", "message": f"Unknown action: {action}"})

    @mcp.tool()
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
        from pdsmcp.cache import build_metadata, cache_clean, cache_status, refresh_metadata, refresh_time_ranges, rebuild_catalog

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

    @mcp.tool()
    def manage_spice_kernels(
        action: Literal["status", "load", "clean", "check_remote", "purge"],
        mission: str | None = None,
        filenames: list[str] | None = None,
    ) -> str:
        """Manage SPICE kernels/cache; use manage_data_cache(source_type="spice") for data-layer cache status."""
        from xhelio_spice.kernel_manager import check_remote_kernels, get_kernel_manager

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

    def _wrap_data_payload(source_type: str, raw: str, **extra: Any) -> str:
        try:
            payload = json.loads(raw)
        except Exception:
            # A non-JSON backend string is almost always a raw error/traceback
            # (e.g. a FileNotFoundError carrying a local cache path). Sanitize it
            # instead of forwarding raw filesystem paths to the client
            # (issues #25/#27).
            payload = _sanitize_message(raw)
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

    # Byte budget for the structured dataset catalog added to a load_data_source
    # response. The observatory prompt payload itself is ~38KB for large
    # observatories (e.g. MMS); capping the structured list keeps the total
    # response within the MCP stdio response-size safety expectation (<64KB).
    _DATASET_ENUM_BYTE_BUDGET = 16000

    def _enumerate_cdaweb_datasets(source_id: str) -> dict[str, Any] | None:
        """Return a compact, JSON-serializable dataset catalog for a CDAWeb observatory.

        Reads the observatory JSON directly so agents can move from
        ``load_data_source`` to ``browse_data_parameters`` without guessing
        dataset IDs (issue #31). Entries carry the dataset id, instrument key,
        and coverage dates — enough to plan a fetch — while human-readable
        descriptions remain in the prompt payload. The list is bounded by the
        actual serialized size of the structured enumeration payload and reports
        ``datasets_truncated``/``dataset_count`` so very large observatories stay
        size-safe without hiding the true total.

        Returns ``None`` if enumeration is unavailable so the existing
        observatory prompt payload is preserved unchanged.
        """
        try:
            from cdawebmcp.catalog import load_observatory_json
        except Exception:  # pragma: no cover - backend not installed
            return None
        stem = (source_id or "").strip().lower().replace("-", "_")
        try:
            observatory = load_observatory_json(stem)
        except Exception:
            # Unknown/invalid observatory stem: leave discovery to the prompt payload.
            return None

        instruments = observatory.get("instruments", {})
        if not isinstance(instruments, dict):
            return None

        all_entries: list[dict[str, Any]] = []
        for inst_key, inst_data in sorted(instruments.items()):
            if not isinstance(inst_data, dict):
                continue
            for ds_id, ds_info in sorted(inst_data.get("datasets", {}).items()):
                ds_info = ds_info if isinstance(ds_info, dict) else {}
                all_entries.append({
                    "dataset_id": ds_id,
                    "instrument": inst_key,
                    "start_date": ds_info.get("start_date"),
                    "stop_date": ds_info.get("stop_date"),
                })

        total = len(all_entries)
        instrument_names = sorted(instruments.keys())

        def _dataset_note(shown: int) -> str:
            return (
                f"Showing {shown} of {total} datasets to stay within the "
                "response-size limit. Use browse_data_sources(source_type='cdaweb', "
                "query=...) to filter, or the compatibility load_observatory tool for "
                "the full per-instrument catalog."
            )

        def _dataset_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
            truncated = len(entries) < total
            payload: dict[str, Any] = {
                "dataset_count": total,
                "datasets": entries,
                "datasets_truncated": truncated,
                "instruments": instrument_names,
            }
            if truncated:
                payload["datasets_note"] = _dataset_note(len(entries))
            return payload

        def _serialized_dataset_bytes(entries: list[dict[str, Any]]) -> int:
            return len(json.dumps(_dataset_payload(entries), default=str, indent=2).encode("utf-8"))

        datasets: list[dict[str, Any]] = []
        for entry in all_entries:
            candidate = [*datasets, entry]
            if _serialized_dataset_bytes(candidate) > _DATASET_ENUM_BYTE_BUDGET and datasets:
                break
            datasets.append(entry)

        return _dataset_payload(datasets)

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
                ],
                "query": query,
                "note": "Use source_type to drill into one category. XHelio package names are internal backend details.",
            })
        if source == "cdaweb":
            return _wrap_data_payload(source, _filter_json_records(browse_observatories(), query), query=query)
        if source == "pds":
            return _wrap_data_payload(source, browse_pds_missions(query=query), query=query)
        if source == "spice":
            return _wrap_data_payload(source, _filter_json_records(list_spice_missions(), query), query=query, note="SPICE is exposed as the geometry data-source category.")
        return _unknown_source_type_error(source_type, ["all", "cdaweb", "pds", "spice"])

    @mcp.tool()
    def load_data_source(source_type: str, source_id: str) -> str:
        """Primary data layer: load source context for a CDAWeb observatory, PDS mission, or SPICE mission/frame.

        For CDAWeb observatories the response also includes an enumerated
        ``datasets`` list (``dataset_id``, ``instrument``, coverage dates) plus
        ``dataset_count``/``datasets_truncated``, so agents can pass a concrete
        ``dataset_id`` straight to ``browse_data_parameters`` without guessing.
        """
        source = _normalize_source_type(source_type)
        if source == "cdaweb":
            # Validate against the canonical catalog before touching the backend
            # so an invalid id (e.g. "MMS1") returns a structured suggestion
            # instead of a FileNotFoundError that leaks a local cache path
            # (issues #25/#27).
            invalid = _validate_source_id(
                "cdaweb",
                source_id,
                _catalog_ids(browse_observatories()),
                match=(source_id or "").strip().lower().replace("-", "_"),
                discover_tool="browse_data_sources(source_type='cdaweb')",
            )
            if invalid is not None:
                return invalid
            enumeration = _enumerate_cdaweb_datasets(source_id)
            extra: dict[str, Any] = {"source_id": source_id}
            if enumeration is not None:
                # Additive discovery fields (issue #31): agents can read dataset_ids
                # here and pass them straight to browse_data_parameters.
                extra.update(enumeration)
            return _wrap_data_payload(source, load_observatory(source_id), **extra)
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
                load_pds_mission(normalized_source_id),
                source_id=source_id,
                normalized_source_id=normalized_source_id,
            )
        if source == "spice":
            return _wrap_data_payload(
                source,
                list_coordinate_frames(),
                source_id=source_id,
                note="SPICE source loading returns the global coordinate-frame catalog; use geometry tools with mission/target arguments for mission-specific context.",
            )
        return _unknown_source_type_error(source_type, ["cdaweb", "pds", "spice"])

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
            return _wrap_data_payload(
                source,
                list_coordinate_frames(),
                dataset_id=dataset_id,
                note="SPICE does not expose measurement parameters; use frames/targets/observer geometry instead.",
            )
        return _unknown_source_type_error(source_type, ["cdaweb", "pds", "spice"])

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
            return _wrap_data_payload(source, fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop, output_dir=output_dir, format=format), dataset_id=dataset_id)
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
        return _unknown_source_type_error(source_type, ["cdaweb", "pds", "spice"])

    @mcp.tool()
    def manage_data_cache(
        source_type: str = "all",
        action: Literal["status", "clean"] = "status",
        cache_dir: str | None = None,
        mission: str | None = None,
    ) -> str:
        """Primary data layer: manage cache status/maintenance by source_type."""
        source = _normalize_source_type(source_type)
        cache_note = None
        if cache_dir:
            cache_note = "cache_dir is configured by the MCP server/environment; unified manage_data_cache does not override backend cache roots per call."
        if source == "all":
            return _json({
                "status": "success",
                "source_type": "all",
                "caches": {
                    "cdaweb": json.loads(manage_cdaweb_cache(action=action)),
                    "pds": json.loads(manage_pds_cache(action=action, mission=mission)),
                    "spice": json.loads(manage_spice_kernels(action=action, mission=mission)),
                },
                "note": cache_note,
            })
        if source == "cdaweb":
            return _wrap_data_payload(source, manage_cdaweb_cache(action=action), note=cache_note)
        if source == "pds":
            return _wrap_data_payload(source, manage_pds_cache(action=action, mission=mission), note=cache_note)
        if source == "spice":
            return _wrap_data_payload(source, manage_spice_kernels(action=action, mission=mission), note=cache_note)
        return _unknown_source_type_error(source_type, ["all", "cdaweb", "pds", "spice"])

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
    def analyze_minvar_coordinates(
        input_file: str,
        output_dir: str,
        twindow: float | None = None,
        tslide: float | None = None,
        time_col: str = "time",
        vector_cols: list[str] | None = None,
    ) -> str:
        """Analysis: minimum-variance analysis (MVA) / LMN boundary-normal frame.

        Backend: pyspedas minvar / minvar_matrix_make. Full-interval mode
        (twindow=None) returns eigenvalues, eigenvectors, the normal vector, and
        the intermediate/min ratio plus a rotated-series file path. Sliding-window
        mode writes per-window rotation matrices. Requires spedas-mcp[analysis].
        """
        from spedas_mcp.analysis.coords import analyze_minvar_coordinates as _impl

        return _json(_impl(
            input_file=input_file,
            output_dir=output_dir,
            twindow=twindow,
            tslide=tslide,
            time_col=time_col,
            vector_cols=vector_cols,
        ))

    return mcp


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
        from cdawebmcp import configure
        configure(cache_dir=cdaweb_cache_dir)

    spice_kernel_dir = args.spice_kernel_dir or os.environ.get("XHELIO_SPICE_KERNEL_DIR")
    if spice_kernel_dir:
        os.environ["XHELIO_SPICE_KERNEL_DIR"] = spice_kernel_dir

    pds_cache_dir = args.pds_cache_dir or os.environ.get("PDSMCP_CACHE_DIR")
    if pds_cache_dir:
        from pdsmcp.config import configure as configure_pds
        configure_pds(cache_dir=pds_cache_dir)

    logging.basicConfig(level=logging.INFO)
    create_server().run()
