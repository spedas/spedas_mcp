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
