"""Observatory catalog — load observatory JSONs from cache and generate summaries."""

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")

# In-memory caches
_observatory_cache: list[dict] | None = None
_observatory_cache_mtime: float = 0
_dataset_to_observatory: dict[str, str] | None = None


def get_observatories_dir() -> Path:
    """Return the path to the observatories directory (bootstrapped cache)."""
    from spedas_mcp.backends.cdaweb.config import get_cache_root
    return get_cache_root() / "observatories"


def load_observatory_json(observatory_stem: str) -> dict:
    """Load an observatory JSON file by stem name (e.g., 'ace', 'parker_solar_probe_psp').

    Args:
        observatory_stem: Lowercase observatory identifier.

    Returns:
        Parsed observatory dict.

    Raises:
        FileNotFoundError: If no JSON file exists for this observatory.
    """
    if not observatory_stem or not _SAFE_NAME_RE.match(observatory_stem):
        raise ValueError(f"Invalid observatory name: {observatory_stem!r}")
    filepath = get_observatories_dir() / f"{observatory_stem}.json"
    if not filepath.exists():
        raise FileNotFoundError(f"Observatory file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def browse_observatories() -> list[dict]:
    """List all available observatories with summaries.

    Results are cached in memory and invalidated when the observatories
    directory mtime changes.

    Returns:
        List of dicts with: id, name, description, dataset_count, instruments.
    """
    global _observatory_cache, _observatory_cache_mtime

    obs_dir = get_observatories_dir()
    if not obs_dir.exists():
        return []

    # Check directory mtime to decide if cache is still valid
    try:
        dir_mtime = obs_dir.stat().st_mtime
    except OSError:
        dir_mtime = 0

    if _observatory_cache is not None and dir_mtime == _observatory_cache_mtime:
        return _observatory_cache

    results = []
    for filepath in sorted(obs_dir.glob("*.json")):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                observatory = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load %s: %s", filepath, e)
            continue

        # Count datasets across all instruments
        dataset_count = sum(
            len(inst.get("datasets", {}))
            for inst in observatory.get("instruments", {}).values()
        )

        profile = observatory.get("profile", {})
        results.append({
            "id": observatory.get("id", filepath.stem.upper()),
            "name": observatory.get("name", filepath.stem),
            "description": profile.get("description", ""),
            "dataset_count": dataset_count,
            "instruments": list(observatory.get("instruments", {}).keys()),
        })

    _observatory_cache = results
    _observatory_cache_mtime = dir_mtime
    return results


def _strip_pi_from_description(desc: str, pi_name: str | None) -> str:
    """Remove trailing PI info from CDAWeb description to avoid redundancy."""
    if not pi_name or not desc:
        return desc
    # CDAWeb descriptions often end with " - PI Name (email) (Institution)"
    # Find the last occurrence of " - " followed by PI-like text
    last_dash = desc.rfind(" - ")
    if last_dash > 0:
        after = desc[last_dash + 3 :]
        # Check if PI name (first+last) appears in the trailing text
        pi_parts = pi_name.split()
        if len(pi_parts) >= 2 and pi_parts[-1] in after:
            return desc[:last_dash].rstrip()
    return desc


def _date_only(iso: str) -> str:
    """Truncate ISO timestamp to date only: '2024-01-01T00:00:00.000Z' → '2024-01-01'."""
    return iso[:10] if len(iso) >= 10 else iso


def observatory_to_markdown(observatory: dict) -> str:
    """Convert an observatory JSON dict to a readable markdown dataset catalog.

    Args:
        observatory: Full observatory dict from load_observatory_json().

    Returns:
        Markdown string with dataset catalog.
    """
    lines = ["## Dataset Catalog", ""]
    for inst_key, inst_data in sorted(observatory.get("instruments", {}).items()):
        display_name = inst_data.get("name", inst_key)
        lines.append(f"### {display_name}")
        lines.append("")
        for ds_id, ds_info in sorted(inst_data.get("datasets", {}).items()):
            pi_name = ds_info.get("pi_name")
            desc = _strip_pi_from_description(
                ds_info.get("description", ""), pi_name
            )
            start = _date_only(ds_info.get("start_date", "?"))
            stop = _date_only(ds_info.get("stop_date", "?"))
            lines.append(f"- **{ds_id}**: {desc}")
            lines.append(f"  Coverage: {start} to {stop}")
        lines.append("")
    return "\n".join(lines)


def get_observatory_stem_from_dataset(dataset_id: str) -> str | None:
    """Find which observatory a dataset belongs to.

    Uses a cached reverse map (dataset_id -> observatory stem) that is built
    once from all observatory JSONs and invalidated by invalidate_observatory_cache().

    Args:
        dataset_id: CDAWeb dataset ID (e.g., 'AC_H2_MFI').

    Returns:
        Observatory stem (e.g., 'ace') or None.
    """
    global _dataset_to_observatory

    if _dataset_to_observatory is None:
        _dataset_to_observatory = {}
        obs_dir = get_observatories_dir()
        if not obs_dir.exists():
            return None
        for filepath in sorted(obs_dir.glob("*.json")):
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for inst in data.get("instruments", {}).values():
                    for ds_id in inst.get("datasets", {}):
                        _dataset_to_observatory[ds_id] = filepath.stem
            except (json.JSONDecodeError, OSError):
                continue

    return _dataset_to_observatory.get(dataset_id)


def invalidate_observatory_cache() -> None:
    """Invalidate in-memory caches. Call after rebuild_catalog or refresh_time_ranges."""
    global _observatory_cache, _observatory_cache_mtime, _dataset_to_observatory
    _observatory_cache = None
    _observatory_cache_mtime = 0
    _dataset_to_observatory = None
