"""Shared helpers for source-tree smoke scripts."""
from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"


def ensure_source_tree_on_path() -> None:
    """Prefer the checked-out source tree over any ambient installed package."""
    if SRC_DIR.exists():
        src = str(SRC_DIR)
        if src not in sys.path:
            sys.path.insert(0, src)


def source_tree_pythonpath(env: dict[str, str]) -> dict[str, str]:
    """Return env with repo src/ prepended to PYTHONPATH when available."""
    if not SRC_DIR.exists():
        return env
    env = dict(env)
    src = str(SRC_DIR)
    existing = env.get("PYTHONPATH")
    env["PYTHONPATH"] = src if not existing else src + os.pathsep + existing
    return env


def isolated_cache_env(tmp: str | Path, env: dict[str, str] | None = None) -> dict[str, str]:
    """Return env for no-fetch/no-download smoke runs with isolated caches."""
    base = source_tree_pythonpath(dict(os.environ if env is None else env))
    root = Path(tmp)
    base.setdefault("XHELIO_CDAWEB_CACHE_DIR", str(root / "cdaweb"))
    base.setdefault("XHELIO_SPICE_KERNEL_DIR", str(root / "spice"))
    base.setdefault("PDSMCP_CACHE_DIR", str(root / "pds"))
    return base
