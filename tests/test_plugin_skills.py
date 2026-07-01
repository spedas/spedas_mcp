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


def test_batch008_magnetotail_guardrails_are_indexed():
    workflow = (ROOT / "plugins/spedas-claude/skills/spedas-workflow/SKILL.md").read_text(encoding="utf-8")
    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    gradients = (ROOT / "plugins/spedas-claude/skills/multi-spacecraft-gradients/SKILL.md").read_text(encoding="utf-8")
    doc = (ROOT / "docs/examples/cluster_geotail_themis_magnetotail_multispacecraft.md").read_text(encoding="utf-8")
    presets = (ROOT / "docs/examples/solar_wind_event_presets.md").read_text(encoding="utf-8")

    assert "Magnetotail / multi-spacecraft boundary events (Batch 008 guardrail)" in workflow
    assert "cluster_geotail_themis_magnetotail_multispacecraft.md" in workflow
    assert "single_spacecraft_cis" in workflow
    assert "fgm_route_empty" in workflow
    assert "not_paper_exact" in workflow
    assert "four-spacecraft magnetic fields" in workflow

    assert "cluster_geotail_themis_magnetotail_multispacecraft.md" in index
    assert "fgm_route_empty" in index
    assert "not_paper_exact" in index

    assert "Batch 008 magnetotail guardrail" in gradients
    assert "single_spacecraft_cis" in gradients
    assert "fgm_route_empty" in gradients
    assert "not_paper_exact" in gradients

    for expected in [
        "10.1038/nature02799",
        "10.1038/nphys574",
        "10.1002/jgra.50247",
    ]:
        assert expected in doc
        assert expected in presets
    assert "single_spacecraft_cis" in doc and "single_spacecraft_cis" in presets
    assert "fgm_route_empty" in doc and "fgm_route_empty" in presets
    assert "metadata_unresolved" in doc and "metadata_unresolved" in presets
    assert "not_paper_exact" in doc and "not_paper_exact" in presets
    assert "10.1126/science.1160495" in doc
    assert "10.1029/2009GL038980" in doc
    assert presets.count("10.1126/science.1160495") == 1
    assert presets.count("10.1029/2009GL038980") == 1


def test_batch009_storm_context_guardrails_are_indexed():
    overview = (ROOT / "plugins/spedas-claude/skills/overview-geomagnetic-indices/SKILL.md").read_text(encoding="utf-8")
    storm = (ROOT / "plugins/spedas-claude/skills/solar-wind-icme-storm/SKILL.md").read_text(encoding="utf-8")
    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    presets = (ROOT / "docs/examples/solar_wind_event_presets.md").read_text(encoding="utf-8")

    assert "GOES XRS operational context" in overview
    assert "pyspedas.goes.xrs" in overview
    assert "St. Patrick's Day 2015" in overview
    assert "not a TEC" in overview
    assert "ionosphere data assimilation" in overview
    assert "GIC" in overview and "reproduction" in overview
    assert "ENA imaging" in overview
    assert "precipitation" in overview
    assert "doi_verified_crossref_preprint" in overview

    assert "Batch-009 storm/operational-context cross-reference" in storm
    assert "not add duplicate seed rows" in storm
    assert "GOES XRS operational storm context" in index

    for expected in [
        "10.1002/2016JA023346",
        "10.31401/ws.2024.proc.10",
        "10.22541/essoar.175767277.75279168/v1",
    ]:
        assert expected in presets
    assert "For Batch 009 storm/operational-context seeds" in presets
    assert "10.1029/2009GL038853" not in presets
    assert "10.1186/BF03351958" not in presets
    assert presets.count("10.1029/2004JA010494") == 1
    assert presets.count("10.1029/2001GL014136") == 1


def test_external_pyspedas_routes_are_gated_for_mcp_only_clients():
    """Shared skill route prose should not make MCP-only clients invent PySPEDAS tools."""

    skill_root = ROOT / "plugins/spedas-claude/skills"
    overview = (skill_root / "overview-geomagnetic-indices/SKILL.md").read_text(encoding="utf-8")
    wave = (skill_root / "wave-polarization/SKILL.md").read_text(encoding="utf-8")
    neutral = (skill_root / "neutral-sheet-distance/SKILL.md").read_text(encoding="utf-8")
    erg = (skill_root / "erg-arase-radiation-belt-waves/SKILL.md").read_text(encoding="utf-8")
    presets = (ROOT / "docs/examples/solar_wind_event_presets.md").read_text(encoding="utf-8")
    preset_resource = (
        ROOT / "src/spedas_agent_kit/resources/presets/solar_wind_event_presets.json"
    ).read_text(encoding="utf-8")

    for text in [overview, wave, neutral, erg]:
        assert "external_runtime_route.not_an_mcp_tool" in text
        assert "MCP-only" in text

    assert "guided_recipes.geomagnetic_indices[*].mcp_first_route" in overview
    assert "OMNI2_H0_MRG1HR" in overview
    assert "pyspedas.goes.xrs" in overview
    assert "not attempt to call `goes.xrs` as an Agent Kit MCP tool" in overview

    assert "do not invent a\n`twavpol` MCP call" in wave
    assert "Do not attempt to call\n`neutral_sheet` as an MCP tool" in neutral
    assert "should not\ninvent dataset IDs or MCP tool names" in erg

    assert "not an Agent Kit MCP tool" in presets
    assert "not an Agent Kit MCP tool" in preset_resource


def test_batch010_erg_arase_guardrails_are_indexed():
    skill = (ROOT / "plugins/spedas-claude/skills/erg-arase-radiation-belt-waves/SKILL.md").read_text(encoding="utf-8")
    index = (ROOT / "plugins/spedas-claude/skills/spedas-skills-index/SKILL.md").read_text(encoding="utf-8")

    assert "name: erg-arase-radiation-belt-waves" in skill
    for expected in [
        "pyspedas.erg.mgf",
        "pyspedas.erg.pwe_ofa",
        "pyspedas.erg.pwe_hfa",
        "omniflux",
        "gmag_isee_fluxgate",
        "camera_omti_asi",
        "OMTI",
        "PySPEDAS-only",
        "instrument/data-route anchor",
        "not PSD",
        "10.1038/nature25505",
        "10.1186/s40623-018-0854-0",
        "10.1186/s40623-018-0853-1",
        "10.1186/s40623-018-0800-1",
        "10.1029/2024JA032617",
    ]:
        assert expected in skill

    assert "erg-arase-radiation-belt-waves" in index
    assert "ISEE/OMTI/MAGDAS" in index


def test_batch001_pyspedas_foundation_skills_are_indexed_and_guarded() -> None:
    skill_root = ROOT / "plugins/spedas-claude/skills"
    source_root = ROOT / "src/spedas_agent_kit/resources/skills"
    index = (skill_root / "spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    load = (source_root / "pyspedas-load-planning/SKILL.md").read_text(encoding="utf-8")
    tplot = (source_root / "tplot-data-lifecycle/SKILL.md").read_text(encoding="utf-8")
    heritage = (source_root / "spedas-heritage-vocabulary/SKILL.md").read_text(encoding="utf-8")

    for skill_name in [
        "pyspedas-load-planning",
        "tplot-data-lifecycle",
        "spedas-heritage-vocabulary",
    ]:
        assert skill_name in index

    for expected in [
        "time_clip=True",
        "`downloadonly`",
        "`notplot`",
        "`no_update`",
        "not_an_mcp_tool",
        "external_runtime_route.not_an_mcp_tool: true",
        "create_spedas_analysis_bundle",
    ]:
        assert expected in load

    for expected in [
        "STORE_DATA",
        "GET_DATA",
        "tplot_names",
        "artifact-first",
        "Do not paste raw arrays",
        "not_an_mcp_tool",
    ]:
        assert expected in tplot

    for expected in [
        "IDL SPEDAS",
        "GUI plugin",
        "`project`",
        "`load_data`",
        "not_an_mcp_tool",
        "PySPEDAS/PyTplot functions are source evidence or external runtime routes",
    ]:
        assert expected in heritage

def test_batch002_omni_kyoto_noaa_smoke_workflow_is_indexed_and_guarded() -> None:
    skill_root = ROOT / "plugins/spedas-claude/skills"
    source_root = ROOT / "src/spedas_agent_kit/resources/skills"
    index = (skill_root / "spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    skill = (source_root / "omni-kyoto-noaa-smoke-workflows/SKILL.md").read_text(encoding="utf-8")

    assert "omni-kyoto-noaa-smoke-workflows" in index
    for expected in [
        "OMNI_HRO_1MIN",
        "OMNI_HRO2_1MIN",
        "OMNI2_H0_MRG1HR",
        "AE_INDEX",
        "SYM_H",
        "Kp",
        "pyspedas.projects.omni.data",
        "pyspedas.projects.kyoto.load_geomagnetic_indices",
        "pyspedas.projects.noaa.noaa_load_kp",
        "not_an_mcp_tool",
        "external_runtime_route.not_an_mcp_tool: true",
        "downloadonly=True",
        "notplot=True",
        "no_update=True",
        "cache-only",
        "Do not paste arrays",
        "provenance/run.json",
    ]:
        assert expected in skill


def test_systematic_batch003_themis_workflows_are_indexed_and_guarded() -> None:
    skill_root = ROOT / "plugins/spedas-claude/skills"
    source_root = ROOT / "src/spedas_agent_kit/resources/skills"
    index = (skill_root / "spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    skill = (source_root / "themis-workflows/SKILL.md").read_text(encoding="utf-8")

    assert "themis-workflows" in index
    for expected in [
        "THA_L2_FGM",
        "THA_L2_ESA",
        "THA_L2_SST",
        "THA_OR_SSC",
        "pyspedas.projects.themis.fgm",
        "pyspedas.projects.themis.esa",
        "pyspedas.projects.themis.sst",
        "pyspedas.projects.themis.scm",
        "pyspedas.projects.themis.gmag",
        "pyspedas.projects.themis.ask",
        "pyspedas.projects.themis.ssc",
        "not_an_mcp_tool",
        "external_runtime_route.not_an_mcp_tool: true",
        "downloadonly=True",
        "notplot=True",
        "no_update=True",
        "not_gradient_ready",
        "single_spacecraft_route_scout",
        "Do not paste arrays",
        "create_spedas_analysis_bundle",
        "thm_load_fgm",
    ]:
        assert expected in skill


def test_systematic_batch004_mms_workflows_are_indexed_and_guarded() -> None:
    skill_root = ROOT / "plugins/spedas-claude/skills"
    source_root = ROOT / "src/spedas_agent_kit/resources/skills"
    index = (skill_root / "spedas-skills-index/SKILL.md").read_text(encoding="utf-8")
    skill = (source_root / "mms-basic-workflows/SKILL.md").read_text(encoding="utf-8")

    assert "mms-basic-workflows" in index
    for expected in [
        "MMS1_FGM_SRVY_L2",
        "MMS1_MEC_SRVY_L2_EPHT89D",
        "MMS1_SCM_SRVY_L2_SCSRVY",
        "MMS1_FPI_FAST_L2_DIS-MOMS",
        "MMS1_EDP_FAST_L2_DCE",
        "MMS1_HPCA_SRVY_L2_MOMENTS",
        "pyspedas.projects.mms.fgm",
        "pyspedas.projects.mms.mec",
        "pyspedas.projects.mms.scm",
        "pyspedas.projects.mms.fpi",
        "pyspedas.projects.mms.hpca",
        "pyspedas.projects.mms.edp",
        "pyspedas.projects.mms.curlometer",
        "pyspedas.projects.mms.lingradest",
        "pyspedas.projects.mms.fpi_tools.mms_pad_fpi.mms_pad_fpi",
        "pyspedas.projects.mms.fpi_tools.mms_load_fpi_calc_pad.mms_load_fpi_calc_pad",
        "pyspedas.projects.mms.particles.mms_part_getspec.mms_part_getspec",
        "pyspedas.projects.mms.particles.mms_part_slice2d.mms_part_slice2d",
        "mms_load_fpi_calc_pad",
        "magf",
        "not_an_mcp_tool",
        "external_runtime_route.not_an_mcp_tool: true",
        "available=True",
        "notplot=True",
        "no_update=True",
        "not_gradient_ready",
        "single_spacecraft_route_scout",
        "Do not paste arrays",
        "create_spedas_analysis_bundle",
        "mms_load_fgm",
    ]:
        assert expected in skill

    for forbidden in [
        "pyspedas.projects.mms.mms_pad_fpi",
        "pyspedas.projects.mms.mms_load_fpi_calc_pad",
        "pyspedas.projects.mms.mms_part_getspec",
        "pyspedas.projects.mms.mms_part_slice2d",
    ]:
        assert forbidden not in skill
