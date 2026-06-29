# src/spedas_agent_kit/backends — vendored data backends

## What this is

In-tree copies of ALL data backends the facade dispatches to (issue #107: the former external `xhelio-*` packages, now fully absorbed so the repo is self-contained). Each sub-package exposes a library surface (catalog / metadata / fetch / cache / config) that `server.py` imports; their former standalone MCP servers/CLIs are dropped — the spedas_agent_kit facade replaces them.

## Components

- **`cdaweb/`** — vendored CDAWeb backend (was `xhelio-cdaweb`/`cdawebmcp`). Modules: `config.py` (cache root + bundled-data bootstrap), `catalog.py` (observatories), `metadata.py` (parameters; local cache → Master-CDF fallback), `fetch.py` (CDF fetch), `cache.py` (status/clean/rebuild), `http.py`, `prompts.py`, `validation.py`, `scripts/` (catalog/metadata builders). `data/observatories` + `data/prompts` are vendored seed; the 23 MB `data/metadata` bundle is excluded (regenerable via `scripts/build_metadata.py`, fetched on-miss). Imported by `server.py` for `source_type="cdaweb"`.
- **`pds/`** — vendored PDS PPI backend (was `xhelio-pds`/`pdsmcp`). Same module shape as cdaweb plus `label_parser.py` (PDS3/PDS4 ASCII/XML labels). `data/missions` (432KB) + `data/prompts` vendored seed; 4.4MB `data/metadata` excluded (regenerable, fetched on-miss). Imported by `server.py` for `source_type="pds"`. Deps: pandas/numpy/requests (no cdflib — PDS is ASCII/XML, not CDF).
- **`spice/`** — vendored SPICE/ephemeris backend (was `xhelio-spice`). Modules: `ephemeris.py` (get_state/get_trajectory/get_position), `frames.py` (frame catalog + aliases), `missions.py` (87-mission registry + resolve), `kernel_manager.py` (on-demand NAIF kernel download + cache + gating). `manifests/` (384KB, mission kernel definitions) vendored; actual kernels download on-demand to `~/.xhelio_spice/kernels/` (none bundled). Imported by `server.py` for `source_type="spice"` + the geometry tools. Deps: spiceypy, numpy, pandas, requests, beautifulsoup4.

## Connections

- **In:** `server.py` tool closures import `spedas_agent_kit.backends.cdaweb.{catalog,metadata,fetch,cache,config}`.
- **Out:** cdaweb → `cdflib`/pandas/numpy/requests + CDAWeb REST/Master-CDF; pds → pandas/numpy/requests + PDS PPI archive (ASCII/XML labels via `label_parser`); spice → spiceypy/numpy/pandas/requests/beautifulsoup4 + public NAIF kernel archives.

## Composition

- **Parent:** `src/spedas_agent_kit/`.

## State

- cdaweb bootstraps a runtime cache at `~/.cdawebmcp/` (metadata, cdf_cache) from the vendored seed; `manage_data_cache(source_type="cdaweb")` manages it.
- pds bootstraps a runtime cache at `~/.pdsmcp/` (metadata, data_cache) from the vendored seed; `manage_data_cache(source_type="pds")` manages it.
- spice keeps the former kernel cache path `~/.xhelio_spice/kernels/` for backward-compatible on-demand NAIF downloads; `manage_data_cache(source_type="spice")` manages it.

## Notes

- Internal imports were rewritten `cdawebmcp.* → spedas_agent_kit.backends.cdaweb.*`. The absorption surfaced + fixed a latent bug: the facade called `cache_clean(observatory=...)` but the backend takes `observatories=[...]` (server.py now maps singular→list).
- #107 COMPLETE: all three backends (cdaweb, pds, spice) are vendored; no `xhelio-*` runtime dependencies remain.
