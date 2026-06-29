"""Data validation — CDF variable inspection, metadata sync, override management.

Automatically compares fetched CDF data against cached Master CDF metadata,
detects discrepancies (phantom/undocumented parameters), and maintains
an append-only validation archive per dataset.

Override files are stored at:
    ~/.cdawebmcp/overrides/{mission_stem}/{dataset_id}.json
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

try:
    import cdflib
except ImportError:
    cdflib = None

# CDF types to skip when inspecting data variables
_SKIP_TYPES = {
    "CDF_EPOCH", "CDF_EPOCH16", "CDF_TIME_TT2000",
    "CDF_CHAR", "CDF_UCHAR",
}


def _get_overrides_dir() -> Path:
    """Return the overrides directory."""
    from spedas_mcp.backends.cdaweb.config import get_cache_root
    return get_cache_root() / "overrides"


def inspect_cdf_variables(cdf_path: Path) -> list[dict]:
    """Read actual data variables from a CDF file.

    Opens the CDF and returns metadata for each variable that is a plottable
    data variable (skips epoch/time types, character types, support_data, and
    metadata VAR_TYPE variables).

    Args:
        cdf_path: Path to a local CDF file.

    Returns:
        List of dicts with keys: name, type, size, units, description.
    """
    data_cdf = cdflib.CDF(str(cdf_path))
    data_info = data_cdf.cdf_info()
    all_vars = list(data_info.zVariables) + list(data_info.rVariables)

    result = []
    for var_name in all_vars:
        try:
            var_inq = data_cdf.varinq(var_name)
            if var_inq.Data_Type_Description.split()[0] in _SKIP_TYPES:
                continue
            var_attrs = data_cdf.varattsget(var_name)
            var_type = var_attrs.get("VAR_TYPE", "")
            if isinstance(var_type, (bytes, np.bytes_)):
                var_type = var_type.decode()
            if isinstance(var_type, np.ndarray):
                var_type = str(var_type)
            if var_type in ("support_data", "metadata"):
                continue

            units = var_attrs.get("UNITS", "") or ""
            if isinstance(units, np.ndarray):
                units = str(units)
            description = (var_attrs.get("CATDESC", "")
                           or var_attrs.get("FIELDNAM", "") or "")
            if isinstance(description, np.ndarray):
                description = str(description)

            dim_sizes = list(var_inq.Dim_Sizes) if var_inq.Dim_Sizes else [1]

            result.append({
                "name": var_name,
                "type": var_inq.Data_Type_Description,
                "size": dim_sizes,
                "units": units,
                "description": description,
            })
        except Exception:
            continue

    return result


def _deep_merge(base: dict, patch: dict) -> dict:
    """Deep-merge patch into base (mutates base). Lists are replaced, not appended."""
    for key, value in patch.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def load_override(dataset_id: str, mission_stem: str) -> dict | None:
    """Load a dataset override file.

    Args:
        dataset_id: CDAWeb dataset ID.
        mission_stem: Mission stem directory name.

    Returns:
        Parsed override dict, or None if no override exists.
    """
    overrides_dir = _get_overrides_dir()
    path = overrides_dir / mission_stem / f"{dataset_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            logger.warning("Override %s is not a JSON object; ignoring", path)
            return None
        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Cannot read override %s: %s", path, e)
        return None


def save_override(dataset_id: str, patch: dict, mission_stem: str) -> dict:
    """Read-modify-write a dataset override file.

    Deep-merges patch into existing override (or creates new).

    Args:
        dataset_id: CDAWeb dataset ID.
        patch: Sparse dict to merge into the override.
        mission_stem: Mission stem directory name.

    Returns:
        The full override dict after merging.
    """
    overrides_dir = _get_overrides_dir()
    ds_dir = overrides_dir / mission_stem
    ds_dir.mkdir(parents=True, exist_ok=True)
    path = ds_dir / f"{dataset_id}.json"

    existing: dict = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError):
            existing = {}

    _deep_merge(existing, patch)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2, ensure_ascii=False)
        f.write("\n")

    return existing


def sync_metadata(
    dataset_id: str,
    cdf_path: Path,
    *,
    source_url: str = "",
    observatory_stem: str | None = None,
) -> None:
    """Compare data CDF variables against cached metadata and record discrepancies.

    Called automatically on the first CDF file during fetch_data(). If the data
    CDF contains variables not in the cached metadata (or vice versa), writes
    annotations to the override file so discrepancies are visible to future calls.

    Each validation is recorded as a structured entry in ``_validations`` with
    provenance (source URL, filename, timestamp). If the same source URL has
    already been validated, the sync is skipped.

    Args:
        dataset_id: CDAWeb dataset ID.
        cdf_path: Path to the downloaded data CDF file.
        source_url: URL the CDF was downloaded from (for dedup).
        observatory_stem: Observatory stem (e.g., 'ace'). Auto-detected if None.
    """
    from spedas_mcp.backends.cdaweb.metadata import get_cache_dir

    # Find cached metadata
    cache_dir = get_cache_dir()
    cache_file = cache_dir / f"{dataset_id}.json"
    if not cache_file.exists():
        logger.debug("Metadata sync skipped for %s: no local cache", dataset_id)
        return

    try:
        cached_info = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        logger.debug("Metadata sync skipped for %s: cache read failed: %s", dataset_id, e)
        return

    # Auto-detect observatory_stem if not provided
    if observatory_stem is None:
        from spedas_mcp.backends.cdaweb.catalog import get_observatory_stem_from_dataset
        observatory_stem = get_observatory_stem_from_dataset(dataset_id)
        if observatory_stem is None:
            logger.debug("Metadata sync skipped for %s: unknown observatory", dataset_id)
            return

    # Check existing override for prior validations
    existing_override = load_override(dataset_id, mission_stem=observatory_stem)
    if existing_override:
        existing_validations = existing_override.get("_validations", [])
        if source_url and any(
            v.get("source_url") == source_url for v in existing_validations
        ):
            logger.debug("Metadata sync skipped for %s: source already validated", dataset_id)
            return
    else:
        existing_validations = []

    # Read actual data CDF variables
    try:
        data_var_names = {v["name"] for v in inspect_cdf_variables(cdf_path)}
    except Exception as e:
        logger.warning("Metadata sync failed for %s: %s", dataset_id, e)
        return

    # Also get ALL CDF vars (unfiltered) for phantom detection
    try:
        data_cdf = cdflib.CDF(str(cdf_path))
        data_info = data_cdf.cdf_info()
        all_cdf_vars = set(data_info.zVariables) | set(data_info.rVariables)
    except Exception as e:
        logger.warning("Metadata sync failed for %s: could not read CDF: %s", dataset_id, e)
        return

    # Cached parameter names (excluding Time)
    cached_names = {
        p.get("name") for p in cached_info.get("parameters", [])
        if p.get("name", "").lower() != "time"
    }

    # Compare: phantom = in metadata but not in any CDF var
    master_only = cached_names - all_cdf_vars
    # Compare: undocumented = in filtered data vars but not in metadata
    data_only = data_var_names - cached_names

    # Build discrepancies
    discrepancies: dict = {}

    for param in cached_info.get("parameters", []):
        name = param.get("name", "")
        if name.lower() == "time":
            continue
        if name in master_only:
            discrepancies[name] = {
                "_category": "phantom",
                "_note": "in master CDF but not found in data CDF",
            }

    for var_name in sorted(data_only):
        discrepancies[var_name] = {
            "_category": "undocumented",
            "_note": "found in data CDF but not in master CDF",
        }

    if not discrepancies:
        logger.info("Metadata sync for %s: perfect match (%d variables)",
                     dataset_id, len(cached_names))
    else:
        logger.info("Metadata sync for %s: %d phantom, %d undocumented",
                     dataset_id, len(master_only), len(data_only))

    # Build validation record
    validation_record = {
        "version": len(existing_validations) + 1,
        "source_file": cdf_path.name,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "discrepancies": discrepancies,
    }
    if source_url:
        validation_record["source_url"] = source_url

    # Build override patch
    override_patch: dict = {"_validated": True}
    if discrepancies:
        override_patch["parameters_annotations"] = discrepancies
    override_patch["_validations"] = existing_validations + [validation_record]

    save_override(dataset_id, override_patch, mission_stem=observatory_stem)


def get_quality_report(dataset_id: str, mission_stem: str) -> dict | None:
    """Summarize metadata discrepancies for a dataset.

    Groups annotations into:
    - metadata_only: parameters in metadata but absent from actual data
    - data_only: parameters in data but missing from metadata

    Args:
        dataset_id: CDAWeb dataset ID.
        mission_stem: Mission stem directory name.

    Returns:
        Dict with validated, metadata_only, data_only, validation_count, summary.
        None if no override exists or dataset has never been validated.
    """
    override = load_override(dataset_id, mission_stem=mission_stem)
    if override is None:
        return None

    validations = override.get("_validations", [])

    # Union discrepancies across all validations
    if validations:
        annotations: dict = {}
        for v in validations:
            for param, ann in v.get("discrepancies", {}).items():
                if param not in annotations and isinstance(ann, dict):
                    annotations[param] = ann
    else:
        annotations = override.get("parameters_annotations", {})

    if not annotations and not override.get("_validated"):
        return None

    metadata_only: list[str] = []
    data_only: list[str] = []

    for param, ann in annotations.items():
        if not isinstance(ann, dict):
            continue
        category = ann.get("_category", "")
        note = ann.get("_note", "")
        if category == "phantom" or (
            not category and "not found in data" in note
        ):
            metadata_only.append(param)
        elif category == "undocumented" or (
            not category and "found in data" in note
        ):
            data_only.append(param)

    parts: list[str] = []
    if metadata_only:
        parts.append(
            f"{len(metadata_only)} parameter(s) in metadata but absent from data: "
            f"{', '.join(sorted(metadata_only))}"
        )
    if data_only:
        parts.append(
            f"{len(data_only)} parameter(s) in data but missing from metadata: "
            f"{', '.join(sorted(data_only))}"
        )

    return {
        "validated": bool(override.get("_validated")),
        "validation_count": len(validations),
        "metadata_only": sorted(metadata_only),
        "data_only": sorted(data_only),
        "summary": "; ".join(parts) if parts else "No discrepancies detected.",
    }
