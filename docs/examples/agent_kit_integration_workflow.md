# SPEDAS Agent Kit integration workflow

This workflow is for agent runtimes that want to use SPEDAS without copying
SPEDAS science logic into each runtime wrapper. It turns the Agent Kit into a
portable contract:

> install the MCP server, load the shared skills, run a golden science workflow,
> and verify the artifacts/provenance.

The same workflow should apply to Claude Code, Codex, OpenCode, Cursor, LingTai,
Claude Science, or any MCP-capable client.

## Layer contract

Keep the integration in three separate layers.

| Layer | Owns | Must not own |
|---|---|---|
| MCP layer | Tool/resource implementation, data-source routing, schemas, event presets, provenance resources, cache/env gates | Runtime-specific prompt style or wrapper-only science logic |
| Skill layer | Reusable `SKILL.md` workflows, guardrails, golden task playbooks, artifact-first instructions | MCP tool implementation or hidden runtime assumptions |
| Runtime adapter layer | Runtime-specific packaging, MCP config, command snippets, marketplace/plugin metadata | Duplicated SPEDAS science workflows or divergent tool contracts |

The canonical shared skill set lives in the package resources under
`src/spedas_agent_kit/resources/skills/` and is discoverable through the MCP skill
resources:

- `spedas-skill://index`
- `spedas-skill://skills/<skill-name>`

Runtime wrappers may mirror these files for packaging, but the package resource
copy is the source of truth. Wrapper-specific copies must stay synchronized and
should not introduce independent scientific behavior.

Use `scripts/export_packaged_skills.py --target <runtime-plugin>/skills --clean`
to materialize the canonical package-resource skill set into a wrapper directory
without hand-copying skills.

## Integration workflow for a new runtime

### 1. Connect the MCP server

Use the same Agent Kit MCP server command/config that existing wrappers validate.
Runtime packages should point to the Agent Kit package, not vendor a fork of the
server.

Preflight checklist:

- the runtime can launch the `spedas-agent-kit` MCP server;
- base tools are visible without enabling compatibility/debug gates;
- gated compatibility tools, if referenced, have in-band gate hints;
- core resources are visible, including the skill index, preset index, event
  preset resources, and the reproduction provenance schema.

### 2. Load the shared skills

Start with the shared skill index, then load only the skills relevant to the task.
For a thin wrapper, this normally means:

1. expose `spedas-workflow` as the default entry skill;
2. expose `spedas-skills-index` or `spedas-skill://index` for routing;
3. expose topical skills such as wave polarization, pitch-angle distribution,
   paper reproduction, switchbacks, ICME/storm, or multi-spacecraft gradients as
   task-specific skills;
4. keep wrapper instructions short: "use Agent Kit MCP tools/resources and these
   shared skills" rather than rewriting the science workflow.

### 3. Run the canonical science workflow

For a first golden workflow, follow the runtime-agnostic sequence from
`docs/examples/agent_workflow.md`:

1. **Search/plan**: call `search_spedas_data_sources(...)` and
   `plan_spedas_observation(...)` before choosing files or variables.
2. **Select through the unified data layer**: use `browse_data_sources(...)`,
   `load_data_source(...)`, and `browse_data_parameters(...)` before fetching.
3. **Create the analysis bundle**: call `create_spedas_analysis_bundle(...)` once
   the science question, time range, source, variables, and output directory are
   explicit, then keep the seeded `provenance/run.json` updated as tool calls
   and artifacts accumulate.
4. **Fetch/compute only after the plan is explicit**: use
   `fetch_data_product(...)` and any specialized analysis tools only after the
   runtime can explain the selected source and parameters.
5. **Return artifacts, not arrays**: summarize the run directory, figures, data
   products, hashes, and provenance paths instead of pasting large data into chat.

Suggested smoke missions, from fastest to most demanding:

- OMNI / geomagnetic indices for a lightweight solar-wind smoke;
- THEMIS overview for a classic SPEDAS mission workflow;
- MMS PAD or magnetopause workflow for high-value mission-specific guidance;
- PSP switchback / turbulence workflow for modern heliophysics examples.

### 4. Verify artifacts and provenance

A runtime integration is not complete when the tools merely list. It is complete
when a golden task produces inspectable artifacts.

Minimum evidence:

- MCP tool list and resource list were visible to the runtime;
- the chosen shared skill was loaded or explicitly cited;
- a run directory was created;
- output data/figure artifacts were written;
- the seeded `provenance/run.json` was updated, or another provenance
  artifact/reproduction schema output was written;
- the runtime response names artifact paths and caveats instead of embedding
  large data arrays;
- no wrapper-specific science logic was required.

### 5. Add or update the wrapper package

A runtime wrapper should be a thin adapter. A healthy wrapper usually contains
only:

```text
runtime-plugin/
  README.md                # install and smoke instructions
  plugin/manifest.json     # runtime-specific metadata
  .mcp.json or equivalent  # MCP server config pointing to Agent Kit
  skills/                  # synced shared skills, or a pointer to package resources
  commands/ or prompts/    # short runtime affordances only
```

If a wrapper needs new scientific behavior, add it to the Agent Kit MCP or shared
skill layer first, then let the wrapper consume that shared layer.

## PR acceptance checklist

Use this checklist when polishing Agent Kit for a new runtime or workflow:

- [ ] The change keeps MCP implementation, shared skills, and runtime adapter
      packaging separate.
- [ ] Any skill-content change started from the canonical packaged source in
      `src/spedas_agent_kit/resources/skills/`, and runtime fixture/wrapper
      copies were refreshed with the export helper or covered by a sync test.
- [ ] Runtime docs point to `spedas-skill://index` or the packaged skill catalog
      instead of copying the full skill library into prose.
- [ ] Golden workflow instructions follow the sequence:
      search/plan -> browse/load/parameters -> bundle -> fetch/compute ->
      artifact/provenance summary.
- [ ] The wrapper does not expand default MCP tool exposure without documenting
      the gate and user-facing discovery behavior.
- [ ] Validation includes `scripts/validate_plugin_packages.py`, relevant resource
      tests, and `git diff --check`.

## Why this matters

SPEDAS should be easy to integrate because the Agent Kit itself is cleanly
structured. Claude Science, Claude Code, Codex, OpenCode, and future scientific
agent systems should all see the same core contract: a stable MCP server, a
shared skill catalog, and reproducible artifact-first workflows.
