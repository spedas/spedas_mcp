# SPEDAS Agent Kit agent plugin examples

Canonical runtime-specific plugin wrappers are now standalone SPEDAS org repos:

- <https://github.com/spedas/spedas_claude> — Claude Code plugin wrapper.
- <https://github.com/spedas/spedas_codex> — Codex plugin wrapper.

This repository still keeps lightweight in-repo fixtures for validation and local
experimentation:

- `plugins/spedas-claude/` — Claude Code wrapper fixture named `spedas-claude`.
- `.agents/plugins/spedas-codex/` — Codex wrapper fixture named `spedas-codex`,
  with `.agents/plugins/marketplace.json` for repo-scoped marketplace testing.

All wrappers should use this repository as the MCP implementation via
`git+https://github.com/spedas/spedas_agent_kit.git` and should prefer the unified data
layer tools (`browse_data_sources`, `load_data_source`, `browse_data_parameters`,
`fetch_data_product`, `manage_data_cache`) over low-level compatibility tools.

## Validation

```bash
python scripts/validate_plugin_packages.py
```
