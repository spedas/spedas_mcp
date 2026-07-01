---
name: pyspedas-load-planning
description: Plan PySPEDAS mission/product/time data loads through Agent Kit's compact MCP surface, preserving time clipping, cache, variable naming, and provenance hygiene without adding mission-specific tools.
---

# PySPEDAS load planning

Use this skill when a user asks for a SPEDAS/PySPEDAS data load, mission/product selection, quick-look data availability check, or a reproducible first-pass load plan. It translates PySPEDAS loader vocabulary into the SPEDAS Agent Kit workflow without expanding the default MCP tool surface.

## MCP/default-surface boundary

This skill adds no MCP tool. When documenting external routes, use the structured marker `external_runtime_route.not_an_mcp_tool: true`. PySPEDAS loader functions such as `pyspedas.themis.fgm`, `pyspedas.mms.fgm`, `pyspedas.omni.data`, `pyspedas.kyoto.dst`, or `pyspedas.noaa.noaa_load_kp` are **external runtime routes** and are `not_an_mcp_tool` unless a future Agent Kit tool explicitly exposes them. For MCP-only clients, route through the compact Agent Kit surface:

1. `spedas_overview()` when uncertain.
2. `create_spedas_analysis_bundle(...)` for a run directory and `provenance/run.json`.
3. `search_spedas_data_sources(...)` or `browse_data_sources(...)` for source discovery.
4. `plan_spedas_observation(...)` before fetching.
5. `browse_data_parameters(...)`, `load_data_source(...)`, `fetch_data_product(...)`, and `manage_data_cache(...)` only after the plan is bounded.

## Loader contract to preserve

| PySPEDAS concept | Planning rule for agents |
|---|---|
| `trange` | Use a narrow, explicit UTC range. Do not let an exploratory request become a multi-day fetch unless the user asks. |
| `time_clip=True` | Prefer or explicitly discuss `time_clip=True`; PySPEDAS can load whole CDF spans around a requested time range. |
| `downloadonly` | Use `downloadonly` or Agent Kit plan/cache discovery for preflight provenance when data volume or source availability is uncertain. |
| `notplot` | Use `notplot` or an Agent Kit compact metadata route when the next step is inspection, not plotting; avoid dumping arrays into chat. |
| `no_update` | Use `no_update` / cache-only validation for reproducible tests, CI, and cold-cache caveats. |
| `prefix` / `suffix` | Require run-scoped prefixes or suffixes when loading overlapping missions/products to avoid tplot name collisions. |
| `varformat` / `varnames` | Request only the variables needed for the science question. Record the variable selection in provenance. |
| `level` / `datatype` / `probe` / `instrument` | Treat these as science choices, not defaults to guess silently. If uncertain, browse or ask; for autonomous work, choose a documented minimal product and label it. |
| `get_support_data` | Include support data only when the analysis requires it; otherwise keep the first-pass load compact. |

## Planning procedure

1. **Restate the science intent.** Identify mission, target interval, coordinate/context needs, and expected artifact: table, plot, CDF/CSV, or analysis bundle.
2. **Create or reuse an analysis bundle.** Prefer `create_spedas_analysis_bundle(...)`; update `provenance/run.json` after every real load, derived variable, plot, or caveat.
3. **Select the source route.** Prefer Agent Kit's unified route. Use external PySPEDAS only when the required loader is not yet represented by Agent Kit discovery/fetch tools, and mark that route as `not_an_mcp_tool`.
4. **Make the load bounded.** Include `trange`, product/instrument/datatype, variable subset, `time_clip=True` or an explicit reason not to clip, cache policy, and output directory.
5. **Plan before fetch.** Use discovery and planning calls first; fetch only the smallest interval/product that answers the question.
6. **Preserve provenance.** Record source type, mission/product, loader-like options, cache mode, variable names, and output artifact paths. Do not paste raw tplot arrays.

## Fast first-pass patterns

- **OMNI/Kyoto/NOAA indices:** small bounded intervals are good smoke tests. Use the geomagnetic/overview skill for Dst/AE/Kp/SYM-H context, then write artifact summaries and caveats.
- **THEMIS FGM/state:** choose probes and instrument/datatype deliberately; prefer one probe or a short multi-probe interval before expanding.
- **MMS FGM/MEC/FPI:** start with FGM/MEC overview or cache-only planning. Burst/FPI/particle products can be large; hand off to dedicated MMS/particle skills when needed.
- **PSP/Solar Orbiter:** keep heliophysics intervals narrow and cite coordinate/frame assumptions before combining with SPICE geometry.

## Provenance checklist

Every real load plan or execution should leave enough grain for another agent to reproduce it:

- Mission/source and dataset/product identifiers.
- Requested `trange` and actual clipped range.
- Loader-like options: `time_clip=True`, `downloadonly`, `notplot`, `no_update`, `prefix`/`suffix`, `varnames`/`varformat`, support-data policy.
- Cache/source state: cold cache, cache-only, public archive rate limit, authentication caveat.
- Artifact paths: downloaded files, compact metadata JSON, figures, exported tables, and `provenance/run.json`.
- Known limitations and whether the route was Agent Kit MCP, packaged resource, or external PySPEDAS runtime.
