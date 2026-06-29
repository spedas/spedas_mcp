"""Tests for the unified SPEDAS Agent Kit facade."""
import asyncio
import json
import sys
import types
from pathlib import Path

from spedas_agent_kit import __version__
from spedas_agent_kit.server import (
    ANALYSIS_TOOL_NAMES,
    FDSN_TOOL_NAMES,
    HAPI_TOOL_NAMES,
    create_server,
)

COMPAT_CDAWEB_PDS_TOOLS = {
    "browse_observatories",
    "load_observatory",
    "browse_parameters",
    "fetch_data",
    "browse_pds_missions",
    "load_pds_mission",
    "browse_pds_parameters",
    "fetch_pds_data",
}

DATASOURCE_HAPI_FDSN_TOOLS = {
    "browse_hapi_catalog",
    "fetch_hapi_data",
    "browse_fdsn_datasets",
    "fetch_fdsn_data",
}


def _call_tool(server, name, args=None):
    args = args or {}
    content, _metadata = asyncio.run(server.call_tool(name, args))
    # FastMCP returns (content_blocks, metadata); tests only need the first text block.
    return content[0].text


def test_version():
    assert __version__ == "0.1.0"


def test_server_has_expected_tools(monkeypatch):
    monkeypatch.delenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", raising=False)
    monkeypatch.delenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", raising=False)
    server = create_server(include_analysis_tools=True)
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
        "get_ephemeris",
        "compute_distance",
        "transform_coordinates",
        "transform_timeseries_coordinates",
        "generate_fac_matrix",
        "tvector_rotate",
        "analyze_minvar_coordinates",
        "dynamic_power_spectrum",
        "wavelet_transform",
        "evaluate_magnetic_field",
        "calculate_lshell",
        "build_particle_distribution_artifact",
        "load_particle_distribution_artifact",
        "compute_particle_moments",
        "compute_particle_spectra",
        "render_tplot",
    } <= names
    assert {"manage_cdaweb_cache", "manage_pds_cache", "manage_spice_kernels"}.isdisjoint(names)
    assert {"list_spice_missions", "list_coordinate_frames"}.isdisjoint(names)
    assert names.isdisjoint(COMPAT_CDAWEB_PDS_TOOLS)
    # Direct HAPI/FDSN tools are demoted out of the default surface (issue #87).
    assert names.isdisjoint(DATASOURCE_HAPI_FDSN_TOOLS)


def test_base_surface_is_thirteen_primary_tools(monkeypatch):
    monkeypatch.delenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", raising=False)
    monkeypatch.delenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", raising=False)
    server = create_server(include_analysis_tools=False)
    tools = asyncio.run(server.list_tools())
    assert len(tools) == 13
    assert {tool.meta["surface"] for tool in tools} == {"primary"}


def test_server_advertises_cdaweb_pds_compat_tools_when_flag_set(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", "1")
    server = create_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert COMPAT_CDAWEB_PDS_TOOLS <= names


def test_server_advertises_hapi_fdsn_tools_when_datasource_flag_set(monkeypatch):
    monkeypatch.delenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", raising=False)
    monkeypatch.setenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", "1")
    server = create_server(include_analysis_tools=False)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    assert DATASOURCE_HAPI_FDSN_TOOLS <= set(tools)
    for name in DATASOURCE_HAPI_FDSN_TOOLS:
        assert tools[name].meta["surface"] == "datasource"
    # fetch tools mutate the filesystem; browse tools are read-only.
    assert tools["browse_hapi_catalog"].annotations.readOnlyHint is True
    assert tools["fetch_hapi_data"].annotations.readOnlyHint is False
    assert tools["browse_fdsn_datasets"].annotations.readOnlyHint is True
    assert tools["fetch_fdsn_data"].annotations.readOnlyHint is False


def test_analysis_tools_are_gated_when_analysis_extra_is_absent(monkeypatch):
    from spedas_agent_kit import server as server_mod

    monkeypatch.setattr(server_mod, "_analysis_dependencies_available", lambda: False)
    server = create_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert set(ANALYSIS_TOOL_NAMES).isdisjoint(names)

    data = json.loads(_call_tool(server, "spedas_overview"))
    assert data["capability_groups"]["analysis"]["tools"] == []
    assert "install with spedas-agent-kit[analysis]" in data["capability_groups"]["analysis"]["status"]


def test_analysis_tools_register_when_analysis_extra_is_available(monkeypatch):
    from spedas_agent_kit import server as server_mod

    monkeypatch.setattr(server_mod, "_analysis_dependencies_available", lambda: True)
    server = create_server()
    tools = asyncio.run(server.list_tools())
    names = {tool.name for tool in tools}
    assert set(ANALYSIS_TOOL_NAMES) <= names

    data = json.loads(_call_tool(server, "spedas_overview"))
    assert data["capability_groups"]["analysis"]["tools"] == list(ANALYSIS_TOOL_NAMES)

def test_optional_backend_availability_metadata_when_base_deps_missing(monkeypatch):
    from spedas_agent_kit import server as server_mod

    monkeypatch.setattr(server_mod, "_analysis_dependencies_available", lambda: False)
    monkeypatch.setattr(server_mod, "_module_available", lambda name: False)

    monkeypatch.delenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", raising=False)
    server = create_server()
    tool_names = {tool.name for tool in asyncio.run(server.list_tools())}
    # Direct HAPI/FDSN tools are hidden from the default surface (issue #87), but
    # their backend availability is still reported via optional_backends below.
    assert {"browse_hapi_catalog", "fetch_hapi_data", "browse_fdsn_datasets", "fetch_fdsn_data"}.isdisjoint(tool_names)
    assert set(ANALYSIS_TOOL_NAMES).isdisjoint(tool_names)

    overview = json.loads(_call_tool(server, "spedas_overview"))
    optional = overview["capability_groups"]["optional_backends"]
    assert optional["analysis"]["available"] is False
    assert optional["analysis"]["requires_extra"] == "analysis"
    assert optional["analysis"]["registration"] == "registered_when_available"
    assert optional["hapi"]["available"] is False
    assert optional["hapi"]["requires_extra"] == "hapi"
    assert optional["hapi"]["registration"] == "gated_optional"
    assert optional["hapi"]["missing_modules"] == ["hapiclient"]
    assert optional["hapi"]["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert optional["hapi"]["advertised"] is False
    assert optional["hapi"]["discover_via"] == "browse_data_sources(source_type='hapi')"
    assert optional["hapi"]["tools"] == list(HAPI_TOOL_NAMES)
    assert optional["fdsn"]["available"] is False
    assert optional["fdsn"]["requires_extra"] == "fdsn"
    assert optional["fdsn"]["registration"] == "gated_optional"
    assert {"pyspedas", "mth5", "obspy"} == set(optional["fdsn"]["missing_modules"])
    assert optional["fdsn"]["advertised"] is False
    assert optional["fdsn"]["discover_via"] == "browse_data_sources(source_type='fdsn')"
    assert "missing_dependency" in optional["hapi"]["call_behavior"]
    assert "missing_dependency" in optional["fdsn"]["call_behavior"]

    sources = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "all"}))
    by_type = {entry["source_type"]: entry for entry in sources["source_types"]}
    assert by_type["hapi"]["available"] is False
    assert by_type["hapi"]["requires_extra"] == "hapi"
    assert by_type["hapi"]["install_hint"] == "pip install 'spedas-agent-kit[hapi]'"
    assert by_type["hapi"]["direct_tool_gate"]["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert by_type["hapi"]["direct_tool_gate"]["advertised"] is False
    assert by_type["fdsn"]["available"] is False
    assert by_type["fdsn"]["requires_extra"] == "fdsn"
    assert by_type["fdsn"]["install_hint"] == "pip install 'spedas-agent-kit[fdsn]'"
    assert by_type["fdsn"]["direct_tool_gate"]["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert by_type["fdsn"]["direct_tool_gate"]["advertised"] is False


def test_overview_is_compact_json(monkeypatch):
    monkeypatch.delenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", raising=False)
    monkeypatch.delenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", raising=False)
    server = create_server()
    data = json.loads(_call_tool(server, "spedas_overview"))
    assert data["status"] == "success"
    assert "data" in data["capability_groups"]
    assert "science_workflows" in data["capability_groups"]
    assert "geometry" in data["capability_groups"]
    assert "compatibility_low_level" in data["capability_groups"]
    compat = data["capability_groups"]["compatibility_low_level"]
    assert compat["env_flag"] == "SPEDAS_AGENT_KIT_COMPAT_TOOLS=1"
    assert set(compat["hidden_by_default"]) == COMPAT_CDAWEB_PDS_TOOLS
    assert compat["available_for_existing_clients"] == []
    datasource = data["capability_groups"]["datasource_optional"]
    assert datasource["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert set(datasource["hidden_by_default"]) == DATASOURCE_HAPI_FDSN_TOOLS
    assert datasource["available_directly"] == []
    assert datasource["discover_via"] == [
        "browse_data_sources(source_type='hapi')",
        "browse_data_sources(source_type='fdsn')",
    ]


def test_overview_advertises_hapi_fdsn_directly_when_datasource_flag_set(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", "1")
    server = create_server()
    data = json.loads(_call_tool(server, "spedas_overview"))
    datasource = data["capability_groups"]["datasource_optional"]
    assert set(datasource["available_directly"]) == DATASOURCE_HAPI_FDSN_TOOLS
    assert "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1" in datasource["status"]


def test_overview_advertises_geomagnetic_index_recipe(monkeypatch):
    monkeypatch.delenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", raising=False)
    server = create_server()
    data = json.loads(_call_tool(server, "spedas_overview"))
    recipes = data["guided_recipes"]
    assert recipes["overview_skill"] == "overview-geomagnetic-indices"
    geomag = {entry["intent"]: entry for entry in recipes["geomagnetic_indices"]}
    assert any("Dst" in intent for intent in geomag)
    assert any("Kp" in entry["variables"] for entry in geomag.values())
    assert any("SYM_H" in entry["variables"] for entry in geomag.values())
    assert "MMS1_FGM_SRVY_L2" in recipes["mission_overview_starting_points"]["MMS"]
    assert "THA_L2_FGM" in recipes["mission_overview_starting_points"]["THEMIS"]


def test_base_tools_expose_primary_surface_metadata(monkeypatch):
    monkeypatch.delenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", raising=False)
    monkeypatch.delenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", raising=False)
    server = create_server(include_analysis_tools=False)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    assert tools
    assert {tool.meta["surface"] for tool in tools.values()} == {"primary"}
    assert all(tool.annotations is not None for tool in tools.values())
    assert tools["browse_data_sources"].annotations.readOnlyHint is True
    assert tools["fetch_data_product"].annotations.readOnlyHint is False
    assert tools["fetch_data_product"].annotations.openWorldHint is True
    assert tools["get_ephemeris"].annotations.readOnlyHint is False
    assert tools["get_ephemeris"].annotations.openWorldHint is True
    assert tools["compute_distance"].annotations.readOnlyHint is False
    assert tools["transform_coordinates"].annotations.readOnlyHint is False
    assert tools["manage_data_cache"].annotations.destructiveHint is True
    assert tools["manage_data_cache"].annotations.openWorldHint is False


def test_tool_descriptions_and_meta_mark_primary_and_compatibility_surfaces(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", "1")
    server = create_server()
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}
    descriptions = {name: tool.description for name, tool in tools.items()}
    assert descriptions["browse_data_sources"].startswith("Primary data layer")
    assert descriptions["fetch_data_product"].startswith("Primary data layer")
    assert tools["browse_data_sources"].meta["surface"] == "primary"
    assert tools["fetch_data_product"].meta["surface"] == "primary"
    assert descriptions["browse_observatories"].startswith("Compatibility:")
    assert "Prefer browse_data_sources" in descriptions["browse_observatories"]
    assert tools["browse_observatories"].meta["surface"] == "compat"
    assert tools["browse_observatories"].annotations.readOnlyHint is True
    assert descriptions["fetch_data"].startswith("Compatibility:")
    assert "Prefer fetch_data_product" in descriptions["fetch_data"]
    assert tools["fetch_data"].meta["surface"] == "compat"
    assert tools["fetch_data"].annotations.readOnlyHint is False
    assert tools["fetch_data"].annotations.openWorldHint is True


def test_analysis_tools_expose_advanced_surface_metadata(monkeypatch):
    monkeypatch.delenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", raising=False)
    server = create_server(include_analysis_tools=True)
    tools = {tool.name: tool for tool in asyncio.run(server.list_tools())}

    for name in [
        "transform_timeseries_coordinates",
        "build_particle_distribution_artifact",
        "render_tplot",
    ]:
        assert tools[name].meta["surface"] == "advanced"
        assert tools[name].annotations.readOnlyHint is False
        assert tools[name].annotations.openWorldHint is True

def test_browse_data_sources_lists_spedas_source_categories():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "all"}))
    assert data["status"] == "success"
    assert data["data_layer"] == "spedas"
    assert {entry["source_type"] for entry in data["source_types"]} == {"cdaweb", "pds", "spice", "hapi", "fdsn"}



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


def test_browse_data_sources_cdaweb_dataset_query_mms_fgm():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "cdaweb", "query": "MMS FGM"}))

    assert data["status"] == "success"
    assert data["discovery_mode"] == "dataset_query"
    dataset_ids = [entry["dataset_id"] for entry in data["payload"]]
    assert "MMS1_FGM_SRVY_L2" in dataset_ids
    assert "MMS1_FGM_BRST_L2" in dataset_ids
    first = data["payload"][0]
    assert first["source_id"] == "mms"
    assert first["why"]
    assert any("browse_data_parameters" in call and first["dataset_id"] in call for call in first["next_tools"])


def test_browse_data_sources_cdaweb_dataset_query_themis_fgm_and_negative():
    server = create_server()
    themis = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "cdaweb", "query": "THEMIS FGM"}))

    assert themis["status"] == "success"
    assert themis["discovery_mode"] == "dataset_query"
    dataset_ids = {entry["dataset_id"] for entry in themis["payload"]}
    assert {"THA_L2_FGM", "THB_L2_FGM"} <= dataset_ids
    assert all(entry["why"] for entry in themis["payload"][:3])

    negative = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "cdaweb", "query": "zzzz notarealproduct"}))
    assert negative["status"] == "success"
    assert negative["payload"] == []


def test_browse_data_sources_pds_matches_single_token_query():
    # Regression for issue #133: a single recognizable mission token must surface
    # the matching PDS mission instead of an empty payload.
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "pds", "query": "juno"}))
    assert data["status"] == "success"
    ids = [entry["id"] for entry in data["payload"]]
    assert "JUNO_PPI" in ids


def test_browse_data_sources_pds_matches_multiword_query_by_term():
    # Regression for issue #133: a multi-word query whose mission token clearly
    # matches must not silently return an empty payload just because the whole
    # phrase is not a contiguous substring of the record.
    server = create_server()
    for query in ("juno magnetometer", "Juno spacecraft", "juno mag"):
        data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "pds", "query": query}))
        assert data["status"] == "success", query
        ids = [entry["id"] for entry in data["payload"]]
        assert "JUNO_PPI" in ids, f"expected Juno PDS mission to surface for query {query!r}, got {ids}"


def test_browse_data_sources_pds_negative_query_returns_empty():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "pds", "query": "zzzz notarealmission"}))
    assert data["status"] == "success"
    assert data["payload"] == []


def test_browse_data_sources_spice_matches_multiword_query_by_term():
    # Regression for issue #133: SPICE multi-word queries must match by token too.
    server = create_server()
    for query in ("juno magnetometer", "Juno spacecraft", "juno jupiter"):
        data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "spice", "query": query}))
        assert data["status"] == "success", query
        keys = [entry.get("mission_key") for entry in data["payload"]]
        assert "JUNO" in keys, f"expected Juno SPICE mission to surface for query {query!r}, got {keys}"


def test_browse_data_sources_spice_negative_query_returns_empty():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "spice", "query": "zzzz notarealmission"}))
    assert data["status"] == "success"
    assert data["payload"] == []


def test_browse_data_sources_discovers_curated_omni_and_geomagnetic_indices():
    server = create_server()

    omni = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "cdaweb", "query": "omni"}))
    omni_ids = {entry["id"] for entry in omni["payload"]}
    assert "omni" in omni_ids
    assert any(entry.get("source_label") == "CDAWeb curated dataset group" for entry in omni["payload"])

    dst = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "cdaweb", "query": "dst"}))
    assert any(entry["id"] == "geomagnetic_indices" for entry in dst["payload"])


def test_load_data_source_cdaweb_resolves_curated_omni_aliases():
    server = create_server()
    for source_id in ("OMNI", "OMNI_HRO", "OMNI_HRO2"):
        data = json.loads(_call_tool(server, "load_data_source", {"source_type": "cdaweb", "source_id": source_id}))
        assert data["status"] == "success"
        assert data["normalized_source_id"] == "omni"
        dataset_ids = {entry["dataset_id"] for entry in data["datasets"]}
        assert {"OMNI_HRO_1MIN", "OMNI_HRO2_1MIN", "OMNI2_H0_MRG1HR"} <= dataset_ids
        assert data["payload"]["source_label"] == "CDAWeb curated dataset group"


def test_load_data_source_cdaweb_resolves_geomagnetic_index_alias():
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {"source_type": "cdaweb", "source_id": "dst"}))
    assert data["status"] == "success"
    assert data["normalized_source_id"] == "geomagnetic_indices"
    text = json.dumps(data)
    assert "OMNI2_H0_MRG1HR" in text
    assert "SYM-H" in text
    assert "Kp" in text

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


def test_browse_observatories_uses_cdaweb_catalog(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", "1")
    server = create_server()
    data = json.loads(_call_tool(server, "browse_observatories"))
    assert isinstance(data, list)
    assert any(obs.get("id") == "ace" for obs in data)


def test_unified_spice_browse_uses_in_tree_spice_registry():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "spice"}))
    assert data["status"] == "success"
    assert isinstance(data["payload"], list)
    assert any(mission.get("mission_key") == "PSP" for mission in data["payload"])


def test_browse_pds_missions_uses_in_tree_pds_catalog(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", "1")
    server = create_server()
    data = json.loads(_call_tool(server, "browse_pds_missions"))
    assert isinstance(data, list)
    assert any(mission.get("id") == "JUNO_PPI" for mission in data)


def test_browse_pds_parameters_uses_bundled_metadata(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_COMPAT_TOOLS", "1")
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


def test_unified_spice_frame_catalog_is_programmatic_without_extra_tool():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    assert "list_coordinate_frames" not in {tool.name for tool in tools}

    loaded = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": "frames"}))
    assert loaded["status"] == "success"
    assert loaded["source_type"] == "spice"
    assert loaded["frame_catalog"]["catalog_type"] == "spice_coordinate_frames"
    assert loaded["frame_catalog"]["frames"] == loaded["payload"]
    assert loaded["frame_catalog"]["frame_count"] == len(loaded["frame_names"])
    assert {"J2000", "ECLIPJ2000", "RTN"} <= set(loaded["supported_frame_names"])
    assert any(frame["frame"] == "RTN" and "spacecraft" in frame["description"].lower() for frame in loaded["payload"])
    assert any(alias["alias"] == "ECLIPTIC" and alias["frame"] == "ECLIPJ2000" for alias in loaded["frame_catalog"]["aliases"])
    assert loaded["frame_catalog"]["transform_tool"] == "transform_coordinates"


def test_browse_spice_sources_also_advertises_frame_catalog_for_discovery():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "spice", "query": "frame"}))
    assert data["status"] == "success"
    assert data["frame_catalog"]["frames"]
    assert "GSE" in data["supported_frame_names"]
    assert "transform_coordinates" in data["note"]


# Issue #134: load_data_source(spice, <mission>) must return mission-specific
# SPICE metadata (NAIF id, kernel files, cache status) instead of silently
# ignoring source_id and always returning the global frame catalog.


def test_load_data_source_spice_empty_source_id_returns_global_frame_catalog():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": ""}))
    assert loaded["status"] == "success"
    assert loaded["source_type"] == "spice"
    # Empty source_id keeps the legacy global coordinate-frame catalog behavior.
    assert loaded["frame_catalog"]["catalog_type"] == "spice_coordinate_frames"
    assert loaded["frame_catalog"]["frames"] == loaded["payload"]
    # No mission-specific metadata leaks into the global catalog response.
    assert "naif_id" not in loaded
    assert "mission" not in loaded


def test_load_data_source_spice_juno_returns_mission_metadata():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": "JUNO"}))
    assert loaded["status"] == "success"
    assert loaded["source_type"] == "spice"
    # Juno is NAIF -61 with the juno_rec_orbit.bsp SPK (issue #134).
    assert loaded["naif_id"] == -61
    assert loaded["mission"] == "JUNO"
    payload = loaded["payload"]
    assert payload["naif_id"] == -61
    assert payload["mission_key"] == "JUNO"
    assert "juno_rec_orbit.bsp" in payload["kernel_files"]
    # Cache status is reported without downloading anything.
    assert "cached" in payload["kernel_status"]
    # Frame support is not falsely claimed for mission body frames.
    assert payload["caveats"]


def test_load_data_source_spice_juno_differs_from_global_frame_catalog():
    server = create_server()
    juno = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": "JUNO"}))
    glbl = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": ""}))
    # Mission load must NOT return the global frame catalog.
    assert juno["payload"] != glbl["payload"]
    assert "frame_catalog" not in juno
    assert glbl["frame_catalog"]["catalog_type"] == "spice_coordinate_frames"


def test_load_data_source_spice_frames_keyword_still_returns_catalog():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": "frames"}))
    assert loaded["status"] == "success"
    assert loaded["frame_catalog"]["catalog_type"] == "spice_coordinate_frames"


def test_load_data_source_spice_unknown_mission_returns_structured_error():
    server = create_server()
    raw = _call_tool(server, "load_data_source", {"source_type": "spice", "source_id": "NOT_A_MISSION"})
    # No filesystem path may leak (issue #25 contract carried over).
    assert "/Users/" not in raw
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unknown_source_id"
    assert payload["source_id"] == "NOT_A_MISSION"
    assert payload["source_type"] == "spice"


def test_load_data_source_spice_mission_alias_resolves():
    server = create_server()
    # "Parker Solar Probe" is an alias for PSP (NAIF -96); aliases must resolve
    # to the canonical mission metadata, not an unknown_source_id error.
    loaded = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "spice",
        "source_id": "Parker Solar Probe",
    }))
    assert loaded["status"] == "success"
    assert loaded["naif_id"] == -96
    assert loaded["mission"] == "PSP"


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


def test_user_facing_branding_hides_backend_package_names():
    import inspect

    import spedas_agent_kit

    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "all"}))
    pyproject = Path("pyproject.toml").read_text()
    description_line = next(line for line in pyproject.splitlines() if line.startswith("description = "))

    assert "xhelio" not in data["note"].lower()
    assert "xhelio" not in (spedas_agent_kit.__doc__ or "").lower()
    assert "xhelio dependencies" not in inspect.getsource(spedas_agent_kit.main).lower()
    assert "xhelio" not in description_line.lower()


def test_load_data_source_cdaweb_translates_backend_guidance_to_facade(monkeypatch):
    import spedas_agent_kit.backends.cdaweb.prompts as prompts

    def _fake_prompt(observatory_id: str) -> str:
        return (
            "Call `browse_parameters(dataset_id)` before fetching. "
            "Then call `fetch_data(dataset_id, parameters, start, stop, output_dir)`. "
            "If the catalog is stale, run `manage_cache(action=\"rebuild_catalog\")`."
        )

    monkeypatch.setattr(prompts, "build_observatory_prompt", _fake_prompt)
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "ace",
        "mode": "full",
    }))
    payload = data["payload"]
    assert data["status"] == "success"
    assert "browse_data_parameters(source_type=\"cdaweb\"" in payload
    assert "fetch_data_product(source_type=\"cdaweb\"" in payload
    assert "manage_data_cache(source_type=\"cdaweb\"" in payload
    assert "browse_parameters(" not in payload
    assert "fetch_data(" not in payload
    assert "manage_cache(" not in payload


def test_load_data_source_pds_translates_backend_guidance_to_facade(monkeypatch):
    import spedas_agent_kit.backends.pds.prompts as prompts

    def _fake_prompt(mission_id: str) -> str:
        return (
            "Use `browse_parameters` to inspect dataset variables before fetching. "
            "Use `fetch_data` to download PDS data. "
            "Then call `browse_parameters(dataset_id)` to see available variables. "
            "Run `manage_cache(action=\"rebuild_catalog\")` if metadata is stale."
        )

    monkeypatch.setattr(prompts, "build_mission_prompt", _fake_prompt)
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "pds",
        "source_id": "vex",
    }))
    payload = data["payload"]
    assert data["status"] == "success"
    assert "browse_data_parameters(source_type=\"pds\"" in payload
    assert "fetch_data_product(source_type=\"pds\"" in payload
    assert "manage_data_cache(source_type=\"pds\"" in payload
    assert "browse_parameters" not in payload
    assert "fetch_data`" not in payload
    assert "manage_cache" not in payload


def test_cdaweb_fetch_product_limit_and_quality_stats(monkeypatch, tmp_path: Path):
    import pandas as pd
    import spedas_agent_kit.backends.cdaweb.fetch as fetch_mod

    def _fake_fetch_data(dataset_id: str, parameters: list[str], start: str, stop: str):
        index = pd.date_range("2025-01-01T00:00:00", periods=5, freq="s")
        return {
            "DENS": {
                "data": pd.DataFrame({"DENS": [1.0, 2.0, 1e30, 4.0, 5.0]}, index=index),
                "units": "cm^-3",
                "description": "density",
                "stats": {"min": 1.0, "max": 1e30, "nan_ratio": 0.0},
            },
            "QUALITY_FLAG": {
                "data": pd.DataFrame({"QUALITY_FLAG": [0, 0, 1, 0, 1]}, index=index),
                "units": "",
                "description": "quality flag",
                "stats": {"min": 0, "max": 1, "nan_ratio": 0.0},
            },
        }

    monkeypatch.setattr(fetch_mod, "fetch_data", _fake_fetch_data)
    server = create_server()
    data = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "cdaweb",
        "dataset_id": "PSP_SWP_SPI_SF00_L3_MOM",
        "parameters": ["DENS", "QUALITY_FLAG"],
        "start": "2025-01-01T00:00:00Z",
        "stop": "2025-01-01T00:00:05Z",
        "output_dir": str(tmp_path),
        "limit": 2,
    }))
    assert data["status"] == "success"
    payload = data["payload"]
    assert payload["rows_before_limit"] == 5
    assert payload["rows_written"] == 2
    assert payload["rows_truncated"] == 3
    assert payload["limit"] == 2
    assert payload["limit_applied"] is True
    assert len(pd.read_csv(payload["file_path"])) == 2

    density_stats = payload["parameters"]["DENS"]["stats"]
    quality_checks = density_stats["quality_checks"]
    assert quality_checks["fill_like_count"] == 1
    assert quality_checks["fill_ratio"] == 0.2
    assert "p99" in quality_checks["robust_stats"]["columns"]["DENS"]

    flag_checks = payload["parameters"]["QUALITY_FLAG"]["stats"]["quality_checks"]
    assert flag_checks["quality_flags"]["QUALITY_FLAG"]["counts"]["0"] == 3
    assert flag_checks["quality_flags"]["QUALITY_FLAG"]["counts"]["1"] == 2




def test_fetch_data_product_rejects_bad_times_before_cdaweb_backend(monkeypatch, tmp_path: Path):
    import spedas_agent_kit.backends.cdaweb.fetch as fetch_mod

    called = False

    def _fake_fetch_data(dataset_id: str, parameters: list[str], start: str, stop: str):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(fetch_mod, "fetch_data", _fake_fetch_data)
    server = create_server()

    malformed = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "cdaweb",
        "dataset_id": "PSP_FLD_L2_MAG_RTN_1MIN",
        "parameters": ["psp_fld_l2_mag_RTN_1min"],
        "start": "not-a-date",
        "stop": "2025-06-19T09:00:00Z",
        "output_dir": str(tmp_path),
    }))
    _assert_uniform_error(malformed)
    assert malformed["code"] == "invalid_argument"
    assert malformed["invalid_argument"] == "start"
    assert "parse" in malformed["message"]

    reversed_range = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "cdaweb",
        "dataset_id": "PSP_FLD_L2_MAG_RTN_1MIN",
        "parameters": ["psp_fld_l2_mag_RTN_1min"],
        "start": "2025-06-19T10:00:00Z",
        "stop": "2025-06-19T08:00:00Z",
        "output_dir": str(tmp_path),
    }))
    _assert_uniform_error(reversed_range)
    assert reversed_range["code"] == "invalid_argument"
    assert reversed_range["invalid_argument"] == "stop"
    assert "after start" in reversed_range["message"]
    assert called is False


def test_fetch_data_product_shapes_cdaweb_no_data_codes(monkeypatch, tmp_path: Path):
    import spedas_agent_kit.backends.cdaweb.fetch as fetch_mod

    def _fake_fetch_data(dataset_id: str, parameters: list[str], start: str, stop: str):
        if dataset_id == "PSP_TOTALLY_FAKE_DATASET":
            return {parameters[0]: {"error": "Master CDF download failed with 404 Not Found"}}
        if dataset_id == "PSP_FAKE_MIXED_DATASET":
            return {parameters[0]: {"error": "Unknown dataset not in catalog; no CDF files found for requested time range"}}
        if parameters == ["this_param_does_not_exist"]:
            return {parameters[0]: {"error": "Parameter this_param_does_not_exist not in dataset"}}
        if parameters == ["mixed_missing_param"]:
            return {parameters[0]: {"error": "Unknown parameter mixed_missing_param; no data files found for requested time range"}}
        return {parameters[0]: {"error": "No CDF files found for requested time range"}}

    monkeypatch.setattr(fetch_mod, "fetch_data", _fake_fetch_data)
    server = create_server()
    base = {
        "source_type": "cdaweb",
        "dataset_id": "PSP_FLD_L2_MAG_RTN_1MIN",
        "parameters": ["psp_fld_l2_mag_RTN_1min"],
        "start": "2025-06-19T08:00:00Z",
        "stop": "2025-06-19T09:00:00Z",
        "output_dir": str(tmp_path),
    }

    bad_dataset = json.loads(_call_tool(server, "fetch_data_product", {**base, "dataset_id": "PSP_TOTALLY_FAKE_DATASET"}))
    _assert_uniform_error(bad_dataset)
    assert bad_dataset["code"] == "unknown_dataset"
    assert bad_dataset["parameters"]

    bad_parameter = json.loads(_call_tool(server, "fetch_data_product", {**base, "parameters": ["this_param_does_not_exist"]}))
    _assert_uniform_error(bad_parameter)
    assert bad_parameter["code"] == "unknown_parameter"
    assert bad_parameter["requested_parameters"] == ["this_param_does_not_exist"]

    mixed_dataset = json.loads(_call_tool(server, "fetch_data_product", {**base, "dataset_id": "PSP_FAKE_MIXED_DATASET"}))
    _assert_uniform_error(mixed_dataset)
    assert mixed_dataset["code"] == "unknown_dataset"

    mixed_parameter = json.loads(_call_tool(server, "fetch_data_product", {**base, "parameters": ["mixed_missing_param"]}))
    _assert_uniform_error(mixed_parameter)
    assert mixed_parameter["code"] == "unknown_parameter"

    empty_range = json.loads(_call_tool(server, "fetch_data_product", {**base, "start": "2030-01-01T00:00:00Z", "stop": "2030-01-01T01:00:00Z"}))
    _assert_uniform_error(empty_range)
    assert empty_range["code"] == "no_data_in_range"
    assert empty_range["time_range"]["start"].startswith("2030")


def test_fetch_data_product_rejects_bad_times_before_pds_backend(monkeypatch, tmp_path: Path):
    import spedas_agent_kit.backends.pds.fetch as fetch_mod

    called = False

    def _fake_fetch_data(dataset_id: str, parameters: list[str], start: str, stop: str):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(fetch_mod, "fetch_data", _fake_fetch_data)
    server = create_server()
    data = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "pds",
        "dataset_id": "urn:nasa:pds:test",
        "parameters": ["B_RTN"],
        "start": "2025-06-19T10:00:00Z",
        "stop": "2025-06-19T08:00:00Z",
        "output_dir": str(tmp_path),
    }))
    _assert_uniform_error(data)
    assert data["code"] == "invalid_argument"
    assert data["source_type"] == "pds"
    assert called is False


def test_unified_cache_manager_does_not_forward_cache_dir_kwarg():
    server = create_server()
    data = json.loads(_call_tool(server, "manage_data_cache", {"source_type": "spice", "action": "status", "cache_dir": "/tmp/ignored"}))
    assert data["status"] == "success"
    assert data["note"]


def test_unified_cache_manager_passes_cdaweb_kwargs(monkeypatch):
    seen = {}

    def _cache_clean(**kwargs):
        seen.update(kwargs)
        return {"status": "success", "seen": kwargs}

    cache_mod = types.SimpleNamespace(
        cache_status=lambda detail=False: {"status": "success", "detail": detail},
        cache_clean=_cache_clean,
        rebuild_catalog=lambda observatory=None: {"status": "success"},
        refresh_metadata=lambda dataset_ids=None, observatory=None: {"status": "success"},
        refresh_time_ranges=lambda observatory=None: {"status": "success"},
    )
    monkeypatch.setitem(sys.modules, "spedas_agent_kit.backends.cdaweb.cache", cache_mod)

    server = create_server()
    data = json.loads(_call_tool(server, "manage_data_cache", {
        "source_type": "cdaweb",
        "action": "clean",
        "category": "cdf_cache",
        "observatory": "MMS",
        "older_than_days": 7,
        "dry_run": False,
    }))
    assert data["status"] == "success"
    assert seen == {
        "category": "cdf_cache",
        "observatories": ["MMS"],
        "older_than_days": 7,
        "dry_run": False,
    }


def test_unified_cache_manager_passes_pds_and_spice_kwargs(monkeypatch):
    pds_seen = {}
    spice_seen = {}

    pds_cache_mod = types.SimpleNamespace(
        cache_status=lambda detail=False: {"status": "success", "detail": detail},
        cache_clean=lambda **kwargs: {"status": "success", **kwargs},
        refresh_metadata=lambda dataset_ids=None, mission=None: {"status": "success"},
        build_metadata=lambda **kwargs: (pds_seen.update(kwargs) or {"status": "success", "seen": kwargs}),
        refresh_time_ranges=lambda mission=None: {"status": "success"},
        rebuild_catalog=lambda mission=None: {"status": "success"},
    )
    monkeypatch.setitem(sys.modules, "spedas_agent_kit.backends.pds.cache", pds_cache_mod)

    spice_mod = types.SimpleNamespace(
        check_remote_kernels=lambda mission=None: {"status": "success"},
        get_kernel_manager=lambda: types.SimpleNamespace(
            get_cache_info=lambda: {"status": "success"},
            ensure_mission_kernels=lambda mission: None,
            delete_cached_files=lambda filenames: (spice_seen.update({"filenames": filenames}) or filenames),
            delete_mission_cache=lambda mission: [mission],
            purge_cache=lambda: [],
        ),
    )
    monkeypatch.setitem(sys.modules, "spedas_agent_kit.backends.spice.kernel_manager", spice_mod)

    server = create_server()
    pds_data = json.loads(_call_tool(server, "manage_data_cache", {
        "source_type": "pds",
        "action": "build_metadata",
        "mission": "JUNO",
        "force": True,
    }))
    assert pds_data["status"] == "success"
    assert pds_seen == {"mission": "JUNO", "force": True}

    spice_data = json.loads(_call_tool(server, "manage_data_cache", {
        "source_type": "spice",
        "action": "clean",
        "filenames": ["a.bsp"],
    }))
    assert spice_data["status"] == "success"
    assert spice_seen == {"filenames": ["a.bsp"]}


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


# ---------------------------------------------------------------------------
# Issue #30 / zhipu-1 B1: the date-shaped regex can match impossible tokens
# (2015-13-40, 2015-02-30, 9999-99-99). These must be treated as "no parse"
# and never raise a raw ValueError out of the public planner tools.
# ---------------------------------------------------------------------------

import pytest as _pytest_b1  # noqa: E402


@_pytest_b1.mark.parametrize(
    "goal",
    [
        "magnetopause crossing on 2015-13-40",
        "event on 2015-02-30 around noon",
        "study 9999-99-99",
        "burst at 2015-10-16 25:61",
    ],
)
def test_plan_spedas_observation_impossible_date_does_not_crash(goal):
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {"science_goal": goal}))
    # No raw ValueError escapes; the tool returns a structured, parse-free plan.
    assert data["status"] == "needs_input"
    assert data["inferred"] == {}
    assert {"start", "stop"} <= set(data["needs_user_input"])


def test_extract_time_range_drops_impossible_dates():
    from spedas_agent_kit.workflows import _extract_time_range

    for goal in ("2015-13-40", "2015-02-30", "9999-99-99", "2020-00-10"):
        assert _extract_time_range(goal) == (None, None)


def test_extract_time_range_valid_date_still_parses():
    from spedas_agent_kit.workflows import _extract_time_range

    assert _extract_time_range("event on 2015-10-16") == (
        "2015-10-16T00:00:00Z",
        "2015-10-17T00:00:00Z",
    )


def test_plan_spedas_observation_is_safe_tool_wrapped(monkeypatch):
    """B1 defense in depth: an unexpected backend error converts to an envelope.

    Force a non-ValueError out of the workflow impl to prove the ``@_safe_tool``
    decorator wraps ``plan_spedas_observation`` (not just the helper parse fix).
    """
    import spedas_agent_kit.workflows as workflows_mod

    def _boom(*args, **kwargs):
        raise OSError("planner exploded at /Users/secret/path")

    monkeypatch.setattr(workflows_mod, "plan_observation", _boom)
    server = create_server()
    raw = _call_tool(server, "plan_spedas_observation", {"science_goal": "x"})
    out = json.loads(raw)
    assert out["status"] == "error"
    assert out["tool"] == "plan_spedas_observation"
    assert "/Users/" not in raw


def test_plan_spedas_observation_schema_preserved():
    server = create_server()
    tools = asyncio.run(server.list_tools())
    tool = next(t for t in tools if t.name == "plan_spedas_observation")
    props = set(tool.inputSchema.get("properties", {}))
    assert {"science_goal", "start", "stop", "target", "observables", "data_sources"} <= props
    assert tool.inputSchema.get("required") == ["science_goal"]


# ---------------------------------------------------------------------------
# Issue #30 / zhipu-1 SF1: mission alias false positives. Generic words must
# not be inferred as spacecraft, while explicit spacecraft phrasing still works.
# ---------------------------------------------------------------------------

@_pytest_b1.mark.parametrize(
    "goal",
    ["solo", "fly solo", "cluster", "a cluster of substorms", "wind speed", "solar-wind", "solar wind", "wind direction"],
)
def test_extract_target_no_false_positive(goal):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) is None


@_pytest_b1.mark.parametrize(
    "goal,expected",
    [
        ("Solar Orbiter magnetometer", "Solar Orbiter"),
        ("SolO spacecraft data", "Solar Orbiter"),
        ("solo mission overview", "Solar Orbiter"),
        ("Wind spacecraft plasma", "Wind"),
        ("Wind mission magnetic field", "Wind"),
        ("Cluster mission multi-point study", "Cluster"),
        ("Cluster constellation crossing", "Cluster"),
    ],
)
def test_extract_target_explicit_spacecraft_still_works(goal, expected):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) == expected


def test_plan_spedas_observation_does_not_infer_target_for_generic_wind():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "characterise solar-wind speed near the bow shock",
        "start": "2015-10-16T00:00:00Z",
        "stop": "2015-10-16T06:00:00Z",
    }))
    assert "target" not in data["inferred"]


# ---------------------------------------------------------------------------
# T009: multi-mission upstream comparison. A goal naming several spacecraft
# (e.g. "compare ACE, Wind, and OMNI ...") must surface ALL of them, not just
# the first match. The single-target path is preserved for back-compat; the
# extra missions are reported additively so a comparison workflow does not
# silently drop Wind/OMNI.
# ---------------------------------------------------------------------------

def test_extract_targets_returns_all_named_missions_in_order():
    from spedas_agent_kit.workflows import _extract_targets

    goal = (
        "Compare ACE, Wind, and OMNI solar-wind magnetic field and plasma "
        "upstream of Earth on 2015-10-16"
    )
    assert _extract_targets(goal) == ["ACE", "Wind", "OMNI"]


def test_extract_targets_deduplicates_and_preserves_first_position():
    from spedas_agent_kit.workflows import _extract_targets

    # Repeated mentions collapse; first appearance order wins.
    goal = "ACE vs Wind upstream; cross-check ACE against OMNI and Wind again"
    assert _extract_targets(goal) == ["ACE", "Wind", "OMNI"]


def test_extract_targets_single_mission_matches_extract_target():
    from spedas_agent_kit.workflows import _extract_target, _extract_targets

    goal = "Parker Solar Probe perihelion magnetic field on 2021-04-29"
    assert _extract_targets(goal) == ["Parker Solar Probe"]
    assert _extract_target(goal) == "Parker Solar Probe"


def test_extract_targets_no_false_positive_for_generic_wind():
    from spedas_agent_kit.workflows import _extract_targets

    assert _extract_targets("characterise solar-wind speed near the bow shock") == []


def test_extract_target_unchanged_returns_first_for_multimission():
    # Back-compat: the scalar helper still returns the first match only.
    from spedas_agent_kit.workflows import _extract_target

    goal = "Compare ACE, Wind, and OMNI upstream solar wind on 2015-10-16"
    assert _extract_target(goal) == "ACE"


def test_plan_spedas_observation_reports_all_inferred_targets():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "Compare ACE, Wind, and OMNI solar-wind magnetic field and plasma "
            "upstream of Earth"
        ),
        "start": "2015-10-16T00:00:00Z",
        "stop": "2015-10-18T00:00:00Z",
    }))
    assert data["status"] == "success"
    # Scalar target preserved for back-compat (first match).
    assert data["inferred"]["target"] == "ACE"
    # New: every named mission is surfaced for the comparison.
    assert data["inferred_targets"] == ["ACE", "Wind", "OMNI"]
    scope = next(step for step in data["plan"] if step["phase"] == "scope")
    assert scope["targets"] == ["ACE", "Wind", "OMNI"]


def test_plan_spedas_observation_explicit_target_not_overridden_by_inference():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Compare ACE, Wind, and OMNI upstream solar wind",
        "start": "2015-10-16T00:00:00Z",
        "stop": "2015-10-18T00:00:00Z",
        "target": "Wind",
    }))
    # An explicit target wins and is not inferred away...
    assert data["plan"][0]["target"] == "Wind"
    assert "target" not in data["inferred"]
    # ...but the goal still names several missions, so they remain visible,
    # with the explicit target leading the list.
    assert data["inferred_targets"] == ["Wind", "ACE", "OMNI"]


def test_plan_spedas_observation_single_target_has_singleton_targets_list():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Parker Solar Probe perihelion solar wind",
        "start": "2021-04-29T00:00:00Z",
        "stop": "2021-04-29T06:00:00Z",
    }))
    scope = next(step for step in data["plan"] if step["phase"] == "scope")
    assert scope["target"] == "Parker Solar Probe"
    assert scope["targets"] == ["Parker Solar Probe"]


# ---------------------------------------------------------------------------
# T010: Cluster is a four-spacecraft constellation, so multi-spacecraft phrasing
# is its most natural wording. The qualified-keyword matcher must recognise the
# multi-point/C1-C4/instrument forms, while still rejecting generic "cluster"
# uses (no false positive for "a cluster of substorms").
# ---------------------------------------------------------------------------

@_pytest_b1.mark.parametrize(
    "goal",
    [
        "Cluster multi-spacecraft magnetopause crossing",
        "Cluster multi-point magnetopause timing",
        "multi-spacecraft Cluster magnetopause study",
        "multi-point Cluster timing analysis",
        "Cluster four-spacecraft timing",
        "Cluster C1 C2 C3 C4 magnetopause",
        "Cluster C3 boundary crossing",
        "Cluster FGM magnetopause crossing",
        "Cluster CIS ion moments",
    ],
)
def test_extract_target_cluster_multispacecraft_phrasing(goal):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) == "Cluster"


@_pytest_b1.mark.parametrize(
    "goal",
    [
        "a cluster of substorms",
        "a cluster of events near the magnetopause",
        "clustering algorithm for boundary detection",
        "star cluster catalogue",
    ],
)
def test_extract_target_cluster_no_false_positive(goal):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) is None


def test_plan_spedas_observation_infers_cluster_for_multispacecraft_goal():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "Cluster multi-spacecraft magnetopause crossing on 2002-03-30 "
            "around 10:00 UT using FGM magnetic field"
        ),
    }))
    assert data["inferred"].get("target") == "Cluster"
    # The natural-language date/time should still be inferred alongside the target.
    assert data["inferred"].get("start") == "2002-03-30T09:00:00Z"
    assert data["inferred"].get("stop") == "2002-03-30T11:00:00Z"
    assert data["status"] == "success"


# ---------------------------------------------------------------------------
# Issue #30 / zhipu-1 nice-to-have: a non-positive interval (start >= stop)
# should be flagged rather than silently succeeding.
# ---------------------------------------------------------------------------

def test_plan_spedas_observation_flags_start_after_stop():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "study near 2015-10-16",
        "start": "2015-10-20T00:00:00Z",
    }))
    assert data["status"] == "needs_input"
    assert data["time_range_warning"]
    assert {"start", "stop"} <= set(data["needs_user_input"])


def test_plan_spedas_observation_valid_interval_no_warning():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "magnetopause study",
        "start": "2015-10-16T00:00:00Z",
        "stop": "2015-10-16T06:00:00Z",
        "data_sources": ["cdaweb"],
    }))
    assert data["status"] == "success"
    assert data["time_range_warning"] is None


# --- Issue #135: mission-aware canonical dataset / coverage / analysis guidance ---

def _mms_magnetopause_plan(monkeypatch=None, analysis_available=None):
    """Plan the canonical MMS magnetopause interval from issue #135.

    When ``analysis_available`` is set, the workflow-level analysis probe is
    monkeypatched so the test does not depend on whether the optional
    ``[analysis]`` extra is installed in the running environment.
    """
    from spedas_agent_kit import workflows as workflows_mod

    if analysis_available is not None:
        assert monkeypatch is not None
        monkeypatch.setattr(
            workflows_mod, "_mva_analysis_available", lambda: analysis_available
        )
    server = create_server()
    return json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "Screen MMS1 for a magnetopause current-sheet crossing: check magnetic "
            "field rotation (FGM), ion and electron moments (FPI), and spacecraft "
            "position"
        ),
        "target": "Earth magnetopause",
        "start": "2015-10-16T13:00:00Z",
        "stop": "2015-10-16T13:20:00Z",
    }))


def _candidate_dataset_ids(data):
    ids = []
    for candidate in data.get("mission_dataset_candidates", []):
        ids.extend(candidate.get("dataset_ids", []))
    return ids


def test_mms_magnetopause_plan_suggests_canonical_fgm_dataset():
    data = _mms_magnetopause_plan()
    assert data["status"] == "success"
    assert "MMS1_FGM_SRVY_L2" in _candidate_dataset_ids(data)


def test_mms_magnetopause_plan_suggests_fpi_ion_and_electron_moments():
    data = _mms_magnetopause_plan()
    ids = _candidate_dataset_ids(data)
    assert "MMS1_FPI_FAST_L2_DIS-MOMS" in ids  # ion moments
    assert "MMS1_FPI_FAST_L2_DES-MOMS" in ids  # electron moments


def test_mms_magnetopause_plan_suggests_mec_ephemeris_dataset():
    data = _mms_magnetopause_plan()
    assert "MMS1_MEC_SRVY_L2_EPHT89D" in _candidate_dataset_ids(data)


def test_mms_dataset_candidates_carry_per_probe_ids():
    """A single-probe goal (MMS1) keeps probe 1, but the constellation pattern
    is still discoverable so the agent can fan out to MMS2-4."""
    data = _mms_magnetopause_plan()
    fgm = next(
        c for c in data["mission_dataset_candidates"]
        if c["instrument"] == "FGM"
    )
    # The probe inferred from "MMS1" leads; the pattern documents the family.
    assert "MMS1_FGM_SRVY_L2" in fgm["dataset_ids"]
    assert fgm["dataset_id_pattern"] == "MMS{probe}_FGM_SRVY_L2"


def test_mms_magnetopause_plan_reports_coverage_status_for_interval():
    data = _mms_magnetopause_plan()
    fgm = next(
        c for c in data["mission_dataset_candidates"]
        if c["instrument"] == "FGM"
    )
    coverage = fgm["coverage"]
    # 2015-10-16 is inside MMS science coverage (starts 2015-09-01).
    assert coverage["mission_start"] == "2015-09-01"
    assert coverage["interval_within_coverage"] is True
    assert coverage["status"] == "ok"


def test_mms_plan_flags_interval_before_mission_coverage():
    from spedas_agent_kit import workflows as workflows_mod

    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "MMS1 FGM magnetic field survey near a magnetopause crossing",
        "target": "Earth magnetopause",
        "start": "2014-01-01T00:00:00Z",
        "stop": "2014-01-01T01:00:00Z",
    }))
    fgm = next(
        c for c in data["mission_dataset_candidates"]
        if c["instrument"] == "FGM"
    )
    coverage = fgm["coverage"]
    assert coverage["interval_within_coverage"] is False
    assert coverage["status"] == "before_coverage"


def test_mms_plan_includes_gse_gsm_frame_guidance():
    data = _mms_magnetopause_plan()
    fgm = next(
        c for c in data["mission_dataset_candidates"]
        if c["instrument"] == "FGM"
    )
    # FGM publishes both GSE and GSM; planning output must name them and warn
    # about keeping the field and position frames consistent.
    assert "gse" in [f.lower() for f in fgm["frames"]]
    assert "gsm" in [f.lower() for f in fgm["frames"]]
    blob = json.dumps(data).lower()
    assert "gse" in blob and "gsm" in blob
    assert "frame" in blob


def test_mms_plan_warns_when_analysis_layer_unavailable(monkeypatch):
    data = _mms_magnetopause_plan(monkeypatch, analysis_available=False)
    availability = data["analysis_availability"]
    assert availability["available"] is False
    # MVA / moments are the downstream steps called out by issue #135.
    blob = json.dumps(availability).lower()
    assert "minvar" in blob or "mva" in blob or "minimum variance" in blob
    # A concrete fallback path must be offered when the layer is missing.
    assert availability["fallback"]
    assert "pyspedas" in json.dumps(availability).lower()


def test_mms_plan_reports_analysis_layer_available(monkeypatch):
    data = _mms_magnetopause_plan(monkeypatch, analysis_available=True)
    assert data["analysis_availability"]["available"] is True


def test_mms_plan_analysis_availability_matches_registered_tools(monkeypatch):
    """Planner analysis guidance must use the same full gate as MCP registration.

    A partial PySPEDAS install may expose ``pyspedas.cotrans_tools.minvar`` while
    still lacking particle/tplot/wavelet pieces required by the registered
    analysis tool group. In that case the server hides analysis tools and the
    planner must not tell the researcher those in-kit tools can run.
    """
    from spedas_agent_kit import server as server_mod
    from spedas_agent_kit import workflows as workflows_mod

    monkeypatch.setattr(server_mod, "_analysis_dependencies_available", lambda: False)
    monkeypatch.setattr(workflows_mod, "analysis_dependencies_available", lambda: False)

    server = create_server()
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert "analyze_minvar_coordinates" not in names
    assert "compute_particle_moments" not in names

    data = _mms_magnetopause_plan()
    assert data["analysis_availability"]["available"] is False
    assert "not detected" in data["analysis_availability"]["guidance"]


def test_mms_plan_adds_mission_guidance_phase():
    data = _mms_magnetopause_plan()
    assert any(step["phase"] == "mission_guidance" for step in data["plan"])


def test_generic_plan_has_no_mission_dataset_candidates():
    """A goal with no recognized mission/instrument mapping stays lean and
    backward-compatible: the new keys exist but are empty, and the legacy plan
    shape is untouched."""
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Generic solar-wind survey",
        "start": "2020-01-01T00:00:00Z",
        "stop": "2020-01-02T00:00:00Z",
        "data_sources": ["cdaweb"],
    }))
    assert data["status"] == "success"
    assert data["mission_dataset_candidates"] == []
    # Legacy contract preserved.
    assert any(step["phase"] == "preserve_provenance" for step in data["plan"])
    assert data["low_level_tools_remain_available"] is True


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
# T006: THEMIS magnetotail substorm routing.
# A magnetospheric goal phrased in pure physics terms ("THEMIS magnetotail
# substorm") used to score only 1 on the bare "themis" token. With nothing above
# the score>1 selection threshold, plan_observation fell back to "all sources
# equally" and recommended the PDS planetary archive, which is explicitly
# not_for near-Earth CDAWeb observatories. The magnetospheric/substorm
# vocabulary must route these queries to CDAWeb alone.
# ---------------------------------------------------------------------------

def test_themis_magnetotail_substorm_routes_to_cdaweb_only():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "THEMIS magnetotail substorm injection workflow",
        "target": "THEMIS",
        "observables": ["magnetic field", "ion plasma", "particle injection"],
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]
    # The planetary archive must not be dredged up for a near-Earth study.
    assert "pds" not in data["recommended_sources"]


def test_themis_substorm_plan_recommends_cdaweb_not_pds():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "THEMIS magnetotail substorm on 2008-02-26 around 04:35 UT",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]
    # Target and a bounded window are inferred from the natural-language goal.
    assert data["inferred"]["target"] == "THEMIS"
    assert data["inferred"]["start"] == "2008-02-26T03:35:00Z"
    assert data["inferred"]["stop"] == "2008-02-26T05:35:00Z"
    phases = {step["phase"] for step in data["plan"]}
    assert {"discover_cdaweb", "fetch_or_compute_cdaweb", "preserve_provenance"} <= phases
    assert "discover_pds" not in phases


def test_planetary_routing_not_regressed_by_magnetospheric_keywords():
    """The T006 magnetospheric terms must not suppress PDS for planetary goals."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Juno magnetic field and plasma measurements near Jupiter",
        "target": "Jupiter",
    }))
    assert data["status"] == "success"
    assert "pds" in data["recommended_sources"]


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
    # Issue #113: default MMS catalog response should be compact enough for
    # agents (<12 KB) while preserving concrete candidates to proceed.
    assert len(raw.encode("utf-8")) < 12 * 1024
    loaded = json.loads(raw)
    assert loaded["mode"] == "compact"
    assert isinstance(loaded["payload"], dict)
    assert loaded["payload"]["catalog_mode"] == "compact"
    assert loaded["dataset_count"] > len(loaded["datasets"])
    assert loaded["filtered_dataset_count"] == loaded["dataset_count"]
    assert loaded["datasets_truncated"] is True
    assert loaded["datasets_limit"] == 10
    assert loaded["datasets_offset"] == 0
    assert loaded["datasets_next_offset"] == 10
    assert "dataset_candidates_by_instrument" in loaded
    assert loaded["datasets"], "expected MMS default page to include candidate datasets"
    first = loaded["datasets"][0]
    assert "browse_data_parameters(source_type='cdaweb'" in first["next_tools"][0]


def test_load_data_source_cdaweb_paginates_and_filters_mms_catalog():
    server = create_server()
    first = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "mms",
        "limit": 5,
        "instrument": "fgm",
        "dataset_query": "srvy",
    }))
    assert first["status"] == "success"
    assert first["datasets_limit"] == 5
    assert first["datasets_offset"] == 0
    assert len(first["datasets"]) <= 5
    assert first["filtered_dataset_count"] >= len(first["datasets"])
    assert first["datasets"], "expected FGM survey filter to return concrete candidates"
    assert all("fgm" in entry["dataset_id"].casefold() for entry in first["datasets"])
    assert all("srvy" in entry["dataset_id"].casefold() for entry in first["datasets"])
    if first["datasets_next_offset"] is not None:
        second = json.loads(_call_tool(server, "load_data_source", {
            "source_type": "cdaweb",
            "source_id": "mms",
            "limit": 5,
            "offset": first["datasets_next_offset"],
            "instrument": "fgm",
            "dataset_query": "srvy",
        }))
        assert second["datasets_offset"] == first["datasets_next_offset"]
        assert {d["dataset_id"] for d in first["datasets"]}.isdisjoint({d["dataset_id"] for d in second["datasets"]})


def test_load_data_source_cdaweb_themis_mag_prefers_spacecraft_bucket():
    # Regression for issue #136: instrument="mag" on THEMIS must prefer the
    # spacecraft "mag" bucket (which holds probe FGM) rather than being flooded
    # by the much larger "ground_mag" bucket via substring matching.
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "themis",
        "instrument": "mag",
        "limit": 30,
    }))
    assert data["status"] == "success"
    buckets = {entry["instrument"] for entry in data["datasets"]}
    assert buckets == {"mag"}, f"expected only the spacecraft mag bucket, got {buckets}"
    dataset_ids = {entry["dataset_id"] for entry in data["datasets"]}
    assert {"THA_L2_FGM", "THB_L2_FGM"} <= dataset_ids
    assert not any("THG_L2_MAG" in entry["dataset_id"] for entry in data["datasets"])


def test_load_data_source_cdaweb_themis_fgm_finds_probe_fgm():
    # Probe FGM must remain findable via instrument="fgm".
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "themis",
        "instrument": "fgm",
        "limit": 30,
    }))
    assert data["status"] == "success"
    dataset_ids = {entry["dataset_id"] for entry in data["datasets"]}
    assert {"THA_L2_FGM", "THB_L2_FGM", "THC_L2_FGM"} <= dataset_ids


def test_load_data_source_cdaweb_themis_ground_mag_remains_discoverable():
    # Ground magnetometers must stay reachable via the explicit bucket name.
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "themis",
        "instrument": "ground_mag",
        "limit": 30,
    }))
    assert data["status"] == "success"
    buckets = {entry["instrument"] for entry in data["datasets"]}
    assert buckets == {"ground_mag"}, f"expected only the ground_mag bucket, got {buckets}"
    assert any("THG_L2_MAG" in entry["dataset_id"] for entry in data["datasets"])


def test_load_data_source_cdaweb_full_mode_preserves_legacy_prompt_payload():
    server = create_server()
    loaded = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "mms",
        "mode": "full",
        "limit": 5,
    }))
    assert loaded["status"] == "success"
    assert loaded["mode"] == "full"
    assert isinstance(loaded["payload"], str)
    assert len(loaded["datasets"]) == 5


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


# ---------------------------------------------------------------------------
# Batch K — error contract, source_id validation, response-size guard
# (issues #25, #27, #28)
# ---------------------------------------------------------------------------

from spedas_agent_kit.server import (  # noqa: E402
    _MAX_RESPONSE_BYTES,
    _error_response,
    _sanitize_message,
    _size_guarded,
)


def test_sanitize_message_redacts_posix_and_windows_paths():
    # POSIX absolute path (real load_data_source leak from issue #25).
    out = _sanitize_message(
        "Observatory file not found: /Users/someone/.cdawebmcp/observatories/MMS1.json"
    )
    assert "/Users/" not in out
    assert ".cdawebmcp" not in out
    assert "<path>" in out
    # Windows absolute path.
    out_win = _sanitize_message(r"Mission file not found: C:\Users\x\cache\m.json here")
    assert "C:\\" not in out_win
    assert "<path>" in out_win


def test_sanitize_message_redacts_external_urls():
    out = _sanitize_message(
        "Field required (type=missing) https://errors.pydantic.dev/2.13/v/missing"
    )
    assert "http" not in out
    assert "<url-redacted>" in out


def test_sanitize_message_does_not_over_redact_plain_text():
    # Slashes that are not absolute paths (ratios, frame lists) must survive so
    # error messages stay useful.
    assert _sanitize_message("ratio 3/4 and a/b notation") == "ratio 3/4 and a/b notation"
    frames = "valid frames are GSE, GSM, RTN"
    assert _sanitize_message(frames) == frames


def test_sanitize_message_collapses_multiline_to_single_line():
    # SPICE tracebacks carry an 80-char banner across many lines (issue #27/#28);
    # the sanitized message must be a single line so it cannot overflow the
    # 64KB stdio line buffer.
    multiline = "error:\n" + ("=" * 80) + "\nSPICE(UNKNOWNFRAME)\n" + ("=" * 80)
    out = _sanitize_message(multiline)
    assert "\n" not in out


def test_error_response_has_uniform_contract():
    raw = _error_response(
        "unknown_source_id",
        "Source ID 'MMS1' not found in /Users/x/cache/MMS1.json",
        hint="Did you mean 'mms'?",
        source_type="cdaweb",
        source_id="MMS1",
    )
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unknown_source_id"
    assert payload["hint"] == "Did you mean 'mms'?"
    assert payload["source_type"] == "cdaweb"
    # The message is sanitized by default — no path leak even when the caller
    # passes a backend string that embedded one.
    assert "/Users/" not in payload["message"]


def test_size_guard_passes_small_payload_unchanged():
    small = json.dumps({"status": "success", "x": 1})
    assert _size_guarded(small) == small


def test_size_guard_replaces_oversized_payload_with_compact_error():
    oversized = json.dumps({"status": "success", "payload": "X" * (_MAX_RESPONSE_BYTES + 5000)})
    assert len(oversized.encode("utf-8")) > _MAX_RESPONSE_BYTES
    guarded = _size_guarded(oversized, source_type="cdaweb")
    # Measured against actual serialized bytes, the guard returns a compact,
    # structured error well under the limit (issue #28).
    assert len(guarded.encode("utf-8")) < _MAX_RESPONSE_BYTES
    payload = json.loads(guarded)
    assert payload["status"] == "error"
    assert payload["code"] == "response_too_large"
    assert payload["response_bytes"] > payload["max_bytes"]
    assert payload["source_type"] == "cdaweb"
    assert "hint" in payload


def test_load_data_source_invalid_cdaweb_id_returns_structured_error_without_path():
    server = create_server()
    raw = _call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "MMS1",
    })
    # No filesystem path may appear anywhere in the response (issue #25).
    assert "/Users/" not in raw
    assert "/var/folders" not in raw
    assert ".cdawebmcp" not in raw
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unknown_source_id"
    assert payload["source_id"] == "MMS1"
    # A typo for the real observatory ("mms") must be suggested for recovery.
    assert any(s.lower() == "mms" for s in payload["suggestions"])
    assert payload["valid_ids_sample"]


def test_load_data_source_invalid_pds_id_returns_structured_error_without_path():
    server = create_server()
    raw = _call_tool(server, "load_data_source", {
        "source_type": "pds",
        "source_id": "NOT_A_MISSION",
    })
    assert "/Users/" not in raw
    assert "site-packages" not in raw
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unknown_source_id"
    assert payload["source_id"] == "NOT_A_MISSION"


def test_load_data_source_valid_ids_still_succeed():
    server = create_server()
    cdaweb = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "cdaweb",
        "source_id": "mms",
    }))
    assert cdaweb["status"] == "success"
    pds = json.loads(_call_tool(server, "load_data_source", {
        "source_type": "pds",
        "source_id": "CASSINI_PPI",
    }))
    assert pds["status"] == "success"


def test_geometry_tool_invalid_body_returns_structured_error():
    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "NONEXISTENT_BODY",
        "time": "2020-01-01T00:00:00",
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert "code" in payload
    # Single-line message, no path leak (issues #27/#28).
    assert "\n" not in payload["message"]
    assert "/Users/" not in raw


def test_wrapped_tool_responses_stay_within_size_limit():
    server = create_server()
    # The discovery/listing tools most at risk of overflowing the 64KB stdio
    # buffer (issue #28) must stay within the safety limit.
    for source_type in ("cdaweb", "pds", "spice"):
        raw = _call_tool(server, "browse_data_sources", {"source_type": source_type})
        assert len(raw.encode("utf-8")) <= _MAX_RESPONSE_BYTES, source_type


# ---------------------------------------------------------------------------
# Batch K should-fixes — complete the uniform error contract (#27)
# ---------------------------------------------------------------------------

import inspect  # noqa: E402

from spedas_agent_kit.server import _classify_exception  # noqa: E402


def _assert_uniform_error(payload: dict) -> None:
    """Every user-facing tool error must carry status/code/message (issue #27)."""
    assert payload["status"] == "error"
    assert isinstance(payload.get("code"), str) and payload["code"]
    assert isinstance(payload.get("message"), str) and payload["message"]
    # The legacy duplicate ``error`` key must be gone from converted surfaces.
    assert "error" not in payload, payload


def test_data_layer_unknown_source_type_uses_uniform_envelope():
    server = create_server()
    # All five unified data-layer routing tools must report an unknown
    # source_type through the uniform envelope, not the legacy status/error shape.
    cases = [
        ("browse_data_sources", {"source_type": "bogus"}),
        ("load_data_source", {"source_type": "bogus", "source_id": "x"}),
        ("browse_data_parameters", {"source_type": "bogus", "dataset_id": "x"}),
        ("fetch_data_product", {"source_type": "bogus", "dataset_id": "x", "parameters": ["a"]}),
        ("manage_data_cache", {"source_type": "bogus"}),
    ]
    for tool, args in cases:
        payload = json.loads(_call_tool(server, tool, args))
        _assert_uniform_error(payload)
        assert payload["code"] == "invalid_argument", tool
        assert "bogus" in payload["message"], tool
        assert payload["allowed"], tool


def test_fetch_data_product_arg_validation_uses_uniform_envelope():
    server = create_server()
    # Missing required cdaweb args.
    cdaweb = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "cdaweb", "dataset_id": "x", "parameters": ["a"],
    }))
    _assert_uniform_error(cdaweb)
    assert cdaweb["code"] == "invalid_argument"
    # Missing required pds args.
    pds = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "pds", "dataset_id": "x", "parameters": ["a"],
    }))
    _assert_uniform_error(pds)
    assert pds["source_type"] == "pds"
    # SPICE measurement-fetch rejection keeps its recommended_tools extra.
    spice = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "spice", "dataset_id": "juno", "parameters": ["ephemeris"],
    }))
    _assert_uniform_error(spice)
    assert "get_ephemeris" in spice["recommended_tools"]


def test_no_legacy_status_error_returns_on_data_layer_and_analysis_surfaces():
    """Static guard: no remaining ``{"status":"error","error":...}`` tool returns.

    Greps the rendered source of the unified data-layer routing tools and the
    three analysis tools for the legacy duplicate-``error``-key shape so the
    uniform contract (issue #27) cannot silently regress.
    """
    from spedas_agent_kit import server as server_mod
    from spedas_agent_kit.analysis import coords as coords_mod

    # The legacy shape always pairs a status="error" dict with a bare "error":
    # key. The uniform envelope uses code=/message= instead. Assert the literal
    # ``"error":`` key does not appear as a dict key in either module's source.
    for mod in (server_mod, coords_mod):
        src = inspect.getsource(mod)
        assert '"error":' not in src, (
            f"legacy status/error/error return still present in {mod.__name__}"
        )


def test_analysis_tools_are_wrapped_in_safe_tool():
    server = create_server(include_analysis_tools=True)
    # Unexpected exceptions from pyspedas/OS/file-writes must surface as the
    # structured envelope, not a raw traceback. A non-existent input_file makes
    # the impl raise ValueError, which _safe_tool/_error must convert.
    # transform: bad frame -> impl _error (uniform) ; missing file -> ValueError.
    bad_frame = json.loads(_call_tool(server, "transform_timeseries_coordinates", {
        "input_file": "/nonexistent/in.csv",
        "coord_in": "not_a_frame",
        "coord_out": "gse",
        "output_file": "/tmp/out.csv",
    }))
    _assert_uniform_error(bad_frame)
    assert bad_frame["code"] == "invalid_argument"

    missing_file = json.loads(_call_tool(server, "analyze_minvar_coordinates", {
        "input_file": "/nonexistent/path/in.csv",
        "output_dir": "/tmp",
    }))
    _assert_uniform_error(missing_file)


def test_render_tplot_registered_and_validates(tmp_path: Path):
    server = create_server(include_analysis_tools=True)
    # Pure validation path (no matplotlib needed): non-PNG output is rejected
    # through the server with the uniform structured envelope.
    bad_ext = json.loads(_call_tool(server, "render_tplot", {
        "input_files": [str(tmp_path / "in.npz")],
        "output_file": str(tmp_path / "out.pdf"),
    }))
    _assert_uniform_error(bad_ext)
    assert bad_ext["code"] == "invalid_argument"

    # Empty input list -> structured invalid_argument, not a traceback.
    empty = json.loads(_call_tool(server, "render_tplot", {
        "input_files": [],
        "output_file": str(tmp_path / "out.png"),
    }))
    _assert_uniform_error(empty)

    # New scatter/xy arguments are exposed through MCP and validate before any
    # matplotlib import or file loading.
    bad_components = json.loads(_call_tool(server, "render_tplot", {
        "input_files": [str(tmp_path / "a.npz"), str(tmp_path / "b.npz")],
        "output_file": str(tmp_path / "out.png"),
        "panel_types": "xy",
        "x_component": [0],
        "y_component": [1, 2],
    }))
    _assert_uniform_error(bad_components)
    assert "x_component" in bad_components["message"]


def test_render_tplot_missing_file_is_structured(tmp_path: Path):
    server = create_server(include_analysis_tools=True)
    missing = json.loads(_call_tool(server, "render_tplot", {
        "input_files": [str(tmp_path / "nope.npz")],
        "output_file": str(tmp_path / "out.png"),
    }))
    _assert_uniform_error(missing)
    assert missing["code"] == "resource_not_found"


def test_render_tplot_wrapped_in_safe_tool(monkeypatch):
    server = create_server(include_analysis_tools=True)
    import spedas_agent_kit.analysis.plotting as plotting_mod

    def _boom(*args, **kwargs):
        raise OSError("disk write failed at /Users/secret/path")

    monkeypatch.setattr(plotting_mod, "render_tplot", _boom)
    raw = _call_tool(server, "render_tplot", {
        "input_files": ["a.npz"], "output_file": "o.png",
    })
    payload = json.loads(raw)
    _assert_uniform_error(payload)
    assert payload["tool"] == "render_tplot"
    assert "/Users/" not in raw


def test_analysis_safe_tool_converts_unexpected_exception(monkeypatch):
    server = create_server(include_analysis_tools=True)
    # Force an unexpected (non-ValueError) exception out of the impl to prove the
    # @_safe_tool decorator — not just the impl's own try/except — wraps it.
    import spedas_agent_kit.analysis.coords as coords_mod

    def _boom(*args, **kwargs):
        raise OSError("disk write failed at /Users/secret/path")

    monkeypatch.setattr(coords_mod, "generate_fac_matrix", _boom)
    raw = _call_tool(server, "generate_fac_matrix", {
        "mag_file": "m.npy", "output_file": "o.npy",
    })
    payload = json.loads(raw)
    _assert_uniform_error(payload)
    # _safe_tool tags the failing tool and sanitizes the path out of the message.
    assert payload["tool"] == "generate_fac_matrix"
    assert "/Users/" not in raw


def test_spice_keyerror_classified_as_geometry_error():
    # A geometry KeyError (SPICE backend "Cannot resolve body name 'X'") must be
    # classified as geometry_error with a geometry hint, not the generic
    # KeyError -> invalid_argument mapping (issue #27 should-fix #3).
    code, hint = _classify_exception(KeyError("Cannot resolve body name 'NOPE'"))
    assert code == "geometry_error"
    assert hint and "browse_data_sources(source_type='spice')" in hint
    # A frame-resolution KeyError too.
    code_f, _ = _classify_exception(KeyError("frame 'BOGUS' is not recognized"))
    assert code_f == "geometry_error"
    # A plain dict-miss KeyError stays a generic invalid_argument.
    code_plain, _ = _classify_exception(KeyError("some_internal_dict_key"))
    assert code_plain == "invalid_argument"


def test_get_ephemeris_invalid_body_now_unsupported_spice_target():
    # Issue #26: an unsupported target is now caught by the network-free preflight
    # *before* the backend, so it returns the dedicated unsupported_spice_target
    # error (with alternatives) rather than the generic geometry_error that only
    # surfaced after touching the SPICE backend. The geometry_error classifier still
    # covers genuinely unguarded SPICE failures (see
    # test_spice_keyerror_classified_as_geometry_error).
    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "NONEXISTENT_BODY",
        "time": "2020-01-01T00:00:00",
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unsupported_spice_target"
    assert "browse_data_sources(source_type='spice')" in payload["hint"]
    assert "/Users/" not in raw


def test_error_response_sanitizes_string_extras():
    raw = _error_response(
        "unknown_source_id",
        "lookup failed",
        leaked_path="cache at /Users/x/.cdawebmcp/MMS1.json here",
        allowed=["cdaweb", "pds"],
        count=3,
    )
    payload = json.loads(raw)
    # String extras are path-redacted to honor the docstring contract (#25/#27)...
    assert "/Users/" not in payload["leaked_path"]
    assert "<path>" in payload["leaked_path"]
    # ...while non-string extras and plain-text lists pass through untouched.
    assert payload["allowed"] == ["cdaweb", "pds"]
    assert payload["count"] == 3


# ---------------------------------------------------------------------------
# Batch L — geometry/SPICE safety: unsupported-target validation (#26) and a
# pre-download confirmation gate (#29).
#
# These tests must NEVER trigger a real kernel download. They:
#   * isolate the kernel cache to an empty tmp dir via XHELIO_SPICE_KERNEL_DIR
#     and reset the KernelManager singleton, so "missing kernels" is deterministic;
#   * monkeypatch spedas_agent_kit.backends.spice get_state/get_trajectory/transform_vector to raise
#     if ever called, proving the preflight short-circuits before the backend.
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

from spedas_agent_kit.server import (  # noqa: E402
    _spice_missing_kernels,
    _spice_resolve_target,
    _spice_supported_frames,
)


@pytest.fixture
def empty_kernel_cache(tmp_path, monkeypatch):
    """Point the in-tree SPICE backend at an empty kernel cache and reset its singleton.

    Yields the cache dir. With no files present, every mission's required
    kernels are "missing", so the #29 confirmation gate fires deterministically
    regardless of the developer's real ~/.xhelio_spice cache.
    """
    import spedas_agent_kit.backends.spice.kernel_manager as km_mod

    cache_dir = tmp_path / "kernels"
    cache_dir.mkdir()
    monkeypatch.setenv("XHELIO_SPICE_KERNEL_DIR", str(cache_dir))
    monkeypatch.setattr(km_mod, "_instance", None)
    yield cache_dir
    # Reset the singleton again so later tests do not inherit the tmp cache.
    monkeypatch.setattr(km_mod, "_instance", None)


@pytest.fixture
def no_backend_downloads(monkeypatch):
    """Make any real in-tree SPICE backend geometry/download call fail loudly.

    The preflight is supposed to return before these run; if it does not, the
    test fails with a clear marker instead of attempting a network download.
    """
    import spedas_agent_kit.backends.spice as spice_backend

    def _boom(*args, **kwargs):  # pragma: no cover - only hit on regression
        raise AssertionError("backend geometry call reached — preflight did not gate it")

    monkeypatch.setattr(spice_backend, "get_state", _boom)
    monkeypatch.setattr(spice_backend, "get_trajectory", _boom)
    monkeypatch.setattr(spice_backend, "transform_vector", _boom)
    return _boom


# --- #26: unsupported-target validation ------------------------------------

def test_resolve_target_distinguishes_supported_and_unsupported():
    assert _spice_resolve_target("PSP")["resolved"] is True
    assert _spice_resolve_target("psp")["key"] == "PSP"
    # SUN/EARTH resolve but are covered by generic kernels, not mission kernels.
    sun = _spice_resolve_target("SUN")
    assert sun["resolved"] is True and sun["has_kernels"] is False
    # MMS / MMS1 are CDAWeb missions with no SPICE kernels.
    assert _spice_resolve_target("MMS1")["resolved"] is False
    assert _spice_resolve_target("MMS")["resolved"] is False


@pytest.mark.parametrize("bad_target", ["MMS1", "MMS"])
def test_get_ephemeris_unsupported_target_is_structured(bad_target, no_backend_downloads):
    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": bad_target,
        "time": "2023-09-10T00:00:00",
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unsupported_spice_target"
    assert payload["spice_target"] == bad_target
    # Routes the agent to alternatives and CDAWeb for MMS, no raw traceback/path.
    assert "browse_data_sources(source_type='spice')" in payload["hint"]
    assert "cdaweb" in payload["hint"].lower()
    assert payload["supported_targets_sample"]
    assert "Cannot resolve body name" not in raw
    assert "/Users/" not in raw and "\n" not in payload["message"]


def test_get_ephemeris_unsupported_observer_is_structured(no_backend_downloads):
    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "PSP",
        "observer": "MMS1",
        "time": "2023-09-10T00:00:00",
        "allow_kernel_download": True,  # prove it's the observer, not the cache gate
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unsupported_spice_target"
    assert payload["spice_target"] == "MMS1"
    assert payload["role"] == "observer"


def test_compute_distance_unsupported_target_is_structured(no_backend_downloads):
    server = create_server()
    raw = _call_tool(server, "compute_distance", {
        "target1": "PSP",
        "target2": "MMS1",
        "time_start": "2023-09-10T00:00:00",
        "time_end": "2023-09-11T00:00:00",
        "allow_kernel_download": True,
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unsupported_spice_target"
    assert payload["spice_target"] == "MMS1"


def test_transform_coordinates_unsupported_spacecraft_is_structured(no_backend_downloads):
    server = create_server()
    raw = _call_tool(server, "transform_coordinates", {
        "vector": [1.0, 0.0, 0.0],
        "time": "2023-09-10T00:00:00",
        "from_frame": "RTN",
        "to_frame": "J2000",
        "spacecraft": "MMS1",
        "allow_kernel_download": True,
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "unsupported_spice_target"




def _assert_clean_unknown_frame_error(payload, raw, *, frame, role, tool):
    assert payload["status"] == "error"
    assert payload["code"] == "invalid_argument"
    assert payload["tool"] == tool
    assert payload["frame"] == frame
    assert payload["role"] == role
    assert payload["message"] == f"unknown frame '{frame}'"
    assert "load_data_source(source_type='spice'" in payload["hint"]
    assert "J2000" in payload["supported_frames"]
    assert "GSE" in payload["supported_frames"]
    assert "CSPICE" not in raw
    assert "SPICE(UNKNOWNFRAME)" not in raw
    assert "Toolkit version" not in raw
    assert "-->" not in raw
    assert "\n" not in payload["message"]


def test_get_ephemeris_unknown_frame_is_clean_structured_error(no_backend_downloads):
    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "PSP",
        "time": "2025-06-19T09:29:00",
        "frame": "NOT_A_FRAME",
        "allow_kernel_download": True,
    })
    payload = json.loads(raw)
    _assert_clean_unknown_frame_error(
        payload, raw, frame="NOT_A_FRAME", role="frame", tool="get_ephemeris"
    )


def test_transform_coordinates_unknown_frame_is_clean_structured_error(no_backend_downloads):
    server = create_server()
    raw = _call_tool(server, "transform_coordinates", {
        "vector": [1.0, 0.0, 0.0],
        "time": "2025-06-19T09:29:00",
        "from_frame": "BOGUS",
        "to_frame": "GSE",
        "allow_kernel_download": True,
    })
    payload = json.loads(raw)
    _assert_clean_unknown_frame_error(
        payload, raw, frame="BOGUS", role="from_frame", tool="transform_coordinates"
    )


def test_supported_frame_catalog_for_errors_includes_coordinate_frames():
    server = create_server()
    # The frame catalog (used to validate transform_coordinates frame args) is
    # surfaced via the frames source_id; a mission source_id now returns
    # mission-specific metadata instead (issue #134).
    listed = json.loads(_call_tool(server, "load_data_source", {"source_type": "spice", "source_id": "frames"}))
    supported = _spice_supported_frames()
    for entry in listed["payload"]:
        assert entry["frame"] in supported
    # Backend aliases are also accepted/surfaced when available.
    assert "ECLIPTIC" in supported


# --- #29: pre-download confirmation gate -----------------------------------

def test_missing_kernels_reports_uncached_mission(empty_kernel_cache):
    info = _spice_missing_kernels(["PSP"])
    assert info["cached"] is False
    assert "PSP" in info["missing_missions"]
    assert "GENERIC" in info["missing_missions"]
    # Cache dir is path-redacted so the envelope never leaks a local path.
    assert "/Users/" not in info["cache_dir"]
    assert info["missing_files"]


def test_get_ephemeris_uncached_returns_needs_confirmation(empty_kernel_cache, no_backend_downloads):
    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "PSP",
        "time": "2024-01-01T00:00:00",
    })
    payload = json.loads(raw)
    assert payload["status"] == "needs_confirmation"
    assert payload["code"] == "kernel_download_required"
    assert "PSP" in payload["missions"]
    assert payload["missing_kernel_files"]
    # Tells the agent exactly how to opt in.
    assert any("manage_data_cache" in step and "source_type='spice'" in step for step in payload["next_steps"])
    assert any("allow_kernel_download" in step for step in payload["next_steps"])
    # No path leak, single-line message, safely under the size limit.
    assert "/Users/" not in raw
    assert len(raw.encode("utf-8")) < _MAX_RESPONSE_BYTES


def test_transform_coordinates_uncached_generic_kernels_gated(empty_kernel_cache, no_backend_downloads):
    # Even with no spacecraft, a frame transform needs the generic kernels
    # (~120 MB) — the gate must fire so that download is not silent either.
    server = create_server()
    raw = _call_tool(server, "transform_coordinates", {
        "vector": [1.0, 2.0, 3.0],
        "time": "2024-01-01T00:00:00",
        "from_frame": "GSE",
        "to_frame": "J2000",
    })
    payload = json.loads(raw)
    assert payload["status"] == "needs_confirmation"
    assert payload["code"] == "kernel_download_required"
    assert "GENERIC" in payload["missions"]


def test_get_ephemeris_cached_target_proceeds_to_backend(empty_kernel_cache, monkeypatch):
    # When all required kernels are present on disk, the gate must NOT fire and
    # the real geometry path runs. We fake-cache the generic + PSP files and stub
    # get_state so no download or SPICE call is needed.
    import spedas_agent_kit.backends.spice as spice_backend
    from spedas_agent_kit.backends.spice.missions import GENERIC_KERNELS, MISSION_KERNELS

    for fname in list(GENERIC_KERNELS) + list(MISSION_KERNELS["PSP"]):
        (empty_kernel_cache / fname).write_bytes(b"x")  # non-zero size = "cached"

    def _fake_get_state(target, observer, time, frame):
        return {"x_km": 1.0, "y_km": 2.0, "z_km": 3.0, "target": target,
                "observer": observer, "frame": frame, "time": time}

    monkeypatch.setattr(spice_backend, "get_state", _fake_get_state)

    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "PSP",
        "time": "2024-01-01T00:00:00",
    })
    payload = json.loads(raw)
    assert payload["status"] == "success"
    assert payload["x_km"] == 1.0


def test_get_ephemeris_allow_kernel_download_bypasses_gate(empty_kernel_cache, monkeypatch):
    # allow_kernel_download=True is the explicit opt-in: the gate is skipped even
    # though the cache is empty, and the (stubbed) backend runs.
    import spedas_agent_kit.backends.spice as spice_backend

    def _fake_get_state(target, observer, time, frame):
        return {"x_km": 9.0, "target": target, "observer": observer,
                "frame": frame, "time": time}

    monkeypatch.setattr(spice_backend, "get_state", _fake_get_state)

    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "PSP",
        "time": "2024-01-01T00:00:00",
        "allow_kernel_download": True,
    })
    payload = json.loads(raw)
    assert payload["status"] == "success"
    assert payload["x_km"] == 9.0


def test_transform_coordinates_output_vector_is_json_array(empty_kernel_cache, monkeypatch):
    import numpy as np
    import spedas_agent_kit.backends.spice as spice_backend

    def _fake_transform_vector(vector, time, from_frame, to_frame, spacecraft=None):
        return np.array([1.0, 2.5, 3.0])

    monkeypatch.setattr(spice_backend, "transform_vector", _fake_transform_vector)
    server = create_server()
    raw = _call_tool(server, "transform_coordinates", {
        "vector": [1.0, 0.0, 0.0],
        "time": "2025-06-19T09:29:00",
        "from_frame": "J2000",
        "to_frame": "ECLIPJ2000",
        "allow_kernel_download": True,
    })
    payload = json.loads(raw)
    assert payload["status"] == "success"
    assert payload["output_vector"] == [1.0, 2.5, 3.0]
    assert not isinstance(payload["output_vector"], str)


def test_geometry_tools_expose_allow_kernel_download_param():
    import asyncio

    server = create_server()
    tools = asyncio.run(server.list_tools())
    schemas = {t.name: t.inputSchema for t in tools}
    for name in ("get_ephemeris", "compute_distance", "transform_coordinates"):
        props = schemas[name]["properties"]
        assert "allow_kernel_download" in props, name
        # Optional, defaults to the safe (gated) behavior.
        assert name not in schemas[name].get("required", [])
        assert props["allow_kernel_download"].get("default") is False


# ---------------------------------------------------------------------------
# Issue #30: plan_spedas_observation should extract dates and mission names
# from the natural-language science_goal before declaring "needs_input".
# Explicit start/stop/target parameters must still override anything inferred.
# ---------------------------------------------------------------------------

def test_plan_observation_infers_mms_datetime_from_goal_text():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "MMS magnetopause crossing magnetic field and ion data on 2015-10-16 around 13:06 UT",
    }))
    assert data["status"] == "success"
    assert data["needs_user_input"] == []
    scope = next(step for step in data["plan"] if step["phase"] == "scope")
    # Single "around" datetime -> symmetric +/- 1 hour window.
    assert scope["time_range"] == {
        "start": "2015-10-16T12:06:00Z",
        "stop": "2015-10-16T14:06:00Z",
    }
    assert scope["target"] == "MMS"
    inferred = data["inferred"]
    assert inferred["start"] == "2015-10-16T12:06:00Z"
    assert inferred["stop"] == "2015-10-16T14:06:00Z"
    assert inferred["target"] == "MMS"
    assert "cdaweb" in data["recommended_sources"]


def test_plan_observation_infers_psp_date_only_from_goal_text():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Parker Solar Probe perihelion solar wind magnetic field near 2021-11-21",
    }))
    assert data["status"] == "success"
    assert data["needs_user_input"] == []
    scope = next(step for step in data["plan"] if step["phase"] == "scope")
    # Date-only goal -> full-day interval [00:00:00Z, next day 00:00:00Z).
    assert scope["time_range"] == {
        "start": "2021-11-21T00:00:00Z",
        "stop": "2021-11-22T00:00:00Z",
    }
    assert scope["target"] == "Parker Solar Probe"
    inferred = data["inferred"]
    assert inferred["start"] == "2021-11-21T00:00:00Z"
    assert inferred["stop"] == "2021-11-22T00:00:00Z"
    assert inferred["target"] == "Parker Solar Probe"


def test_plan_observation_explicit_params_override_extracted_dates():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "MMS magnetopause crossing on 2015-10-16 around 13:06 UT",
        "start": "2017-01-01T00:00:00Z",
        "stop": "2017-01-02T00:00:00Z",
        "target": "Cluster",
    }))
    assert data["status"] == "success"
    scope = next(step for step in data["plan"] if step["phase"] == "scope")
    assert scope["time_range"] == {
        "start": "2017-01-01T00:00:00Z",
        "stop": "2017-01-02T00:00:00Z",
    }
    assert scope["target"] == "Cluster"
    # Explicit values win; they are not listed as inferred.
    assert "start" not in data["inferred"]
    assert "stop" not in data["inferred"]
    assert "target" not in data["inferred"]


def test_plan_observation_does_not_infer_wind_mission_from_solar_wind_phrase():
    # "solar wind" is a plasma observable, not the Wind spacecraft. A goal that
    # only mentions the solar wind (no actual mission) must not silently claim
    # target="Wind" — that would misrepresent the science.
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Characterize solar wind turbulence on 2018-03-01",
    }))
    assert "target" not in data["inferred"]
    scope = next(step for step in data["plan"] if step["phase"] == "scope")
    assert scope["target"] is None


def test_plan_observation_infers_wind_spacecraft_when_named_explicitly():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Wind spacecraft magnetic field upstream of Earth on 2018-03-01",
    }))
    assert data["inferred"]["target"] == "Wind"


def test_plan_observation_without_date_still_needs_input_with_helpful_fields():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "MMS magnetopause crossing magnetic field and ion data",
    }))
    assert data["status"] == "needs_input"
    assert set(data["needs_user_input"]) == {"start", "stop"}
    # Target was still inferable and surfaced to help the caller.
    assert data["inferred"]["target"] == "MMS"
    scope = next(step for step in data["plan"] if step["phase"] == "scope")
    assert scope["target"] == "MMS"


# ---------------------------------------------------------------------------
# Issues #21 / #22: HAPI + FDSN/MTH5 data-source support in the unified layer.
# These verify the source_type routing and that the dedicated tools surface a
# clean missing_dependency envelope without the optional [hapi]/[fdsn] extras
# installed (so MCP list-tools and base routing stay safe).
# ---------------------------------------------------------------------------


def test_browse_data_sources_all_lists_hapi_and_fdsn():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "all"}))
    types = {entry["source_type"] for entry in data["source_types"]}
    assert {"hapi", "fdsn"} <= types


def test_browse_data_sources_hapi_points_to_dedicated_tool():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "hapi"}))
    assert data["status"] == "success"
    assert data["source_type"] == "hapi"
    assert any("browse_hapi_catalog" in t for t in data["next_tools"])
    assert data["direct_tool_gate"]["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert data["direct_tool_gate"]["advertised"] is False


def test_browse_data_sources_fdsn_alias_mth5():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "mth5"}))
    assert data["status"] == "success"
    assert data["source_type"] == "fdsn"
    assert data["direct_tool_gate"]["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert data["direct_tool_gate"]["advertised"] is False


def test_unified_load_data_source_hapi_routes_to_dedicated_tool():
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {"source_type": "hapi", "source_id": "x"}))
    assert data["status"] == "error"
    assert data["code"] == "use_dedicated_tool"
    assert "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1" in data["hint"]
    assert data["direct_tool_gate"]["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert data["direct_tool_gate"]["advertised"] is False
    assert "browse_hapi_catalog" in data["recommended_tools"]


def test_unified_fetch_data_product_fdsn_routes_to_dedicated_tool():
    server = create_server()
    data = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "fdsn", "dataset_id": "x", "parameters": ["p"],
    }))
    assert data["status"] == "error"
    assert data["code"] == "use_dedicated_tool"
    assert "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1" in data["hint"]
    assert data["direct_tool_gate"]["env_flag"] == "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1"
    assert data["direct_tool_gate"]["advertised"] is False
    assert "fetch_fdsn_data" in data["recommended_tools"]


def test_unified_browse_data_parameters_unknown_lists_new_sources():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_parameters", {
        "source_type": "nope", "dataset_id": "x",
    }))
    assert data["status"] == "error"
    assert data["code"] == "invalid_argument"
    assert {"hapi", "fdsn"} <= set(data["allowed"])


# Issue #137: wide products (e.g. THA_L2_ESA, ~200 params/~53 KB) overflow the
# response budget. browse_data_parameters gains parameter_query/limit/offset so
# agents can narrow parameter metadata before fetching data. The bundled PDS
# dataset below resolves offline and exposes 8 distinctly-named parameters.
_PDS_PARAM_DATASET = "pds3:JNO-J-3-FGM-CAL-V1.0:DATA"


def _browse_pds_params(server, **extra):
    args = {"source_type": "pds", "dataset_id": _PDS_PARAM_DATASET}
    args.update(extra)
    return json.loads(_call_tool(server, "browse_data_parameters", args))


def test_browse_data_parameters_unfiltered_returns_all_params():
    server = create_server()
    data = _browse_pds_params(server)
    assert data["status"] == "success"
    params = data["payload"]["parameters"]
    assert len(params) == 8
    # Backwards-compatible: no pagination metadata when no filter/page applied.
    assert "parameter_page" not in data["payload"]


def test_browse_data_parameters_query_filters_by_name():
    server = create_server()
    # "BX PLANETOCENTRIC" is unique to a single parameter name.
    data = _browse_pds_params(server, parameter_query="bx planetocentric")
    assert data["status"] == "success"
    page = data["payload"]["parameter_page"]
    assert page["query"] == "bx planetocentric"
    assert page["total"] == 1
    assert page["returned"] == 1
    names = [p["name"] for p in data["payload"]["parameters"]]
    assert names == ["BX PLANETOCENTRIC"]


def test_browse_data_parameters_query_matches_description():
    server = create_server()
    # "planetocentric" appears in the names of the B-field components AND in the
    # descriptions of the X/Y/Z spacecraft-position parameters, so the query
    # searches description text too.
    data = _browse_pds_params(server, parameter_query="planetocentric")
    page = data["payload"]["parameter_page"]
    assert page["total"] == 6
    names = {p["name"] for p in data["payload"]["parameters"]}
    assert names == {
        "BX PLANETOCENTRIC", "BY PLANETOCENTRIC", "BZ PLANETOCENTRIC",
        "X", "Y", "Z",
    }


def test_browse_data_parameters_query_is_case_insensitive():
    server = create_server()
    data = _browse_pds_params(server, parameter_query="RANGE")
    names = [p["name"] for p in data["payload"]["parameters"]]
    assert names == ["INSTRUMENT RANGE"]


def test_browse_data_parameters_limit_and_offset_paginate():
    server = create_server()
    data = _browse_pds_params(server, limit=3, offset=2)
    page = data["payload"]["parameter_page"]
    assert page["total"] == 8
    assert page["returned"] == 3
    assert page["offset"] == 2
    assert page["limit"] == 3
    assert page["has_more"] is True
    names = [p["name"] for p in data["payload"]["parameters"]]
    assert names == ["BY PLANETOCENTRIC", "BZ PLANETOCENTRIC", "INSTRUMENT RANGE"]


def test_browse_data_parameters_query_and_limit_compose():
    server = create_server()
    data = _browse_pds_params(server, parameter_query="planetocentric", limit=2)
    page = data["payload"]["parameter_page"]
    assert page["total"] == 6  # total counts matches before pagination
    assert page["returned"] == 2
    assert page["has_more"] is True
    names = [p["name"] for p in data["payload"]["parameters"]]
    assert names == ["BX PLANETOCENTRIC", "BY PLANETOCENTRIC"]


def test_browse_data_parameters_offset_past_end_returns_empty_page():
    server = create_server()
    data = _browse_pds_params(server, offset=100)
    page = data["payload"]["parameter_page"]
    assert page["total"] == 8
    assert page["returned"] == 0
    assert page["has_more"] is False
    assert data["payload"]["parameters"] == []


def test_browse_data_parameters_query_no_match_is_clean_success():
    server = create_server()
    data = _browse_pds_params(server, parameter_query="no-such-parameter-xyz")
    assert data["status"] == "success"
    page = data["payload"]["parameter_page"]
    assert page["total"] == 0
    assert page["returned"] == 0
    assert data["payload"]["parameters"] == []


def test_browse_data_parameters_rejects_negative_limit():
    server = create_server()
    data = _browse_pds_params(server, limit=0)
    assert data["status"] == "error"
    assert data["code"] == "invalid_argument"


def test_browse_data_parameters_rejects_negative_offset():
    server = create_server()
    data = _browse_pds_params(server, offset=-1)
    assert data["status"] == "error"
    assert data["code"] == "invalid_argument"


def test_browse_data_parameters_existing_source_type_behavior_preserved():
    # source_type routing for spice/unknown must be unaffected by the new filter.
    server = create_server()
    spice = json.loads(_call_tool(server, "browse_data_parameters", {
        "source_type": "spice", "dataset_id": "PSP",
    }))
    assert spice["status"] == "success"
    assert spice["payload"]

    unknown = json.loads(_call_tool(server, "browse_data_parameters", {
        "source_type": "nope", "dataset_id": "x", "parameter_query": "anything",
    }))
    assert unknown["status"] == "error"
    assert unknown["code"] == "invalid_argument"


def test_browse_hapi_catalog_missing_dep_or_size_safe_success(tmp_path: Path, monkeypatch):
    # Direct HAPI/FDSN tools are gated out of the default surface (issue #87);
    # enable the datasource flag to register and exercise the tool itself.
    monkeypatch.setenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", "1")
    server = create_server()
    data = json.loads(_call_tool(server, "browse_hapi_catalog", {
        "server_url": "https://cdaweb.gsfc.nasa.gov/hapi",
    }))
    # Without the optional [hapi] extra installed the tool returns a structured
    # missing_dependency error. If the local test environment does have
    # hapiclient installed, the unfiltered catalog must still be size-safe.
    if data["status"] == "error":
        assert data["code"] == "missing_dependency"
        assert data["extra"] == "hapi"
    else:
        assert data["status"] == "success"
        assert data["dataset_count"] <= 500
        assert "response_too_large" not in json.dumps(data)


def test_browse_fdsn_datasets_missing_dep_is_clean(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", "1")
    server = create_server()
    data = json.loads(_call_tool(server, "browse_fdsn_datasets", {
        "trange": ["2015-06-22", "2015-06-23"],
    }))
    assert data["status"] == "error"
    assert data["code"] == "missing_dependency"
    assert data["extra"] == "fdsn"


def test_browse_fdsn_datasets_bad_trange_validates_before_backend(monkeypatch):
    monkeypatch.setenv("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", "1")
    server = create_server()
    data = json.loads(_call_tool(server, "browse_fdsn_datasets", {"trange": ["only-one"]}))
    assert data["status"] == "error"
    assert data["code"] == "invalid_argument"


# ---------------------------------------------------------------------------
# Numbered/lettered spacecraft target inference (Batch V T007). Mission keywords
# are matched on strict word boundaries, so the per-spacecraft suffix used in
# the natural way to phrase a single-probe goal ("MMS1 bow-shock crossing",
# "rbspa", "themisa") was rejected and ``_extract_target`` returned ``None`` --
# even though the CDAWeb discovery layer already fuzzy-resolves "MMS1" -> "mms".
# Allow the suffix for the missions that fly numbered/lettered probes, without
# weakening the false-positive guards for generic words (ace/wind/solo/cluster).
# ---------------------------------------------------------------------------

@_pytest_b1.mark.parametrize(
    "goal,expected",
    [
        ("MMS1 bow-shock crossing", "MMS"),
        ("use MMS3 FGM survey", "MMS"),
        ("MMS4 dayside magnetopause", "MMS"),
        ("rbspa radiation belt", "Van Allen Probes"),
        ("RBSP-B EMFISIS", "Van Allen Probes"),
        ("themisa substorm tail", "THEMIS"),
        ("stereoa upstream", "STEREO"),
    ],
)
def test_extract_target_numbered_spacecraft(goal, expected):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) == expected


@_pytest_b1.mark.parametrize(
    "goal",
    # Suffix relaxation must not resurrect the generic-word false positives:
    # bare "ace"/"wind"/"solo"/"cluster" and plausible-suffix lookalikes.
    ["surface waves", "spacelike", "acexyz", "windy day", "soloist", "clustered"],
)
def test_extract_target_numbered_suffix_no_false_positive(goal):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) is None


def test_extract_targets_preserves_mixed_mission_ordering():
    from spedas_agent_kit.workflows import _extract_targets

    assert _extract_targets(
        "Compare ACE then the Cluster multi-spacecraft constellation and finally Wind"
    ) == ["ACE", "Cluster", "Wind"]


def test_plan_spedas_observation_infers_numbered_mms_target():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "Identify an MMS1 bow-shock crossing on 2015-10-07 using FGM "
            "magnetic field and FPI ion plasma moments"
        ),
    }))
    assert data["status"] == "success"
    assert data["inferred"]["target"] == "MMS"
    assert data["inferred"]["start"] == "2015-10-07T00:00:00Z"
    assert data["recommended_sources"] == ["cdaweb"]


# ---------------------------------------------------------------------------
# Van Allen Probes (RBSP) source routing. ``_extract_target`` already maps the
# "van allen probes"/"rbsp" phrasing to the canonical "Van Allen Probes" label
# (issue #30), but the source router previously had no matching CDAWeb keyword,
# so a bare radiation-belt goal fell back to "recommend all three families
# equally" instead of leading with CDAWeb. RBSP is a CDAWeb-only mission (no
# SPICE kernels, no PDS bundles), so CDAWeb must win.
# ---------------------------------------------------------------------------

def test_van_allen_probes_radiation_belt_routes_to_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Plan a Van Allen Probes radiation belt interval with electron flux and magnetic field",
    }))
    assert data["status"] == "success"
    # CDAWeb must lead and outrank PDS/SPICE — RBSP is a CDAWeb-only mission.
    assert data["ranked_sources"][0]["source"] == "cdaweb"
    assert data["recommended_sources"] == ["cdaweb"]


def test_rbsp_acronym_routes_to_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "RBSP EMFISIS and MagEIS radiation belt electron flux interval",
    }))
    assert data["status"] == "success"
    assert data["ranked_sources"][0]["source"] == "cdaweb"
    assert "cdaweb" in data["recommended_sources"]
    assert "pds" not in data["recommended_sources"]
    assert "spice" not in data["recommended_sources"]


def test_planetary_radiation_belt_does_not_add_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Jupiter radiation belt dynamics from Juno",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["pds"]
    assert data["ranked_sources"][0]["source"] == "pds"
    assert "cdaweb" not in data["recommended_sources"]


def test_van_allen_probes_observation_plan_leads_with_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "Van Allen Probes radiation belt electron flux and EMFISIS magnetic "
            "field during the 2015-03-17 storm"
        ),
    }))
    assert data["status"] == "success"
    # Mission and day-scale interval inferred from the goal text (issue #30).
    assert data["inferred"]["target"] == "Van Allen Probes"
    assert data["inferred"]["start"] == "2015-03-17T00:00:00Z"
    assert data["recommended_sources"] == ["cdaweb"]
    phases = {step["phase"] for step in data["plan"]}
    assert {"discover_cdaweb", "fetch_or_compute_cdaweb"} <= phases


# ===========================================================================
# Batch W integration (T011-T015): combined routing/alias fixes.
#   T011 - Geotail plasma-sheet substring false positives (word-boundary matcher)
#   T012 - Solar Orbiter / SolO instrument+science alias
#   T013 - Ulysses high-latitude solar wind -> CDAWeb (not PDS)
#   T014 - Parker Solar Probe switchback -> CDAWeb (FIELDS/SWEAP)
#   T015 - MAVEN Mars bow-shock planetary guard (boundary words not near-Earth)
# Each fix touches src/spedas_agent_kit/workflows.py (`_score_sources` /
# `_QUALIFIED_MISSION_KEYWORDS`); these tests guard the combined behavior and the
# cross-topic regression guards that must all hold simultaneously.
# ===========================================================================


# --- T011: Geotail plasma-sheet substring false positives ------------------

@pytest.mark.parametrize(
    "goal",
    [
        "Geotail plasma sheet interval workflow",
        "Geotail current sheet flapping in the plasma sheet",
        "Geotail magnetotail plasma sheet mapping survey",
        "Geotail plasma sheet ion flows with return-flow signatures",
    ],
)
def test_geotail_plasma_sheet_routes_to_cdaweb_only(goal):
    """ppi/urn substrings inside flapping/mapping/return must not surface PDS."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": goal,
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]
    assert "pds" not in data["recommended_sources"]


def test_score_sources_no_ppi_substring_false_positive():
    from spedas_agent_kit.workflows import _score_sources

    # "flapping"/"mapping" contain "ppi"; "return" contains "urn"; "marshalling"
    # contains "mars" -- none of these should add to the PDS score.
    base = _score_sources("geotail plasma sheet survey")
    noisy = _score_sources(
        "geotail current sheet flapping mapping return-flow marshalling survey"
    )
    assert noisy["pds"] <= base["pds"]


def test_score_sources_real_pds_tokens_still_match():
    from spedas_agent_kit.workflows import _score_sources

    # Genuine whole-word PDS vocabulary must still score after the word-boundary
    # hardening (T011 must not break real matches).
    scored = _score_sources("juno pds ppi bundle near saturn")
    assert scored["pds"] >= 3


# --- T012: Solar Orbiter / SolO instrument+science alias --------------------

@pytest.mark.parametrize(
    "goal",
    [
        "SolO MAG RTN magnetic field near perihelion",
        "SolO SWA proton plasma during encounter",
        "SolO EPD energetic particles survey",
        "SolO RPW radio and plasma waves",
        "SolO EUI imaging campaign",
        "SolO STIX flare observations",
        "SolO perihelion solar-wind workflow with MAG and SWA",
        "SolO periapsis geometry context",
    ],
)
def test_extract_target_solo_instrument_and_science_phrasing(goal):
    from spedas_agent_kit.workflows import _extract_target, _extract_targets

    assert _extract_target(goal) == "Solar Orbiter"
    assert "Solar Orbiter" in _extract_targets(goal)


@pytest.mark.parametrize("goal", ["solo", "fly solo", "soloist performance", "a solo run"])
def test_solo_instrument_alias_preserves_false_positive_guard(goal):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) is None


def test_solo_perihelion_observation_plan_names_target_and_routes_cdaweb_spice():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "SolO perihelion MAG RTN magnetic field and SWA solar wind plasma with "
            "heliocentric geometry on 2023-04-10"
        ),
    }))
    assert data["status"] == "success"
    assert data["inferred"]["target"] == "Solar Orbiter"
    assert "cdaweb" in data["recommended_sources"]
    assert "spice" in data["recommended_sources"]


# --- T013: Ulysses high-latitude solar wind --------------------------------

@pytest.mark.parametrize(
    "goal",
    [
        "Ulysses high-latitude solar wind survey over the south polar pass",
        "Ulysses fast solar wind at high heliographic latitude",
        "Ulysses high-latitude pass",
        "Ulysses south polar pass",
    ],
)
def test_ulysses_high_latitude_solar_wind_routes_to_cdaweb_not_pds(goal):
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": goal,
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]
    assert "pds" not in data["recommended_sources"]


def test_ulysses_hyphenated_solar_wind_phrasing_routes_to_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Plan a Ulysses polar pass solar-wind workflow",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]


def test_ulysses_high_latitude_plan_infers_target_and_leads_with_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "Ulysses fast solar wind at high heliographic latitude during the "
            "1994-09-13 south polar pass"
        ),
    }))
    assert data["status"] == "success"
    assert data["inferred"]["target"] == "Ulysses"
    assert data["recommended_sources"][0] == "cdaweb"


def test_ulysses_high_latitude_does_not_regress_planetary_routing():
    """A high-latitude mention in a planetary context must stay PDS-led."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Cassini high-latitude orbit at Saturn",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"][0] == "pds"


# --- T014: Parker Solar Probe switchback -----------------------------------

def test_psp_switchback_full_name_routes_to_cdaweb_not_pds():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "switchback interval study using Parker Solar Probe SWEAP and FIELDS "
            "on 2021-04-29"
        ),
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]
    assert "pds" not in data["recommended_sources"]


def test_psp_switchback_encounter_survey_keeps_cdaweb_above_spice():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Parker Solar Probe encounter 8 switchback survey 2021-04-29",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]
    assert data["inferred"]["target"] == "Parker Solar Probe"
    phases = {step["phase"] for step in data["plan"]}
    assert "discover_cdaweb" in phases
    assert "discover_pds" not in phases


def test_psp_switchback_with_perihelion_geometry_keeps_spice():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Analyze switchbacks in PSP solar wind near perihelion 2021-11-21",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb", "spice"]


def test_psp_switchback_routing_does_not_regress_planetary_fields_goals():
    """The deliberately-excluded bare 'fields' must not flip planetary goals."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "MESSENGER magnetic fields near Mercury",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"][0] == "pds"


# --- T015: MAVEN Mars bow-shock planetary guard ----------------------------

def test_maven_mars_bow_shock_routes_to_pds_not_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "MAVEN Mars bow shock and magnetosheath induced-magnetosphere study",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["pds"]


def test_maven_mars_bow_shock_does_not_boost_cdaweb_via_boundary_nudge():
    from spedas_agent_kit.workflows import _score_sources

    plain = _score_sources("maven mars induced magnetosphere study")
    boundary = _score_sources("maven mars bow shock magnetopause induced magnetosphere study")
    # Adding the boundary words must not raise CDAWeb for a planetary (Mars) goal.
    assert boundary["cdaweb"] <= plain["cdaweb"]


def test_earth_bow_shock_still_routes_to_cdaweb():
    """Non-planetary bow-shock goals must keep their near-Earth CDAWeb nudge."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Earth bow shock crossing in the solar wind with MMS",
    }))
    assert data["status"] == "success"
    assert data["recommended_sources"] == ["cdaweb"]


# ===========================================================================
# Batch X T016: Cassini / Saturn magnetosphere planetary guard.
#
# Cassini is a PDS-only planetary-archive mission (its MAG/CAPS products live in
# the PDS PPI node; it has no CDAWeb datasets). A goal phrased with generic
# physics vocabulary ("Cassini Saturn magnetosphere magnetic field") still hit
# the bare CDAWeb *keywords* ``magnetosphere``/``magnetic`` and lifted CDAWeb to
# score 3 -- above the score>1 selection threshold -- so the planner wrongly
# recommended CDAWeb alongside PDS for a mission with no CDAWeb data. The boundary
# (bow shock / magnetopause) and radiation-belt nudges were already guarded
# against planetary contexts (T015/T006); these tests extend that same discipline
# to the generic CDAWeb magnetosphere/field/plasma/particle keywords, which are
# equally planetary-archive physics vocabulary.
# ===========================================================================


@pytest.mark.parametrize(
    "goal",
    [
        "Cassini Saturn magnetosphere magnetic field",
        "Cassini MAG Saturn orbit",
        "Cassini plasma near Saturn",
    ],
)
def test_cassini_saturn_goals_lead_with_pds_not_cdaweb(goal):
    """Cassini/Saturn goals are PDS-led and must not recommend CDAWeb."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": goal,
    }))
    assert data["status"] == "success"
    assert data["ranked_sources"][0]["source"] == "pds"
    assert data["recommended_sources"][0] == "pds"
    assert "cdaweb" not in data["recommended_sources"]


def test_cassini_mag_saturn_orbit_keeps_spice_geometry_context():
    """An explicit orbit/geometry phrasing may still surface SPICE as context."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Cassini MAG Saturn orbit",
    }))
    assert data["recommended_sources"] == ["pds", "spice"]


def test_cassini_plan_observation_leads_with_pds_no_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "Cassini Saturn magnetosphere magnetic field survey 2006-01-01 to "
            "2006-01-02"
        ),
    }))
    assert data["status"] == "success"
    assert data["inferred"]["target"] == "Cassini"
    assert data["recommended_sources"][0] == "pds"
    assert "cdaweb" not in data["recommended_sources"]
    phases = {step["phase"] for step in data["plan"]}
    assert "discover_pds" in phases
    assert "discover_cdaweb" not in phases


def test_planetary_magnetosphere_keywords_do_not_boost_cdaweb():
    """The generic magnetosphere/magnetic keywords must not raise CDAWeb for a
    planetary (Saturn) goal, mirroring the T015 boundary-nudge guard."""
    from spedas_agent_kit.workflows import _score_sources

    physics = _score_sources("cassini saturn magnetosphere magnetic field survey")
    # The generic magnetosphere/field keyword matches are subtracted, so CDAWeb
    # stays at most the single cross-source measurement nudge (+1) -- below the
    # score>1 recommendation threshold -- while PDS leads the planetary goal.
    assert physics["cdaweb"] <= 1
    assert physics["pds"] > physics["cdaweb"]
    # The bare magnetosphere/magnetic keywords must not lift CDAWeb above the
    # selection threshold the way they did before the planetary guard (was 3).
    no_physics = _score_sources("cassini saturn survey")
    assert physics["cdaweb"] - no_physics["cdaweb"] <= 1


def test_planetary_guard_does_not_regress_near_earth_magnetosphere():
    """Near-Earth magnetosphere goals (no planetary body/mission) keep CDAWeb."""
    server = create_server()
    for goal in (
        "Earth magnetosphere magnetic field bow shock",
        "THEMIS magnetotail substorm magnetic field",
        "MMS reconnection magnetopause plasma",
    ):
        data = json.loads(_call_tool(server, "search_spedas_data_sources", {
            "question": goal,
        }))
        assert data["recommended_sources"] == ["cdaweb"], goal


# ---------------------------------------------------------------------------
# T018: Voyager outer-heliosphere / heliopause magnetic-field routing.
#
# Voyager 1/2 are a *dual-archive* mission. Their planetary-flyby products
# (Jupiter/Saturn/Uranus/Neptune encounters) live in the PDS PPI archive, but
# their decades-long heliospheric MAG/PLS time-series — including the
# termination-shock and heliopause crossings and the interstellar magnetic
# field — are CDAWeb/SPDF observatory products (VOYAGER1/2 MAG and PLS
# datasets), not PDS planetary bundles.
#
# Because "voyager" is registered as a planetary-context mission (correctly, for
# the flybys), an outer-heliosphere goal used to score PDS=4/CDAWeb=2 and a goal
# with no generic measurement word ("Voyager outer heliosphere termination
# shock") scored CDAWeb=0 and routed to PDS *alone* — burying the CDAWeb
# time-series that actually holds the data. A guarded heliospheric-context nudge
# lifts CDAWeb for these goals while leaving the planetary-flyby routing intact.
# ---------------------------------------------------------------------------

def test_voyager_outer_heliosphere_bfield_routes_to_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Voyager 1 outer heliosphere magnetic field time series at the heliopause",
        "target": "Voyager",
        "observables": ["magnetic field"],
    }))
    assert data["status"] == "success"
    # The heliospheric time-series source must lead for an outer-heliosphere goal.
    assert data["recommended_sources"][0] == "cdaweb"


def test_voyager_heliopause_goal_with_no_measurement_word_still_includes_cdaweb():
    """The starkest baseline failure: a heliopause goal with no generic
    measurement word scored CDAWeb=0 and routed to PDS alone."""
    from spedas_agent_kit.workflows import _score_sources

    scores = _score_sources("voyager outer heliosphere termination shock heliopause")
    assert scores["cdaweb"] >= scores["pds"]
    assert scores["cdaweb"] > 0


def test_voyager_interstellar_field_plan_recommends_cdaweb_first():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": "Voyager 1 interstellar magnetic field in the very local interstellar medium",
    }))
    assert data["status"] in {"success", "needs_input"}
    assert "cdaweb" in data["recommended_sources"]
    assert data["recommended_sources"][0] == "cdaweb"
    assert data["inferred"]["target"] == "Voyager"


def test_voyager_planetary_flyby_still_routes_to_pds():
    """The heliospheric nudge must not regress the planetary-flyby archive
    routing: a Jupiter/Neptune flyby goal stays PDS-led."""
    server = create_server()
    for goal in (
        "Voyager 1 Jupiter flyby magnetic field",
        "Voyager 2 Neptune flyby plasma observations",
    ):
        data = json.loads(_call_tool(server, "search_spedas_data_sources", {
            "question": goal,
            "target": "Voyager",
        }))
        assert data["status"] == "success", goal
        assert "pds" in data["recommended_sources"], goal
        assert data["recommended_sources"][0] == "pds", goal


def test_heliospheric_nudge_needs_heliospheric_terms():
    """The nudge is specific: a bare planetary goal with no heliospheric term
    must not gain a CDAWeb boost from this rule (no generic false positives)."""
    from spedas_agent_kit.workflows import _score_sources

    plain = _score_sources("cassini saturn magnetosphere magnetic field")
    assert plain["pds"] > plain["cdaweb"]


def test_heliopause_term_does_not_boost_planetary_flyby_context():
    """If both a heliospheric term and a specific planet/flyby body are named,
    the planetary-flyby body context wins so PDS still leads (guarded nudge)."""
    from spedas_agent_kit.workflows import _score_sources

    # "heliopause" mentioned in passing while the goal is a Jupiter flyby.
    scores = _score_sources("voyager jupiter flyby on the way to the heliopause")
    assert scores["pds"] >= scores["cdaweb"]


# ===========================================================================
# T019: New Horizons Pluto-flyby / SWAP / PEPSSI planetary-archive routing.
#   New Horizons is a PDS PPI mission (NEW-HORIZONS_PPI, 12 datasets incl. the
#   "Solar Wind" SWAP product and the PEPSSI energetic-particle product); it has
#   NO CDAWeb time-series. Two gaps existed before this fix:
#     1. "Pluto" was not a planetary-context body, so "Pluto flyby plasma"
#        scored no PDS planetary boost and mis-routed to near-Earth CDAWeb.
#     2. The bare "solar wind" near-Earth nudge fired unconditionally, so
#        "New Horizons solar wind" (a PDS SWAP product) spuriously surfaced
#        CDAWeb alongside PDS. Guarding it against planetary contexts (the same
#        discipline as the T015 bow-shock / T013 high-latitude nudges) keeps
#        genuine near-Earth/heliospheric solar-wind goals (OMNI/ACE/Wind/
#        Ulysses) on CDAWeb while New-Horizons/Pluto solar wind stays PDS-led.
#   SWAP/PEPSSI are added as PDS vocabulary so the instrument phrasing scores PDS.
# ===========================================================================


def test_new_horizons_pluto_flyby_swap_pepssi_routes_to_pds():
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "New Horizons Pluto flyby SWAP and PEPSSI plasma and energetic particles",
    }))
    assert data["status"] == "success"
    # PDS is New Horizons' only honest source; it must lead and outrank CDAWeb.
    assert data["ranked_sources"][0]["source"] == "pds"
    assert data["recommended_sources"][0] == "pds"
    pds = next(r for r in data["ranked_sources"] if r["source"] == "pds")
    cdaweb = next(r for r in data["ranked_sources"] if r["source"] == "cdaweb")
    assert pds["score"] > cdaweb["score"]


def test_new_horizons_solar_wind_stays_pds_led_not_cdaweb_led():
    """New Horizons solar wind is the SWAP PDS product, not a CDAWeb time-series."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "New Horizons solar wind during the cruise to Pluto",
    }))
    assert data["status"] == "success"
    assert data["ranked_sources"][0]["source"] == "pds"
    assert data["recommended_sources"][0] == "pds"
    pds = next(r for r in data["ranked_sources"] if r["source"] == "pds")
    cdaweb = next(r for r in data["ranked_sources"] if r["source"] == "cdaweb")
    assert pds["score"] > cdaweb["score"]


def test_pluto_flyby_plasma_routes_to_pds_not_cdaweb_led():
    """A Pluto flyby is planetary-archive science; it must be PDS-led, not CDAWeb-led."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": "Pluto flyby plasma",
    }))
    assert data["status"] == "success"
    # Before the fix Pluto was not a planetary-context body, so this scored
    # CDAWeb=2 / PDS=1 and recommended ["cdaweb"] — a planetary flyby routed to
    # the near-Earth archive. PDS must now lead.
    assert data["ranked_sources"][0]["source"] == "pds"
    assert data["recommended_sources"][0] == "pds"
    pds = next(r for r in data["ranked_sources"] if r["source"] == "pds")
    cdaweb = next(r for r in data["ranked_sources"] if r["source"] == "cdaweb")
    assert pds["score"] > cdaweb["score"]


def test_new_horizons_plan_infers_target_and_leads_with_pds():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "New Horizons SWAP solar-wind plasma during the Pluto encounter on "
            "2015-07-14"
        ),
    }))
    assert data["status"] == "success"
    assert data["inferred"]["target"] == "New Horizons"
    assert data["inferred"]["start"] == "2015-07-14T00:00:00Z"
    assert data["recommended_sources"][0] == "pds"
    phases = {step["phase"] for step in data["plan"]}
    assert {"discover_pds", "fetch_or_compute_pds"} <= phases


def test_solar_wind_planetary_guard_does_not_regress_near_earth_goals():
    """Guarding the 'solar wind' nudge must not drop CDAWeb for near-Earth/heliospheric solar-wind goals."""
    server = create_server()
    for goal in (
        "OMNI solar wind during a geomagnetic storm",
        "ACE solar wind plasma upstream of Earth",
        "Wind spacecraft solar wind measurements",
        "Ulysses high-latitude fast solar wind",
    ):
        data = json.loads(_call_tool(server, "search_spedas_data_sources", {
            "question": goal,
        }))
        assert data["status"] == "success", goal
        assert data["recommended_sources"] == ["cdaweb"], goal


def test_solar_wind_nudge_suppressed_in_planetary_context():
    from spedas_agent_kit.workflows import _score_sources

    # The +2 "solar wind" near-Earth nudge must fire for a non-planetary goal but
    # be suppressed when a planetary body/mission is named (mirrors the T015
    # bow-shock guard). The bare "solar wind" *keyword* (+1) may still count.
    # Same trailing vocabulary, with and without a planetary body/mission named.
    nearearth = _score_sources("flyby plasma solar wind")
    planetary = _score_sources("new horizons pluto flyby plasma solar wind")
    # The +2 near-Earth nudge fires only without a planetary context, so the
    # planetary CDAWeb score is strictly lower despite the extra mission word.
    assert planetary["cdaweb"] < nearearth["cdaweb"]
    # And the suppressed nudge keeps PDS decisively ahead of CDAWeb.
    assert planetary["pds"] > planetary["cdaweb"]


def test_swap_pepssi_are_pds_vocabulary():
    from spedas_agent_kit.workflows import _score_sources

    # The New Horizons instrument acronyms must score for PDS (they name PDS PPI
    # products), and must not fire inside unrelated words via substring matching.
    scored = _score_sources("new horizons swap pepssi products")
    assert scored["pds"] >= 3
    # "swap" must not match inside e.g. "swapping"; "pepssi" is distinctive.
    noisy = _score_sources("geotail swapping buffers")
    assert noisy["pds"] == 0


# ===========================================================================
# Batch X T020 - STEREO solar-energetic-particle / solar-wind source routing.
# ``_extract_target`` already maps "STEREO"/"STEREO-A"/"STEREO B"/"stereoa" to the
# canonical "STEREO" label (#30 / Batch V T007), but the source router had no
# matching CDAWeb keyword. A SEP/energetic-particle goal phrased without the
# generic "solar wind"/"plasma"/"magnetic" measurement words ("STEREO-A SEP
# SEPT", "STEREO-A IMPACT energetic electrons") scored only 1 on every family and
# fell back to "all sources equally" -- surfacing the PDS planetary archive; and
# "STEREO ahead spacecraft SEP" routed to SPICE alone on the bare "spacecraft"
# geometry token. STEREO is an SPDF/CDAWeb mission (no PDS bundles, no SPICE
# kernels in this context), so CDAWeb must lead. Fix: register "stereo"/"sept" as
# CDAWeb keywords plus a planetary-guarded solar-energetic-particle nudge,
# mirroring the Ulysses (T013) / PSP switchback (T014) lanes.
# ===========================================================================


@pytest.mark.parametrize(
    "goal",
    [
        "STEREO-A SEP SEPT solar energetic particle event",
        "STEREO-A IMPACT energetic electrons",
        "STEREO-B energetic protons solar energetic particles",
        "STEREO solar wind PLASTIC plasma",
        "STEREO MAG magnetic field interval",
        "STEREO ahead spacecraft solar energetic particles",
    ],
)
def test_stereo_sep_solar_wind_routes_to_cdaweb(goal):
    """STEREO heliophysics goals must lead with CDAWeb, never the PDS archive."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": goal,
    }))
    assert data["status"] == "success"
    assert data["ranked_sources"][0]["source"] == "cdaweb"
    assert "cdaweb" in data["recommended_sources"]
    assert "pds" not in data["recommended_sources"]


@pytest.mark.parametrize(
    "goal,expected",
    [
        ("STEREO-A SEP SEPT", "STEREO"),
        ("STEREO B PLASTIC solar wind", "STEREO"),
        ("STEREO-B IMPACT", "STEREO"),
        ("STEREO Ahead MAG magnetic field", "STEREO"),
        ("STEREO Behind solar wind", "STEREO"),
    ],
)
def test_stereo_alias_target_inference(goal, expected):
    from spedas_agent_kit.workflows import _extract_target

    assert _extract_target(goal) == expected


def test_stereo_observation_plan_leads_with_cdaweb():
    server = create_server()
    data = json.loads(_call_tool(server, "plan_spedas_observation", {
        "science_goal": (
            "STEREO-A SEP SEPT solar energetic particle event on 2012-03-07"
        ),
    }))
    assert data["status"] == "success"
    assert data["inferred"]["target"] == "STEREO"
    assert data["inferred"]["start"] == "2012-03-07T00:00:00Z"
    assert data["recommended_sources"] == ["cdaweb"]
    phases = {step["phase"] for step in data["plan"]}
    assert {"discover_cdaweb", "fetch_or_compute_cdaweb"} <= phases


def test_sept_keyword_does_not_match_september():
    """The unambiguous SEPT acronym is word-boundary-anchored, so the month name
    'September' (trailing letters) must not add to the CDAWeb score (T020)."""
    from spedas_agent_kit.workflows import _score_sources

    plain = _score_sources("monthly data review")
    month = _score_sources("September monthly data review")
    assert month["cdaweb"] <= plain["cdaweb"]


@pytest.mark.parametrize(
    "goal",
    [
        "Jupiter energetic ions in the magnetosphere from Juno",
        "Cassini energetic electrons at Saturn",
        "Galileo energetic ions at Jupiter",
    ],
)
def test_planetary_energetic_particles_stay_pds_led(goal):
    """The solar-energetic-particle CDAWeb nudge must be planetary-guarded so a
    planetary energetic-particle goal still leads with PDS (T020)."""
    server = create_server()
    data = json.loads(_call_tool(server, "search_spedas_data_sources", {
        "question": goal,
    }))
    assert data["status"] == "success"
    assert data["ranked_sources"][0]["source"] == "pds"
    assert "cdaweb" not in data["recommended_sources"]


# ---------------------------------------------------------------------------
# Argument-validation error contract (#57)
#
# FastMCP validates tool arguments against a generated pydantic model *before*
# the (_safe_tool-wrapped) tool body runs, so a missing/misnamed/wrong-typed
# argument used to escape as a raw pydantic ToolError carrying the input dict and
# a public errors.pydantic.dev URL — bypassing the {status:"error", code, ...}
# contract every other error follows. These lock in the structured envelope.
# ---------------------------------------------------------------------------


def test_arg_validation_output_file_alias_reaches_minvar_body_no_pydantic_leak():
    """The exact issue #57 ergonomics case now succeeds at argument validation:
    analyze_minvar_coordinates accepts output_file like sibling single-artifact
    tools. Any later error comes from the body and must not be a raw Pydantic
    ToolError.
    """
    server = create_server(include_analysis_tools=True)
    raw = _call_tool(server, "analyze_minvar_coordinates", {
        "input_file": "x.csv",
        "output_file": "out.csv",
        "vector_cols": ["Bx", "By", "Bz"],
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] != "invalid_arguments"
    assert payload.get("tool") != "analyze_minvar_coordinatesArguments"
    # No raw pydantic leak: no doc URL, no echoed validation internals.
    assert "errors.pydantic.dev" not in raw
    assert "input_value" not in raw
    assert "ValidationError" not in raw
    assert "out.csv" not in raw
    assert "\n" not in payload["message"]
    assert "/Users/" not in raw


def test_arg_validation_wrong_type_is_structured():
    """Wrong-typed arguments are summarized per-field without leaking the
    pydantic URL or the offending input values."""
    server = create_server(include_analysis_tools=True)
    raw = _call_tool(server, "render_tplot", {
        "input_files": "not-a-list",
        "output_file": 123,
        "dpi": "abc",
    })
    payload = json.loads(raw)
    assert payload["status"] == "error"
    assert payload["code"] == "invalid_arguments"
    # Each offending argument is named.
    assert "input_files" in payload["message"]
    assert "output_file" in payload["message"]
    assert "dpi" in payload["message"]
    # No pydantic doc URL or echoed input values.
    assert "errors.pydantic.dev" not in raw
    assert "not-a-list" not in raw
    assert "input_value" not in raw


def test_valid_arguments_still_reach_tool_body():
    """A correctly-named/typed call must pass validation and reach the tool body
    (here surfacing the analysis dependency_missing error, never the
    invalid_arguments validation envelope)."""
    server = create_server(include_analysis_tools=True)
    raw = _call_tool(server, "analyze_minvar_coordinates", {
        "input_file": "x.csv",
        "output_dir": "/tmp/does-not-matter",
    })
    payload = json.loads(raw)
    # Reached the body: not intercepted by the argument-validation guard.
    assert payload["code"] != "invalid_arguments"


def test_summarize_pydantic_validation_is_url_free():
    """The summarizer turns a real pydantic ValidationError into a compact,
    URL-free, input-free one-liner."""
    from pydantic import BaseModel, ValidationError

    from spedas_agent_kit.server import _summarize_pydantic_validation

    class _M(BaseModel):
        output_dir: str
        count: int

    try:
        _M.model_validate({"count": "not-an-int"})
    except ValidationError as exc:
        message = _summarize_pydantic_validation(exc)
        assert "https://" not in message
        assert "errors.pydantic.dev" not in message
        assert "not-an-int" not in message  # no echoed input value
        assert "output_dir" in message  # the missing field is named
        assert message.endswith(".")
    else:  # pragma: no cover - validation must fail
        raise AssertionError("expected a ValidationError")
