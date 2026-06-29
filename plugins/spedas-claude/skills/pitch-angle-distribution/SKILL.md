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
(`build_particle_distribution_artifact` | `load_particle_distribution_artifact`, the #95 bridge — give it the B field here via `mag_tplot_name=`/`magf=`) →
`compute_particle_spectra(spectrum_types=["pitch_angle"])` (reuses the artifact's embedded `magf`) →
`render_tplot`.

## Backend (VERIFIED contract)
- **Distribution input.** `compute_particle_spectra(dist_file, output_dir, ...)` reads a distribution **artifact on disk** — not an in-memory array and not a stored tplot variable name. Produce that artifact with `build_particle_distribution_artifact` (convert a 3D distribution you already have) or `load_particle_distribution_artifact` (the #95 bridge: fetch/load + convert in one step). Both write the file and return its path; pass that path as `dist_file`.
- **B field comes from the artifact by default (issue #148).** The #95 bridge already requires a B field to write the artifact (`mag_tplot_name=` or `magf=`) and stores it as embedded `magf` shaped `(T,3)`. `compute_particle_spectra(spectrum_types=["pitch_angle"])` **reuses that embedded `magf` automatically** — no separate `mag_file` needed. The pitch-angle entry reports `mag_source: "distribution_artifact_magf"`. This B defines the field-aligned +z; each slice is rotated into FAC (`spd_pgs_do_fac`) and the polar/pitch angle is binned over 0–180° (colatitude mode).
- **`mag_file` is an optional override.** Pass `mag_file` only when you want a *different* B reference than the one embedded in the artifact (e.g. a higher-cadence or differently-framed magnetometer product). It is a separate **file** (`.npz`/`.json`), not a tplot var, holding key `b` as `(T,3)` (one B vector per distribution slice) or `(3,)` (broadcast), in the **distribution's own coordinate frame**. An explicit `mag_file` wins over embedded `magf`; the entry then reports `mag_source: "mag_file"`.
- **needs_input, not failure.** `spectrum_types` defaults to `["energy","pitch_angle"]`. `"pitch_angle"` needs a B reference: embedded `magf` or `mag_file`. Only when the artifact has **no** embedded `magf` **and** no `mag_file` is passed does the pitch-angle entry return `status: "needs_input"` (code `needs_input`, `mag_source: "missing"`) while any other requested spectra still compute — the call does not hard-fail.
- **Output = one matrix per .npz, artifact-first.** Each spectrogram is written to `output_dir/particle_spectra_<type>.npz` as a single `(n_time, n_bin)` 2-D matrix (here `n_bin` = pitch-angle bins, axis 0–180°). The tool returns **paths + ranges + shapes only**, never the arrays. `render_tplot` then renders exactly one matrix per `.npz` as a pcolormesh panel.

## Procedure

1. **Bundle & scope.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)`. Use its `data/` for artifacts and `plots/` for the PNG. Keep the interval focused on the population/region of interest.

2. **Get the distribution artifact with its B field embedded.** Use `load_particle_distribution_artifact(...)` (the #95 bridge: fetch/load a 3D distribution and convert it to the schema in one step) or `build_particle_distribution_artifact(...)` if you already hold the distribution. **Supply the co-temporal B field to the bridge here** via `mag_tplot_name=` (a loaded magnetometer tplot var, interpolated to the distribution slices) or `magf=` (explicit `(T,3)`/`(3,)` vectors). The bridge stores it as embedded `magf`, which the PAD step reuses. Write the artifact under `<bundle>/data`; keep the returned path as `dist_file`. **State the species** (electrons vs ions) and the **energy range** — a PAD is only meaningful for a stated population at a stated energy.

3. **Compute the PAD (embedded B field, no extra file).** `compute_particle_spectra(dist_file=<artifact>, output_dir=<bundle>/data, spectrum_types=["pitch_angle"])`. This reuses the artifact's embedded `magf`; the entry returns `mag_source: "distribution_artifact_magf"`. Optionally set `resolution` for the angular binning. On success you get `<output_dir>/particle_spectra_pitch_angle.npz` plus its shape/range stats. A `needs_input` (`mag_source: "missing"`) means the artifact carried no `magf` — rebuild it with a B field (step 2) or pass an override (step 3b).

   **3b. Override the B field (optional).** Only if you need a *different* B reference than the embedded one, fetch a magnetometer product covering the **same interval, cadence, and frame** as the distribution (`fetch_data_product(...)`; confirm the vector variable with `browse_data_parameters`), write a `mag_file` whose `b` is `(T,3)` aligned to the slices (or `(3,)` if B is steady), and pass `mag_file=<B file>`. The entry then reports `mag_source: "mag_file"`.

4. **Render.** `render_tplot(input_files=[<particle_spectra_pitch_angle.npz>], output_file=<bundle>/plots/pad.png, panel_types=["spectrogram"], zlog=[true])` — one matrix per `.npz`, so one PAD panel. (If you also requested `energy`, render its `.npz` as a second panel.) Read the PNG back to inspect.

5. **Interpret (the science).**
   - **Beam:** flux peaked near 0° **or** 180° (field-aligned, one direction) — counterstreaming if both.
   - **Pancake:** flux peaked near 90° (perpendicular / trapped).
   - **Isotropic:** roughly flat across 0–180°.
   - **Loss cone:** a depletion at 0° and/or 180° (particles mirrored away / precipitated). Loss-cone interpretation is only valid with the **magnetic-mirror context** (where the spacecraft sits relative to the mirror point / atmosphere); state that context or label the feature tentative.

6. **Record.** Save species, energy range, interval, B source/frame (and `mag_source`), and the beam/pancake/isotropic/loss-cone verdict to `notes/`. Keep arrays on disk; report numbers + the PNG path, not the spectrogram matrix.

## Guardrails
- Artifact-first: every step writes to the bundle; return paths + compact stats (shapes, ranges, the classification), never pasted PAD arrays.
- **A co-temporal B field is mandatory** — but it normally comes from the artifact's embedded `magf` (supplied to the #95 bridge), not a separate `mag_file`. Pitch angle is defined relative to B; no B anywhere yields `needs_input`, and a wrong/stale/mis-framed B yields a *plausible-looking but meaningless* PAD. Confirm the B interval, cadence, and coordinate frame match the distribution, and check `mag_source` in the result to know which B was actually used.
- Always state the **species and energy range** — "the PAD" is undefined without them; a beam at one energy can be isotropic at another.
- Loss-cone claims require **magnetic-mirror context**; do not assert a loss cone from the 0°/180° depletion alone.
- Use numeric Unix-second timestamps for any spectral/FFT-style step so the slice/time axis stays unambiguous.

## Example
MMS-style interval → `load_particle_distribution_artifact` (electron distribution, B field via `mag_tplot_name=`/`magf=` so it is embedded as `magf`) → `compute_particle_spectra(spectrum_types=["pitch_angle"])` (reuses the embedded `magf`; `mag_source: "distribution_artifact_magf"`) → `particle_spectra_pitch_angle.npz` (`n_time × n_pitch_bin`) → `render_tplot` one-panel PAD spectrogram. To swap in a different magnetometer product, add `mag_file=...` and the entry reports `mag_source: "mag_file"`. Only if the artifact carries no `magf` **and** you pass no `mag_file` does the `pitch_angle` entry come back `needs_input` (`mag_source: "missing"`, the FAC rotation has no B axis) — exactly the case where the guardrail stops you from producing a meaningless PAD.
