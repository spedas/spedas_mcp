# Maintainer note: SPEDAS MCP data layer

`spedas_mcp` is the SPEDAS-facing MCP endpoint for agentic heliophysics workflows. Its outward-facing model is **one SPEDAS data layer**, not a pile of backend-specific MCPs.

It does **not** replace SPEDAS, PySPEDAS, CDAWeb, PDS, or SPICE. It gives MCP-capable coding/research agents one interface for planning and executing SPEDAS-related work with clearer data-source boundaries and provenance expectations.

## Core framing

Jason's latest direction is that the public interface should not preserve names like `xhelio_cdaweb` or `xhelio_pds` as the main user model. Those packages can remain internal backends. The SPEDAS MCP should expose:

- one `data` layer;
- data source categories under that layer;
- science workflow tools above the data layer;
- plugin/runtime packaging around the MCP, now owned by standalone wrapper repos (`spedas_claude`, `spedas_codex`) rather than by the MCP server repo itself.

## Data source categories

Current source categories:

- `cdaweb` — heliophysics observatory time-series, CDF-like intervals, plasma/fields/particles, solar-wind context.
- `pds` — Planetary Plasma Interactions mission/dataset discovery, PDS parameter metadata, and archive products.
- `spice` — geometry, ephemeris, trajectory, distances, coordinate frames, and transforms.

SPICE is a special case: it is part of the SPEDAS data context, but most useful operations are geometry computations rather than measurement-product fetches.

## Public layers

1. **Data layer**
   - `browse_data_sources`
   - `load_data_source`
   - `browse_data_parameters`
   - `fetch_data_product`
   - `manage_data_cache`

2. **Science workflow layer**
   - `search_spedas_data_sources`
   - `plan_spedas_observation`
   - `compare_cdaweb_pds_spice`
   - `create_spedas_analysis_bundle`

3. **Geometry layer**
   - SPICE-specific operations like `get_ephemeris`, `compute_distance`, and `transform_coordinates`.

4. **Compatibility layer**
   - Existing source-specific tools remain for clients that already know them, but docs and overview should steer new users to the unified data layer.

## Internal backend policy

Good fits for backend packages:

- CDAWeb catalog/fetch semantics → vendored `spedas_mcp.backends.cdaweb` backend (formerly `xhelio-cdaweb`).
- PDS archive resolution and dataset metadata → vendored `spedas_mcp.backends.pds` backend (formerly `xhelio-pds`).
- SPICE kernel registry and geometry computation → vendored `spedas_mcp.backends.spice` backend (formerly `xhelio-spice`).

Good fits for `spedas_mcp`:

- unified tool names and schemas;
- data-source taxonomy;
- cross-source planning logic;
- provenance bundle conventions;
- plugin wrapper references/examples, with canonical runtime-specific code in `spedas/spedas_claude` and `spedas/spedas_codex`;
- compatibility smoke tests.

## Near-term next steps

1. Add real end-to-end examples that combine measurement + geometry, such as Juno PDS + SPICE or MMS/CDAWeb + bow-shock geometry.
2. Decide whether compatibility low-level tools should remain public long-term or be hidden/renamed in a breaking API cleanup.
3. Add opt-in real-data integration smokes that write artifacts to temporary directories.
4. Prepare a small release once the data-layer API stabilizes.
