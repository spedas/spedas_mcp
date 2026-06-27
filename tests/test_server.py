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
        "dynamic_power_spectrum",
        "wavelet_transform",
        "evaluate_magnetic_field",
        "calculate_lshell",
        "compute_particle_moments",
        "compute_particle_spectra",
        "render_tplot",
        "browse_hapi_catalog",
        "fetch_hapi_data",
        "browse_fdsn_datasets",
        "fetch_fdsn_data",
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
    from spedas_mcp.workflows import _extract_time_range

    for goal in ("2015-13-40", "2015-02-30", "9999-99-99", "2020-00-10"):
        assert _extract_time_range(goal) == (None, None)


def test_extract_time_range_valid_date_still_parses():
    from spedas_mcp.workflows import _extract_time_range

    assert _extract_time_range("event on 2015-10-16") == (
        "2015-10-16T00:00:00Z",
        "2015-10-17T00:00:00Z",
    )


def test_plan_spedas_observation_is_safe_tool_wrapped(monkeypatch):
    """B1 defense in depth: an unexpected backend error converts to an envelope.

    Force a non-ValueError out of the workflow impl to prove the ``@_safe_tool``
    decorator wraps ``plan_spedas_observation`` (not just the helper parse fix).
    """
    import spedas_mcp.workflows as workflows_mod

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
    from spedas_mcp.workflows import _extract_target

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
    from spedas_mcp.workflows import _extract_target

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
    from spedas_mcp.workflows import _extract_targets

    goal = (
        "Compare ACE, Wind, and OMNI solar-wind magnetic field and plasma "
        "upstream of Earth on 2015-10-16"
    )
    assert _extract_targets(goal) == ["ACE", "Wind", "OMNI"]


def test_extract_targets_deduplicates_and_preserves_first_position():
    from spedas_mcp.workflows import _extract_targets

    # Repeated mentions collapse; first appearance order wins.
    goal = "ACE vs Wind upstream; cross-check ACE against OMNI and Wind again"
    assert _extract_targets(goal) == ["ACE", "Wind", "OMNI"]


def test_extract_targets_single_mission_matches_extract_target():
    from spedas_mcp.workflows import _extract_target, _extract_targets

    goal = "Parker Solar Probe perihelion magnetic field on 2021-04-29"
    assert _extract_targets(goal) == ["Parker Solar Probe"]
    assert _extract_target(goal) == "Parker Solar Probe"


def test_extract_targets_no_false_positive_for_generic_wind():
    from spedas_mcp.workflows import _extract_targets

    assert _extract_targets("characterise solar-wind speed near the bow shock") == []


def test_extract_target_unchanged_returns_first_for_multimission():
    # Back-compat: the scalar helper still returns the first match only.
    from spedas_mcp.workflows import _extract_target

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
    from spedas_mcp.workflows import _extract_target

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
    from spedas_mcp.workflows import _extract_target

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


# ---------------------------------------------------------------------------
# Batch K — error contract, source_id validation, response-size guard
# (issues #25, #27, #28)
# ---------------------------------------------------------------------------

from spedas_mcp.server import (  # noqa: E402
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

from spedas_mcp.server import _classify_exception  # noqa: E402


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
    from spedas_mcp import server as server_mod
    from spedas_mcp.analysis import coords as coords_mod

    # The legacy shape always pairs a status="error" dict with a bare "error":
    # key. The uniform envelope uses code=/message= instead. Assert the literal
    # ``"error":`` key does not appear as a dict key in either module's source.
    for mod in (server_mod, coords_mod):
        src = inspect.getsource(mod)
        assert '"error":' not in src, (
            f"legacy status/error/error return still present in {mod.__name__}"
        )


def test_analysis_tools_are_wrapped_in_safe_tool():
    server = create_server()
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
    server = create_server()
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


def test_render_tplot_missing_file_is_structured(tmp_path: Path):
    server = create_server()
    missing = json.loads(_call_tool(server, "render_tplot", {
        "input_files": [str(tmp_path / "nope.npz")],
        "output_file": str(tmp_path / "out.png"),
    }))
    _assert_uniform_error(missing)
    assert missing["code"] == "resource_not_found"


def test_render_tplot_wrapped_in_safe_tool(monkeypatch):
    server = create_server()
    import spedas_mcp.analysis.plotting as plotting_mod

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
    server = create_server()
    # Force an unexpected (non-ValueError) exception out of the impl to prove the
    # @_safe_tool decorator — not just the impl's own try/except — wraps it.
    import spedas_mcp.analysis.coords as coords_mod

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
    # A geometry KeyError (xhelio_spice "Cannot resolve body name 'X'") must be
    # classified as geometry_error with a geometry hint, not the generic
    # KeyError -> invalid_argument mapping (issue #27 should-fix #3).
    code, hint = _classify_exception(KeyError("Cannot resolve body name 'NOPE'"))
    assert code == "geometry_error"
    assert hint and "list_spice_missions" in hint
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
    # surfaced after touching xhelio_spice. The geometry_error classifier still
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
    assert "list_spice_missions" in payload["hint"]
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
#   * monkeypatch xhelio_spice.get_state/get_trajectory/transform_vector to raise
#     if ever called, proving the preflight short-circuits before the backend.
# ---------------------------------------------------------------------------

import pytest  # noqa: E402

from spedas_mcp.server import (  # noqa: E402
    _spice_missing_kernels,
    _spice_resolve_target,
)


@pytest.fixture
def empty_kernel_cache(tmp_path, monkeypatch):
    """Point xhelio_spice at an empty kernel cache and reset its singleton.

    Yields the cache dir. With no files present, every mission's required
    kernels are "missing", so the #29 confirmation gate fires deterministically
    regardless of the developer's real ~/.xhelio_spice cache.
    """
    import xhelio_spice.kernel_manager as km_mod

    cache_dir = tmp_path / "kernels"
    cache_dir.mkdir()
    monkeypatch.setenv("XHELIO_SPICE_KERNEL_DIR", str(cache_dir))
    monkeypatch.setattr(km_mod, "_instance", None)
    yield cache_dir
    # Reset the singleton again so later tests do not inherit the tmp cache.
    monkeypatch.setattr(km_mod, "_instance", None)


@pytest.fixture
def no_backend_downloads(monkeypatch):
    """Make any real xhelio_spice geometry/download call fail loudly.

    The preflight is supposed to return before these run; if it does not, the
    test fails with a clear marker instead of attempting a network download.
    """
    import xhelio_spice

    def _boom(*args, **kwargs):  # pragma: no cover - only hit on regression
        raise AssertionError("backend geometry call reached — preflight did not gate it")

    monkeypatch.setattr(xhelio_spice, "get_state", _boom)
    monkeypatch.setattr(xhelio_spice, "get_trajectory", _boom)
    monkeypatch.setattr(xhelio_spice, "transform_vector", _boom)
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
    assert "list_spice_missions" in payload["hint"]
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
    assert any("manage_spice_kernels" in step for step in payload["next_steps"])
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
        "to_frame": "GSM",
    })
    payload = json.loads(raw)
    assert payload["status"] == "needs_confirmation"
    assert payload["code"] == "kernel_download_required"
    assert "GENERIC" in payload["missions"]


def test_get_ephemeris_cached_target_proceeds_to_backend(empty_kernel_cache, monkeypatch):
    # When all required kernels are present on disk, the gate must NOT fire and
    # the real geometry path runs. We fake-cache the generic + PSP files and stub
    # get_state so no download or SPICE call is needed.
    import xhelio_spice
    from xhelio_spice.missions import GENERIC_KERNELS, MISSION_KERNELS

    for fname in list(GENERIC_KERNELS) + list(MISSION_KERNELS["PSP"]):
        (empty_kernel_cache / fname).write_bytes(b"x")  # non-zero size = "cached"

    def _fake_get_state(target, observer, time, frame):
        return {"x_km": 1.0, "y_km": 2.0, "z_km": 3.0, "target": target,
                "observer": observer, "frame": frame, "time": time}

    monkeypatch.setattr(xhelio_spice, "get_state", _fake_get_state)

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
    import xhelio_spice

    def _fake_get_state(target, observer, time, frame):
        return {"x_km": 9.0, "target": target, "observer": observer,
                "frame": frame, "time": time}

    monkeypatch.setattr(xhelio_spice, "get_state", _fake_get_state)

    server = create_server()
    raw = _call_tool(server, "get_ephemeris", {
        "target": "PSP",
        "time": "2024-01-01T00:00:00",
        "allow_kernel_download": True,
    })
    payload = json.loads(raw)
    assert payload["status"] == "success"
    assert payload["x_km"] == 9.0


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


def test_browse_data_sources_fdsn_alias_mth5():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_sources", {"source_type": "mth5"}))
    assert data["status"] == "success"
    assert data["source_type"] == "fdsn"


def test_unified_load_data_source_hapi_routes_to_dedicated_tool():
    server = create_server()
    data = json.loads(_call_tool(server, "load_data_source", {"source_type": "hapi", "source_id": "x"}))
    assert data["status"] == "error"
    assert data["code"] == "use_dedicated_tool"
    assert "browse_hapi_catalog" in data["recommended_tools"]


def test_unified_fetch_data_product_fdsn_routes_to_dedicated_tool():
    server = create_server()
    data = json.loads(_call_tool(server, "fetch_data_product", {
        "source_type": "fdsn", "dataset_id": "x", "parameters": ["p"],
    }))
    assert data["status"] == "error"
    assert data["code"] == "use_dedicated_tool"
    assert "fetch_fdsn_data" in data["recommended_tools"]


def test_unified_browse_data_parameters_unknown_lists_new_sources():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_data_parameters", {
        "source_type": "nope", "dataset_id": "x",
    }))
    assert data["status"] == "error"
    assert data["code"] == "invalid_argument"
    assert {"hapi", "fdsn"} <= set(data["allowed"])


def test_browse_hapi_catalog_missing_dep_is_clean(tmp_path: Path):
    server = create_server()
    data = json.loads(_call_tool(server, "browse_hapi_catalog", {
        "server_url": "https://cdaweb.gsfc.nasa.gov/hapi",
    }))
    # Without the optional [hapi] extra installed the tool returns a structured
    # missing_dependency error rather than crashing.
    assert data["status"] == "error"
    assert data["code"] == "missing_dependency"
    assert data["extra"] == "hapi"


def test_browse_fdsn_datasets_missing_dep_is_clean():
    server = create_server()
    data = json.loads(_call_tool(server, "browse_fdsn_datasets", {
        "trange": ["2015-06-22", "2015-06-23"],
    }))
    assert data["status"] == "error"
    assert data["code"] == "missing_dependency"
    assert data["extra"] == "fdsn"


def test_browse_fdsn_datasets_bad_trange_validates_before_backend():
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
    from spedas_mcp.workflows import _extract_target

    assert _extract_target(goal) == expected


@_pytest_b1.mark.parametrize(
    "goal",
    # Suffix relaxation must not resurrect the generic-word false positives:
    # bare "ace"/"wind"/"solo"/"cluster" and plausible-suffix lookalikes.
    ["surface waves", "spacelike", "acexyz", "windy day", "soloist", "clustered"],
)
def test_extract_target_numbered_suffix_no_false_positive(goal):
    from spedas_mcp.workflows import _extract_target

    assert _extract_target(goal) is None


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
