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
        "solar-wind-turbulence-intermittency",
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
    assert "Horbury" in psp and "Chhiber" in psp
    assert "interval_quality" in psp
    assert "rtn-normal" in psp
    assert "spice-conjunction-finder" in psp
    assert "name: solar-wind-icme-storm" in storm
    assert "AE_INDEX" in storm
    assert "BX_GSE" in storm and "BZ_GSE" in storm
    assert "8hz" in storm and "1min" in storm
    assert "STEREO" in storm

    index = read_packaged_skill("spedas-skills-index")
    assert "psp-solar-wind-switchbacks" in index
    assert "solar-wind-icme-storm" in index

def test_solar_wind_event_presets_include_psp_batch003_seeds() -> None:
    from pathlib import Path

    # The docs file is not a packaged resource; resolve from repository layout for
    # regression coverage in source checkouts.
    text = (Path(__file__).resolve().parents[1] / "docs/examples/solar_wind_event_presets.md").read_text(encoding="utf-8")
    assert "10.3847/1538-4365/ab5b15" in text
    assert "10.3847/1538-4365/ab53d2" in text
    assert "10.3847/1538-4365/ab60a3" in text
    assert "10.3847/1538-4365/ab5dae" in text
    assert "10.3847/1538-4365/ab4da7" in text
    assert "representative_proxy" in text
    assert "cached_smoke" in text


def test_solar_wind_turbulence_intermittency_skill_is_packaged_and_indexed() -> None:
    skill = read_packaged_skill("solar-wind-turbulence-intermittency")
    assert "name: solar-wind-turbulence-intermittency" in skill
    assert "PVI" in skill
    assert "third-order" in skill
    assert "event table" in skill

    index = read_packaged_skill("spedas-skills-index")
    assert "solar-wind-turbulence-intermittency" in index


def test_provenance_schema_and_presets_are_packaged_resources() -> None:
    schema = resources.files("spedas_agent_kit.resources").joinpath(
        "schemas", "reproduction_provenance.schema.json"
    )
    assert schema.is_file()
    analysis_run_schema = resources.files("spedas_agent_kit.resources").joinpath(
        "schemas", "analysis_bundle_run.schema.json"
    )
    assert analysis_run_schema.is_file()
    presets = resources.files("spedas_agent_kit.resources").joinpath(
        "presets", "solar_wind_event_presets.json"
    )
    assert presets.is_file()


def test_multispacecraft_insitu_example_documents_batch004_routes() -> None:
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "docs/examples/stereo_psp_solo_multispacecraft_insitu.md").read_text(encoding="utf-8")
    assert "B_RTN" in text
    assert "BX_GSE" in text and "BZ_GSE" in text
    assert "1min" in text
    assert "spice-conjunction-finder" in text


def test_batch001_foundation_skills_are_rendered_as_resources() -> None:
    index = render_skill_index_markdown()
    for skill_name in [
        "pyspedas-load-planning",
        "tplot-data-lifecycle",
        "spedas-heritage-vocabulary",
    ]:
        assert f"{SPEDAS_SKILL_URI_PREFIX}{skill_name}" in index
        assert read_packaged_skill(skill_name).startswith("---\nname: ")

def test_batch002_omni_kyoto_noaa_skill_is_packaged_and_indexed() -> None:
    skill_name = "omni-kyoto-noaa-smoke-workflows"
    skill = read_packaged_skill(skill_name)
    index = read_packaged_skill("spedas-skills-index")
    rendered = render_skill_index_markdown()

    assert f"{SPEDAS_SKILL_URI_PREFIX}{skill_name}" in rendered
    assert skill_name in index
    for expected in [
        "OMNI_HRO_1MIN",
        "OMNI2_H0_MRG1HR",
        "pyspedas.projects.kyoto.dst",
        "pyspedas.projects.noaa.noaa_load_kp",
        "external_runtime_route.not_an_mcp_tool: true",
        "downloadonly=True",
        "notplot=True",
        "no_update=True",
        "route_scout",
    ]:
        assert expected in skill
