# spedas_agent_kit

> **What is an `ANATOMY.md`?** A code-cited structural map of one folder, written for an agent reader, sitting next to the code it describes (the LingTai anatomy convention). Every structural claim points at a `file:line`. ~80-line cap per file. **Reading and maintaining are the same act:** if anatomy disagrees with code, fix the anatomy in the same change. This is the repo-root anatomy — the only file with a complete child enumeration; descend it to navigate by structure instead of grep.

## What this is

The SPEDAS Agent Kit core: one package/repo that gives AI agents a unified MCP door to heliophysics data (CDAWeb, PDS, SPICE, HAPI, FDSN), a pyspedas-backed analysis layer, and packaged shared workflow **skills**. A thin **facade** (`server.py`) does dispatch + validation + artifact discipline; the science lives in wrapped backends. Runtime wrappers such as Claude Code/Codex/OpenCode should stay thin and package or sync the shared skills from this core.

## Components

- **`src/spedas_agent_kit/`** — the package (see `src/spedas_agent_kit/ANATOMY.md`). Entry: `__init__.py:6` `main()` → `server.create_server().run()`; `__main__.py` enables `python -m spedas_agent_kit`.
- **`src/spedas_agent_kit/server.py`** — the FastMCP facade. `create_server()` at `server.py:1200` registers tools through `_register_tool()` `server.py:1228`, so every advertised tool carries MCP `ToolAnnotations` and `meta.surface`; gating helpers `_analysis_dependencies_available()` `server.py:161` and `_compat_tools_enabled()` `server.py:259` decide the advertised surface. Avoid hard-coding this large file's total line count; it shifts whenever tools are added.
- **`src/spedas_agent_kit/workflows.py`** (1087 lines) — pure-Python science-planning logic behind the workflow tools (`search_data_sources` `workflows.py:816`, `plan_observation` `workflows.py:870`, …).
- **`src/spedas_agent_kit/datasources/`** — optional HAPI + FDSN backends (see `datasources/ANATOMY.md`).
- **`src/spedas_agent_kit/analysis/`** — pyspedas-backed analysis tools (see `analysis/ANATOMY.md`).
- **`src/spedas_agent_kit/resources/skills/`** — canonical packaged shared workflow skills for runtime wrappers.
- **`plugins/spedas-claude/` and `.agents/plugins/spedas-codex/`** — in-repo runtime packaging fixtures; they are examples/thin wrappers around this core, not the canonical science logic.
- **`tests/`** — pytest suite mirroring each module and packaged resources.
- **`scripts/smoke_mcp_list_tools.py`** — lists the advertised tool surface (the consolidation check).

## Connections

- **Client → facade.** MCP stdio JSON-RPC; client sees tool names/schemas only, receives `{status, file_path, stats}` — never bulk arrays (artifact-first).
- **Facade → backends.** `server.py` lazily imports the in-tree vendored `spedas_agent_kit.backends.cdaweb` / `pds` / `spice` packages (data + geometry) and, when `[analysis]` is present, the `analysis/` functions and `datasources/`. Unified `fetch_data_product(source_type=...)` dispatches by source.
- **Runtime wrapper → server.** Thin wrapper fixtures launch the `spedas-agent-kit` server; wrapper commands/skills should reference the unified tools and packaged shared skills from this core.

## Composition

- **Parent:** repo root (this file).
- **Subfolders with their own anatomy:** `src/spedas_agent_kit/`, `src/spedas_agent_kit/analysis/`, `src/spedas_agent_kit/datasources/`.
- **Mapped narratively (no own anatomy yet):** `plugins/spedas-claude/`, `tests/`, `docs/`, `scripts/`.

## State

- No server-side persistent state. Caches live in the user's home (`~/.cdawebmcp/`, `~/.pdsmcp/`, `~/.xhelio_spice/kernels/`), managed via `manage_data_cache`.
- Surface gating is runtime, not stored: `[analysis]` importability + `SPEDAS_AGENT_KIT_COMPAT_TOOLS` + `SPEDAS_AGENT_KIT_DATASOURCE_TOOLS` env flags. In the current lean environment the smoke script advertises 13 base tools, 21 with compat enabled, and 17 with the datasource flag (the four direct HAPI/FDSN tools, demoted out of the default surface in issue #87); installing `[analysis]` adds the optional analysis group, currently 13 tool names in `ANALYSIS_TOOL_NAMES` (`server.py:34`). Advertised tools also expose `meta.surface` (`primary`, `advanced`, `compat`, `datasource`) plus side-effect hints through MCP `ToolAnnotations`.
- Analysis/skills are artifact-first: packaged shared skills live under `src/spedas_agent_kit/resources/skills/`; bulk results are written under a `create_spedas_analysis_bundle` directory (`requests/ data/ plots/ provenance/ notes/`).

## Notes

- The bug-prone seam is **facade↔backend adapters**, not the dispatch — most fixed issues lived there (numpy serialization, unit conventions, fill values, probe paths). Validate adapter I/O shapes, not just that a call returns.
- Consolidation: the compat/cache tools are *hidden*, not deleted — the unified tools call the same underlying functions. New capability lands as a `source_type` or a **skill**, not a new top-level tool.
