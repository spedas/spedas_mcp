# Solar-wind event preset seeds

These are documentation-only preset seeds for Agent Kit skills. They are not yet
API-level event presets: use them to plan narrow, artifact-first paper
reproductions, then record exact paper/supplement intervals in provenance.

| Event / paper family | DOI | Starting interval | Data route | Quality label until paper interval confirmed | Skill |
|---|---|---|---|---|---|
| PSP Encounter-1 structured slow wind (Bale et al. 2019) | `10.1038/s41586-019-1818-7` | `2018-11-05/00:00:00`–`2018-11-07/00:00:00` | PSP FIELDS MAG RTN 1-min + SWEAP/SPC L3i | `candidate_interval` | `psp-solar-wind-switchbacks` |
| PSP Encounter-1 Alfvénic velocity spikes (Kasper et al. 2019) | `10.1038/s41586-019-1813-z` | `2018-11-06/00:00:00`–`2018-11-06/12:00:00` | PSP FIELDS MAG RTN + SWEAP/SPC velocity moments | `proxy` | `psp-solar-wind-switchbacks` |
| PSP Encounter-1 switchbacks (Dudok de Wit et al. 2020) | `10.3847/1538-4365/ab5853` | `2018-11-05/00:00:00`–`2018-11-07/00:00:00` | PSP FIELDS MAG RTN, optional SWEAP/SPC context | `proxy` | `psp-solar-wind-switchbacks` |
| Halloween 2003 extreme-speed solar wind (Skoug et al. 2004) | `10.1029/2004JA010494` | `2003-10-29/00:00:00`–`2003-10-31/00:00:00` | OMNI HRO 1-min + Wind/ACE context | `paper_quality` only if timing/source choices match target figure | `solar-wind-icme-storm` |
| July 2012 STEREO-A extreme ICME (Liu et al. 2014) | `10.1038/ncomms4481` | `2012-07-23/00:00:00`–`2012-07-25/00:00:00` | STEREO-A MAG + PLASTIC 1-min | `candidate_interval` | `solar-wind-icme-storm` |

## Rules for using these seeds

- Keep the `paper-reproduction` artifact/provenance contract: report, provenance
  JSON, plot/table artifacts, and the script or recipe used to regenerate them.
- Do not claim paper quality from a seed interval alone. Promote to
  `paper_quality` only after matching paper interval, source, coordinate basis,
  calibration choices, and diagnostic definitions.
- Record archive variable aliases exactly, for example OMNI `AE_INDEX` and
  `SYM_H`, PSP `psp_fld_l2_mag_RTN_1min`, and STEREO `BFIELD` / PLASTIC proton
  moment names.
