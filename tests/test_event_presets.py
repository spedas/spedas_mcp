from __future__ import annotations

import json
import re
from importlib import resources
from pathlib import Path

import pytest

from spedas_agent_kit.resources.event_presets import (
    SPEDAS_PRESET_INDEX_URI,
    SPEDAS_PRESET_URI_PREFIX,
    EventPreset,
    get_event_preset,
    list_event_presets,
    load_preset_document,
    render_event_preset_index_markdown,
    render_event_preset_json,
)

# Allowed quality labels: the four documented status labels plus the honest
# proxy/scout/caveat labels carried over from the Markdown table. The test
# asserts every label in the JSON is in this documented set so a typo or a new
# silent label cannot slip in.
_ALLOWED_QUALITY_LABELS = {
    "paper_quality",
    "proxy",
    "candidate_interval",
    "partial_success",
    "representative_proxy",
    "cached_smoke",
    "reduced_sep_proxy",
    "availability_failure",
    "metadata_unresolved",
    "single_spacecraft_cis",
    "fgm_route_empty",
    "scouting",
    "not_paper_exact",
    "route_scout",
}

_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s`;]+")


def _markdown_text() -> str:
    return (
        Path(__file__).resolve().parents[1]
        / "docs/examples/solar_wind_event_presets.md"
    ).read_text(encoding="utf-8")


def test_preset_json_resource_loads_and_is_valid_json() -> None:
    text = (
        resources.files("spedas_agent_kit.resources.presets")
        .joinpath("solar_wind_event_presets.json")
        .read_text(encoding="utf-8")
    )
    document = json.loads(text)
    assert document["kind"] == "solar_wind_event_preset_seeds"
    assert isinstance(document["presets"], list)


def test_list_event_presets_returns_all_rows_with_required_fields() -> None:
    presets = list_event_presets()
    # The Markdown table currently carries 30 seed rows.
    assert len(presets) >= 30
    ids = [p.id for p in presets]
    assert len(ids) == len(set(ids)), "preset ids must be unique"
    for preset in presets:
        assert isinstance(preset, EventPreset)
        assert preset.id
        assert preset.event
        assert preset.data_route, f"{preset.id} has empty data_route"
        assert preset.quality_labels, f"{preset.id} has no quality labels"
        assert len(preset.trange_utc) == 2
        assert preset.resource_uri == f"{SPEDAS_PRESET_URI_PREFIX}{preset.id}"


def test_quality_labels_are_from_documented_set() -> None:
    for preset in list_event_presets():
        for label in preset.quality_labels:
            assert label in _ALLOWED_QUALITY_LABELS, (
                f"{preset.id} carries undocumented quality label {label!r}"
            )


def test_get_event_preset_roundtrips_and_rejects_unknown_and_traversal() -> None:
    preset = list_event_presets()[0]
    assert get_event_preset(preset.id).id == preset.id
    with pytest.raises(KeyError):
        get_event_preset("no-such-preset")
    with pytest.raises(KeyError):
        get_event_preset("../solar_wind_event_presets")
    with pytest.raises(KeyError):
        get_event_preset("")


def test_unresolved_doi_and_companion_doi_survive_conversion() -> None:
    by_id = {p.id: p for p in list_event_presets()}
    lugaz = by_id["stereo-2010-aug-cme-cme-interaction-insitu-proxy-lugaz-temmer"]
    assert lugaz.doi is None
    assert "metadata_unresolved" in lugaz.quality_labels
    assert lugaz.extra.get("doi_status")  # honesty flag preserved

    stpat = by_id["st-patricks-day-2015-storm-context-ionosphere-perturbation"]
    assert "10.31401/ws.2024.proc.10" in stpat.companion_dois


def test_smoke_and_route_scout_caveats_preserved() -> None:
    by_id = {p.id: p for p in list_event_presets()}
    horbury = by_id["psp-e1-horbury-2020-sharp-alfvenic-impulses"]
    assert "representative_proxy" in horbury.quality_labels
    assert "smoke" in horbury.notes.lower()

    chhiber = by_id["psp-e1-chhiber-2020-pvi-intermittent-structures"]
    assert "cached_smoke" in chhiber.quality_labels

    goes = by_id["september-2017-storm-goes-xrs-gic-driver-route-scout"]
    assert goes.quality_labels == ["route_scout"]


def test_doi_drift_guard_json_to_markdown() -> None:
    """Every DOI present in the JSON appears in the Markdown mirror."""
    markdown = _markdown_text()
    for preset in list_event_presets():
        for doi in [preset.doi, *preset.companion_dois]:
            if doi:
                assert doi in markdown, f"DOI {doi} ({preset.id}) missing from Markdown"


def test_doi_drift_guard_markdown_to_json() -> None:
    """Every resolved DOI in the Markdown appears in the JSON (the one
    'DOI unresolved' row has no DOI and is represented as null in JSON)."""
    markdown = _markdown_text()
    json_dois = set()
    for preset in list_event_presets():
        if preset.doi:
            json_dois.add(preset.doi)
        json_dois.update(preset.companion_dois)
    # Only scan table rows (lines starting with '|') so prose/example DOIs do not
    # produce false positives.
    for line in markdown.splitlines():
        if not line.startswith("|"):
            continue
        for doi in _DOI_RE.findall(line):
            doi = doi.rstrip("`;.,")
            assert doi in json_dois, f"DOI {doi} in Markdown table missing from JSON"


def test_index_markdown_lists_preset_resource_uris() -> None:
    index = render_event_preset_index_markdown()
    assert "# SPEDAS Agent Kit solar-wind event presets" in index
    assert SPEDAS_PRESET_INDEX_URI == "spedas-preset://index"
    presets = list_event_presets()
    assert f"Preset count: {len(presets)}" in index
    assert presets[0].resource_uri in index
    # The seeds-are-not-a-catalog disclaimer is surfaced.
    assert "seeds, not a curated catalog" in index


def test_render_event_preset_json_roundtrips() -> None:
    preset = list_event_presets()[0]
    payload = json.loads(render_event_preset_json(preset.id))
    assert payload["id"] == preset.id
    assert payload["quality_labels"] == preset.quality_labels
    assert payload["data_route"] == preset.data_route


def test_load_preset_document_exposes_glossary_and_disclaimer() -> None:
    document = load_preset_document()
    assert "quality_label_glossary" in document
    assert document["disclaimer"]
