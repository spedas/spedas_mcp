#!/usr/bin/env python3
"""Smoke-test analysis-bundle creation and run provenance updates.

This calls the in-process Agent Kit server, reads the analysis-bundle run schema
resource, creates a tiny analysis bundle, appends one compact tool_call/artifact/
caveat entry to ``provenance/run.json``, and verifies the updated record remains
machine-readable. It does not fetch archive data or download kernels.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from _smoke_runtime import ensure_source_tree_on_path

ensure_source_tree_on_path()

from spedas_agent_kit.server import create_server

SCHEMA_URI = "spedas-preset://schemas/analysis_bundle_run"


def _read_text_content(block: Any) -> str:
    return getattr(block, "content", None) or getattr(block, "text", "")


async def _create_and_update_bundle(output_root: Path) -> dict[str, Any]:
    server = create_server(include_analysis_tools=False)
    schema_blocks = await server.read_resource(SCHEMA_URI)
    schema_text = _read_text_content(schema_blocks[0]) if schema_blocks else ""
    schema = json.loads(schema_text)
    content, _metadata = await server.call_tool(
        "create_spedas_analysis_bundle",
        {
            "study_name": "Analysis bundle run provenance smoke",
            "output_dir": str(output_root),
            "science_goal": "Validate analysis-bundle run provenance scaffolding without fetching data",
            "target": "solar wind",
            "start": "2024-01-01T00:00:00Z",
            "stop": "2024-01-01T00:10:00Z",
            "data_sources": ["cdaweb"],
        },
    )
    payload = json.loads(content[0].text)
    run_path = Path(payload["paths"]["run_provenance"])
    run = json.loads(run_path.read_text(encoding="utf-8"))
    smoke_note = Path(payload["paths"]["notes"]) / "smoke-artifact.txt"
    smoke_note.write_text("analysis-bundle smoke artifact; no archive data fetched\n", encoding="utf-8")
    run["tool_calls"].append(
        {
            "tool": "create_spedas_analysis_bundle",
            "status": payload["status"],
            "output_paths": {
                "bundle_dir": payload["bundle_dir"],
                "run_provenance": str(run_path),
            },
        }
    )
    run["artifacts"].append(
        {
            "path": str(smoke_note),
            "role": "smoke_note",
            "source_tool": "smoke_analysis_bundle.py",
        }
    )
    run["caveats"].append(
        {
            "scope": "smoke",
            "message": "No archive data was fetched; this only validates bundle scaffolding.",
        }
    )
    run_path.write_text(json.dumps(run, indent=2), encoding="utf-8")
    updated = json.loads(run_path.read_text(encoding="utf-8"))
    structural_failures: list[str] = []
    if updated.get("schema_version") != "spedas-analysis-bundle-run-v1":
        structural_failures.append("unexpected schema_version")
    if updated.get("resource_hints", {}).get("provenance_schema_uri") != SCHEMA_URI:
        structural_failures.append("schema hint mismatch")
    for key in ("tool_calls", "artifacts", "caveats"):
        if not updated.get(key):
            structural_failures.append(f"{key} was not updated")
    schema_validation = "not_run"
    try:
        import jsonschema  # type: ignore[import-not-found]
    except Exception:
        schema_validation = "skipped_missing_jsonschema"
    else:
        jsonschema.validate(updated, schema)
        schema_validation = "ok"
    return {
        "bundle_status": payload["status"],
        "bundle_dir": payload["bundle_dir"],
        "run_provenance": str(run_path),
        "schema_uri": SCHEMA_URI,
        "schema_title": schema.get("title"),
        "schema_validation": schema_validation,
        "tool_calls_len": len(updated["tool_calls"]),
        "artifacts_len": len(updated["artifacts"]),
        "caveats_len": len(updated["caveats"]),
        "structural_failures": structural_failures,
        "note": "creates local bundle scaffolding only; no archive data fetch or kernel download requested",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    parser.add_argument(
        "--output-dir",
        help="Optional parent directory for the smoke bundle. Defaults to a temporary directory that is removed unless --keep-output is set.",
    )
    parser.add_argument("--keep-output", action="store_true", help="Keep the temporary output directory")
    args = parser.parse_args()

    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    if args.output_dir:
        output_root = Path(args.output_dir)
        output_root.mkdir(parents=True, exist_ok=True)
        retained = True
    elif args.keep_output:
        output_root = Path(tempfile.mkdtemp(prefix="spedas-agent-kit-bundle-smoke-"))
        retained = True
    else:
        temp_dir = tempfile.TemporaryDirectory(prefix="spedas-agent-kit-bundle-smoke-")
        output_root = Path(temp_dir.name)
        retained = False

    try:
        payload = asyncio.run(_create_and_update_bundle(output_root))
        ok = payload["bundle_status"] in {"success", "created"} and not payload["structural_failures"]
        payload.update({"ok": ok, "output_retained": retained})
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"SPEDAS Agent Kit analysis-bundle smoke: {'OK' if ok else 'FAIL'}")
            print(f"bundle_dir: {payload['bundle_dir']}")
            if payload["structural_failures"]:
                print("structural failures:", ", ".join(payload["structural_failures"]), file=sys.stderr)
        return 0 if ok else 1
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
