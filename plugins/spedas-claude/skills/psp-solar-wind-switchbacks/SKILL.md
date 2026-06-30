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
| Horbury/Chhiber PSP E1 switchback/turbulence papers | PSP E1 paper interval or candidate interval | FIELDS MAG, SWEAP, optional derived turbulence skill | switchback markers plus PSD/PVI follow-up |

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
