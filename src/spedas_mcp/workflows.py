"""SPEDAS-level workflow helpers for the unified MCP facade.

The low-level tool groups expose CDAWeb, PDS, and SPICE directly.  This module
adds a small SPEDAS semantic layer: choose the right source family, plan a
science observation workflow, compare the source families, and scaffold an
analysis bundle that records request/provenance intent before data fetches.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SOURCE_PROFILES: dict[str, dict[str, Any]] = {
    "cdaweb": {
        "label": "CDAWeb heliophysics time-series",
        "best_for": [
            "Near-Earth and heliophysics observatory time-series",
            "plasma, fields, particles, indices, and solar-wind context",
            "Fast browse-then-fetch workflows for CDF-like time intervals",
        ],
        "not_for": ["spacecraft/body geometry by itself", "PDS-only planetary archive products"],
        "discovery_tools": ["browse_data_sources(source_type=\"cdaweb\")", "load_data_source(source_type=\"cdaweb\", source_id=...)", "browse_data_parameters(source_type=\"cdaweb\", dataset_id=...)"],
        "fetch_tools": ["fetch_data_product(source_type=\"cdaweb\", ...)"],
        "cache_tools": ["manage_data_cache(source_type=\"cdaweb\")"],
        "keywords": [
            "cdaweb", "omni", "mms", "themis", "cluster", "wind", "ace", "dscovr",
            "geotail", "psp", "solo", "heliophysics", "magnetosphere", "ionosphere",
            "solar wind", "timeseries", "time-series", "plasma", "magnetic", "electric",
            "particle", "cdf", "observatory", "near earth", "near-earth",
        ],
    },
    "pds": {
        "label": "PDS Planetary Plasma Interactions archive",
        "best_for": [
            "Planetary mission archive products and bundle/dataset discovery",
            "Jupiter/Saturn/planetary plasma investigations from PDS PPI",
            "Parameter metadata and file-backed fetches for archived products",
        ],
        "not_for": ["generic near-Earth CDAWeb observatories", "pure geometry without archived data"],
        "discovery_tools": ["browse_data_sources(source_type=\"pds\")", "load_data_source(source_type=\"pds\", source_id=...)", "browse_data_parameters(source_type=\"pds\", dataset_id=...)"],
        "fetch_tools": ["fetch_data_product(source_type=\"pds\", ...)"],
        "cache_tools": ["manage_data_cache(source_type=\"pds\")"],
        "keywords": [
            "pds", "ppi", "planetary", "jupiter", "saturn", "mars", "venus", "mercury",
            "uranus", "neptune", "juno", "cassini", "voyager", "galileo", "maven",
            "messenger", "new horizons", "pioneer", "ulysses", "planet", "archive",
            "bundle", "dataset", "urn",
        ],
    },
    "spice": {
        "label": "SPICE geometry and ephemeris",
        "best_for": [
            "Spacecraft/body position, velocity, distance, and frame transforms",
            "Geometry context for CDAWeb/PDS data windows",
            "Coordinate-frame-aware observation planning",
        ],
        "not_for": [
            "fetching plasma data values by itself",
            "dataset/parameter metadata",
            # MMS and Cluster are CDAWeb magnetospheric missions with no SPICE
            # kernels; their geometry comes from CDAWeb orbit products, not
            # get_ephemeris. THEMIS A-E are the magnetospheric missions that do
            # have SPICE kernels (issue #26).
            "MMS/Cluster geometry (no SPICE kernels; use CDAWeb orbit products)",
        ],
        "discovery_tools": ["browse_data_sources(source_type=\"spice\")", "load_data_source(source_type=\"spice\", source_id=...)", "browse_data_parameters(source_type=\"spice\", dataset_id=...)"],
        "fetch_tools": ["get_ephemeris", "compute_distance", "transform_coordinates"],
        "cache_tools": ["manage_data_cache(source_type=\"spice\")"],
        # Note: "mms" is intentionally a CDAWeb keyword (above), not a SPICE
        # keyword — MMS has no SPICE kernels, so SPICE discovery must not claim it.
        "keywords": [
            "spice", "spicey", "spiceypy", "ephemeris", "trajectory", "geometry",
            "position", "velocity", "distance", "coordinate", "coordinates", "frame",
            "transform", "kernel", "kernels", "furnsh", "body", "spacecraft", "orbit",
            "perihelion", "heliocentric", "closest solar approach",
        ],
    },
}


def _as_list(values: list[str] | None) -> list[str]:
    return [str(v) for v in values or [] if str(v).strip()]


def _blob(*parts: object) -> str:
    tokens: list[str] = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (list, tuple, set)):
            tokens.extend(str(v) for v in part)
        else:
            tokens.append(str(part))
    return " ".join(tokens).lower()


def _score_sources(text: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    for key, profile in SOURCE_PROFILES.items():
        score = 0
        for keyword in profile["keywords"]:
            if keyword in text:
                score += 1
        scores[key] = score

    # Cross-source nudges that reflect common SPEDAS science workflows.
    if any(term in text for term in ["magnetic", "field", "plasma", "particle"]):
        scores["cdaweb"] += 1
        scores["pds"] += 1
    if any(term in text for term in ["where", "location", "near", "encounter", "closest approach"]):
        scores["spice"] += 1
    if any(term in text for term in ["jupiter", "saturn", "cassini", "juno", "galileo", "voyager"]):
        scores["pds"] += 2
        scores["spice"] += 1
    if any(term in text for term in ["earth", "magnetopause", "bow shock", "solar wind", "omni"]):
        scores["cdaweb"] += 2

    if max(scores.values()) == 0:
        # A general SPEDAS request should expose all families but ask the agent to
        # narrow the science target before fetching data.
        return {key: 1 for key in SOURCE_PROFILES}
    return scores


def _ranked_sources(question: str = "", target: str | None = None, observables: list[str] | None = None) -> list[dict[str, Any]]:
    text = _blob(question, target, observables)
    scores = _score_sources(text)
    ranked = sorted(SOURCE_PROFILES.items(), key=lambda item: (-scores[item[0]], item[0]))
    result: list[dict[str, Any]] = []
    for key, profile in ranked:
        result.append({
            "source": key,
            "label": profile["label"],
            "score": scores[key],
            "best_for": profile["best_for"],
            "discovery_tools": profile["discovery_tools"],
            "fetch_tools": profile["fetch_tools"],
            "cache_tools": profile["cache_tools"],
            "recommended_first_step": profile["discovery_tools"][0],
        })
    return result


def search_data_sources(
    question: str = "",
    target: str | None = None,
    observables: list[str] | None = None,
    query: str | None = None,
) -> dict[str, Any]:
    """Recommend which SPEDAS source family/families should lead a request.

    ``query`` is a backward-compatible alias for ``question`` (matching the
    parameter name used by ``browse_data_sources``). An explicit ``question``
    takes precedence; the alias is only used when ``question`` is empty.
    """
    if not question and query:
        question = query
    ranked = _ranked_sources(question=question, target=target, observables=observables)
    top_score = ranked[0]["score"] if ranked else 0
    recommended = [entry for entry in ranked if entry["score"] == top_score or entry["score"] > 1]
    return {
        "status": "success",
        "question": question,
        "target": target,
        "observables": _as_list(observables),
        "recommended_sources": [entry["source"] for entry in recommended],
        "ranked_sources": ranked,
        "agent_guidance": [
            "Use this as a planning step; do not fetch bulk data until dataset/parameter choices are explicit.",
            "For mixed science questions, combine source families: CDAWeb/PDS for measurements, SPICE for geometry.",
            "When uncertain, call plan_spedas_observation with the science goal and time range before fetching or computing products.",
        ],
    }


def compare_sources(science_goal: str = "") -> dict[str, Any]:
    """Return a compact comparison matrix for CDAWeb, PDS, and SPICE."""
    ranked = _ranked_sources(question=science_goal) if science_goal else []
    return {
        "status": "success",
        "science_goal": science_goal,
        "matrix": [
            {
                "source": key,
                "label": profile["label"],
                "best_for": profile["best_for"],
                "not_for": profile["not_for"],
                "discovery_tools": profile["discovery_tools"],
                "fetch_or_compute_tools": profile["fetch_tools"],
                "cache_tools": profile["cache_tools"],
            }
            for key, profile in SOURCE_PROFILES.items()
        ],
        "suggested_priority_for_goal": [entry["source"] for entry in ranked] if ranked else None,
    }


def plan_observation(
    science_goal: str,
    start: str | None = None,
    stop: str | None = None,
    target: str | None = None,
    observables: list[str] | None = None,
    data_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Plan a SPEDAS observation workflow without fetching data."""
    ranked = _ranked_sources(question=science_goal, target=target, observables=observables)
    requested_sources = [s.lower().replace("-", "_") for s in _as_list(data_sources)]
    invalid_sources = [s for s in requested_sources if s not in SOURCE_PROFILES]
    if requested_sources:
        selected = [s for s in requested_sources if s in SOURCE_PROFILES]
    else:
        selected = [entry["source"] for entry in ranked if entry["score"] > 1]
        if not selected:
            selected = [entry["source"] for entry in ranked]

    needs_user_input = [
        field for field, value in {"start": start, "stop": stop, "science_goal": science_goal}.items() if not value
    ]
    steps: list[dict[str, Any]] = [
        {
            "phase": "scope",
            "goal": science_goal,
            "target": target,
            "time_range": {"start": start, "stop": stop},
            "observables": _as_list(observables),
            "needs_user_input": needs_user_input,
            "invalid_sources": invalid_sources,
        }
    ]
    for source in selected:
        profile = SOURCE_PROFILES[source]
        steps.append({
            "phase": f"discover_{source}",
            "source": source,
            "rationale": profile["best_for"],
            "tools": profile["discovery_tools"],
            "next_unified_calls": [
                {"tool": "browse_data_sources", "args": {"source_type": source}},
                {"tool": "load_data_source", "args": {"source_type": source, "source_id": "<choose from browse_data_sources>"}},
                {"tool": "browse_data_parameters", "args": {"source_type": source, "dataset_id": "<choose from load_data_source>"}},
            ],
            "output": "candidate missions/datasets/parameters/frames; no bulk data yet",
        })
        steps.append({
            "phase": f"fetch_or_compute_{source}",
            "source": source,
            "tools": profile["fetch_tools"],
            "preconditions": [
                "candidate dataset/mission/frame has been selected",
                "time range is explicit",
                "bulk outputs use output_dir/output_file and return paths only",
            ],
        })

    steps.append({
        "phase": "preserve_provenance",
        "tools": ["create_spedas_analysis_bundle"],
        "checklist": [
            "record original science goal, target, time range, and selected sources",
            "store fetched files separately from request/provenance JSON",
            "record package versions and MCP tool names in the analysis note",
        ],
    })
    if invalid_sources and not selected:
        status = "error"
    elif invalid_sources or needs_user_input:
        status = "needs_input"
    else:
        status = "success"

    return {
        "status": status,
        "recommended_sources": selected,
        "ranked_sources": ranked,
        "plan": steps,
        "needs_user_input": needs_user_input,
        "invalid_sources": invalid_sources,
        "low_level_tools_remain_available": True,
    }


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name.strip().lower()).strip("-._")
    return slug or "spedas-analysis"


def create_analysis_bundle(
    study_name: str,
    output_dir: str,
    science_goal: str = "",
    target: str | None = None,
    start: str | None = None,
    stop: str | None = None,
    data_sources: list[str] | None = None,
) -> dict[str, Any]:
    """Create a lightweight file bundle for a SPEDAS MCP analysis plan."""
    bundle_dir = Path(output_dir).expanduser().resolve() / _slugify(study_name)
    subdirs = {
        "requests": bundle_dir / "requests",
        "data": bundle_dir / "data",
        "plots": bundle_dir / "plots",
        "provenance": bundle_dir / "provenance",
        "notes": bundle_dir / "notes",
    }
    for path in subdirs.values():
        path.mkdir(parents=True, exist_ok=True)

    plan = plan_observation(
        science_goal=science_goal or study_name,
        start=start,
        stop=stop,
        target=target,
        data_sources=data_sources,
    )
    request_path = subdirs["requests"] / "spedas_plan.json"
    request_path.write_text(json.dumps(plan, indent=2), encoding="utf-8")

    readme_path = bundle_dir / "README.md"
    readme_path.write_text(
        "\n".join([
            f"# {study_name}",
            "",
            "SPEDAS MCP analysis bundle scaffold.",
            "",
            f"- Science goal: {science_goal or study_name}",
            f"- Target: {target or 'TBD'}",
            f"- Time range: {start or 'TBD'} to {stop or 'TBD'}",
            f"- Recommended sources: {', '.join(plan['recommended_sources'])}",
            "",
            "## Next actions",
            "",
            "1. Review `requests/spedas_plan.json`.",
            "2. Use unified data-layer discovery tools before any data fetch.",
            "3. Write fetched files under `data/` and provenance under `provenance/`.",
            "4. Keep plots and derived artifacts separate from raw/archive data.",
            "",
        ]),
        encoding="utf-8",
    )

    provenance_note = subdirs["provenance"] / "README.md"
    provenance_note.write_text(
        "# Provenance notes\n\nRecord MCP tool calls, package versions, input time ranges, selected datasets, and output file hashes here.\n",
        encoding="utf-8",
    )

    return {
        "status": "success",
        "bundle_dir": str(bundle_dir),
        "paths": {
            "readme": str(readme_path),
            "request_plan": str(request_path),
            "provenance_note": str(provenance_note),
            **{name: str(path) for name, path in subdirs.items()},
        },
        "recommended_sources": plan["recommended_sources"],
        "next_tools": ["search_spedas_data_sources", "plan_spedas_observation", "browse_data_sources", "load_data_source", "browse_data_parameters", "fetch_data_product"],
    }
