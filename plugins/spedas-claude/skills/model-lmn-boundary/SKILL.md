---
name: model-lmn-boundary
description: Build a model-based (Shue magnetopause) LMN boundary-normal frame from B + spacecraft position and rotate B into LMN — the model counterpart to data-driven MVA. Use for a magnetopause crossing when you want a boundary normal independent of the field rotation, or to cross-check an MVA normal. Composes existing tools; adds no new tool.
---

# Model-based (Shue magnetopause) LMN boundary frame

Where `boundary-minimum-variance` derives the boundary normal *from the field rotation
itself* (MVA), this skill derives it *from a model magnetopause* (Shue et al.) evaluated
at the spacecraft position. The two are complementary: the model normal does not depend on
the field having a clean planar rotation, so it works where MVA fails (poor eigenvalue
separation) and gives an independent number to validate a trusted MVA normal against.

## When to use
- "Give me an LMN normal that does NOT depend on the field rotation" (e.g. MVA eigenvalue ratio was too low to trust).
- "Rotate B into the model (Shue) magnetopause boundary-normal frame for this crossing."
- "Cross-check my MVA normal against the model magnetopause normal" — agreement strengthens the boundary identification.

## Tool chain (all existing)
`load_data_source` → `browse_data_parameters` → `fetch_data_product` (B in **GSM** + spacecraft **position**)
→ build the (N,3,3) LMN matrix via the `lmn_matrix_make` backend (below)
→ apply it with the **apply-rotation-matrix** skill (`tvector_rotate`) → `render_tplot`,
all inside a `create_spedas_analysis_bundle`. Cross-reference `boundary-minimum-variance`
(data-driven LMN) and `magnetopause-lmn-analysis` (full field+plasma crossing study).

## Backend (VERIFIED contract)
Two pyspedas functions, both operating on **tplot variables** — they STORE results, they do not return arrays:

- `pyspedas.cotrans_tools.lmn_matrix_make.lmn_matrix_make(pos_var_name, mag_var_name, trange=None, hro2=False, newname=None)`
  - **Inputs:** names of two already-stored tplot variables — `pos_var_name` (spacecraft position, GSM, (M,3)) and `mag_var_name` (B in GSM, (N,3)). Evaluates the Shue magnetopause model at the position to get the local normal and builds the L/M/N basis.
  - **Returns:** the **name of a stored tplot variable** holding the **(N,3,3) LMN rotation-matrix stack** — NOT the array. Retrieve the matrix with `get_data(<name>)` → `(times, (N,3,3) array)`.
  - `hro2=True` selects the alternate (Shue 1998 vs. earlier) magnetopause parametrization; `trange` clips the interval.
- `pyspedas.cotrans_tools.gsm2lmn.gsm2lmn(times, Rxyz, Bxyz, swdata=None)`
  - Lower-level: takes raw arrays (`times`, position `Rxyz`, field `Bxyz`, optional solar-wind `swdata`) and returns B rotated into LMN. The matrix path above plus `tvector_rotate` is preferred (consistent with `apply-rotation-matrix`); use `gsm2lmn` only when you already have the arrays in hand.

## Procedure

1. **Bundle & scope the crossing.** `create_spedas_analysis_bundle(...)` for `data/`+`plots/`+`provenance/`. Pick a tight window around the single magnetopause crossing — the model normal is evaluated along the trajectory, so a sane window keeps the spacecraft near the modeled boundary.

2. **Fetch B in GSM + spacecraft position.** Confirm the magnetometer vector and the position variable with `browse_data_parameters`, then `fetch_data_product(source_type=..., dataset_id=..., parameters=[<B GSM vector>], start, stop, output_dir=<bundle>/data)` and likewise for the position. **The model requires GSM** — if B is in another Earth frame, convert with `transform_timeseries_coordinates` (Earth frames only) first. The model is Earth-magnetopause-specific; do not feed heliocentric data.

3. **Load both as tplot vars, then build the LMN matrix.** `store_data('pos', data={'x':pos_time,'y':pos_M x3})` and `store_data('bgsm', data={'x':b_time,'y':b_N x3})`, then `mat_name = lmn_matrix_make('pos','bgsm', newname='lmn_mat')`.
   - **Gotcha (verified):** `lmn_matrix_make` returns the **name of a stored matrix tplot var**, not the matrix. Retrieve it with `mat_times, mat = get_data(mat_name)` → `mat` is the `(N,3,3)` stack. `tnames()` listing the var does NOT mean you have the array — `get_data` is the only way to pull it.

4. **Rotate B into LMN.** Hand `lmn_mat` + the B vector to the **apply-rotation-matrix** skill: `names = tvector_rotate('lmn_mat','bgsm', newname='b_lmn')`, then `get_data(names[0])` → the `(N,3)` B in LMN. (`tvector_rotate` also returns a list of var names, not an array — qslerp-interpolates the matrix onto B's timestamps.) Write `<bundle>/data/b_lmn.csv` with columns `time,B_L,B_M,B_N`.

5. **Reliability / cross-check — do not skip.** The model normal has no internal eigenvalue test, so validate it externally:
   - Run `boundary-minimum-variance` (MVA) on the same B window and **compare the model N to the MVA N** (dot product / angle between them).
   - **Angle ≲ 15–20°** → model and data agree; the boundary normal is robust. **Large angle** → either the model standoff is off (check solar-wind conditions / the Shue parametrization, try `hro2`) or the crossing is not a clean magnetopause; report the disagreement rather than trusting either blindly.
   - As a physical sanity check, in a clean crossing **B_L should rotate while B_N stays small and steady** in the model frame too.

6. **Render & record.** `render_tplot(input_files=[<bundle>/data/b_lmn.csv], output_file=<bundle>/plots/model_lmn.png, panel_types=["line"])` — one 2-D matrix per `.npz`, so one B-LMN panel per file. Report the model normal direction (GSM), the MVA-vs-model angle + verdict, and the B_L/B_N behavior. Save to `notes/`.

## Guardrails
- Artifact-first: return paths + the model normal vector + the model-vs-MVA angle; never paste the rotated B array.
- I/O discipline: `lmn_matrix_make` and `tvector_rotate` STORE tplot vars and return a **name / list of names** — retrieve every result with `get_data`. `tnames()`-listed ≠ `get_data`-retrievable until you actually pull it.
- Frame discipline: the model is **Earth magnetopause, GSM input only**. Convert non-GSM B with `transform_timeseries_coordinates` (Earth frames only); never feed solar-wind/heliocentric data.
- `render_tplot` renders ONE 2-D matrix per `.npz` (one panel per file) — do not expect multiple panels from a single multi-key npz; write separate files.
- Needs the `[analysis]` / cotrans extras (same as `apply-rotation-matrix`).

## Example
PSP/MMS-style magnetopause crossing where MVA returned a low eigenvalue ratio (λ_int/λ_min ≈ 1.4, flagged untrustworthy by `boundary-minimum-variance`): feed B(GSM) + position to `lmn_matrix_make` → `get_data` the (N,3,3) stack → `tvector_rotate` → B in model LMN. The model supplies a normal independent of the (here ambiguous) field rotation, and the model-vs-MVA angle becomes the headline reliability number instead.
