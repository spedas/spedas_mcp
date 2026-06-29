---
name: neutral-sheet-distance
description: Compute a spacecraft's distance to the magnetotail neutral/current sheet (and whether it is north or south of it) from a GSM position time-series, using PySPEDAS neutral-sheet models — for plasma-sheet / current-sheet crossing studies in the tail. Use when asked "how far is the s/c from the neutral sheet?", "is it north or south of the current sheet?", or "did it cross the neutral sheet?". Composes existing tools; adds no new tool.
---

# Neutral-sheet distance (magnetotail current-sheet geometry)

Given a spacecraft GSM position time-series in the magnetotail, compute the
**signed distance from the spacecraft to the model neutral sheet along GSM-z**
(or the GSM-z coordinate of the sheet itself), pick an empirical neutral-sheet
model, and use the sign of the result to decide whether the spacecraft is north
or south of the current sheet. This is the geometry context for plasma-sheet /
current-sheet crossing studies (THEMIS, MMS, Cluster, Geotail, etc.). There is
no dedicated "neutral sheet" MCP tool and there should not be — the value is the
position fetch + model call + interpretation procedure.

## When to use
- "How far is THEMIS/MMS from the neutral sheet on <date>?"
- "Is the spacecraft north or south of the tail current sheet?"
- "Did the spacecraft cross the neutral sheet during this interval?" (sign change of sc-to-NS distance)
- Providing current-sheet geometry context for a tail reconnection / flapping / dipolarization study.

Do **not** use this on the dayside, far outside the model's near-tail validity
region, or for a non-tail orbit — the empirical fits are only meaningful in the
magnetotail (roughly the nightside, within ~ -30 Re < X_GSM < a few Re).

## Tool chain (all already exist)
`plan_spedas_observation` → `create_spedas_analysis_bundle` →
(`get_ephemeris` **or** `load_data_source` / `browse_data_parameters` /
`fetch_data_product`) to obtain the **GSM position** →
optional `transform_coordinates` / `transform_timeseries_coordinates` to land in GSM →
a reproducible Python note in the bundle that calls the PySPEDAS neutral-sheet
backend → export compact CSV/NPZ → `render_tplot` for the distance panel. Wrap
everything in `create_spedas_analysis_bundle` for provenance.

## Backend (VERIFIED contract)

Top-level attribute `pyspedas.neutral_sheet` (real module
`pyspedas.analysis.neutral_sheet`). **Verified signature** (PySPEDAS in this repo's venv):

```
neutral_sheet(time, pos, kp=None, model='themis', mlt=None,
              in_coord='gsm', pdyn=2.0, byimf=0.0, bzimf=0.0, sc2NS=False)
```

- `time` — array of doubles (unix seconds; build with `pyspedas.tplot_tools.time_double`).
- `pos` — `(N,3)` position array, **GSM by default** (`in_coord='gsm'`); km or Re per the model (THEMIS/most models expect Re — confirm units before calling and re-check the function source in-skill).
- `model` — one of `'sm'`, `'themis'` (default), `'aen'`, `'den'`, `'fairfield'`, `'den_fairfield'`, `'lopez'`, `'tag14'`. Some models need extra inputs (`kp`, `mlt`, `pdyn`, `byimf`, `bzimf`); each model uses only a subset.
- `sc2NS` — **the key flag.** `False` (default) returns the GSM-z coordinate **of the neutral sheet** at the spacecraft's (X,Y). `True` returns the **signed distance from the spacecraft to the neutral sheet along z** (i.e. `z_sc - z_NS`-style). For "how far is the s/c from the sheet / is it north or south", use `sc2NS=True`.
- **Returns** a plain NumPy array `distance2NS`, length `N` — **NOT a tplot variable, not a bool, not a list of names.** You must capture the return value directly; there is nothing to retrieve with `get_data` afterward (the function does not store a tplot variable). To plot it, build your own tplot variable / CSV from this array.

Always re-check the live signature in-skill (`inspect.signature(pyspedas.neutral_sheet)`) and read the function source for the chosen model's required args and expected position units before trusting numbers.

## Procedure

1. **Plan & bundle.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)` → `requests/ data/ plots/ provenance/`. Use its `data/` and `plots/` dirs for every artifact below.

2. **Get the GSM position time-series.** Two paths:
   - **Ephemeris route:** `get_ephemeris(target=<spacecraft>, time=<start>, time_end=<stop>, step="1h", frame="GSM", observer="EARTH", output_file=<bundle>/data/<spacecraft>_gsm_ephemeris.csv, allow_kernel_download=<bool>)` to compute a trajectory CSV directly. `time_end` requires `output_file`; there is no `start`/`stop`/`output_dir` signature for this MCP tool.
   - **Data route:** `load_data_source` → `browse_data_parameters` → `fetch_data_product(source_type="cdaweb", dataset_id=..., parameters=[<position vector>], start, stop, output_dir=<bundle>/data)` for a mission position product (e.g. THEMIS/MMS state).
   - Either way, end with an `(N,3)` GSM position and a matching time array on disk. Inspect the returned `stats`/`quality_checks` for fill/NaNs first.

3. **Confirm frame & units.** Ensure the position is **GSM** — if it is GSE/SM/GEI, run `transform_timeseries_coordinates` (or `transform_coordinates`) to GSM first. Then check the units the chosen model expects (Re vs km) by reading the backend source; convert if needed. Record the frame and unit decision in `provenance/`.

4. **Validity gate (reliability check).** Verify the interval is in the model's near-tail validity region: nightside, `X_GSM` negative and within the model's fitted range (typically out to ~ -30 Re for THEMIS-class fits). If samples fall on the dayside or far down-tail, flag them and either drop or report them as out-of-region — the empirical fit is extrapolating there.

5. **Run the backend from one reproducible script.** In `notes/run_neutral_sheet.py`: load time + GSM position from the bundle artifact, `time_double` the times, and call `pyspedas.neutral_sheet(time, pos, model=<chosen>, in_coord='gsm', sc2NS=True, ...)` with any model-required extras (`kp`, `pdyn`, `byimf`, `bzimf`, `mlt`). **Capture the returned array directly** — do not look for a tplot var. Save the array (and the model name) to `<bundle>/data/sc_to_ns_distance.npz` / `.csv` alongside the time axis.

6. **Derive north/south & crossings.** From the `sc2NS=True` array: `sign > 0` ⇒ spacecraft on one side (state which, per the model's sign convention you verified), `sign < 0` ⇒ the other; **sign changes = neutral-sheet crossings.** Compute and report the crossing times, the min |distance| (closest approach), and the fraction of the interval spent on each side. If you also called `sc2NS=False`, you have the sheet's z-coordinate for plotting against the spacecraft's z.

7. **Render.** Build a single 2-D matrix per `.npz` (one panel per file — `render_tplot` renders one matrix per file, not multiple panels from one multi-key npz). Render the sc-to-NS distance as a line panel: `render_tplot(input_files=[<sc_to_ns_distance.npz>], output_file=<bundle>/plots/neutral_sheet_distance.png, panel_types=["line"])`. Read the PNG back to confirm.

8. **Record.** Drop the **model used**, its validity caveat, the sign convention, crossing times, closest approach, and the dataset/interval into the bundle's `notes/`. Keep arrays on disk; return paths + compact stats, never pasted arrays.

## Guardrails
- Artifact-first: every step writes to the bundle; return file paths + compact stats (min/max |distance|, crossing count/times, % north vs south), never pasted arrays.
- **I/O discipline:** `neutral_sheet` returns a NumPy array — capture it from the call. It does **not** create a tplot variable, so `tnames()`/`get_data` will not find a result; build your own tplot var / CSV from the returned array for `render_tplot`.
- **Frame & units are load-bearing:** wrong frame (GSE↔GSM) or wrong units (km↔Re) silently produces plausible-but-wrong distances. Transform to GSM and verify the unit convention before calling.
- **State the model.** Each empirical model (`sm`, `themis`, `aen`, `den`, `fairfield`, `den_fairfield`, `lopez`, `tag14`) has its own validity region, required inputs, and sign/offset convention. Always report which model produced the numbers and its near-tail validity limits; don't compare distances across models without re-deriving.
- Don't apply this on the dayside or far outside the fitted tail region — flag out-of-region samples rather than reporting extrapolated distances as fact.

## Example
THEMIS-A (THA) in the magnetotail, a nightside interval: `get_ephemeris(target="THEMIS-A", time=<start>, time_end=<stop>, frame="GSM", observer="EARTH", output_file="data/tha_gsm_ephemeris.csv")` → GSM position (convert units to Re if the CSV is km) → `pyspedas.neutral_sheet(time, pos, model='themis', in_coord='gsm', sc2NS=True)` → 1-D signed sc-to-NS distance array → save to `data/sc_to_ns_distance.npz` → `render_tplot([...], panel_types=["line"])`. A sign change near the center of the interval marks a neutral-sheet crossing; report the crossing time, the ~0-Re closest approach, the THEMIS model and its near-tail validity caveat, and the PNG path — not the raw array.
