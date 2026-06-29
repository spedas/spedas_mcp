---
name: wave-polarization
description: Characterize the polarization of a 3-component magnetic-field wave interval (whistlers, EMIC, chorus, ULF) — degree of polarization, wave-normal angle, ellipticity, helicity, and 3-axis power vs time & frequency, via pyspedas twavpol (Means/Samson method). Composes existing tools; adds no new tool. The wave-domain companion to solar-wind-turbulence-spectrum.
---

# Wave polarization analysis (twavpol)

The canonical IDL SPEDAS `twavpol`/`wavpol` analysis: from a 3-component B (or E)
waveform, decompose the fluctuations into polarization parameters vs time and
frequency. This is how you tell a field-aligned compressional wave from an
obliquely-propagating circularly-polarized whistler — the spectral power alone
(see `solar-wind-turbulence-spectrum`) can't.

## When to use
- "Is this a whistler / EMIC / chorus wave? What's its wave-normal angle?"
- "Degree of polarization / ellipticity / helicity spectrogram for this interval."
- Any 3-component wave identification: parallel vs oblique, R- vs L-hand, planar vs random.

## Tool chain (all existing)
`load_data_source` → `browse_data_parameters` → `fetch_data_product` (3-component B)
→ [optional `generate_fac_matrix` + apply to put B in field-aligned coords]
→ a small `twavpol` call → `render_tplot`, in a `create_spedas_analysis_bundle`.

## Backend (verified output contract)
`pyspedas.analysis.twavpol.twavpol(tvarname, prefix=..., nopfft=..., steplength=..., bin_freq=...)`:
- **Input:** a single tplot variable holding an (N,3) vector time-series (the 3-component B).
- **Returns:** `1` on success, `0` on failure (NOT the data — see the gotcha below).
- **Stores** these tplot variables (retrieve with `get_data`), each an (n_time, n_freq) spectrogram:
  `{prefix}_powspec`, `{prefix}_degpol` (degree of polarization 0–1),
  `{prefix}_waveangle` (wave-normal angle, deg), `{prefix}_elliptict` (ellipticity, −1..1),
  `{prefix}_helict` (helicity), and the per-component wave power variables
  `{prefix}_pspec3_x`, `{prefix}_pspec3_y`, `{prefix}_pspec3_z`.
  `twavpol` does **not** store a combined `{prefix}_pspec3` tplot variable in current PySPEDAS; combine the three component variables yourself only if a downstream artifact needs a single `(n_time,n_freq,3)` array.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(...)`. Use a stationary wave interval (seconds–minutes); polarization assumes the wave properties are roughly steady over the FFT window.

2. **Fetch 3-component B at adequate cadence.** Pick a magnetometer/search-coil dataset whose Nyquist covers the wave band (search-coil SCM for whistler/chorus; fluxgate for ULF/EMIC). Confirm the 3-vector variable with `browse_data_parameters`, then `fetch_data_product(... output_dir=<bundle>/data)`. **Cadence matters** exactly as in the turbulence skill — sub-second for chorus, seconds for ULF.

3. **(Optional but recommended) field-aligned coordinates.** Wave-normal angle is physically meaningful relative to B0. Use `generate_fac_matrix` to build the FAC (Z-along-B) rotation, then apply that matrix stack with a small local script or a pre-rotated artifact so the input to twavpol is in field-aligned coords. For a quick look you can skip this and interpret angles relative to the input frame.

4. **Run twavpol** (small local call, no dedicated MCP tool needed): load the 3-comp B as a tplot var, call `twavpol(var, prefix=...)`, then `get_data` each output. Tune `nopfft` (FFT window length) / `steplength` / `bin_freq` for the time/frequency resolution you want.
   - **Gotcha (verified):** `twavpol` returns only a success bool; the results are the stored tplot variables, retrieved via `get_data('{prefix}_degpol')` etc. Do not expect the arrays back from the call itself.
   - For durable artifacts, write one compact `.npz` per panel you intend to render, using standard spectrogram keys such as `time`, `freq`, and `spectrogram` (or `power` for power). Suggested files: `<bundle>/data/wavepol_powspec.npz`, `wavepol_degpol.npz`, `wavepol_waveangle.npz`, and `wavepol_elliptict.npz`. Keep optional component power files (`wavepol_pspec3_x.npz`, etc.) only if you need them.

5. **Render.** `render_tplot(input_files=[<panel npz files>], output_file=<bundle>/plots/polarization.png, panel_types=["spectrogram",...], zlog=[...])`. `render_tplot` selects one 2-D matrix per `.npz`; do not put all panels into one multi-key `wavepol.npz` and expect a multi-panel stack. Typical stack: power, degree-of-polarization, wave-normal angle, ellipticity.

6. **Interpret (the science).**
   - **Degree of polarization** ~1 → coherent polarized wave; low → random/turbulent. Only trust the other params where degpol is high.
   - **Wave-normal angle** ~0° → field-aligned (parallel) propagation; ~90° → perpendicular/compressional.
   - **Ellipticity** +1 right-hand circular, −1 left-hand, ~0 linear. (Whistlers: R-hand; EMIC: L-hand.)
   - Combine to classify: e.g. high degpol + small wave-normal angle + ellipticity≈+1 ⇒ parallel whistler.

7. **Record** the band, dominant wave-normal angle, ellipticity sign, and degpol in `notes/` with the PNG path.

## Guardrails
- Artifact-first: paths + a compact parameter summary (band, angle, ellipticity), never the full spectrograms.
- Only interpret waveangle/ellipticity/helicity where `degpol` is high — they are meaningless in unpolarized noise.
- Needs the `[analysis]` extra (pyspedas). Cadence must resolve the wave band; state it.
- Stationary window: don't span a mode change or a boundary crossing in one twavpol call.

## Example (output contract verified live)
On a synthetic circularly-polarized 3-component wave, `twavpol('B', prefix='B')` → returned `1` and stored `B_degpol`, `B_waveangle`, `B_elliptict`, `B_helict`, `B_powspec`, plus component power variables `B_pspec3_x`, `B_pspec3_y`, and `B_pspec3_z` (each observed as `(n_time,128)` in the review smoke). It did **not** store `B_pspec3`; the stored-tplot-variable retrieval contract is per-variable/per-component.
