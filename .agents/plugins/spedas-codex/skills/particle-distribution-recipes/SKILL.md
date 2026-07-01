---
name: particle-distribution-recipes
description: Preflight and route real 3D particle distribution artifacts for moments, spectra, pitch-angle distributions, and velocity-space slices without expanding the default Agent Kit MCP tool surface.
---

# Particle distribution recipes

Use this skill when a researcher asks for MMS/ERG/THEMIS-style particle
"distributions", 3D phase-space density, moments from distributions, energy /
theta / phi / pitch-angle / gyro spectra, or velocity-space slices. This is an
upstream route-scout and validation skill: it chooses a valid distribution
product and artifact path, then hands off to the existing analysis tools and
specialized skills.

It does **not** replace `pitch-angle-distribution` or
`particle-velocity-slice`. Those skills interpret already-built artifacts; this
skill decides whether the requested data are a real 3D distribution, how to
build/load the artifact, which side inputs are required, and which downstream
route should own the science product.

## MCP/default-surface boundary

This skill adds no default MCP tool. Mission loaders and PySPEDAS/SPEDAS
particle helpers are external runtime vocabulary and must be marked with
`external_runtime_route.not_an_mcp_tool: true` unless a current Agent Kit server
actually exposes the action.

```yaml
external_runtime_route:
  not_an_mcp_tool: true
  examples:
    - pyspedas.projects.mms.particles.mms_part_getspec.mms_part_getspec
    - pyspedas.projects.mms.particles.mms_part_products.mms_part_products
    - pyspedas.projects.mms.particles.mms_part_slice2d.mms_part_slice2d
    - pyspedas.projects.mms.fpi_tools.mms_pad_fpi.mms_pad_fpi
    - pyspedas.projects.mms.fpi_tools.mms_load_fpi_calc_pad.mms_load_fpi_calc_pad
    - pyspedas.projects.mms.fpi_tools.mms_get_fpi_dist.mms_get_fpi_dist
    - pyspedas.projects.mms.hpca_tools.mms_get_hpca_dist.mms_get_hpca_dist
    - pyspedas.particles.spd_slice2d.slice2d.slice2d
    - pyspedas.particles.spd_part_products.spd_pgs_moments
    - pyspedas.particles.moments_3d.moments_3d
    - spedas_idl.spd_pgs_make_e_spec
    - spedas_idl.spd_pgs_make_theta_spec
    - spedas_idl.spd_pgs_make_phi_spec
    - spedas_idl.thm_part_getspec
    - spedas_idl.erg_pgs_moments
```

Do **not** invent MCP-prefixed PySPEDAS particle helpers, and do not present
PySPEDAS functions as dedicated Agent Kit tools. The Agent Kit path is: plan a
bounded mission/product query -> create an analysis bundle -> build or load a
3D distribution artifact -> compute moments/spectra or hand off to PAD/slice
skills -> return artifact paths, compact metadata, and provenance.

## Product validity rules

| Request / product | Use as distribution artifact? | Route |
|---|---:|---|
| MMS FPI ion/electron `*-DIST` products such as `MMS1_FPI_FAST_L2_DIS-DIST` or `MMS1_FPI_FAST_L2_DES-DIST` | Yes | `build_particle_distribution_artifact`, then moments/spectra/PAD/slice |
| MMS HPCA distribution products and species (`hplus`, `heplus`, `heplusplus`, `oplus`, `oplusplus`) | Yes, with HPCA ancillary/azimuth caveats | Build/load artifact, then spectra/moments where supported |
| ERG/Arase particle distributions (`3dflux`, `2dflux`, `omniflux`, LEPe/LEPi/MEPe/MEPi/HEP/XEP) | Yes when the bridge supports the instrument/product | Build/load artifact, then spectra/moments/PAD |
| `*-MOMS`, official moments, scalar spectra, tplot spectrograms, or CDF quicklook variables | No | Use as context or compare against `compute_particle_moments`, not as `dist_file` |
| THEMIS ESA/SST or PSP SPAN-i distribution requests | Not a default Agent Kit artifact route yet | Treat as legacy/unsupported unless a Python converter artifact already exists |

If the user gives a moment or spectrogram variable, ask for or discover the
corresponding `*-DIST` / distribution-function product before calling it a
particle distribution artifact. Use official moments for overview and sanity
checks, but use the distribution product to build the artifact.

## Analysis tool chain

1. **Plan and bound the fetch.** Use `create_spedas_analysis_bundle`, discovery
   resources, and mission workflow skills to select probe/spacecraft, instrument,
   species, data rate, level, and a narrow time range. Burst distributions can be
   large; avoid broad downloads.
2. **Build or load the artifact.** Use `[analysis] build_particle_distribution_artifact`
   when the server has the analysis extra enabled. Record `dist_file`, product,
   species, cadence, energy bins, angular bins, frame, units, and any support
   variables. Use `load_particle_distribution_artifact` to inspect an existing
   artifact before downstream calculations.
3. **Choose the derived product.** Use `compute_particle_moments` for density /
   bulk velocity / temperature from the artifact; use `compute_particle_spectra`
   with `spectrum_types=["energy", "pitch_angle", "azimuth", "elevation"]` for
   compact spectra. Route field-aligned PAD interpretation to
   `pitch-angle-distribution`; route 2D velocity-space planes to
   `particle-velocity-slice`.
4. **Render only compact artifacts.** Use `render_tplot` or runtime plotting only
   after artifact metadata are known. Return paths and sidecar metadata, not raw
   distribution arrays.

## Side-input checklist

- **Magnetic field for PAD/FAC.** PAD, gyro, FAC moments, and BV/BE rotations
  require a co-temporal magnetic field in the distribution frame. Prefer embedding
  the field during artifact build via `magf` / `mag_tplot_name`, which downstream
  reports as `distribution_artifact_magf`. A `mag_file` override is a file path,
  not a tplot variable name.
- **Bulk velocity for velocity rotations.** Bulk subtraction, `xvel`, `bv`, `be`,
  and perpendicular slice rotations require a velocity support source (`vel_data`
  / bulk velocity) with matching coordinates and cadence.
- **Spacecraft potential and corrections.** Record `sc_pot_name` / `sc_pot`,
  DES photoelectron options, one-count-level handling, regridding, and whether
  generated moments may differ from official mission moments.
- **Units and ranges.** Preserve `eflux`, `flux`, `df_cm`, or `df_km`; record
  `energy`, `theta`, `phi`, `pitch`, or `gyro` limits and whether limits are data
  cuts or display-only ranges.

## Output/provenance contract

Every particle-distribution recipe should leave a bundle record with:

- distribution artifact path (`dist_file` or bundle-relative path), format, and
  SHA-256 when available;
- mission, probe/spacecraft, instrument, species, data rate, level, time range,
  product id, cadence, coordinate frame, and units;
- shape/bin metadata: time samples, energy bins, theta/phi or pitch/gyro bins,
  valid-value ranges, fill/gap policy, and quality flags;
- side inputs: `magf`/`distribution_artifact_magf`, `mag_file`, bulk velocity,
  spacecraft potential, photoelectron or one-count-level settings;
- derived artifacts: moments JSON/CSV, spectra tplot/PNG/SVG/PDF, PAD summary,
  or 2D slice `.npz`/image paths;
- a caveat if a route is legacy IDL-only, experimental PySPEDAS particle code,
  unsupported by the current Agent Kit bridge, or intended only as vocabulary.

Do not paste raw arrays, full CDF contents, or dense distribution bins in chat.

## Vocabulary bridge

Recognize these as particle-distribution intents and normalize them before
choosing tools:

- `particle_distribution`, `distribution_function`, `phase_space_density`,
  `3d_distribution`, `3dflux`, `2dflux`, `omniflux`;
- `energy_spectrogram`, `theta_spectrogram`, `phi_spectrogram`,
  `pitch_angle_distribution`, `gyro_phase_distribution`;
- `moments`, `fac_moments`, density, bulk velocity, temperature;
- `2d_slice`, `velocity_slice`, `slice2d`, `bulk_velocity_subtraction`,
  `regrid`, `field_aligned_coordinates`, `fac_type`;
- MMS aliases: FPI DES/DIS, HPCA, `mms_part_getspec`, `mms_part_slice2d`,
  `mms_pad_fpi`, `mms_load_fpi_calc_pad`;
- ERG aliases: `erg_lep`, `erg_lepe`, `erg_lepi`, `erg_mep`, `erg_hep`,
  `erg_xep`, `erg_*_part_products`, `erg_*_get_dist`;
- THEMIS legacy aliases: `thm_part_getspec`, `thm_part_products`,
  `thm_part_slice2d`, ESA, SST. Treat these as compatibility vocabulary unless
  an Agent Kit bridge artifact already exists.

## Handoffs

- `mms-basic-workflows` for MMS mission/product route scouting and burst/SROI
  data-volume gates.
- `pyspedas-load-planning` for bounded loads, no-update/cache choices, and public
  archive caveats.
- `tplot-data-lifecycle` for tplot variable metadata and cleanup before building
  artifacts from runtime state.
- `pitch-angle-distribution` for beam/pancake/loss-cone interpretation after the
  artifact has a valid magnetic-field source.
- `particle-velocity-slice` for 2D slice planes, interpolation, rotations, and
  bulk-subtraction interpretation.
- `pytplot-plotting-options` for styling or saving spectra/PAD/slice figures.
