---
name: spectral-cross-coherence
description: Measure magnitude-squared coherence and cross-phase between two scalar channels over a stationary interval — "are these two signals coherent at frequency f, and what's the phase lag?" (two components of B, B vs density, wave-mode identification, propagation). Composes existing tools; adds no new tool.
---

# Spectral cross-coherence and cross-phase

The two-channel companion to the single-channel power-spectral-density workflow
(`solar-wind-turbulence-spectrum`). From two scalar time series over the same
interval, compute the **magnitude-squared coherence** C_xy(f) ∈ [0,1] (how
linearly related the two channels are at each frequency) and the **cross-phase**
∠P_xy(f) (the phase lag between them). This is how you ask whether two signals
share a common wave at frequency f, and which one leads — e.g. B_R vs B_T,
B vs density (compressional vs incompressible), or the same channel on two
spacecraft for propagation timing.

## When to use
- "Are these two channels coherent at frequency f, and what's the phase lag?"
- "Is this fluctuation compressional?" — coherence/phase between |B| and density.
- Wave-mode / propagation: phase lag between two components, or the same field on two spacecraft.

## Tool chain (existing tools only)
`create_spedas_analysis_bundle` → `load_data_source` → `browse_data_parameters`
→ `fetch_data_product` (×2, or one multi-component fetch + derive the two scalars)
→ **local scipy coherence/csd on a common uniform time grid** → write per-panel `.npz`
→ `render_tplot`. There is no dedicated pyspedas coherence tool — the spectral step is a
small local computation, the same pattern as the local PSD step in the turbulence skill.

## Backend (VERIFIED contract)
There is **no MCP/pyspedas cross-coherence tool**; you compute it locally with scipy
and persist `.npz` artifacts. The verified numeric contract:

- **Input is a state array, not a stored tplot var:** scipy works on plain in-memory
  ndarrays `x`, `y` that you have already loaded from the fetched files and **resampled
  to one common uniform time grid**. Coherence requires identical sampling — same `fs`,
  same length, sample-aligned — so both channels must be interpolated onto the *same*
  numeric Unix-second grid before this step. There is no tplot variable and no dict/tuple
  handed back by a tool here.
- `scipy.signal.coherence(x, y, fs=fs, nperseg=...)` → returns a plain tuple
  `(f, Cxy)`: `f` = frequency ndarray, `Cxy` = magnitude-squared coherence ndarray in
  [0,1]. Welch-averaged over segments.
- `scipy.signal.csd(x, y, fs=fs, nperseg=...)` → returns `(f, Pxy)`: `Pxy` is the
  **complex** cross-spectral density. Cross-phase = `numpy.angle(Pxy)` (rad);
  convert to degrees for the panel: `numpy.degrees(numpy.angle(Pxy))`.
- Both calls return plain ndarrays computed locally (same as the pwrspc-style PSD step);
  nothing is stored as a tplot variable.
- **`render_tplot` = ONE 2-D matrix per `.npz`.** A coherence-vs-frequency curve and a
  phase-vs-frequency curve are two separate panels, so write **one `.npz` per panel**
  (do not pack both into one multi-key file and expect a 2-panel stack). Keep them
  side-by-side on the same frequency axis.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)`. Pass `output_dir`; use its `data/` and `plots/` for every artifact. Choose a **stationary** window — coherence assumes the relationship is steady over the interval.

2. **Fetch both channels.** Confirm variables with `browse_data_parameters(source_type=..., dataset_id=...)`, then `fetch_data_product(... output_dir=<bundle>/data)` for each. Two cases:
   - Two components of one vector (e.g. B_R, B_T) → one fetch, derive both scalars.
   - Two physically different channels (e.g. |B| from MAG and density from SWEAP) → two fetches, possibly two datasets/cadences.
   Check the returned `stats` / `quality_checks` for fill/outliers first.

3. **Align/resample to a COMMON uniform grid.** This is the load-bearing step. Build one **numeric Unix-second** time axis at a single chosen `fs` spanning the overlap of both channels, and interpolate **both** series onto it. Both arrays must end up the same length, same `fs`, sample-aligned. Coherence between mismatched/irregular grids is meaningless. Use numeric Unix-second timestamps throughout this and the FFT step (never datetime strings).

4. **Coherence + cross-phase (local scipy).** With the two aligned ndarrays:
   - `f, Cxy = scipy.signal.coherence(x, y, fs=fs, nperseg=NPERSEG)`
   - `f, Pxy = scipy.signal.csd(x, y, fs=fs, nperseg=NPERSEG)`; `phase_deg = numpy.degrees(numpy.angle(Pxy))`
   Pick `nperseg` so you get **enough Welch segments** — coherence near 1 from a single segment is an artifact (see guardrails). Record `nperseg` and the resulting segment count.

5. **Write per-panel `.npz`.** Because `render_tplot` takes one matrix per file, write **two** files into `<bundle>/data`:
   - `coherence.npz` with `{freq, coherence}` (coherence in [0,1])
   - `cross_phase.npz` with `{freq, phase_deg}`
   (You may also stash `{freq, coherence, phase_deg, nperseg, fs, n_segments}` in a sidecar for provenance, but the render inputs stay one-matrix-per-file.) Keep arrays on disk; never paste them into the response.

6. **Render.** `render_tplot(input_files=[<coherence.npz>, <cross_phase.npz>], output_file=<bundle>/plots/coherence.png, panel_types=["line","line"])`. Coherence panel on a 0–1 y-axis; phase panel in degrees (−180..180). Read the PNG back to inspect.

7. **Interpret & record.** Identify the band(s) where coherence is high and report the corresponding cross-phase there (phase is only meaningful where coherence is high). Note `fs`, `nperseg`, segment count, the dataset/interval, and the two channels in `notes/`. Return paths + compact stats (peak coherence, its frequency, phase at that frequency), never the arrays.

## Guardrails
- **Common grid is mandatory:** both series must share the **same uniform time grid and the same `fs`**, sample-aligned. Resample first; coherence/csd on mismatched or irregular grids is invalid.
- **Numeric Unix-second timestamps** for the resampling and every spectral/FFT step — not datetime strings.
- **Stationary window:** don't span a shock, sector boundary, or mode change in one call; split the interval if conditions change.
- **Segment count matters:** coherence near 1 is only meaningful with enough Welch segments. A single (or very few) `nperseg`-length segment forces C_xy≈1 everywhere as a numerical artifact. **Always report `nperseg` and the segment count**, and choose `nperseg` so the window holds several segments.
- **Phase only where coherent:** cross-phase is meaningless where coherence is low — quote phase only in high-coherence bands.
- High coherence is **not** causation; it is shared linear structure at that frequency. **State the band** you are claiming coherence/phase over.
- Artifact-first: paths + a compact summary (peak coherence + frequency + phase there, `fs`, `nperseg`, segments), never pasted spectra.

## Example
PSP `PSP_FLD_L2_MAG_RTN` → derive B_R and B_T over a stationary ~1 h interval. Resample
both onto one Unix-second grid at a common `fs`, then `scipy.signal.coherence` and
`scipy.signal.csd` with `nperseg` chosen for ~8 Welch segments. Write `coherence.npz`
`{freq, coherence}` and `cross_phase.npz` `{freq, phase_deg}`, render a 2-panel line plot.
A coherence peak (≈0.8) in a narrow ULF band with cross-phase ≈ +90° between B_R and B_T
indicates a transverse, roughly circularly-polarized fluctuation in that band — reported
with the band, `nperseg`, and segment count so the result is self-documenting.
