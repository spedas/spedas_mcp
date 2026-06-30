"""Packaged solar-wind event preset accessors.

The Agent Kit ships documentation-only event/paper preset seeds as a single
canonical JSON resource
(``resources/presets/solar_wind_event_presets.json``). This module loads that
JSON dependency-free and exposes a small accessor surface mirroring
``skill_catalog.py`` so thin wrappers and the MCP server can expose presets as
read-only MCP resources without baking 30+ event rows into source code.

Presets are *seeds*, not a curated event catalog. A preset's starting interval
is not a paper-quality endorsement; honest quality labels (``proxy``,
``cached_smoke``, ``route_scout``, ``metadata_unresolved`` …) and caveat notes
are preserved verbatim from the JSON. See the "Rules for using these seeds"
section in ``docs/examples/solar_wind_event_presets.md``.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from importlib import resources
from typing import Any

SPEDAS_PRESET_INDEX_URI = "spedas-preset://index"
SPEDAS_PRESET_URI_PREFIX = "spedas-preset://events/"

_PRESET_PACKAGE = "spedas_agent_kit.resources.presets"
_PRESET_FILE = "solar_wind_event_presets.json"


@dataclass(frozen=True)
class EventPreset:
    """One packaged solar-wind event preset seed."""

    id: str
    event: str
    doi: str | None
    trange_utc: list[str]
    data_route: str
    quality_labels: list[str]
    skills: list[str]
    notes: str
    companion_dois: list[str] = field(default_factory=list)
    resource_uri: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# Keys consumed directly into EventPreset fields; everything else on a record is
# preserved verbatim in ``extra`` so honesty-carrying fields (doi_status,
# trange_utc_narrow, …) survive the JSON conversion.
_KNOWN_RECORD_KEYS = {
    "id",
    "event",
    "doi",
    "trange_utc",
    "data_route",
    "quality_labels",
    "skills",
    "notes",
    "companion_dois",
}


def _preset_file() -> Any:
    return resources.files(_PRESET_PACKAGE).joinpath(_PRESET_FILE)


def _load_raw() -> dict[str, Any]:
    """Load and parse the canonical preset JSON document."""
    return json.loads(_preset_file().read_text(encoding="utf-8"))


def _to_preset(record: dict[str, Any]) -> EventPreset:
    preset_id = record["id"]
    extra = {k: v for k, v in record.items() if k not in _KNOWN_RECORD_KEYS}
    return EventPreset(
        id=preset_id,
        event=record.get("event", preset_id),
        doi=record.get("doi"),
        trange_utc=list(record.get("trange_utc", [])),
        data_route=record.get("data_route", ""),
        quality_labels=list(record.get("quality_labels", [])),
        skills=list(record.get("skills", [])),
        notes=record.get("notes", ""),
        companion_dois=list(record.get("companion_dois", [])),
        resource_uri=f"{SPEDAS_PRESET_URI_PREFIX}{preset_id}",
        extra=extra,
    )


def load_preset_document() -> dict[str, Any]:
    """Return the full preset JSON document (presets plus glossary/disclaimer)."""
    return _load_raw()


def list_event_presets() -> list[EventPreset]:
    """Return every packaged event preset, sorted by id."""
    document = _load_raw()
    presets = [_to_preset(record) for record in document.get("presets", [])]
    return sorted(presets, key=lambda item: item.id)


def get_event_preset(preset_id: str) -> EventPreset:
    """Return one preset by id.

    Raises ``KeyError`` for an unknown id and rejects path-traversal-ish ids the
    same way ``skill_catalog._skill_path`` guards skill names, so a preset id can
    safely be used to build a resource URI / file lookup.
    """
    if (
        not preset_id
        or "/" in preset_id
        or "\\" in preset_id
        or preset_id in {".", ".."}
    ):
        raise KeyError(preset_id)
    for preset in list_event_presets():
        if preset.id == preset_id:
            return preset
    raise KeyError(preset_id)


def render_event_preset_index_markdown() -> str:
    """Render a compact MCP-resource index for the packaged event presets."""
    presets = list_event_presets()
    document = _load_raw()
    lines = [
        "# SPEDAS Agent Kit solar-wind event presets",
        "",
        (
            "These documentation-only preset seeds ship inside `spedas_agent_kit` "
            "and are exposed by the MCP server as read-only resources. Use "
            "`list_resources` to discover them and `read_resource` on the "
            "individual URI to load one preset as JSON."
        ),
        "",
        (
            "Presets are seeds, not a curated catalog. A starting interval is not a "
            "paper-quality endorsement; honor the per-preset `quality_labels` and "
            "`notes`. See docs/examples/solar_wind_event_presets.md for the rules."
        ),
        "",
        f"Preset count: {len(presets)}",
        "",
    ]
    for preset in presets:
        labels = ", ".join(preset.quality_labels) or "(none)"
        lines.append(
            f"- `{preset.id}` — `{preset.resource_uri}` — {preset.event} "
            f"[{labels}]"
        )
    lines.append("")
    disclaimer = document.get("disclaimer")
    if disclaimer:
        lines.append(f"> {disclaimer}")
        lines.append("")
    return "\n".join(lines)


def render_event_preset_json(preset_id: str) -> str:
    """Render one preset as a stable JSON string for an MCP resource read."""
    preset = get_event_preset(preset_id)
    payload: dict[str, Any] = {
        "id": preset.id,
        "event": preset.event,
        "doi": preset.doi,
        "companion_dois": preset.companion_dois,
        "trange_utc": preset.trange_utc,
        "data_route": preset.data_route,
        "quality_labels": preset.quality_labels,
        "skills": preset.skills,
        "notes": preset.notes,
    }
    payload.update(preset.extra)
    return json.dumps(payload, indent=2, sort_keys=False)
