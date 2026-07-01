#!/usr/bin/env python3
"""Smoke-test stdio MCP resources without fetching science data.

This starts the SPEDAS Agent Kit stdio server with isolated cache directories,
performs MCP ``initialize`` + ``list_resources`` + selected ``read_resource``
requests, and verifies that core skill/preset/schema resources are discoverable
and readable. It is intentionally no-fetch/no-download.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from _smoke_runtime import ensure_source_tree_on_path, isolated_cache_env

ensure_source_tree_on_path()

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED_RESOURCES = [
    "spedas-skill://index",
    "spedas-skill://skills/spedas-workflow",
    "spedas-skill://skills/spedas-skills-index",
    "spedas-preset://schemas/reproduction_provenance",
    "spedas-preset://schemas/analysis_bundle_run",
]


def _content_text(content: Any) -> str:
    text = getattr(content, "text", None)
    if text is not None:
        return text
    blob = getattr(content, "blob", None)
    if blob is not None:
        return str(blob)
    return ""


async def _probe_resources(module: str, env: dict[str, str]) -> dict[str, Any]:
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", module],
        env=env,
    )
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            listed = await session.list_resources()
            resources = {str(resource.uri): resource for resource in listed.resources}
            read_results: dict[str, dict[str, Any]] = {}
            unreadable: dict[str, str] = {}
            for uri in EXPECTED_RESOURCES:
                if uri not in resources:
                    continue
                try:
                    result = await session.read_resource(uri)
                except Exception as exc:  # pragma: no cover - smoke failure path
                    unreadable[uri] = f"{type(exc).__name__}: {exc}"
                    continue
                contents = list(getattr(result, "contents", []))
                text = "\n".join(_content_text(item) for item in contents)
                entry: dict[str, Any] = {
                    "content_count": len(contents),
                    "chars": len(text),
                    "mime_type": getattr(contents[0], "mimeType", None) if contents else None,
                }
                if uri.endswith("analysis_bundle_run") or uri.endswith("reproduction_provenance"):
                    try:
                        schema = json.loads(text)
                    except Exception as exc:  # pragma: no cover - smoke failure path
                        unreadable[uri] = f"schema_json_error: {type(exc).__name__}: {exc}"
                    else:
                        entry["schema_title"] = schema.get("title")
                        entry["schema_version_enum"] = (
                            schema.get("properties", {})
                            .get("schema_version", {})
                            .get("enum", [])
                        )
                read_results[uri] = entry
            resource_uris = sorted(resources)
            missing = [uri for uri in EXPECTED_RESOURCES if uri not in resources]
            empty_reads = [
                uri for uri, entry in read_results.items() if entry.get("chars", 0) <= 0
            ]
            return {
                "resource_count": len(resource_uris),
                "expected_resources": EXPECTED_RESOURCES,
                "missing_resources": missing,
                "unreadable_resources": unreadable,
                "empty_reads": empty_reads,
                "read_results": read_results,
                "preset_event_resource_count": sum(
                    1 for uri in resource_uris if uri.startswith("spedas-preset://events/")
                ),
            }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument(
        "--module",
        default="spedas_agent_kit",
        help="Python module to run as the MCP server (default: spedas_agent_kit)",
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory(prefix="spedas-agent-kit-resource-smoke-") as tmp:
        payload = anyio.run(_probe_resources, args.module, isolated_cache_env(Path(tmp)))

    ok = not payload["missing_resources"] and not payload["unreadable_resources"] and not payload["empty_reads"]
    payload.update(
        {
            "ok": ok,
            "note": "list/read MCP resources only; no CDAWeb/PDS data fetch or SPICE kernel download requested",
        }
    )

    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"SPEDAS Agent Kit MCP resource smoke: {'OK' if ok else 'FAIL'}")
        print(f"resources: {payload['resource_count']}")
        if payload["missing_resources"]:
            print("missing:", ", ".join(payload["missing_resources"]), file=sys.stderr)
        if payload["unreadable_resources"]:
            print("unreadable:", json.dumps(payload["unreadable_resources"], indent=2), file=sys.stderr)
        if payload["empty_reads"]:
            print("empty reads:", ", ".join(payload["empty_reads"]), file=sys.stderr)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
