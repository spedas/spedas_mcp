#!/usr/bin/env python3
"""Smoke-test real optional analysis backend registration.

This is a no-fetch/no-download smoke for the ``spedas-agent-kit[analysis]``
extra. It imports the exact modules/attributes used by
``spedas_agent_kit.optional_backends.ANALYSIS_REQUIRED_IMPORTS`` and verifies
that the default MCP server registers the full analysis tool group when those
imports are present.
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import io
import json
from collections.abc import Sequence

from _smoke_runtime import ensure_source_tree_on_path

ensure_source_tree_on_path()

from spedas_agent_kit.optional_backends import (
    ANALYSIS_REQUIRED_IMPORTS,
    ANALYSIS_TOOL_NAMES,
    analysis_dependencies_available,
)
from spedas_agent_kit.server import create_server


def _probe_required_imports() -> tuple[list[str], list[dict[str, str]]]:
    """Return (missing, captured_notes) for the analysis import probes."""
    missing: list[str] = []
    notes: list[dict[str, str]] = []
    for module_name, attr_name in ANALYSIS_REQUIRED_IMPORTS:
        stdout = io.StringIO()
        stderr = io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                module = importlib.import_module(module_name)
        except Exception as exc:  # pragma: no cover - exercised by smoke failures
            missing.append(f"{module_name}: {type(exc).__name__}: {exc}")
        else:
            if attr_name is not None and not hasattr(module, attr_name):
                missing.append(f"{module_name}.{attr_name}: missing attribute")
        out = stdout.getvalue().strip()
        err = stderr.getvalue().strip()
        if out or err:
            notes.append(
                {
                    "module": module_name,
                    "stdout": out,
                    "stderr": err,
                }
            )
    return missing, notes


async def _default_tool_names() -> list[str]:
    server = create_server()
    return [tool.name for tool in await server.list_tools()]


def _missing_analysis_tools(tool_names: Sequence[str]) -> list[str]:
    names = set(tool_names)
    return [name for name in ANALYSIS_TOOL_NAMES if name not in names]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    args = parser.parse_args()

    missing_imports, import_notes = _probe_required_imports()
    analysis_available = analysis_dependencies_available()
    tool_names = asyncio.run(_default_tool_names())
    missing_tools = _missing_analysis_tools(tool_names)
    ok = not missing_imports and analysis_available and not missing_tools
    payload = {
        "ok": ok,
        "analysis_dependencies_available": analysis_available,
        "required_imports_count": len(ANALYSIS_REQUIRED_IMPORTS),
        "analysis_tool_count": len(ANALYSIS_TOOL_NAMES),
        "default_tool_count": len(tool_names),
        "missing_imports": missing_imports,
        "missing_analysis_tools": missing_tools,
        "analysis_tools": list(ANALYSIS_TOOL_NAMES),
        "import_notes": import_notes,
        "note": "analysis import + default list_tools smoke only; no data fetch or kernel download requested",
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"SPEDAS Agent Kit analysis import smoke: {'OK' if ok else 'FAIL'}")
        print(f"analysis_dependencies_available: {analysis_available}")
        print(f"default_tool_count: {len(tool_names)}")
        if missing_imports:
            print("missing imports:")
            for item in missing_imports:
                print(f"  - {item}")
        if missing_tools:
            print("missing analysis tools:")
            for item in missing_tools:
                print(f"  - {item}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
