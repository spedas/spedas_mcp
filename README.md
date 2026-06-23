# SPEDAS MCP

`spedas_mcp` is the SPEDAS organization MCP server for agentic heliophysics workflows. It presents one SPEDAS-facing **data layer** and organizes capabilities by data source category instead of by the internal backend packages used to implement them.

The current design follows Jason's A+B direction:

- **A. SPEDAS data layer** — one unified entry point for source categories such as `cdaweb`, `pds`, and `spice`/geometry.
- **B. SPEDAS science workflow layer** — high-level planning tools that let Claude Code, Codex, OpenCode, LingTai, or another agent start from a science question before choosing source-specific operations.

The `xhelio-*` packages are implementation backends. They should stay visible to maintainers, but they should not be the user's first mental model.

## Repository

- Official repo: <https://github.com/spedas/spedas_mcp>
- Python package name: `spedas-mcp`
- Python module / CLI module: `spedas_mcp`
- Current MCP tool count: 26

## Layered capability map

### 1. Data layer tools

Start here when the user asks for data, datasets, parameters, products, archives, or cache status.

- `browse_data_sources(source_type="all", query=None)` — browse SPEDAS data source categories, or drill into one category.
- `load_data_source(source_type, source_id)` — load source context, e.g. a CDAWeb observatory, PDS mission, or SPICE mission/frame context.
- `browse_data_parameters(source_type, dataset_id, dataset_ids=None)` — browse parameters/metadata for CDAWeb or PDS datasets; for SPICE, returns geometry/frame context.
- `fetch_data_product(source_type, dataset_id, parameters, start=None, stop=None, output_dir=None, format="csv", limit=None)` — unified measurement/archive data fetch for CDAWeb/PDS. SPICE requests are routed to geometry tools instead.
- `manage_data_cache(source_type="all", action="status", cache_dir=None, mission=None)` — unified cache status/maintenance for the source categories.

Supported `source_type` values:

| source_type | Use for | Main data-layer path |
|---|---|---|
| `cdaweb` | heliophysics observatory time-series, plasma/fields/particles, solar wind, CDF-like intervals | `browse_data_sources` → `load_data_source` → `browse_data_parameters` → `fetch_data_product` |
| `pds` | Planetary Plasma Interactions archives, planetary mission datasets, PDS metadata/products | `browse_data_sources` → `load_data_source` → `browse_data_parameters` → `fetch_data_product` |
| `spice` | geometry, ephemeris, trajectory, distance, coordinate frames/transforms | `browse_data_sources` → `load_data_source` → geometry tools |

### 2. Science workflow tools

Start here for open-ended science requests.

- `spedas_overview()` — compact map of capability groups and recommended workflow.
- `search_spedas_data_sources(question, target=None, observables=None)` — recommend which data source categories should lead a request.
- `plan_spedas_observation(science_goal, start=None, stop=None, target=None, observables=None, data_sources=None)` — produce a source-specific plan before fetching data.
- `compare_cdaweb_pds_spice(science_goal="")` — explain source boundaries and choose the right source family.
- `create_spedas_analysis_bundle(study_name, output_dir, ...)` — create a request/provenance scaffold with `requests/`, `data/`, `plots/`, `provenance/`, and `notes/` folders.

### 3. Geometry tools

SPICE is exposed as a data source category, but geometry operations are clearer as explicit tools:

- `list_spice_missions()`
- `get_ephemeris(mission, target, start, stop, step="1h", frame="J2000", observer=None)`
- `compute_distance(mission, target, observer, start, stop, step="1h")`
- `transform_coordinates(mission, coordinates, from_frame, to_frame, epoch=None)`
- `list_coordinate_frames(mission=None)`
- `manage_spice_kernels(action, mission=None, cache_dir=None)`

### 4. Compatibility low-level tools

These remain available for clients that already know the source-specific operations:

- CDAWeb: `browse_observatories`, `load_observatory`, `browse_parameters`, `fetch_data`, `manage_cdaweb_cache`
- PDS: `browse_pds_missions`, `load_pds_mission`, `browse_pds_parameters`, `fetch_pds_data`, `manage_pds_cache`
- SPICE: the geometry tools above plus `manage_spice_kernels`

Future cleanup can hide or rename some compatibility tools if we decide to make a breaking API pass. For now the primary docs and `spedas_overview` route users to the unified data layer.

## Recommended agent workflow

1. Call `spedas_overview()`.
2. For a natural-language science request, call `search_spedas_data_sources(...)` or `plan_spedas_observation(...)`.
3. Use the data layer:
   - `browse_data_sources(source_type="all")`
   - `browse_data_sources(source_type="cdaweb" | "pds" | "spice")`
   - `load_data_source(...)`
   - `browse_data_parameters(...)`
   - `fetch_data_product(...)` for CDAWeb/PDS measurement/archive products
4. Use geometry tools directly for SPICE ephemeris, distance, frame, and coordinate-transform work.
5. For any real analysis, call `create_spedas_analysis_bundle(...)` and write fetched files under the generated `data/` directory.
6. Return compact summaries and file paths. Do not paste large science arrays into chat.

## Quick start for local development

```bash
git clone https://github.com/spedas/spedas_mcp.git
cd spedas_mcp
uv sync --extra dev --extra mcp
uv run --extra mcp python -m spedas_mcp
```

Run tests and smoke checks:

```bash
uv run --extra dev --extra mcp python -m pytest -q
uv run --extra mcp python scripts/smoke_mcp_list_tools.py --json
uv run --extra dev --extra mcp python scripts/validate_plugin_packages.py
```

The list-tools smoke starts the stdio MCP server with isolated temporary cache directories, performs MCP `initialize` + `list_tools`, and verifies the expected advertised tool names. It does not fetch CDAWeb/PDS data or download SPICE kernels.

## MCP client configuration

Example stdio configuration:

```json
{
  "mcpServers": {
    "spedas": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "python", "-m", "spedas_mcp"],
      "cwd": "/path/to/spedas_mcp"
    }
  }
}
```

For plugin-style distribution, see:

- `plugins/spedas-claude/` — Claude Code wrapper.
- `.agents/plugins/spedas-codex/` — Codex plugin wrapper.
- `plugins/README.md` — plugin packaging notes.

## Maintainer-facing positioning

`spedas_mcp` should be thick at the SPEDAS data/workflow layer and thin at the backend implementation layer:

- Users see one SPEDAS MCP and one `data` layer.
- Data source categories are scientific concepts: CDAWeb, PDS, SPICE/geometry.
- Backend packages remain maintainable internal implementation surfaces.
- Higher-level tools should encode reusable SPEDAS scientific method: source selection, planning, provenance, and artifact discipline.

See `docs/maintainer_note.md` and `docs/examples/agent_workflow.md` for the current framing.
