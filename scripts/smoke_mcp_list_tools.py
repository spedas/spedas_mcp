#!/usr/bin/env python3
"""Smoke-test the unified SPEDAS Agent Kit stdio server by listing tools only.

This is intentionally a no-fetch/no-download smoke: it starts the server with
isolated CDAWeb and SPICE cache directories (unless the environment already sets
those locations), performs MCP initialize + list_tools, verifies the advertised
tool names, and exits.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from _smoke_runtime import ensure_source_tree_on_path, isolated_cache_env

ensure_source_tree_on_path()

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from spedas_agent_kit.optional_backends import (
    ANALYSIS_TOOL_NAMES as ANALYSIS_EXPECTED_TOOLS,
    analysis_dependencies_available,
)

COMPAT_CDAWEB_PDS_TOOLS = [
    "browse_observatories",
    "load_observatory",
    "browse_parameters",
    "fetch_data",
    "browse_pds_missions",
    "load_pds_mission",
    "browse_pds_parameters",
    "fetch_pds_data",
]

BASE_EXPECTED_TOOLS = [
    "spedas_overview",
    "browse_data_sources",
    "load_data_source",
    "browse_data_parameters",
    "fetch_data_product",
    "manage_data_cache",
    "search_spedas_data_sources",
    "plan_spedas_observation",
    "compare_cdaweb_pds_spice",
    "create_spedas_analysis_bundle",
    "get_ephemeris",
    "compute_distance",
    "transform_coordinates",
]

# Direct HAPI/FDSN data-source tools are demoted out of the default surface
# (issue #87); advertised only with SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1.
DATASOURCE_TOOLS = [
    "browse_hapi_catalog",
    "fetch_hapi_data",
    "browse_fdsn_datasets",
    "fetch_fdsn_data",
]

async def _list_tools(module: str, env: dict[str, str]) -> list[str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        env=env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.list_tools()
            return [tool.name for tool in result.tools]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument(
        "--module",
        default="spedas_agent_kit",
        help="Python module to run as the MCP server (default: spedas_agent_kit)",
    )
    parser.add_argument(
        "--compat-tools",
        action="store_true",
        help="Set SPEDAS_AGENT_KIT_COMPAT_TOOLS=1 and expect legacy CDAWeb/PDS tools",
    )
    parser.add_argument(
        "--datasource-tools",
        action="store_true",
        help="Set SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1 and expect direct HAPI/FDSN tools",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="spedas-agent-kit-smoke-") as tmp:
        env = isolated_cache_env(tmp)
        if args.compat_tools:
            env["SPEDAS_AGENT_KIT_COMPAT_TOOLS"] = "1"
        else:
            env.pop("SPEDAS_AGENT_KIT_COMPAT_TOOLS", None)
        if args.datasource_tools:
            env["SPEDAS_AGENT_KIT_DATASOURCE_TOOLS"] = "1"
        else:
            env.pop("SPEDAS_AGENT_KIT_DATASOURCE_TOOLS", None)
        tools = anyio.run(_list_tools, args.module, env)

    expected_tools = list(BASE_EXPECTED_TOOLS)
    if args.compat_tools:
        expected_tools.extend(COMPAT_CDAWEB_PDS_TOOLS)
    if args.datasource_tools:
        expected_tools.extend(DATASOURCE_TOOLS)
    analysis_available = analysis_dependencies_available()
    if analysis_available:
        expected_tools.extend(ANALYSIS_EXPECTED_TOOLS)

    missing = [name for name in expected_tools if name not in tools]
    unexpected = [name for name in tools if name not in expected_tools]
    ok = not missing and not unexpected
    payload = {
        "ok": ok,
        "tool_count": len(tools),
        "tools": tools,
        "expected_tools": expected_tools,
        "analysis_extra_detected": analysis_available,
        "compat_tools_enabled": args.compat_tools,
        "compat_env_flag": "SPEDAS_AGENT_KIT_COMPAT_TOOLS=1",
        "datasource_tools_enabled": args.datasource_tools,
        "datasource_env_flag": "SPEDAS_AGENT_KIT_DATASOURCE_TOOLS=1",
        "missing": missing,
        "unexpected": unexpected,
        "note": "list_tools only; no CDAWeb/PDS data fetch or SPICE kernel download requested",
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"SPEDAS Agent Kit list-tools smoke: {'OK' if ok else 'FAIL'}")
        print("tools:", ", ".join(tools))
        if missing:
            print("missing:", ", ".join(missing), file=sys.stderr)
        if unexpected:
            print("unexpected:", ", ".join(unexpected), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
