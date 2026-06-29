# src/spedas_mcp — the package

## What this is

The Python package: a FastMCP **facade** that registers heliophysics tools and dispatches them to wrapped backends. Almost no science lives here — the value is unified `source_type` dispatch, input validation, the structured-error contract, kernel-download gating, and the artifact-first response shape.

## Components

- **`__init__.py:6`** `main()` — entry point; builds and runs the server (`create_server().run()`). `__main__.py` makes `python -m spedas_mcp` work.
- **`server.py`** — the whole facade. Key anchors:
  - `create_server()` `server.py:1072` — constructs the FastMCP and registers all `@mcp.tool` closures (17 base/optional data+geometry tools in the lean environment, plus 13 optional analysis tools when dependencies import, plus 8 legacy compat tools when enabled). One big factory; tools are nested closures, so grep by tool name finds the `def`.
  - `_analysis_dependencies_available()` `server.py:157` (driven by `_ANALYSIS_REQUIRED_IMPORTS` `server.py:55`; names listed in `ANALYSIS_TOOL_NAMES` `server.py:34`) — gates the analysis group; probes pyspedas submodules (a wrong probe path here once hid the group — keep entries at the function-bearing module).
  - `_compat_tools_enabled()` `server.py:176` — gates the 8 legacy per-source tools behind `SPEDAS_MCP_COMPAT_TOOLS`.
  - `_normalize_source_type()` `server.py:1846`, `_wrap_data_payload()` `server.py:1926` — the unified-dispatch core: route by `source_type`, wrap backend output.
  - `_error_response()` `server.py:398` — the structured `{status,code,message,hint}` contract (issue #27).
  - `_install_argument_validation_guard()` `server.py:3201` — turns FastMCP arg-validation failures into structured errors.
- **`workflows.py`** (1087 lines) — pure-Python planning behind the workflow tools: `search_data_sources` `:816`, `compare_sources` `:848`, `plan_observation` `:870`, `create_analysis_bundle` `:1016`. No backend dependency → robust; this is why bugs cluster in adapters, not here.

## Connections

- **In:** MCP client calls a registered tool → its closure in `create_server()`.
- **Out:** lazily imports the in-tree vendored `backends.cdaweb`/`backends.pds`/`backends.spice` packages for data+geometry; calls `analysis/` and `datasources/` functions for the analysis/optional tools.
- Dispatch fans `fetch_data_product`/`browse_*`/`manage_data_cache` to the right backend by `source_type`.

## Composition

- **Parent:** repo root (`ANATOMY.md`).
- **Subfolders:** `analysis/` (`analysis/ANATOMY.md`), `datasources/` (`datasources/ANATOMY.md`).

## State

- None persistent in-process. Writes only via the data tools (to backend caches / bundle dirs). Surface composition is decided at `create_server()` time from import-availability + the env flag.

## Notes

- `server.py` is large and closure-heavy by design (FastMCP registration). Navigate by tool name → its nested `def`, or by the helper anchors above — not by reading top-to-bottom.
- Gating is all-or-nothing per group: one failing analysis probe drops all analysis tools. When adding an analysis tool, add its backend to `_ANALYSIS_REQUIRED_IMPORTS` at the **submodule** path.
