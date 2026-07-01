from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_agent_kit_integration_workflow_doc_names_runtime_contract():
    text = (ROOT / "docs/examples/agent_kit_integration_workflow.md").read_text(
        encoding="utf-8"
    )

    required = [
        "MCP layer",
        "Skill layer",
        "Runtime adapter layer",
        "spedas-skill://index",
        "spedas-skill://skills/<skill-name>",
        "search_spedas_data_sources",
        "plan_spedas_observation",
        "create_spedas_analysis_bundle",
        "fetch_data_product",
        "artifact/provenance summary",
        "spedas-preset://schemas/analysis_bundle_run",
        "tool_calls",
        "artifacts",
        "caveats",
        "source_tool",
    ]
    for phrase in required:
        assert phrase in text


def test_shared_skills_readme_points_to_integration_workflow():
    text = (ROOT / "src/spedas_agent_kit/resources/skills/README.md").read_text(
        encoding="utf-8"
    )

    assert "agent_kit_integration_workflow.md" in text
    assert "spedas-skill://index" in text
    assert "search/plan -> browse/load/parameters -> bundle -> fetch/compute" in text
