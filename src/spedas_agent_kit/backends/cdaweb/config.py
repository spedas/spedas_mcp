"""Package configuration — centralized settings for cache paths.

Usage:
    import spedas_agent_kit.backends.cdaweb as cdawebmcp
    cdawebmcp.configure(cache_dir="/path/to/cache")

Or from internal modules:
    from spedas_agent_kit.backends.cdaweb.config import get_cache_root
"""

import logging
import shutil
import threading
import time
from pathlib import Path

logger = logging.getLogger(__name__)

_cache_dir: Path | None = None
_bootstrapped: bool = False
_bootstrap_lock = threading.Lock()

# Bundled package data directories
_BUNDLED_DATA = Path(__file__).parent / "data"
_BUNDLED_OBSERVATORIES = _BUNDLED_DATA / "observatories"
_BUNDLED_METADATA = _BUNDLED_DATA / "metadata"

_REFRESH_STAMP = "last_time_range_refresh"
_REFRESH_INTERVAL_SECONDS = 86400  # 24 hours


def configure(cache_dir: str | Path | None = None) -> None:
    """Configure the vendored CDAWeb backend.

    Call once at startup to set the cache root directory. All runtime data
    (metadata cache, CDF file cache, validation overrides) lives under this root.

    Args:
        cache_dir: Root directory for all caches. Defaults to ~/.cdawebmcp/.
    """
    global _cache_dir, _bootstrapped
    if cache_dir is not None:
        _cache_dir = Path(cache_dir)
    else:
        _cache_dir = None
    _bootstrapped = False


def get_cache_root() -> Path:
    """Return the cache root directory.

    Resolution order:
    1. Value set by configure(cache_dir=...)
    2. Default: ~/.cdawebmcp/

    On first access, copies bundled data (observatories + metadata) into the cache
    directory if not already present.
    """
    global _bootstrapped
    root = _cache_dir if _cache_dir is not None else Path.home() / ".cdawebmcp"
    if not _bootstrapped:
        with _bootstrap_lock:
            if not _bootstrapped:
                _bootstrap(root)
                _bootstrapped = True
    return root


def _bootstrap(root: Path) -> None:
    """Copy bundled observatories and metadata into cache dir if not already present."""
    _copy_bundled_dir(_BUNDLED_OBSERVATORIES, root / "observatories")
    _copy_bundled_dir(_BUNDLED_METADATA, root / "metadata")


def needs_time_range_refresh() -> bool:
    """Check whether dataset time ranges should be refreshed.

    Returns True if no refresh has been done today (based on a timestamp
    file in the cache directory). Safe to call frequently — just a stat().
    """
    root = get_cache_root()
    stamp = root / _REFRESH_STAMP
    if not stamp.exists():
        return True
    age = time.time() - stamp.stat().st_mtime
    return age > _REFRESH_INTERVAL_SECONDS


def mark_time_range_refreshed() -> None:
    """Record that a time range refresh was completed."""
    root = get_cache_root()
    stamp = root / _REFRESH_STAMP
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text("")


def _copy_bundled_dir(src: Path, dst: Path) -> None:
    """Sync JSON files from bundled src to dst.

    Copies new files, and removes cache files that no longer exist in the
    bundled data (e.g. after observatory renames).
    """
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    bundled_names = {f.name for f in src.glob("*.json")}
    copied = 0
    for src_file in src.glob("*.json"):
        dst_file = dst / src_file.name
        if not dst_file.exists():
            shutil.copy2(src_file, dst_file)
            copied += 1
    # Remove stale cache files not in bundled data
    removed = 0
    for dst_file in dst.glob("*.json"):
        if dst_file.name not in bundled_names:
            dst_file.unlink()
            removed += 1
    if copied or removed:
        logger.info("Bootstrap %s: %d copied, %d stale removed", src.name, copied, removed)
