---
name: spedas-skills-index
description: Start here. Routes a heliophysics intent to the right spedas skill and the first tool to call, so an agent needs to know one thing up front instead of memorizing the runtime MCP tool list. Read this, then load one focused skill.
---

# SPEDAS skills index

The `spedas` MCP server advertises many tools, but you should not learn them all.
**The agent-facing surface is: a small unified vocabulary + these skills.** Pick the
skill matching the intent, load it, follow it. Call `spedas_overview()` if unsure what
exists; treat the full tool list as discoverable on demand, not memorized.

## The unified vocabulary (what skills compose)
- **Plan:** `search_spedas_data_sources`, `plan_spedas_observation`, `compare_cdaweb_pds_spice`, `create_spedas_analysis_bundle`
- **Data (one set of verbs, switch by `source_type=cdaweb|pds|spice`):** `browse_data_sources`, `load_data_source`, `browse_data_parameters`, `fetch_data_product`, `manage_data_cache`
- **Geometry:** `get_ephemeris`, `compute_distance`, `transform_coordinates`
- **Analysis (`[analysis]` extra):** coordinate transforms, spectra, field models, particle moments, `render_tplot`

Low-level / source-specific compat tools exist for maintenance only — skills do not use them.

## Intent → skill → first step

| If the user wants… | Use skill | First call |
|---|---|---|
| Reproduce a published paper, figure, event, or DOI with artifact/provenance output | `paper-reproduction` | `spedas_overview` then `search_spedas_data_sources` / `plan_spedas_observation` |
| Parker Solar Probe / Solar Orbiter switchbacks, Alfvénic impulses, or radial-alignment in-situ comparisons | `psp-solar-wind-switchbacks` | `spedas_overview` then `search_spedas_data_sources` / `plan_spedas_observation`; load `spice-conjunction-finder` when geometry matters |
| Solar-wind storm, ICME, magnetic cloud, stream interaction, SEP reduced proxy, or multi-spacecraft in-situ overview (OMNI/Wind/ACE/STEREO/PSP/SolO) | `solar-wind-icme-storm` | `spedas_overview` then `search_spedas_data_sources` / `plan_spedas_observation`; compose scalar OMNI vectors, start STEREO multi-day runs at 1-minute cadence, and keep SEP onset/fluence claims gated on channel metadata |
| The turbulence/wave power spectrum of a field interval | `solar-wind-turbulence-spectrum` | `create_spedas_analysis_bundle` |
| Solar-wind intermittency, PVI, vector increments, thresholded event tables, or proxy-labelled energy-transfer / third-order-law workflow | `solar-wind-turbulence-intermittency` | `create_spedas_analysis_bundle` |
| Wave polarization (whistler/EMIC/chorus: degpol, wave-normal angle, ellipticity; THEMIS SCM `scf`/`scp`/`scw` valid-window checks) | `wave-polarization` | `create_spedas_analysis_bundle` |
| A boundary normal / LMN frame for a crossing | `boundary-minimum-variance` | `create_spedas_analysis_bundle` |
| Hodogram: vector component-vs-component for wave polarization / rotation sense (LMN) | `hodogram` | `create_spedas_analysis_bundle` |
| Apply a FAC/LMN/rotation matrix to a vector series | `apply-rotation-matrix` | (matrix from generate_fac_matrix / MVA) |
| Four-spacecraft curlometer J, linear B gradients/curvature, or magnetic nulls | `multi-spacecraft-gradients` | `create_spedas_analysis_bundle` |
| Cluster/Geotail/THEMIS magnetotail boundary, current-sheet, or multi-spacecraft proxy/scouting overview | `spedas-workflow` + `multi-spacecraft-gradients` | `search_spedas_data_sources`; use `docs/examples/cluster_geotail_themis_magnetotail_multispacecraft.md`, keep `single_spacecraft_cis` / `fgm_route_empty` and `not_paper_exact` labels, and require four-spacecraft FGM + positions before curlometer/timing claims |
| A full magnetopause/bow-shock crossing study (B + plasma + position) | `magnetopause-lmn-analysis` | `search_spedas_data_sources` |
| Times two spacecraft/bodies are close | `spice-conjunction-finder` | `spedas_overview` then `manage_data_cache(source_type="spice", action="status")` |
| Distance from a spacecraft to the magnetotail neutral sheet | `neutral-sheet-distance` | `create_spedas_analysis_bundle` |
| Model (Shue) LMN boundary-normal frame for a magnetopause crossing | `model-lmn-boundary` | `create_spedas_analysis_bundle` |
| Clean/condition a messy time-series before analysis (despike, deflag, smooth, gap-fill) | `timeseries-cleaning` | `create_spedas_analysis_bundle` |
| 2D velocity-space slice of a particle distribution (beams/crescents) | `particle-velocity-slice` | `create_spedas_analysis_bundle` |
| Just fetch & plot a time series | `spedas-workflow` | `plan_spedas_observation` |
| ERG/Arase radiation-belt, wave-particle, PWE/MGF/particle, or ground-conjugate ISEE/OMTI/MAGDAS route scout | `erg-arase-radiation-belt-waves` | `spedas_overview`; use this skill to choose `pyspedas.erg.*` / CDAWeb satellite routes, and keep ground routes labeled PySPEDAS-only |
| Standard mission overview plot, geomagnetic-index context, GOES XRS operational storm context, THEMIS FGM/ESA substorm/dipolarization proxy, or RBSP MagEIS/REPT radiation-belt overview | `overview-geomagnetic-indices` | `spedas_overview` |
| To know what data/sources exist at all | `spedas-workflow` | `spedas_overview` |

| Trace a spacecraft to its ionospheric footpoint / magnetic-equator (conjugacy, L-shell) | `field-line-footpoint` | `create_spedas_analysis_bundle` |
| Quick-look 1-D power spectral density (PSD slope/peak) of an interval | `power-spectral-density` | `create_spedas_analysis_bundle` |
| Field-aligned pitch-angle distribution (beam/pancake/loss-cone) of particles | `pitch-angle-distribution` | `create_spedas_analysis_bundle` |
| Coherence + cross-phase between two channels (wave-mode, compressibility, propagation) | `spectral-cross-coherence` | `create_spedas_analysis_bundle` |
| Multi-spacecraft timing: boundary normal + speed from >=4 s/c crossing times | `dual-spacecraft-timing` | `create_spedas_analysis_bundle` |
| Pick the right SPICE coordinate frame for a science goal + transform into it | `coordinate-frame-tour` | `create_spedas_analysis_bundle` |

## Load order
1. (this index) → 2. one focused skill → 3. that skill's tool chain. Don't pre-read every skill.

## For coding agents (maintenance)
- To navigate or change the spedas_agent_kit codebase, use the **`spedas-agent-kit-anatomy`** skill: descend the `ANATOMY.md` tree from the repo root, read cited `file:line` code, and update anatomy in the same commit as code.

## Universal rules (every skill obeys)
- **Artifact-first:** bundle the run, pass `output_dir` everywhere, return paths + compact stats, never pasted arrays.
- **Plan before fetch:** know source_type, dataset_id, parameters, time range, output_dir first.
- **New capability is a skill or a `source_type`, not a new tool.**
