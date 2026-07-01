---
name: tplot-data-lifecycle
description: Manage PySPEDAS/tplot variable state as an artifact-first lifecycle from load to inspect, derive, plot, export, and cleanup while avoiding raw-array chat output and name collisions.
---

# tplot data lifecycle

Use this skill when a workflow mentions tplot variables, PyTplot, IDL SPEDAS `STORE_DATA` / `GET_DATA`, PySPEDAS `store_data` / `get_data`, plotting, export, or variable cleanup. The goal is to keep global-ish tplot state understandable and reproducible inside an Agent Kit run.

## MCP/default-surface boundary

When documenting tplot runtime routes, use the structured marker `external_runtime_route.not_an_mcp_tool: true`. `tplot_names`, `store_data`, `get_data`, `del_data`, `tplot`, `tplotxy`, `cdf_to_tplot`, `tplot_save`, and related routines are PySPEDAS/PyTplot runtime routines, not default Agent Kit MCP tools. Treat them as `not_an_mcp_tool` unless a current Agent Kit tool explicitly exposes the action. MCP clients should ask Agent Kit to plan/load/export/plot through existing tools and should receive compact metadata plus artifact paths.

## Lifecycle model

1. **Load or create variables.** Use a bounded plan and run-scoped `prefix` / `suffix` so variable names reveal mission, product, and interval.
2. **List and inspect.** Record names, shapes, time span, cadence, coordinate metadata, units, support-data status, and fill values. Do not paste raw arrays.
3. **Normalize metadata.** Preserve or set coordinate systems and units before rotations, LMN/MVA, spectra, or particle calculations.
4. **Derive variables.** Copy/rename before destructive operations; name derived products with method and frame, e.g. `mms1_fgm_gsm_lmn_batch1`.
5. **Plot/export.** Figures, CDF/CSV/JSON summaries, and notebook snippets are artifacts. Return paths, hashes, variable lists, and compact stats.
6. **Cleanup or checkpoint.** Delete scratch variables only after exported artifacts and `provenance/run.json` capture what was done.

## Inspection checklist

For each important tplot variable, capture:

- Variable name and source product.
- Time range after clipping and number of samples.
- Data shape and component labels.
- Units and coordinate frame (`GSE`, `GSM`, `SM`, `FAC`, `LMN`, `RTN`, or unknown).
- Whether it is original, support data, or derived.
- Fill-value/de-spike/interpolation/smoothing status.
- Artifact path for any plot or exported table.

## Name-collision and state hygiene

- Use `suffix`/`prefix` at load time when loading repeated intervals or multiple probes.
- Never assume a variable name is unique across a long agent session; list first.
- Prefer copy/derive names over in-place mutation for science products.
- Use bundle-local export paths instead of relying on lingering interactive tplot state.
- For CI or review, prefer `notplot`/metadata summaries and no-update/cache-only validation.

## Plotting and export discipline

A plot request should produce a file, not a chat-sized data dump. Ask the backend/MCP layer for a figure or export artifact and report:

- Path and file type.
- Variables plotted/exported.
- Plot options that affect interpretation: y/z log scale, spectrogram, legend names, highlights, limits, coordinate frame.
- Any dropped/fill/interpolated data and whether the interval was clipped.

## Downstream skill handoff

Use this lifecycle before calling focused science skills:

- `timeseries-cleaning` for despiking, gap handling, smoothing, and interpolation.
- `coordinate-frame-tour`, `apply-rotation-matrix`, `boundary-minimum-variance`, or `magnetopause-lmn-analysis` when coordinate/frame assumptions matter.
- `power-spectral-density`, `wave-polarization`, or `spectral-cross-coherence` after cadence and gap checks.
- `particle-velocity-slice` and `pitch-angle-distribution` only after particle product shape, units, and calibration caveats are explicit.
