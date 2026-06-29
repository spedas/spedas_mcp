---
name: dual-spacecraft-timing
description: Solve for a planar boundary's normal direction n and phase speed V from one discontinuity crossing seen at multiple spacecraft (the classic 4-s/c timing / CVA method) — fetch each spacecraft's position at the crossing, pair it with that spacecraft's crossing time, and solve the timing system by least squares. Use when you have a boundary/shock/discontinuity crossing time at >=4 (or 2-3, degenerate) spacecraft and want the normal and speed. Composes existing tools; adds no new tool.
---

# Multi-spacecraft timing (CVA): boundary normal and phase speed

A guided version of the classic four-spacecraft timing / Constant-Velocity-Approach
(CVA) crib sheet. Given the **same** boundary crossing observed at several spacecraft
and their positions, it recovers the boundary **normal n** (unit vector) and the
**phase speed V** along n. There is no "timing" backend tool and there should not be —
the only data fetch is each spacecraft's position; the solve is a tiny local NumPy
least-squares. The value is in the procedure, the geometry/conditioning check, and the
interpretation.

## When to use
- "I see this magnetopause/shock/discontinuity crossing at 4 spacecraft — what's the normal and speed?"
- "Use timing on the MMS/Cluster tetrahedron for this crossing."
- "How fast and in what direction is this boundary moving?" (single-spacecraft MVA gives orientation only, not speed — timing gives both.)

## Tool chain (existing tools only)
`create_spedas_analysis_bundle` → `get_ephemeris` × N spacecraft (positions only)
→ **local NumPy `numpy.linalg.lstsq`** (no tool; run via the Bash python interpreter,
writing inputs/outputs into the bundle) → optional `render_tplot` only if you want to
overlay the per-spacecraft field traces that justify the crossing times.

## Backend (VERIFIED contract)
- **`get_ephemeris(target, time, observer, frame)` with `time` only returns a single-time STATE INLINE** — a dict/array of position (and velocity) in the requested `frame`, in **km**. It is *not* a stored tplot variable and *not* an `.npz`. Read the returned position straight out of the response dict; do not look for a file unless you passed `output_file`.
- **Default `frame="ECLIPJ2000"`, `observer="SUN"`.** For magnetospheric boundaries you almost always want `frame="GSE"` (or GSM) and `observer="EARTH"`. Pass them explicitly — the default Sun-centered ecliptic frame is wrong for a magnetopause and will silently give a nonsense normal.
- **Target registry is enforced.** `get_ephemeris` validates `target` against the SPICE mission registry and returns a structured `unsupported_spice_target` error for names it does not know (e.g. **`MMS1` is NOT in the registry**). THEMIS A–E, Cluster-class, Van Allen Probes A/B and the heliophysics fleet are supported; for MMS-style fleets not in SPICE you must supply the per-spacecraft positions yourself (from the mission ephemeris CDF / user-provided km vectors) and skip straight to the solve.
- **Kernels:** a cold cache returns `needs_confirmation` / `kernel_download_required`; first check `manage_data_cache(source_type="spice", action="status")`, then retry the relevant `get_ephemeris(...)` call with `allow_kernel_download=True` after confirming the download. Do not route this skill through hidden source-specific kernel tools.
- The crossing **times** are NOT produced by any tool — they are identified by the user (or read off per-spacecraft field traces) as the moment each spacecraft sees the boundary.
- **Timestamps for the solve are numeric Unix seconds.** Convert each crossing time to a float epoch (seconds) before differencing; do not feed ISO strings into the arithmetic. (No FFT/spectral step here, but the same numeric-epoch rule applies.)
- **`render_tplot` is optional and out-of-band:** it draws ONE 2-D matrix per `.npz` — used here, if at all, only to display the field traces that anchor the crossing times, never for the timing result itself.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(study_name, output_dir, science_goal, target, start, stop)`. Put the positions table, the solve script, and the result JSON under `data/`; provenance under `provenance/`.

2. **Collect the crossing times t_i.** One per spacecraft, for the SAME boundary, identified by the user or from the field traces. Record each as an ISO time AND as a numeric Unix-second epoch t_i (float). Keep spacecraft 1 (the reference) explicit.

3. **Get each spacecraft position r_i.** For every spacecraft, `get_ephemeris(target=<sc>, time=<that sc's crossing time>, observer="EARTH", frame="GSE", allow_kernel_download=True)`. Read the inline position (km) from the response. **Use each spacecraft's own crossing time** for its position (positions barely move over the crossing, but be consistent). All r_i MUST be in the SAME frame and in km. If a target is `unsupported_spice_target`, supply that spacecraft's km position from external ephemeris instead.

4. **Build the timing system.** With reference spacecraft 1, form the matrix D whose rows are the baseline vectors `(r_i − r_1)` (km), and the vector `dt` whose entries are `(t_i − t_1)` (seconds), for i = 2…N. The slowness model is `D · m = dt`, where **`m = n / V`** (units s/km).

5. **Solve by least squares.** Run locally:
   `import numpy as np; m, *_ = np.linalg.lstsq(D, dt, rcond=None)`.
   Then **`V = 1/|m|`** (km/s) and **`n = m/|m|`** (dimensionless unit vector). For exactly 4 non-coplanar spacecraft D is 3×3 and the solve is exact; with >4 it is over-determined (least squares); with 2–3 it is under-determined (degenerate — see Guardrails).

6. **Compute a conditioning / quality metric — do not skip.** The normal is only trustworthy if the spacecraft are well-separated in 3-D:
   - **Tetrahedron volume** of the 4 positions, and a normalized **elongation/planarity** or the dimensionless quality factor Q (volume relative to the mean baseline cubed).
   - **Condition number** `np.linalg.cond(D)`. A large cond(D) (or near-zero volume) means a planar/string-of-pearls configuration → the component of n out of the spacecraft plane is unconstrained and V is unreliable.

7. **Record.** Write n, V, baselines, cond(D), tetrahedron volume/quality, and the input times+positions to a small JSON/CSV in the bundle's `data/`. Return paths + these compact numbers — never the raw position arrays.

## Guardrails
- **>=4 non-coplanar spacecraft are required for a unique (n, V).** With 3 coplanar (or 2) spacecraft the system is degenerate: you can constrain the normal's projection in the spacecraft plane but not its full 3-D direction or V — report it as a degenerate/partial result, not a confident normal.
- **Always state the tetrahedron quality and cond(D)** beside n and V. Flag planar / string configurations explicitly: a small volume or large condition number means the out-of-plane normal and the speed are unreliable, exactly the case this metric exists to catch.
- **One frame, km, everywhere.** Mixing frames (e.g. one position in ECLIPJ2000 and others in GSE) or units silently corrupts D. Verify every r_i shares the frame you intend (default get_ephemeris frame is ECLIPJ2000 — override to GSE/GSM).
- **Same boundary at every spacecraft.** The crossing times must mark the identical structure; misidentifying which feature is "the" boundary at one spacecraft poisons the whole solve.
- **Planarity & constant-velocity assumption.** CVA assumes a locally planar boundary moving at constant V over the crossing interval. Strong curvature or acceleration across the baseline breaks it; for accelerating boundaries consider the constant-thickness (CTA) variant instead.
- **Artifact-first.** Positions, the solve script, and results go to the bundle; return paths + (n, V, Q, cond) numbers, never pasted arrays.

## Example
An MMS-class tetrahedron magnetopause crossing: the user supplies the four per-spacecraft
crossing times and (since `MMS1` is not in the SPICE registry) the four GSE positions in km.
Build D from `(r_i − r_1)` and dt from `(t_i − t_1)` in Unix seconds, `np.linalg.lstsq` →
`m = n/V` → report n (GSE unit vector), V (km/s), the tetrahedron volume / quality factor Q,
and cond(D). A near-regular tetrahedron gives a small cond(D) and a confident normal+speed;
a flattened (planar) configuration gives a large cond(D) — the procedure flags the result as
unreliable rather than reporting a spurious normal.
