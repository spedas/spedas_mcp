"""SPEDAS-level workflow helpers for the unified MCP facade.

The low-level tool groups expose CDAWeb, PDS, and SPICE directly.  This module
adds a small SPEDAS semantic layer: choose the right source family, plan a
science observation workflow, compare the source families, and scaffold an
analysis bundle that records request/provenance intent before data fetches.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
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


# Mission/target keywords for lightweight extraction from a natural-language
# science goal (issue #30). Each entry maps a lowercase phrase to the canonical
# target label returned to the caller. Order matters: longer/more specific
# phrases are listed first so e.g. "parker solar probe" wins over a bare "psp".
# Kept conservative and transparent — only well-known heliophysics/planetary
# missions, and only exact word/phrase matches (see ``_extract_target``).
_MISSION_KEYWORDS: list[tuple[str, str]] = [
    ("parker solar probe", "Parker Solar Probe"),
    ("solar orbiter", "Solar Orbiter"),
    ("van allen probes", "Van Allen Probes"),
    ("van allen probe", "Van Allen Probes"),
    ("new horizons", "New Horizons"),
    # ``solo`` and ``cluster`` are common English words, so they are matched only
    # in explicit spacecraft phrasing (see ``_QUALIFIED_MISSION_KEYWORDS`` below)
    # rather than as bare tokens, which produced false positives (SF1: a bare
    # "solo" -> Solar Orbiter, "cluster" -> Cluster).
    ("psp", "Parker Solar Probe"),
    ("rbsp", "Van Allen Probes"),
    ("mms", "MMS"),
    ("themis", "THEMIS"),
    ("stereo", "STEREO"),
    ("dscovr", "DSCOVR"),
    ("geotail", "Geotail"),
    ("juno", "Juno"),
    ("cassini", "Cassini"),
    ("voyager", "Voyager"),
    ("galileo", "Galileo"),
    ("maven", "MAVEN"),
    ("messenger", "MESSENGER"),
    ("ulysses", "Ulysses"),
    ("ace", "ACE"),
    ("wind", "Wind"),
    ("omni", "OMNI"),
]

# Missions whose short names collide with ordinary English ("solo", "cluster")
# are only inferred from explicit spacecraft/mission phrasing. Each pattern is a
# case-insensitive regex matched against the goal text. This preserves real
# references ("SolO spacecraft", "Cluster mission") while ignoring generic uses
# ("fly solo", "a cluster of events"). ``solar orbiter`` is already covered by
# the main keyword list above.
_QUALIFIED_MISSION_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsolo\s+(?:spacecraft|orbiter|mission|probe)\b", re.IGNORECASE), "Solar Orbiter"),
    (re.compile(r"\bcluster\s+(?:spacecraft|mission|constellation|satellites?)\b", re.IGNORECASE), "Cluster"),
]

# ISO date with an optional trailing time. The date is required; the time
# (HH:MM optionally :SS, with a leading space or 'T') is captured separately so
# date-only goals can be widened to a day-scale interval.
_DATETIME_RE = re.compile(
    r"(?P<date>\d{4}-\d{2}-\d{2})"
    r"(?:[ T](?P<time>\d{2}:\d{2}(?::\d{2})?))?",
)

# A standalone clock time (e.g. "13:06 UT", "13:06Z") that may appear apart from
# the date in phrasing like "on 2015-10-16 around 13:06 UT". Matched only to
# refine a single-date goal; never used to invent a date.
_LOOSE_TIME_RE = re.compile(
    r"(?<![\d:])(?P<time>\d{2}:\d{2}(?::\d{2})?)\s*(?:UT|UTC|Z)\b",
    re.IGNORECASE,
)

# Words signalling that a single datetime is approximate, so a small symmetric
# window is appropriate rather than treating it as an exact bound.
_APPROX_WORDS = ("around", "near", "circa", "about", "approximately", "~")


def _extract_target(text: str) -> str | None:
    """Return a canonical mission/target label inferred from ``text``.

    Matching is conservative: a keyword only matches on word boundaries so a
    short token like ``ace`` does not fire inside ``"surface"`` or ``"space"``.
    The bare word ``wind`` is additionally guarded against the plasma phrase
    ``"solar wind"`` / ``"solar-wind"`` and generic phrases like ``"wind speed"``
    so a goal about the solar wind is not misread as the Wind spacecraft.
    Spacecraft whose short names are everyday words (``solo``, ``cluster``) are
    only inferred from explicit phrasing (see ``_QUALIFIED_MISSION_KEYWORDS``).
    """
    lowered = text.lower()
    # Explicit, qualified spacecraft phrasing takes precedence over plain keywords.
    for pattern, label in _QUALIFIED_MISSION_KEYWORDS:
        if pattern.search(text):
            return label
    for keyword, label in _MISSION_KEYWORDS:
        if keyword == "wind":
            # Match "wind" as a mission only in spacecraft phrasing, never inside
            # "solar wind"/"solar-wind" or generic phrases like "wind speed".
            if re.search(
                r"(?<![a-z0-9])(?<!solar )(?<!solar-)wind(?![a-z0-9])"
                r"(?!\s+(?:speed|velocity|direction|stream|streams|profile|data))",
                lowered,
            ):
                return label
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", lowered):
            return label
    return None


def _extract_time_range(text: str) -> tuple[str | None, str | None]:
    """Infer ``(start, stop)`` ISO-8601 bounds from dates in ``text``.

    - Two or more dates: first as ``start``, last as ``stop``.
    - One datetime with a time component near an approximate word
      (``around``/``near``/...): a symmetric +/-1 hour window.
    - One date with a time but no approximate word: that instant as ``start``,
      +1 hour as ``stop``.
    - One date with no time: a full-day interval ``[00:00:00Z, next day)``.

    ``_DATETIME_RE`` matches date-*shaped* tokens, including impossible ones like
    ``2015-13-40`` or ``2015-02-30``. Such tokens are validated by
    ``_parse_datetime``/``_parse_utc_date`` and silently dropped, so an
    impossible date is treated as "no parse" rather than raising a raw
    ``ValueError`` out of the public planner tools (issue #30, blocker B1).

    Returns ``(None, None)`` when no parseable date is present.
    """
    matches = [m for m in _DATETIME_RE.finditer(text) if _is_valid_match(m)]
    if not matches:
        return None, None

    if len(matches) >= 2:
        start = _iso_start(matches[0])
        stop = _iso_stop(matches[-1])
        if start is None or stop is None:
            return None, None
        return start, stop

    match = matches[0]
    date = match.group("date")
    time = match.group("time")
    if time is None:
        # The time may be written apart from the date ("on 2015-10-16 around
        # 13:06 UT"); pick it up if a single explicit clock time is present.
        loose = _LOOSE_TIME_RE.search(text)
        if loose is not None:
            time = loose.group("time")
    if time is None:
        # Date-only: widen to a full UTC day.
        start_day = _parse_utc_date(date)
        if start_day is None:
            return None, None
        stop_day = start_day + timedelta(days=1)
        return _format_iso(start_day), _format_iso(stop_day)

    instant = _parse_iso_instant(date, time)
    if instant is None:
        # An impossible date or time component; fall back to no parse.
        return None, None
    lowered = text.lower()
    if any(word in lowered for word in _APPROX_WORDS):
        return (
            _format_iso(instant - timedelta(hours=1)),
            _format_iso(instant + timedelta(hours=1)),
        )
    return _format_iso(instant), _format_iso(instant + timedelta(hours=1))


def _is_valid_match(match: re.Match[str]) -> bool:
    """Return ``True`` only when the matched date (and time, if any) is real."""
    date, time = match.group("date"), match.group("time")
    if time is None:
        return _parse_utc_date(date) is not None
    return _parse_iso_instant(date, time) is not None


def _parse_utc_date(date: str) -> datetime | None:
    """Parse ``YYYY-MM-DD`` to a UTC datetime, or ``None`` if impossible."""
    try:
        return datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _parse_iso_instant(date: str, time: str) -> datetime | None:
    """Parse a date+time to a UTC datetime, or ``None`` if impossible."""
    fmt = "%Y-%m-%d %H:%M:%S" if time.count(":") == 2 else "%Y-%m-%d %H:%M"
    try:
        return datetime.strptime(f"{date} {time}", fmt).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _iso_start(match: re.Match[str]) -> str | None:
    date, time = match.group("date"), match.group("time")
    if time is None:
        start = _parse_utc_date(date)
        return _format_iso(start) if start is not None else None
    instant = _parse_iso_instant(date, time)
    return _format_iso(instant) if instant is not None else None


def _iso_stop(match: re.Match[str]) -> str | None:
    date, time = match.group("date"), match.group("time")
    if time is None:
        # A bare end date is inclusive of that whole UTC day.
        end = _parse_utc_date(date)
        return _format_iso(end + timedelta(days=1)) if end is not None else None
    instant = _parse_iso_instant(date, time)
    return _format_iso(instant) if instant is not None else None


def _format_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso8601(value: str | None) -> datetime | None:
    """Best-effort parse of an ISO-8601 timestamp for ordering comparisons.

    Returns ``None`` (rather than raising) for ``None`` or any value that does
    not parse, so callers can compare bounds only when both are real timestamps.
    Accepts a trailing ``Z`` and date-only values.
    """
    if not value:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _ge_safe(a: datetime, b: datetime) -> bool:
    """``a >= b`` that tolerates a naive/aware mismatch (assume UTC if naive)."""
    if (a.tzinfo is None) != (b.tzinfo is None):
        a = a.replace(tzinfo=a.tzinfo or timezone.utc)
        b = b.replace(tzinfo=b.tzinfo or timezone.utc)
    return a >= b


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
    """Plan a SPEDAS observation workflow without fetching data.

    When ``start``/``stop``/``target`` are not supplied, a lightweight,
    deterministic pass extracts ISO dates and mission keywords from
    ``science_goal`` so a complete natural-language goal does not bounce back as
    ``needs_input`` (issue #30). Explicit parameters always take precedence over
    anything inferred from the text; inferred values are reported under the
    ``inferred`` key for transparency.
    """
    inferred: dict[str, str] = {}
    if science_goal:
        if not start or not stop:
            extracted_start, extracted_stop = _extract_time_range(science_goal)
            if not start and extracted_start:
                start = extracted_start
                inferred["start"] = extracted_start
            if not stop and extracted_stop:
                stop = extracted_stop
                inferred["stop"] = extracted_stop
        if not target:
            extracted_target = _extract_target(science_goal)
            if extracted_target:
                target = extracted_target
                inferred["target"] = extracted_target

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

    # Sanity check: a non-positive interval (start >= stop) is never usable. This
    # most often surfaces when an explicit ``start`` is combined with an inferred
    # ``stop`` (or vice versa). Compared only when both bounds parse as ISO so
    # non-ISO explicit values are passed through untouched rather than rejected.
    time_range_warning: str | None = None
    start_dt, stop_dt = _parse_iso8601(start), _parse_iso8601(stop)
    if start_dt is not None and stop_dt is not None and _ge_safe(start_dt, stop_dt):
        time_range_warning = (
            f"start ({start}) is not before stop ({stop}); confirm the intended time range"
        )
        if "start" not in needs_user_input:
            needs_user_input.append("start")
        if "stop" not in needs_user_input:
            needs_user_input.append("stop")
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
        "inferred": inferred,
        "invalid_sources": invalid_sources,
        "time_range_warning": time_range_warning,
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
