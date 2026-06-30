---
name: multi-spacecraft-gradients
description: Four-spacecraft magnetic-gradient workflow for curlometer current density, linear gradient/curl/divergence and field-line curvature, and FOTE magnetic-null finding. Reuses existing data/coordinate/artifact tools plus PySPEDAS backends; adds no MCP tools. Requires four spacecraft magnetic-field vectors and positions in a common GSE timeline/frame, and reports tetrahedron-quality caveats before interpreting results.
---

# Multi-spacecraft gradients: curlometer, lingradest, magnetic nulls

Use this for IDL-SPEDAS-style four-spacecraft science: current density from the
curlometer, linear magnetic gradients/divergence/curl/curvature, and magnetic
null searches. It is written for MMS but the math is the generic Chanteur / FOTE
four-spacecraft tetrahedron method when the inputs are four simultaneous
spacecraft positions and magnetic-field vectors.

## When to use

- "Compute current density / curlometer J from MMS1-4 FGM."
- "Estimate div B, curl B, gradient tensor, or field-line curvature from a tetrahedron."
- "Find / classify magnetic nulls from four spacecraft around this reconnection interval."
- Any Cluster/MMS-like four-point magnetic-field analysis with positions in the same frame.

Do **not** use this for a single spacecraft, for mixed coordinate frames, or when the
spacecraft form a nearly flat/linear tetrahedron unless the result is explicitly
reported as low confidence.

## Batch 008 magnetotail guardrail

Cluster, Geotail, and THEMIS magnetotail/boundary overview plots are not enough
for this skill. Batch 008 found useful Cluster C1 CIS proxies but an empty
Cluster FGM route; label those cases `single_spacecraft_cis` and
`fgm_route_empty`, not four-spacecraft gradients. Do not run or cite curlometer,
linear-gradient, timing-normal, KH-vortex, shock-normal, or reconnection-rate
results until all four magnetic-field vectors and all four positions are loaded
in one frame/cadence with provenance. Geotail route scouts labelled
`not_paper_exact` / `metadata_unresolved` are discovery evidence, not validation
for gradient tooling.

## Tool chain (all existing; no new MCP tools)

`search_spedas_data_sources` → `plan_spedas_observation` →
`create_spedas_analysis_bundle` → `load_data_source` / `browse_data_parameters` →
`fetch_data_product` for all four B vectors and all four positions → optional
`transform_timeseries_coordinates` so **B and R are GSE** → write a reproducible
Python note/script in the bundle that calls the PySPEDAS backends → export compact
CSV/NPZ/PNG artifacts → `render_tplot` for plots.

If the backend is executed outside MCP, keep it inside the analysis bundle (for
example `notes/run_multispacecraft_gradients.py`) and record package versions,
input artifact paths, variable names, coordinate frames, and output file hashes in
`provenance/`.

## Required inputs

1. Four magnetic-field vectors, one per spacecraft, with identical or interpolatable
   cadence. Use GSE components, typically nT.
2. Four spacecraft position vectors on the same time base or safely interpolatable
   to the field timeline. Use GSE positions, typically km.
3. A short interval over one structure. Minutes are usually better than hours.
4. A tetrahedron-quality note: report spacecraft separation scale and whether the
   tetrahedron is compact enough for a linear-gradient approximation. If formal
   quality factors are not computed, state that limitation and avoid overclaiming.

## Backend map and output shapes to verify

These are the PySPEDAS routines to call after the MCP fetch/alignment steps. The
paths/signatures were checked against the optional `spedas-agent-kit[analysis]` PySPEDAS
backend; keep these exact module paths in scripts so import failures are obvious.

| Quantity | Backend | Inputs | Expected return / created variables |
|---|---|---|---|
| Curlometer current density and reliability proxies | `pyspedas.projects.mms.mms_curl(fields=[...4 tplot vars...], positions=[...4 tplot vars...], suffix="...")` | Four GSE B tplot variables + four GSE position tplot variables | Returns a list of created tplot variable base names: `baryb`, `curlB`, `divB`, `jtotal`, `jpar`, `jperp`, `alpha`, `alphaparallel`. `jtotal` is a 3-column current density timeseries in A/m²; `divB` and `curlB` are reliability/context checks. |
| Linear gradient / curl / divergence / curvature | `pyspedas.lingradest(Bx1, Bx2, Bx3, Bx4, By1, ..., Bz4, R1, R2, R3, R4, scale_factor=1000.0)` | Component arrays on a common time base plus four `(N,3)` position arrays | Returns a `dict` containing `Rbary`, `dR1`-`dR4`, `Bxbc`, `Bybc`, `Bzbc`, `Bbc`, `LGBx`, `LGBy`, `LGBz`, `LCxB`, `LCyB`, `LCzB`, `LD`, `curv_x_B`, `curv_y_B`, `curv_z_B`, `RcurvB`. |
| FOTE magnetic-null search | `pyspedas.find_magnetic_nulls_fote(fields=[...], positions=[...], smooth_fields=True, smooth_npts=10, smooth_median=True, scale_factor=1.0)` | Four B + four position tplot variables | Returns created tplot variables: `null_pos`, `null_bary_dist`, `null_bary_dist_types`, `null_sc_distances`, `null_fom`, `null_typecode`, `max_reconstruction_error`. Interpret `null_fom` (`eta`, `xi`) as lower-is-better confidence; values below about 0.4 are a useful first-pass threshold. |
| Null topology labels | `pyspedas.classify_null_type(lambdas_in)` | Three complex Jacobian eigenvalues | Returns integer type code: 0 unknown, 1 X, 2 O, 3 A, 4 B, 5 A_s, 6 B_s, 7-10 degenerate X/O variants. |

## Procedure

1. **Plan and bundle.** Use `plan_spedas_observation` or source search to identify
   the four-spacecraft mission/product and a tight interval. Create a bundle before
   data fetches.
2. **Fetch all eight vectors.** Fetch B and position for spacecraft 1-4. For MMS,
   FGM products can include both `*_fgm_b_gse_*` and `*_fgm_r_gse_*`; confirm exact
   parameter names with `browse_data_parameters`.
3. **Frame and cadence discipline.** Confirm B and R are both GSE. Interpolate all
   inputs to one master timeline (usually spacecraft 1 B) and drop NaNs/flagged
   samples before backend calls. Record interpolation choices in `provenance/`.
4. **Run the three backends from one reproducible script.** Populate tplot variables
   (for `mms_curl` / FOTE) and array inputs (for `lingradest`) from fetched artifacts.
   Save only files and compact summaries: CSV/NPZ for `jtotal`, `divB`, `curlB`,
   `LC*B`, `LD`, curvature, null position/distance/FOM/typecode.
5. **Quality gates.** Treat `|divB|/|curlB|`, null `eta/xi`, reconstruction error,
   tetrahedron geometry, and sensitivity to smoothing/interpolation as part of the
   result, not optional metadata. If quality is poor, report "computed but not
   physically reliable".
6. **Plot and summarize.** Render J, div/curl diagnostics, barycenter B, and null
   distance/FOM/typecode as panels. In the final answer include paths, backend
   versions, coordinate frame, time interval, quality caveats, and the physical
   interpretation.

## Interpretation guardrails

- Curlometer assumes a linear magnetic field inside the tetrahedron. It can fail
  near sharp structures smaller than the spacecraft separation or with bad geometry.
- Magnetic null routines will usually find a mathematical null from a first-order
  expansion; only call it a physical null when it is close to the barycenter,
  `eta/xi` are low, reconstruction error is small, and the result is stable under
  reasonable smoothing choices.
- Never mix GSE/GSM/DSL/spacecraft frames. Transform first or stop.
- Do not paste arrays in chat. Return artifact paths and compact min/max/shape/time
  summaries only.
