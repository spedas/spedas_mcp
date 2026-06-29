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

from .optional_backends import analysis_dependencies_available


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
            # Magnetospheric/substorm science vocabulary. THEMIS (and Cluster/MMS/
            # Geotail) magnetotail substorm studies live entirely in CDAWeb, but a
            # goal phrased purely in physics terms ("THEMIS magnetotail substorm")
            # used to score only 1 on the bare "themis"/"magnetosphere" tokens.
            # With no source above the score>1 selection threshold, plan_observation
            # fell back to "all sources equally" and recommended the PDS planetary
            # archive — which is explicitly not_for near-Earth CDAWeb observatories.
            # Naming the magnetospheric terms here lifts the in-domain query above
            # the threshold so it routes to CDAWeb alone (T006). The cross-source
            # near-Earth nudge below adds the multi-word phrases.
            "magnetotail", "substorm", "injection", "reconnection", "aurora",
            "auroral", "electrojet", "ring current", "geomagnetic",
            # Van Allen Probes (RBSP) is a CDAWeb-only inner-magnetosphere mission
            # — its EMFISIS/MagEIS/REPT/HOPE/EFW/RBSPICE products live in CDAWeb,
            # and (like MMS/Cluster) it has no SPICE kernels and no PDS bundles.
            # ``_extract_target`` already canonicalises these phrases to "Van Allen
            # Probes" (issue #30); the source router must agree so a radiation-belt
            # goal routes to CDAWeb instead of falling back to "all sources equally".
            "rbsp", "van allen", "van allen probes",
            # Parker Solar Probe (PSP) is a CDAWeb heliophysics observatory: its
            # FIELDS (magnetic field, RTN) and SWEAP (plasma) products live in
            # CDAWeb, with no PDS planetary bundles. A switchback-interval goal
            # phrased with the full mission name and switchback/instrument science
            # used to score 0 on the lone "psp" abbreviation, so the planner fell
            # back to "all sources equally" and surfaced the PDS archive (T014).
            # Registering the full name and switchback/SWEAP vocabulary lifts these
            # goals onto CDAWeb. ``encounter`` also nudges SPICE (perihelion
            # geometry) below; naming it here keeps CDAWeb (the measurement source)
            # from being dropped under the geometry nudge. The bare plural "fields"
            # is *deliberately* excluded — it is everyday plasma vocabulary
            # ("magnetic fields") that regressed planetary magnetic-field goals
            # (e.g. MESSENGER/Mercury); the unambiguous parker/psp/switchback/sweap
            # tokens capture the FIELDS instrument instead.
            "parker", "parker solar probe", "switchback", "switchbacks",
            "sweap", "encounter",
            # Ulysses is an SPDF/CDAWeb mission (remote_data_dir is spdf.gsfc; its
            # SWOOPS/VHM/FGM/SWICS/URAP products live in *_cdaweb/ directories with
            # the UY_* naming convention), not a PDS planetary-archive mission. It
            # previously appeared *only* in the PDS keywords, which mis-routed
            # Ulysses high-latitude solar-wind goals toward the planetary archive.
            # Moved here (analogous to RBSP/Van Allen Probes) so Ulysses leads with
            # CDAWeb; SPICE remains available for heliographic-latitude geometry
            # (NAIF body -55) via the high-latitude nudge below (T013).
            "ulysses",
            # STEREO (Ahead/Behind) is an SPDF/CDAWeb twin-spacecraft heliophysics
            # mission: its IMPACT (SEP/SEPT/MAG), PLASTIC (solar-wind plasma), and
            # SECCHI/WAVES products live in CDAWeb (the ST[AB]_* dataset family),
            # with no PDS planetary bundles. ``_extract_target`` already maps
            # "STEREO"/"STEREO-A"/"STEREO B"/"stereoa" to the canonical "STEREO"
            # label (#30 / Batch V T007), but the source router had no matching
            # keyword, so a SEP/energetic-particle goal phrased without the generic
            # "solar wind"/"plasma"/"magnetic" measurement words ("STEREO-A SEP
            # SEPT", "STEREO-A IMPACT energetic electrons") scored only 1 on every
            # family and fell back to "all sources equally" — surfacing the PDS
            # planetary archive. Worse, "STEREO ahead spacecraft SEP" routed to
            # SPICE alone (on the bare "spacecraft" geometry token). Registering the
            # mission name and its unambiguous instrument acronym lifts these goals
            # onto CDAWeb. The bare "impact"/"sep"/"mag"/"plastic" English words are
            # *deliberately* excluded — only the whole-word acronym "sept" and the
            # multi-word SEP phrases (nudge below) are unambiguous; this mirrors the
            # parker/psp "fields" exclusion (T020).
            "stereo", "sept",
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
            "uranus", "neptune", "pluto", "juno", "cassini", "voyager", "galileo",
            "maven", "messenger", "new horizons", "pioneer", "planet", "archive",
            "bundle", "dataset", "urn",
            # New Horizons instruments archived in PDS PPI (NEW-HORIZONS_PPI): SWAP
            # (Solar Wind Around Pluto, the "Solar Wind" product) and PEPSSI (Pluto
            # Energetic Particle Spectrometer). Naming them lets instrument-phrased
            # goals ("New Horizons SWAP/PEPSSI") score PDS — its only honest source,
            # as New Horizons has no CDAWeb time-series (T019). Both are distinctive
            # acronyms (word-boundary matched, so "swap" never fires in "swapping").
            "swap", "pepssi",
            # Note: "ulysses" was moved to the CDAWeb keyword list above — it is an
            # SPDF/CDAWeb solar-wind mission, not a PDS planetary-archive one (T013).
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
            # Van Allen Probes (RBSP) likewise has no SPICE kernels; its orbit
            # comes from CDAWeb magnephem products, not get_ephemeris.
            "Van Allen Probes/RBSP geometry (no SPICE kernels; use CDAWeb magnephem)",
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


_PLANETARY_CONTEXT_TERMS = (
    "jupiter", "saturn", "mars", "venus", "mercury", "uranus", "neptune",
    # Pluto is the New Horizons flyby target and has PDS PPI products
    # (NEW-HORIZONS_PPI SWAP "Solar Wind" + PEPSSI). Without it, "Pluto flyby
    # plasma" scored no PDS planetary boost and mis-routed to near-Earth CDAWeb
    # (T019). Listed as a body alongside the other planets it sits among.
    "pluto",
    "juno", "cassini", "galileo", "voyager", "maven", "messenger",
    "new horizons", "pioneer",
)


def _word_pattern(term: str) -> re.Pattern[str]:
    """Compile a word-boundary-anchored pattern for a source/nudge ``term``.

    Source-keyword and cross-source-nudge matching previously used a bare
    ``term in text`` substring test, so short tokens fired *inside* ordinary
    science words: ``ppi`` matched "fla**ppi**ng"/"ma**ppi**ng", ``urn`` matched
    "ret**urn**", and ``mars`` matched "**mars**halling" — inflating the PDS
    planetary score for pure near-Earth (e.g. Geotail magnetotail) goals (T011).

    Anchoring with non-word lookarounds on the outer edges (the same discipline
    ``_mission_keyword_pattern`` already uses for mission keywords) keeps genuine
    whole-word/whole-phrase mentions matching — including multi-word phrases like
    ``"solar wind"``, ``"ring current"``, ``"closest approach"`` — while ignoring
    matches buried inside unrelated words. Letters/digits count as word
    characters so hyphenated forms (``"solar-wind"``) still match on the edges.
    """
    return re.compile(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", re.IGNORECASE)


def _any_match(patterns: tuple[re.Pattern[str], ...], text: str) -> bool:
    return any(pattern.search(text) for pattern in patterns)


# Pre-compiled, word-boundary-aware patterns for the source keyword lists and the
# cross-source nudge term lists. Compiled once at import; see ``_word_pattern``.
_SOURCE_KEYWORD_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    key: tuple(_word_pattern(keyword) for keyword in profile["keywords"])
    for key, profile in SOURCE_PROFILES.items()
}
_PLANETARY_CONTEXT_PATTERNS = tuple(_word_pattern(t) for t in _PLANETARY_CONTEXT_TERMS)
_MEASUREMENT_PATTERNS = tuple(_word_pattern(t) for t in ("magnetic", "field", "plasma", "particle"))
_GEOMETRY_HINT_PATTERNS = tuple(
    _word_pattern(t) for t in ("where", "location", "near", "encounter", "closest approach")
)
# Multi-word/phrase magnetotail/substorm vocabulary that reinforces the
# near-Earth CDAWeb lane. The boundary terms (bow shock / magnetopause /
# magnetosheath) and "solar wind" are split out below so they can be guarded
# against planetary contexts (T015/T019).
# Unconditional near-Earth CDAWeb vocabulary. These terms are Earth-specific
# (or OMNI-specific) and never describe a genuine planetary PDS-archive context,
# so they boost CDAWeb regardless of a named body/mission. "solar wind" is
# *deliberately excluded* here and guarded below: the solar wind is measured at
# Pluto too (New Horizons SWAP, archived in PDS as the "Solar Wind" product), so
# a bare "solar wind" mention in a planetary context must not surface CDAWeb
# (T019), mirroring the T015 bow-shock / T013 high-latitude planetary guards.
_NEAR_EARTH_PATTERNS = tuple(
    _word_pattern(t) for t in (
        "earth", "omni",
        "magnetotail", "plasma sheet", "substorm",
    )
)
# Boundary structures that exist at Mars/Venus/Mercury too, not just Earth, plus
# the bare "solar wind" phrase. They only count as a near-Earth CDAWeb nudge when
# no planetary body/mission is named — otherwise "MAVEN Mars bow shock" or "New
# Horizons solar wind" spuriously routes CDAWeb alongside PDS (T015/T019),
# mirroring the "radiation belt" guard.
_BOUNDARY_PATTERNS = tuple(_word_pattern(t) for t in ("bow shock", "magnetopause", "magnetosheath"))
_RADIATION_BELT_PATTERN = _word_pattern("radiation belt")
_SOLAR_WIND_PATTERN = _word_pattern("solar wind")
# Ulysses-style high-latitude / fast-solar-wind heliospheric vocabulary. These
# define the out-of-ecliptic polar-pass science the planner must route to CDAWeb
# (measurements, +2) with SPICE for heliographic-latitude geometry (+1), guarded
# against planetary contexts so a "high-latitude" mention near Saturn stays
# PDS-led (T013).
_HIGH_LATITUDE_PATTERNS = tuple(
    _word_pattern(t) for t in (
        "high latitude", "high-latitude", "heliographic latitude",
        "polar pass", "fast solar wind", "corotating interaction region",
        "out of the ecliptic",
    )
)
# Parker-Solar-Probe-style near-Sun switchback science. ``switchback(s)``/``sweap``
# reinforce CDAWeb (the FIELDS/SWEAP measurement source), guarded against
# planetary contexts the same way (T014).
_HELIO_OBSERVATORY_PATTERNS = tuple(
    _word_pattern(t) for t in ("switchback", "switchbacks", "sweap")
)
# STEREO-style solar-energetic-particle heliospheric science. The whole multi-word
# phrases ("solar energetic particle(s)", "energetic electrons/protons/ions") are
# unambiguous in-situ measurement vocabulary that belongs to CDAWeb (the
# IMPACT/SEPT/HET/LET/SIT measurement source), so they reinforce CDAWeb (+2),
# guarded against planetary contexts so an "energetic ions" mention near Jupiter
# stays PDS-led — exactly like the switchback/high-latitude guards (T020). The
# bare acronyms "sep"/"impact" are deliberately *not* here: "sep" collides with
# the month abbreviation and "impact" is an everyday English word; the unambiguous
# "sept" acronym is registered as a CDAWeb keyword above instead.
_SEP_PARTICLE_PATTERNS = tuple(
    _word_pattern(t) for t in (
        "solar energetic particle", "solar energetic particles",
        "energetic electrons", "energetic protons", "energetic ions",
    )
)
# Generic measurement vocabulary that sits in the CDAWeb keyword list but is
# *equally* planetary-archive physics ("Cassini Saturn magnetosphere magnetic
# field", "Galileo Jupiter plasma"). For a near-Earth/heliophysics goal these
# words rightly reinforce CDAWeb, but a Cassini/Juno/MAVEN-style planetary goal
# names a PDS-only mission with no CDAWeb datasets, so leaving them in inflates
# the CDAWeb score above the score>1 recommendation threshold and surfaces CDAWeb
# alongside PDS for missions that have no CDAWeb data (Batch X T016). When a
# planetary body/mission is named these matches are subtracted from CDAWeb,
# mirroring the existing boundary (bow shock) and radiation-belt planetary guards
# (T015/T006). Mission/observatory-specific CDAWeb tokens (omni/mms/themis/psp/
# rbsp/...) are deliberately *not* listed here: a goal that names a near-Earth
# observatory keeps its CDAWeb score even if it also mentions a planet.
_GENERIC_CDAWEB_MEASUREMENT_PATTERNS = tuple(
    _word_pattern(t) for t in (
        "magnetosphere", "ionosphere", "magnetic", "electric", "particle", "plasma",
    )
)
# Voyager-style outer-heliosphere / heliopause / interstellar science. Voyager
# 1/2 are a *dual-archive* mission: their planetary-flyby products live in PDS
# PPI, but their decades-long heliospheric MAG/PLS time-series — through the
# termination shock and heliopause and into the interstellar magnetic field —
# are CDAWeb/SPDF observatory products (the VOYAGER1/2 MAG and PLS datasets), not
# PDS planetary bundles. Because "voyager" is (correctly, for the flybys) a
# planetary-context mission, an outer-heliosphere goal otherwise scored
# PDS>CDAWeb, and a goal with no generic measurement word ("Voyager outer
# heliosphere termination shock") scored CDAWeb=0 and routed to PDS *alone* —
# burying the CDAWeb time-series that actually holds the data. These heliospheric
# terms reinforce CDAWeb (the time-series source) and suppress the planetary PDS
# boost, guarded so a goal that also names a specific planetary-flyby body
# (Jupiter/Saturn/Uranus/Neptune or "flyby") stays PDS-led (T018).
_OUTER_HELIOSPHERE_PATTERNS = tuple(
    _word_pattern(t) for t in (
        "heliopause", "outer heliosphere", "termination shock", "heliosheath",
        "interstellar magnetic field", "interstellar medium",
        "very local interstellar medium", "vlism", "interstellar space",
    )
)
# Specific planetary-flyby bodies (the outer planets Voyager encountered) and the
# bare "flyby" term, whose archived products are PDS-led. Used only to *guard*
# the outer-heliosphere nudge above: when one of these is named the goal is a
# planetary-flyby/archive workflow, so a heliopause word mentioned in passing
# ("Voyager Jupiter flyby on the way to the heliopause") must not pull the
# routing onto CDAWeb. Earth/Mercury/Mars/Venus are deliberately excluded — they
# are not on Voyager's outbound heliospheric trajectory and have their own
# near-Earth/PDS handling above.
_FLYBY_BODY_PATTERNS = tuple(
    _word_pattern(t) for t in (
        "jupiter", "jovian", "saturn", "saturnian", "uranus", "neptune", "flyby",
    )
)


def _score_sources(text: str) -> dict[str, int]:
    scores: dict[str, int] = {}
    for key, patterns in _SOURCE_KEYWORD_PATTERNS.items():
        scores[key] = sum(1 for pattern in patterns if pattern.search(text))

    # Cross-source nudges that reflect common SPEDAS science workflows. All term
    # matching here is word-boundary-aware (``_any_match``) so short tokens never
    # fire inside unrelated science words (T011).
    if _any_match(_MEASUREMENT_PATTERNS, text):
        scores["cdaweb"] += 1
        scores["pds"] += 1
    if _any_match(_GEOMETRY_HINT_PATTERNS, text):
        scores["spice"] += 1

    # Voyager outer-heliosphere / heliopause / interstellar context: the goal is a
    # heliospheric CDAWeb time-series workflow, *unless* a specific planetary-flyby
    # body (Jupiter/Saturn/Uranus/Neptune or "flyby") is also named — in which case
    # it is a planetary-archive (PDS) flyby workflow and the heliospheric word is
    # incidental. Computed before the planetary PDS boost so it can suppress it
    # (Voyager itself is a planetary-context mission name); see _OUTER_HELIOSPHERE_
    # PATTERNS (T018).
    outer_heliosphere_context = _any_match(_OUTER_HELIOSPHERE_PATTERNS, text) and not _any_match(
        _FLYBY_BODY_PATTERNS, text
    )

    planetary_context = _any_match(_PLANETARY_CONTEXT_PATTERNS, text)
    if planetary_context and not outer_heliosphere_context:
        scores["pds"] += 2
        scores["spice"] += 1
        # Generic measurement keywords (magnetosphere / magnetic / plasma / ...)
        # are equally planetary-archive physics vocabulary, so they must not
        # inflate CDAWeb for a PDS-only planetary mission (Cassini/Juno/MAVEN
        # have no CDAWeb datasets). Subtract those bare-keyword matches from the
        # CDAWeb score, mirroring the boundary/radiation-belt planetary guards
        # below (T015/T006). Floored at 0 so a planetary goal that *also* names a
        # near-Earth observatory still keeps that observatory's CDAWeb token
        # (e.g. "OMNI") -- only the generic physics words are removed (T016). The
        # Voyager outer-heliosphere branch is excluded from this block so the
        # heliospheric MAG/PLS time-series keeps its CDAWeb score (T018 × T016).
        generic_cdaweb = sum(
            1 for pattern in _GENERIC_CDAWEB_MEASUREMENT_PATTERNS if pattern.search(text)
        )
        scores["cdaweb"] = max(0, scores["cdaweb"] - generic_cdaweb)
    near_earth_context = _any_match(_NEAR_EARTH_PATTERNS, text)
    # Boundary structures (bow shock / magnetopause / magnetosheath), a bare
    # "radiation belt" phrase, and a bare "solar wind" phrase are good CDAWeb
    # nudges for Earth/near-Earth science, but not for explicitly planetary
    # contexts: Mars/Venus bow shocks and Jupiter radiation belts are PDS
    # planetary-archive science (T015/T006), and New Horizons "solar wind" is the
    # PDS SWAP product, not a CDAWeb time-series (T019).
    if not planetary_context and (
        _any_match(_BOUNDARY_PATTERNS, text)
        or _RADIATION_BELT_PATTERN.search(text)
        or _SOLAR_WIND_PATTERN.search(text)
    ):
        near_earth_context = True
    if near_earth_context:
        scores["cdaweb"] += 2

    # Ulysses high-latitude / fast-solar-wind polar-pass science: boost CDAWeb
    # (measurements, +2) and SPICE (heliographic-latitude geometry, +1), guarded
    # so a "high-latitude" mention in a planetary context stays PDS-led (T013).
    if not planetary_context and _any_match(_HIGH_LATITUDE_PATTERNS, text):
        scores["cdaweb"] += 2
        scores["spice"] += 1

    # PSP-style near-Sun switchback science: reinforce CDAWeb (FIELDS/SWEAP
    # measurements, +2) so a geometry (encounter -> SPICE) or archive nudge can
    # never overtake it, guarded against planetary contexts (T014).
    if not planetary_context and _any_match(_HELIO_OBSERVATORY_PATTERNS, text):
        scores["cdaweb"] += 2

    # STEREO-style solar-energetic-particle science: reinforce CDAWeb (the
    # IMPACT/SEPT measurement source, +2) so a bare "spacecraft" geometry nudge or
    # archive fallback can never overtake it, guarded against planetary contexts
    # so "energetic ions at Jupiter" stays PDS-led (T020).
    if not planetary_context and _any_match(_SEP_PARTICLE_PATTERNS, text):
        scores["cdaweb"] += 2

    # Voyager outer-heliosphere science: reinforce CDAWeb (the MAG/PLS time-series
    # source, +2) so the heliospheric workflow leads the PDS planetary archive.
    # The planetary PDS boost was already suppressed above for this context, so
    # +2 is enough to put CDAWeb first even when "voyager" scored a lone PDS
    # keyword. Guarded by _FLYBY_BODY_PATTERNS (folded into the context flag) so a
    # Jupiter/Neptune flyby goal keeps its PDS lead (T018).
    if outer_heliosphere_context:
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

# Mission keywords that fly numbered/lettered probes, so a single-spacecraft goal
# is naturally phrased with a per-probe suffix ("MMS1", "rbspa", "themisa"). For
# these, an optional trailing probe token is allowed immediately after the
# keyword (a per-mission probe digit/letter, e.g. MMS1-4 or RBSP a/b), still
# anchored by a trailing word boundary so "acexyz"/"soloist" do NOT match.
# The CDAWeb discovery
# layer already fuzzy-resolves "MMS1" -> "mms"; this keeps target inference in the
# planner consistent with it (Batch V T007). Keys are the lowercase keyword.
_NUMBERED_SPACECRAFT_KEYWORDS: dict[str, str] = {
    "mms": r"[1-4]",
    "rbsp": r"[ab]",
    "themis": r"[a-e]",
    "stereo": r"[ab]",
}


def _mission_keyword_pattern(keyword: str) -> str:
    """Word-boundary regex for ``keyword`` allowing an optional probe suffix.

    For numbered/lettered missions (see ``_NUMBERED_SPACECRAFT_KEYWORDS``) an
    optional trailing probe token is permitted between the keyword and the
    closing boundary, so "MMS1"/"rbspa" match while generic-word lookalikes
    ("acexyz", "soloist") still do not.
    """
    suffix = _NUMBERED_SPACECRAFT_KEYWORDS.get(keyword)
    body = re.escape(keyword) + (f"(?:{suffix})?" if suffix else "")
    return rf"(?<![a-z0-9]){body}(?![a-z0-9])"


# Missions whose short names collide with ordinary English ("solo", "cluster")
# are only inferred from explicit spacecraft/mission phrasing. Each pattern is a
# case-insensitive regex matched against the goal text. This preserves real
# references ("SolO spacecraft", "Cluster mission") while ignoring generic uses
# ("fly solo", "a cluster of events"). ``solar orbiter`` is already covered by
# the main keyword list above.
#
# Cluster is a four-spacecraft (C1-C4) constellation, so multi-spacecraft goals
# are its most natural phrasing. The bare ``\bcluster\s+<qualifier>`` form missed
# the canonical multi-point wording — "Cluster multi-spacecraft magnetopause",
# "multi-point Cluster timing", "Cluster C1 C2 C3 C4", "Cluster FGM" — silently
# dropping the target so the planner could not route to CDAWeb Cluster products.
# The patterns below also recognise the multi-point qualifier on either side of
# "Cluster", the C1-C4 spacecraft designators, and the core Cluster instrument
# acronyms. They stay conservative: a bare "cluster" or generic uses ("a cluster
# of substorms", "clustering algorithm") still do not match.
_QUALIFIED_MISSION_KEYWORDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsolo\s+(?:spacecraft|orbiter|mission|probe)\b", re.IGNORECASE), "Solar Orbiter"),
    # Bare "SolO" followed by an instrument acronym (MAG/SWA/EPD/RPW in-situ,
    # EUI/PHI/Metis/SoloHI/STIX remote-sensing) or a science term
    # (perihelion/periapsis/encounter) is the single most common way scientists
    # write Solar Orbiter goals, but the qualified pattern above only matched
    # solo + spacecraft/orbiter/mission/probe, dropping the target (T012). Anchored
    # to ``\bsolo\s+…`` so bare/generic "solo", "fly solo", "soloist" still do not
    # match. Mirrors the existing Cluster instrument-acronym branch below.
    (
        re.compile(
            r"\bsolo\s+(?:mag|swa|epd|rpw|eui|phi|metis|solohi|stix"
            r"|perihelion|periapsis|encounter)\b",
            re.IGNORECASE,
        ),
        "Solar Orbiter",
    ),
    (
        re.compile(
            r"\bcluster\s+(?:spacecraft|mission|constellation|satellites?"
            r"|multi[- ]?spacecraft|multi[- ]?point|four[- ]?spacecraft)\b",
            re.IGNORECASE,
        ),
        "Cluster",
    ),
    (
        re.compile(
            r"\b(?:multi[- ]?spacecraft|multi[- ]?point|four[- ]?spacecraft)\s+cluster\b",
            re.IGNORECASE,
        ),
        "Cluster",
    ),
    (
        re.compile(
            r"\bcluster\s+(?:c[1-4]\b|fgm|cis|peace|staff|whisper|edi|aspoc)",
            re.IGNORECASE,
        ),
        "Cluster",
    ),
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


def _wind_is_mission(lowered: str) -> bool:
    """Return ``True`` when bare ``wind`` refers to the Wind spacecraft.

    Guards against the plasma phrase ``"solar wind"`` / ``"solar-wind"`` and
    generic phrases like ``"wind speed"`` so a goal about the solar wind is not
    misread as the Wind spacecraft.
    """
    return bool(
        re.search(
            r"(?<![a-z0-9])(?<!solar )(?<!solar-)wind(?![a-z0-9])"
            r"(?!\s+(?:speed|velocity|direction|stream|streams|profile|data))",
            lowered,
        )
    )


def _extract_targets(text: str) -> list[str]:
    """Return all canonical mission/target labels inferred from ``text``.

    A multi-mission science goal ("compare ACE, Wind, and OMNI ...") names
    several spacecraft; surfacing only the first match silently drops the rest
    and breaks comparison workflows (T009). This returns every distinct mission
    mentioned, in first-appearance (text-position) order, de-duplicated.

    Matching is conservative and identical in spirit to ``_extract_target``:
    keywords match on word boundaries so a short token like ``ace`` does not fire
    inside ``"surface"``/``"space"``; bare ``wind`` only counts in spacecraft
    phrasing (see ``_wind_is_mission``); and spacecraft whose short names are
    everyday words (``solo``, ``cluster``) are only inferred from explicit
    phrasing (see ``_QUALIFIED_MISSION_KEYWORDS``).
    """
    lowered = text.lower()
    # Collect (position, label) so the result is ordered by first appearance.
    hits: list[tuple[int, str]] = []
    for pattern, label in _QUALIFIED_MISSION_KEYWORDS:
        match = pattern.search(text)
        if match is not None:
            hits.append((match.start(), label))
    for keyword, label in _MISSION_KEYWORDS:
        if keyword == "wind":
            match = re.search(
                r"(?<![a-z0-9])(?<!solar )(?<!solar-)wind(?![a-z0-9])"
                r"(?!\s+(?:speed|velocity|direction|stream|streams|profile|data))",
                lowered,
            )
            if match is not None:
                hits.append((match.start(), label))
            continue
        # Use the shared keyword matcher so numbered/lettered probe phrasing
        # ("MMS1", "rbspa", "themisa") is recognised in the list path exactly as
        # in the scalar ``_extract_target`` (Batch V T007 + T009 reconciliation).
        match = re.search(_mission_keyword_pattern(keyword), lowered)
        if match is not None:
            hits.append((match.start(), label))

    ordered: list[str] = []
    for _pos, label in sorted(hits, key=lambda item: item[0]):
        if label not in ordered:
            ordered.append(label)
    return ordered


def _extract_target(text: str) -> str | None:
    """Return a single canonical mission/target label inferred from ``text``.

    Back-compatible scalar wrapper: explicit, qualified spacecraft phrasing still
    takes precedence over plain keywords, then the first mission keyword in
    declaration order (matching the historical behaviour). Returns ``None`` when
    no mission is recognised. For multi-mission goals use ``_extract_targets``.

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
            if _wind_is_mission(lowered):
                return label
            continue
        if re.search(_mission_keyword_pattern(keyword), lowered):
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
    ``_parse_iso_instant``/``_parse_utc_date`` and silently dropped, so an
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


# --- Mission-aware canonical dataset / coverage / analysis guidance (issue #135) ---
#
# A compact, declarative mapping from a recognized mission (keyed by the same
# canonical label ``_MISSION_KEYWORDS`` emits) to the canonical CDAWeb dataset
# IDs a researcher would otherwise have to discover by hand. The shape is
# deliberately data-only so future missions are added by appending an entry, not
# by writing code: each instrument carries the dataset-ID *pattern* (with a
# ``{probe}`` placeholder for multi-spacecraft constellations), the standard
# coordinate frames the product publishes, and a one-line note. ``science_goals``
# lists keyword cues that make an instrument relevant; ``core`` instruments are
# always surfaced once the mission matches. ``coverage`` records the first date
# the mission's science products exist (``stop=None`` means ongoing) so the
# planner can validate a requested interval without any network I/O.
_MISSION_DATASET_PROFILES: dict[str, dict[str, Any]] = {
    "MMS": {
        # MMS flies four identical spacecraft (MMS1-4). A single-spacecraft goal
        # ("MMS1 ...") resolves to that probe; otherwise probe 1 leads and the
        # pattern documents the constellation so an agent can fan out to 2-4.
        "probes": ["1", "2", "3", "4"],
        "default_probe": "1",
        "coverage": {"start": "2015-09-01", "stop": None},
        "frame_note": (
            "MMS FGM and MEC publish both GSE and GSM; keep the field and "
            "position in the same frame when combining them (e.g. analyze the "
            "field in GSM if you place the crossing in GSM)."
        ),
        "instruments": [
            {
                "instrument": "FGM",
                "role": "magnetic field (survey)",
                "dataset_id_pattern": "MMS{probe}_FGM_SRVY_L2",
                "frames": ["GSE", "GSM"],
                "core": True,
                "note": "Vector B for the field-rotation signature; GSE and GSM both available.",
            },
            {
                "instrument": "FPI",
                "role": "ion 3D distribution (DIS) — in-kit moments/spectra input",
                "dataset_id_pattern": "MMS{probe}_FPI_FAST_L2_DIS-DIST",
                "frames": ["GSE"],
                "core": True,
                "note": (
                    "Ion 3D velocity distribution. This is the input the in-kit particle "
                    "tools need: feed it to build_particle_distribution_artifact("
                    "converter='mms_fpi') -> compute_particle_moments / "
                    "compute_particle_spectra (pitch-angle needs a magf/B-field input). "
                    "The DIS-MOMS product below is precomputed moments and is NOT a valid "
                    "distribution-artifact input."
                ),
            },
            {
                "instrument": "FPI",
                "role": "electron 3D distribution (DES) — in-kit moments/spectra input",
                "dataset_id_pattern": "MMS{probe}_FPI_FAST_L2_DES-DIST",
                "frames": ["GSE"],
                "core": True,
                "note": (
                    "Electron 3D velocity distribution; same bridge path as DIS-DIST "
                    "(converter='mms_fpi') -> compute_particle_moments / "
                    "compute_particle_spectra. NOT the precomputed DES-MOMS product."
                ),
            },
            {
                "instrument": "FPI",
                "role": "ion moments (DIS) — precomputed/published",
                "dataset_id_pattern": "MMS{probe}_FPI_FAST_L2_DIS-MOMS",
                "frames": ["GSE"],
                "core": True,
                "note": (
                    "Precomputed ion density/velocity/temperature for the plasma jump "
                    "across the boundary. Use directly if you only want published "
                    "moments; it is NOT a valid input to the in-kit particle tools "
                    "(those need the DIS-DIST 3D distribution above)."
                ),
            },
            {
                "instrument": "FPI",
                "role": "electron moments (DES) — precomputed/published",
                "dataset_id_pattern": "MMS{probe}_FPI_FAST_L2_DES-MOMS",
                "frames": ["GSE"],
                "core": True,
                "note": (
                    "Precomputed electron density/velocity/temperature; complements the "
                    "ion moments. Like DIS-MOMS, it is published moments — NOT a "
                    "distribution-artifact input (use DES-DIST for the in-kit tools)."
                ),
            },
            {
                "instrument": "MEC",
                "role": "ephemeris / position",
                "dataset_id_pattern": "MMS{probe}_MEC_SRVY_L2_EPHT89D",
                "frames": ["GSE", "GSM"],
                "core": True,
                "note": "Spacecraft position (and model field) for boundary context.",
            },
        ],
    },
}


# Downstream analysis steps the planner reasons about when the analysis layer is
# absent. MVA (minimum-variance analysis) and particle moments are the steps
# issue #135 calls out for the MMS magnetopause case; each names the in-kit tool
# and the PySPEDAS fallback an agent can run directly.
_ANALYSIS_STEP_GUIDANCE: list[dict[str, str]] = [
    {
        "analysis": "minimum variance analysis (MVA / LMN boundary normal)",
        "in_kit_tool": "analyze_minvar_coordinates",
        "pyspedas_fallback": "pyspedas.cotrans_tools.minvar",
    },
    {
        "analysis": "particle moments (density / velocity / temperature)",
        "in_kit_tool": "compute_particle_moments",
        "prerequisite": (
            "First build the distribution artifact (dist_file) from a *-DIST product, "
            "not *-MOMS: build_particle_distribution_artifact / "
            "load_particle_distribution_artifact (needs a mission *-DIST product, e.g. "
            "MMS{probe}_FPI_FAST_L2_DIS-DIST, plus a magf/B-field input). Supported "
            "converters: MMS FPI/HPCA + ERG. *-MOMS is precomputed and is not a valid input."
        ),
        "pyspedas_fallback": "pyspedas.particles.moments.moments_3d",
        "see_skill": "pitch-angle-distribution",
    },
    {
        "analysis": "particle spectra (energy / phi / theta / pitch-angle / PAD)",
        "in_kit_tool": "compute_particle_spectra",
        "prerequisite": (
            "Same distribution artifact as compute_particle_moments "
            "(build_particle_distribution_artifact from a *-DIST product). Pitch-angle / "
            "PAD spectra additionally require mag_file (a B-field reference) — "
            "spectrum_types=['pitch_angle'], mag_file=<B .npz>."
        ),
        "pyspedas_fallback": "pyspedas.particles.spd_pgs_make_*_spec (e_spec / phi_spec / theta_spec)",
        "see_skill": "pitch-angle-distribution / particle-velocity-slice",
    },
]


def _mva_analysis_available() -> bool:
    """Whether the optional analysis tools are registered by default.

    The planner must not over-promise MVA/moments availability: it uses the
    same full optional-backend dependency gate as the MCP server instead of
    probing only the MVA import path. Kept as a workflow-local wrapper so tests
    can still monkeypatch this planner signal directly.
    """
    return analysis_dependencies_available()


def _mission_profile_for(targets: list[str]) -> tuple[str, dict[str, Any]] | None:
    """Return the first ``(label, profile)`` whose mission is named in ``targets``.

    ``targets`` is the planner's resolved target list, which already includes any
    mission inferred from the goal text (e.g. ``"MMS"`` from "MMS1 ..."), so the
    lookup reuses that inference rather than re-parsing the goal.
    """
    for target in targets:
        profile = _MISSION_DATASET_PROFILES.get(target)
        if profile is not None:
            return target, profile
    return None


def _resolve_probe(targets: list[str], science_goal: str, profile: dict[str, Any]) -> str:
    """Pick the spacecraft probe token for a numbered constellation.

    Honors an explicit probe in the goal text (``MMS1`` -> ``"1"``) and otherwise
    falls back to the profile's ``default_probe``. Non-probe missions return an
    empty string, which leaves a bare ``{probe}``-free pattern unchanged.
    """
    probes = profile.get("probes")
    if not probes:
        return ""
    label_lower = next((t for t in targets if t in _MISSION_DATASET_PROFILES), "").lower()
    text = (science_goal or "").lower()
    for probe in probes:
        # Match the mission keyword immediately followed by the probe token, e.g.
        # "mms1"/"mms 1"; anchored so "mms14" does not read as probe 1.
        if re.search(rf"(?<![a-z0-9]){re.escape(label_lower)}\s*{re.escape(probe)}(?![a-z0-9])", text):
            return probe
    return profile.get("default_probe", probes[0])


def _coverage_status(start: str | None, stop: str | None, coverage: dict[str, Any]) -> dict[str, Any]:
    """Compare the requested interval against a mission's known coverage window.

    Returns a compact dict naming the mission coverage bounds and whether the
    requested ``[start, stop]`` falls inside them. ``status`` is one of
    ``ok``/``before_coverage``/``after_coverage``/``unknown`` (the last when the
    requested bounds are missing or unparseable), so the agent gets a clear signal
    without the planner having to fetch any dataset metadata.
    """
    cov_start, cov_stop = coverage.get("start"), coverage.get("stop")
    result: dict[str, Any] = {
        "mission_start": cov_start,
        "mission_stop": cov_stop,  # None == ongoing
    }
    start_dt = _parse_iso8601(start)
    cov_start_dt = _parse_iso8601(cov_start)
    cov_stop_dt = _parse_iso8601(cov_stop)
    if start_dt is None:
        result["interval_within_coverage"] = None
        result["status"] = "unknown"
        return result
    if cov_start_dt is not None and not _ge_safe(start_dt, cov_start_dt):
        result["interval_within_coverage"] = False
        result["status"] = "before_coverage"
        return result
    stop_dt = _parse_iso8601(stop) or start_dt
    if cov_stop_dt is not None and _ge_safe(stop_dt, cov_stop_dt):
        result["interval_within_coverage"] = False
        result["status"] = "after_coverage"
        return result
    result["interval_within_coverage"] = True
    result["status"] = "ok"
    return result


def _mission_dataset_candidates(
    targets: list[str],
    science_goal: str,
    start: str | None,
    stop: str | None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Build canonical dataset candidates + frame note for a recognized mission.

    Returns ``([], None)`` when no mapped mission is named, keeping generic
    planning lean and backward-compatible. Otherwise returns one candidate per
    relevant instrument (each carrying expanded per-probe dataset IDs, the
    constellation pattern, coverage status, frames, and a note) plus the
    mission-level frame-consistency note.
    """
    matched = _mission_profile_for(targets)
    if matched is None:
        return [], None
    label, profile = matched
    probe = _resolve_probe(targets, science_goal, profile)
    text = (science_goal or "").lower()
    coverage = profile.get("coverage", {})

    candidates: list[dict[str, Any]] = []
    for inst in profile["instruments"]:
        cues = inst.get("science_goals")
        if not inst.get("core") and cues and not any(cue in text for cue in cues):
            continue
        pattern = inst["dataset_id_pattern"]
        dataset_ids = [pattern.format(probe=probe)] if probe else [pattern]
        candidates.append({
            "mission": label,
            "instrument": inst["instrument"],
            "role": inst["role"],
            "dataset_id_pattern": pattern,
            "dataset_ids": dataset_ids,
            "frames": list(inst.get("frames", [])),
            "coverage": _coverage_status(start, stop, coverage),
            "note": inst.get("note", ""),
        })
    return candidates, profile.get("frame_note")


def _analysis_availability() -> dict[str, Any]:
    """Report whether the analysis layer is installed and the fallback if not."""
    available = _mva_analysis_available()
    info: dict[str, Any] = {
        "available": available,
        "downstream_steps": _ANALYSIS_STEP_GUIDANCE,
    }
    if available:
        info["guidance"] = (
            "Analysis layer present: MVA/moments steps can run via the in-kit "
            "analysis tools (e.g. analyze_minvar_coordinates, compute_particle_moments)."
        )
        info["fallback"] = None
    else:
        info["guidance"] = (
            "Analysis layer not detected in this install; the MVA/moments steps "
            "below are unavailable as MCP tools."
        )
        info["fallback"] = (
            "Install the optional analysis backend with "
            "pip install 'spedas-agent-kit[analysis]' (provides pyspedas), or run the "
            "listed pyspedas functions directly on the fetched CSV/CDF files."
        )
    return info


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
    # Every mission named in the goal, in first-appearance order. A multi-mission
    # comparison goal ("compare ACE, Wind, and OMNI ...") names several
    # spacecraft; surfacing only the first would silently drop Wind/OMNI and
    # break the comparison (T009). An explicit ``target`` is kept first below so
    # the scalar and the list always agree on element 0.
    inferred_targets: list[str] = _extract_targets(science_goal) if science_goal else []
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

    # Ensure an explicit target leads the list and is never duplicated, so
    # ``targets[0]`` and the scope ``target`` always agree.
    if target:
        targets = [target] + [m for m in inferred_targets if m != target]
    else:
        targets = list(inferred_targets)

    # Mission-aware enrichment (issue #135): once the target list is settled,
    # look up canonical dataset candidates, interval-vs-coverage status, and
    # frame guidance for any recognized mission. Empty for unmapped goals, so
    # generic planning is unchanged.
    mission_candidates, mission_frame_note = _mission_dataset_candidates(
        targets, science_goal, start, stop
    )
    analysis_availability = _analysis_availability()

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
            "targets": targets,
            "time_range": {"start": start, "stop": stop},
            "observables": _as_list(observables),
            "needs_user_input": needs_user_input,
            "invalid_sources": invalid_sources,
        }
    ]
    # Surface a mission-guidance phase only when a recognized mission gives us
    # canonical datasets to suggest; generic plans keep their original shape.
    if mission_candidates:
        steps.append({
            "phase": "mission_guidance",
            "rationale": (
                "Canonical dataset candidates for the recognized mission/instruments, "
                "with interval-vs-coverage status and frame guidance, so discovery can "
                "start from known IDs instead of an open browse."
            ),
            "dataset_candidates": mission_candidates,
            "frame_guidance": mission_frame_note,
            "analysis_availability": analysis_availability,
            "next_unified_calls": [
                {
                    "tool": "browse_data_parameters",
                    "args": {
                        "source_type": "cdaweb",
                        "dataset_id": mission_candidates[0]["dataset_ids"][0],
                    },
                },
            ],
        })
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
        "inferred_targets": targets,
        "invalid_sources": invalid_sources,
        "time_range_warning": time_range_warning,
        "mission_dataset_candidates": mission_candidates,
        "mission_frame_guidance": mission_frame_note,
        "analysis_availability": analysis_availability,
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
    """Create a lightweight file bundle for a SPEDAS Agent Kit analysis plan."""
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
            "SPEDAS Agent Kit analysis bundle scaffold.",
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
