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
