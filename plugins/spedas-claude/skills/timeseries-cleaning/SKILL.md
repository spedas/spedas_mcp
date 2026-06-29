---
name: timeseries-cleaning
description: Pre-analysis conditioning of a fetched vector/scalar time-series — despike, de-flag fill values, smooth, subtract a background average, and interpolate gaps onto a uniform grid before spectra/MVA/moments. Use as the first step feeding the turbulence, MVA/LMN, or polarization skills, especially for messy or irregular-cadence data. Composes existing tools; adds no new tool.
---

# Time-series cleaning (the tplot-math hygiene crib)

The IDL-SPEDAS `tplot_math` pre-analysis ritual: take a raw, messy, possibly
irregular-cadence series and condition it into something the spectral / minimum-variance /
moment tools can trust. This is the **first** step in front of
`solar-wind-turbulence-spectrum`, `boundary-minimum-variance` / `magnetopause-lmn-analysis`,
and `wave-polarization` — never feed those raw fill-value-laden, gappy data. There is no
dedicated "clean" MCP tool; the value is the ordered chain and recording every step for
reproducibility.

## When to use
- "Clean up this B/V series before I run a spectrum / MVA / polarization."
- "There are spikes / fill values / gaps / NaNs in the data — regularize it."
- "Put this irregular-cadence series on a uniform time grid."
- Any series with data dropouts, instrument spikes, sentinel fill values, or non-uniform cadence.

Do **not** over-clean: aggressive smoothing destroys the high-frequency power a spectrum
needs, and background subtraction changes what MVA/moments see. Clean the minimum required.

## Tool chain (all existing)
`load_data_source` → `browse_data_parameters` → `fetch_data_product` (raw series)
→ load the fetched array as a tplot variable → chain the pyspedas `tplot_math` ops
(`time_clip` → `tdeflag` → `clean_spikes` → `tsmooth` → `subtract_average` → `tinterpol`)
→ `get_data` the cleaned var → write a cleaned CSV/NPZ artifact → feed the downstream skill,
all wrapped in a `create_spedas_analysis_bundle`. Use `render_tplot` for a before/after look.

## Backend (verified output contract)
All of these are pyspedas top-level functions that operate on tplot variable **names**,
store a **new** tplot variable (via `newname=` or a `suffix`), and **return `None`** — they
do NOT return arrays. Retrieve the result with `pytplot.get_data(<name>)`.

- `pyspedas.tdeflag(names, flag=None, method='remove_nan', fillval=...)` — replace/remove
  fill values and NaNs. `method='remove_nan'` drops flagged rows (changes the time base);
  other methods (e.g. interpolate/repeat) keep length. Set `flag`/`fillval` to the dataset's
  sentinel (e.g. `-1e31`) when it isn't already NaN.
- `pyspedas.clean_spikes(names, nsmooth=10, thresh=0.3, sub_avg=False, ...)` — despike by
  comparing to an `nsmooth`-point smooth; points deviating beyond `thresh` are removed.
- `pyspedas.tsmooth(names, width=10, median=...)` — boxcar (or median, if `median` set)
  smooth over `width` points.
- `pyspedas.subtract_average(names, median=...)` — subtract the interval mean (or median)
  to remove a DC background.
- `pyspedas.tinterpol(names, interp_to, ...)` — interpolate `names` onto the time base of
  the `interp_to` variable; build a uniform-grid dummy var first to regularize cadence.
- `pyspedas.avg_data(...)` — downsample by time-bin averaging when you want a coarser uniform cadence.
- `pyspedas.time_clip(names, trange)` — trim to the analysis window.

**I/O discipline (hard-won):** these store and return `None`. `pytplot.tnames()` listing a
name does NOT mean it is retrievable as you expect — always `get_data` and verify the shape.
`method='remove_nan'` and `clean_spikes` removal change the row count and the time axis, so
the cleaned series is generally NOT row-aligned with the raw one — re-`get_data` the time
column after every length-changing step.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)`. Write every artifact (raw, intermediate, cleaned) under its `data/` and the before/after PNG under `plots/`.

2. **Fetch raw.** `fetch_data_product(source_type=..., dataset_id=..., parameters=[<var>], start, stop, output_dir=<bundle>/data)`. Inspect the returned `stats` / `quality_checks` for the fill value, NaN fraction, spike count, and cadence regularity — these decide which steps below you actually need.

3. **Load as a tplot variable.** Read the fetched file and `pytplot.store_data(name, data={'x': time, 'y': values})` so the `tplot_math` ops have a named target to operate on.

4. **Clip to the window.** `time_clip(name, [start, stop])` so background averages and smoothing are computed over the interval of interest, not stray padding.

5. **De-flag fill values.** `tdeflag(name, flag=<sentinel>, method=..., newname=...)`. Use `method='remove_nan'` to drop dropouts (note: time base changes) or an interpolating method to keep length. Record the sentinel used.

6. **Despike.** `clean_spikes(name, nsmooth=10, thresh=0.3, newname=...)` to remove instrument spikes. Verify with a before/after that you removed spikes, not real structure.

7. **(Optional) smooth — sparingly.** `tsmooth(name, width=..., newname=...)` only if downstream needs it. **Do NOT smooth before a spectrum** (it suppresses high-frequency power and biases the slope). Smoothing is fine ahead of a coarse overview or a slowly-varying background.

8. **(Optional) subtract background.** `subtract_average(name, newname=...)` to remove the DC component for MVA / wave work. Skip this if the downstream tool needs absolute values (e.g. |B|, moments).

9. **Regularize cadence.** If the cadence is irregular, build a uniform-grid dummy variable spanning the interval and `tinterpol(name, uniform_grid_var, newname=...)`, or `avg_data` to a target bin. The turbulence and polarization tools assume a uniform time axis — a `cadence_warning` downstream means this step was skipped.

10. **Retrieve and persist.** `d = pytplot.get_data(<cleaned name>)`; verify `d.times` and `d.y` shapes (length may differ from raw after de-flag/despike). Write a cleaned CSV (`time` + value columns) and/or `.npz` to `<bundle>/data` — this is what the downstream skill consumes.

11. **Before/after check.** `render_tplot(input_files=[<raw.npz>, <cleaned.npz>], output_file=<bundle>/plots/clean_before_after.png, ...)` (one 2-D matrix per `.npz`, one panel per file). Read the PNG back to confirm you fixed the defect without erasing signal.

12. **Record every step.** Cleaning changes the data — log the ordered operation list with all parameters (sentinel, `nsmooth`, `thresh`, smoothing `width`, average type, interpolation target/cadence) and the raw→cleaned row counts into `notes/`. Reproducibility hinges on this.

## Guardrails
- Artifact-first: write raw, intermediate, and cleaned series to the bundle; return paths + compact stats (NaN fraction removed, spikes removed, in/out row counts, final cadence), never pasted arrays.
- **Cleaning changes the data.** Record every operation and its parameters in `notes/` so the pipeline is reproducible and the downstream result is interpretable.
- **Don't oversmooth before a spectrum** — `tsmooth` suppresses high-frequency power and flattens/steepens the inferred slope. Despike and de-flag, but leave the fluctuations intact.
- These backends return `None` and store tplot vars; always `get_data` and check shapes. `tnames()`-listed is not the same as get_data-retrievable.
- De-flag (`remove_nan`) and despike change the row count and time axis — re-fetch the time column after each length-changing step; don't assume row alignment with the raw series.
- Subtract the background only when the downstream tool wants fluctuations (MVA/polarization), not when it needs absolute magnitude (|B|, moments).

## Example
PSP `PSP_FLD_L2_MAG_RTN` over a switchback interval with sparse `-1e31` fill and a few
saturation spikes: fetch raw → `store_data` → `time_clip` → `tdeflag(flag=-1e31, method='remove_nan')`
→ `clean_spikes(nsmooth=10, thresh=0.3)` → `tinterpol` onto a uniform 0.87 s grid →
`get_data` → write `mag_rtn_cleaned.csv`. `notes/` records the ordered steps and that
de-flag+despike dropped 412 of 41,280 rows; the cleaned uniform-cadence CSV then feeds
`solar-wind-turbulence-spectrum` without a `cadence_warning`. Smoothing was deliberately
skipped to preserve the inertial-range power.
