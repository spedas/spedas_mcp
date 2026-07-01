---
name: omni-kyoto-noaa-smoke-workflows
description: Build lightweight OMNI/Kyoto/NOAA space-weather context and cache-only smoke workflows through Agent Kit resources, with MCP-first CDAWeb routes and clearly marked external PySPEDAS loader fallbacks.
---

# OMNI / Kyoto / NOAA smoke workflows

Use this skill when the user asks for a fast space-weather context bundle, a
geomagnetic-index smoke test, or a bounded preflight around solar-wind + Dst/AE/Kp
indices. It turns the PySPEDAS OMNI/Kyoto/NOAA loaders and IDL-SPEDAS overview
habits into a reproducible Agent Kit workflow without adding mission-specific MCP
tools.

Compose it with:

- `overview-geomagnetic-indices` for intent-to-dataset and parameter names.
- `pyspedas-load-planning` for `trange`, `time_clip=True`, cache, `downloadonly`,
  `notplot`, `no_update`, and variable-selection hygiene.
- `tplot-data-lifecycle` before plotting/exporting tplot variables.

## MCP/default-surface boundary

This skill adds **no MCP tool**. Keep the default Agent Kit `list_tools` surface
compact. Loader names below are external PySPEDAS runtime routes, not Agent Kit MCP
names:

```yaml
external_runtime_route:
  not_an_mcp_tool: true
  examples:
    - pyspedas.projects.omni.data
    - pyspedas.projects.kyoto.dst
    - pyspedas.projects.kyoto.load_ae
    - pyspedas.projects.kyoto.load_geomagnetic_indices
    - pyspedas.projects.noaa.noaa_load_kp
```

An MCP-only client should never call an invented `load_omni`, `kyoto_dst`,
`load_ae`, or `noaa_load_kp` tool. Use MCP resources and the unified data verbs:

1. `create_spedas_analysis_bundle(...)` for `output_dir` and
   `provenance/run.json`.
2. `spedas_overview()` and read `spedas-skill://skills/overview-geomagnetic-indices`
   if the index intent is unclear.
3. `browse_data_sources(source_type="cdaweb", query="OMNI")` or
   `search_spedas_data_sources(...)`.
4. `load_data_source(source_type="cdaweb", source_id=...)`,
   `browse_data_parameters(...)`, then `fetch_data_product(...)` for a bounded
   dataset/parameter/time range.
5. If exact Kyoto WDC or NOAA/GFZ loader behavior is required, record it as an
   external runtime requirement instead of expanding the MCP surface.

## Fast workflow cards

### 1. MCP-first OMNI storm / quiet-time context

Use this when the user needs solar-wind + geomagnetic context and does not require
Kyoto-WDC-only or NOAA/GFZ-only semantics.

- Create an analysis bundle before any fetch.
- Candidate CDAWeb datasets to browse first:
  - `OMNI_HRO_1MIN` or `OMNI_HRO2_1MIN` for high-cadence context.
  - `OMNI2_H0_MRG1HR` for hourly Dst/Kp/ap context.
- Browse before fetch; variable names can differ by product. Start with compact
  parameter subsets such as `BX_GSE`, `BY_GSM`, `BZ_GSM`, `flow_speed`,
  `Pressure`, `SYM_H`, `AE_INDEX`, `AL_INDEX`, `AU_INDEX`, `Kp`, `ap`, and `Dst`
  only after `browse_data_parameters(...)` confirms them.
- Use one short interval first (hours to one day). If the science question needs a
  storm multi-day context, fetch in explicit chunks and record each source file or
  artifact in provenance.
- Return paths, parameter names, sample counts, time spans, and caveats. Do not paste arrays into chat.

### 2. External PySPEDAS exact-loader route

Use this only when the surrounding runtime can import PySPEDAS and local policy
allows external data access or cache-only local reads. Mark the result as
`external_runtime_route.not_an_mcp_tool: true`.

| Source | External loader evidence | Good first use | Caveat |
|---|---|---|---|
| OMNI | `pyspedas.projects.omni.data(...)` / internal `load(..., datatype="1min"|"5min"|"hourly", level="hro"|"hro2", downloadonly=False, notplot=False, no_update=False, time_clip=True)` | quick solar-wind + OMNI-index context | Prefer MCP CDAWeb route unless local PySPEDAS execution is explicitly available. |
| Kyoto Dst | `pyspedas.projects.kyoto.dst(trange, datatypes=["final", "provisional", "realtime"], time_clip=True, prefix="", suffix="", no_download=False, download_only=False)` | exact Kyoto WDC Dst (`kyoto_dst`) | Kyoto data have WDC acknowledgement/redistribution constraints; record source and type. |
| Kyoto AE family | `pyspedas.projects.kyoto.load_ae(trange, datatypes=["ae", "al", "ao", "au", "ax"], time_clip=True, prefix="", suffix="", no_download=False, download_only=False, realtime=False)` | exact AE/AL/AU/AO/AX tplot variables | Use run-scoped prefix/suffix when comparing intervals. |
| Combined indices | `pyspedas.projects.kyoto.load_geomagnetic_indices(missions=["kyoto", "themis", "noaa", "gfz", "omni"], datatypes=..., omni_load_all=False, time_clip=True)` | local route scout across Dst/AE/Kp/OMNI families | This is a PySPEDAS convenience helper, not a new Agent Kit tool. |
| NOAA/GFZ Kp | `pyspedas.projects.noaa.noaa_load_kp(trange, datatype=["Kp", "ap", "Kp_Sum", ...], gfz=False, prefix="", suffix="", time_clip=True)` | Kp/ap/F10.7 context or Kp smoke | GFZ is default for some modern dates and lacks NOAA-only Sunspot/F10.7/Flux qualifier fields. |

### 3. Cache-only / no-network smoke

Use this for CI, review, and cold-cache diagnostics. The goal is to prove the
route and provenance shape, not to guarantee public archive availability.

- Prefer static MCP resource tests and plan-only checks in CI; do not require live
  network downloads.
- If local PySPEDAS cache is intentionally seeded, use `no_update=True` for OMNI,
  `no_download=True` / `download_only=True` for Kyoto, or a local Kp directory for
  NOAA/GFZ where applicable.
- Use `downloadonly=True` to create source-file artifacts without loading tplot
  variables when validating source availability.
- Use `notplot=True` for compact metadata inspection, then export summaries rather
  than raw arrays.
- Record cache mode (`cache_only`, `downloadonly`, `cold_cache`, or
  `live_archive_fetch`) in `provenance/run.json`.

## Minimal smoke recipe template

```yaml
study_name: omni_kyoto_noaa_smoke
quality_label: route_scout
trange: ["2015-03-17T00:00:00Z", "2015-03-17T06:00:00Z"]
agent_kit_route:
  source_type: cdaweb
  candidate_datasets: [OMNI_HRO_1MIN, OMNI_HRO2_1MIN, OMNI2_H0_MRG1HR]
  browse_parameters_first: true
  candidate_parameters: [BX_GSE, BY_GSM, BZ_GSM, Pressure, SYM_H, AE_INDEX, AL_INDEX, AU_INDEX, Kp, ap, Dst]
external_runtime_route:
  not_an_mcp_tool: true
  pyspedas_loaders:
    - pyspedas.projects.omni.data
    - pyspedas.projects.kyoto.dst
    - pyspedas.projects.kyoto.load_ae
    - pyspedas.projects.noaa.noaa_load_kp
provenance_required:
  - dataset_id_or_loader
  - variable_or_parameter_subset
  - requested_trange
  - actual_clipped_range
  - cache_mode
  - artifact_paths
  - caveats
```

Keep the label `route_scout` or `context_smoke` unless the requested paper/event
analysis is reproduced with its exact products, cadence, station/spacecraft choice,
and analysis method. OMNI/Kyoto/NOAA context does not by itself reproduce TEC,
GIC, auroral imaging, ENA imaging, particle precipitation, or ground-network
responses.

## Provenance checklist

For every real execution or local route scout, update `provenance/run.json` with:

- The Agent Kit MCP resource/skill chain used (`spedas-skill://skills/...`).
- Dataset IDs or exact external loader names and options.
- Requested and clipped time ranges.
- Parameter/variable subset, units/frame/cadence when known, and tplot prefix/suffix.
- Cache/data-access mode: no network, cache-only, download-only, live fetch, cold
  cache, public archive rate-limit caveat.
- Artifact paths for downloaded files, compact metadata, plots, exported tables,
  and validation logs.
- Caveats that distinguish context from science reproduction.

## Source evidence

- PySPEDAS OMNI source: `pyspedas/projects/omni/load.py` (`downloadonly`,
  `notplot`, `no_update`, `time_clip`, `datatype`, `level`, `varformat`,
  `varnames`) and `tests/test_omni.py` examples.
- PySPEDAS Kyoto source: `pyspedas/projects/kyoto/load_dst.py`, `load_ae.py`, and
  `load_geomagnetic_indices.py` (Dst, AE/AL/AU/AO/AX, OMNI `AE_INDEX`, `SYM_H`,
  `Pressure`, NOAA/GFZ Kp/ap families).
- PySPEDAS NOAA source: `pyspedas/projects/noaa/noaa_load_kp.py` (`Kp`, `ap`,
  `Kp_Sum`, `F10.7`, `gfz`, `prefix`, `suffix`, `time_clip`).
- Existing Agent Kit bridge: `overview-geomagnetic-indices` already maps common
  storm-index intents to MCP-first CDAWeb datasets and external PySPEDAS caveats.
