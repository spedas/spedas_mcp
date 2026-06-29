# Codex plugin fixture: spedas-codex

This in-repo fixture mirrors the standalone <https://github.com/spedas/spedas_codex>
plugin wrapper for the shared `spedas_agent_kit` MCP server. The canonical skills are packaged under `src/spedas_agent_kit/resources/skills/`; this fixture is a runtime packaging example.

It contains:

- `.codex-plugin/plugin.json` — Codex plugin manifest.
- `.mcp.json` — plugin-scoped MCP server entry named `spedas`.
- `skills/spedas-workflow/SKILL.md` — reusable Codex guidance for the unified
  SPEDAS data layer and science workflow layer.

The repo also includes `.agents/plugins/marketplace.json`, pointing at
`./spedas-codex`, so Codex can treat this repository as a local marketplace
source while developing the plugin fixture.

## Compatibility pin

This in-repo fixture follows `../../../plugins/spedas-agent-kit-compatibility.json`: it
tracks `spedas_agent_kit` from the `main` ref, bounds the
MCP protocol package as `mcp>=1.26.0,<2`, and expects the base `list_tools`
surface to advertise 17 tools. Refresh the manifest, this `.mcp.json`, and the
Claude fixture together after any server tool-surface change.
