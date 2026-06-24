# Juno MAG at Jupiter: PDS measurement discovery + SPICE geometry planning

This example records the current actionable MCP workflow for a Juno magnetic-field
study near Jupiter.  It intentionally separates **measurement/archive discovery**
(PDS PPI) from **geometry planning** (SPICE): PDS is where the Juno MAG/FGM
calibrated magnetic-field archive is discovered, while SPICE is where spacecraft
trajectory, distance, and frame context are planned or computed.

The workflow is artifact-first.  Create an analysis bundle before any bulk fetch,
write PDS products and SPICE trajectory tables under the bundle's `data/`
directory, and keep the exact MCP calls in `provenance/`.

## Recommended MCP call sequence

### 1. Source selection

```json
{
  "tool": "search_spedas_data_sources",
  "args": {
    "question": "Plan a Juno Jupiter magnetic-field study that discovers archived MAG measurements in PDS and computes spacecraft geometry with SPICE",
    "target": "Jupiter",
    "observables": ["magnetic field", "spacecraft position", "distance"]
  }
}
```

Expected result: `pds` and `spice` should be among the recommended sources.  The
scoring may also mention `cdaweb` because magnetic-field terms are broadly
heliophysics-relevant; for this planetary archive workflow, continue with PDS and
SPICE unless the science question explicitly needs a CDAWeb context product.

### 2. Observation plan

```json
{
  "tool": "plan_spedas_observation",
  "args": {
    "science_goal": "Juno Jupiter magnetic-field workflow combining PDS measurement discovery with SPICE geometry planning",
    "start": "2016-08-27T00:00:00Z",
    "stop": "2016-08-28T00:00:00Z",
    "target": "Jupiter",
    "observables": ["magnetic field", "spacecraft position"],
    "data_sources": ["pds", "spice"]
  }
}
```

Expected result: `recommended_sources` is `['pds', 'spice']` and the returned plan
contains `discover_pds`, `fetch_or_compute_pds`, `discover_spice`,
`fetch_or_compute_spice`, and `preserve_provenance` phases.

### 3. Create the analysis bundle

```json
{
  "tool": "create_spedas_analysis_bundle",
  "args": {
    "study_name": "juno-jupiter-mag-pds-spice",
    "output_dir": "/path/to/work/runs",
    "science_goal": "Juno Jupiter magnetic-field workflow combining PDS measurement discovery with SPICE geometry planning",
    "target": "Jupiter",
    "start": "2016-08-27T00:00:00Z",
    "stop": "2016-08-28T00:00:00Z",
    "data_sources": ["pds", "spice"]
  }
}
```

### 4. Discover Juno PDS datasets

```json
{
  "tool": "load_data_source",
  "args": {"source_type": "pds", "source_id": "juno"}
}
```

The mission prompt/catalog includes Juno FGM/MAG dataset IDs.  Use the fully
qualified PDS3 data-set ID below for parameter browsing; the shorter catalog stem
`pds3:JNO-J-3-FGM-CAL-V1` is not enough for metadata lookup in the current PDS
backend.

```json
{
  "tool": "browse_data_parameters",
  "args": {
    "source_type": "pds",
    "dataset_id": "pds3:JNO-J-3-FGM-CAL-V1.0:DATA"
  }
}
```

Known useful parameters from the metadata include:

- `BX PLANETOCENTRIC`, `BY PLANETOCENTRIC`, `BZ PLANETOCENTRIC`
- `BX RTN`, `BY RTN`, `BZ RTN`
- `DECIMAL DAY`

### 5. Fetch PDS MAG data cautiously

```json
{
  "tool": "fetch_data_product",
  "args": {
    "source_type": "pds",
    "dataset_id": "pds3:JNO-J-3-FGM-CAL-V1.0:DATA",
    "parameters": ["BX PLANETOCENTRIC", "BY PLANETOCENTRIC", "BZ PLANETOCENTRIC"],
    "start": "2016-08-27T00:00:00Z",
    "stop": "2016-08-27T00:10:00Z",
    "output_dir": "/path/to/work/runs/juno-jupiter-mag-pds-spice/data/pds",
    "format": "csv"
  }
}
```

Current caveat: PDS `fetch_data_product` does **not** support the CDAWeb-style
`limit` argument.  Narrow time windows and parameter lists instead.  A black-box
probe of this fetch path timed out after 120 seconds in a no-cache environment, so
treat bulk PDS fetch as a backend/performance item to validate before promising an
interactive result.

### 6. Plan SPICE geometry without large downloads

```json
{
  "tool": "browse_data_sources",
  "args": {"source_type": "spice", "query": "juno"}
}
```

Expected result: the SPICE mission registry includes `{"mission_key": "JUNO",
"naif_id": -61, "has_kernels": true}`.

```json
{
  "tool": "list_coordinate_frames",
  "args": {"mission": "juno"}
}
```

This returns the available frame catalog for planning.  For remote kernel planning
without downloading kernels:

```json
{
  "tool": "manage_spice_kernels",
  "args": {"action": "check_remote", "mission": "juno"}
}
```

Expected result: configured file `juno_rec_orbit.bsp` and the NAIF JUNO kernel
remote directory listing.  Only after the study owner accepts the download cost
should the workflow call `manage_spice_kernels(action="load", mission="juno")` or
`get_ephemeris` for a trajectory table.

### 7. Compute trajectory once kernels are available

```json
{
  "tool": "get_ephemeris",
  "args": {
    "target": "JUNO",
    "observer": "JUPITER BARYCENTER",
    "time": "2016-08-27T00:00:00Z",
    "time_end": "2016-08-28T00:00:00Z",
    "step": "10m",
    "frame": "J2000",
    "output_file": "/path/to/work/runs/juno-jupiter-mag-pds-spice/data/spice/juno_jupiter_geometry_20160827.csv"
  }
}
```

## Current status

Actionable for planning and discovery:

- source selection and observation planning work;
- Juno PDS mission catalog loading works;
- Juno FGM/MAG parameter metadata works with `pds3:JNO-J-3-FGM-CAL-V1.0:DATA`;
- Juno is present in the SPICE registry and remote-kernel check works without
  downloading kernels.

Not yet proven end-to-end in a fast smoke:

- PDS MAG fetch can be slow in a no-cache environment and timed out in a 120 s
  probe;
- SPICE trajectory computation needs kernel download/load validation and should be
  kept out of default smoke tests.
