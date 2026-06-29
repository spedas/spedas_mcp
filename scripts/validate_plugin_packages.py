#!/usr/bin/env python3
"""Validate the repo's Claude Code and Codex plugin wrapper packages."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPATIBILITY = ROOT / "plugins" / "spedas-agent-kit-compatibility.json"
SERVER_JSON = ROOT / "server.json"


def load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - failure path prints useful context
        raise SystemExit(f"Invalid JSON {path}: {exc}") from exc


def require(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Missing required plugin file: {path.relative_to(ROOT)}")


def _server_manifest_env_names() -> set[str]:
    manifest = load_json(SERVER_JSON)
    names: set[str] = set()
    for package in manifest.get("packages", []):
        for env in package.get("environmentVariables", []):
            name = env.get("name")
            if isinstance(name, str):
                names.add(name)
    return names


def _validate_server_manifest_env_flags() -> None:
    manifest_env = _server_manifest_env_names()
    compatibility = load_json(COMPATIBILITY)
    required_flags = {"SPEDAS_AGENT_KIT_COMPAT_TOOLS"}
    datasource_flag = compatibility.get("datasource_env_flag")
    if isinstance(datasource_flag, str) and datasource_flag:
        required_flags.add(datasource_flag.split("=", 1)[0])

    missing = sorted(required_flags - manifest_env)
    if missing:
        raise SystemExit(
            "server.json: missing environmentVariables for public Agent Kit gate "
            f"flags: {', '.join(missing)}"
        )


def _expected_mcp_args() -> list[str]:
    manifest = load_json(COMPATIBILITY)
    tools = manifest.get("base_tools", [])
    if manifest.get("base_tool_count") != len(tools):
        raise SystemExit(
            "plugins/spedas-agent-kit-compatibility.json: base_tool_count does not "
            "match base_tools length"
        )
    return [
        "--with",
        manifest["mcp_requirement"],
        "--from",
        manifest["spedas_agent_kit_source"],
        "spedas-agent-kit",
    ]


def _validate_mcp_server(mcp_path: Path, server: dict) -> None:
    assert server["command"] == "uvx"
    expected = _expected_mcp_args()
    if server.get("args") != expected:
        raise SystemExit(
            f"{mcp_path.relative_to(ROOT)}: spedas MCP args must match "
            f"plugins/spedas-agent-kit-compatibility.json; got {server.get('args')!r}"
        )
    env = server.get("env", {})
    for name in ["XHELIO_CDAWEB_CACHE_DIR", "PDSMCP_CACHE_DIR", "XHELIO_SPICE_KERNEL_DIR"]:
        if name not in env:
            raise SystemExit(f"{mcp_path.relative_to(ROOT)}: missing cache env {name}")


def validate_claude() -> None:
    root = ROOT / "plugins" / "spedas-claude"
    require(COMPATIBILITY)
    require(root / ".claude-plugin" / "plugin.json")
    require(root / ".mcp.json")
    require(root / "skills" / "spedas-workflow" / "SKILL.md")
    for name in ["overview", "cdaweb", "pds", "spice"]:
        require(root / "commands" / f"{name}.md")

    manifest = load_json(root / ".claude-plugin" / "plugin.json")
    assert manifest["name"] == "spedas-claude"
    assert manifest["version"]
    mcp_path = root / ".mcp.json"
    mcp = load_json(mcp_path)
    _validate_mcp_server(mcp_path, mcp["mcpServers"]["spedas"])


def validate_codex() -> None:
    root = ROOT / ".agents" / "plugins" / "spedas-codex"
    require(COMPATIBILITY)
    require(root / ".codex-plugin" / "plugin.json")
    require(root / ".mcp.json")
    require(root / "skills" / "spedas-workflow" / "SKILL.md")
    require(ROOT / ".agents" / "plugins" / "marketplace.json")

    manifest = load_json(root / ".codex-plugin" / "plugin.json")
    assert manifest["name"] == "spedas-codex"
    assert manifest["skills"] == "./skills/"
    assert manifest["mcpServers"] == "./.mcp.json"
    mcp_path = root / ".mcp.json"
    mcp = load_json(mcp_path)
    _validate_mcp_server(mcp_path, mcp["mcp_servers"]["spedas"])
    marketplace = load_json(ROOT / ".agents" / "plugins" / "marketplace.json")
    assert marketplace["plugins"][0]["source"]["path"] == "./spedas-codex"


def main() -> int:
    _validate_server_manifest_env_flags()
    validate_claude()
    validate_codex()
    print("Plugin package validation: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
