---
name: psp-solar-wind-switchbacks
description: Reproduce Parker Solar Probe Encounter-1 solar-wind and switchback papers with FIELDS/SWEAP planning, cadence alignment, deflection-angle proxies, Alfvénic velocity-spike caveats, and artifact/provenance output.
---

# PSP solar wind and switchback workflow

Use this skill for Parker Solar Probe (PSP) near-Sun solar-wind papers or event
requests involving Encounter 1, switchbacks, structured slow wind, Alfvénic
velocity spikes, or magnetic-field rotations. It turns a paper/event prompt into
a narrow FIELDS + SWEAP data plan, an artifact bundle, and explicit proxy labels.

## Good first targets

| Paper/event family | Typical starting interval | Products | First diagnostic |
|---|---|---|---|
| Bale et al. 2019 structured slow wind, DOI `10.1038/s41586-019-1818-7` | PSP E1, e.g. `2018-11-05/00:00:00`–`2018-11-07/00:00:00` until the paper figure interval is confirmed | FIELDS MAG RTN 1-min + SWEAP/SPC L3i | `Br/Bt/Bn`, `|B|`, proton speed/density/thermal speed, magnetic deflection angle |
| Kasper et al. 2019 Alfvénic velocity spikes, DOI `10.1038/s41586-019-1813-z` | PSP E1 windows around perihelion, e.g. `2018-11-06/00:00:00`–`12:00:00` | FIELDS MAG RTN + SWEAP/SPC velocity moments | B/V component rotations, speed spikes, candidate Alfvénic correlation |
| Dudok de Wit et al. 2020 switchbacks, DOI `10.3847/1538-4365/ab5853` | PSP E1 multi-hour to multi-day windows | FIELDS MAG RTN, optional SPC context | deflection-angle histogram, threshold sensitivity, candidate switchback fraction |
| Horbury et al. 2020 sharp Alfvénic impulses, DOI `10.3847/1538-4365/ab5b15` | PSP E1 paper interval or smoke window such as `2018-11-06/00:00:00`–`06:00:00` | FIELDS MAG RTN + SWEAP/SPC | matched-cadence B/V rotations, deflection angle, candidate velocity-jump/Alfvénicity proxy |
| Chhiber et al. 2020 PVI/intermittent structures, DOI `10.3847/1538-4365/ab53d2` | PSP E1 short windows around perihelion, e.g. `2018-11-06/00:00:00`–`03:00:00` for cache-friendly smoke | FIELDS MAG RTN, optional SWEAP/SPC context | PVI by explicit lag, thresholded intermittent-structure candidates, event table |
| PSP E1 turbulence / cascade papers, DOIs `10.3847/1538-4365/ab60a3` and `10.3847/1538-4365/ab5dae` | PSP E1 statistically quiet sub-intervals; keep smoke windows narrow until paper windows are confirmed | FIELDS MAG RTN + SWEAP/SPC, preferably high cadence for real analysis | PSD/PVI/increment breadcrumbs first; escalate to `solar-wind-turbulence-spectrum` or a documented cascade workflow |
| Solar Orbiter first results: magnetic switchbacks, DOI `10.1051/0004-6361/202140972` | June 2020 SolO MAG smoke intervals; verify exact figure intervals before science claims | Solar Orbiter MAG `rtn-normal` (`B_RTN`), optional SWA/PAS when available | MAG-only switchback/deflection panels with explicit SWA fallback caveat |
| PSP/Solar Orbiter radial-alignment switchback or stream-interaction papers, DOI `10.1051/0004-6361/202140570` | 2020-09-24–2020-10-02 reduced in-situ window | PSP FIELDS/SWEAP + SolO MAG + optional OMNI | in-situ-first comparison; use `spice-conjunction-finder` for geometry/context before source mapping |
| Solar-source switchback studies, DOI `10.1007/s11207-022-02022-4` | 2020-09-27 PSP/SolO smoke intervals before remote-sensing attribution | PSP/SolO in-situ first, remote-sensing only with explicit caveats | separate switchback detection from solar-source attribution and magnetic mapping |
| Magnetic field line switchbacks near the Sun, DOI `10.3847/1538-4365/ab4da7` | PSP E1 perihelion windows such as `2018-11-05/00:00:00`–`06:00:00` for smoke | FIELDS MAG RTN + SWEAP/SPC | field-line polarity/deflection proxy, speed overlay, threshold-sensitivity follow-up |

Treat these intervals as **candidate intervals** unless the user supplies an exact
paper figure time or you have checked the paper/supplement.

## Workflow

1. **Start from paper reproduction discipline.** If the request names a DOI,
   figure, or paper, load `paper-reproduction` first. Use this skill for the PSP
   data route and first diagnostics; keep the paper artifact bundle/provenance
   contract from `paper-reproduction`.
2. **Plan before fetching.** Record `source_type`, products, variables, interval,
   coordinate basis, and output/cache directories. First calls usually start with
   `spedas_overview`, then `search_spedas_data_sources` / `plan_spedas_observation`;
   if current Agent Kit coverage is insufficient, a direct PySPEDAS fallback is
   acceptable only when the report says why.
3. **Fetch narrowly.** Prefer FIELDS MAG RTN 1-minute for first-pass overview and
   SWEAP/SPC L3i proton moments for velocity/density context. Keep downloads in a
   per-run cache/output directory.
4. **Align cadences explicitly.** Interpolate slower/lower-cadence plasma moments
   onto the MAG cadence only for overview/proxy plots. Record interpolation method,
   source variable names, sample counts, and any fill-value handling in
   `provenance.json`.
5. **Compute first-pass proxies.** Useful non-paper-quality diagnostics include:
   - magnetic deflection angle, e.g. `acos(Br / |B|)` in RTN;
   - thresholded switchback fraction (state threshold, e.g. `>45°`);
   - B/V component rotation overlays;
   - candidate speed-spike or density/thermal-speed context.
6. **Validate artifacts.** Ensure axes include units, panels are populated, and the
   report labels the result as `candidate_interval` or `proxy` unless the exact
   paper method/interval has been matched.

## Batch-003 follow-up diagnostics

The paper-reproduction campaign's PSP batch 003 (Horbury/Chhiber/turbulence/
energy-transfer/field-line-switchback papers) showed a repeated gap: agents can
fetch PSP E1 MAG+SPC, but they must hand-code the same derived breadcrumbs. Until
Agent Kit grows dedicated, validated operations, keep the workflow explicit:

- **PVI/intermittency:** state the vector product, cadence, lag, normalization
  window, threshold, and whether event durations were merged. Export a compact
  event table (`start`, `stop`, `peak_pvi`, `lag`, `threshold`) before claiming an
  intermittent-structure catalog.
- **Sharp impulses / switchbacks:** record the deflection-angle definition,
  threshold sweep, B/V interpolation method, and candidate duration. Keep
  `proxy` labels unless the paper's event list or figure interval is matched.
- **Turbulence / cascade papers:** use `solar-wind-turbulence-intermittency` for PVI/event tables,
  `solar-wind-turbulence-spectrum` or `power-spectral-density` for spectra, but label single-window PSD/increment
  plots as pedagogical breadcrumbs. A third-order-law or cascade-rate result
  needs explicit units, Taylor-hypothesis assumptions, plasma moments, lag range,
  and uncertainty/fit bounds.
- **Provenance:** add `interval_quality` (`paper_exact`, `representative_proxy`,
  or `cached_smoke`), `cadence_choice`, `fill_value_warnings`, and
  `derived_normalization` so a reviewer can tell what is science-ready and what
  is only a workflow smoke test.

## Batch-004 Solar Orbiter and radial-alignment notes

Batch 004 showed that PSP/SolO switchback papers are best handled as an
**in-situ-first** extension of this skill, not a new skill:

- **Solar Orbiter MAG route:** first try MAG `rtn-normal`; the tplot variable seen
  in the smoke reproduction was `B_RTN`. Record product/cadence and coordinate
  basis before comparing with PSP RTN panels.
- **SWA/PAS fallback:** `solo.swa` / `pas-grnd-mom` may return no matching CDAWeb
  files for some June 2020 switchback windows. If plasma moments are absent,
  produce a MAG-only artifact and label velocity/plasma comparisons as
  unavailable rather than silently dropping panels.
- **Radial alignment:** for PSP+SolO stream-interaction or switchback alignment
  papers, load `spice-conjunction-finder` for geometry/conjunction context, then
  keep the first pass to a reduced in-situ panel (PSP MAG/SWEAP, SolO MAG, OMNI
  context if relevant). Do not claim mapped solar-source timing until propagation,
  connectivity, and remote-sensing assumptions are explicit.
- **Source attribution:** papers such as `10.1007/s11207-022-02022-4` need two
  layers in provenance: (1) in-situ switchback/event detection, and (2) mapping /
  remote-sensing interpretation. The first can be reproduced with this skill; the
  second is a caveated context product unless the paper method is matched.

## Caveats to state in the report

- Deflection angle from RTN MAG is a **proxy**, not a full paper switchback
  catalog. Duration merging, field polarity context, threshold sensitivity, and
  data-quality flags matter.
- Alfvénic spike reproduction needs more than B/V overlays: lag/correlation,
  Alfvén-speed normalization, de Hoffmann-Teller frame assumptions, and coordinate
  consistency should be documented before claiming paper quality.
- PSP SWEAP/SPC variables can include fill values or unavailable alpha moments;
  record selected variables and missing products.
- FIELDS and SWEAP cadences differ. Any interpolation must be documented and kept
  out of raw-data claims.

## Minimal provenance additions

In addition to the `paper-reproduction` schema, include:

```json
{
  "psp_context": {
    "encounter": "E1",
    "mag_variable": "psp_fld_l2_mag_RTN_1min",
    "plasma_variables": ["psp_spc_np_fit", "psp_spc_vp_fit_RTN", "psp_spc_wp_fit"],
    "coordinate_basis": "RTN",
    "cadence_alignment": "plasma moments interpolated to MAG timestamps for overview only",
    "deflection_proxy": {
      "formula": "degrees(acos(Br / |B|))",
      "threshold_deg": 45,
      "quality": "proxy"
    }
  }
}
```

## Agent Kit feedback pattern

If you had to hand-code this workflow, use feedback like:

> Agent Kit feedback: PSP Encounter-1 switchback workflows need named event/paper
> presets plus a FIELDS+SWEAP overview recipe. Evidence: reproducing
> Bale/Kasper/Dudok de Wit required manual product selection, cadence alignment,
> deflection-angle proxy code, and quality labels. Desired behavior: Agent Kit
> should generate the artifact bundle and provenance scaffold while clearly
> marking candidate intervals and proxy diagnostics.
