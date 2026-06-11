# spedas-mcp

Unified SPEDAS-oriented MCP server that composes focused XHelio building blocks:

- [`xhelio-cdaweb`](https://github.com/huangzesen/xhelio-cdaweb): CDAWeb observatory/dataset discovery, parameter metadata, and CDF data fetch.
- [`xhelio-pds`](https://github.com/huangzesen/xhelio-pds): NASA PDS Planetary Plasma Interactions mission/dataset discovery, parameter metadata, and PDS data fetch.
- [`xhelio-spice`](https://github.com/huangzesen/xhelio-spice): SPICE kernel management, spacecraft/body ephemeris, distances, and coordinate transforms.

The goal is not to replace SPEDAS/PySPEDAS in one step. The first repo boundary is a reliable MCP layer for Claude Code, Codex, and future SPEDAS plugins.

## Install

```bash
pip install spedas-mcp[mcp]
```

For development from source:

```bash
pip install -e '.[dev,mcp]'
pytest -q
```

For a CI-safe MCP check that does not fetch CDAWeb data or download SPICE kernels:

```bash
uv run --extra mcp python scripts/smoke_mcp_list_tools.py --json
```

The smoke starts the stdio server with isolated temporary caches, runs MCP
`initialize` + `list_tools`, and verifies the advertised tool names.

## Run

```bash
spedas-mcp
python -m spedas_mcp
```

Optional cache overrides:

```bash
spedas-mcp \
  --cdaweb-cache-dir /tmp/spedas-cdaweb-cache \
  --pds-cache-dir /tmp/spedas-pds-cache \
  --spice-kernel-dir /tmp/spedas-spice-kernels
```

## MCP tools

### Overview

- `spedas_overview()` — summarize available capability groups and workflow.

### CDAWeb tools

- `browse_observatories()`
- `load_observatory(observatory_id)`
- `browse_parameters(dataset_id, dataset_ids?)`
- `fetch_data(dataset_id, parameters, start, stop, output_dir, format="csv")`
- `manage_cdaweb_cache(action, ...)`

### PDS PPI tools

- `browse_pds_missions(query?)`
- `load_pds_mission(mission_id)`
- `browse_pds_parameters(dataset_id?, dataset_ids?)`
- `fetch_pds_data(dataset_id, parameters, start, stop, output_dir, format="csv")`
- `manage_pds_cache(action, ...)`

### SPICE tools

- `list_spice_missions()`
- `get_ephemeris(target, time, frame="ECLIPJ2000", observer="SUN", output_file="", time_end="", step="1h")`
- `compute_distance(target1, target2, time_start, time_end, step="1h")`
- `transform_coordinates(vector, time, from_frame, to_frame, spacecraft?)`
- `list_coordinate_frames()`
- `manage_spice_kernels(action, ...)`

## Agent workflow contract

1. Discover before fetching: `browse_observatories`, `load_observatory`, `browse_parameters`, `browse_pds_missions`, `load_pds_mission`, `browse_pds_parameters`, or `list_spice_missions` first.
2. Bulk data must go to files (`output_dir` / `output_file`), not inline chat.
3. Use compact summaries: paths, stats, units, coordinate frames, cache size, warnings.
4. Treat CDAWeb/PDS downloads and SPICE kernel downloads as integration actions; make time ranges small by default.

## Claude Code plugin path

A future Claude Code plugin can package this MCP server plus:

- skills: heliophysics workflow guidance;
- commands: `/spedas:cdaweb`, `/spedas:pds`, `/spedas:spice`, `/spedas:overview`;
- hooks: guardrails around huge downloads, missing output paths, and array-in-chat behavior.

The MCP layer should stay useful without Claude Code: any MCP-compatible harness can connect to `spedas-mcp`.
