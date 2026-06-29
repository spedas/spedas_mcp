# spedas_mcp

> **What is an `ANATOMY.md`?** A code-cited structural map of one folder, written for an agent reader, sitting next to the code it describes (the LingTai anatomy convention). Every structural claim points at a `file:line`. ~80-line cap per file. **Reading and maintaining are the same act:** if anatomy disagrees with code, fix the anatomy in the same change. This is the repo-root anatomy — the only file with a complete child enumeration; descend it to navigate by structure instead of grep.

## What this is

An MCP server that gives an AI agent one unified door to heliophysics data (CDAWeb, PDS, SPICE, HAPI, FDSN) plus a pyspedas-backed analysis layer. A thin **facade** (`server.py`) does dispatch + validation + artifact discipline; the science lives in wrapped backends. Shipped as a Claude Code plugin under `plugins/spedas-claude/` whose agent-facing surface is a small unified tool set + a library of analysis **skills**.

## Components

- **`src/spedas_mcp/`** — the package (see `src/spedas_mcp/ANATOMY.md`). Entry: `__init__.py:6` `main()` → `server.create_server().run()`; `__main__.py` enables `python -m spedas_mcp`.
- **`src/spedas_mcp/server.py`** — the FastMCP facade. `create_server()` at `server.py:1072` registers every `@mcp.tool`; gating helpers `_analysis_dependencies_available()` `server.py:157` and `_compat_tools_enabled()` `server.py:176` decide the advertised surface. Avoid hard-coding this large file's total line count; it shifts whenever tools are added.
- **`src/spedas_mcp/workflows.py`** (1087 lines) — pure-Python science-planning logic behind the workflow tools (`search_data_sources` `workflows.py:816`, `plan_observation` `workflows.py:870`, …).
- **`src/spedas_mcp/datasources/`** — optional HAPI + FDSN backends (see `datasources/ANATOMY.md`).
- **`src/spedas_mcp/analysis/`** — pyspedas-backed analysis tools (see `analysis/ANATOMY.md`).
- **`plugins/spedas-claude/`** — the Claude Code plugin: `commands/` (slash commands), `skills/` (15 skill folders total, including the index and anatomy-maintenance skill), `.mcp.json`, `hooks/`.
- **`tests/`** (10 files, ~7k lines) — pytest suite mirroring each module.
- **`scripts/smoke_mcp_list_tools.py`** — lists the advertised tool surface (the consolidation check).

## Connections

- **Client → facade.** MCP stdio JSON-RPC; client sees tool names/schemas only, receives `{status, file_path, stats}` — never bulk arrays (artifact-first).
- **Facade → backends.** `server.py` lazily imports the in-tree vendored `spedas_mcp.backends.cdaweb` / `pds` / `spice` packages (data + geometry) and, when `[analysis]` is present, the `analysis/` functions and `datasources/`. Unified `fetch_data_product(source_type=...)` dispatches by source.
- **Plugin → server.** `plugins/spedas-claude/.mcp.json` launches the `spedas` server; commands + skills reference its unified tools.

## Composition

- **Parent:** repo root (this file).
- **Subfolders with their own anatomy:** `src/spedas_mcp/`, `src/spedas_mcp/analysis/`, `src/spedas_mcp/datasources/`.
- **Mapped narratively (no own anatomy yet):** `plugins/spedas-claude/`, `tests/`, `docs/`, `scripts/`.

## State

- No server-side persistent state. Caches live in the user's home (`~/.cdawebmcp/`, `~/.pdsmcp/`, `~/.xhelio_spice/kernels/`), managed via `manage_data_cache`.
- Surface gating is runtime, not stored: `[analysis]` importability + `SPEDAS_MCP_COMPAT_TOOLS` env flag. In the current lean environment the smoke script advertises 17 base tools and 25 tools with compat enabled; installing `[analysis]` adds the optional analysis group, currently 13 tool names in `ANALYSIS_TOOL_NAMES` (`server.py:34`).
- Analysis/skills are artifact-first: bulk results written under a `create_spedas_analysis_bundle` directory (`requests/ data/ plots/ provenance/ notes/`).

## Notes

- The bug-prone seam is **facade↔backend adapters**, not the dispatch — most fixed issues lived there (numpy serialization, unit conventions, fill values, probe paths). Validate adapter I/O shapes, not just that a call returns.
- Consolidation: the compat/cache tools are *hidden*, not deleted — the unified tools call the same underlying functions. New capability lands as a `source_type` or a **skill**, not a new top-level tool.
