# Solar-wind event preset seeds

These are documentation-only preset seeds for Agent Kit skills. They are not yet
API-level event presets: use them to plan narrow, artifact-first paper
reproductions, then record exact paper/supplement intervals in provenance.

| Event / paper family | DOI | Starting interval | Data route | Quality label until paper interval confirmed | Skill |
|---|---|---|---|---|---|
| PSP Encounter-1 structured slow wind (Bale et al. 2019) | `10.1038/s41586-019-1818-7` | `2018-11-05/00:00:00`–`2018-11-07/00:00:00` | PSP FIELDS MAG RTN 1-min + SWEAP/SPC L3i | `candidate_interval` | `psp-solar-wind-switchbacks` |
| PSP Encounter-1 Alfvénic velocity spikes (Kasper et al. 2019) | `10.1038/s41586-019-1813-z` | `2018-11-06/00:00:00`–`2018-11-06/12:00:00` | PSP FIELDS MAG RTN + SWEAP/SPC velocity moments | `proxy` | `psp-solar-wind-switchbacks` |
| PSP Encounter-1 switchbacks (Dudok de Wit et al. 2020) | `10.3847/1538-4365/ab5853` | `2018-11-05/00:00:00`–`2018-11-07/00:00:00` | PSP FIELDS MAG RTN, optional SWEAP/SPC context | `proxy` | `psp-solar-wind-switchbacks` |
| PSP Encounter-1 sharp Alfvénic impulses (Horbury et al. 2020) | `10.3847/1538-4365/ab5b15` | `2018-11-06/00:00:00`–`2018-11-06/06:00:00` for cache-friendly smoke; replace with paper figure interval when known | PSP FIELDS MAG RTN + SWEAP/SPC velocity moments | `representative_proxy` | `psp-solar-wind-switchbacks` |
| PSP Encounter-1 PVI/intermittent structures (Chhiber et al. 2020) | `10.3847/1538-4365/ab53d2` | `2018-11-06/00:00:00`–`2018-11-06/03:00:00` smoke interval | PSP FIELDS MAG RTN, optional SWEAP/SPC context | `cached_smoke` until lag/cadence/threshold match the paper | `psp-solar-wind-switchbacks` + `solar-wind-turbulence-spectrum` |
| PSP inner-heliosphere turbulence evolution (2020) | `10.3847/1538-4365/ab60a3` | `2018-11-05/12:00:00`–`2018-11-05/18:00:00` smoke interval; use paper-selected E1/E2 intervals for science | PSP FIELDS MAG RTN + SWEAP/SPC | `representative_proxy` | `solar-wind-turbulence-spectrum` |
| PSP enhanced energy-transfer/cascade-rate paper (2020) | `10.3847/1538-4365/ab5dae` | `2018-11-06/00:00:00`–`2018-11-06/06:00:00` smoke interval | PSP FIELDS MAG RTN + SWEAP/SPC proton moments | `proxy` unless third-order-law assumptions and lag range are reproduced | `solar-wind-turbulence-spectrum` |
| PSP magnetic field line switchbacks near the Sun (2020) | `10.3847/1538-4365/ab4da7` | `2018-11-05/00:00:00`–`2018-11-05/06:00:00` smoke interval | PSP FIELDS MAG RTN + SWEAP/SPC | `representative_proxy` | `psp-solar-wind-switchbacks` |
| Halloween 2003 extreme-speed solar wind (Skoug et al. 2004) | `10.1029/2004JA010494` | `2003-10-29/00:00:00`–`2003-10-31/00:00:00` | OMNI HRO 1-min + Wind/ACE context | `paper_quality` only if timing/source choices match target figure | `solar-wind-icme-storm` |
| July 2012 STEREO-A extreme ICME (Liu et al. 2014) | `10.1038/ncomms4481` | `2012-07-23/00:00:00`–`2012-07-25/00:00:00` | STEREO-A MAG + PLASTIC 1-min | `candidate_interval` | `solar-wind-icme-storm` |
| THEMIS substorm onset proxy (Angelopoulos et al. 2008) | `10.1126/science.1160495` | `2008-02-26/04:45:00`–`2008-02-26/05:15:00` | THEMIS-A FGM L2 + ESA moments | `proxy` until multi-probe timing and ground/auroral context are reproduced | `overview-geomagnetic-indices` |
| THEMIS dipolarization-front proxy (Runov et al. 2009) | `10.1029/2009GL038980` | `2008-02-27/07:10:00`–`2008-02-27/07:25:00` | THEMIS-D FGM L2 + ESA moments | `proxy` until paper front markers/speed and multi-probe context are reproduced | `overview-geomagnetic-indices` |
| THEMIS whistler wave-context proxy (Cattell et al. 2008) | `10.1029/2007GL032009` | `2007-03-23/12:00:00`–`2007-03-23/12:10:00` | THEMIS-C SCM + EFI + FGM; choose non-empty SCM cadence family (`scf`/`scp`/`scw`) | `proxy` until waveform amplitude/polarization definitions match the paper | `wave-polarization` |
| RBSP third-radiation-belt smoke (Baker et al. 2013) | `10.1126/science.1233518` | `2013-03-01/00:00:00`–`2013-03-01/06:00:00` | RBSP-A ECT MagEIS + REPT with suffix-namespaced `FEDU`/`L` variables | `proxy` until multi-day L*/PSD/flux-map diagnostics are reproduced | `overview-geomagnetic-indices` |
| RBSP local-acceleration smoke (Reeves et al. 2013) | `10.1126/science.1237743` | `2012-10-09/00:00:00`–`2012-10-09/06:00:00` | RBSP-A ECT MagEIS + REPT; EMFISIS/HOPE optional fallback context | `proxy` until L*/PSD, energy-channel, and acceleration diagnostics are reproduced | `overview-geomagnetic-indices` |
| MMS asymmetric magnetopause electron-current/heating proxy (Graham et al. 2016) | `10.1002/2016GL068613` | `2015-10-16/13:06:30`–`2015-10-16/13:07:30` | MMS1 burst FGM + FPI DES/DIS moments + EDP; run MVA/LMN before interpreting current-sheet signatures | `proxy, candidate_interval` until paper LMN/curlometer definitions are reproduced | `spedas-workflow` + `magnetopause-lmn-analysis` |
| MMS asymmetric reconnection electron-jet proxy (Khotyaintsev et al. 2016) | `10.1002/2016GL069064` | `2015-10-16/13:06:45`–`2015-10-16/13:07:15` | MMS1 burst FGM + FPI DES/DIS velocity moments + EDP | `proxy, candidate_interval` until LMN jet component and paper subinterval are verified | `spedas-workflow` + `magnetopause-lmn-analysis` |
| MMS electron scattering/bouncing near diffusion region proxy (Lavraud et al. 2016) | `10.1002/2016GL068359` | `2015-10-16/13:06:30`–`2015-10-16/13:07:30` | MMS1 burst FGM + FPI DES moments/distributions + EDP; use `*-DIST` for pitch-angle or distribution claims | `proxy, candidate_interval` until PAD/distribution method and paper interval are reproduced | `spedas-workflow` + `pitch-angle-distribution` |
| MMS electron-only reconnection availability scout (Phan et al. 2018) | `10.1038/nature26178` | `2015-12-27/00:00:00`–`2015-12-27/00:10:00` scouting window only | MMS FGM/FPI/EDP search route; exact supplement interval must be verified before data claims | `availability_failure` in Batch 006; do not claim reproduction from this seed alone | `spedas-workflow` |
| MMS symmetric magnetotail EDR diagnostics proxy (Torbert et al. 2018) | `10.1126/science.aat2998` | `2017-07-11/22:33:30`–`2017-07-11/22:34:30` | MMS1 burst FGM + FPI DES/DIS moments + EDP; future paper-quality work needs MMS1-4 curlometer/LMN | `proxy, candidate_interval` until four-spacecraft current and pressure-tensor diagnostics are reproduced | `spedas-workflow` + `magnetopause-lmn-analysis` |
| 2007 May STEREO ICME proxy (Liu et al.) | `10.5194/angeo-27-4491-2009` | `2007-05-19/00:00:00`–`2007-05-23/00:00:00` | STEREO-A/B MAG `1min` + PLASTIC proton moments; Wind/ACE/OMNI optional context | `proxy` until paper boundaries, coordinate basis, and spacecraft timing are reproduced | `solar-wind-icme-storm` + `spedas-workflow` |
| 2007 May STEREO/Wind magnetic-cloud shock-sheath proxy (Möstl et al.) | `10.1007/s11207-009-9360-7` | `2007-05-20/00:00:00`–`2007-05-24/00:00:00` | STEREO-A/B MAG + PLASTIC, Wind MFI/SWE or OMNI comparison | `proxy` until time-shifted boundaries and paper sheath/cloud markers are verified | `solar-wind-icme-storm` |
| Bastille Day Wind/ACE magnetic-cloud proxy (Lepping/Berdichevsky family) | `10.1029/2001GL014136` | `2000-07-14/00:00:00`–`2000-07-17/00:00:00` | Wind MFI/SWE + ACE MAG/SWEPAM + OMNI geomagnetic indices | `proxy` until shock/sheath/cloud boundaries and magnetic-cloud fit choices match the paper | `solar-wind-icme-storm` |
| 2010 Jan 17 SEP longitudinal-spread reduced proxy (Dresing et al.) | `10.1007/s11207-012-0049-y` | `2010-01-17/00:00:00`–`2010-01-19/00:00:00` | STEREO SEPT reduced-intensity profiles + STEREO MAG context; ACE/Wind only with verified particle-channel metadata | `reduced_sep_proxy` until telescope/species/energy band/onset/fluence definitions are reproduced | `solar-wind-icme-storm` + `spedas-workflow` |
| 2010 Aug CME-CME interaction in-situ proxy (Lugaz/Temmer family) | DOI unresolved in Batch 007 | `2010-08-01/00:00:00`–`2010-08-06/00:00:00` | STEREO MAG/PLASTIC + OMNI/Wind/ACE in-situ context; SECCHI/HI J-map not attempted | `proxy, metadata_unresolved` until exact paper DOI, HI/J-map products, and arrival-time model are verified | `solar-wind-icme-storm` |

## Rules for using these seeds

- Keep the `paper-reproduction` artifact/provenance contract: report, provenance
  JSON, plot/table artifacts, and the script or recipe used to regenerate them.
- Do not claim paper quality from a seed interval alone. Promote to
  `paper_quality` only after matching paper interval, source, coordinate basis,
  calibration choices, and diagnostic definitions.
- Record archive variable aliases exactly, for example OMNI `AE_INDEX` and
  `SYM_H`, PSP `psp_fld_l2_mag_RTN_1min`, PSP SPC `psp_spc_np_fit` /
  `psp_spc_vp_fit_RTN`, and STEREO `BFIELD` / PLASTIC proton moment names.
- For PSP turbulence/switchback seeds, record `interval_quality` (`paper_exact`,
  `representative_proxy`, or `cached_smoke`) plus cadence/lag/threshold choices
  in provenance before using the result as Agent Kit feedback.
- For THEMIS/RBSP Batch 005 seeds, treat the listed windows as partial/proxy data-route probes: record empty THEMIS ESA/SCM variables, RBSP suffix/namespacing choices, and optional EMFISIS/HOPE fallback warnings before using the result as Agent Kit feedback.
- For Batch 007 STEREO/Wind/ACE/SEP seeds, treat the listed windows as reduced/proxy route probes: record STEREO spacecraft/cadence/alias choices, SEP telescope/species/energy metadata, and HI/J-map scope boundaries before using the result as Agent Kit feedback.
