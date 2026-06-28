# Claude Code plugin: spedas-claude

This directory is the `spedas-claude` Claude Code plugin package for the in-repo `spedas-mcp` server.

It contributes:

- `.claude-plugin/plugin.json` — Claude Code plugin metadata.
- `.mcp.json` — MCP server entry named `spedas`, launched with `uvx` from the GitHub repo.
- `skills/spedas-workflow/SKILL.md` — workflow guidance for CDAWeb, PDS PPI, and SPICE.
- Focused science skills, including `multi-spacecraft-gradients` for curlometer, lingradest, and magnetic-null workflows.
- `commands/` — namespaced slash-command prompts for overview, CDAWeb, PDS, and SPICE workflows.

## Local development note

The packaged MCP definition still launches the shared `spedas-mcp` server:

```bash
uvx --with 'mcp>=1.26.0' --from git+https://github.com/spedas/spedas_mcp.git spedas-mcp
```

For local hacking before release, install this repo into the environment you use with Claude Code or edit `.mcp.json` to run `uv run --project /path/to/spedas-mcp --extra mcp spedas-mcp`.
