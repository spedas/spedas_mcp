from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_multi_spacecraft_gradients_skill_is_indexed_and_backend_shapes_are_documented():
    skill = ROOT / "plugins/spedas-claude/skills/multi-spacecraft-gradients/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "name: multi-spacecraft-gradients" in text
    assert "pyspedas.projects.mms.mms_curl" in text
    assert "pyspedas.lingradest" in text
    assert "pyspedas.find_magnetic_nulls_fote" in text
    assert "pyspedas.classify_null_type" in text
    for expected in ["jtotal", "divB", "curlB", "Rbary", "LCxB", "LD", "null_fom", "null_typecode"]:
        assert expected in text
    assert "GSE" in text
    assert "tetrahedron" in text.lower()

    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    assert "multi-spacecraft-gradients" in index

def test_claude_plugin_skills_match_packaged_resource_copies():
    """Keep the editable Claude plugin skills in sync with the packaged copies.

    The wheel ships src/spedas_agent_kit/resources/skills, while the repo also
    keeps a Claude-plugin copy under plugins/spedas-claude/skills. A researcher
    may read either surface, so doc fixes must land in both trees.
    """
    plugin_root = ROOT / "plugins/spedas-claude/skills"
    resource_root = ROOT / "src/spedas_agent_kit/resources/skills"

    plugin_skills = sorted(p.name for p in plugin_root.iterdir() if p.is_dir())
    resource_skills = sorted(p.name for p in resource_root.iterdir() if p.is_dir())
    assert plugin_skills == resource_skills

    mismatches = []
    for name in plugin_skills:
        plugin = plugin_root / name / "SKILL.md"
        resource = resource_root / name / "SKILL.md"
        if plugin.read_text(encoding="utf-8") != resource.read_text(encoding="utf-8"):
            mismatches.append(name)

    assert not mismatches, "Skill copies differ: " + ", ".join(mismatches)


def test_solar_wind_turbulence_intermittency_skill_is_indexed():
    skill = ROOT / "plugins/spedas-claude/skills/solar-wind-turbulence-intermittency/SKILL.md"
    text = skill.read_text(encoding="utf-8")
    assert "name: solar-wind-turbulence-intermittency" in text
    assert "PVI" in text
    assert "third-order" in text
    assert "event table" in text

    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    assert "solar-wind-turbulence-intermittency" in index


def test_batch004_multispacecraft_guardrails_are_indexed():
    psp = (ROOT / "plugins/spedas-claude/skills/psp-solar-wind-switchbacks/SKILL.md").read_text(encoding="utf-8")
    storm = (ROOT / "plugins/spedas-claude/skills/solar-wind-icme-storm/SKILL.md").read_text(encoding="utf-8")
    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    assert "rtn-normal" in psp
    assert "spice-conjunction-finder" in psp
    assert "BX_GSE" in storm and "BY_GSE" in storm and "BZ_GSE" in storm
    assert "8hz" in storm and "1min" in storm
    assert "Solar Orbiter" in index
    assert "scalar OMNI vectors" in index



def test_batch005_themis_rbsp_guardrails_are_indexed():
    overview = (ROOT / "plugins/spedas-claude/skills/overview-geomagnetic-indices/SKILL.md").read_text(encoding="utf-8")
    wave = (ROOT / "plugins/spedas-claude/skills/wave-polarization/SKILL.md").read_text(encoding="utf-8")
    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    presets = (ROOT / "docs/examples/solar_wind_event_presets.md").read_text(encoding="utf-8")

    assert "THEMIS ESA availability" in overview
    assert "FEDU_mageis" in overview and "FEDU_rept" in overview
    assert "EMFISIS" in overview and "HOPE" in overview
    assert "THEMIS SCM Batch 005 guardrail" in wave
    assert "thc_scw_gse" in wave and "thc_scf_gse" in wave
    assert "THEMIS FGM/ESA substorm/dipolarization proxy" in index
    assert "THEMIS SCM `scf`/`scp`/`scw` valid-window checks" in index
    for expected in [
        "10.1126/science.1160495",
        "10.1029/2009GL038980",
        "10.1029/2007GL032009",
        "10.1126/science.1233518",
        "10.1126/science.1237743",
    ]:
        assert expected in presets


def test_batch006_mms_reconnection_guardrails_are_indexed():
    workflow = (ROOT / "plugins/spedas-claude/skills/spedas-workflow/SKILL.md").read_text(encoding="utf-8")
    doc = (ROOT / "docs/examples/mms_magnetopause_workflow.md").read_text(encoding="utf-8")
    presets = (ROOT / "docs/examples/solar_wind_event_presets.md").read_text(encoding="utf-8")

    assert "MMS reconnection events (Batch 006 guardrail)" in workflow
    assert "analyze_minvar_coordinates" in workflow
    assert "pitch_angle" in workflow
    assert "transparent proxy" in workflow
    assert "availability_failure" in workflow

    assert "Batch 006 MMS derived-diagnostics guardrail" in doc
    assert "transform_timeseries_coordinates" in doc
    assert "single-spacecraft moment current" in doc
    assert "curlometer current" in doc
    assert "availability_failure" in doc

    for expected in [
        "10.1002/2016GL068613",
        "10.1002/2016GL069064",
        "10.1002/2016GL068359",
        "10.1038/nature26178",
        "10.1126/science.aat2998",
    ]:
        assert expected in presets
    assert "MMS asymmetric magnetopause electron-current/heating proxy" in presets
    assert "MMS electron-only reconnection availability scout" in presets
    assert "availability_failure" in presets



def test_batch007_stereo_icme_sep_guardrails_are_indexed():
    workflow = (ROOT / "plugins/spedas-claude/skills/spedas-workflow/SKILL.md").read_text(encoding="utf-8")
    storm = (ROOT / "plugins/spedas-claude/skills/solar-wind-icme-storm/SKILL.md").read_text(encoding="utf-8")
    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    doc = (ROOT / "docs/examples/stereo_icme_multispacecraft.md").read_text(encoding="utf-8")
    presets = (ROOT / "docs/examples/solar_wind_event_presets.md").read_text(encoding="utf-8")

    assert "Heliospheric ICME/SEP multi-spacecraft events (Batch 007 guardrail)" in workflow
    assert "reduced_sep_proxy" in workflow
    assert "SECCHI/HI J-map" in workflow

    assert "Batch-007 heliospheric ICME / SEP guardrails" in storm
    assert "STEREO MAG `1min` plus PLASTIC" in storm
    assert "telescope, species, energy band" in storm
    assert "docs/examples/stereo_icme_multispacecraft.md" in storm

    assert "SEP reduced proxy" in index
    assert "channel metadata" in index

    for expected in [
        "10.5194/angeo-27-4491-2009",
        "10.1007/s11207-009-9360-7",
        "10.1029/2001GL014136",
        "10.1007/s11207-012-0049-y",
    ]:
        assert expected in doc
        assert expected in presets
    assert "DOI unresolved in Batch 007" in doc
    assert "metadata_unresolved" in presets
    assert "HI/J-map" in doc
