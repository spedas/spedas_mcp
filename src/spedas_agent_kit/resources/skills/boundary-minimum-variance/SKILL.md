---
name: boundary-minimum-variance
description: Analyze a magnetic boundary crossing (magnetopause, bow shock, current sheet, discontinuity) with minimum-variance analysis (MVA) to find the LMN boundary-normal frame, judge the result's reliability from the eigenvalue ratio, and render the rotated field. Composes existing spedas tools; adds no new tool.
---

# Boundary crossing: minimum-variance (LMN) analysis

A guided version of the IDL SPEDAS minimum-variance crib sheet — the standard way to
find the orientation of a magnetic boundary from single-spacecraft field data and
rotate the field into the boundary-normal (L, M, N) frame.

## When to use
- "Find the magnetopause/bow-shock normal for this crossing."
- "Rotate B into LMN for this current sheet / discontinuity."
- "Is this a well-determined boundary normal?" (the reliability question MVA exists to answer.)

## Tool chain (all already exist)
`load_data_source` → `browse_data_parameters` → `fetch_data_product`
→ `analyze_minvar_coordinates` → (`render_tplot`), in a `create_spedas_analysis_bundle`.

## Procedure

1. **Bundle & scope the crossing.** `create_spedas_analysis_bundle(...)`. Pick a window **tight around the single boundary crossing** — MVA assumes one planar structure; a window spanning two boundaries or lots of turbulence gives a meaningless normal.

2. **Fetch the field.** Choose a magnetometer dataset appropriate to the mission/region and confirm the vector variable with `browse_data_parameters`. Then `fetch_data_product(source_type=..., dataset_id=..., parameters=[<B vector>], start, stop, output_dir=<bundle>/data)`. Use the highest cadence that keeps the crossing well-sampled.

3. **Run MVA.** `analyze_minvar_coordinates(input_file=<B csv>, output_dir=<bundle>/data, vector_cols=[<Bx>,<By>,<Bz>], time_col="time")`. It returns:
   - `eigenvalues` (λ_max ≥ λ_int ≥ λ_min),
   - `eigenvectors` (maximum=L, intermediate=M, minimum=N),
   - `normal_vector` (= the minimum-variance eigenvector N),
   - `intermediate_to_min_ratio` (λ_int / λ_min),
   - and a `rotated_file` with B in LMN.

4. **Judge reliability — do not skip this.** The boundary normal is only trustworthy when the **minimum eigenvalue is well-separated** from the intermediate one:
   - **λ_int / λ_min ≳ 5–10** → well-determined normal.
   - **ratio ≲ 2–3** → the normal is poorly constrained; report it as unreliable and consider a different window, a longer/shorter interval, or multi-spacecraft timing instead.
   - Always report the ratio alongside the normal so the result is self-documenting.

5. **Render the rotated field.** `render_tplot(input_files=[<rotated_file>], output_file=<bundle>/plots/lmn.png, panel_types=["line"])`. In a clean crossing, B_N is ~constant (∇·B=0 across a planar boundary) while B_L rotates — that pattern is the visual confirmation MVA worked.

6. **Interpret & record.** Report the normal direction (in the input frame), the eigenvalue ratio + reliability verdict, and the B_L/B_M/B_N behavior. For a magnetopause, the rotation of B_L and small steady B_N indicate a tangential/rotational discontinuity; large fluctuating B_N suggests a poorly chosen window. Save to `notes/`.

## Guardrails
- Artifact-first: paths + the eigenvalue summary, not pasted rotated arrays.
- MVA is single-spacecraft and assumes one planar, time-stationary boundary. State the window and the eigenvalue ratio so a reader can judge validity.
- Coordinate frame: feed B in a physically meaningful frame (e.g. GSE/GSM near Earth, RTN/SC in the solar wind); the normal is returned in that same frame. (Note: `transform_timeseries_coordinates` handles Earth frames only — see its own constraints before converting.)

## Example
A magnetopause crossing window → MVA → normal vector with λ_int/λ_min reported. When I ran `analyze_minvar_coordinates` on a broad PSP MAG interval it returned a ratio ≈ 1.4 — correctly flagged as **not** a clean single boundary, exactly the case where the procedure's reliability check stops you from trusting a garbage normal.
