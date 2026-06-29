"""Fetch parameter metadata for all bundled observatory datasets.

Downloads Master CDF skeletons from CDAWeb, extracts parameter metadata,
and saves JSON files to src/spedas_agent_kit/backends/cdaweb/data/metadata/ for bundling with the package.

When a Master CDF is unavailable, falls back to downloading one real data CDF
from the dataset and extracting metadata from it (same CDF attributes).

Usage:
    python -m spedas_agent_kit.backends.cdaweb.scripts.build_metadata                      # All observatories
    python -m spedas_agent_kit.backends.cdaweb.scripts.build_metadata --observatory timed  # One observatory
    python -m spedas_agent_kit.backends.cdaweb.scripts.build_metadata --workers 20         # Faster parallel
"""

import argparse
import json
import logging
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logger = logging.getLogger(__name__)

# Output directory — bundled with the package
METADATA_DIR = Path(__file__).parent.parent / "data" / "metadata"
OBSERVATORIES_DIR = Path(__file__).parent.parent / "data" / "observatories"


def collect_datasets(observatory_filter: str | None = None) -> list[dict]:
    """Collect all datasets from bundled observatory JSONs.

    Returns list of dicts with keys: dataset_id, start_date, stop_date.
    """
    datasets = []
    for filepath in sorted(OBSERVATORIES_DIR.glob("*.json")):
        if observatory_filter and filepath.stem != observatory_filter:
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                observatory = json.load(f)
            for inst in observatory.get("instruments", {}).values():
                for ds_id, ds in inst.get("datasets", {}).items():
                    datasets.append({
                        "dataset_id": ds_id,
                        "start_date": ds.get("start_date", ""),
                        "stop_date": ds.get("stop_date", ""),
                    })
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Skipping %s: %s", filepath.name, e)
    return datasets


def _fetch_from_data_cdf(dataset_id: str, start_date: str, stop_date: str) -> dict | None:
    """Fallback: download one real data CDF and extract metadata from it.

    Queries CDAWeb for the file list using a short time window near the
    start of the dataset, picks the smallest file, and extracts metadata.
    """
    from spedas_agent_kit.backends.cdaweb.metadata import _extract_metadata

    # Parse start_date to compute a short query window
    start_iso = start_date[:10] if start_date else ""
    if not start_iso:
        return None

    # Try a 7-day window near the start
    from datetime import datetime, timedelta
    try:
        dt = datetime.strptime(start_iso, "%Y-%m-%d")
    except ValueError:
        return None

    t_start = (dt + timedelta(days=1)).strftime("%Y-%m-%d")
    t_stop = (dt + timedelta(days=8)).strftime("%Y-%m-%d")

    try:
        from spedas_agent_kit.backends.cdaweb.fetch import _get_cdf_file_list
        file_list = _get_cdf_file_list(dataset_id, t_start, t_stop)
    except Exception:
        # Try near stop_date if start didn't work
        stop_iso = stop_date[:10] if stop_date else ""
        if not stop_iso:
            return None
        try:
            dt2 = datetime.strptime(stop_iso, "%Y-%m-%d")
            t_start2 = (dt2 - timedelta(days=7)).strftime("%Y-%m-%d")
            file_list = _get_cdf_file_list(dataset_id, t_start2, stop_iso)
        except Exception:
            return None

    if not file_list:
        return None

    # Pick the smallest file to minimize download
    file_list.sort(key=lambda f: f.get("size", 0))
    chosen = file_list[0]
    url = chosen["url"]

    logger.info("Downloading data CDF for %s: %s", dataset_id, url.split("/")[-1])

    from spedas_agent_kit.backends.cdaweb.http import request_with_retry, DOWNLOAD_TIMEOUT
    try:
        resp = request_with_retry(url, timeout=DOWNLOAD_TIMEOUT)
    except Exception as e:
        logger.warning("Data CDF download failed for %s: %s", dataset_id, e)
        return None

    with tempfile.NamedTemporaryFile(suffix=".cdf", delete=False) as tmp:
        tmp.write(resp.content)
        tmp_path = Path(tmp.name)

    try:
        return _extract_metadata(tmp_path)
    except Exception as e:
        logger.warning("Data CDF extraction failed for %s: %s", dataset_id, e)
        return None
    finally:
        tmp_path.unlink(missing_ok=True)


def fetch_one(entry: dict) -> tuple[str, bool, str]:
    """Fetch metadata for a single dataset. Returns (dataset_id, success, method)."""
    from spedas_agent_kit.backends.cdaweb.metadata import _fetch_from_master_cdf

    dataset_id = entry["dataset_id"]
    out_path = METADATA_DIR / f"{dataset_id}.json"
    if out_path.exists():
        return dataset_id, True, "cached"

    # Try Master CDF first
    try:
        info = _fetch_from_master_cdf(dataset_id)
    except Exception:
        info = None

    method = "master_cdf"

    # Fallback: real data CDF
    if info is None:
        info = _fetch_from_data_cdf(
            dataset_id, entry.get("start_date", ""), entry.get("stop_date", ""),
        )
        method = "data_cdf"

    if info is None:
        return dataset_id, False, "failed"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(info, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return dataset_id, True, method


def main():
    parser = argparse.ArgumentParser(
        description="Fetch parameter metadata for bundled datasets"
    )
    parser.add_argument(
        "--observatory", type=str,
        help="Fetch only datasets for this observatory (e.g., timed, ace).",
    )
    # Keep --mission as alias for backwards compatibility
    parser.add_argument(
        "--mission", type=str,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--workers", type=int, default=10,
        help="Number of parallel download workers (default: 10).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-fetch even if JSON already exists.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    obs_filter = args.observatory or args.mission
    if obs_filter:
        obs_filter = obs_filter.lower()
    datasets = collect_datasets(obs_filter)

    if not datasets:
        print("No datasets found.")
        sys.exit(1)

    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    if args.force:
        to_fetch = datasets
    else:
        to_fetch = [
            d for d in datasets
            if not (METADATA_DIR / f"{d['dataset_id']}.json").exists()
        ]

    print(f"Found {len(datasets)} datasets, {len(to_fetch)} to fetch")

    if not to_fetch:
        print("All metadata already cached.")
        return

    success = 0
    failed = 0
    by_method = {"master_cdf": 0, "data_cdf": 0}
    workers = min(args.workers, len(to_fetch))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_one, entry): entry for entry in to_fetch}
        for future in as_completed(futures):
            ds_id, ok, method = future.result()
            if ok:
                success += 1
                by_method[method] = by_method.get(method, 0) + 1
            else:
                failed += 1
                print(f"  FAIL: {ds_id}")

            total_done = success + failed
            if total_done % 50 == 0:
                print(f"  Progress: {total_done}/{len(to_fetch)}")

    print(f"\nDone: {success} succeeded, {failed} failed out of {len(to_fetch)}")
    if by_method.get("master_cdf"):
        print(f"  Via Master CDF: {by_method['master_cdf']}")
    if by_method.get("data_cdf"):
        print(f"  Via data CDF fallback: {by_method['data_cdf']}")


if __name__ == "__main__":
    main()
