---
name: apply-rotation-matrix
description: Apply a saved (N,3,3) rotation-matrix stack to a 3-vector time-series — the missing last step that makes generate_fac_matrix, sliding-window MVA, and model-LMN outputs actually usable. Rotates a vector CSV into FAC/LMN/boundary-normal coordinates via pyspedas tvector_rotate (qslerp-interpolated). Composes existing tools; adds no new tool.
---

# Apply a rotation-matrix stack to a vector series

`generate_fac_matrix`, sliding-window `analyze_minvar_coordinates`, and model-based
LMN all **emit** an (N,3,3) rotation-matrix stack — but until now there was no way
to **apply** it to a field/velocity vector within the toolset. This skill closes
that loop: matrix stack + vector series in → rotated vector series out (FAC, LMN,
boundary-normal, or any custom frame).

## When to use
- "Rotate B (or V) into field-aligned coordinates using the FAC matrix from `generate_fac_matrix`."
- "Apply my MVA / LMN rotation to the field time-series."
- Any "I have a rotation matrix and a vector, give me the rotated vector" step.

## Tool chain (all existing)
(`generate_fac_matrix` | `analyze_minvar_coordinates` | model-LMN) → matrix `.npy/.npz`
+ a vector CSV (e.g. from `fetch_data_product`) → small `tvector_rotate` call → rotated CSV → `render_tplot`.

## Backend (verified I/O contract)
`pyspedas.tvector_rotate(mat_var_in, vec_var_in, newname=None)`:
- **Inputs:** two tplot variables — `mat_var_in` an (N,3,3) matrix stack, `vec_var_in` an (M,3) vector series. The matrix stack is **automatically interpolated** (qslerp — quaternion SLERP) onto the vector's timestamps, so the two need not share a time grid.
- **Returns:** a **list of new tplot variable name(s)** (e.g. `['vec_rot']`) — NOT the array. Retrieve the rotated vectors with `get_data(name)`.
- Designed for `fac_matrix_make`/`generate_fac_matrix` output, but works for any rotation stack (MVA, LMN, model).

## Procedure

1. **Have a matrix stack + a vector series.** The matrix comes from `generate_fac_matrix` (FAC, `(N,3,3)` .npy), or sliding-window MVA, or a model-LMN step. The vector is a fetched field/velocity CSV (`time` + 3 components).

2. **Load both as tplot variables** (small local call): `store_data('mat', data={'x':mat_times,'y':mat_NxN3x3})` and `store_data('vec', data={'x':vec_time,'y':vec_M x3})`. If the matrix has no explicit time axis, give it the vector's time grid (no interpolation needed); otherwise let qslerp handle the mismatch.

3. **Rotate:** `names = tvector_rotate('mat','vec', newname='vec_fac')`. Then `d = get_data(names[0])` → the rotated `(M,3)` series.
   - **Gotcha (verified):** the function returns a *list of tplot var names*, not the rotated array — read the data back with `get_data`. (Same stored-output pattern as twavpol; do not expect arrays from the call.)

4. **Write the rotated CSV** to `<bundle>/data/<vec>_rotated.csv` (`time` + the 3 rotated components, named for the target frame, e.g. `B_perp1,B_perp2,B_para` for FAC or `B_L,B_M,B_N` for LMN).

5. **Render / use downstream.** `render_tplot([rotated.csv], panel_types=["line"])`, or feed the field-aligned vector into `wave-polarization` (wave-normal angle is only meaningful in FAC) or `boundary-minimum-variance` follow-ups.

## Guardrails
- Artifact-first: paths + a note on the source frame and target frame; never paste the rotated array.
- Name the output components for their actual frame (perp1/perp2/para for FAC; L/M/N for boundary-normal) so downstream steps and humans aren't guessing.
- The matrix→vector time interpolation is qslerp; if the matrix grid is much coarser than the vector, say so (the rotation is smoothed between matrix samples).
- Needs the `[analysis]` extra.

## Why this is a skill, not a tool
It's the connective tissue between existing tool *outputs* (matrix stacks) and existing data (vector series) — a short, judgment-light procedure. Per the skills-not-tools strategy it adds zero tool surface while making three existing tools (`generate_fac_matrix`, sliding-window MVA, model-LMN) actually actionable.

## Example (verified live)
`tvector_rotate('mat','vec')` with a +90°-about-z matrix stack applied to `[1,0,0]` returned `['vec_rot']` and `get_data` gave `[0,1,0]` — confirming both the rotation correctness and the list-of-tplot-names return contract this skill documents.
