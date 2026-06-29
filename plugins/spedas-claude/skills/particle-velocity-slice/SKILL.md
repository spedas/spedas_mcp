---
name: particle-velocity-slice
description: Produce a 2D velocity-space distribution slice (spd_slice2d) from a 3D particle distribution — the iconic SPEDAS plot for spotting beams, crescents, and non-Maxwellian ion/electron structure that moments and 1D spectra hide. Use when you have a 3D distribution artifact and want a vx–vy slice in a chosen plane (xy/xz/yz, BV, BE, perp) with interpolation and optional bulk-velocity subtraction. Composes existing tools; adds no new tool.

---

# 2D velocity-space distribution slice (spd_slice2d)

The canonical IDL/Python SPEDAS `spd_slice2d` plot: cut a single 2D plane through a
3D particle velocity distribution and render it as a vx–vy heatmap. This is how you
see beams, temperature anisotropy, ring/crescent distributions, and other
non-Maxwellian structure that bulk moments average away and that 1D energy/pitch-angle
spectra collapse. It is **downstream** of a real 3D distribution: it consumes a
distribution artifact, it does not create one.

## When to use
- "Show me a 2D slice of the ion/electron distribution at <time> in the BV plane."
- "Is there a beam / crescent / ring in this distribution? Plot the velocity-space cut."
- "Compare the distribution with and without bulk-velocity subtraction."
- Any single-time (or short-window-averaged) velocity-space inspection of a 3D dist.

Do **not** use this for energy-time spectrograms or pitch-angle distributions (use
`compute_particle_spectra`), for moments (use `compute_particle_moments`), or when you
do not yet have a 3D distribution — build it first (see prerequisite below).

## Prerequisite (hard dependency)
This skill requires a **real 3D distribution object** (the pyspedas particle
distribution dict/array, per energy × theta × phi per time), not a tplot spectrogram.
Produce it first with the **particle-distribution bridge** skill
(`build_particle_distribution_artifact`, the `#95` bridge): it loads the L2 particle
product (a `*-DIST` 3D distribution, e.g. MMS FPI `dis-dist`/`des-dist`, MMS HPCA, or an
ERG particle product) and emits a distribution artifact. **Supported bridge converters
today are MMS FPI/HPCA + ERG only** — THEMIS ESA and PSP SPAN-i have no Python
`*_get_dist` converter in pyspedas yet, so the bridge returns `code="unsupported"` for
them; treat them as not-yet-available until upstream pyspedas exposes the converters. If
you only have a spectrogram, stop — `spd_slice2d` cannot use it.

## Tool chain (all existing)
particle-distribution bridge (`build_particle_distribution_artifact`) → small local
`slice2d` call → write the vx–vy grid to a single `.npz` → `render_tplot`
(one spectrogram-style panel), all inside a `create_spedas_analysis_bundle`.
For BV/BE/perp planes and bulk subtraction you also need aligned **B** and **bulk
velocity** time-series — fetch those with `load_data_source` / `browse_data_parameters`
/ `fetch_data_product`.

## Backend (verified contract)
`pyspedas.particles.spd_slice2d.slice2d.slice2d(dists, time=, window=, interpolation='geometric'|'2d'|'nearest', rotation='xy'|'xz'|'yz'|'bv'|'be'|'perp'|..., subtract_bulk=False, mag_data=None, vel_data=None, ...)`:
- **Input:** `dists` is the 3D distribution object from the bridge (a list/array of
  per-time distribution dicts), **not** a tplot variable name and **not** an array of
  values. `time=` selects the center time; `window=`/`samples=` average a short span.
- **Returns:** a **slice dict** (the data, returned directly — unlike many pyspedas
  funcs that only store tplot vars). Key fields: `'xgrid'` and `'ygrid'` (the velocity
  axes, km/s), `'data'` (the 2D `(ny, nx)` interpolated value grid, typically phase-space
  density or flux), plus metadata such as `'rotation'`, `'coord'`, `'units_name'`, and
  the rotation/orientation vectors. There is **no tplot variable to `get_data` here** —
  read the grid straight from the returned dict.
- **Rotation needs context:** `rotation='bv'|'be'|'perp'` (and bulk subtraction)
  require `mag_data=` and/or `vel_data=` arrays aligned to the slice time; `'xy'|'xz'|'yz'`
  are in the instrument/data frame and need no extra inputs.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)`. Use its `data/` and `plots/` for every artifact below.

2. **Get the 3D distribution (prerequisite).** Run the particle-distribution bridge to produce/locate the distribution artifact for your instrument and interval. Confirm it is a 3D distribution object (energy × theta × phi per time), not a spectrogram. Pick a tight interval bracketing the time(s) you want to slice.

3. **Fetch B and bulk-V if needed.** For `rotation='bv'|'be'|'perp'` and/or `subtract_bulk=True`, fetch the magnetic field vector and the species bulk-velocity moment with `fetch_data_product(... output_dir=<bundle>/data)` (e.g. MMS FGM `*_b_gse_*` and FPI `*_bulkv_*`). Align them to the slice time/window. Confirm exact parameter names with `browse_data_parameters`.

4. **Run slice2d** (small local call, no dedicated MCP tool): load the distribution object from the bridge artifact, then
   `s = slice2d(dists, time=<center>, window=<sec>, rotation=<plane>, interpolation='geometric', subtract_bulk=<bool>, mag_data=<B>, vel_data=<V>)`.
   - **Gotcha (verified):** `slice2d` returns the slice **dict directly** — read `s['xgrid']`, `s['ygrid']`, `s['data']`. Do not call `get_data`; nothing is stored as a tplot variable.
   - State your three choices explicitly, because they change the meaning: the **plane** (which 2D cut), the **interpolation** (`geometric` = closest to the measured bins; `2d`/`nearest` smooth or coarsen differently), and **bulk subtraction** (`subtract_bulk=True` plots in the plasma rest frame and recenters the core at the origin — a beam sits off-center; `False` plots in the spacecraft frame).

5. **Write one `.npz` (one panel).** Save a single 2D grid per file using spectrogram-style keys so `render_tplot` can render it as one panel: e.g. `np.savez(<bundle>/data/slice_bv.npz, x=s['xgrid'], y=s['ygrid'], spectrogram=s['data'])` (vx on x, vy on y, values as the 2D matrix). `render_tplot` renders **one 2-D matrix per `.npz`** — for multiple slices (different planes/times, or with vs without bulk subtraction) write **separate** `.npz` files, one per panel.

6. **Render.** `render_tplot(input_files=[<slice .npz files>], output_file=<bundle>/plots/velocity_slice.png, panel_types=["spectrogram", ...], zlog=[true, ...])`. Phase-space density spans many decades — use `zlog=true`. Note in the answer that the axes are velocity (km/s), not a time–frequency spectrogram, even though the panel type is "spectrogram". Read the PNG back to inspect for beams/crescents/anisotropy.

7. **Reliability check (state the frame and method).** Every slice answer must record: the **slice plane/rotation**, the **interpolation** method, whether **bulk velocity was subtracted** (and in which frame the result therefore lives), the species, the center time and averaging window, and the value units. A "beam off the origin" means nothing unless the reader knows whether the core was recentered. Flag low counts / sparse angular coverage — interpolation will happily fill gaps that the instrument never measured.

8. **Record.** Drop plane, interpolation, subtract_bulk, species, time/window, units, and the PNG path into the bundle's `notes/`. Keep the grids on disk; return paths + a compact summary (grid shape, vx/vy extent, value min/max), never the pasted 2D array.

## Guardrails
- Artifact-first: write each slice grid to the bundle and return paths + compact stats (shape, velocity extent, value range); never paste the 2D matrix.
- **Prerequisite is non-negotiable:** needs a real 3D distribution object from the particle-distribution bridge (`#95`). A spectrogram or moment cannot be sliced.
- One 2D grid per `.npz`, one panel per file — do not pack multiple slices into one multi-key npz and expect a multi-panel stack.
- `bv`/`be`/`perp` and `subtract_bulk` require aligned `mag_data`/`vel_data`; without them, fall back to `xy`/`xz`/`yz` in the data frame and say so.
- Interpolation fabricates a smooth field from discrete bins — distrust structure in poorly-sampled regions; report counts/coverage caveats. State plane + interpolation + bulk-subtraction in every result (the frame changes the science).
- Needs the `[analysis]` extra (pyspedas). State the species and cadence.

## Example (contract)
MMS1 FPI ions (`dis-dist`) around a magnetopause crossing: build the 3D distribution with the bridge, fetch FGM B (GSE) and FPI ion `bulkv`, then `slice2d(dis_dist, time='2017-07-11/22:34:02', window=0.15, rotation='bv', interpolation='geometric', subtract_bulk=True, mag_data=B, vel_data=V)` returns a dict with `xgrid`/`ygrid` (km/s) and a `(ny,nx)` `data` grid. Saved as `slice_bv.npz` (`x`,`y`,`spectrogram`) and rendered with `render_tplot(panel_types=["spectrogram"], zlog=[true])`. With bulk subtraction the core sits at the origin and a sunward crescent appears off-center in the perpendicular direction — the non-Maxwellian signature invisible in the ion moments alone.