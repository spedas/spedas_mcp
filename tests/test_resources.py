from __future__ import annotations

from importlib import resources


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
