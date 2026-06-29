# Parker Solar Probe perihelion solar-wind workflow

This example is a metadata-first SPEDAS Agent Kit recipe for a Parker Solar Probe (PSP)
perihelion interval. It combines CDAWeb PSP measurements with SPICE geometry
planning while avoiding bulk downloads until dataset, parameter, and cadence
choices are explicit.

## Science question

> During a PSP perihelion interval, compare the local solar-wind magnetic field
> and proton moments with the spacecraft heliocentric geometry.

Example planning window: `2021-04-29T00:00:00Z` to `2021-04-29T06:00:00Z`.
This is intentionally short for smoke validation; extend only after discovery
confirms dataset coverage and desired cadence.

## 1. Route the request across SPEDAS data sources

Call the workflow planner before any fetch:

```json
{
  "tool": "search_spedas_data_sources",
  "args": {
    "question": "Plan a Parker Solar Probe perihelion solar-wind workflow with FIELDS magnetic field, SWEAP plasma, and spacecraft heliocentric geometry",
    "target": "Parker Solar Probe",
    "observables": ["solar wind", "magnetic field", "plasma", "perihelion geometry"]
  }
}
```

Expected source mix: `cdaweb` for PSP FIELDS/SWEAP time series and `spice` for
trajectory, heliocentric distance, frames, and geometry context.

Then create the no-fetch plan:

```json
{
  "tool": "plan_spedas_observation",
  "args": {
    "science_goal": "Parker Solar Probe perihelion solar-wind context: combine CDAWeb PSP FIELDS/SWEAP measurements with SPICE heliocentric distance and trajectory planning",
    "start": "2021-04-29T00:00:00Z",
    "stop": "2021-04-29T06:00:00Z",
    "target": "Parker Solar Probe",
    "observables": ["solar wind", "magnetic field", "proton plasma", "heliocentric distance"]
  }
}
```

## 2. Discover PSP CDAWeb products

Use the unified data layer:

```json
{"tool": "browse_data_sources", "args": {"source_type": "cdaweb", "query": "PSP"}}
{"tool": "load_data_source", "args": {"source_type": "cdaweb", "source_id": "psp"}}
```

Useful metadata-discovered candidates:

| Role | Dataset | Parameters to inspect first | Notes |
| --- | --- | --- | --- |
| FIELDS MAG RTN | `PSP_FLD_L2_MAG_RTN` | `psp_fld_l2_mag_RTN` | Full-cadence magnetic field in RTN coordinates, units nT. |
| SWEAP/SPAN-I moments | `PSP_SWP_SPI_SF00_L3_MOM` | `DENS`, `VEL_RTN_SUN`, `TEMP` | Partial moment density, RTN Sun-frame velocity, and temperature. |
| SWEAP/SPC moments (alternative) | `PSP_SWP_SPC_L3I` | `np_moment_gd`, `vp_moment_RTN_gd`, `wp_moment_gd` | Good-quality proton density/velocity/thermal speed variables. |

Confirm parameters with compact metadata calls before fetching:

```json
{"tool": "browse_data_parameters", "args": {"source_type": "cdaweb", "dataset_id": "PSP_FLD_L2_MAG_RTN"}}
{"tool": "browse_data_parameters", "args": {"source_type": "cdaweb", "dataset_id": "PSP_SWP_SPI_SF00_L3_MOM"}}
```

Only after confirming coverage and parameter names should an agent call
`fetch_data_product`. Keep the interval short first, write to `output_dir`, and
record the returned file path/provenance rather than inlining data.

## 3. Plan SPICE geometry

Discover SPICE support and frames without loading kernels or writing trajectory
files:

```json
{"tool": "browse_data_sources", "args": {"source_type": "spice", "query": "psp"}}
{"tool": "load_data_source", "args": {"source_type": "spice", "source_id": "PSP"}}
```

The `browse_data_sources(source_type="spice")` result should include a `PSP`
mission entry. Use `load_data_source(source_type="spice", source_id="PSP")` to
review coordinate-frame context. For actual geometry products, use explicit
file-backed calls, for example:

```json
{
  "tool": "get_ephemeris",
  "args": {
    "target": "PSP",
    "observer": "SUN",
    "frame": "ECLIPJ2000",
    "time": "2021-04-29T00:00:00Z",
    "time_end": "2021-04-29T06:00:00Z",
    "step": "10m",
    "output_file": "runs/psp-perihelion/geometry/psp_eclipj2000_20210429.csv",
    "allow_kernel_download": true
  }
}
```

PSP kernels are ~266 MB. If they are not already cached, `get_ephemeris` returns
a `needs_confirmation` / `kernel_download_required` response rather than
downloading silently (issue #29). Pass `allow_kernel_download: true` (as above) to
opt in, or pre-load with `manage_data_cache(source_type="spice", action="load", mission="PSP")`.

For a perihelion workflow, compute or derive heliocentric distance from the
trajectory CSV and align it with the CDAWeb time series during analysis.

## 4. Preserve provenance

Before fetching bulk data, scaffold the analysis bundle:

```json
{
  "tool": "create_spedas_analysis_bundle",
  "args": {
    "study_name": "psp-perihelion-solar-wind",
    "output_dir": "runs",
    "science_goal": "Combine PSP FIELDS/SWEAP solar-wind measurements with SPICE heliocentric geometry near perihelion",
    "target": "Parker Solar Probe",
    "start": "2021-04-29T00:00:00Z",
    "stop": "2021-04-29T06:00:00Z",
    "data_sources": ["cdaweb", "spice"]
  }
}
```

Record each MCP call, selected datasets/parameters, output files, hashes, package
versions, and any cache/kernel state in the bundle's `provenance/` directory.
