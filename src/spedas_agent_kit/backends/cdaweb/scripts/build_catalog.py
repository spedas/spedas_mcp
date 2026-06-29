"""Build the observatory catalog from CDAWeb REST API.

Queries CDAWeb's observatory groups and dataset catalog, groups datasets by
observatory group, categorizes by InstrumentType, and writes one JSON per group.

Usage:
    python -m spedas_agent_kit.backends.cdaweb.scripts.build_catalog                    # Build all
    python -m spedas_agent_kit.backends.cdaweb.scripts.build_catalog --observatory ace   # Build one
    python -m spedas_agent_kit.backends.cdaweb.scripts.build_catalog --list              # List groups
"""

import argparse
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spedas_agent_kit.backends.cdaweb.http import request_with_retry

logger = logging.getLogger(__name__)

# Output directory for observatory JSONs
OBSERVATORIES_DIR = Path(__file__).parent.parent / "data" / "observatories"

# CDAWeb REST API endpoints
CDAWEB_BASE = "https://cdaweb.gsfc.nasa.gov/WS/cdasr/1/dataviews/sp_phys"
CDAWEB_DATASETS_URL = f"{CDAWEB_BASE}/datasets"
CDAWEB_OBS_GROUPS_URL = f"{CDAWEB_BASE}/observatoryGroups"
_NS = {"cda": "http://cdaweb.gsfc.nasa.gov/schema"}


# ===================================================================
# Instrument type mapping (from CDAWeb InstrumentType taxonomy)
# ===================================================================

INSTRUMENT_TYPE_INFO = {
    "Magnetic Fields (space)": {
        "id": "mag", "name": "Magnetic Fields",
        "keywords": ["magnetic", "field", "mag", "b-field", "imf", "magnetometer"],
    },
    "Plasma and Solar Wind": {
        "id": "plasma", "name": "Plasma and Solar Wind",
        "keywords": ["plasma", "solar wind", "proton", "density", "velocity",
                      "temperature", "ion", "electron"],
    },
    "Particles (space)": {
        "id": "particles", "name": "Energetic Particles",
        "keywords": ["particle", "energetic", "cosmic ray"],
    },
    "Electric Fields (space)": {
        "id": "efield", "name": "Electric Fields",
        "keywords": ["electric", "e-field"],
    },
    "Radio and Plasma Waves (space)": {
        "id": "waves", "name": "Radio and Plasma Waves",
        "keywords": ["radio", "wave", "plasma wave"],
    },
    "Activity Indices": {
        "id": "indices", "name": "Activity Indices",
        "keywords": ["index", "indices", "geomagnetic", "sym-h", "dst", "kp", "ae"],
    },
    "Ephemeris/Attitude/Ancillary": {
        "id": "ephemeris", "name": "Ephemeris and Attitude",
        "keywords": ["ephemeris", "orbit", "attitude", "position"],
    },
    "Ground-Based Magnetometers, Riometers, Sounders": {
        "id": "ground_mag", "name": "Ground-Based Magnetometers",
        "keywords": ["ground", "magnetometer", "riometer"],
    },
    "Imaging and Remote Sensing (Magnetosphere/Earth)": {
        "id": "imaging_mag", "name": "Magnetospheric Imaging",
        "keywords": ["imaging", "remote sensing", "magnetosphere"],
    },
    "Imaging and Remote Sensing (ITM/Earth)": {
        "id": "imaging_itm", "name": "ITM Imaging",
        "keywords": ["imaging", "ionosphere", "thermosphere", "mesosphere"],
    },
    "Imaging and Remote Sensing (Sun)": {
        "id": "imaging_sun", "name": "Solar Imaging",
        "keywords": ["solar", "coronagraph", "euv", "uv", "x-ray"],
    },
    "Engineering": {
        "id": "engineering", "name": "Engineering",
        "keywords": ["engineering", "housekeeping"],
    },
    "Housekeeping": {
        "id": "engineering", "name": "Engineering",
        "keywords": ["engineering", "housekeeping"],
    },
    "Plasma Composition/Charge State Analyzers": {
        "id": "composition", "name": "Plasma Composition",
        "keywords": ["composition", "charge state", "ion"],
    },
    "Coronagraph/Heliograph": {
        "id": "coronagraph", "name": "Coronagraph",
        "keywords": ["coronagraph", "heliograph", "solar"],
    },
}

INSTRUMENT_TYPE_PRIORITY = [
    "Magnetic Fields (space)",
    "Plasma and Solar Wind",
    "Particles (space)",
    "Electric Fields (space)",
    "Radio and Plasma Waves (space)",
    "Activity Indices",
    "Plasma Composition/Charge State Analyzers",
    "Coronagraph/Heliograph",
    "Imaging and Remote Sensing (Sun)",
    "Imaging and Remote Sensing (Magnetosphere/Earth)",
    "Imaging and Remote Sensing (ITM/Earth)",
    "Ground-Based Magnetometers, Riometers, Sounders",
    "Engineering",
    "Housekeeping",
    "Ephemeris/Attitude/Ancillary",
]


# ===================================================================
# Helper functions
# ===================================================================


def slugify(name: str) -> str:
    """Convert an observatory group name to a filesystem-safe slug.

    Examples:
        'Parker Solar Probe (PSP)' -> 'parker_solar_probe_psp'
        'OMNI (Combined 1AU IP Data; Magnetic and Solar Indices)' -> 'omni'
        'Van Allen Probes (RBSP)' -> 'van_allen_probes_rbsp'
        'IMP (All)' -> 'imp'
    """
    s = name.lower()
    s = re.sub(r"\s*\(all\)", "", s)  # remove "(All)"
    # For OMNI, strip the long parenthetical
    s = re.sub(r"\s*\(combined[^)]*\)", "", s)
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


def pick_primary_type(instrument_types: list[str]) -> str | None:
    """Pick the highest-priority InstrumentType from a list."""
    if not instrument_types:
        return None
    for priority_type in INSTRUMENT_TYPE_PRIORITY:
        if priority_type in instrument_types:
            return priority_type
    return instrument_types[0] if instrument_types else None


def get_type_info(instrument_type: str) -> dict:
    """Return {id, name, keywords} for an InstrumentType string."""
    info = INSTRUMENT_TYPE_INFO.get(instrument_type)
    if info:
        return dict(info)
    clean_id = instrument_type.lower().replace(" ", "_").replace("/", "_")
    clean_id = clean_id.replace("(", "").replace(")", "")
    return {"id": clean_id, "name": instrument_type, "keywords": []}


# ===================================================================
# CDAWeb REST API
# ===================================================================


def _text(elem, tag: str) -> str:
    """Extract text from a child element, or empty string."""
    child = elem.find(tag, _NS)
    if child is not None and child.text:
        return child.text.strip()
    return ""


def fetch_observatory_groups() -> dict[str, dict]:
    """Fetch observatory groups from CDAWeb REST API.

    Returns dict mapping group slug to:
        {"name": "Group Name", "observatory_ids": ["OBS1", "OBS2", ...]}
    """
    logger.info("Fetching observatory groups from CDAWeb REST API...")
    resp = request_with_retry(CDAWEB_OBS_GROUPS_URL)

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.error("Error parsing observatory groups XML: %s", e)
        return {}

    groups = {}
    for og in root.findall("cda:ObservatoryGroupDescription", _NS):
        name_elem = og.find("cda:Name", _NS)
        if name_elem is None or not name_elem.text:
            continue
        name = name_elem.text.strip()
        obs_ids = [
            el.text.strip()
            for el in og.findall("cda:ObservatoryId", _NS)
            if el.text and el.text.strip()
        ]
        slug = slugify(name)
        if slug in groups:
            # Merge observatory IDs if slug collision
            groups[slug]["observatory_ids"].extend(obs_ids)
        else:
            groups[slug] = {"name": name, "observatory_ids": obs_ids}

    logger.info("Found %d observatory groups", len(groups))
    return groups


def fetch_cdaweb_catalog() -> dict[str, dict]:
    """Fetch all dataset metadata from CDAWeb REST API.

    Returns dict mapping dataset_id to metadata.
    """
    logger.info("Fetching dataset catalog from CDAWeb REST API...")
    resp = request_with_retry(CDAWEB_DATASETS_URL)

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.error("Error parsing CDAWeb XML: %s", e)
        return {}

    result = {}
    for ds in root.findall("cda:DatasetDescription", _NS):
        ds_id = _text(ds, "cda:Id")
        if not ds_id:
            continue

        instrument_types = [
            el.text.strip()
            for el in ds.findall("cda:InstrumentType", _NS)
            if el.text and el.text.strip()
        ]

        ti = ds.find("cda:TimeInterval", _NS)
        start_date = ""
        stop_date = ""
        if ti is not None:
            start_date = _text(ti, "cda:Start")
            stop_date = _text(ti, "cda:End")

        result[ds_id] = {
            "instrument": _text(ds, "cda:Instrument") or "",
            "instrument_types": instrument_types,
            "label": _text(ds, "cda:Label") or "",
            "observatory": _text(ds, "cda:Observatory") or "",
            "observatory_group": _text(ds, "cda:ObservatoryGroup") or "",
            "pi_name": _text(ds, "cda:PiName") or "",
            "doi": _text(ds, "cda:Doi") or "",
            "start_date": start_date,
            "stop_date": stop_date,
        }

    logger.info("Found %d datasets", len(result))
    return result


# ===================================================================
# Observatory JSON building
# ===================================================================


def build_obs_id_to_group(groups: dict[str, dict]) -> dict[str, str]:
    """Build reverse map: observatory_id (case-insensitive) -> group slug."""
    reverse = {}
    for slug, info in groups.items():
        for obs_id in info["observatory_ids"]:
            reverse[obs_id.lower()] = slug
    return reverse


def build_observatory_json(
    slug: str,
    group_name: str,
    datasets: list[tuple[str, dict]],
) -> dict:
    """Build a complete observatory JSON from matched datasets.

    Args:
        slug: Filesystem slug (e.g., 'ace', 'parker_solar_probe_psp').
        group_name: CDAWeb observatory group name.
        datasets: List of (dataset_id, dataset_metadata) tuples.

    Returns:
        Observatory dict ready to write as JSON.
    """
    obs = {
        "id": slug,
        "name": group_name,
        "profile": {
            "description": f"{group_name} data from CDAWeb.",
            "coordinate_systems": [],
            "typical_cadence": "",
            "data_caveats": [],
        },
        "instruments": {},
    }

    for ds_id, ds_meta in datasets:
        # Determine instrument category from InstrumentType
        primary_type = pick_primary_type(ds_meta.get("instrument_types", []))
        if primary_type:
            type_info = get_type_info(primary_type)
            inst_id = type_info["id"]
            inst_name = type_info["name"]
            inst_keywords = type_info["keywords"]
        else:
            inst_id = "General"
            inst_name = "General"
            inst_keywords = []

        # Ensure instrument exists
        if inst_id not in obs["instruments"]:
            obs["instruments"][inst_id] = {
                "name": inst_name,
                "keywords": inst_keywords,
                "datasets": {},
            }

        # Add dataset
        ds_entry = {
            "description": ds_meta.get("label", ""),
            "start_date": ds_meta.get("start_date", ""),
            "stop_date": ds_meta.get("stop_date", ""),
        }
        if ds_meta.get("pi_name"):
            ds_entry["pi_name"] = ds_meta["pi_name"]
        if ds_meta.get("doi"):
            ds_entry["doi"] = ds_meta["doi"]

        obs["instruments"][inst_id]["datasets"][ds_id] = ds_entry

    # Add generation metadata
    obs["_meta"] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "CDAWeb REST API",
    }

    return obs


def save_observatory_json(slug: str, data: dict, output_dir: Path | None = None):
    """Save an observatory JSON file."""
    out = output_dir or OBSERVATORIES_DIR
    out.mkdir(parents=True, exist_ok=True)
    filepath = out / f"{slug}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=False, ensure_ascii=False)
        f.write("\n")
    logger.debug("Saved %s", filepath.name)


def _build_group_name_to_slug(groups: dict[str, dict]) -> dict[str, str]:
    """Build reverse map: group display name (case-insensitive) -> slug."""
    result = {}
    for slug, info in groups.items():
        result[info["name"].lower()] = slug
    return result


def _resolve_short_name(slug: str, datasets: list[tuple[str, dict]]) -> str:
    """Derive the CDAWeb top-level data folder name for an observatory group.

    Queries the CDAWeb orig_data endpoint for a sample dataset to extract the
    canonical folder name from the data file URL path (e.g. sp_phys/data/ace/...).
    Falls back to the slugified group name if no files are available.
    """
    from spedas_agent_kit.backends.cdaweb.fetch import CDAWEB_REST_BASE, _iso_to_cdaweb_time

    for ds_id, ds_meta in datasets[:5]:  # try up to 5 datasets
        start = ds_meta.get("start_date", "")[:10]
        if not start:
            continue
        try:
            dt = datetime.strptime(start, "%Y-%m-%d")
            s = _iso_to_cdaweb_time((dt + timedelta(days=1)).strftime("%Y-%m-%d"))
            e = _iso_to_cdaweb_time((dt + timedelta(days=8)).strftime("%Y-%m-%d"))
            url = f"{CDAWEB_REST_BASE}/datasets/{ds_id}/orig_data/{s},{e}"
            resp = request_with_retry(url, headers={"Accept": "application/json"}, timeout=15)
            data = resp.json()
            file_descs = (data.get("FileDescription")
                          or data.get("FileDescriptionList", {}).get("FileDescription")
                          or [])
            if file_descs:
                file_url = file_descs[0].get("Name", "")
                marker = "sp_phys/data/"
                idx = file_url.find(marker)
                if idx >= 0:
                    folder = file_url[idx + len(marker):].split("/")[0]
                    if folder:
                        return folder
        except Exception:
            continue
    return slug  # fallback


def build_all(
    groups: dict[str, dict],
    catalog: dict[str, dict],
    filter_slug: str | None = None,
    output_dir: Path | None = None,
) -> list[str]:
    """Build observatory JSONs for all groups (or one if filtered).

    Args:
        groups: Observatory groups from fetch_observatory_groups().
        catalog: Dataset catalog from fetch_cdaweb_catalog().
        filter_slug: Only build this observatory slug.
        output_dir: Directory to write JSONs. Defaults to bundled data dir.

    Returns list of built slugs.
    """
    obs_id_to_group = build_obs_id_to_group(groups)
    group_name_to_slug = _build_group_name_to_slug(groups)

    # Build a sorted list of observatory IDs for prefix fallback (longest first)
    all_obs_ids = sorted(obs_id_to_group.keys(), key=len, reverse=True)

    # Group datasets by observatory group slug
    grouped: dict[str, list[tuple[str, dict]]] = {}
    unmatched = []
    for ds_id, ds_meta in catalog.items():
        obs = ds_meta.get("observatory", "")
        slug = obs_id_to_group.get(obs.lower()) if obs else None

        # Fallback 1: match dataset ID against observatory IDs as prefixes
        if slug is None:
            ds_lower = ds_id.lower()
            for obs_key in all_obs_ids:
                if ds_lower.startswith(obs_key):
                    slug = obs_id_to_group[obs_key]
                    break

        # Fallback 2: use the dataset's ObservatoryGroup field directly
        if slug is None:
            obs_group = ds_meta.get("observatory_group", "")
            if obs_group:
                slug = group_name_to_slug.get(obs_group.lower())

        if slug is None:
            unmatched.append((ds_id, obs))
            continue
        if filter_slug and slug != filter_slug:
            continue
        grouped.setdefault(slug, []).append((ds_id, ds_meta))

    if unmatched and not filter_slug:
        logger.info("%d datasets with unrecognized observatory IDs", len(unmatched))
        obs_counts: dict[str, int] = {}
        for _, obs in unmatched:
            obs_counts[obs] = obs_counts.get(obs, 0) + 1
        for obs, count in sorted(obs_counts.items(), key=lambda x: -x[1])[:10]:
            logger.debug("  Unmatched observatory '%s': %d datasets", obs, count)

    # Resolve short names (CDAWeb data folder names) for each group
    logger.info("Resolving CDAWeb short names for %d groups...", len(grouped))
    short_names: dict[str, str] = {}
    for slug in sorted(grouped):
        short_name = _resolve_short_name(slug, grouped[slug])
        short_names[slug] = short_name
        if short_name != slug:
            logger.info("  %s → short_name: %s", slug, short_name)

    # Detect short_name collisions (e.g. PSP and Parker Solar Probe both → psp)
    # Merge groups that resolve to the same short_name
    merged: dict[str, list[tuple[str, dict]]] = {}
    merged_names: dict[str, str] = {}
    for slug in sorted(grouped):
        sn = short_names[slug]
        if sn in merged:
            merged[sn].extend(grouped[slug])
            logger.info("  Merging %s into %s (same short_name: %s)",
                        slug, merged_names[sn], sn)
        else:
            merged[sn] = list(grouped[slug])
            merged_names[sn] = groups[slug]["name"]

    # Remove stale observatory files not in the new build.
    # Only clean up when doing a full (unfiltered) rebuild — a filtered rebuild
    # intentionally builds a subset and must not delete the rest.
    out = output_dir or OBSERVATORIES_DIR
    if out.exists() and not filter_slug:
        new_slugs = set(merged.keys())
        for old_file in out.glob("*.json"):
            if old_file.stem not in new_slugs:
                logger.info("  Removing stale: %s", old_file.name)
                old_file.unlink()

    built = []
    for short_name in sorted(merged):
        group_name = merged_names[short_name]
        datasets = merged[short_name]
        obs_data = build_observatory_json(short_name, group_name, datasets)
        obs_data["short_name"] = short_name
        save_observatory_json(short_name, obs_data, output_dir=output_dir)
        logger.debug("%s: %d datasets", group_name, len(datasets))
        built.append(short_name)

    return built


def main():
    parser = argparse.ArgumentParser(
        description="Build observatory catalog from CDAWeb REST API"
    )
    parser.add_argument(
        "--observatory", type=str,
        help="Build only this observatory (slug, e.g., ace, psp). Case-insensitive.",
    )
    parser.add_argument(
        "--list", action="store_true",
        help="List all observatory groups and their slugs.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    # Fetch observatory groups
    groups = fetch_observatory_groups()
    if not groups:
        print("Error: Could not fetch observatory groups.")
        sys.exit(1)

    if args.list:
        print(f"\n{len(groups)} observatory groups:\n")
        for slug in sorted(groups):
            info = groups[slug]
            n_obs = len(info["observatory_ids"])
            print(f"  {slug:40s} {info['name']} ({n_obs} observatory IDs)")
        return

    # Fetch dataset catalog
    catalog = fetch_cdaweb_catalog()
    if not catalog:
        print("Error: Could not fetch CDAWeb catalog.")
        sys.exit(1)

    filter_slug = args.observatory.lower() if args.observatory else None
    built = build_all(groups, catalog, filter_slug=filter_slug)

    print(f"\nDone! Built {len(built)} observatory catalogs.")


if __name__ == "__main__":
    main()
