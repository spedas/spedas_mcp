"""Cache management — status, cleanup, metadata refresh, catalog rebuild."""

import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _get_cache_root() -> Path:
    """Return the cache root directory."""
    from spedas_agent_kit.backends.cdaweb.config import get_cache_root
    return get_cache_root()


def _get_observatories_dir():
    """Return the observatories directory (from cache)."""
    from spedas_agent_kit.backends.cdaweb.catalog import get_observatories_dir
    return get_observatories_dir()


def _validate_name(name: str) -> str:
    """Validate a single path component (no traversal)."""
    if not name or not _SAFE_NAME_RE.match(name) or ".." in name:
        raise ValueError(f"Invalid name: {name!r}")
    return name


def _format_bytes(n: int) -> str:
    """Human-readable size (e.g., '2.3 GB')."""
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n /= 1024
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}"
    return f"{n:.1f} TB"


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _scan_directory(path: Path) -> dict:
    """Recursively scan a directory for file count and total bytes."""
    total_bytes = 0
    file_count = 0
    oldest_mtime = None
    newest_mtime = None

    def _walk(p: str) -> None:
        nonlocal total_bytes, file_count, oldest_mtime, newest_mtime
        try:
            with os.scandir(p) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        try:
                            stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        total_bytes += stat.st_size
                        file_count += 1
                        mt = stat.st_mtime
                        if oldest_mtime is None or mt < oldest_mtime:
                            oldest_mtime = mt
                        if newest_mtime is None or mt > newest_mtime:
                            newest_mtime = mt
                    elif entry.is_dir(follow_symlinks=False):
                        _walk(entry.path)
        except PermissionError:
            pass

    if path.exists():
        _walk(str(path))

    return {
        "path": str(path),
        "total_bytes": total_bytes,
        "total_human": _format_bytes(total_bytes),
        "file_count": file_count,
        "oldest_mtime": oldest_mtime,
        "newest_mtime": newest_mtime,
    }


def _scan_subdirectories(root: Path) -> list[dict]:
    """Scan each immediate subdirectory of root."""
    results = []
    if not root.exists():
        return results
    try:
        entries = sorted(root.iterdir())
    except PermissionError:
        return results
    for child in entries:
        if child.is_dir():
            stats = _scan_directory(child)
            stats["name"] = child.name
            results.append(stats)
    return results


# ---------------------------------------------------------------------------
# Cleanup helpers
# ---------------------------------------------------------------------------

def _delete_old_files(root: Path, older_than_days: int) -> tuple[int, int]:
    """Delete files older than N days within root."""
    cutoff = time.time() - older_than_days * 86400
    deleted_count = 0
    freed_bytes = 0

    def _walk(p: str) -> None:
        nonlocal deleted_count, freed_bytes
        try:
            with os.scandir(p) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        try:
                            stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if stat.st_mtime < cutoff:
                            size = stat.st_size
                            try:
                                os.unlink(entry.path)
                                deleted_count += 1
                                freed_bytes += size
                            except OSError:
                                pass
                    elif entry.is_dir(follow_symlinks=False):
                        _walk(entry.path)
        except PermissionError:
            pass

    if root.exists():
        _walk(str(root))
    _remove_empty_dirs(root)
    return deleted_count, freed_bytes


def _count_old_files(root: Path, older_than_days: int) -> tuple[int, int]:
    """Count files and bytes older than N days (for dry_run)."""
    cutoff = time.time() - older_than_days * 86400
    count = 0
    total_bytes = 0

    def _walk(p: str) -> None:
        nonlocal count, total_bytes
        try:
            with os.scandir(p) as it:
                for entry in it:
                    if entry.is_file(follow_symlinks=False):
                        try:
                            stat = entry.stat(follow_symlinks=False)
                        except OSError:
                            continue
                        if stat.st_mtime < cutoff:
                            count += 1
                            total_bytes += stat.st_size
                    elif entry.is_dir(follow_symlinks=False):
                        _walk(entry.path)
        except PermissionError:
            pass

    if root.exists():
        _walk(str(root))
    return count, total_bytes


def _remove_empty_dirs(root: Path) -> None:
    """Remove empty leaf directories under root (bottom-up)."""
    if not root.exists():
        return
    for dirpath, dirnames, filenames in os.walk(str(root), topdown=False):
        if not filenames and not dirnames:
            p = Path(dirpath)
            if p != root:
                try:
                    p.rmdir()
                except OSError:
                    pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cache_status(detail: bool = False) -> dict:
    """Scan cache directories and return usage statistics.

    Args:
        detail: If True, include per-subdirectory breakdown.

    Returns:
        Dict with status, categories (metadata, cdf_cache), total_bytes.
    """
    root = _get_cache_root()

    categories = {}
    for name in ("metadata", "cdf_cache"):
        cat_path = root / name
        stats = _scan_directory(cat_path)
        entry = {
            "path": stats["path"],
            "total_bytes": stats["total_bytes"],
            "total_human": stats["total_human"],
            "file_count": stats["file_count"],
        }
        if detail:
            entry["subcategories"] = _scan_subdirectories(cat_path)
        categories[name] = entry

    total = sum(c["total_bytes"] for c in categories.values())
    return {
        "status": "success",
        "categories": categories,
        "total_bytes": total,
        "total_human": _format_bytes(total),
    }


def cache_clean(
    category: str = "all",
    observatories: list[str] | None = None,
    older_than_days: int | None = None,
    dry_run: bool = True,
) -> dict:
    """Delete cached files with optional filters.

    Args:
        category: "metadata", "cdf_cache", or "all".
        observatories: Filter CDF cache to specific observatory subdirectories.
        older_than_days: Only delete files older than N days.
        dry_run: If True (default), report what would be deleted without deleting.

    Returns:
        Dict with deleted_count, freed_bytes, freed_human, dry_run.
    """
    root = _get_cache_root()
    if category == "all":
        targets = ["metadata", "cdf_cache"]
    else:
        targets = [category]

    total_deleted = 0
    total_freed = 0

    for cat in targets:
        cat_path = root / cat

        if cat == "cdf_cache" and observatories:
            for name in observatories:
                _validate_name(name)
                target = cat_path / name
                if not target.exists():
                    continue
                if older_than_days is not None:
                    if dry_run:
                        c, b = _count_old_files(target, older_than_days)
                    else:
                        c, b = _delete_old_files(target, older_than_days)
                else:
                    stats = _scan_directory(target)
                    c = stats["file_count"]
                    b = stats["total_bytes"]
                    if not dry_run:
                        shutil.rmtree(target, ignore_errors=True)
                total_deleted += c
                total_freed += b
        elif older_than_days is not None:
            if not cat_path.exists():
                continue
            if dry_run:
                c, b = _count_old_files(cat_path, older_than_days)
            else:
                c, b = _delete_old_files(cat_path, older_than_days)
            total_deleted += c
            total_freed += b
        else:
            if not cat_path.exists():
                continue
            stats = _scan_directory(cat_path)
            total_deleted += stats["file_count"]
            total_freed += stats["total_bytes"]
            if not dry_run:
                shutil.rmtree(cat_path, ignore_errors=True)
                cat_path.mkdir(parents=True, exist_ok=True)

    return {
        "status": "success",
        "deleted_count": total_deleted,
        "freed_bytes": total_freed,
        "freed_human": _format_bytes(total_freed),
        "dry_run": dry_run,
    }


def _fetch_from_master_cdf(dataset_id: str) -> dict | None:
    """Download a Master CDF and extract metadata. Delegates to metadata module."""
    from spedas_agent_kit.backends.cdaweb.metadata import _fetch_from_master_cdf as _impl
    return _impl(dataset_id)


def refresh_metadata(
    dataset_ids: list[str] | None = None,
    observatory: str | None = None,
) -> dict:
    """Re-fetch parameter metadata from Master CDFs.

    Args:
        dataset_ids: Specific dataset IDs to refresh.
        observatory: Refresh all cached datasets belonging to this observatory.
                     (Scans existing metadata cache files.)

    Returns:
        Dict with refreshed count, failed count, details.
    """
    root = _get_cache_root()
    meta_dir = root / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)

    ids_to_refresh: list[str] = []
    if dataset_ids:
        ids_to_refresh = list(dataset_ids)
    elif observatory:
        from spedas_agent_kit.backends.cdaweb.catalog import load_observatory_json
        try:
            obs_data = load_observatory_json(observatory)
            for inst in obs_data.get("instruments", {}).values():
                for ds_id in inst.get("datasets", {}):
                    if (meta_dir / f"{ds_id}.json").exists():
                        ids_to_refresh.append(ds_id)
        except FileNotFoundError:
            pass
    else:
        ids_to_refresh = [f.stem for f in meta_dir.glob("*.json")]

    if not ids_to_refresh:
        return {"status": "success", "refreshed": 0, "failed": 0, "details": {}}

    refreshed = 0
    failed = 0
    details = {}

    for ds_id in ids_to_refresh:
        info = _fetch_from_master_cdf(ds_id)
        if info is None:
            failed += 1
            details[ds_id] = "failed"
            continue

        cache_file = meta_dir / f"{ds_id}.json"
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(info, f, indent=2)
        refreshed += 1
        details[ds_id] = "refreshed"

    return {
        "status": "success",
        "refreshed": refreshed,
        "failed": failed,
        "details": details,
    }


def _fetch_cdaweb_time_ranges() -> dict[str, dict]:
    """Fetch start/stop dates for all datasets from CDAWeb REST API."""
    from spedas_agent_kit.backends.cdaweb.scripts.build_catalog import fetch_cdaweb_catalog
    catalog = fetch_cdaweb_catalog()
    return {
        ds_id: {"start_date": meta.get("start_date", ""),
                "stop_date": meta.get("stop_date", "")}
        for ds_id, meta in catalog.items()
    }


def refresh_time_ranges(observatory: str | None = None) -> dict:
    """Update start/stop dates in observatory catalog JSONs from CDAWeb.

    Fetches the CDAWeb dataset catalog (single HTTP call) and patches
    all observatory JSON files with fresh time coverage.

    Args:
        observatory: Only refresh this observatory stem. If None, refresh all.

    Returns:
        Dict with observatories_updated, datasets_updated, datasets_failed.
    """
    obs_dir = _get_observatories_dir()
    catalog = _fetch_cdaweb_time_ranges()

    if not catalog:
        return {
            "status": "error",
            "message": "Could not fetch CDAWeb catalog",
            "observatories_updated": 0,
            "datasets_updated": 0,
            "datasets_failed": 0,
        }

    observatories_updated = 0
    datasets_updated = 0
    datasets_failed = 0

    json_files = sorted(obs_dir.glob("*.json"))
    for filepath in json_files:
        stem = filepath.stem
        if observatory and stem != observatory:
            continue

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                obs_data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        stem_updated = 0
        for inst in obs_data.get("instruments", {}).values():
            for ds_id, ds_entry in inst.get("datasets", {}).items():
                meta = catalog.get(ds_id)
                if meta is None:
                    datasets_failed += 1
                    continue
                new_start = meta.get("start_date", "")
                new_stop = meta.get("stop_date", "")
                if new_start:
                    ds_entry["start_date"] = new_start
                if new_stop:
                    ds_entry["stop_date"] = new_stop
                stem_updated += 1

        if stem_updated > 0:
            obs_data.setdefault("_meta", {})
            obs_data["_meta"]["time_ranges_updated_at"] = (
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            )
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(obs_data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            observatories_updated += 1

        datasets_updated += stem_updated

    from spedas_agent_kit.backends.cdaweb.catalog import invalidate_observatory_cache
    invalidate_observatory_cache()

    return {
        "status": "success",
        "observatories_updated": observatories_updated,
        "datasets_updated": datasets_updated,
        "datasets_failed": datasets_failed,
    }


def _fetch_full_cdaweb_catalog() -> dict[str, dict]:
    """Fetch the full CDAWeb dataset catalog."""
    from spedas_agent_kit.backends.cdaweb.scripts.build_catalog import fetch_cdaweb_catalog
    return fetch_cdaweb_catalog()


def rebuild_catalog(observatory: str | None = None) -> dict:
    """Rebuild observatory catalog JSONs from CDAWeb REST API.

    Downloads the full CDAWeb dataset catalog and observatory groups,
    and regenerates observatory JSON files. This is the programmatic
    equivalent of:
        python -m spedas_agent_kit.backends.cdaweb.scripts.build_catalog [--observatory <slug>]

    Args:
        observatory: Only rebuild this observatory slug. If None, rebuild all.

    Returns:
        Dict with observatories_rebuilt count and details.
    """
    from spedas_agent_kit.backends.cdaweb.scripts.build_catalog import (
        build_all,
        fetch_observatory_groups,
    )

    obs_dir = _get_observatories_dir()
    obs_dir.mkdir(parents=True, exist_ok=True)

    groups = fetch_observatory_groups()
    if not groups:
        return {
            "status": "error",
            "message": "Could not fetch CDAWeb observatory groups",
            "observatories_rebuilt": 0,
        }

    catalog = _fetch_full_cdaweb_catalog()
    if not catalog:
        return {
            "status": "error",
            "message": "Could not fetch CDAWeb catalog",
            "observatories_rebuilt": 0,
        }

    built = build_all(groups, catalog, filter_slug=observatory, output_dir=obs_dir)

    from spedas_agent_kit.backends.cdaweb.catalog import invalidate_observatory_cache
    invalidate_observatory_cache()

    return {
        "status": "success",
        "observatories_rebuilt": len(built),
        "observatories": built,
    }
