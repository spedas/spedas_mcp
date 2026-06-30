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


## MMS reconnection events (Batch 006 guardrail)

For MMS reconnection/EDR papers, keep the first pass narrow and explicit: plan
with `spedas_overview` / `plan_spedas_observation`, fetch burst FGM/FPI/EDP
artifacts, then chain into existing analysis helpers before asking for new code.
Use `analyze_minvar_coordinates` plus `transform_timeseries_coordinates` for LMN
or field-aligned panels, and use `*-DIST` artifacts with
`compute_particle_spectra(..., spectrum_types=["energy", "pitch_angle"])` for
PAD/energy claims. A single-spacecraft `e*n_e*(V_i-V_e)` current or `J·E'` is a
transparent proxy, not a curlometer or paper-quality heating result; mark it
`proxy` unless the interval, LMN/FAC basis, calibrated E-field, and MMS1-4
curlometer diagnostics are all verified. If the paper/supplement interval cannot
be verified, record `candidate_interval` or `availability_failure` instead of
widening the fetch or claiming reproduction.

## Heliospheric ICME/SEP multi-spacecraft events (Batch 007 guardrail)

For Wind/ACE/STEREO/OMNI ICME, magnetic-cloud, CME-CME, or SEP papers, use
`paper-reproduction` as the outer artifact contract and treat
`docs/examples/stereo_icme_multispacecraft.md` as the reduced first-pass recipe.
Start with STEREO MAG `1min` + PLASTIC proton moments for multi-day events, add
Wind/ACE/OMNI only with explicit source/propagation labels, and keep SEP products
as `reduced_sep_proxy` until telescope/species/energy-channel metadata are
verified. Batch 007 confirmed that STEREO/PLASTIC/SEPT routing already exists;
the repeated gap is discoverability, event seeds, variable-alias provenance, and
overclaim prevention. Do not promote shock/sheath/cloud boundaries,
SEP onset/fluence, or SECCHI/HI J-map context to paper-quality outputs unless
those products and methods are explicitly loaded and documented.

## Magnetotail / multi-spacecraft boundary events (Batch 008 guardrail)

For Cluster, Geotail, or THEMIS magnetotail/boundary papers, use
`paper-reproduction` as the artifact contract and
`docs/examples/cluster_geotail_themis_magnetotail_multispacecraft.md` as the
first-pass recipe. Discover sources with `search_spedas_data_sources`, plan the
field/plasma/state products with `plan_spedas_observation`, and create a bundle
before plotting. Batch 008 showed that Cluster C1 CIS can load while the tested
Cluster FGM UP route returns no files; label those overviews
`single_spacecraft_cis` and `fgm_route_empty` instead of implying
four-spacecraft science. Keep the Geotail Nagai 2013 route scout labelled
`not_paper_exact` / `metadata_unresolved` until the actual event list and
methods are verified. Do not claim curlometer current density, gradients,
timing normals, KH-vortex morphology, shock normals, FTEs, or reconnection rates
without four-spacecraft magnetic fields, positions, cadence/frame checks, and
paper-interval provenance.

## Guardrails

- Do not fetch large intervals until source_type, dataset_id, parameters, time range, output_dir, and provenance plan are clear.
- Prefer artifact paths, hashes, compact summaries, and provenance over pasted raw arrays/CDF contents.
- For PDS fetches, narrow by time and parameters; `limit` is not a PDS backend control.
- For SPICE geometry, use geometry tools after discovery; do not expect measurement parameters.
