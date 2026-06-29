# src/spedas_mcp/backends — vendored data backends

## What this is

In-tree copies of the data backends the facade dispatches to (issue #107: absorb the former external `xhelio-*` packages so the repo is self-contained). Each sub-package exposes a library surface (catalog / metadata / fetch / cache / config) that `server.py` imports; their former standalone MCP servers/CLIs are dropped — the spedas_mcp facade replaces them.

## Components

- **`cdaweb/`** — vendored CDAWeb backend (was `xhelio-cdaweb`/`cdawebmcp`). Modules: `config.py` (cache root + bundled-data bootstrap), `catalog.py` (observatories), `metadata.py` (parameters; local cache → Master-CDF fallback), `fetch.py` (CDF fetch), `cache.py` (status/clean/rebuild), `http.py`, `prompts.py`, `validation.py`, `scripts/` (catalog/metadata builders). `data/observatories` + `data/prompts` are vendored seed; the 23 MB `data/metadata` bundle is excluded (regenerable via `scripts/build_metadata.py`, fetched on-miss). Imported by `server.py` for `source_type="cdaweb"`.
- **`pds/`, `spice/`** — NOT YET vendored; still external (`xhelio-pds`, `xhelio-spice`). Staged absorption per #107 (cdaweb first).

## Connections

- **In:** `server.py` tool closures import `spedas_mcp.backends.cdaweb.{catalog,metadata,fetch,cache,config}`.
- **Out:** cdaweb → `cdflib`, `pandas`, `numpy`, `requests`, CDAWeb REST + Master-CDF endpoints.

## Composition

- **Parent:** `src/spedas_mcp/`.

## State

- cdaweb bootstraps a runtime cache at `~/.cdawebmcp/` (metadata, cdf_cache) from the vendored seed; `manage_data_cache(source_type="cdaweb")` manages it.

## Notes

- Internal imports were rewritten `cdawebmcp.* → spedas_mcp.backends.cdaweb.*`. The absorption surfaced + fixed a latent bug: the facade called `cache_clean(observatory=...)` but the backend takes `observatories=[...]` (server.py now maps singular→list).
- Remaining work (#107): vendor `pds/` and `spice/` the same way (each its own PR, anatomy updated in the same commit); fold their deps; drop the `xhelio-pds`/`xhelio-spice` lines.
