---
name: field-line-footpoint
description: Trace a magnetic field line from a spacecraft position to its ionospheric footpoint (or magnetic equator / L-shell apex) with a Tsyganenko/IGRF model — the magnetosphere conjugacy / ground-conjunction workflow, e.g. "where does this spacecraft map to on the ground?" or "find the conjugate ground station." Composes existing tools; adds no new tool.
---

# Field-line footpoint: trace a spacecraft to its ionospheric conjugate

A guided version of the pyspedas geopack field-line tracing crib — map a near-Earth
spacecraft position down a model field line to its **ionospheric footpoint** (for
ground/auroral conjunctions) or out to the **magnetic equator** (for L-shell / drift-shell
context). This is GUIDANCE around the existing `evaluate_magnetic_field` tool, which already
performs the trace; no new tool or code is added.

## When to use
- "Where does this spacecraft map to on the ground / in the ionosphere?" (conjugate ground station, auroral oval, SuperDARN/THEMIS-GBO conjunction.)
- "Trace this field line to the magnetic equator / give me its L-shell apex."
- "Are these two spacecraft on the same field line / drift shell?" (footpoint or L comparison.)

## Tool chain (all already exist)
`get_ephemeris` (or `fetch_data_product` for a position dataset) → `transform_coordinates`
(to **GSM**) → `evaluate_magnetic_field(trace="ionosphere" | "equator", model=...)`
→ read footpoints from the output `.npz` → (`render_tplot` for the per-sample series),
all inside a `create_spedas_analysis_bundle`. For McIlwain **L** specifically,
`calculate_lshell` is the equatorial-trace shortcut.

## Backend (VERIFIED contract)
`evaluate_magnetic_field` wraps pyspedas geopack `tigrf/tt89/tt96/tt01/tts04` (field) and
`ttrace2endpoint` (tracing). Key facts that drive this skill:
- **Input** is a positions artifact: `.npz` with `positions` = N×3 **in GSM, kilometers** (and optional `times`); or `.npy`; or CSV/JSON with `position_cols`/`time_col`. Positions are **not** auto-transformed — you must hand it GSM.
- **`trace`** ∈ `{none, ionosphere, equator}`, mapped to `ttrace2endpoint` endpoints. `"ionosphere"` traces along the field line to the ionospheric foot; `"equator"` traces to the magnetic equator.
- **Output** is `output_file` as `.npz`: per-sample **B (nT)** for every position, plus **footpoints** when tracing, plus an **L series** for `equator` traces. The tool **returns only** the model, `field_strength_nT` min/max/mean, paths, and (for equator) an `lshell_summary` — never the raw arrays. Read the `.npz` yourself to get coordinates.
- **`model`**: `igrf` (default) is fast and **parameter-free**. Distorted external models (`t89`, `t96`, `t01`, `ts04`) require **explicit `parameters`** (geomagnetic / solar-wind drivers — e.g. Dst, Pdyn, By/Bz, G/W indices as the model demands); there is **no hidden network I/O**, so missing/garbage parameters give a silently wrong field, not an error.
- `calculate_lshell` is the same machinery specialized to an equator trace: equatorial foot radius in Re = McIlwain **L**; returns `{min_L, max_L, mean_L}` + paths, optional ionospheric `footprint=True`.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(...)`; use `<bundle>/data` for artifacts and `<bundle>/plots` for renders.

2. **Get the spacecraft position(s).** `get_ephemeris(...)` for the spacecraft and interval (or `fetch_data_product` on a position dataset). You need one or more position samples with their times.

3. **Put positions in GSM, in km.** Tsyganenko/IGRF tracing is defined in **GSM**. If your ephemeris is in another Earth frame, `transform_coordinates` to GSM first; confirm units are **kilometers** (convert from Re ×6371.2 if needed). Write an artifact `<bundle>/data/pos_gsm.npz` with `positions` N×3 and matching `times`. **A wrong frame or Re-vs-km mix-up silently produces a plausible-looking but wrong footpoint** — verify before tracing.

4. **Pick the model and check its domain.** Use `igrf` for an internal-field / quiet baseline (no parameters needed). For realistic, activity-dependent mapping use `t89` (Kp-only) or a distorted model (`t96`/`t01`/`ts04`) and **supply `parameters`** with the required drivers for the event time. Tsyganenko external models are valid **only inside the magnetosphere, near Earth** — pair this step with the field-model domain guard (see Guardrails).

5. **Trace.**
   - Footpoint: `evaluate_magnetic_field(positions_file="<bundle>/data/pos_gsm.npz", output_file="<bundle>/data/trace_iono.npz", model=<model>, parameters=<...>, trace="ionosphere")`.
   - Equatorial / L: `trace="equator"` (read the returned `lshell_summary`), or use `calculate_lshell(..., footprint=True)` to get both L and the ionospheric foot in one call.

6. **Read the footpoints from the `.npz`.** The tool returns only summary + paths, so open `output_file` and pull the **footpoints** array (and the per-sample B, and L series for equator). Convert the footpoint to the geographic/geomagnetic lat-lon you need (the foot is returned in the trace's coordinate convention — confirm it before mapping to a ground station).

7. **Render (optional) & report.** `render_tplot(input_files=["<bundle>/data/trace_iono.npz"], output_file="<bundle>/plots/B_and_L.png", panel_types=["line"])` to show the per-sample |B| or L over the interval (one 2-D matrix per `.npz`; split footpoint vs B/L into separate `.npz` inputs if they don't share an axis). Report: model used + its parameters, the footpoint coordinate(s), L (if traced), and an explicit **validity verdict** (next section). Save to `notes/`.

## Guardrails
- **Artifact-first:** return the `.npz` paths + the compact summary (model, |B| min/max/mean, footpoint coord, L), never pasted footpoint/B arrays.
- **Frame & units:** input MUST be GSM in km. State the source frame and the conversion you applied; a frame or Re/km error is the most common cause of a silently wrong footpoint.
- **Model domain (reliability):** Tsyganenko models are only physical **in the near-Earth magnetosphere**. A footpoint traced from a position beyond the model's validity region (deep tail, far upstream/downstream, outside the magnetopause) is **unreliable** — state the model and that any footpoint past its domain should not be trusted. Always report which model was used.
- **Distorted-model parameters:** `t96/t01/ts04` (and `t89`'s Kp) need correct geomagnetic/solar-wind drivers for the event; with no network fallback, wrong/absent parameters yield a wrong field with **no error**. Record the parameter values used. `igrf` avoids this but ignores all external/activity distortion.
- **Trace endpoint convention:** confirm whether the returned footpoint is geographic vs geomagnetic / GSM before mapping it to a ground station or comparing two spacecraft.

## Example
A THEMIS spacecraft at ~10 Re in the night-side magnetosphere → `get_ephemeris` → `transform_coordinates` to GSM(km) → write `pos_gsm.npz` → `evaluate_magnetic_field(..., model="t89", parameters={"kp": 3}, trace="ionosphere")`. The tool returns `field_strength_nT` {min,max,mean} + paths; opening `trace_iono.npz` gives the ionospheric footpoint, which I map to the conjugate ground magnetometer. Re-running with `trace="equator"` (or `calculate_lshell`) yields L ≈ 9–10, confirming the spacecraft sits on a tail-stretched field line where the **T89 footpoint is only marginally reliable** — exactly the caveat the domain guard exists to flag.