---
name: pitch-angle-distribution
description: Compute the field-aligned pitch-angle distribution (PAD) of a particle population over an interval to classify it as beam / pancake / isotropic or look for a loss cone — bridge a 3D distribution to an artifact, pair a co-temporal B field, run the pitch-angle spectrum, and render the PAD spectrogram. Composes existing tools; adds no new tool.
---

# Field-aligned pitch-angle distribution (PAD)

A guided version of the IDL SPEDAS particle pitch-angle crib sheet — take a particle
population over an interval and ask the classic question: **is it a beam, a pancake, or
isotropic, and is there a loss cone?** Pitch angle is the angle between the particle
velocity and the local magnetic field, so the whole workflow hinges on having a B field
to define the field-aligned axis. There is no dedicated "PAD" tool and there should not
be: `compute_particle_spectra` already produces the field-aligned 0–180° spectrum
directly. This skill is the procedure and interpretation wrapped around it.

## When to use
- "Is this electron/ion population a beam, a pancake, or isotropic?"
- "Show me the pitch-angle distribution / PAD for <mission> on <interval>."
- "Is there a loss cone in this interval?" (the field-aligned-vs-perpendicular question PADs exist to answer.)

## Tool chain (all already exist)
`create_spedas_analysis_bundle` →
(`build_particle_distribution_artifact` | `load_particle_distribution_artifact`, the #95 bridge) →
`fetch_data_product` (the co-temporal B field) →
`compute_particle_spectra(spectrum_types=["pitch_angle"], mag_file=...)` →
`render_tplot`.

## Backend (VERIFIED contract)
- **Distribution input.** `compute_particle_spectra(dist_file, output_dir, ...)` reads a distribution **artifact on disk** — not an in-memory array and not a stored tplot variable name. Produce that artifact with `build_particle_distribution_artifact` (convert a 3D distribution you already have) or `load_particle_distribution_artifact` (the #95 bridge: fetch/load + convert in one step). Both write the file and return its path; pass that path as `dist_file`.
- **Magnetic field input.** `mag_file` is a separate **file** (`.npz` or `.json`), not a tplot var, holding key `b` as `(T,3)` (one B vector per distribution slice) or `(3,)` (broadcast to all slices), in the **distribution's own coordinate frame**. This B defines the field-aligned +z; each slice is rotated into FAC (`spd_pgs_do_fac`) and the polar/pitch angle is binned over 0–180° (colatitude mode).
- **needs_input, not failure.** `spectrum_types` defaults to `["energy","pitch_angle"]`; `"pitch_angle"` **requires** `mag_file`. If `mag_file` is absent the pitch-angle entry returns `status: "needs_input"` (code `needs_input`) while any other requested spectra still compute — the call does not hard-fail.
- **Output = one matrix per .npz, artifact-first.** Each spectrogram is written to `output_dir/particle_spectra_<type>.npz` as a single `(n_time, n_bin)` 2-D matrix (here `n_bin` = pitch-angle bins, axis 0–180°). The tool returns **paths + ranges + shapes only**, never the arrays. `render_tplot` then renders exactly one matrix per `.npz` as a pcolormesh panel.

## Procedure

1. **Bundle & scope.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)`. Use its `data/` for artifacts and `plots/` for the PNG. Keep the interval focused on the population/region of interest.

2. **Get the distribution artifact.** Use `load_particle_distribution_artifact(...)` (the #95 bridge: fetch/load a 3D distribution and convert it to the schema in one step) or `build_particle_distribution_artifact(...)` if you already hold the distribution. Write it under `<bundle>/data`; keep the returned path as `dist_file`. **State the species** (electrons vs ions) and the **energy range** — a PAD is only meaningful for a stated population at a stated energy.

3. **Get a co-temporal B field.** Fetch a magnetometer product that **covers the same interval and cadence** as the distribution: `fetch_data_product(source_type=..., dataset_id=..., parameters=[<B vector>], start, stop, output_dir=<bundle>/data)`. Confirm the vector variable with `browse_data_parameters` first. Produce a `mag_file` whose `b` is `(T,3)` aligned to the distribution slices (or `(3,)` only if B is genuinely steady) and in the **same frame** as the distribution.

4. **Compute the PAD.** `compute_particle_spectra(dist_file=<artifact>, output_dir=<bundle>/data, spectrum_types=["pitch_angle"], mag_file=<B file>)`. Optionally set `resolution` for the angular binning. Check the return: a `needs_input` for `pitch_angle` means the B field was not supplied/usable — fix `mag_file` before going further. On success you get `<output_dir>/particle_spectra_pitch_angle.npz` plus its shape/range stats.

5. **Render.** `render_tplot(input_files=[<particle_spectra_pitch_angle.npz>], output_file=<bundle>/plots/pad.png, panel_types=["spectrogram"], zlog=[true])` — one matrix per `.npz`, so one PAD panel. (If you also requested `energy`, render its `.npz` as a second panel.) Read the PNG back to inspect.

6. **Interpret (the science).**
   - **Beam:** flux peaked near 0° **or** 180° (field-aligned, one direction) — counterstreaming if both.
   - **Pancake:** flux peaked near 90° (perpendicular / trapped).
   - **Isotropic:** roughly flat across 0–180°.
   - **Loss cone:** a depletion at 0° and/or 180° (particles mirrored away / precipitated). Loss-cone interpretation is only valid with the **magnetic-mirror context** (where the spacecraft sits relative to the mirror point / atmosphere); state that context or label the feature tentative.

7. **Record.** Save species, energy range, interval, B source/frame, and the beam/pancake/isotropic/loss-cone verdict to `notes/`. Keep arrays on disk; report numbers + the PNG path, not the spectrogram matrix.

## Guardrails
- Artifact-first: every step writes to the bundle; return paths + compact stats (shapes, ranges, the classification), never pasted PAD arrays.
- **`mag_file` is mandatory and must be co-temporal** with the distribution. Pitch angle is defined relative to B; a missing B yields `needs_input`, and a wrong/stale/mis-framed B yields a *plausible-looking but meaningless* PAD. Confirm the B interval, cadence, and coordinate frame match the distribution.
- Always state the **species and energy range** — "the PAD" is undefined without them; a beam at one energy can be isotropic at another.
- Loss-cone claims require **magnetic-mirror context**; do not assert a loss cone from the 0°/180° depletion alone.
- Use numeric Unix-second timestamps for any spectral/FFT-style step so the slice/time axis stays unambiguous.

## Example
PSP/MMS-style interval → `load_particle_distribution_artifact` (electron distribution) → `fetch_data_product` for the co-temporal MAG vector → `mag_file` with `b` as `(T,3)` in the distribution frame → `compute_particle_spectra(spectrum_types=["pitch_angle"], mag_file=...)` → `particle_spectra_pitch_angle.npz` (`n_time × n_pitch_bin`) → `render_tplot` one-panel PAD spectrogram. Run the same call **without** `mag_file` and the `pitch_angle` entry comes back `needs_input` (the FAC rotation has no B axis) — exactly the case where the guardrail stops you from producing a meaningless PAD.
