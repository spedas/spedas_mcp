---
name: spedas-workflow
description: Use the spedas-agent-kit MCP server through the unified SPEDAS data layer and science workflow layer.
---

# SPEDAS Agent Kit workflow

The plugin exposes one MCP server named `spedas`. Start with `spedas_overview()` when uncertain.

Prefer the public SPEDAS mental model:

1. science workflow layer;
2. unified data layer;
3. data source categories: `cdaweb`, `pds`, `spice`;
4. internal backend packages only when maintaining/debugging the MCP.

## Preferred tools

- `search_spedas_data_sources`
- `plan_spedas_observation`
- `compare_cdaweb_pds_spice`
- `create_spedas_analysis_bundle`
- `browse_data_sources(source_type="all"|"cdaweb"|"pds"|"spice")`
- `load_data_source(source_type, source_id)`
- `browse_data_parameters(source_type, dataset_id, ...)`
- `fetch_data_product(source_type, ...)`
- `manage_data_cache(source_type, ...)`

Compatibility low-level tools remain available for maintenance/debugging, but new agent workflows should start with the unified data-layer tools.

## Guardrails

- Do not fetch large intervals until source_type, dataset_id, parameters, time range, output_dir, and provenance plan are clear.
- Prefer artifact paths, hashes, compact summaries, and provenance over pasted raw arrays/CDF contents.
- For PDS fetches, narrow by time and parameters; `limit` is not a PDS backend control.
- For SPICE geometry, use geometry tools after discovery; do not expect measurement parameters.
