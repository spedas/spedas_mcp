# SPEDAS MCP

`spedas_mcp` is the SPEDAS organization MCP server for agentic heliophysics workflows. It presents one SPEDAS-facing **data layer** and organizes capabilities by data source category instead of by the internal backend packages used to implement them.

The current design follows Jason's A+B direction:

- **A. SPEDAS data layer** — one unified entry point for source categories such as `cdaweb`, `pds`, and `spice`/geometry.
- **B. SPEDAS science workflow layer** — high-level planning tools that let Claude Code, Codex, OpenCode, LingTai, or another agent start from a science question before choosing source-specific operations.

Implementation backend packages should stay visible to maintainers, but they should not be the user's first mental model.

## Repository

- Official repo: <https://github.com/spedas/spedas_mcp>
- Python package name: `spedas-mcp`
- Python module / CLI module: `spedas_mcp`
- Default MCP tool count: 17 (compatibility and analysis tools are conditionally registered)

## Practical guide: run a SPEDAS MCP study

Use this section as the README-level operating guide for researchers and agents.
The detailed capability map below is the reference; this guide is the shortest
safe path from a science question to reproducible artifacts.

### The default loop

1. **Restate the science question and constraints.** Capture the target, mission,
   instrument or observable, time range, and whether the request is heliophysics,
   planetary, geometry-only, or local-analysis oriented.
2. **Ask SPEDAS MCP to choose the data-source family before fetching data.** Start
   with `spedas_overview()`, then call `search_spedas_data_sources(...)` or
   `plan_spedas_observation(...)`. Do not jump directly to a low-level archive
   tool just because a mission name matched a backend.
3. **Create a run directory.** For work that may fetch, transform, render, or be
   cited later, call `create_spedas_analysis_bundle(...)` first and keep data,
   plots, provenance, and notes under that bundle.
4. **Browse narrowly, then fetch narrowly.** Use the data-layer tools to browse
   source categories and parameters. Keep public-archive requests to small,
   reproducible intervals and explicit parameters.
5. **Use geometry and analysis as follow-on steps.** SPICE geometry, coordinate
   transforms, spectra, field models, particle moments, and rendering tools should
   consume explicit files/artifacts. They should not hide large downloads or return
   bulk arrays inline.
6. **Return paths, provenance, and caveats.** A good answer names the source,
   dataset/product, variables, time window, output files, validation/caveats, and
   the next reproducible command. It does not paste CDF contents or giant arrays
   into chat.

### Choose the leading source family

| User request pattern | Lead with | Then use | Common caveat |
|---|---|---|---|
| Near-Earth magnetosphere, solar wind, MMS, THEMIS, Cluster, Geotail, Van Allen / RBSP, STEREO, PSP, Solar Orbiter, Ulysses, Voyager heliosphere | `source_type="cdaweb"` | CDAWeb browse/load/fetch tools; SPICE only if geometry is part of the question | Mission names may also appear in planetary archives; keep the science context in the plan. |
| Planetary mission fields/particles at a planet, e.g. Juno/Jupiter, Cassini/Saturn, MAVEN/Mars, New Horizons/Pluto | `source_type="pds"` | PDS discovery/fetch, plus SPICE geometry when trajectory or observation geometry matters | Generic words like "bow shock", "magnetosphere", "plasma", or "energetic particle" are not enough to choose CDAWeb if the target is planetary. |
| Ephemeris, distance, trajectory, frame transforms, observer-target geometry | `source_type="spice"` | Browse missions/frames with `browse_data_sources` / `load_data_source`; compute with `get_ephemeris`, `compute_distance`, `transform_coordinates` | SPICE is geometry, not measurement data. Pair it with CDAWeb/PDS when you also need fields or particles. |
| Any HAPI-compliant server outside the bundled categories | `source_type="hapi"` | `browse_hapi_catalog`, `fetch_hapi_data` | Requires the optional `hapi` extra and an explicit HAPI server URL. |
| Ground magnetotelluric / FDSN station magnetic data | `source_type="fdsn"` | `browse_fdsn_datasets`, `fetch_fdsn_data` | Requires the optional `fdsn` extra and a time range. |
| Local file analysis after data already exists | Analysis tools | Coordinate transforms, FAC/minvar, spectra, field/L-shell, particle moments/spectra, `render_tplot` | Inputs are files; install `spedas-mcp[analysis]` for the optional backend. |

### Minimal MCP call sequence

For an open-ended question, the safe skeleton is:

```text
spedas_overview()
search_spedas_data_sources(question="...", target="...", observables=[...])
plan_spedas_observation(science_goal="...", start="...", stop="...", target="...", observables=[...])
create_spedas_analysis_bundle(study_name="...", output_dir="...")
browse_data_sources(source_type="cdaweb|pds|spice|hapi|fdsn")
load_data_source(source_type="...", source_id="...")
browse_data_parameters(source_type="...", dataset_id="...")
fetch_data_product(source_type="...", dataset_id="...", parameters=[...], start="...", stop="...", output_dir="...")
```

Add geometry or local analysis only when the plan calls for it:

```text
get_ephemeris(...)
compute_distance(...)
transform_timeseries_coordinates(input_file="...", output_file="...")
dynamic_power_spectrum(input_file="...", output_dir="...")
render_tplot(input_files=[...], output_file="...")
```

### Practical recipes

- **PSP perihelion solar wind**: route the science question first, let CDAWeb lead
  measurement discovery, then add SPICE only for spacecraft-Sun geometry. See
  `docs/examples/psp_perihelion_solar_wind.md`.
- **MMS magnetopause interval**: use `plan_spedas_observation` to keep mission,
  observable, and interval explicit; fetch selected CDAWeb variables into an
  analysis bundle before plotting or transforming. See
  `docs/examples/mms_magnetopause_workflow.md`.
- **Juno / planetary plasma interactions**: let PDS lead MAG/plasma archive
  discovery and use SPICE as a geometry companion. See
  `docs/examples/juno_pds_spice_workflow.md`.
- **Overview + geomagnetic-index context**: for IDL-SPEDAS-style summary plots
  or Dst/AE/Kp/SYM-H context, load the Claude skill
  `overview-geomagnetic-indices` and use `spedas_overview()["guided_recipes"]`
  to map the intent to CDAWeb/HAPI OMNI datasets or PySPEDAS Kyoto/NOAA loaders.
- **Radiation-belt or field-model analysis**: fetch or prepare a position artifact
  first, then call `evaluate_magnetic_field(...)`, `calculate_lshell(...)`, or
  related analysis tools. Record the model parameters; distorted field models
  intentionally require explicit geomagnetic inputs.
- **Spectrogram or particle moments**: build local input artifacts, then run the
  analysis tools into an output directory. Return the `.npz`/CSV/PNG paths and
  summary ranges, not the bulk matrices.

### Artifact and provenance contract

Every non-trivial run should leave a directory that another researcher can audit:

```text
<run>/
  requests/      original prompt, plan, or recipe
  data/          fetched or prepared measurement files
  plots/         PNG/SVG/PDF renderings
  provenance/    source IDs, parameters, cache notes, tool versions, hashes
  notes/         interpretation, caveats, and next steps
```

When reporting results, include at least:

- science goal and time range;
- selected source family (`cdaweb`, `pds`, `spice`, `hapi`, `fdsn`, or local analysis);
- dataset/product IDs and parameters/variables;
- output files and hashes when available;
- dependency or data-access caveats (`missing_dependency`, archive rate limits,
  cache-only validation, unavailable kernels, no matching station, etc.);
- the next command or MCP call needed to reproduce or extend the run.

### Agent safety checklist

- Prefer the unified data-layer and science-workflow tools over compatibility
  low-level tools for new work.
- Do not infer a source from one keyword. Use target + mission + observable + time
  context, especially for planetary versus near-Earth uses of generic words such
  as "magnetosphere", "bow shock", "radiation belt", "solar wind", and
  "energetic particle".
- Keep fetches narrow. Public archives can rate-limit or be cold; long intervals
  should be split deliberately and recorded in provenance.
- Treat optional extras as optional. Analysis tools are not registered or
  advertised in base installs; HAPI/FDSN tools can return a clear
  `missing_dependency` response. Install `analysis`, `hapi`, or `fdsn` only
  when the workflow needs that backend.
- Validate generated artifacts before interpreting them. Check file existence,
  row/sample counts, time coverage, coordinate frame, and whether the tool returned
  warnings or caveats.

## Layered capability map

### 1. Data layer tools

Start here when the user asks for data, datasets, parameters, products, archives, or cache status.

- `browse_data_sources(source_type="all", query=None)` — browse SPEDAS data source categories, or drill into one category.
- `load_data_source(source_type, source_id, mode="compact", limit=None, offset=0, instrument=None, dataset_query=None, include_full_prompt=False)` — load source context. CDAWeb observatories default to a compact structured dataset page (dataset IDs, instruments, coverage, next calls); use `limit`/`offset` and filters for large catalogs, or `mode="full"` / `include_full_prompt=True` for the legacy full prompt.
- `browse_data_parameters(source_type, dataset_id, dataset_ids=None)` — browse parameters/metadata for CDAWeb or PDS datasets; for SPICE, returns geometry/frame context.
- `fetch_data_product(source_type, dataset_id, parameters, start=None, stop=None, output_dir=None, format="csv", limit=None)` — unified measurement/archive data fetch for CDAWeb/PDS. SPICE requests are routed to geometry tools instead. `limit` is currently a CDAWeb-oriented safety control; PDS fetches should be narrowed by time/parameters.
- `manage_data_cache(source_type="all", action="status", cache_dir=None, mission=None, ...)` — unified cache status/maintenance for the source categories. It passes source-specific cache options through one advertised tool: CDAWeb (`category`, `observatory`, `dataset_ids`, `older_than_days`, `dry_run`, `detail`), PDS (`category`, `mission`, `dataset_ids`, `older_than_days`, `dry_run`, `detail`, `force`), and SPICE (`mission`, `filenames`). Per-call `cache_dir` is reported as guidance only; backend cache roots are configured by the MCP server environment.

Supported `source_type` values:

| source_type | Use for | Main data-layer path |
|---|---|---|
| `cdaweb` | heliophysics observatory time-series, plasma/fields/particles, solar wind, CDF-like intervals | `browse_data_sources` → `load_data_source` → `browse_data_parameters` → `fetch_data_product` |
| `pds` | Planetary Plasma Interactions archives, planetary mission datasets, PDS metadata/products | `browse_data_sources` → `load_data_source` → `browse_data_parameters` → `fetch_data_product` |
| `spice` | geometry, ephemeris, trajectory, distance, coordinate frames/transforms | `browse_data_sources` → `load_data_source` → geometry tools |
| `hapi` | any HAPI-compliant server (CDAWeb, PDS-PPI, ISWA, LISIRD, university networks) | `browse_data_sources(source_type="hapi")` → `browse_hapi_catalog` → `fetch_hapi_data` |
| `fdsn` | FDSN/MTH5 ground magnetotelluric (MT) magnetic stations from EarthScope | `browse_data_sources(source_type="fdsn")` → `browse_fdsn_datasets` → `fetch_fdsn_data` |

`hapi` and `fdsn` are server/time-range addressed (HAPI needs a `server_url`, FDSN needs a `trange`), so the unified `load_data_source`/`browse_data_parameters`/`fetch_data_product` tools recognize these `source_type` values but route you to the dedicated `browse_hapi_catalog`/`fetch_hapi_data` and `browse_fdsn_datasets`/`fetch_fdsn_data` tools (see section 6). Both require optional extras and degrade to a clear `missing_dependency` error when those are not installed.

Compact CDAWeb catalog discovery examples:

```python
# Default MMS page is compact (<12 KB) and includes exact next calls per dataset.
load_data_source(source_type="cdaweb", source_id="mms")

# Page through or narrow large observatories.
load_data_source(source_type="cdaweb", source_id="mms", limit=10, offset=10)
load_data_source(source_type="cdaweb", source_id="mms", instrument="fgm", dataset_query="srvy")

# Opt into the legacy human prompt only when needed.
load_data_source(source_type="cdaweb", source_id="mms", mode="full")
```

### 2. Science workflow tools

Start here for open-ended science requests.

- `spedas_overview()` — compact map of capability groups and recommended workflow.
- `search_spedas_data_sources(question, target=None, observables=None)` — recommend which data source categories should lead a request.
- `plan_spedas_observation(science_goal, start=None, stop=None, target=None, observables=None, data_sources=None)` — produce a source-specific plan before fetching data.
- `compare_cdaweb_pds_spice(science_goal="")` — explain source boundaries and choose the right source family.
- `create_spedas_analysis_bundle(study_name, output_dir, ...)` — create a request/provenance scaffold with `requests/`, `data/`, `plots/`, `provenance/`, and `notes/` folders.

### 3. Geometry tools

SPICE is exposed as a data source category, but geometry operations are clearer as explicit tools:

- Browse SPICE missions with `browse_data_sources(source_type="spice")`; the response also includes a `frame_catalog` with frame descriptions and aliases.
- Browse the same SPICE coordinate-frame catalog explicitly with `load_data_source(source_type="spice", source_id="frames")` or `browse_data_parameters(source_type="spice", dataset_id="frames")`; use `supported_frame_names` as `transform_coordinates` `from_frame`/`to_frame` values.
- `get_ephemeris(mission, target, start, stop, step="1h", frame="J2000", observer=None)`
- `compute_distance(mission, target, observer, start, stop, step="1h")`
- `transform_coordinates(mission, coordinates, from_frame, to_frame, epoch=None)`

SPICE kernel cache status/load/clean/check/purge actions are exposed through `manage_data_cache(source_type="spice", action=..., mission=..., filenames=...)`.

### 4. Analysis tools (optional `pyspedas` backend)

Phase-1 coordinate transforms and Phase-2 time-frequency analysis over fetched
artifacts. These tools require the optional `analysis` extra
(`pip install 'spedas-mcp[analysis]'`, which installs `pyspedas>=2.0` and
`matplotlib`, and `PyWavelets`). `pyspedas`/`matplotlib`/`PyWavelets` are **not** part of the base install, and
the analysis tools are registered with MCP only when their optional
dependencies are importable. In a base install they are absent from `list_tools`;
install `spedas-mcp[analysis]` before asking an MCP client to call them. They are
file-in / file-out: inputs are paths to fetched CSV/JSON
products, bulk outputs are written to disk, and only paths plus compact summaries
are returned (never raw arrays).

Phase 1 — coordinate transforms:

- `transform_timeseries_coordinates(input_file, coord_in, coord_out, output_file, time_col="time", vector_cols=None)` — transform an Nx3 vector time-series between `gse`/`gsm`/`sm`/`gei`/`geo`/`mag`/`j2000` (`pyspedas` `cotrans`).
- `generate_fac_matrix(mag_file, output_file, other_dim="xgse", pos_file=None, time_col="time", vector_cols=None, mag_coord="gse")` — build per-sample field-aligned-coordinate (FAC) 3×3 rotation matrices (`fac_matrix_make`). Position-dependent modes (`rgeo`/`mrgeo`/`phigeo`/`mphigeo`/`phism`/`mphism`) require a GEI `pos_file`; if the position time grid differs from the magnetic-field time grid, the response reports `pos_rows_in`, `mag_rows`, `position_interpolated`, and warnings for sparse upsampling rather than silently hiding the alignment/interpolation.
- `analyze_minvar_coordinates(input_file, output_file=None, output_dir=None, twindow=None, tslide=None, time_col="time", vector_cols=None)` — minimum-variance analysis / LMN boundary-normal frame (`minvar`/`minvar_matrix_make`). Use `output_file` for an explicit single artifact path (`.csv` for full-interval rotated LMN vectors, `.npz` for sliding-window matrices), or `output_dir` for the default `minvar_rotated.csv` / `minvar_matrices.npz` filename; `output_dir` remains supported for existing callers. Full-interval mode returns eigenvalues, eigenvectors, the normal vector, and the intermediate/min ratio; sliding-window mode (set `twindow`) writes per-window rotation matrices.

Phase 2 — time-frequency / wave analysis (issue #15). Each reads a single scalar
channel and writes the bulk `time × frequency` spectrogram (with its axes) to a
compressed `.npz` under `output_dir`, returning only the path, ranges, and shape.
Pair the spectrogram with a downstream renderer to view it.

- `dynamic_power_spectrum(input_file, output_dir, data_col=None, nboxpoints=256, nshiftpoints=128, bin=3, nohanning=False, time_col="time")` — sliding Hanning-window Welch dynamic power spectrum (`pyspedas` `dpwrspc`). Returns `{spectrogram_file, data_col, shape, time_range, freq_range, ...}`.
- `wavelet_transform(input_file, output_dir, data_col=None, wavename="morl", min_period=None, max_period=None, compute_significance=False, siglvl=0.95, time_col="time")` — continuous wavelet transform (Morlet/Paul/DOG) via PyWavelets over Torrence & Compo scales, optionally limited to a period band. `compute_significance=True` adds the per-scale 95% red-noise significance (`pyspedas` `wave_signif`); it is opt-in because significance and wide scale ranges are compute-heavy. Returns `{spectrogram_file, data_col, wavename, shape, time_range, freq_range, period_range, significance_computed, ...}`.

Phase 2 — magnetic field models & radiation-belt coordinates (issues #16, #17).
Both read a **positions artifact** — preferably an `.npz` with a `positions` array
of shape `(N, 3)` in **GSM coordinates (km)** plus an optional `times` array of
Unix seconds (a bare `.npy` Nx3 array, or a CSV/JSON with a time column and three
numeric position columns, are also accepted). Per-sample B vectors, footpoints,
and L series are written to `output_file` as a compressed `.npz`; only summary
stats and paths are returned. IGRF is fast and parameter-free; the distorted
Tsyganenko models require explicit geomagnetic parameters and return a
`parameters_required` error otherwise (no hidden network downloads).

- `evaluate_magnetic_field(positions_file, output_file, model="igrf", parameters=None, trace="none", time_col="time", position_cols=None)` — evaluate `igrf`/`t89`/`t96`/`t01`/`ts04` B (nT) at each geocentric GSM position (`pyspedas` geopack `tigrf`/`tt89`/`tt96`/`tt01`/`tts04`), optionally tracing each field line (`trace` in `none`/`ionosphere`/`equator`, via `ttrace2endpoint`). Position radii are guarded to the near-Earth field-model domain `1..30 Re`; out-of-domain inputs return `code="position_domain_error"` with a hint to convert heliocentric/SPICE or planet-centered vectors to Earth-centered GSM km before calling. `parameters` carries model indices (e.g. `t89` needs `iopt` or `kp`; `t96`/`t01`/`ts04` need `pdyn`/`dst`/`byimf`/`bzimf`(`/g1,g2`/`w1..w6`) or a precomputed `parmod`). Returns `{result_file, model, field_strength_nT: {min,max,mean,components}, footpoints_file?, lshell_summary?, ...}`.
- `calculate_lshell(positions_file, output_file, model="igrf", geomag_parameters=None, footprint=False, time_col="time", position_cols=None, parameters=None)` — McIlwain L-shell (equatorial field-line apex radius, Re) by tracing each geocentric GSM position to the magnetic equator (`pyspedas` geopack `ttrace2endpoint`). Position radii are guarded to `1..30 Re` for near-Earth science use; out-of-domain inputs return `code="position_domain_error"` rather than meaningless large L values. `footprint=True` also writes the northern ionospheric footprint. Distorted models reuse the same geomagnetic-index contract as `evaluate_magnetic_field`; `parameters=` is accepted as an alias for `geomag_parameters=` (so the index argument has the same name across both tools — `geomag_parameters` stays supported for backward compatibility, and passing both with different values is an `invalid_argument` error). Returns `{lshell_file, model, summary: {min_L, max_L, mean_L}, footprint_file?, ...}`.

Phase 2 — particle distributions, moments & spectra (issues #18, #19, #95). The bridge
tool `load_particle_distribution_artifact` runs a pyspedas mission loader/fetch (default
mappings include MMS FPI/HPCA and ERG particle products, with loader overrides available),
selects the requested or best-effort distribution tplot variable, calls the same pyspedas
mission converter, and writes the standard `.npz` distribution artifact. For already-loaded
tplot variables, `build_particle_distribution_artifact` starts at the converter step and
does not download on its own. Both bridges write the required `magf` field: supply
`magf` directly, pass `mag_tplot_name` for an already-loaded B-field tplot variable,
or let `load_particle_distribution_artifact` try the default B-field loader mappings
(MMS FGM / ERG MGF) and interpolate that B vector to the distribution slice times.
The selected B-field time coverage must bracket the distribution slice times; the
bridge returns an input error rather than silently extrapolating endpoint B values.
Only `load_particle_distribution_artifact` performs loader/fetch steps, so any archive
download/cache behavior comes from the requested pyspedas loaders and is reported in
the returned provenance. Both downstream tools read this **explicit
distribution artifact** — an `.npz` (preferred) or JSON object holding per-time-slice
energy/solid-angle cubes: `data` (T,E,A flux), `energy`/`denergy`/`theta`/`dtheta`/`phi`/`dphi`/`bins`
(same shape as `data`, or a single `(E,A)` slice broadcast across time), the scalars
`charge` and `mass`, and optional `times` (Unix seconds). This is the same `data_in`
dict that `pyspedas`'s particle algorithms consume; mission CDF distributions can be
bridged into it either by `load_particle_distribution_artifact` (loader/fetch + converter)
or by `build_particle_distribution_artifact` from an already loaded tplot variable. Bulk
moment time series and spectrogram
matrices are written to `output_dir`; only scalar summaries, paths, ranges, and shapes
are returned (full pressure/temperature tensors, heat-flux cubes, and spectrogram
matrices are never returned inline).

Migration note: `compute_particle_moments` now requires the distribution artifact to
include `magf`, the magnetic-field direction consumed by `moments_3d` for
field-aligned temperature/pressure products. Existing artifacts without `magf` will
return `invalid_argument`; add `magf` as either `(T,3)` vectors (one per time slice),
a single `(3,)` vector to broadcast across all slices, or rebuild the artifact from a
loaded B-field tplot variable via `mag_tplot_name`/the default loader bridge.

- `load_particle_distribution_artifact(output_file, converter="mms_fpi", trange=None, tplot_name=None, loader_module=None, loader_function=None, loader_kwargs=None, mag_tplot_name=None, mag_loader_module=None, mag_loader_function=None, mag_loader_kwargs=None, ..., magf=None, max_slices=32)` — end-to-end bridge that calls a pyspedas mission loader/fetch to populate real CDF-backed tplot variables, selects `tplot_name` (or a best-effort distribution variable from the loader result), sources magnetic context from `magf`, `mag_tplot_name`, or the default MMS FGM / ERG MGF loader mappings, then writes the documented `.npz` distribution artifact. Default particle loader mappings cover MMS FPI/HPCA and ERG particle products; `loader_module`/`loader_function`/`loader_kwargs` and the matching `mag_loader_*` parameters allow mission-product overrides without adding per-mission MCP tools. The return includes loader backend/kwargs, loaded/selected distribution and magnetic tplot names, converter provenance, shapes/ranges, and artifact paths only.
- `build_particle_distribution_artifact(tplot_name, output_file, converter="mms_fpi", index=None, probe=None, data_rate=None, species=None, level=None, units=None, trange=None, single_time=None, magf=None, mag_tplot_name=None, max_slices=32)` — bridge a pyspedas mission particle converter from a pre-loaded real mission tplot/CDF distribution variable into the documented `.npz` schema. `mag_tplot_name` lets the bridge read an already-loaded B-field tplot variable and interpolate it to output slice times, rejecting B variables whose time coverage does not bracket every output slice. Supported converter keys are reported on invalid input; current keys include MMS FPI/HPCA and ERG LEP/MEP/HEP/XEP products. The output is validated against `DIST_SCHEMA_DOC` and a sidecar JSON records converter/magnetic-field provenance, shapes, time/energy/data ranges, and truncation if `max_slices` limits the artifact.
- `compute_particle_moments(dist_file, output_dir, sc_potential_v=0.0, energy_range_ev=None, output_format="json", no_unit_conversion=False)` — plasma moments (density, velocity, temperature, pressure tensor, heat-flux-related quantities) per time slice (`pyspedas` `moments_3d`). Requires the distribution artifact fields listed above, including `magf` as `(T,3)` or broadcast `(3,)`. Optionally restricts to `energy_range_ev=[min,max]` eV (by masking inactive bins) and applies the spacecraft potential. Writes the full moment time series to `output_dir/particle_moments.{json,csv}`. Returns `{moments_file, n_time, time_range, density_summary, velocity_summary, temperature_summary, pressure_tensor_summary, columns, ...}` with `{min,max,mean}` scalar summaries only. Units follow `moments_3d` (density cm⁻³, velocity km/s, temperature eV, pressure eV/cm³).
- `compute_particle_spectra(dist_file, output_dir, spectrum_types=["energy","pitch_angle"], mag_file=None, resolution=None)` — energy / azimuth (`phi`) / elevation (`theta`) / **pitch-angle** spectrograms. Energy/phi/theta use `pyspedas` `spd_pgs_make_e_spec` / `spd_pgs_make_phi_spec` / `spd_pgs_make_theta_spec`, averaging the distribution over the complementary dimensions per slice. `azimuth`→`phi` and `elevation`→`theta` aliases are accepted. Field-aligned `pitch_angle` spectra require a `mag_file` (B-field reference): each slice is rotated into field-aligned coordinates with `spd_pgs_do_fac` (B as +z) and the polar (pitch) angle is binned over 0–180° via `spd_pgs_make_theta_spec` in colatitude mode — **no optional `spd_pgs_make_pad_spec` backend is needed**, so pitch-angle is delivered on every pyspedas build that has the spectra functions. `mag_file` is an `.npz`/`.json` with key `b` as `(T,3)` (one B vector per slice, matched by index) or `(3,)` (broadcast across slices), in the distribution's coordinate frame; only B's direction is used. `resolution` sets the number of pitch-angle bins (default 18). When `mag_file` is absent the `pitch_angle` entry reports `needs_input` while the other requested spectra still compute. Each spectrogram is written to `output_dir/particle_spectra_<type>.npz`. Returns `{spectra: {energy: {spectrogram_file, axis_label, axis_units, shape, axis_range, value_range, ...}, pitch_angle: {..., n_pitch_angle_bins}, ...}, requested, succeeded, n_time, time_range, ...}`.

Phase 2 — artifact rendering / visualization (issue #20, plotting epic #10). This
closes the explore/visualize step of the research loop: the data, spectral, field-model,
and particle tools above all write bulk arrays to disk and return only compact summaries,
and `render_tplot` turns those artifacts into a picture. It uses `matplotlib` (headless
`Agg` backend, no GUI/display) and never fetches remote data.

- `render_tplot(input_files, output_file, panel_types=None, trange=None, xsize=12, ysize=None, dpi=200, ylog=None, zlog=None, x_component=None, y_component=None)` — render a multi-panel tplot-style **PNG** from local artifacts, one stacked panel per `input_file` (top to bottom). Spectrogram `.npz` matrices (`power`/`spectrogram` keys with `time` + `freq`/`axis` axes, as written by `dynamic_power_spectrum`/`wavelet_transform`/`compute_particle_spectra`) render as `pcolormesh` panels with a colorbar; CSV/JSON tables and 1-D/2-D `.npz`/`.npy` value arrays render as line panels. Explicit `panel_types="scatter"`/`"xy"`/`"hodogram"` renders one 2-D numeric matrix per input artifact as a parametric x-y panel; `x_component` and `y_component` are zero-based column selectors (scalars broadcast to all inputs, or lists matching `input_files`; defaults are 0 vs 1). `panel_types` overrides per-file auto-detection — each of `auto` (default), `line`/`timeseries`, `spectrogram`, or `scatter`/`xy`; pass `None` (all auto), a single token (broadcast), or a list matching `input_files`. `trange` is an optional 2-element window (ISO-8601 strings or Unix seconds) that filters samples when a time axis is present (otherwise sample index is used). `ylog`/`zlog` (per-panel booleans or a scalar broadcast) set a log y-axis / log color scale and are rejected with `invalid_argument` when invalid for the panel/data; scatter panels are linear-only. `xsize`/`ysize` are inches and `dpi` is bounded to avoid absurd canvases. The PNG is written to `output_file` (parent dirs created); the return is `{status, output_file, n_panels, trange: {requested, actual}, size_px, dpi, panels: [{index, type, file, shape, value_range, time_range, axis_range?/n_series?/components?, x_range?, y_range?, ylog?/zlog?}], warnings?}` only — **image bytes are never inlined and no bulk arrays are returned**. Requires `spedas-mcp[analysis]` (matplotlib). Scatter coloring by time is not inlined in the first implementation; temporal ordering is shown by a thin connected path plus points.

### 5. External data-source tools (optional `hapi` / `fdsn` backends)

Two additional data sources reach archives outside the three bundled SPEDAS
backend families. Like the analysis tools, their backends are **optional** and imported
lazily: without the extra installed each tool returns a structured
`status="error"`, `code="missing_dependency"` payload naming the extra to
install, so the base install and MCP `list_tools` keep working. Bulk data is
written to `output_dir`; tools return only the file path plus compact metadata
(artifact-first).

HAPI (issue #21, optional `spedas-mcp[hapi]`, installs `hapiclient`):

- `browse_hapi_catalog(server_url, query=None)` — list datasets advertised by any
  HAPI-compliant server (e.g. `https://cdaweb.gsfc.nasa.gov/hapi`,
  `https://pds-ppi.igpp.ucla.edu/hapi`, `https://iswa.gsfc.nasa.gov/IswaSystemWebApp/hapi`,
  `https://lasp.colorado.edu/lisird/hapi`). Returns `{status, server, dataset_count, datasets: [{id, title}...]}`; pass `query` to filter ids/titles.
- `fetch_hapi_data(server_url, dataset_id, parameters, start, stop, output_dir, format="csv")` —
  fetch a dataset slice over `[start, stop)` (stop exclusive per the HAPI spec) and write a flat CSV/JSON table (time column plus one column per scalar parameter and `name[i]` columns for vector/spectral parameters). Returns `{status, file_path, format, server, dataset_id, time_range, rows, parameters_meta}` with per-parameter `units`/`description`/`type`/`size`/`spectral` only.

FDSN/MTH5 (issue #22, optional `spedas-mcp[fdsn]`, installs `pyspedas` + `mth5` + `obspy`):

- `browse_fdsn_datasets(trange, network=None, station=None, usa_only=False)` — list
  EarthScope FDSN magnetotelluric stations that expose three same-band magnetic channels (e.g. `LFE/LFN/LFZ`) within `trange=['YYYY-MM-DD','YYYY-MM-DD']`. Returns `{status, trange, station_count, stations: [{network, station, time_range, channels}...]}`.
- `fetch_fdsn_data(trange, network, station, output_dir, format="csv")` — download an
  MTH5 file, calibrate counts → nT, enforce 3-component Hx/Hy/Hz geometry, and write the time-series (time column plus one column per channel). Returns `{status, file_path, format, network, station, trange, rows, channels, units?}`. Returns `code="resource_not_found"` when no qualifying 3-component data exist in the window.

### 6. Compatibility low-level tools

These remain available for clients that already know the source-specific browse/fetch operations:

- CDAWeb: `browse_observatories`, `load_observatory`, `browse_parameters`, `fetch_data`
- PDS: `browse_pds_missions`, `load_pds_mission`, `browse_pds_parameters`, `fetch_pds_data`
- SPICE: the geometry tools above

The former dedicated cache tools (`manage_cdaweb_cache`, `manage_pds_cache`, `manage_spice_kernels`) are no longer advertised as MCP tools because their actions and kwargs are covered by `manage_data_cache`. See `docs/public_api_strategy.md` for the compatibility map and deprecation guidance.

## Recommended agent workflow

1. Call `spedas_overview()`.
2. For a natural-language science request, call `search_spedas_data_sources(...)` or `plan_spedas_observation(...)`.
3. Use the data layer:
   - `browse_data_sources(source_type="all")`
   - `browse_data_sources(source_type="cdaweb" | "pds" | "spice")`
   - `load_data_source(...)`
   - `browse_data_parameters(...)`
   - `fetch_data_product(...)` for CDAWeb/PDS measurement/archive products
4. Use geometry tools directly for SPICE ephemeris, distance, frame, and coordinate-transform work.
5. For any real analysis, call `create_spedas_analysis_bundle(...)` and write fetched files under the generated `data/` directory.
6. Return compact summaries and file paths. Do not paste large science arrays into chat.

## Quick start for local development

```bash
git clone https://github.com/spedas/spedas_mcp.git
cd spedas_mcp
uv sync --extra dev --extra mcp
uv run --extra mcp python -m spedas_mcp
```

Run tests and smoke checks:

```bash
uv run --extra dev --extra mcp python -m pytest -q
uv run --extra mcp python scripts/smoke_mcp_list_tools.py --json
uv run --extra dev --extra mcp python scripts/validate_plugin_packages.py
```

The list-tools smoke starts the stdio MCP server with isolated temporary cache directories, performs MCP `initialize` + `list_tools`, and verifies the expected advertised tool names. It does not fetch CDAWeb/PDS data or download SPICE kernels.

Optional backends are installed via extras and are not required for the base
install. The `analysis` extra also controls MCP registration of the ten local
analysis tools, so a base `list_tools` response stays focused on data/workflow
and geometry surfaces:

```bash
uv sync --extra analysis   # pyspedas + matplotlib + PyWavelets (coordinate/spectral/field/particle analysis, rendering)
uv sync --extra hapi       # hapiclient (browse_hapi_catalog / fetch_hapi_data, issue #21)
uv sync --extra fdsn       # pyspedas + mth5 + obspy (browse_fdsn_datasets / fetch_fdsn_data, issue #22)
```

## MCP client configuration

Example stdio configuration:

```json
{
  "mcpServers": {
    "spedas": {
      "command": "uv",
      "args": ["run", "--extra", "mcp", "python", "-m", "spedas_mcp"],
      "cwd": "/path/to/spedas_mcp"
    }
  }
}
```

For plugin-style distribution, the canonical standalone wrappers now live in separate SPEDAS org repos:

- <https://github.com/spedas/spedas_claude> — Claude Code plugin wrapper.
- <https://github.com/spedas/spedas_codex> — Codex plugin wrapper.

The in-repo `plugins/spedas-claude/` and `.agents/plugins/spedas-codex/` directories remain lightweight development examples and compatibility fixtures; runtime-specific packaging should evolve in the standalone repos while this repository owns the MCP server itself.
Their shared compatibility contract is recorded in `plugins/spedas-mcp-compatibility.json` and validated by `scripts/validate_plugin_packages.py`: current base `list_tools` count is 17 at `170a8b0c0d058c729d4769f9848754cfb8ec9f8e`; optional analysis and legacy compatibility tools are intentionally outside that base count.

## Maintainer-facing positioning

`spedas_mcp` should be thick at the SPEDAS data/workflow layer and thin at the backend implementation layer:

- Users see one SPEDAS MCP and one `data` layer.
- Data source categories are scientific concepts: CDAWeb, PDS, SPICE/geometry.
- Backend packages remain maintainable internal implementation surfaces.
- Higher-level tools should encode reusable SPEDAS scientific method: source selection, planning, provenance, and artifact discipline.

See `docs/maintainer_note.md` and `docs/examples/agent_workflow.md` for the current framing.
- `docs/examples/juno_pds_spice_workflow.md` — Juno MAG/PDS discovery plus SPICE geometry planning, including current caveats.
