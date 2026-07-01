# SPEDAS Agent Kit shared skills

These are the canonical shared workflow skills for the SPEDAS Agent Kit. Runtime
wrappers such as `spedas_claude`, `spedas_codex`, and future OpenCode/Cursor
packages should stay thin and package/sync these skills rather than owning
scientific workflow logic independently.

## Runtime integration workflow

The packaged skills are one half of the runtime-neutral Agent Kit contract. The
other half is the MCP server and resource surface. Runtime wrappers should follow
the workflow in [`docs/examples/agent_kit_integration_workflow.md`](/docs/examples/agent_kit_integration_workflow.md). To materialize the canonical skill set into a runtime wrapper, use:

```bash
python scripts/export_packaged_skills.py --target <runtime-plugin>/skills --clean
```

Then:

1. connect the Agent Kit MCP server;
2. discover the shared skill catalog through `spedas-skill://index` and
   `spedas-skill://skills/<skill-name>`;
3. run the canonical SPEDAS sequence from `docs/examples/agent_workflow.md`:
   search/plan -> browse/load/parameters -> bundle -> fetch/compute ->
   artifact/provenance summary;
4. keep Claude Code, Codex, OpenCode, Claude Science, and future wrappers thin by
   consuming this shared MCP + skill layer rather than copying scientific logic.
