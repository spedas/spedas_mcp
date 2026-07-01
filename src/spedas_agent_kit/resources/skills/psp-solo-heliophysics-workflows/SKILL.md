---
name: psp-solo-heliophysics-workflows
description: Route-scout PSP / Solar Orbiter heliospheric in-situ workflows: FIELDS/SWEAP/Solo MAG/SWA/RPW/EPD load planning, switchback and radial-alignment comparisons, cadence/frame caveats, SPICE geometry handoff, and links to existing turbulence/ICME skills without expanding the default MCP tool surface.
---

# PSP / Solar Orbiter heliophysics workflows

Use this skill when the user asks for a Parker Solar Probe (PSP), Solar Orbiter
(SolO), or inner-heliosphere solar-wind workflow and the request is broader than
one narrow switchback reproduction. Typical prompts:

- "Plan PSP + Solar Orbiter radial-alignment analysis."
- "Which products should I load for PSP FIELDS/SWEAP and SolO MAG/SWA?"
- "Make a cache-friendly quicklook for a SolO switchback interval."
- "Compare PSP perihelion in-situ data with Solar Orbiter or Wind/ACE context."
- "Route a heliospheric workflow into Agent Kit resources without inventing tools."

This is a **route-scout and load-plan skill**, not a new MCP tool. The default
Agent Kit MCP surface stays compact: use `spedas_overview`,
`search_spedas_data_sources`, `plan_spedas_observation`, and
`create_spedas_analysis_bundle` first. External PySPEDAS loader names below are
runtime/library routes and must be labelled as such.

## First decision

| User intent | Use this skill? | Compose with |
|---|---:|---|
| PSP or SolO product/cadence/load-plan selection | Yes | `pyspedas-load-planning`, `tplot-data-lifecycle` |
| PSP/SolO radial alignment or conjunction context | Yes | `spice-conjunction-finder`, `coordinate-frame-tour` |
| PSP/SolO switchback / Alfvénic impulse reproduction | Yes for route scouting, then specialize | `psp-solar-wind-switchbacks` |
| PSP/SolO turbulence spectrum or PVI event table | Yes for products/cadence, then specialize | `solar-wind-turbulence-spectrum`, `solar-wind-turbulence-intermittency` |
| Stream interaction, ICME, storm, or wide heliosphere context | Usually yes as the inner-heliosphere branch | `solar-wind-icme-storm`, `omni-kyoto-noaa-smoke-workflows` |
| A pure archive-discovery question | Maybe | `spedas_overview`, `search_spedas_data_sources`, `browse_data_sources` |

## MCP-first workflow

1. Start with `spedas_overview` and confirm the compact default tool surface.
2. Call `search_spedas_data_sources` or `browse_data_sources(source_type="cdaweb")`
   for candidate CDAWeb datasets. Do not assume a dataset ID without checking.
3. Use `browse_data_parameters` on the selected dataset before choosing variable
   names. Record coordinate frame, cadence, units, and support variables.
4. For any real run, create an artifact/provenance workspace with
   `create_spedas_analysis_bundle`. Do **not** paste arrays, CDF records, or tplot
   dumps into chat. Write small plots/tables/manifests to files.
5. If geometry matters, load `spice-conjunction-finder` before source mapping or
   radial-alignment claims. Use `coordinate-frame-tour` before mixing RTN, VSO,
   HCI/HAE/ECLIPJ2000, spacecraft-centered frames, or transformed vectors.

## Core products and routes

### Parker Solar Probe (PSP)

| Need | CDAWeb / product cue | External PySPEDAS route (not an MCP tool) | Notes |
|---|---|---|---|
| Magnetic-field quicklook | `PSP_FLD_L2_MAG_RTN_1MIN` | `pyspedas.projects.psp.fields` | Good first-pass RTN overview; label as low-cadence/proxy. |
| Publication-quality MAG / turbulence | `PSP_FLD_L2_MAG_RTN`, `PSP_FLD_L2_MAG_RTN_4_SA_PER_CYC` | `pyspedas.projects.psp.fields` | Prefer full cadence for sharp impulses, PVI, inertial-range spectra, and switchback intermittency. |
| Proton moments / solar wind context | `PSP_SWP_SPC_L3I` | `pyspedas.projects.psp.spc` | Solar Probe Cup moments; align/interpolate onto MAG only for explicitly labelled overview products. |
| SWEAP/SPAN-ion distribution or moments | inspect SWEAP/SPAN-i products | `pyspedas.projects.psp.spi` | Use when SPC is insufficient; document product/cadence/support variables. |
| SWEAP/SPAN-electron context | inspect SWEAP/SPAN-e products | `pyspedas.projects.psp.spe` | Useful for electron/plasma context, not a replacement for proton-moment planning. |
| Radio/FIELDS spectral context | inspect RFS products such as `PSP_FLD_L2_RFS_LFR` / `PSP_FLD_L2_RFS_HFR` | `pyspedas.projects.psp.rfs` | Use for radio/plasma-wave context; route detailed wave analysis to specialized skills when needed. |
| Energetic-particle context | inspect IS☉IS products | `pyspedas.projects.psp.epihi`, `pyspedas.projects.psp.epilo`, `pyspedas.projects.psp.epi` | Use for SEP context, onset checks, or safety notes; do not infer anisotropy without channel metadata. |

Typical first PSP smoke interval: one to six hours around a known encounter or
perihelion sub-window. For PSP E1, examples often start near
`2018-11-06/00:00:00` and must be confirmed against the paper figure interval
before claiming reproduction.

### Solar Orbiter (SolO)

| Need | CDAWeb / product cue | External PySPEDAS route (not an MCP tool) | Notes |
|---|---|---|---|
| MAG quicklook in RTN | `SOLO_L2_MAG-RTN-NORMAL-1-MINUTE` or `SOLO_L2_MAG-RTN-NORMAL` | `pyspedas.projects.solo.mag(datatype="rtn-normal")` | PySPEDAS examples load tplot variable `B_RTN`; record normal/burst/LL mode and cadence. |
| MAG high-cadence or burst context | `SOLO_L2_MAG-RTN-BURST`, merged MAG/RPW/SCM products | `pyspedas.projects.solo.mag` | Only use burst/merged products when the interval and science case justify the volume. |
| Solar-wind plasma moments | SWA/PAS or HIS products; start by browsing parameters | `pyspedas.projects.solo.swa` | Availability/cadence differs by product; write an explicit fallback if no SWA product is available. |
| Radio/plasma-wave context | RPW products such as TNR/SBM routes | `pyspedas.projects.solo.rpw` | For wave context; keep detailed spectral products artifact-first. |
| Energetic particles / SEP context | EPD EPT/HET/SIS/STEP products | `pyspedas.projects.solo.epd` | Treat direction, sector, and channel metadata as mandatory for anisotropy/fluence claims. |

For first SolO MAG smoke tests, PySPEDAS examples use:

```python
pyspedas.projects.solo.mag(trange=["2020-06-01", "2020-06-02"], datatype="rtn-normal")
# expected tplot variable family includes B_RTN
```

## External runtime route markers

When you mention PySPEDAS mission functions, include this marker so naive MCP
clients do not try to call them as tools:

```yaml
external_runtime_route:
  not_an_mcp_tool: true
  examples:
    - pyspedas.projects.psp.fields
    - pyspedas.projects.psp.spc
    - pyspedas.projects.psp.spi
    - pyspedas.projects.psp.spe
    - pyspedas.projects.psp.rfs
    - pyspedas.projects.psp.epihi
    - pyspedas.projects.psp.epilo
    - pyspedas.projects.psp.epi
    - pyspedas.projects.solo.mag
    - pyspedas.projects.solo.swa
    - pyspedas.projects.solo.rpw
    - pyspedas.projects.solo.epd
```

`external_runtime_route.not_an_mcp_tool: true` is part of the contract. The
Agent Kit MCP may discover/fetch CDAWeb/PDS/SPICE products through its own
unified tools, but `pyspedas.projects.psp.fields`, `pyspedas.projects.psp.spc`,
`pyspedas.projects.solo.mag`, and friends are Python-library routes unless a
future Agent Kit release exposes a dedicated tool. Some PySPEDAS examples import
top-level aliases such as `pyspedas.psp.fields`, `pyspedas.psp.spc`, or
`pyspedas.solo.mag`; those are still external runtime routes, not MCP tools.

## Reusable workflow skeletons

### A. PSP MAG + SPC quicklook

1. Create a bundle with `create_spedas_analysis_bundle` and record the science
   question, interval, and whether the target is smoke/proxy or paper-exact.
2. Discover `PSP_FLD_L2_MAG_RTN_1MIN` for overview; escalate to
   `PSP_FLD_L2_MAG_RTN` or `PSP_FLD_L2_MAG_RTN_4_SA_PER_CYC` for switchback,
   sharp-impulse, intermittency, or spectrum claims.
3. Discover/browse `PSP_SWP_SPC_L3I` or related SWEAP products for proton speed,
   density, and thermal speed. Record the cadence mismatch.
4. If using PySPEDAS directly, the external routes are
   `pyspedas.projects.psp.fields` and `pyspedas.projects.psp.spc`; common load
   flags include `downloadonly=True`, `notplot=True`, `no_update=True`, and
   `time_clip=True`. Verify the exact function signature in the installed
   PySPEDAS version.
5. Derive only small artifact tables/plots: `Br/Bt/Bn`, `|B|`, proton speed,
   density, and a clearly labelled magnetic-deflection proxy. Do not paste
   arrays.

### B. Solar Orbiter MAG + optional SWA quicklook

1. Browse SolO MAG datasets and choose RTN vs VSO vs SRF deliberately. For RTN
   normal-mode MAG, start with `SOLO_L2_MAG-RTN-NORMAL-1-MINUTE` or
   `SOLO_L2_MAG-RTN-NORMAL`.
2. If using PySPEDAS directly, route via
   `pyspedas.projects.solo.mag(datatype="rtn-normal")`; expect tplot variable
   `B_RTN` in the common quicklook path.
3. Browse SWA/PAS/HIS products and use `pyspedas.projects.solo.swa` only as an
   external runtime route. If plasma moments are unavailable for the requested
   interval, keep the product MAG-only and mark the missing-plasma caveat.
4. For SolO switchback claims, use `psp-solar-wind-switchbacks` after the route
   scout; for spectra/PVI, use the turbulence skills.

### C. PSP + Solar Orbiter radial alignment

1. Start with in-situ products first: PSP FIELDS/SWEAP and SolO MAG/SWA, with
   intervals no wider than needed for the comparison.
2. Use `spice-conjunction-finder` for geometry: radial separation, angular
   separation, and closest-approach windows. Do not call a radial alignment
   "source mapped" unless a model and assumptions are stated.
3. Use `coordinate-frame-tour` to document frames before comparing vectors.
   RTN components at two spacecraft are not automatically interchangeable.
4. If OMNI/Wind/ACE/STEREO context is needed, route broad context through
   `solar-wind-icme-storm` or `omni-kyoto-noaa-smoke-workflows` rather than
   bloating this workflow.
5. Deliver an artifact manifest with product IDs, variable names, cadence,
   interpolation method, frame assumptions, geometry settings, and caveats.

## Quality gates and caveats

- **Fetch narrowly first.** Start with hour-scale to day-scale smoke windows,
  not whole encounters or week-long high-cadence intervals.
- **Proxy labels matter.** `PSP_FLD_L2_MAG_RTN_1MIN` is good for overview plots,
  but not for publication-quality sharp-impulse or inertial-range claims.
- **Frame labels matter.** Record RTN/VSO/SRF/spacecraft frame and whether any
  transform was applied. Use SPICE context before radial-alignment claims.
- **Cadence mismatch is not a detail.** Record how SWEAP/SPC/SWA data were
  aligned to MAG cadence; never hide interpolation.
- **No raw arrays in chat.** Do not paste arrays. Write artifacts, plots, CSV/JSON summaries, and
  manifests. Keep chat conclusion-first and path-labelled.
- **No invented tools.** Names like `pyspedas.projects.psp.fields` and
  `pyspedas.projects.solo.mag` are external Python routes; label them with
  `external_runtime_route.not_an_mcp_tool: true` and keep Agent Kit tool calls
  on the unified MCP vocabulary.

## Minimal deliverables

For a PSP/SolO route scout, return:

1. Science question and interval.
2. Product plan: datasets, variables, cadence, and archive route.
3. Tool plan: Agent Kit calls first; PySPEDAS external routes only when needed.
4. Geometry/frame plan if comparing spacecraft.
5. Artifact paths: bundle directory, manifest, plots/tables, and validation log.
6. Caveats: smoke/proxy vs paper-exact, cadence/frame/interpolation limits, and
   any missing plasma/particle product fallback.
