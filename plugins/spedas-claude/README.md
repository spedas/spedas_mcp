# Claude Code plugin: spedas-claude

This directory is the `spedas-claude` Claude Code plugin package for the in-repo `spedas-agent-kit` server. The canonical skills are packaged under `src/spedas_agent_kit/resources/skills/`; this fixture is a runtime packaging example.

It contributes:

- `.claude-plugin/plugin.json` — Claude Code plugin metadata.
- `.mcp.json` — MCP server entry named `spedas`, launched with `uvx` from the GitHub repo.
- `skills/spedas-workflow/SKILL.md` — workflow guidance for CDAWeb, PDS PPI, and SPICE.
- Focused science skills, including `multi-spacecraft-gradients` for curlometer, lingradest, and magnetic-null workflows.
- `commands/` — namespaced slash-command prompts for overview, CDAWeb, PDS, and SPICE workflows.

## Local development note

The packaged MCP definition still launches the shared `spedas-agent-kit` server:

```bash
uvx --with 'mcp>=1.26.0' --from git+https://github.com/spedas/spedas_agent_kit.git spedas-agent-kit
```

For local hacking before release, install this repo into the environment you use with Claude Code or edit `.mcp.json` to run `uv run --project /path/to/spedas-agent-kit --extra mcp spedas-agent-kit`.

## Compatibility pin

This in-repo fixture follows `../spedas-agent-kit-compatibility.json`: it pins
`spedas_agent_kit` from the `main` ref, bounds the MCP
protocol package as `mcp>=1.26.0,<2`, and expects the base `list_tools` surface to
advertise 17 tools. Refresh the manifest, this `.mcp.json`, and the Codex fixture
together after any server tool-surface change.
