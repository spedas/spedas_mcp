---
name: solar-wind-turbulence-spectrum
description: Compute and inspect the magnetic-field turbulence spectrum of an in-situ solar-wind interval (PSP, Solar Orbiter, Wind, etc.) — fetch B, derive |B|, run a dynamic power spectrum and a wavelet transform, render the spectrograms, and check for a Kolmogorov f^-5/3 inertial range. Composes existing spedas tools; adds no new tool.
---

# Solar-wind magnetic turbulence spectrum

A guided, end-to-end version of the classic IDL SPEDAS "wave/turbulence crib sheet":
take a magnetic-field interval and characterize its fluctuation power vs. frequency.
It chains **existing** unified + analysis tools — there is no dedicated "turbulence"
tool, and there should not be; the value is in the procedure and the interpretation.

## When to use
- "What does the turbulence spectrum look like for PSP on <date>?"
- "Is there an inertial range / does it follow Kolmogorov f^-5/3?"
- "Show me the wave power around perihelion / a switchback interval."

## Tool chain (all already exist)
`plan_spedas_observation` → `load_data_source` → `browse_data_parameters`
→ `fetch_data_product` → `dynamic_power_spectrum` → `wavelet_transform` → `render_tplot`,
wrapped in `create_spedas_analysis_bundle` for provenance.

## Procedure

1. **Plan & bundle.** Call `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)` to lay out `requests/ data/ plots/ provenance/`. Use its `data/` and `plots/` dirs for every artifact below.

2. **Pick the field dataset.** For high-rate work prefer full-cadence magnetometer data:
   - PSP: `PSP_FLD_L2_MAG_RTN` (full cadence) or `PSP_FLD_L2_MAG_RTN_4_SA_PER_CYC`; 1-min `PSP_FLD_L2_MAG_RTN_1MIN` only for overviews.
   - Confirm the exact vector variable with `browse_data_parameters(source_type="cdaweb", dataset_id=...)` (e.g. `psp_fld_l2_mag_RTN`).
   - **Cadence matters:** spectral resolution and the resolvable frequency band scale with the sampling interval. State the cadence you used.

3. **Fetch.** `fetch_data_product(source_type="cdaweb", dataset_id=..., parameters=[<B vector>], start, stop, output_dir=<bundle>/data)`. Keep the interval focused (a turbulence spectrum wants a statistically stationary window — minutes to a few hours, not days). Check the returned `stats` / `quality_checks` for fill/outliers before proceeding.

4. **Derive |B| (and optionally components).** Write a small CSV with a `time` column plus `Bmag = sqrt(BR^2+BT^2+BN^2)` from the fetched file. (A trace-power spectrum can also be built per-component and summed.) This is the scalar channel the spectral tools consume.

5. **Dynamic power spectrum.** `dynamic_power_spectrum(input_file=<Bmag.csv>, output_dir=<bundle>/data, data_col="Bmag")` → sliding-window Welch PSD (`.npz`). Good for the time-evolving picture and a quick PSD slope.

6. **Wavelet transform.** `wavelet_transform(input_file=<Bmag.csv>, output_dir=<bundle>/data, data_col="Bmag", wavename="morl")` → Morlet CWT power (`.npz`). Better time-localization of intermittent structure (switchbacks).
   - **Cadence guard:** confirm the returned `sampling_interval_s` matches your data; a `cadence_warning` means the time axis is irregular and the frequency axis is only approximate — resample to a uniform grid first.

7. **Render.** `render_tplot(input_files=[<dpwr.npz>, <wavelet.npz>], output_file=<bundle>/plots/turbulence.png, panel_types=["spectrogram","spectrogram"], ylog=[true,true], zlog=[true,true])`. Read the PNG back to inspect.

8. **Interpret (the science).**
   - **Inertial range:** on a log–log PSD, look for a power-law band; solar-wind magnetic turbulence typically shows **~f^-5/3 (Kolmogorov)** in the inertial range, often steepening toward **~f^-8/3** past the ion-kinetic break (~0.1–1 Hz near 1 AU, higher closer to the Sun).
   - Fit the slope over the candidate band (log-log linear fit of the time-averaged PSD) and report it with the band used.
   - Flag the **spectral break** frequency if visible; relate it to the ion gyro/inertial scale when ephemeris/plasma context is available.
   - Note **intermittency** (patchy high-power columns in the wavelet panel) — often switchbacks/discontinuities.

9. **Record.** Drop the slope, band, break frequency, cadence, and dataset/interval into the bundle's `notes/`. Keep arrays on disk; report numbers + the PNG path, not raw spectra.

## Guardrails
- Artifact-first: every step writes to the bundle; return paths + compact stats, never pasted spectra.
- A meaningful spectrum needs enough samples for the lowest frequency of interest — a few minutes minimum at high cadence; warn if the window is too short (the spectral tools will reject single-row / all-NaN input).
- Don't over-interpret a slope from a non-stationary window (e.g. spanning a shock or sector boundary); split the interval if conditions change.

## Example (verified)
PSP Encounter 24, 2025-06-17→06-21, `PSP_FLD_L2_MAG_RTN_1MIN` → |B| → dynamic power spectrum + Morlet wavelet → 2-panel spectrogram PNG. Enhanced power bands coincide with high-density streamer crossings near perihelion; the full-cadence MAG (`PSP_FLD_L2_MAG_RTN`) resolves the inertial range and switchback intermittency far better than the 1-min product.
