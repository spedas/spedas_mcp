# src/spedas_agent_kit/datasources — optional HAPI + FDSN backends

## What this is

Two opt-in data-source adapters reached through the unified data layer with `source_type="hapi"` / `"fdsn"`. Lazily imported so the base install stays light; absent extras yield a clean `missing_dependency` error rather than a crash.

## Components

- **`hapi.py`** (315) — `browse_hapi_catalog` `:32` (lists datasets from any HAPI server; omits absent titles, exposes `title_count`/truncation), `fetch_hapi_data` `:146` (fetch via hapiclient → artifact). Needs `spedas-agent-kit[hapi]`.
- **`fdsn.py`** (288) — `browse_fdsn_datasets` `:37` (EarthScope magnetotelluric stations), `fetch_fdsn_data` `:113` (via pyspedas.mth5). Needs `spedas-agent-kit[fdsn]` (mth5 + obspy).
- **`__init__.py`** (159) — `require_hapiclient()` / `require_mth5()` import guards + `_missing_dependency_error()`. The guard must distinguish "not installed" from a namespace-shadow/broken install (a prior bug leaked a misleading `cannot import name config from mth5`).

## Connections

- **In:** `server.py` routes `browse_data_sources`/`fetch_data_product` with `source_type="hapi"|"fdsn"` here.
- **Out:** `hapiclient` (HAPI servers: CDAWeb, PDS-PPI, ISWA, LISIRD…); `pyspedas.mth5` → mth5 + obspy → EarthScope FDSN.
- Returns the same artifact-first shape as the core data layer (paths + metadata).

## Composition

- **Parent:** `src/spedas_agent_kit/` (`../ANATOMY.md`).

## State

- None in-process; fetches write to the caller's `output_dir`. hapiclient maintains its own cache in the user's home.

## Notes

- These extras are heavier and niche (ground magnetometers, generic HAPI), kept out of base/analysis deliberately. Keep the `require_*` guards precise: report "install spedas-agent-kit[hapi|fdsn]", not the raw upstream ImportError.
- HAPI `/catalog` for CDAWeb carries no titles — `title_count: 0` + a note is expected, not a bug.
