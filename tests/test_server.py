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
        "transform_timeseries_coordinates",
        "generate_fac_matrix",
        "analyze_minvar_coordinates",
    } <= names


def test_overview_is_compact_json():
    server = create_server()
    data = json.loads(_call_tool(server, "spedas_overview"))
    assert data["status"] == "success"
    assert "data" in data["capability_groups"]
    assert "science_workflows" in data["capability_groups"]
    assert "geometry" in data["capability_groups"]
    assert "compatibility_low_level" in data["capability_groups"]



def test_tool_descriptions_mark_primary_and_compatibility_surfaces():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    descriptions = {tool.name: tool.description for tool in tools}
    assert descriptions["browse_data_sources"].startswith("Primary data layer")
    assert descriptions["fetch_data_product"].startswith("Primary data layer")
    assert descriptions["browse_observatories"].startswith("Compatibility:")
    assert "Prefer browse_data_sources" in descriptions["browse_observatories"]
    assert descriptions["fetch_data"].startswith("Compatibility:")
    assert "Prefer fetch_data_product" in descriptions["fetch_data"]

def test_browse_data_sources_lists_spedas_source_categories():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "all"}))
    assert data["status"] == "success"
    assert data["data_layer"] == "spedas"
    assert {entry["source_type"] for entry in data["source_types"]} == {"cdaweb", "pds", "spice"}



def test_browse_data_sources_filters_cdaweb_query():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "cdaweb", "query": "mms"}))
    assert data["status"] == "success"
    ids = [entry["id"] for entry in data["payload"]]
    assert ids == ["mms"]


def test_browse_data_sources_filters_spice_query():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "spice", "query": "PSP"}))
    assert data["status"] == "success"
    assert data["payload"]
    assert all("psp" in json.dumps(entry).lower() or "parker" in json.dumps(entry).lower() for entry in data["payload"])

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


def test_psp_perihelion_workflow_routes_to_cdaweb_and_spice():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Plan a Parker Solar Probe perihelion solar-wind workflow with FIELDS magnetic field, SWEAP plasma, and heliocentric geometry",
        "target": "Parker Solar Probe",
        "observables": ["solar wind", "magnetic field", "proton plasma", "perihelion geometry"],
    }))
    assert data["status"] == "success"
    assert "cdaweb" in data["recommended_sources"]
    assert "spice" in data["recommended_sources"]


def test_psp_perihelion_observation_plan_has_discovery_and_geometry_steps():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Parker Solar Probe perihelion solar-wind context: combine CDAWeb PSP FIELDS/SWEAP measurements with SPICE heliocentric distance and trajectory planning",
        "start": "2021-04-29T00:00:00Z",
        "stop": "2021-04-29T06:00:00Z",
        "target": "Parker Solar Probe",
        "observables": ["solar wind", "magnetic field", "proton plasma", "heliocentric distance"],
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"][:2] == ["cdaweb", "spice"]
    phases = {step["phase"] for step in data["plan"]}
    assert {"discover_cdaweb", "fetch_or_compute_cdaweb", "discover_spice", "fetch_or_compute_spice"} <= phases
    spice_step = next(step for step in data["plan"] if step["phase"] == "fetch_or_compute_spice")
    assert "get_ephemeris" in spice_step["tools"]


# ---------------------------------------------------------------------------
# Issue #24: parameter-name consistency between discovery tools.
# search_spedas_data_sources historically takes `question`; browse_data_sources
# takes `query`. Accept `query` as a backward-compatible alias so agents that
# learned `browse_data_sources(query=...)` do not silently get empty results.
# ---------------------------------------------------------------------------

def test_search_spedas_data_sources_accepts_query_alias():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "query": "MMS magnetopause ions",
    }))
    assert data["status"] == "success"
    # The science-goal text must actually be processed, not dropped.
    assert data["question"] == "MMS magnetopause ions"
    assert data["observables"] != [] or data["recommended_sources"]


def test_search_spedas_data_sources_question_still_works():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "MMS magnetopause ions",
    }))
    assert data["status"] == "success"
    assert data["question"] == "MMS magnetopause ions"


def test_search_spedas_data_sources_question_wins_over_query_alias():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Parker Solar Probe FIELDS magnetic field",
        "query": "ignored alias value",
    }))
    assert data["status"] == "success"
    # Explicit canonical `question` takes precedence over the alias.
    assert data["question"] == "Parker Solar Probe FIELDS magnetic field"


# ---------------------------------------------------------------------------
# Issue #31: dataset enumeration in load_data_source(cdaweb) so agents can move
# from discovery -> load -> browse_data_parameters without guessing IDs.
# ---------------------------------------------------------------------------

def test_load_data_source_cdaweb_enumerates_datasets():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "mms",
    }))
    assert loaded["status"] == "success"
    assert loaded["source_id"] == "mms"
    datasets = loaded["datasets"]
    assert isinstance(datasets, list)
    assert datasets, "expected a non-empty dataset list for the mms observatory"
    assert loaded["dataset_count"] == len(datasets) or loaded["dataset_count"] >= len(datasets)
    first = datasets[0]
    assert "dataset_id" in first
    # Dataset IDs surfaced here must be consumable by browse_data_parameters.
    dataset_ids = {entry["dataset_id"] for entry in datasets}
    assert any(ds_id.upper().startswith("MMS") for ds_id in dataset_ids)


def test_load_data_source_cdaweb_dataset_response_is_size_safe():
    server = create_server()
    raw = _call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "mms",
    })
    # Keep comfortably within the MCP stdio response-size safety expectation
    # (<64KB) even for a large observatory such as MMS (~268 datasets).
    assert len(raw.encode("utf-8")) < 64 * 1024
    loaded = json.loads(raw)
    # A large observatory truncates the structured list but still reports the
    # true total so discovery is not silently incomplete.
    if loaded["datasets_truncated"]:
        assert loaded["dataset_count"] > len(loaded["datasets"])
        assert "datasets_note" in loaded

    enum_payload = {
        "dataset_count": loaded["dataset_count"],
        "datasets": loaded["datasets"],
        "datasets_truncated": loaded["datasets_truncated"],
        "instruments": loaded["instruments"],
    }
    if "datasets_note" in loaded:
        enum_payload["datasets_note"] = loaded["datasets_note"]
    assert len(json.dumps(enum_payload, indent=2).encode("utf-8")) <= 16_000


def test_load_data_source_cdaweb_small_observatory_not_truncated():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "genesis",
    }))
    assert loaded["status"] == "success"
    assert loaded["datasets_truncated"] is False
    assert loaded["dataset_count"] == len(loaded["datasets"])


def test_load_data_source_cdaweb_datasets_round_trip_to_browse_parameters():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "mms",
    }))
    dataset_id = loaded["datasets"][0]["dataset_id"]
    # Should not raise and should echo the dataset_id back through the unified layer.
    params = json.loads(_call_tool(server, "browse_data_parameters", {
        "source_type": "cdaweb",
        "dataset_id": dataset_id,
    }))
    assert params["dataset_id"] == dataset_id
