"""Tests for the unified SPEDAS MCP facade."""
import asyncio
import json
from pathlib import Path

from spedas_mcp import __version__
from spedas_mcp.server import create_server


def _call_tool(server, name, args=None):
    args = args or {}
    content, _metadata = asyncio.run(server.call_tool(name, args))
    # FastMCP returns (content_blocks, metadata); tests only need the first text block.
    return content[0].text


def test_version():
    assert __version__ == "0.1.0"


def test_server_has_expected_tools():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert {
        "spedas_overview",
        "browse_data_sources",
        "load_data_source",
        "browse_data_parameters",
        "fetch_data_product",
        "manage_data_cache",
        "search_spedas_data_sources",
        "plan_spedas_observation",
        "compare_cdaweb_pds_spice",
        "create_spedas_analysis_bundle",
        "browse_observatories",
        "load_observatory",
        "browse_parameters",
        "fetch_data",
        "manage_cdaweb_cache",
        "browse_pds_missions",
        "load_pds_mission",
        "browse_pds_parameters",
        "fetch_pds_data",
        "manage_pds_cache",
        "list_spice_missions",
        "get_ephemeris",
        "compute_distance",
        "transform_coordinates",
        "list_coordinate_frames",
        "manage_spice_kernels",
    } <= names


def test_overview_is_compact_json():
    server = create_server()
    data = json.loads(_call_tool(server, "spedas_overview"))
    assert data["status"] == "success"
    assert "data" in data["capability_groups"]
    assert "science_workflows" in data["capability_groups"]
    assert "geometry" in data["capability_groups"]
    assert "compatibility_low_level" in data["capability_groups"]


def test_browse_data_sources_lists_spedas_source_categories():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "all"}))
    assert data["status"] == "success"
    assert data["data_layer"] == "spedas"
    assert {entry["source_type"] for entry in data["source_types"]} == {"cdaweb", "pds", "spice"}


def test_fetch_data_product_rejects_spice_measurement_fetch():
    server = create_server()
    data = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "spice",
        "dataset_id": "juno",
        "parameters": ["ephemeris"],
    }))
    assert data["status"] == "error"
    assert data["source_type"] == "spice"
    assert "get_ephemeris" in data["recommended_tools"]


def test_search_spedas_data_sources_recommends_mixed_planetary_sources():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Study Juno magnetic field measurements near Jupiter and add spacecraft geometry context",
        "target": "Jupiter",
        "observables": ["magnetic field", "spacecraft position"],
    }))
    assert data["status"] == "success"
    assert "pds" in data["recommended_sources"]
    assert "spice" in data["recommended_sources"]


def test_plan_spedas_observation_returns_source_specific_steps():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Compare solar wind plasma and spacecraft geometry during an Earth bow shock interval",
        "target": "Earth bow shock",
        "start": "2020-01-01T00:00:00Z",
        "stop": "2020-01-01T01:00:00Z",
        "observables": ["plasma", "magnetic field", "position"],
    }))
    assert data["status"] == "success"
    assert "cdaweb" in data["recommended_sources"]
    assert any(step["phase"] == "preserve_provenance" for step in data["plan"])


def test_juno_pds_spice_plan_uses_requested_planetary_sources():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Juno Jupiter magnetic-field workflow combining PDS measurement discovery with SPICE geometry planning",
        "target": "Jupiter",
        "start": "2016-08-27T00:00:00Z",
        "stop": "2016-08-28T00:00:00Z",
        "observables": ["magnetic field", "spacecraft position"],
        "data_sources": ["pds", "spice"],
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["pds", "spice"]
    assert {"discover_pds", "discover_spice", "preserve_provenance"} <= {
        step["phase"] for step in data["plan"]
    }


def test_create_spedas_analysis_bundle_writes_plan_files(tmp_path: Path):
    server = create_server()
    data = json.loads(_call_tool(server, "create_spedas_analysis_bundle", {
        "study_name": "Juno Jupiter geometry test",
        "output_dir": str(tmp_path),
        "science_goal": "Plan a Juno magnetic field and geometry study",
        "target": "Jupiter",
        "data_sources": ["pds", "spice"],
    }))
    assert data["status"] == "success"
    assert Path(data["paths"]["readme"]).exists()
    assert Path(data["paths"]["request_plan"]).exists()
    assert data["recommended_sources"] == ["pds", "spice"]


def test_browse_observatories_uses_cdaweb_catalog():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_observatories"))
    assert isinstance(data, list)
    assert any(obs.get("id") == "ace" for obs in data)


def test_list_spice_missions_uses_xhelio_spice_registry():
    server = create_server()
    data = json.loads(_call_tool(server, "list_spice_missions"))
    assert isinstance(data, list)
    assert any(mission.get("mission_key") == "PSP" for mission in data)


def test_browse_pds_missions_uses_xhelio_pds_catalog():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_pds_missions"))
    assert isinstance(data, list)
    assert any(mission.get("id") == "JUNO_PPI" for mission in data)


def test_browse_pds_parameters_uses_bundled_metadata():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_pds_parameters", {"dataset_id": "pds3:JNO-J-3-FGM-CAL-V1.0:DATA"}))
    assert data["status"] == "success"
    assert data.get("dataset_id") == "pds3:JNO-J-3-FGM-CAL-V1.0:DATA"
    assert data.get("parameters")

def test_unified_pds_source_ids_round_trip_from_browse_to_load():
    server = create_server()
    browsed = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "pds", "query": "cassini"}))
    mission_id = browsed["payload"][0]["id"]
    assert mission_id.endswith("_PPI")

    loaded = json.loads(_call_tool(server, "load_data_source", {"source_type": "pds", "source_id": mission_id}))
    assert loaded["status"] == "success"
    assert loaded["normalized_source_id"] == mission_id.removesuffix("_PPI").lower()


def test_unified_spice_load_and_parameter_browse_do_not_pass_mission_kwarg():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": "PSP"}))
    assert loaded["status"] == "success"
    assert loaded["payload"]

    params = json.loads(_call_tool(server, "browse_data_parameters", {"source_type": "spice", "dataset_id": "PSP"}))
    assert params["status"] == "success"
    assert params["payload"]


def test_unified_pds_fetch_rejects_unsupported_limit_cleanly(tmp_path: Path):
    server = create_server()
    data = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "pds",
        "dataset_id": "pds3:JNO-J-3-FGM-CAL-V1.0:DATA",
        "parameters": ["BX"],
        "start": "2016-07-01T00:00:00Z",
        "stop": "2016-07-01T00:01:00Z",
        "output_dir": str(tmp_path),
        "limit": 1,
    }))
    assert data["status"] == "error"
    assert data["unsupported_argument"] == "limit"


def test_unified_cache_manager_does_not_forward_cache_dir_kwarg():
    server = create_server()
    data = json.loads(_call_tool(server, "manage_data_cache", {"source_type": "spice", "action": "status", "cache_dir": "/tmp/ignored"}))
    assert data["status"] == "success"
    assert data["note"]


def test_plan_spedas_observation_reports_invalid_sources_and_missing_time():
    server = create_server()
    invalid = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "test",
        "data_sources": ["madeup"],
    }))
    assert invalid["status"] == "error"
    assert invalid["invalid_sources"] == ["madeup"]

    missing_time = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "test",
        "data_sources": ["cdaweb"],
    }))
    assert missing_time["status"] == "needs_input"
    assert set(missing_time["needs_user_input"]) == {"start", "stop"}
