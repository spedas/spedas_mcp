# Cluster / Geotail / THEMIS magnetotail multi-spacecraft workflow

This example is a Batch 008 paper-reproduction guardrail for magnetotail,
magnetopause, bow-shock, magnetosheath, and current-sheet papers.  It is a
researcher-facing first-pass workflow, not a new data source and not a
paper-quality curlometer recipe.  Use it when a DOI or event needs a narrow,
artifact-first overview before deciding whether a stronger multi-spacecraft
analysis is justified.

Use the supported Agent Kit route instead of hand-written loader scripts:

1. `spedas_overview()` to orient the available source types and skills.
2. `search_spedas_data_sources` with the mission/instrument names, DOI/event
   notes, and time window.
3. `plan_spedas_observation` with explicit mission, products, parameters, time
   range, and output directory.
4. `create_spedas_analysis_bundle` before fetching or plotting so figures,
   provenance, scripts, and hashes are tied to one run directory.
5. Plot only compact overview panels at first; record every alias, empty route,
   cadence choice, spacecraft, and coordinate frame in provenance.

## Batch 008 seed rows

| Iteration | Paper / DOI | Starting interval | First-pass route | Label |
|---|---|---|---|---|
| 036 | Hasegawa et al. 2004, rolled-up Kelvin-Helmholtz vortices, `10.1038/nature02799` | `2001-11-20/08:00:00`-`2001-11-20/09:00:00` | Cluster C1 CIS PP plasma proxy; Cluster FGM UP route returned no files in the daemon run | `proxy, single_spacecraft_cis, fgm_route_empty` |
| 037 | Retinò et al. 2007, turbulent reconnection, `10.1038/nphys574` | `2002-03-27/10:00:00`-`2002-03-27/11:00:00` | Cluster C1 CIS PP plasma proxy; FGM/STAFF/CIS aliases and exact sub-interval need verification | `proxy, single_spacecraft_cis, candidate_interval` |
| 038 | Nagai et al. 2013, Geotail reconnection-structure route scout, `10.1002/jgra.50247` | `2003-11-20/07:00:00`-`2003-11-20/08:00:00` | Geotail MGF K0 + LEP K0 route scout; window is not the paper's statistical-event set | `scouting, not_paper_exact, metadata_unresolved` |
| 039 | Angelopoulos et al. 2008 THEMIS substorm onset, `10.1126/science.1160495` | already in `solar_wind_event_presets.md` | THEMIS A/D/E FGM + `th?_state` for position checks | `proxy` |
| 040 | Runov et al. 2009 THEMIS dipolarization front, `10.1029/2009GL038980` | already in `solar_wind_event_presets.md` | THEMIS-D FGM + ESA moments; add Bz-front / flow checks before interpretation | `proxy` |

Do not duplicate the 039/040 rows in the preset table: Batch 005 already seeded
those intervals.  Batch 008 adds only the three genuinely new rows 036-038.

## Cluster first pass: honest single-spacecraft fallback

For Hasegawa 2004 or Retinò 2007, start by searching for Cluster FGM, CIS,
PEACE, STAFF, and spacecraft-state products.  A four-spacecraft Cluster result
requires **four FGM vectors plus four positions** on a common cadence and frame.
If the FGM route is empty, as it was in the Batch 008 daemon run, keep the result
as a single-spacecraft CIS overview:

- label it `single_spacecraft_cis` and `fgm_route_empty`;
- plot density/velocity/temperature as context only;
- record the empty FGM query and the successful CIS files in provenance;
- do not claim Kelvin-Helmholtz morphology, turbulent reconnection, current
  density, LMN, FTEs, shock normals, or curlometer outputs.

The CSA-vs-SPDF archival route is a discovery caveat.  It is not evidence for a
new Agent Kit source type until a future batch verifies the exact route and a
paper-quality interval.

## Geotail route scout: metadata warnings are signal

For Geotail current-sheet or reconnection-structure papers, use the MGF and LEP
routes as a route scout first.  The Batch 008 Geotail seed is deliberately
`not_paper_exact`: it checks that MGF K0 and LEP K0 variables such as
`IB_vector`, `N0`, `V0`, and `POSITION` can be found and plotted, while keeping
Nagai 2013 claims out of scope.

If LEP CDF metadata warnings appear, surface them in the report and provenance
instead of hiding them in stderr or inventing a metadata repair tool.  A later
paper-quality Geotail workflow needs the actual event list, coordinate-frame
choices, and plasma/field diagnostics before it can leave `scouting` status.

## THEMIS multi-probe boundary/current-sheet template

For THEMIS substorm or dipolarization-front papers, load the field and state data
together:

- FGM for the relevant probes (for example THEMIS A/D/E for timing context);
- `th?_state` so position availability is checked before timing or gradient
  language;
- ESA moments only after verifying the exact moment aliases in the window;
- event markers such as onset time, Bz-front time, and flow-burst windows.

A THEMIS overview can annotate Bz-fronts and flow bursts, but a
four-spacecraft timing or gradient result still needs explicit crossing times,
positions, cadence alignment, and uncertainty.  If those prerequisites are not
present, keep the result as `proxy`.

## Hard scope boundary

Single-spacecraft FGM/CIS/MGF/LEP/ESA overview plots are useful researcher
scouts.  They are not paper-quality four-spacecraft science.  Do **not** promote
any Batch 008 seed to curlometer current density, linear gradients, timing
normals, KH-vortex identification, reconnection rate, FTE detection, shock
normal, or LMN interpretation unless four-spacecraft magnetic fields, positions,
coordinate frames, cadence alignment, quality checks, and the paper's interval
are all present in the bundle and provenance.
