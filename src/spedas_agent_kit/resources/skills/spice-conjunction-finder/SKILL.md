---
name: spice-conjunction-finder
description: Find times when two spacecraft/bodies are close (a conjunction) over an interval — scan ephemerides, compute pairwise separation coarse-then-fine from exported trajectories, apply a distance threshold, and optionally render separation vs time (plotting requires the [analysis] extra).
---

# Multi-spacecraft / body conjunction finder

A guided version of the SPEDAS conjunction crib: locate the times in a window when two
objects (two spacecraft, or a spacecraft and a planet) are within some separation. The
value is the **scan-and-refine procedure with kernel handling** — no single tool finds
conjunctions; this composes the geometry tools with a small local separation calculation
and judgment between steps.

## When to use
- "When were PSP and Solar Orbiter closest in <year>?"
- "Find conjunctions between <A> and <B> under <N> million km."
- "Is spacecraft X near planet Y during this interval?"

## Tool chain (all already exist)
`spedas_overview()` → `manage_data_cache(source_type="spice", action="status")` (availability)
→ `get_ephemeris(target=..., time=..., time_end=..., output_file=...)` for both objects → local separation CSV
(coarse, then refined) → optional `render_tplot` (requires `spedas-agent-kit[analysis]`),
wrapped in `create_spedas_analysis_bundle`.

`compute_distance(...)` is useful as a quick sanity check for aggregate min/max/mean
separation over a sampled interval, but it currently does **not** return the timestamp of
the minimum or a sampled series. Do not use it as the source of candidate-minimum times.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, start, stop)`.

2. **Confirm the SPICE surface and target names.** Start with `spedas_overview()` and `manage_data_cache(source_type="spice", action="status")` to confirm the current unified geometry/data surface. The older separate mission/frame listing tools are not part of the current advertised surface. Use supported target/frame names accepted by `get_ephemeris`/`compute_distance` (unsupported bodies return a structured `unsupported_spice_target` error with alternatives; unsupported frames return a structured frame error). Pick one observer and frame for both trajectories, normally `observer="SUN"` and `frame="ECLIPJ2000"` unless the science case requires otherwise.

3. **Handle kernels deliberately.** Geometry calls gate large kernel downloads. Either pre-load with `manage_data_cache(source_type="spice", action="load", mission=...)`, or pass `allow_kernel_download=true` once you accept the (possibly 100 MB+) download. Do this knowingly — don't let it surprise you mid-scan.

4. **Coarse ephemeris scan.** For each object, call `get_ephemeris(target=<object>, time=<start>, time_end=<stop>, step="1d", frame=<frame>, observer=<observer>, output_file=<bundle>/data/<target>_coarse.csv, allow_kernel_download=<bool>)` (or `step="6h"` for short windows) using the same observer/frame and time grid. `time` is the start time; `time_end` plus `output_file` requests a trajectory CSV. If needed, use `compute_distance(target1=..., target2=..., time_start=..., time_end=..., step=...)` only as an aggregate sanity check that the separation range is plausible.

5. **Compute a local separation table.** Load the two coarse ephemeris CSVs, align rows by timestamp, compute Euclidean separation from the common-frame position columns, and write `<bundle>/data/separation_coarse.csv` with at least `time` and `separation_km`. The minimum rows in this CSV are the candidate conjunction windows.

6. **Refine around candidates.** Around each coarse local minimum (for example ±1–3 coarse steps), rerun `get_ephemeris(target=..., time=<refined_start>, time_end=<refined_stop>, step="1h"/"10m", frame=<frame>, observer=<observer>, output_file=...)` for both objects on the narrowed window. Recompute `<bundle>/data/separation_refined_<candidate>.csv` and use that refined CSV to pin the closest-approach time and distance. This coarse→fine pattern is the whole point: one fine-step scan over a year is wasteful; the coarse pass tells you where to look.

7. **Apply the threshold & report.** Keep candidates under the user's separation cutoff. For each conjunction report: time of closest approach, min separation (km and AU/Re as appropriate), the two ephemeris rows at closest approach, and each object's heliocentric distance/position context (e.g. "both near 0.3 AU").

8. **Optional render.** If `spedas-agent-kit[analysis]` / matplotlib is installed, call `render_tplot(input_files=[<separation_refined.csv>], output_file=<bundle>/plots/separation.png, panel_types=["line"], ylog=true)`. If the `[analysis]` extra is not installed, skip plotting and report the CSV path instead. Mark/annotate the conjunction(s) in `notes/`.

## Guardrails
- Artifact-first: report closest-approach times + distances + CSV/PNG paths, not full sampled tables.
- Coarse-then-fine: never do a fine-step scan over a long interval; localize first.
- Kernel cost: a wide multi-mission scan can need several large kernels — state which you loaded; respect the download gate.
- Frame/observer must be the same for both objects' positions to be comparable.
- Be explicit about optional plotting: `render_tplot` requires the `[analysis]` extra; the geometry/CSV part does not.

## Example (verified primitives)
`compute_distance(PSP, SUN, ...)` returns aggregate min/max/mean km over a sampled window (I used this live: PSP–Sun min 6.86e6 km at the E24 perihelion, matching the instrument's onboard SUN_DIST to ~90 km — a clean cross-check that the geometry tools are trustworthy for conjunction work). For actual conjunction timing, use exported ephemeris CSVs and the local separation table above.
