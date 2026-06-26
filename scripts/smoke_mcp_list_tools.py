#!/usr/bin/env python3
"""Smoke-test the unified SPEDAS MCP stdio server by listing tools only.

This is intentionally a no-fetch/no-download smoke: it starts the server with
isolated CDAWeb and SPICE cache directories (unless the environment already sets
those locations), performs MCP initialize + list_tools, verifies the advertised
tool names, and exits.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_TOOLS = [
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
    "browse_observatories",
    "load_observatory",
    "browse_parameters",
    "fetch_data",
    "browse_pds_missions",
    "load_pds_mission",
    "browse_pds_parameters",
    "fetch_pds_data",
    "list_spice_missions",
    "get_ephemeris",
    "compute_distance",
    "transform_coordinates",
    "list_coordinate_frames",
    "manage_cdaweb_cache",
    "manage_pds_cache",
    "manage_spice_kernels",
    "transform_timeseries_coordinates",
    "generate_fac_matrix",
    "analyze_minvar_coordinates",
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
        default="spedas_mcp",
        help="Python module to run as the MCP server (default: spedas_mcp)",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="spedas-mcp-smoke-") as tmp:
        env = os.environ.copy()
        env.setdefault("XHELIO_CDAWEB_CACHE_DIR", str(Path(tmp) / "cdaweb"))
        env.setdefault("XHELIO_SPICE_KERNEL_DIR", str(Path(tmp) / "spice"))
        env.setdefault("PDSMCP_CACHE_DIR", str(Path(tmp) / "pds"))
        tools = anyio.run(_list_tools, args.module, env)

    missing = [name for name in EXPECTED_TOOLS if name not in tools]
    unexpected = [name for name in tools if name not in EXPECTED_TOOLS]
    ok = not missing and not unexpected
    payload = {
        "ok": ok,
        "tool_count": len(tools),
        "tools": tools,
        "expected_tools": EXPECTED_TOOLS,
        "missing": missing,
        "unexpected": unexpected,
        "note": "list_tools only; no CDAWeb/PDS data fetch or SPICE kernel download requested",
    }

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"SPEDAS MCP list-tools smoke: {'OK' if ok else 'FAIL'}")
        print("tools:", ", ".join(tools))
        if missing:
            print("missing:", ", ".join(missing), file=sys.stderr)
        if unexpected:
            print("unexpected:", ", ".join(unexpected), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
