# MMS magnetopause interval workflow (agent black-box MCP example)

This example records a short, realistic MMS near-Earth boundary-layer workflow that an autonomous agent can run through the SPEDAS Agent Kit stdio server. It is intentionally small, but it is not a no-op: the data fetches below exercised CDAWeb-backed MMS FGM and FPI products for a two-minute interval around the published 2015-10-16 MMS magnetopause/reconnection event.

## Science question

Can MMS1 be screened for a magnetopause current-sheet crossing near `2015-10-16T13:06:00Z` by checking magnetic-field rotation, ion density/velocity changes, and spacecraft position?

Time range used for the smoke workflow:

- start: `2015-10-16T13:06:00Z`
- stop: `2015-10-16T13:08:00Z`
- target: Earth magnetopause

This window is short enough for an agent smoke test, while still being scientifically meaningful for MMS boundary-layer workflow design.

## Exact stdio client command shape

Run from the repository root with MCP dependencies installed:

```bash
PYTHONPATH=src python -m spedas_agent_kit
```

The validation used the Python MCP stdio client (`mcp.ClientSession`, `mcp.client.stdio.stdio_client`) and called these tools in order.

## MCP calls

### 1. Overview

```json
{"tool":"spedas_overview","args":{}}
```

Expected result: compact capability map. The important guidance is to plan first, then browse/load/fetch, and to return file paths rather than arrays.

### 2. Source selection

```json
{
  "tool":"search_spedas_data_sources",
  "args":{
    "question":"MMS1 magnetopause crossing: check magnetic field rotation and solar-wind context near Earth",
    "target":"Earth magnetopause",
    "observables":["magnetic field","ion plasma","spacecraft position"]
  }
}
```

Observed result: `recommended_sources` was `['cdaweb', 'spice']`. CDAWeb is the right first source for MMS measurements; SPICE/geometry is recommended for position context, but current mission support is not yet MMS-specific.

### 3. Observation plan

```json
{
  "tool":"plan_spedas_observation",
  "args":{
    "science_goal":"Determine whether MMS1 observed a magnetopause current sheet crossing by comparing burst/survey magnetic field and ion moments, with upstream solar-wind context",
    "target":"Earth magnetopause",
    "start":"2015-10-16T13:06:00Z",
    "stop":"2015-10-16T13:08:00Z",
    "observables":["magnetic field","ion plasma","spacecraft position"]
  }
}
```

Observed result: `status: success`, with `discover_cdaweb`, `fetch_or_compute_cdaweb`, `discover_spice`, `fetch_or_compute_spice`, and `preserve_provenance` phases.

### 4. CDAWeb discovery

```json
{"tool":"browse_data_sources","args":{"source_type":"cdaweb","query":"mms"}}
{"tool":"load_data_source","args":{"source_type":"cdaweb","source_id":"mms"}}
```

Observed result after this example's query-filter fix: `browse_data_sources(... query='mms')` returns only the MMS observatory record instead of the whole CDAWeb observatory catalog. `load_data_source` returns the MMS dataset catalog and the warning to check coverage before fetching.

### 5. Parameter discovery

```json
{"tool":"browse_data_parameters","args":{"source_type":"cdaweb","dataset_id":"MMS1_FGM_SRVY_L2"}}
{"tool":"browse_data_parameters","args":{"source_type":"cdaweb","dataset_id":"MMS1_FPI_FAST_L2_DIS-MOMS"}}
```

Useful variables found:

- FGM: `mms1_fgm_b_gse_srvy_l2`, `mms1_fgm_r_gse_srvy_l2`
- FPI DIS fast moments: `mms1_dis_numberdensity_fast`, `mms1_dis_bulkv_gse_fast`

One important caveat: `browse_data_parameters` advertised `mms1_fgm_b_gse_srvy_l2_clean`, but the downloaded daily CDF did not contain that variable. Agents should be prepared to retry with the non-`_clean` variable when fetch reports a variable-not-found error.

### 6. Bundle scaffold

```json
{
  "tool":"create_spedas_analysis_bundle",
  "args":{
    "study_name":"T001 MMS1 2015-10-16 magnetopause check",
    "output_dir":".t001_artifacts/bundle",
    "science_goal":"Check whether MMS1 observed a magnetopause current sheet crossing through B rotation, ion density/velocity changes, and spacecraft position.",
    "target":"Earth magnetopause",
    "start":"2015-10-16T13:06:00Z",
    "stop":"2015-10-16T13:08:00Z",
    "data_sources":["cdaweb","spice"]
  }
}
```

Observed result: bundle directories and request/provenance files were created successfully.

### 7. Data fetches

```json
{
  "tool":"fetch_data_product",
  "args":{
    "source_type":"cdaweb",
    "dataset_id":"MMS1_FGM_SRVY_L2",
    "parameters":["mms1_fgm_b_gse_srvy_l2_clean","mms1_fgm_r_gse_srvy_l2"],
    "start":"2015-10-16T13:06:00Z",
    "stop":"2015-10-16T13:08:00Z",
    "output_dir":".t001_artifacts/data",
    "format":"csv"
  }
}
```

Observed result: top-level `status: error`, but the payload wrote a CSV and successfully fetched position. The magnetic-field variable failed because the advertised `_clean` variable was absent in the downloaded CDF. This is not fully agent-friendly because the top-level result is an all-or-nothing `error` even when partial data are usable.

```json
{
  "tool":"fetch_data_product",
  "args":{
    "source_type":"cdaweb",
    "dataset_id":"MMS1_FPI_FAST_L2_DIS-MOMS",
    "parameters":["mms1_dis_numberdensity_fast","mms1_dis_bulkv_gse_fast"],
    "start":"2015-10-16T13:06:00Z",
    "stop":"2015-10-16T13:08:00Z",
    "output_dir":".t001_artifacts/data",
    "format":"csv",
    "limit":20
  }
}
```

Observed result: `status: success`; 27 rows were written. Density ranged approximately 6.16-13.79 cm^-3 and GSE ion velocity components had finite values. Note that `limit` is accepted for CDAWeb but did not limit the returned rows in this call, so agents should not rely on it as a strict row cap yet.

## What is still not autonomous-agent workable

1. MMS-specific science products are discoverable only by raw CDAWeb dataset names. There is no high-level MMS recipe such as “magnetopause crossing quicklook” that selects FGM/FPI/EDP products and preferred variables.
2. CDAWeb metadata can advertise variables that are not present in the fetched file; agents need retry heuristics (`*_clean` -> non-clean) and clearer MCP guidance.
3. Partial fetches are surfaced as top-level `error`, even when files and some variables are usable. A future status such as `partial_success` plus explicit failed/succeeded parameter lists would be easier to automate.
4. `limit` is described as a CDAWeb safety control, but it should be documented/implemented as either a row cap or a prefetch cap; in this MMS FPI run it did not cap the 27 returned rows.
5. SPICE/geometry planning is recommended for spacecraft position context, but the current geometry layer is not an MMS ephemeris solution; FGM position variables are currently the practical path.
6. No plot/quicklook tool exists, so an agent still has to leave MCP and write plotting code to verify a magnetopause signature.

## Validation value

This example is useful as a golden workflow candidate because it checks the agent loop from science question to source planning, dataset/parameter discovery, bundle creation, real CDAWeb fetch, and failure recovery for a mission with realistic complexity.
