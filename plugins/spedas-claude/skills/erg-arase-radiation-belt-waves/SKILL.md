---
name: erg-arase-radiation-belt-waves
description: >
  ERG/Arase radiation-belt, wave-particle, PWE/MGF/particle, and ground-conjugate
  route-scout workflows. Use when a researcher asks for Arase/ERG chorus, EMIC,
  PWE/HFA/OFA, MEP-e/HEP/XEP/LEP particle flux, orbit/attitude, ISEE/MAGDAS/STEL
  magnetometer, OMTI all-sky imager, VLF, or pulsating-aurora context. This skill
  is a conservative route map and overclaim guardrail; it points to existing
  analysis skills for polarization, pitch-angle, velocity-slice, PSD, and coherence.
---

# ERG/Arase radiation-belt, wave-particle, and ground-conjugate workflows

Use this skill when the science request mentions **ERG**, **Arase**, PWE/OFA/HFA,
MGF, MEP-e/HEP/XEP/LEP, chorus/EMIC/hiss/whistler waves, radiation-belt electron
flux, pulsating aurora, ISEE/MAGDAS/STEL ground magnetometers, OMTI all-sky
imagers, VLF, or ground-conjugate context.

This is a route-scout skill, not a new analysis implementation. It tells an agent
where the data usually lives, what the first artifact should be, and where the
paper-quality boundary is. Keep all outputs artifact-first: write run metadata,
provenance, variable lists, plots, and any diagnostics to the output directory;
return only compact paths and caveats.

## Route map

| Research intent | Route to try | Products / variable families | First artifact |
|---|---|---|---|
| Arase magnetic field context | `pyspedas.erg.mgf(...)` or CDAWeb `ERG_MGF_L2_8SEC` | `erg_mgf_l2_mag_8sec_*` (often GSM/GSE components) | B-field overview plus coordinate/frame note |
| PWE/OFA wave spectra (chorus/EMIC/hiss/whistler context) | `pyspedas.erg.pwe_ofa(...)` or CDAWeb `ERG_PWE_OFA_L2_SPEC` | `erg_pwe_ofa_l2_spec_E_spectra_*`, `erg_pwe_ofa_l2_spec_B_spectra_*` | E/B spectrogram quick-look; then load `wave-polarization` for real mode work |
| PWE/HFA upper-hybrid or electron-density route scout | `pyspedas.erg.pwe_hfa(...)` or CDAWeb `ERG_PWE_HFA_L2_SPEC_HIGH/LOW/MONIT` | HFA high/low/monitor spectra, frequency axes, support variables | HFA spectrogram + frequency-axis metadata; do not claim derived density yet |
| Electric-field / waveform context | `pyspedas.erg.pwe_efd(...)`, `pwe_wfc(...)` | EFD potential/electric field, waveform products when available | variable inventory and narrow-window plot |
| Electron flux / radiation-belt browse | `pyspedas.erg.mepe(...)`, `hep(...)`, `xep(...)`, `lepe(...)`; CDAWeb `ERG_MEPE_L2_OMNIFLUX`, `ERG_HEP_L2_OMNIFLUX`, `ERG_XEP_L2_OMNIFLUX`, `ERG_LEPE_L2_OMNIFLUX` | `erg_*_l2_omniflux_*`, 3D flux products where available | energy-channel/units table plus flux overview; do not infer PSD or loss cone |
| Ion flux / ring-current context | `pyspedas.erg.mepi_nml(...)`, `mepi_tof(...)`, `lepi(...)`; CDAWeb `ERG_MEPI_L2_OMNIFLUX`, `ERG_MEPI_L2_3DFLUX`, `ERG_LEPI_L2_OMNIFLUX` | ion omniflux/3D flux products | energy/species table plus flux overview |
| Orbit / attitude / conjunction context | `pyspedas.erg.orb(...)`, `att(...)`; CDAWeb `ERG_ORB_L2` | `erg_orb_l2_pos_gsm`, attitude/support variables | orbit plot + frame/provenance record; load `field-line-footpoint` for mapping |
| Ground magnetometer context | `pyspedas.erg.gmag_isee_fluxgate(...)`, `gmag_isee_induction(...)`, `gmag_magdas_1sec(...)`, `gmag_mm210(...)`, `gmag_stel_fluxgate(...)`, `gmag_stel_induction(...)` | site/cadence-selected ground variables | station/cadence availability diagnostics + ground trace plot |
| Ground optical context | `pyspedas.erg.camera_omti_asi(...)` | `omti_asi_<site>_<wavelength>_image_raw` (for example `ath_5577`) | image-shape preview, station/filter metadata, compact sample frame |
| VLF / SuperDARN / other ground context | `pyspedas.erg.isee_vlf(...)`, `sd_fit(...)` | site-selected VLF/radar products | route diagnostic + provenance; avoid mapping claims without geometry |

## PySPEDAS-only caveat

Agent Kit's CDAWeb `erg.json` is a **satellite-data catalog**. It lists ERG/Arase
satellite datasets such as MGF, PWE, MEP-e/HEP/XEP/LEP, MEP-i/LEP-i, and orbit.
The ground-conjugate routes exercised by Batch 010 are different: ISEE fluxgate,
ISEE induction, MAGDAS, MM210, STEL, OMTI ASI, VLF, and SD-fit are loaded through
`pyspedas.erg.gmag_*`, `pyspedas.erg.camera_omti_asi`, `pyspedas.erg.isee_vlf`,
or `pyspedas.erg.sd_fit`. Do **not** promise that these ground routes work through
`load_data_source` or invent CDAWeb dataset IDs for them.

For ground work, record station, cadence, wavelength/filter, time base, and any
availability failure as first-class provenance. For conjugacy, add footpoint /
field-line / MLT-MLAT evidence before making a mapped event claim.

## Compose with existing analysis skills

Do not create ERG-specific duplicates of existing analysis workflows.

- Chorus/EMIC/whistler polarization, wave-normal angle, ellipticity, and
  degree-of-polarization work belongs in `wave-polarization`.
- Field-aligned pitch-angle, loss-cone, beam, or pancake analysis belongs in
  `pitch-angle-distribution`.
- 3D distribution slicing or velocity-space views belong in `particle-velocity-slice`
  (the distribution bridge already supports ERG distribution artifacts).
- 1-D spectra / slopes belong in `power-spectral-density`.
- Coherence / cross-phase between channels belongs in `spectral-cross-coherence`.
- Magnetic footprint or conjugacy work belongs in `field-line-footpoint`.

This skill's job is route discovery, provenance, and paper-quality guardrails.

## Batch 010 ERG/Arase guardrails

The Batch 010 paper-reproduction campaign deliberately kept these rows as
`route_scout` or `proxy`. Preserve these boundaries in PRs, reports, and seed
rows:

- MEP-e/HEP/XEP/LEP **omniflux** browse plots are **not PSD**, not loss-cone, not
  phase-space-density, and not radiation-belt acceleration/loss proof. They are
  route and context artifacts until energy-channel, pitch-angle, calibration, and
  PSD/L-shell handling are explicit.
- Raw PWE/OFA or PWE/HFA spectra are not calibrated UHR/electron-density products
  by themselves. Record frequency-axis/mode metadata and label density as future
  derived analysis unless you actually implement and validate the derivation.
- MGF plus a ground magnetometer quick-look is not a mapped EMIC conjunction.
  Station choice, cadence, coordinates, spacecraft footprint, and time-base
  alignment are required before making that claim.
- OMTI ASI plus PWE on a compact interval is not a paper-quality pulsating-aurora,
  EISCAT, or footpoint-mapping reproduction. Record station, filter/wavelength,
  image dimensions, and mapping caveats.
- Instrument/data-route papers are legitimate anchors for what product exists,
  but they are not science-event reproductions. Keep the words
  **instrument/data-route anchor** visible for the PWE/HFA, HEP/MEP-e, and MGF
  rows below.
- Failed or empty routes should produce structured diagnostics with suggested
  valid products, sites, datatypes, cadences, and first retry, not silent empty
  plots. Batch 010 used this as a guardrail; it did not justify building a new
  diagnostics tool.

## Seed paper/event rows

Use these as starting points and preserve their quality labels.

| Anchor | DOI | Interval used in Batch 010 | Route | Quality label |
|---|---|---|---|---|
| Pulsating aurora from electron scattering by chorus waves | `10.1038/nature25505` | 2017-03-27 11:00–12:00 | MGF + PWE/OFA spectra | `route_scout`; not loss-cone/chorus-scattering reproduction |
| PWE/HFA instrument and UHR route | `10.1186/s40623-018-0854-0` | 2017-04-01 00:00–03:00 | PWE/HFA spectra + MGF | `route_scout` instrument/data-route anchor; not derived electron density |
| HEP/MEP-e instrument flux route | `10.1186/s40623-018-0853-1` plus MEP-e companion `10.1186/s40623-018-0847-z` | 2017-03-27 00:00–06:00 | MEP-e/HEP omniflux + orbit | `proxy` instrument/data-route anchor; omniflux only |
| MGF instrument plus ISEE ground scout | `10.1186/s40623-018-0800-1` | 2017-03-27 10:00–13:00 | MGF + `gmag_isee_fluxgate` | `route_scout` instrument/data-route anchor; not mapped EMIC conjunction |
| Pulsating-aurora type/energy with Arase, all-sky imagers, and EISCAT | `10.1029/2024JA032617` | compact Batch-010 OMTI/PWE test interval | OMTI ASI + PWE/OFA | `route_scout`; not EISCAT or footprint-mapping reproduction |

## Minimal workflow checklist

1. Write the paper/anchor DOI, route quality (`route_scout`, `proxy`, or
   `paper_exact`), and exact claim boundary before loading data.
2. Plan the satellite route first (MGF/PWE/particles/orbit); then separately plan
   any PySPEDAS-only ground route with station/cadence/filter metadata.
3. Fetch a narrow time window and write `run.json`, `provenance.json`, a variable
   inventory, and a compact plot/image preview.
4. If using particle flux, include an energy-channel/units table and state whether
   the product is omniflux or pitch-angle / 3D flux.
5. If using PWE spectra, include frequency-axis/mode/component metadata and mark
   any UHR/electron-density or polarization result as future work unless computed.
6. If using ground routes, include station, cadence, filter/wavelength, and mapping
   caveats. Load `field-line-footpoint` before claiming conjugacy.
7. Cross-link to the existing analysis skill for the next paper-quality step rather
   than writing a one-off ERG-specific analysis procedure.
