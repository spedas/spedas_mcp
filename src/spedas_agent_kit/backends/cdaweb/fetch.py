"""CDF data fetching — download from CDAWeb and return DataFrames.

Library API: fetch_data() returns DataFrames + stats directly.
MCP server wrapper (server.py) handles file-writing and metadata-only responses.
"""

import json
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Type alias for optional log callback: (level, message) -> None
LogFn = Callable[[str, str], None] | None


def _sync_after_download(dataset_id: str, cdf_path: Path, source_url: str) -> None:
    """Run metadata sync on the first CDF file. Non-blocking — errors are logged, not raised."""
    try:
        from spedas_agent_kit.backends.cdaweb.validation import sync_metadata
        sync_metadata(
            dataset_id=dataset_id,
            cdf_path=cdf_path,
            source_url=source_url,
        )
    except Exception as e:
        logger.debug("Metadata sync error for %s: %s", dataset_id, e)


CDAWEB_REST_BASE = "https://cdaweb.gsfc.nasa.gov/WS/cdasr/1/dataviews/sp_phys"

_WARN_THRESHOLD_BYTES = 500 * 1024 * 1024   # 500 MB
_BLOCK_THRESHOLD_BYTES = 1024 * 1024 * 1024  # 1 GB

_EPOCH_TYPES = {"CDF_EPOCH", "CDF_EPOCH16", "CDF_TIME_TT2000"}
_SKIP_TYPES = _EPOCH_TYPES | {"CDF_CHAR", "CDF_UCHAR"}


def get_cache_dir() -> Path:
    """Return the CDF file cache directory."""
    from spedas_agent_kit.backends.cdaweb.config import get_cache_root
    return get_cache_root() / "cdf_cache"


def _log(log_fn: LogFn, level: str, message: str) -> None:
    """Send a log message via callback or fall back to Python logging."""
    if log_fn is not None:
        log_fn(level, message)
    else:
        getattr(logger, level, logger.info)(message)


def fetch_data(
    dataset_id: str,
    parameters: list[str],
    start: str,
    stop: str,
    force: bool = False,
    log_fn: LogFn = None,
) -> dict:
    """Fetch CDAWeb timeseries data and return DataFrames with stats.

    This is the library API — returns DataFrames directly. The MCP server
    wrapper in server.py handles file-writing and metadata-only responses.

    Args:
        dataset_id: CDAWeb dataset ID (e.g., 'AC_H2_MFI').
        parameters: List of parameter names to fetch.
        start: Start time in ISO 8601 format.
        stop: End time in ISO 8601 format.
        force: Override the 1 GB download safety limit.
        log_fn: Optional callback (level, message) for structured logging.
                When called from MCP server, this routes to ctx.log().

    Returns:
        Dict keyed by parameter_id. Each value has:
        - data: pandas DataFrame with DatetimeIndex
        - units: str
        - description: str
        - stats: dict of per-column {min, max, mean, std, nan_ratio}
        On error, the value has just {"error": str}.
    """
    from spedas_agent_kit.backends.cdaweb.metadata import _resolve_metadata

    cache_dir = get_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Resolve metadata for units/descriptions
    try:
        info = _resolve_metadata(dataset_id)
    except Exception:
        info = {"parameters": []}

    # Fetch file list once for the whole dataset (all parameters share the same CDF files)
    _log(log_fn, "info", f"Fetching {dataset_id}: {len(parameters)} parameter(s), {start} to {stop}")
    try:
        file_list = _get_cdf_file_list(dataset_id, start, stop)
    except ValueError as e:
        _log(log_fn, "warning", f"No CDF files for {dataset_id}: {e}")
        return {param_id: {"error": str(e)} for param_id in parameters}

    total_size = sum(f.get("size", 0) for f in file_list)
    _log(log_fn, "info",
         f"Found {len(file_list)} CDF file(s) for {dataset_id} "
         f"({total_size / 1024:.0f} KB total)")

    results = {}
    for param_id in parameters:
        try:
            result = _fetch_single_parameter(
                dataset_id, param_id, start, stop, info, cache_dir, force,
                file_list=file_list, log_fn=log_fn,
            )
            df = result["data"]
            stats = compute_stats(df)

            results[param_id] = {
                "data": df,
                "units": result["units"],
                "description": result["description"],
                "stats": stats,
            }
        except Exception as e:
            results[param_id] = {"error": str(e)}

    return results


def compute_stats(df: pd.DataFrame) -> dict:
    """Compute per-column summary statistics for a DataFrame.

    Used by both the library API (fetch_data) and the MCP server wrapper.

    Returns:
        Dict keyed by column name with {min, max, mean, std, nan_ratio}.
    """
    stats = {}
    for col in df.columns:
        series = df[col]
        nan_count = int(series.isna().sum())
        total = len(series)
        all_nan = series.isna().all()
        stats[str(col)] = {
            "min": round(float(series.min()), 4) if not all_nan else None,
            "max": round(float(series.max()), 4) if not all_nan else None,
            "mean": round(float(series.mean()), 4) if not all_nan else None,
            "std": round(float(series.std()), 4) if not all_nan else None,
            "nan_ratio": round(nan_count / total, 4) if total > 0 else 0.0,
        }
    return stats


def write_dataframe_csv(df: pd.DataFrame, output_dir: Path, name: str) -> Path:
    """Write a DataFrame to a CSV file.

    Args:
        df: DataFrame with DatetimeIndex.
        output_dir: Directory to write the file.
        name: Base name for the output file.

    Returns:
        Path to the written CSV file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.csv"
    df.to_csv(path)
    return path


def write_dataframe_json(df: pd.DataFrame, output_dir: Path, name: str) -> Path:
    """Write a DataFrame to a JSON file.

    Args:
        df: DataFrame with DatetimeIndex.
        output_dir: Directory to write the file.
        name: Base name for the output file.

    Returns:
        Path to the written JSON file.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{name}.json"
    data = {"time": df.index.strftime("%Y-%m-%dT%H:%M:%S.%f").tolist()}
    for col in df.columns:
        data[str(col)] = [None if pd.isna(v) else v for v in df[col].tolist()]
    with open(path, "w") as f:
        json.dump(data, f)
    return path


# --- Internal helpers (extracted from xhelio's fetch_cdf.py) ---


def _fetch_single_parameter(
    dataset_id: str,
    parameter_id: str,
    time_min: str,
    time_max: str,
    info: dict,
    cache_dir: Path,
    force: bool,
    file_list: list[dict] | None = None,
    log_fn: LogFn = None,
) -> dict:
    """Fetch a single parameter from CDAWeb CDF files.

    Returns dict with keys: data (DataFrame), units, description, fill_value.
    """
    import cdflib

    # Look up parameter metadata
    units = ""
    description = ""
    fill_value = None
    cdf_native = False
    try:
        param_meta = _find_parameter_meta(info, parameter_id)
        units = param_meta.get("units", "")
        description = param_meta.get("description", "")
        fill_value = param_meta.get("fill", None)
    except ValueError:
        cdf_native = True

    # Get CDF file list (prefer pre-fetched list from fetch_data)
    if file_list is None:
        file_list = _get_cdf_file_list(dataset_id, time_min, time_max)

    # Download and read each file
    frames = []
    validmin = None
    validmax = None

    max_workers = min(len(file_list), 6)
    if len(file_list) > 1:
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {
                pool.submit(
                    _download_and_read, fi["url"], parameter_id, cache_dir,
                    log_fn, fi.get("size", 0), fi.get("last_modified", ""),
                ): idx
                for idx, fi in enumerate(file_list)
            }
            results_by_idx = {}
            for future in as_completed(futures):
                idx = futures[future]
                results_by_idx[idx] = future.result()
    else:
        results_by_idx = {}
        for idx, fi in enumerate(file_list):
            results_by_idx[idx] = _download_and_read(
                fi["url"], parameter_id, cache_dir, log_fn,
                fi.get("size", 0), fi.get("last_modified", ""),
            )

    for idx in range(len(file_list)):
        local_path, data, attrs = results_by_idx[idx]
        if not frames:
            # Use attrs returned from _read_cdf_parameter (no need to re-open the CDF)
            try:
                if cdf_native:
                    units = attrs.get("UNITS", "") or ""
                    if isinstance(units, np.ndarray):
                        units = str(units)
                    description = (attrs.get("CATDESC", "")
                                   or attrs.get("FIELDNAM", "") or "")
                    if isinstance(description, np.ndarray):
                        description = str(description)
                fv = attrs.get("FILLVAL", None)
                if fv is not None:
                    try:
                        fill_value = float(fv)
                    except (ValueError, TypeError):
                        pass
                vmin = attrs.get("VALIDMIN", None)
                vmax = attrs.get("VALIDMAX", None)
                if vmin is not None:
                    try:
                        validmin = float(vmin)
                    except (ValueError, TypeError):
                        pass
                if vmax is not None:
                    try:
                        validmax = float(vmax)
                    except (ValueError, TypeError):
                        pass
            except Exception:
                pass
            # Sync metadata against actual data CDF (first file only)
            _sync_after_download(dataset_id, local_path, file_list[idx].get("url", ""))
        frames.append(data)

    if not frames:
        raise ValueError(f"No data for {dataset_id}/{parameter_id} in {time_min} to {time_max}")

    # Concatenate and clean
    df = pd.concat(frames)
    df.sort_index(inplace=True)
    df = df[~df.index.duplicated(keep="first")]

    t_start = _strip_utc_suffix(time_min)
    t_stop = _strip_utc_suffix(time_max)
    df = df.loc[t_start:t_stop]

    if len(df) == 0:
        raise ValueError(f"No data rows in range {time_min} to {time_max}")

    for col in df.columns:
        df[col] = pd.to_numeric(df[col], errors="coerce").astype(np.float64)

    if fill_value is not None:
        try:
            fill_f = float(fill_value)
            for col in df.columns:
                mask = np.isclose(df[col].values, fill_f, rtol=1e-6, equal_nan=False)
                df.loc[mask, col] = np.nan
        except (ValueError, TypeError):
            pass

    if validmin is not None or validmax is not None:
        for col in df.columns:
            if validmin is not None:
                df.loc[df[col] < validmin, col] = np.nan
            if validmax is not None:
                df.loc[df[col] > validmax, col] = np.nan

    return {"data": df, "units": units, "description": description, "fill_value": fill_value}


def _find_parameter_meta(info: dict, parameter_id: str) -> dict:
    """Find metadata for a specific parameter in the resolved metadata."""
    for param in info.get("parameters", []):
        if param.get("name") == parameter_id:
            return param
    raise ValueError(f"Parameter '{parameter_id}' not found in metadata")


def _get_cdf_file_list(dataset_id: str, time_min: str, time_max: str) -> list[dict]:
    """Query CDAWeb REST API for CDF file URLs covering a time range."""
    from spedas_agent_kit.backends.cdaweb.http import request_with_retry

    start_str = _iso_to_cdaweb_time(time_min)
    stop_str = _iso_to_cdaweb_time(time_max)

    url = f"{CDAWEB_REST_BASE}/datasets/{dataset_id}/orig_data/{start_str},{stop_str}"
    resp = request_with_retry(url, headers={"Accept": "application/json"})
    data = resp.json()

    file_descs = (data.get("FileDescription")
                  or data.get("FileDescriptionList", {}).get("FileDescription")
                  or [])

    if not file_descs:
        raise ValueError(f"No CDF files found for {dataset_id} in {time_min} to {time_max}")

    return [
        {"url": fd.get("Name", ""), "start_time": fd.get("StartTime", ""),
         "end_time": fd.get("EndTime", ""), "size": fd.get("Length", 0),
         "last_modified": fd.get("LastModified", "")}
        for fd in file_descs if fd.get("Name")
    ]


def _download_and_read(
    url: str, parameter_id: str, cache_dir: Path,
    log_fn: LogFn = None, remote_size: int = 0, remote_modified: str = "",
):
    """Download a CDF file and read one parameter. Thread-safe.

    Returns (local_path, DataFrame, var_attrs).
    """
    local_path = _download_cdf_file(url, cache_dir, log_fn,
                                    remote_size=remote_size,
                                    remote_modified=remote_modified)
    data, attrs = _read_cdf_parameter(local_path, parameter_id)
    return local_path, data, attrs


def _download_cdf_file(
    url: str, cache_base: Path, log_fn: LogFn = None,
    remote_size: int = 0, remote_modified: str = "",
) -> Path:
    """Download a CDF file, using local cache if available.

    Cache validation: if the cached file exists but its size differs from
    the remote size reported by CDAWeb's file list API, re-download it
    (the file was likely reprocessed). When remote_size is 0 (unknown),
    any non-empty cached file is accepted.
    """
    from spedas_agent_kit.backends.cdaweb.http import request_with_retry

    parsed = urlparse(url)
    path = parsed.path
    marker = "sp_phys/data/"
    idx = path.find(marker)
    if idx >= 0:
        rel_path = path[idx + len(marker):]
    else:
        rel_path = Path(parsed.path).name

    local_path = cache_base / rel_path
    filename = Path(parsed.path).name

    # Check cache — validate size against remote if available
    if local_path.exists():
        local_size = local_path.stat().st_size
        if local_size > 0:
            if remote_size > 0 and local_size != remote_size:
                _log(log_fn, "info",
                     f"Cache stale (size {local_size} != remote {remote_size}), "
                     f"re-downloading: {filename}")
            else:
                _log(log_fn, "debug", f"Cache hit: {filename} ({local_size / 1024:.0f} KB)")
                return local_path

    size_str = f" ({remote_size / 1024:.0f} KB)" if remote_size > 0 else ""
    _log(log_fn, "info", f"Downloading: {filename}{size_str}")
    local_path.parent.mkdir(parents=True, exist_ok=True)

    from spedas_agent_kit.backends.cdaweb.http import DOWNLOAD_TIMEOUT
    resp = request_with_retry(url, timeout=DOWNLOAD_TIMEOUT, stream=True)

    # Reject HTML error pages (CDAWeb sometimes returns HTML on errors)
    content_type = resp.headers.get("Content-Type", "")
    if "html" in content_type.lower():
        resp.close()
        raise ValueError(
            f"CDAWeb returned HTML instead of CDF for {filename} "
            f"(Content-Type: {content_type})"
        )

    # Stream to disk to avoid loading entire file into memory
    import os
    tmp_path = local_path.with_suffix(".tmp")
    written = 0
    try:
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=65536):
                written += len(chunk)
                if written > _BLOCK_THRESHOLD_BYTES:
                    raise ValueError(
                        f"CDF file exceeds {_BLOCK_THRESHOLD_BYTES // (1024*1024)} MB "
                        f"limit: {filename}"
                    )
                f.write(chunk)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise
    finally:
        resp.close()

    if written > _WARN_THRESHOLD_BYTES:
        _log(log_fn, "warning",
             f"Large CDF file: {filename} ({written / (1024*1024):.0f} MB)")

    os.replace(tmp_path, local_path)

    _log(log_fn, "info", f"Downloaded: {filename} ({written / 1024:.0f} KB)")
    return local_path


def _read_cdf_parameter(cdf_path: Path, parameter_id: str) -> tuple[pd.DataFrame, dict]:
    """Extract one parameter from a CDF file. Returns (DataFrame, var_attrs)."""
    import cdflib

    cdf = cdflib.CDF(str(cdf_path))
    info = cdf.cdf_info()

    try:
        param_data = cdf.varget(parameter_id)
    except Exception as e:
        all_vars = info.zVariables + info.rVariables
        raise ValueError(
            f"Variable '{parameter_id}' not found in {cdf_path.name}. Available: {all_vars}"
        ) from e

    # Read variable attributes once (reused by caller to avoid re-opening the CDF)
    try:
        attrs = cdf.varattsget(parameter_id)
    except Exception:
        attrs = {}

    # Find epoch variable — prefer DEPEND_0 attribute, fall back to generic search
    epoch_var = _find_epoch_for_parameter(cdf, info, parameter_id)
    times = _read_epoch(cdf, info, epoch_var)

    if param_data.ndim == 1:
        df = pd.DataFrame({1: param_data}, index=times)
    elif param_data.ndim == 2:
        ncols = param_data.shape[1]
        df = pd.DataFrame({i + 1: param_data[:, i] for i in range(ncols)}, index=times)
    else:
        # Flatten higher dimensions for MCP transport
        flat = param_data.reshape(param_data.shape[0], -1)
        ncols = flat.shape[1]
        df = pd.DataFrame({i + 1: flat[:, i] for i in range(ncols)}, index=times)

    df.index.name = "time"
    return df, attrs


def _read_epoch(cdf, info, epoch_var: str):
    """Read epoch data, handling THEMIS-style virtual epochs.

    THEMIS CDF files store time as virtual epoch variables: the CDF_EPOCH
    variable (e.g. tha_fgs_epoch) has 0 records, but a companion CDF_DOUBLE
    variable (e.g. tha_fgs_time) contains Unix timestamps. When the epoch
    variable is empty, we fall back to the companion *_time variable.
    """
    import cdflib

    try:
        epoch_data = cdf.varget(epoch_var)
        return cdflib.cdfepoch.to_datetime(epoch_data)
    except ValueError as e:
        if "No records found" not in str(e):
            raise

    # Fallback: look for a companion *_time variable with Unix timestamps.
    # THEMIS pattern: tha_fgs_epoch (empty) → tha_fgs_time (Unix seconds)
    all_vars = info.zVariables + info.rVariables
    time_var = None

    # Try replacing _epoch/_epoch16 suffix with _time
    for suffix in ("_epoch", "_epoch16"):
        if epoch_var.endswith(suffix):
            candidate = epoch_var[: -len(suffix)] + "_time"
            if candidate in all_vars:
                time_var = candidate
                break

    if time_var is None:
        raise ValueError(
            f"No records found for variable {epoch_var} and no companion "
            f"*_time variable found"
        )

    time_data = cdf.varget(time_var)

    # Convert Unix seconds to datetime
    from datetime import datetime, timezone

    return [datetime.fromtimestamp(t, tz=timezone.utc) for t in time_data]


def _find_epoch_for_parameter(cdf, info, parameter_id: str) -> str:
    """Find the epoch variable for a specific parameter.

    CDF files can have multiple epoch variables (e.g., Epoch and Epoch2) with
    different record counts. The DEPEND_0 attribute on each variable specifies
    which epoch it uses. We check that first, falling back to the generic search.
    """
    try:
        attrs = cdf.varattsget(parameter_id)
        depend_0 = attrs.get("DEPEND_0")
        if depend_0:
            all_vars = info.zVariables + info.rVariables
            if depend_0 in all_vars:
                return depend_0
    except Exception:
        pass
    return _find_epoch_variable(cdf, info)


def _find_epoch_variable(cdf, info) -> str:
    """Find the epoch/time variable in a CDF file (generic fallback)."""
    all_vars = info.zVariables + info.rVariables

    for name in ["Epoch", "EPOCH", "epoch", "Epoch1"]:
        if name in all_vars:
            return name

    for var_name in all_vars:
        try:
            var_info = cdf.varinq(var_name)
            if var_info.Data_Type_Description.split()[0] in _EPOCH_TYPES:
                return var_name
        except Exception:
            continue

    raise ValueError(f"No epoch variable found. Variables: {all_vars}")


def _strip_utc_suffix(iso_time: str) -> str:
    """Strip timezone suffix from ISO 8601 string."""
    for suffix in ("+00:00", "+0000", "Z"):
        if iso_time.endswith(suffix):
            return iso_time[:-len(suffix)]
    return iso_time


def _iso_to_cdaweb_time(iso_time: str) -> str:
    """Convert ISO 8601 to CDAWeb REST API format (YYYYMMDDTHHmmSSZ)."""
    t = iso_time
    for suffix in ("+00:00", "+0000"):
        if t.endswith(suffix):
            t = t[:-len(suffix)] + "Z"
            break
    t = t.replace("-", "").replace(":", "")
    if not t.endswith("Z"):
        t += "Z"
    if "T" in t:
        date_part, time_z = t.split("T", 1)
        time_part = time_z.rstrip("Z")
        if "." in time_part:
            time_part = time_part.split(".", 1)[0]
        time_part = time_part[:6].ljust(6, "0")
        t = f"{date_part}T{time_part}Z"
    else:
        # Date-only: add T000000Z
        t = t.rstrip("Z") + "T000000Z"
    return t
