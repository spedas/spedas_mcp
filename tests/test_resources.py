from __future__ import annotations

from importlib import resources

import pytest

from spedas_agent_kit.resources.skill_catalog import (
    SPEDAS_SKILL_INDEX_URI,
    SPEDAS_SKILL_URI_PREFIX,
    list_packaged_skills,
    read_packaged_skill,
    render_skill_index_markdown,
)


def test_shared_skills_are_packaged_with_agent_kit() -> None:
    skill = resources.files("spedas_agent_kit.resources").joinpath(
        "skills", "spedas-workflow", "SKILL.md"
    )
    text = skill.read_text(encoding="utf-8")
    assert "name: spedas-workflow" in text
    assert "SPEDAS Agent Kit workflow" in text


def test_renamed_anatomy_skill_is_packaged_with_agent_kit() -> None:
    skill = resources.files("spedas_agent_kit.resources").joinpath(
        "skills", "spedas-agent-kit-anatomy", "SKILL.md"
    )
    text = skill.read_text(encoding="utf-8")
    assert "name: spedas-agent-kit-anatomy" in text
    assert "spedas_agent_kit repo" in text


def test_packaged_skill_catalog_lists_research_skill_resources() -> None:
    skills = list_packaged_skills()
    names = {skill.name for skill in skills}
    assert len(skills) >= 22
    assert {
        "spedas-workflow",
        "spedas-skills-index",
        "overview-geomagnetic-indices",
        "wave-polarization",
        "particle-velocity-slice",
        "paper-reproduction",
        "psp-solar-wind-switchbacks",
        "solar-wind-icme-storm",
    } <= names
    assert all(skill.resource_uri == f"{SPEDAS_SKILL_URI_PREFIX}{skill.name}" for skill in skills)
    assert all(skill.description for skill in skills)


def test_packaged_skill_index_markdown_points_to_resource_uris() -> None:
    index = render_skill_index_markdown()
    assert "# SPEDAS Agent Kit packaged skills" in index
    assert SPEDAS_SKILL_INDEX_URI == "spedas-skill://index"
    assert "spedas-skill://skills/spedas-workflow" in index
    assert "spedas-skill://skills/wave-polarization" in index
    assert "spedas-skill://skills/paper-reproduction" in index
    assert "spedas-skill://skills/psp-solar-wind-switchbacks" in index
    assert "spedas-skill://skills/solar-wind-icme-storm" in index


def test_paper_reproduction_skill_is_packaged_with_provenance_template() -> None:
    text = read_packaged_skill("paper-reproduction")
    assert "name: paper-reproduction" in text
    assert "Minimal provenance schema" in text
    assert "paper_quality | proxy | candidate_interval | partial_success" in text
    assert "Agent Kit feedback" in text


def test_read_packaged_skill_by_name_and_reject_path_traversal() -> None:
    text = read_packaged_skill("spedas-workflow")
    assert "name: spedas-workflow" in text
    assert "SPEDAS Agent Kit workflow" in text
    with pytest.raises(KeyError):
        read_packaged_skill("../spedas-workflow")


def test_solar_wind_paper_reproduction_skills_are_packaged_and_indexed() -> None:
    psp = read_packaged_skill("psp-solar-wind-switchbacks")
    storm = read_packaged_skill("solar-wind-icme-storm")
    assert "name: psp-solar-wind-switchbacks" in psp
    assert "deflection angle" in psp
    assert "Bale" in psp and "Dudok de Wit" in psp
    assert "name: solar-wind-icme-storm" in storm
    assert "AE_INDEX" in storm
    assert "STEREO" in storm

    index = read_packaged_skill("spedas-skills-index")
    assert "psp-solar-wind-switchbacks" in index
    assert "solar-wind-icme-storm" in index
