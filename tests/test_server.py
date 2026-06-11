"""Tests for the unified SPEDAS MCP facade."""
import asyncio
import json

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
    assert "cdaweb" in data["capability_groups"]
    assert "pds" in data["capability_groups"]
    assert "spice" in data["capability_groups"]


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
