---
name: mms-basic-workflows
description: Plan MMS FGM/MEC/EDP/SCM/FPI/HPCA route-scout and overview workflows as Agent Kit skill/resource recipes without expanding the default MCP tool surface.
---

# MMS basic workflows

Use this skill when the user asks for an MMS mission overview, magnetic
reconnection route scout, FGM/MEC orbit context, EDP electric-field/spacecraft-potential context, SCM wave context, FPI/HPCA
particle overview, or MMS four-spacecraft preflight. This is a **router skill**:
it connects MMS mission vocabulary to existing Agent Kit data/provenance tools,
specialized analysis skills, and external PySPEDAS loaders without creating one
MCP tool per MMS loader.

Compose it with:

- `pyspedas-load-planning` for `trange`, `probe`, `data_rate`, `level`,
  `datatype`, `time_clip=True`, `available=True`, `notplot`, `no_update`,
  runtime `CONFIG['download_only']`, and run-scoped `suffix` hygiene.
- `tplot-data-lifecycle` for variable naming, support-data choices, plotting,
  export, and cleanup without pasting arrays into chat.
- `spedas-heritage-vocabulary` for IDL `mms_load_*` / PySPEDAS route translation.
- `spedas-workflow` for existing MMS reconnection/EDR guardrails and the MMS
  magnetopause example; keep single-spacecraft current proxies labeled as proxies.
- `multi-spacecraft-gradients` and `dual-spacecraft-timing` only after four MMS
  magnetic-field streams and four position streams pass cadence/frame checks.
- `magnetopause-lmn-analysis`, `boundary-minimum-variance`, `model-lmn-boundary`,
  `apply-rotation-matrix`, and `hodogram` for LMN/MVA/FAC handoffs after a real
  boundary interval exists.
- `wave-polarization` and `power-spectral-density` for SCM/FGM wave or spectral
  analysis; do not reimplement polarization logic here.
- `pitch-angle-distribution` and `particle-velocity-slice` for particle products
  only when the exact FPI/HPCA distribution route, magnetic-field input, cadence,
  and calibration caveats are verified.

## MCP/default-surface boundary

This skill adds **no MCP tool**. Keep the default Agent Kit `list_tools` surface
compact. The names below are external PySPEDAS runtime routes, not Agent Kit MCP
names:

```yaml
external_runtime_route:
  not_an_mcp_tool: true
  examples:
    - pyspedas.projects.mms.fgm
    - pyspedas.projects.mms.mec
    - pyspedas.projects.mms.scm
    - pyspedas.projects.mms.fsm
    - pyspedas.projects.mms.fpi
    - pyspedas.projects.mms.hpca
    - pyspedas.projects.mms.edp
    - pyspedas.projects.mms.edi
    - pyspedas.projects.mms.eis
    - pyspedas.projects.mms.feeps
    - pyspedas.projects.mms.aspoc
    - pyspedas.projects.mms.dsp
    - pyspedas.projects.mms.bss
    - pyspedas.projects.mms.state
    - pyspedas.projects.mms.tetrahedron_qf
    - pyspedas.projects.mms.curlometer
    - pyspedas.projects.mms.lingradest
    - pyspedas.projects.mms.particles.mms_part_getspec.mms_part_getspec
    - pyspedas.projects.mms.particles.mms_part_slice2d.mms_part_slice2d
    - pyspedas.projects.mms.fpi_tools.mms_pad_fpi.mms_pad_fpi
    - pyspedas.projects.mms.fpi_tools.mms_load_fpi_calc_pad.mms_load_fpi_calc_pad
```

Do not invent MCP tools such as `mms_fgm`, `mms_mec`, `mms_scm`, `mms_fpi`,
`mms_hpca`, `mms_curlometer`, `mms_lingradest`, `mms_pad_fpi`, or `load_mms`.
MCP-only clients should use the resource/plan/fetch verbs:

1. `create_spedas_analysis_bundle(...)` before any fetch.
2. `spedas_overview()` and this skill for the initial MMS route scout.
3. `search_spedas_data_sources(...)` / `browse_data_sources(source_type="cdaweb", query="MMS")`.
4. `load_data_source(...)`, `browse_data_parameters(...)`, then
   `fetch_data_product(...)` for a bounded dataset/parameter/time range.
5. If exact PySPEDAS MMS loader behavior is required, record it as an external
   runtime requirement with `external_runtime_route.not_an_mcp_tool: true`.

## Workflow cards

### 1. Single-spacecraft FGM + MEC overview

Use this for a fast MMS context bundle around a candidate reconnection interval,
boundary crossing, wave packet, or particle burst. Treat it as a **route scout**
until exact products and timing are verified.

- Start with one probe (`mms1` unless the user names another) and a narrow time
  range. Public MMS archives can be large; prefer minutes for burst products and
  tens of minutes for survey products.
- Browse candidate CDAWeb dataset families first, then verify exact parameter
  names and availability:
  - `MMS1_FGM_SRVY_L2` or `MMS1_FGM_BRST_L2` for magnetic-field context.
  - `MMS1_MEC_SRVY_L2_EPHT89D` / ephemeris-quaternion variants or matching
    MEC/state products for position and ephemeris context.
  - Optional `MMS1_EDP_FAST_L2_DCE` / spacecraft-potential products when electric
    field or particle-correction context is part of the question.
  - Optional `MMS1_SCM_SRVY_L2_SCSRVY` / burst SCM products when wave context is
    part of the question.
- Return artifact paths, variable/parameter names, sample counts, actual clipped
  time span, coordinate frame, cadence, and caveats. Do not paste arrays.

### 2. Four-spacecraft reconnection / curlometer preflight

Use this when the user asks for MMS current density, curlometer, linear magnetic
field gradients, boundary normals, reconnection rate, magnetic nulls, or timing.
This card is a **precondition checklist**, not a claim generator.

Before routing to `multi-spacecraft-gradients`, `dual-spacecraft-timing`, or an
external `pyspedas.projects.mms.curlometer` / `lingradest` runtime route, require:

- four magnetic-field vector streams (`mms1`-`mms4` FGM, same data rate/level);
- four MEC/state position streams in a common coordinate frame;
- documented cadence, interpolation, time-base, and quality/flag handling;
- common LMN/FAC/GSE/GSM frame choice and transformation provenance;
- a rejected-interval note when any spacecraft/product is missing or empty.

If only one or two streams are ready, label the result `single_spacecraft_route_scout`
or `not_gradient_ready`. Do not upgrade a quick-look panel to a curlometer or
reconnection conclusion.

### 3. SCM / wave context

Use this when the user asks for MMS whistler/chorus/EMIC/wave packets,
search-coil context, or spectral cross-checks.

- Pair SCM with FGM background field and position context.
- Browse survey vs burst SCM products and count samples after clipping before
  recommending a cadence family.
- Pair SCM/EDP wave or Poynting-flux context with explicit FGM background-field
  and coordinate/rate alignment; EDP version handling and spacecraft potential
  choices belong in provenance.
- Route polarization/spectral analysis to `wave-polarization`,
  `power-spectral-density`, or `spectral-cross-coherence` after the data window is
  non-empty and the background field is identified.
- Record empty variables, rejected cadence families, and any external PySPEDAS
  wave helper as `external_runtime_route.not_an_mcp_tool: true`.

### 4. FPI particle moments, distributions, and pitch-angle planning

Use this when the user asks for ion/electron moments, agyrotropy proxies,
velocity-space slices, pitch-angle distributions, or FPI burst particles.

- Start with moments products (`dis-moms`, `des-moms`) for overview plots before
  distribution products (`dis-dist`, `des-dist`). Distribution files are larger
  and should use narrow intervals and artifact-first outputs.
- Candidate CDAWeb families to browse include `MMS1_FPI_FAST_L2_DIS-MOMS`,
  `MMS1_FPI_FAST_L2_DES-MOMS`, `MMS1_FPI_BRST_L2_DIS-DIST`, and burst
  distribution/moment counterparts. Verify
  exact dataset IDs and parameter names before fetching.
- External helper functions such as `pyspedas.projects.mms.fpi_tools.mms_get_fpi_dist.mms_get_fpi_dist`,
  `pyspedas.projects.mms.particles.mms_part_getspec.mms_part_getspec`,
  `pyspedas.projects.mms.particles.mms_part_slice2d.mms_part_slice2d`,
  `pyspedas.projects.mms.fpi_tools.mms_pad_fpi.mms_pad_fpi`, and
  `pyspedas.projects.mms.fpi_tools.mms_load_fpi_calc_pad.mms_load_fpi_calc_pad`
  are not MCP tools. Use them only in a runtime that can import PySPEDAS and
  record the route in provenance.
- For pitch-angle distribution, explicitly identify the magnetic-field input
  (`magf`) used for pitch-angle bins. If `magf` comes from an embedded/support
  variable, record that; if a dedicated FGM variable is required, load and align
  it first. Do not claim PAD/FAC quality without a verified `magf`, species,
  energy bins, and cadence.
- Route final PAD interpretation to `pitch-angle-distribution`; route 2-D slices
  to `particle-velocity-slice` only after units, species, spacecraft potential,
  sun contamination, and distribution support are checked.

### 5. HPCA / energetic particle context

Use HPCA, EIS, and FEEPS as particle context with instrument-specific caveats, not
as generic scalar time series.

- Candidate external routes include `pyspedas.projects.mms.hpca`, `eis`, and
  `feeps`, plus helpers such as HPCA spin sums and FEEPS PAD/omni/spin-average
  routines.
- Record species (`hplus`, `oplus`, `heplus`, etc.), field of view, energy bins,
  contamination/sun-removal corrections, and data units.
- Use overview labels such as `particle_context_smoke` until calibration and
  instrument-specific quality flags are reviewed.

### 6. Burst segments, EDP/scpot, orbit/context, and overview plots

Use MMS segment/orbit helpers as planning context, not as final science evidence.

- External routes include burst/SROI segment helpers, `mms_overview_plot`,
  `mms_orbit_plot`, `state`, `mec`, `edp`, and `tetrahedron_qf`.
- Before requesting burst data, inspect burst/SROI segment availability where the
  runtime supports it; if no segment overlaps, fall back to survey/fast products
  or ask for a different interval.
- Record whether the interval is survey or burst, and why the selected data rate
  is adequate for the science question.
- Use `available=True`, `no_update=True`, `notplot=True`, and, where a runtime
  exposes it, global `CONFIG['download_only']=True` for route discovery or
  cache checks before creating large tplot state. MMS loader signatures do not all
  expose a per-call `downloadonly=True` argument; do not invent one.

## External PySPEDAS loader option evidence

Common MMS loader options seen across PySPEDAS wrappers include:

- `trange`, `probe`, `data_rate`, `level`, `datatype`, `suffix`, `varformat`,
  `varnames`, `available=True`, `notplot`, `no_update`, `time_clip`, and runtime
  `CONFIG['download_only']`;
- FGM/MEC/SCM/FPI/HPCA/EDP/EDI/EIS/FEEPS/ASPOC/DSP routes each add instrument
  choices such as coordinate, species, data units, or distribution/moment
  datatype;
- multi-spacecraft helpers (`curlometer`, `lingradest`) require already-loaded
  field and position variables, not just product names.

Use run-scoped `suffix` to avoid tplot name collisions. Always record whether the
run used `available=True`, `no_update=True`, `notplot=True`, runtime
`CONFIG['download_only']`, live archive fetch, or cache-only mode.

## IDL/SPEDAS vocabulary bridge

Useful MMS vocabulary for user requests:

- `mms_load_fgm` -> FGM route (`pyspedas.projects.mms.fgm`) or CDAWeb `MMS?_FGM_*`
  browse/fetch; record coordinate frame and flag-removal choices.
- `mms_load_mec`, `mms_load_state`, `mms_load_tetrahedron_qf` -> orbit, position,
  attitude, and tetrahedron-quality context; route geometry claims to the
  appropriate geometry/gradient skill.
- `mms_load_edp` -> DCE/DCV/ACE/HMFE electric-field and spacecraft-potential
  context; record major-version handling, coordinate/rate alignment, and scpot
  use for particle corrections.
- `mms_load_scm`, `mms_load_fsm`, `mms_load_edi` -> wave/electric field context;
  require cadence and non-empty sample checks.
- `mms_load_fpi`, `mms_get_fpi_dist`, `mms_part_getspec`, `mms_part_slice2d`,
  `mms_pad_fpi`, `mms_load_fpi_calc_pad` -> particle distributions/PAD/slices;
  require species, datatype, support-data, `magf`, and calibration caveats.
- `mms_load_hpca`, `mms_load_eis`, `mms_load_feeps` -> ion/energetic-particle
  context with species/energy/FOV/correction caveats.
- `mms_curl`, `mms_lingradest`, `mms_cotrans_lmn`, and `mms_qcotrans` are analysis
  handoffs; record method, inputs, interval, coordinate frame, and quality gates
  before using outputs in conclusions.

## Minimal route-scout template

```yaml
study_name: mms_basic_route_scout
quality_label: route_scout
probe: mms1
trange: ["2015-10-16T13:05:00Z", "2015-10-16T13:10:00Z"]
agent_kit_route:
  source_type: cdaweb
  candidate_datasets:
    - MMS1_FGM_SRVY_L2
    - MMS1_MEC_SRVY_L2_EPHT89D
    - MMS1_EDP_FAST_L2_DCE
    - MMS1_SCM_SRVY_L2_SCSRVY
    - MMS1_FPI_FAST_L2_DIS-MOMS
    - MMS1_FPI_FAST_L2_DES-MOMS
    - MMS1_HPCA_SRVY_L2_MOMENTS
  browse_parameters_first: true
  next_skills:
    - pyspedas-load-planning
    - tplot-data-lifecycle
    - multi-spacecraft-gradients
    - pitch-angle-distribution
external_runtime_route:
  not_an_mcp_tool: true
  pyspedas_loaders:
    - pyspedas.projects.mms.fgm
    - pyspedas.projects.mms.mec
    - pyspedas.projects.mms.scm
    - pyspedas.projects.mms.fpi
    - pyspedas.projects.mms.hpca
    - pyspedas.projects.mms.curlometer
    - pyspedas.projects.mms.lingradest
provenance_required:
  - probe_or_probe_list
  - dataset_id_or_loader
  - variable_or_parameter_subset
  - requested_trange
  - actual_clipped_range
  - data_rate_level_datatype
  - cache_mode
  - coordinate_frame
  - magf_source_when_particles_use_pitch_angles
  - artifact_paths
  - quality_label
  - caveats
```

## Provenance and reporting checklist

For every MMS workflow artifact, include:

- probe(s), dataset IDs or exact external loader names, and loader options;
- requested and actual clipped intervals;
- data rate (`srvy`, `fast`, `brst`), level, datatype, species, EDP/scpot role, coordinate frame,
  cadence, units, and support-data choices;
- sample counts for every panel used in a conclusion;
- cache/data-access mode and public-archive caveats;
- `magf` source, energy bins, species, and distribution/moment route for particle
  PAD/slice work;
- labels such as `route_scout`, `particle_context_smoke`,
  `single_spacecraft_route_scout`, `not_gradient_ready`, `cache_only`, or
  `paper_exact` only when justified;
- links to downstream skills used for LMN/MVA, wave polarization, PAD, velocity
  slices, or multi-spacecraft analysis.

Do not upgrade a route scout to a scientific conclusion merely because a plot or
variable name exists. Require actual non-empty samples, correct products, and the
analysis-specific preconditions owned by the downstream skill.
