---
name: power-spectral-density
description: Compute the quick-look 1-D power spectral density (FFT/Welch PSD) of one scalar channel over a single stationary interval — the spectrum-vs-frequency picture (no time axis) for reading off a spectral slope or peak. Use when you want "what's the PSD slope / spectral peak of this interval?" rather than its time evolution. Composes existing spedas tools; adds no new tool.
---

# Single-interval power spectral density (1-D PSD)

A guided version of the IDL SPEDAS `pwrspc` crib sheet: take one scalar channel over a
stationary interval and produce the classic log–log PSD so you can read off the
inertial-range slope (e.g. Kolmogorov ~f^-5/3) or a spectral peak. This is the
**single-interval** spectrum — collapsed over time, no dynamic axis. For the
time-evolving picture use the `dynamic-power-spectrum` / wavelet tools instead.

## When to use
- "What's the PSD slope of |B| (or B_R, density, V) over this interval?"
- "Where's the spectral peak / break frequency for this window?"
- "Give me the quick-look FFT spectrum, I don't need the time evolution."

## Tool chain (all already exist)
`load_data_source` → `browse_data_parameters` → `fetch_data_product`
→ a small **local `pwrspc(time, values)` call** → write `{freq, power}` to one `.npz`
→ `render_tplot` (single line panel, log–log), wrapped in `create_spedas_analysis_bundle`.

There is deliberately no MCP "PSD" tool: `pwrspc` returns plain arrays, so the spectrum
is computed locally and only the resulting two columns are written to disk.

## Backend (VERIFIED contract)
`pyspedas.tplot_tools.tplot_math.pwrspc.pwrspc(time, quantity, noline=False, nohanning=False, bin=3, notperhz=False)`
**returns a `(freq, power)` tuple of ndarrays DIRECTLY** — it does **not** create or store a
tplot variable, and it does not write a file. You call it in-process and capture the two arrays.
- `time` must be **numeric Unix-second timestamps** (a 1-D float array), not ISO strings / datetime64.
- `quantity` is the 1-D scalar values array, same length as `time`.
- `noline=False` removes a linear trend; `nohanning=False` applies a Hanning window; `bin` sets log-frequency bin smoothing; `notperhz=False` returns power per Hz.
- `freq` is in Hz (derived from the sampling interval implied by `time`), so **irregular/non-monotonic timestamps corrupt the frequency axis** — resample to a uniform grid first if cadence is irregular.

## Procedure

1. **Bundle & scope.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)`. Use its `data/` and `plots/` dirs for every artifact below. Pick a **statistically stationary** window (no shock/sector boundary mid-interval).

2. **Pick the dataset & channel.** Confirm the exact variable with `browse_data_parameters(source_type=..., dataset_id=...)`. Prefer the highest cadence that resolves your band of interest (spectral range scales with sampling interval — state the cadence you used).

3. **Fetch the scalar.** `fetch_data_product(source_type=..., dataset_id=..., parameters=[<channel>], start, stop, output_dir=<bundle>/data)`. For a magnitude spectrum, fetch the B vector and **derive a scalar column** in a small CSV: `Bmag = sqrt(BR^2+BT^2+BN^2)` (or use any single component / density / speed directly). Check the returned `stats`/`quality_checks` for fill/NaN/outliers before proceeding.

4. **Build numeric inputs.** Load the CSV; convert the `time` column to **numeric Unix seconds** (float) and extract the scalar `values`. Drop NaNs/fill, and if the cadence is irregular resample to a uniform grid (otherwise the `freq` axis is wrong). Both arrays must be the same length.

5. **Call `pwrspc`.** In a small local Python step:
   `freq, power = pwrspc(time_unix, values, noline=False, nohanning=False, bin=3, notperhz=False)`.
   It returns the two arrays directly — nothing is stored as a tplot var and nothing is written yet.

6. **Write one `.npz`.** Save `{freq, power}` (two 1-D arrays) into a single `.npz` in `<bundle>/data`. `render_tplot` renders **one 2-D matrix per `.npz`**, so for a single line panel store `freq` as the x-axis and `power` as the y values (one curve per file).

7. **Render / inspect.** `render_tplot(input_files=[<psd.npz>], output_file=<bundle>/plots/psd.png, panel_types=["line"], ylog=[true])` for the MCP quick-look. The current renderer supports log-scaled power but not a log-scaled frequency axis; if you need a true log–log science figure, make a tiny local Matplotlib plot from the saved `.npz` with both axes set to log and keep it under `<bundle>/plots/`. Do **not** pass an `xlog` option to `render_tplot`.

8. **Fit / report the slope (the science).** On the log–log PSD pick an inertial-range band, do a log-log linear fit of `power` vs `freq` over that band, and report the slope **with the band used**. Solar-wind magnetic turbulence typically shows **~ -5/3 (Kolmogorov)** in the inertial range, steepening past the ion-kinetic break. For a spectral peak, report the peak frequency instead. **Always state the band** — a slope without its fit band is uninterpretable.

9. **Record.** Drop the slope, fit band, any peak/break frequency, cadence, dataset, and interval into the bundle's `notes/`. Keep arrays on disk; report numbers + the PNG path, not raw spectra.

## Guardrails
- **Single-interval only — no time evolution.** This collapses the whole window into one spectrum. If conditions change across the window, use `dynamic_power_spectrum` (sliding Welch) or `wavelet_transform` instead.
- **Numeric Unix-second timestamps only.** `pwrspc` infers the frequency axis from `time`; ISO strings, `datetime64`, or irregular/non-monotonic timestamps produce a wrong or meaningless `freq` axis. Resample to a uniform grid if needed.
- **Stationarity.** Don't fit a slope across a non-stationary window (shock, sector boundary, mode change) — split the interval first.
- **Always report the fit band** for any reported slope; report the cadence (it bounds the resolvable frequency range).
- Artifact-first: every step writes to the bundle; return paths + compact stats (slope, band, peak), never pasted spectra arrays.
- Enough samples: a meaningful low-frequency end needs a long enough window (many cycles of the lowest frequency of interest); too few rows gives a noise-dominated spectrum.

## Example
PSP `PSP_FLD_L2_MAG_RTN` over a stationary solar-wind interval → derive |B| → convert `time` to Unix seconds → `freq, power = pwrspc(time_unix, Bmag, bin=3)` → write `{freq, power}` to one `.npz` → use `render_tplot` for the MCP quick-look and a tiny local Matplotlib log–log plot when fitting/inspecting a power-law slope. A log-log fit over the inertial band (e.g. 1e-2–1e-1 Hz) returns a slope ≈ -1.67, consistent with Kolmogorov f^-5/3; the slope is reported together with that band so the result is self-documenting.