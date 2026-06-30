from __future__ import annotations

import copy
import json
import re
from importlib import resources
from pathlib import Path

import pytest

from spedas_agent_kit.resources.provenance import (
    ALLOWED_RUN_STATUS,
    ALLOWED_STATUS_LABELS,
    REQUIRED_TOP_LEVEL_KEYS,
    load_provenance_schema,
    validate_reproduction_provenance,
)


def _valid_provenance() -> dict:
    """A minimal, shape-valid provenance record."""
    return {
        "paper": {"title": "Example", "doi": "10.0/x", "year": 2026},
        "target": {
            "science_question": "test",
            "figure_or_result": "fig 1",
            "status_label": "proxy",
        },
        "event_assumption": {
            "trange_utc": ["2018-11-05/00:00:00", "2018-11-07/00:00:00"],
            "mission": "PSP",
        },
        "data_plan": {
            "source_type": "cdaweb",
            "datasets_or_products": ["PSP_FLD_L2_MAG_RTN_1MIN"],
        },
        "environment": {"python": "3.11"},
        "status": "partial-success",
    }


def test_schema_resource_loads_and_is_valid_json() -> None:
    text = (
        resources.files("spedas_agent_kit.resources.schemas")
        .joinpath("reproduction_provenance.schema.json")
        .read_text(encoding="utf-8")
    )
    schema = json.loads(text)
    assert schema["title"] == "SPEDAS Agent Kit reproduction provenance"
    assert schema["type"] == "object"


def test_load_provenance_schema_matches_constants() -> None:
    schema = load_provenance_schema()
    # Required top-level keys must stay in lockstep with the validator constants.
    assert tuple(schema["required"]) == REQUIRED_TOP_LEVEL_KEYS
    # Status-label enum in the schema mirrors ALLOWED_STATUS_LABELS.
    label_enum = schema["properties"]["target"]["properties"]["status_label"]["enum"]
    assert tuple(label_enum) == ALLOWED_STATUS_LABELS
    status_enum = schema["properties"]["status"]["enum"]
    assert tuple(status_enum) == ALLOWED_RUN_STATUS


def test_validate_accepts_minimal_shape_valid_record() -> None:
    result = validate_reproduction_provenance(_valid_provenance())
    assert result == {"valid": True, "errors": []}


def test_validate_accepts_iso8601_utc_trange() -> None:
    record = _valid_provenance()
    record["event_assumption"]["trange_utc"] = [
        "2018-11-05T00:00:00Z",
        "2018-11-05T01:00:00+00:00",
    ]
    assert validate_reproduction_provenance(record) == {"valid": True, "errors": []}


def test_validate_rejects_missing_required_top_level_keys() -> None:
    record = _valid_provenance()
    del record["data_plan"]
    del record["environment"]
    result = validate_reproduction_provenance(record)
    assert result["valid"] is False
    missing = {e["field"] for e in result["errors"] if e["code"] == "missing_required_key"}
    assert {"data_plan", "environment"} <= missing


def test_validate_rejects_unknown_status_label() -> None:
    record = _valid_provenance()
    record["target"]["status_label"] = "totally_made_up"
    result = validate_reproduction_provenance(record)
    assert result["valid"] is False
    codes = {e["code"] for e in result["errors"]}
    assert "unknown_status_label" in codes


def test_validate_rejects_unknown_run_status() -> None:
    record = _valid_provenance()
    record["status"] = "kinda-worked"
    result = validate_reproduction_provenance(record)
    assert result["valid"] is False
    assert any(e["code"] == "unknown_run_status" for e in result["errors"])


@pytest.mark.parametrize(
    "bad_trange",
    [
        ["2018-11-05/00:00:00"],  # too short
        ["a", "b", "c"],  # too long
        ["", "2018-11-07/00:00:00"],  # empty start
        "2018-11-05/00:00:00",  # not a list
        [1, 2],  # not strings
        ["2018-13-05/00:00:00", "2018-11-07/00:00:00"],  # invalid date
        ["2018-11-07/00:00:00", "2018-11-05/00:00:00"],  # stop before start
        ["2018-11-05/00:00:00", "2018-11-05/00:00:00"],  # zero duration
    ],
)
def test_validate_rejects_malformed_trange(bad_trange) -> None:
    record = _valid_provenance()
    record["event_assumption"]["trange_utc"] = bad_trange
    result = validate_reproduction_provenance(record)
    assert result["valid"] is False
    assert any(e["code"] == "malformed_trange" for e in result["errors"])


def test_validate_rejects_non_object() -> None:
    result = validate_reproduction_provenance("not a dict")
    assert result["valid"] is False
    assert result["errors"][0]["code"] == "not_an_object"


def test_every_allowed_label_validates() -> None:
    for label in ALLOWED_STATUS_LABELS:
        record = _valid_provenance()
        record["target"]["status_label"] = label
        assert validate_reproduction_provenance(record)["valid"] is True
    for status in ALLOWED_RUN_STATUS:
        record = _valid_provenance()
        record["status"] = status
        assert validate_reproduction_provenance(record)["valid"] is True


def test_skill_md_template_labels_match_validator_constants() -> None:
    """Drift guard: the placeholder enums in the SKILL.md provenance template
    must stay in lockstep with the validator's allowed-label constants.

    The SKILL.md JSON block is a human-readable *template* whose ``status_label``
    and ``status`` values are pipe-separated legends (e.g.
    ``"paper_quality | proxy | candidate_interval | partial_success"``), not real
    instance values, so it is not expected to validate clean. Instead we parse
    those legends and assert they enumerate exactly the validator's allowed sets.
    """
    skill = (
        resources.files("spedas_agent_kit.resources")
        .joinpath("skills", "paper-reproduction", "SKILL.md")
        .read_text(encoding="utf-8")
    )
    match = re.search(r"```json\n(.*?)\n```", skill, re.S)
    assert match, "paper-reproduction SKILL.md must contain a fenced json template"
    template = json.loads(match.group(1))

    label_legend = template["target"]["status_label"]
    template_labels = tuple(part.strip() for part in label_legend.split("|"))
    assert template_labels == ALLOWED_STATUS_LABELS

    status_legend = template["status"]
    template_status = tuple(part.strip() for part in status_legend.split("|"))
    assert template_status == ALLOWED_RUN_STATUS

    # And all required top-level keys are present in the template.
    assert set(REQUIRED_TOP_LEVEL_KEYS) <= set(template.keys())


def test_validate_does_not_mutate_input() -> None:
    record = _valid_provenance()
    snapshot = copy.deepcopy(record)
    validate_reproduction_provenance(record)
    assert record == snapshot
