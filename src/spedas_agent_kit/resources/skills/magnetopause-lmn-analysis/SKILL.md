---
name: magnetopause-lmn-analysis
description: Full magnetopause / bow-shock crossing study — fetch magnetic field + ion plasma moments, find the boundary-normal (LMN) frame with minimum-variance analysis, rotate the field, add spacecraft position context, and render the crossing. The flagship boundary-crossing skill; composes existing tools, adds none. Generalizes docs/examples/mms_magnetopause_workflow.md.
---

# Magnetopause / bow-shock crossing — full LMN study

The canonical SPEDAS boundary-crossing analysis, end to end. Where
`boundary-minimum-variance` does the pure MVA step, this skill is the **complete study**:
it pairs the field rotation with the plasma signature (density/velocity jump) and the
spacecraft position that together *identify* the boundary and confirm the crossing.

## When to use
- "Screen <spacecraft> for a magnetopause / bow-shock crossing near <time>."
- "Characterize this boundary: normal, LMN field, plasma jump, where was the spacecraft?"
- Any single-spacecraft current-sheet / discontinuity study needing field + plasma + geometry.

## Tool chain (all existing)
`search_spedas_data_sources` → `plan_spedas_observation` → `create_spedas_analysis_bundle`
→ `load_data_source` → `browse_data_parameters` → `fetch_data_product` (B **and** ion moments)
→ `analyze_minvar_coordinates` → `transform_timeseries_coordinates` (optional, Earth frames)
→ `get_ephemeris` / `calculate_lshell` (position) → `render_tplot`.

## Procedure

1. **Plan & bundle.** `plan_spedas_observation(science_goal)` to confirm source + a tight window around the crossing; `create_spedas_analysis_bundle(...)` for `data/`+`plots/`+`provenance/`. Keep the window short — one boundary, minutes not hours (the MMS example uses a 2-minute window).

2. **Pick datasets — field AND plasma.** A boundary is identified by *both* the magnetic rotation and the plasma jump:
   - **Magnetic field:** the mission's FGM/MAG vector (confirm the variable with `browse_data_parameters`).
   - **Ion moments:** density, bulk velocity, temperature (e.g. FPI-DIS for MMS, SWE/3DP for Wind, SWEAP for PSP).
   Fetch each with `fetch_data_product(source_type=..., dataset_id=..., parameters=[...], start, stop, output_dir=<bundle>/data)`. Check the returned `stats`/`quality_checks` before trusting the data.

3. **MVA on the field → boundary normal.** `analyze_minvar_coordinates(input_file=<B csv>, vector_cols=[Bx,By,Bz], output_dir=<bundle>/data)`. **Gate on reliability:** require λ_int/λ_min ≳ 5–10 before trusting the normal; report the ratio. (If the ratio is low, the window likely spans more than one structure — re-scope.)

4. **Rotate the field into LMN.** Use the MVA `rotated_file` directly, or for an explicit named-frame product run `transform_timeseries_coordinates` (Earth frames only). In a clean magnetopause crossing, **B_L rotates while B_N stays small and steady** — that's the field signature.

5. **Cross-check the plasma jump.** Over the same window, the ion **density and velocity should step** across the boundary (magnetosheath ↔ magnetosphere): denser/slower inside-sheath vs. tenuous/hotter magnetosphere; a velocity rotation/deflection at the current sheet. The field rotation and the plasma jump should be **co-located in time** — that co-location is what confirms it's a real magnetopause, not just a field wiggle.

6. **Position context.** `get_ephemeris(target=<spacecraft>, time=<crossing>)` for location; near Earth, `calculate_lshell` on the position places the crossing in magnetospheric context (and is sane only within the Earth-dipole domain — don't feed heliocentric coordinates).

7. **Render the crossing.** `render_tplot(input_files=[<LMN B>, <density>, <velocity>], output_file=<bundle>/plots/crossing.png, panel_types=["line","line","line"])`. Read it back: aligned B_L rotation + plasma jump = confirmed crossing.

8. **Verdict & record.** State: boundary type (magnetopause vs. bow shock vs. other), normal direction + eigenvalue ratio, the B_L/B_N behavior, the plasma jump, and the spacecraft position. Save to `notes/`. Distinguish: **magnetopause** = rotational/tangential discontinuity (field rotates, density drops going magnetosphere-ward); **bow shock** = compressive jump (|B|, density, temperature all step up downstream).

## Guardrails
- Artifact-first: paths + the eigenvalue summary + the verdict, never pasted arrays.
- The crossing is *confirmed* by field + plasma agreeing in time — don't call it from B alone.
- MVA reliability ratio is mandatory in the report; a normal without it is not trustworthy.
- Frame discipline: feed B in a meaningful frame (GSE/GSM near Earth); `transform_timeseries_coordinates` is Earth-frames-only.

## Example (real, from the repo)
`docs/examples/mms_magnetopause_workflow.md`: MMS1 near 2015-10-16T13:06–13:08, Earth magnetopause — overview → discover FGM B + FPI ion moments → MVA → LMN rotation → position. This skill generalizes that hand-run workflow to any mission/crossing, with the reliability and field+plasma co-location checks made explicit.
