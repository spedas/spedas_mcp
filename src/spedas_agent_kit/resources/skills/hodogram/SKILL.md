---
name: hodogram
description: Plot a magnetic-field (or any vector) hodogram — one component against another as a parametric x-y curve — to read off wave polarization and rotation sense, classically in the minimum-variance (LMN) frame. Use for "is this a linear/circular/elliptical fluctuation, and which way does B rotate across this boundary?" Composes existing tools; adds no new tool.
---

# Hodogram: component-vs-component polarization plot

A hodogram plots one vector component against another (e.g. B in the maximum- vs
intermediate-variance direction) as a parametric curve traced over time. Its *shape*
reveals polarization — a line (linear), a circle (circular), an ellipse (elliptical) —
and the *direction* the curve is traced gives the rotation sense. It is the standard
companion to minimum-variance analysis (MVA) for classifying waves and characterizing
boundary rotations (e.g. magnetopause/current-sheet field rotation). This skill composes
existing tools — `render_tplot` gained scatter/x-y panels (#120/#123), so no new tool is added.

## When to use
- "Plot the hodogram of B for this interval" / "is this fluctuation linear, circular, or elliptical?"
- "Which way does B rotate across this boundary?" (rotation sense / handedness).
- The polarization companion to `boundary-minimum-variance` — view B_max vs B_int in the LMN frame.

## Tool chain (all already exist)
`create_spedas_analysis_bundle` → `fetch_data_product` (B vector) →
(`analyze_minvar_coordinates` to get the LMN/variance frame, recommended) →
`transform_timeseries_coordinates` **or** the MVA-rotated series → write one `.npz`
matrix of the two components → `render_tplot(panel_types=["scatter"], x_component, y_component)`.

## Backend (VERIFIED contract)
The hodogram is produced by **`render_tplot`'s scatter/x-y panel** (added in #123):

- `render_tplot(input_files=[npz], output_file=..., panel_types=["scatter"], x_component=[i], y_component=[j], ...)`
  renders **one 2-D matrix per `.npz`** as a parametric x-y plot of column `i` vs column `j`
  (defaults 0 vs 1). `panel_types` may also use `"xy"`; it overrides the per-file default.
  `x_component`/`y_component` are **lists of column indices**, one per input file. Mismatched
  lengths return a structured `invalid_argument` error (validated before any drawing).
- **One matrix per file:** to plot B_max-vs-B_int and B_max-vs-B_min as two panels, write
  **two `.npz` inputs** (or pass the same file twice with different `x_component`/`y_component`),
  not one multi-key file expecting a multi-panel stack.
- Input `.npz` holds the vector as an N×k `data` matrix (component columns) and a `time` axis;
  the scatter panel ignores `time` for positioning but uses the row order to trace the curve.
- **Verified live:** a 2-column circular series rendered with
  `panel_types=["scatter"], x_component=[0], y_component=[1]` returns `status: success` and writes a PNG.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(...)`; write artifacts under `<bundle>/data`, plots under `<bundle>/plots`.
2. **Fetch B.** `fetch_data_product(... parameters=[<B vector>], output_dir=<bundle>/data)` over a clean, stationary interval (one boundary crossing, or one wave packet).
3. **Get the right frame (recommended).** A hodogram is most interpretable in the **variance (LMN) frame**: run `analyze_minvar_coordinates` to obtain the eigenvectors and the rotated B series, OR `transform_timeseries_coordinates` into a physically chosen frame. Plotting raw instrument-frame components is allowed but harder to read. **Check the MVA eigenvalue ratio (λ2/λ3 ≫ 1)** — if the minimum-variance direction is not well-determined, the LMN hodogram is unreliable (see `boundary-minimum-variance`).
4. **Write the component matrix.** Save the (rotated) B as an N×3 `data` matrix + `time` to `<bundle>/data/hodo.npz`. For the canonical view, columns ordered (max, int, min) so x=max, y=int.
5. **Render the hodogram.** `render_tplot(input_files=["<bundle>/data/hodo.npz"], output_file="<bundle>/plots/hodogram.png", panel_types=["scatter"], x_component=[0], y_component=[1])` → B_max vs B_int. Add a second input (or repeat with `y_component=[2]`) for B_max vs B_min.
6. **Interpret & report.** Read the shape (line→linear, ellipse→elliptical, circle→circular) and the trace direction (rotation sense / handedness). Report the polarization, rotation sense, the frame used, and the MVA eigenvalue ratio that justifies it. Save to `notes/`; return the PNG path + compact stats, not arrays.

## Guardrails
- **Frame matters:** interpret a hodogram in the variance/LMN (or a deliberately chosen physical) frame; raw spacecraft-frame axes rarely align with the wave/boundary and mislead. State the frame.
- **MVA reliability gate:** if you used MVA, report λ2/λ3; a small ratio means the LMN axes (hence the hodogram orientation) are ill-determined — flag it.
- **One matrix per `.npz`:** two component pairs = two inputs (or two render calls); don't expect one multi-key file to stack panels.
- **Stationary, clean interval:** a hodogram over a non-stationary window or across multiple structures is uninterpretable — isolate one crossing/packet.
- **Component indices are lists**, one per input file; mismatched lengths error before drawing.
- Artifact-first: return the PNG path + polarization/rotation summary + eigenvalue ratio, never pasted component arrays.

## Example
A magnetopause crossing: `fetch_data_product` MMS/THEMIS B → `analyze_minvar_coordinates`
(eigenvalue ratio λ2/λ3 ≈ 15, well-determined LMN) → write the rotated B (max,int,min) to
`hodo.npz` → `render_tplot(panel_types=["scatter"], x_component=[0], y_component=[1])`. The
B_max-vs-B_int panel shows a smooth quarter-turn ellipse — a rotational discontinuity with a
clear sense of rotation — reported alongside the frame and the eigenvalue ratio so the
classification is self-documenting.
