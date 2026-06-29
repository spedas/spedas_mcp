---
name: coordinate-frame-tour
description: Discover which SPICE coordinate frame fits a science question and transform vectors/time series into it — "what frame should I use for CME propagation / magnetospheric work / solar-wind turbulence, and how do I convert into it?" Composes existing tools; adds no new tool.
---

# Coordinate-frame tour: pick the right frame, then transform into it

A guided front door to the SPICE coordinate-frame catalog. Heliophysics analysis
lives or dies on using the *right* frame (RTN for solar-wind turbulence, GSE/GSM for
magnetospheric work, HEEQ for mapping to the solar surface, HEE for CME propagation),
and the catalog ships a per-frame **`use_when`** hint for exactly this choice. This
skill turns "which frame?" into a discover → choose → transform → verify workflow over
existing tools — no new tool is added (the catalog is exposed through the unified data
layer, per #121/#122).

## When to use
- "What coordinate frame should I use for <CME propagation / magnetospheric / solar-wind / orbit> analysis?"
- "What frames can I transform between, and what does each mean?"
- "Convert this vector / this B time series from frame A to frame B."

## Tool chain (all already exist)
`load_data_source(source_type="spice", source_id="frames")` (discover the catalog)
→ choose a frame from each entry's `use_when` → `transform_coordinates` (one vector at a
time) or `transform_timeseries_coordinates` (a fetched CSV of vectors) → verify, inside a
`create_spedas_analysis_bundle`.

## Backend (VERIFIED contract)
Frame discovery is exposed through the **existing unified data layer** — there is no
`list_coordinate_frames` tool on the default surface (it was consolidated out; the catalog
returns through `load_data_source` instead).

- `load_data_source(source_type="spice", source_id="frames")` returns a **dict** with
  top-level keys: `frame_catalog`, `frame_names`, `supported_frame_names`, `note`.
  - `frame_catalog.frame_count` (int) and `frame_catalog.frames` — a list of dicts, each
    `{frame, full_name, description, use_when}`. The **`use_when`** field is the frame-selection hint.
  - `frame_names` — canonical frame ids (e.g. `J2000, ECLIPJ2000, ECLIPB1950, HCI, HEE, HAE, HEEQ, GSE, GEI, RTN`).
  - `supported_frame_names` — `frame_names` **plus aliases** you may pass to a transform.
  This is a returned dict (not a stored tplot var, not a file); read the fields directly.
- `transform_coordinates(vector=[x,y,z], time, from_frame, to_frame, allow_kernel_download=...)`
  → returns a dict with `output_vector` as a **JSON list** (`status: success`). Single sample.
- `transform_timeseries_coordinates(...)` → transforms a fetched CSV/`.npz` of vectors
  between frames over a time axis (artifact in / artifact out); use it for a B or position series.
- **Unknown frame** → structured `invalid_argument` error carrying the supported frame list
  (don't guess a frame string — discover it first). Frame-dependent transforms may require
  SPICE kernels: a cold cache returns `needs_confirmation`/`kernel_download_required`; pass
  `allow_kernel_download=True` after checking/confirming via `manage_data_cache(source_type="spice", action="status")`. Do not route this skill through hidden source-specific kernel tools.

## Procedure

1. **Bundle.** `create_spedas_analysis_bundle(...)`; write artifacts under `<bundle>/data`.
2. **Discover.** `load_data_source(source_type="spice", source_id="frames")`. Read
   `frame_catalog.frames` and scan each entry's `use_when` to match your science goal.
3. **Choose** the frame whose `use_when` fits (see the map below), and confirm its id is in
   `supported_frame_names` before using it.
4. **Transform.**
   - One vector → `transform_coordinates(vector=..., time=..., from_frame=..., to_frame=...)`;
     read `output_vector` (a list).
   - A series (B, position) → fetch the vectors to a CSV with `fetch_data_product`, then
     `transform_timeseries_coordinates(... from_frame, to_frame, output_dir=<bundle>/data)`.
5. **Verify & report.** Sanity-check the result (e.g. |vector| is preserved under a pure
   rotation; a radial solar-wind B is mostly +R in RTN). Report the chosen frame + *why*
   (quote its `use_when`), the from→to pair, and paths. Save to `notes/`.

### Frame-selection quick map (from the catalog's `use_when`)
- **RTN** — solar-wind B/V at a spacecraft (radial/tangential/normal).
- **GSE / GEI** — near-Earth / magnetospheric spacecraft (THEMIS, Van Allen Probes).
- **HEE** — Sun–Earth geometry; CME propagation / solar-wind arrival at Earth.
- **HEEQ** — mapping features to the solar surface (active regions, coronal holes).
- **HCI** — heliospheric structure; studies tied to solar rotation.
- **J2000 / ECLIPJ2000 / HAE** — general inertial / orbit-plot / Sun-centered ecliptic.
- **ECLIPB1950** — legacy B1950 catalogs only.

## Guardrails
- **Discover before transforming:** read the catalog and pass only ids from
  `supported_frame_names`; an unknown frame string returns a structured error, not a guess.
- **Frame choice is the science:** justify it with the entry's `use_when`. The wrong frame
  silently produces a valid-looking but physically wrong decomposition (e.g. RTN vs GSE for a
  magnetopause normal).
- **Kernels:** geometry-dependent frames need SPICE kernels; pass `allow_kernel_download=True`
  or preload, and expect a `needs_confirmation` gate on a cold cache.
- **Sanity check:** vector magnitude is invariant under rotation; use it to catch a bad transform.
- Artifact-first: return the chosen frame, the from→to pair, and paths/compact stats — not pasted arrays.

## Example
Goal: "study switchbacks in PSP's magnetic field." → `load_data_source(source_type="spice",
source_id="frames")` → the `RTN` entry's `use_when` ("solar-wind analysis at a spacecraft;
magnetic field and plasma velocity") matches → fetch `PSP_FLD_L2_MAG` (in RTN already, or in
another frame) and, if needed, `transform_timeseries_coordinates(... to_frame="RTN")` →
verify the mean field is predominantly radial (+R) for a Parker-spiral interval. The report
names RTN and quotes its `use_when`, so the frame choice is self-documenting.
