"""Unified SPEDAS-oriented MCP server.

This is intentionally a thin facade. It composes focused XHelio MCP/library
packages instead of duplicating their science logic:

- xhelio-cdaweb: observatory/dataset discovery, parameter metadata, CDAWeb fetch
- xhelio-spice: spacecraft/body ephemeris, distances, coordinate transforms
- xhelio-pds: PDS PPI mission/dataset discovery, parameter metadata, PDS fetch
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Literal

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover - exercised by entrypoint guard
    raise ImportError("Install MCP support with: pip install 'spedas-mcp[mcp]'") from exc

logger = logging.getLogger(__name__)


def _json(data: object) -> str:
    return json.dumps(data, indent=2, default=str)


def create_server() -> FastMCP:
    """Create and configure the unified SPEDAS MCP server."""
    mcp = FastMCP(
        "spedas-mcp",
        instructions=(
            "SPEDAS MCP facade for heliophysics workflows. Use CDAWeb tools to "
            "discover/fetch heliophysics timeseries data, PDS tools to inspect/fetch "
            "Planetary Plasma Interactions mission datasets, and SPICE tools to compute "
            "spacecraft/body ephemeris and coordinate transforms. Plan/discover before "
            "fetching; write bulk data to files; return compact metadata and paths."
        ),
    )

    @mcp.tool()
    def spedas_overview() -> str:
        """Describe available SPEDAS MCP capabilities and the recommended workflow."""
        return _json({
            "status": "success",
            "server": "spedas-mcp",
            "capability_groups": {
                "cdaweb": [
                    "browse_observatories",
                    "load_observatory",
                    "browse_parameters",
                    "fetch_data",
                ],
                "pds": [
                    "browse_pds_missions",
                    "load_pds_mission",
                    "browse_pds_parameters",
                    "fetch_pds_data",
                ],
                "spice": [
                    "get_ephemeris",
                    "compute_distance",
                    "transform_coordinates",
                    "list_spice_missions",
                    "list_coordinate_frames",
                ],
                "cache": ["manage_cdaweb_cache", "manage_pds_cache", "manage_spice_kernels"],
            },
            "workflow": [
                "Call browse_observatories, browse_pds_missions, or list_spice_missions first.",
                "Load observatory/PDS mission context before choosing datasets or frames.",
                "Use browse_parameters before fetch_data for CDAWeb datasets.",
                "Use browse_pds_parameters before fetch_pds_data for PDS datasets.",
                "For bulk data, always provide output_dir/output_file and return paths only.",
            ],
        })

    @mcp.tool()
    def browse_observatories() -> str:
        """List CDAWeb observatories with descriptions, dataset counts, and instruments."""
        from cdawebmcp.catalog import browse_observatories as _browse_observatories

        return _json(_browse_observatories())

    @mcp.tool()
    def load_observatory(observatory_id: str) -> str:
        """Load CDAWeb observatory prompt/catalog for a lowercase observatory stem."""
        from cdawebmcp.prompts import build_observatory_prompt

        return build_observatory_prompt(observatory_id)

    @mcp.tool()
    def browse_parameters(dataset_id: str, dataset_ids: list[str] | None = None) -> str:
        """Browse variables/metadata for one or more CDAWeb dataset IDs."""
        from cdawebmcp.metadata import browse_parameters as _browse_parameters

        return _json(_browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids))

    @mcp.tool()
    def fetch_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
    ) -> str:
        """Fetch CDAWeb timeseries data, write a file, and return metadata/stats only."""
        import pandas as pd
        from cdawebmcp.fetch import fetch_data as _fetch_data

        lib_result = _fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_short = start[:10].replace("-", "")
        stop_short = stop[:10].replace("-", "")
        frames = []
        param_meta: dict[str, dict] = {}
        for param_id, entry in lib_result.items():
            if "error" in entry:
                param_meta[param_id] = {"status": "error", "message": entry["error"]}
                continue
            df = entry["data"]
            df.columns = [f"{param_id}.{c}" for c in df.columns]
            frames.append(df)
            param_meta[param_id] = {
                "status": "success",
                "units": entry.get("units"),
                "description": entry.get("description"),
                "rows": len(df),
                "columns": list(df.columns),
                "stats": entry.get("stats"),
            }
        if not frames:
            return _json({"status": "error", "message": "No data fetched", "parameters": param_meta})
        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.join(frame, how="outer")
        base_name = f"{dataset_id}_{start_short}_{stop_short}"
        file_path = out_dir / f"{base_name}.{format}"
        counter = 1
        while file_path.exists():
            file_path = out_dir / f"{base_name}_{counter}.{format}"
            counter += 1
        if format == "json":
            data = {"time": merged.index.strftime("%Y-%m-%dT%H:%M:%S.%f").tolist()}
            for col in merged.columns:
                data[col] = [None if pd.isna(v) else v for v in merged[col].tolist()]
            file_path.write_text(json.dumps(data), encoding="utf-8")
        else:
            merged.to_csv(file_path)
        return _json({
            "status": "success",
            "file_path": str(file_path),
            "format": format,
            "dataset_id": dataset_id,
            "time_range": {"start": start, "stop": stop},
            "total_rows": len(merged),
            "parameters": param_meta,
        })

    @mcp.tool()
    def browse_pds_missions(query: str | None = None) -> str:
        """List PDS PPI missions/spacecraft with descriptions, dataset counts, and instruments."""
        from pdsmcp.catalog import browse_missions as _browse_missions

        return _json(_browse_missions(query=query))

    @mcp.tool()
    def load_pds_mission(mission_id: str) -> str:
        """Load PDS PPI mission prompt/catalog for a lowercase mission stem."""
        from pdsmcp.prompts import build_mission_prompt

        return build_mission_prompt(mission_id)

    @mcp.tool()
    def browse_pds_parameters(dataset_id: str | None = None, dataset_ids: list[str] | None = None) -> str:
        """Browse variables/metadata for one or more PDS PPI dataset IDs."""
        from pdsmcp.metadata import browse_parameters as _browse_parameters

        return _json(_browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids))

    @mcp.tool()
    def fetch_pds_data(
        dataset_id: str,
        parameters: list[str],
        start: str,
        stop: str,
        output_dir: str,
        format: Literal["csv", "json"] = "csv",
    ) -> str:
        """Fetch PDS PPI timeseries data, write a file, and return metadata/stats only."""
        import re

        import pandas as pd
        from pdsmcp.fetch import fetch_data as _fetch_data

        lib_result = _fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop)
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_short = start[:10].replace("-", "")
        stop_short = stop[:10].replace("-", "")
        frames = []
        param_meta: dict[str, dict] = {}
        for param_id, entry in lib_result.items():
            if "error" in entry:
                param_meta[param_id] = {"status": "error", "message": entry["error"]}
                continue
            df = entry["data"]
            df.columns = [f"{param_id}.{c}" for c in df.columns]
            frames.append(df)
            param_meta[param_id] = {
                "status": "success",
                "units": entry.get("units"),
                "description": entry.get("description"),
                "rows": len(df),
                "columns": list(df.columns),
                "stats": entry.get("stats"),
            }
        if not frames:
            return _json({"status": "error", "message": "No data fetched", "parameters": param_meta})
        merged = frames[0]
        for frame in frames[1:]:
            merged = merged.join(frame, how="outer")
        safe_dataset = re.sub(r"[^A-Za-z0-9_.-]+", "_", dataset_id).strip("_") or "pds_dataset"
        base_name = f"{safe_dataset}_{start_short}_{stop_short}"
        file_path = out_dir / f"{base_name}.{format}"
        counter = 1
        while file_path.exists():
            file_path = out_dir / f"{base_name}_{counter}.{format}"
            counter += 1
        if format == "json":
            data = {"time": merged.index.strftime("%Y-%m-%dT%H:%M:%S.%f").tolist()}
            for col in merged.columns:
                data[col] = [None if pd.isna(v) else v for v in merged[col].tolist()]
            file_path.write_text(json.dumps(data), encoding="utf-8")
        else:
            merged.to_csv(file_path)
        return _json({
            "status": "success",
            "file_path": str(file_path),
            "format": format,
            "dataset_id": dataset_id,
            "time_range": {"start": start, "stop": stop},
            "total_rows": len(merged),
            "parameters": param_meta,
        })

    @mcp.tool()
    def list_spice_missions() -> str:
        """List supported SPICE spacecraft/body missions with NAIF IDs and kernel status."""
        from xhelio_spice import list_supported_missions

        return _json(list_supported_missions())

    @mcp.tool()
    def get_ephemeris(
        target: str,
        time: str,
        frame: str = "ECLIPJ2000",
        observer: str = "SUN",
        output_file: str = "",
        time_end: str = "",
        step: str = "1h",
    ) -> str:
        """Get single-time state inline or timeseries trajectory written to CSV."""
        from xhelio_spice import get_state, get_trajectory
        from xhelio_spice.kernel_manager import get_kernel_manager

        if time_end:
            if not output_file:
                return _json({
                    "status": "error",
                    "message": "output_file is required when time_end is provided",
                })
            df = get_trajectory(
                target=target,
                observer=observer,
                time_start=time,
                time_end=time_end,
                step=step,
                frame=frame,
                include_velocity=True,
            )
            Path(output_file).parent.mkdir(parents=True, exist_ok=True)
            df.to_csv(output_file, index=False)
            return _json({
                "status": "success",
                "mode": "timeseries",
                "target": target,
                "observer": observer,
                "frame": frame,
                "time_start": time,
                "time_end": time_end,
                "step": step,
                "rows": len(df),
                "output_file": output_file,
                "cache_size_mb": round(get_kernel_manager().get_cache_size_bytes() / (1024 * 1024), 2),
            })
        state = get_state(target=target, observer=observer, time=time, frame=frame)
        state["status"] = "success"
        state["cache_size_mb"] = round(get_kernel_manager().get_cache_size_bytes() / (1024 * 1024), 2)
        return _json(state)

    @mcp.tool()
    def compute_distance(target1: str, target2: str, time_start: str, time_end: str, step: str = "1h") -> str:
        """Compute distance between two SPICE targets over a time range."""
        import numpy as np
        from xhelio_spice import get_trajectory

        df1 = get_trajectory(target1, observer="SUN", time_start=time_start, time_end=time_end, step=step)
        df2 = get_trajectory(target2, observer="SUN", time_start=time_start, time_end=time_end, step=step)
        distances = np.sqrt((df1["x_km"] - df2["x_km"]) ** 2 + (df1["y_km"] - df2["y_km"]) ** 2 + (df1["z_km"] - df2["z_km"]) ** 2)
        return _json({
            "status": "success",
            "target1": target1,
            "target2": target2,
            "time_start": time_start,
            "time_end": time_end,
            "step": step,
            "min_distance_km": float(distances.min()),
            "max_distance_km": float(distances.max()),
            "mean_distance_km": float(distances.mean()),
            "samples": len(distances),
        })

    @mcp.tool()
    def transform_coordinates(
        vector: list[float],
        time: str,
        from_frame: str,
        to_frame: str,
        spacecraft: str | None = None,
    ) -> str:
        """Transform a 3D vector between SPICE coordinate frames."""
        from xhelio_spice import transform_vector

        result = transform_vector(vector, time, from_frame=from_frame, to_frame=to_frame, spacecraft=spacecraft)
        return _json({
            "status": "success",
            "input_vector": vector,
            "output_vector": result,
            "from_frame": from_frame,
            "to_frame": to_frame,
            "time": time,
            "spacecraft": spacecraft,
        })

    @mcp.tool()
    def list_coordinate_frames() -> str:
        """List supported SPICE coordinate frames and usage notes."""
        from xhelio_spice import list_frames_with_descriptions

        return _json(list_frames_with_descriptions())

    @mcp.tool()
    def manage_cdaweb_cache(
        action: Literal["status", "clean", "refresh_metadata", "refresh_time_ranges", "rebuild_catalog"],
        category: Literal["metadata", "cdf_cache", "all"] = "all",
        observatory: str | None = None,
        dataset_ids: list[str] | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
        detail: bool = False,
    ) -> str:
        """Manage CDAWeb cache and metadata/catalog refresh operations."""
        from cdawebmcp.cache import cache_clean, cache_status, rebuild_catalog, refresh_metadata, refresh_time_ranges

        if action == "status":
            return _json(cache_status(detail=detail))
        if action == "clean":
            return _json(cache_clean(category=category, observatory=observatory, older_than_days=older_than_days, dry_run=dry_run))
        if action == "refresh_metadata":
            return _json(refresh_metadata(dataset_ids=dataset_ids, observatory=observatory))
        if action == "refresh_time_ranges":
            return _json(refresh_time_ranges(observatory=observatory))
        if action == "rebuild_catalog":
            return _json(rebuild_catalog(observatory=observatory))
        return _json({"status": "error", "message": f"Unknown action: {action}"})

    @mcp.tool()
    def manage_pds_cache(
        action: Literal["status", "clean", "refresh_metadata", "build_metadata", "refresh_time_ranges", "rebuild_catalog"],
        category: Literal["metadata", "data_cache", "all"] = "all",
        mission: str | None = None,
        dataset_ids: list[str] | None = None,
        older_than_days: int | None = None,
        dry_run: bool = True,
        detail: bool = False,
        force: bool = False,
    ) -> str:
        """Manage PDS cache and metadata/catalog refresh operations."""
        from pdsmcp.cache import build_metadata, cache_clean, cache_status, refresh_metadata, refresh_time_ranges, rebuild_catalog

        if action == "status":
            return _json(cache_status(detail=detail))
        if action == "clean":
            missions = [mission] if mission else None
            return _json(cache_clean(category=category, missions=missions, older_than_days=older_than_days, dry_run=dry_run))
        if action == "refresh_metadata":
            return _json(refresh_metadata(dataset_ids=dataset_ids, mission=mission))
        if action == "build_metadata":
            return _json(build_metadata(mission=mission, force=force))
        if action == "refresh_time_ranges":
            return _json(refresh_time_ranges(mission=mission))
        if action == "rebuild_catalog":
            return _json(rebuild_catalog(mission=mission))
        return _json({"status": "error", "message": f"Unknown action: {action}"})

    @mcp.tool()
    def manage_spice_kernels(
        action: Literal["status", "load", "clean", "check_remote", "purge"],
        mission: str | None = None,
        filenames: list[str] | None = None,
    ) -> str:
        """Manage SPICE kernels and cache state."""
        from xhelio_spice.kernel_manager import check_remote_kernels, get_kernel_manager

        km = get_kernel_manager()
        if action == "status":
            return _json(km.get_cache_info())
        if action == "load":
            if not mission:
                return _json({"status": "error", "message": "mission is required for load"})
            km.ensure_mission_kernels(mission)
            return _json({"status": "success", "mission": mission, "cache_info": km.get_cache_info()})
        if action == "clean":
            if not mission and not filenames:
                return _json({"status": "error", "message": "mission or filenames required for clean"})
            deleted = km.delete_cached_files(filenames) if filenames else km.delete_mission_cache(mission or "")
            return _json({"status": "success", "deleted_files": deleted, "cache_info": km.get_cache_info()})
        if action == "check_remote":
            return _json(check_remote_kernels(mission) if mission else {"status": "error", "message": "mission is required for check_remote"})
        if action == "purge":
            deleted = km.purge_cache()
            return _json({"status": "success", "deleted_files": deleted})
        return _json({"status": "error", "message": f"Unknown action: {action}"})

    return mcp


def serve() -> None:
    """Run the MCP server over stdio transport."""
    parser = argparse.ArgumentParser(description="Unified SPEDAS MCP server")
    parser.add_argument("--cdaweb-cache-dir", default=None, help="Override CDAWeb cache root directory")
    parser.add_argument("--spice-kernel-dir", default=None, help="Override SPICE kernel cache directory")
    parser.add_argument("--pds-cache-dir", default=None, help="Override PDS PPI cache root directory")
    args = parser.parse_args()

    import os

    cdaweb_cache_dir = args.cdaweb_cache_dir or os.environ.get("XHELIO_CDAWEB_CACHE_DIR")
    if cdaweb_cache_dir:
        from cdawebmcp import configure
        configure(cache_dir=cdaweb_cache_dir)

    spice_kernel_dir = args.spice_kernel_dir or os.environ.get("XHELIO_SPICE_KERNEL_DIR")
    if spice_kernel_dir:
        os.environ["XHELIO_SPICE_KERNEL_DIR"] = spice_kernel_dir

    pds_cache_dir = args.pds_cache_dir or os.environ.get("PDSMCP_CACHE_DIR")
    if pds_cache_dir:
        from pdsmcp.config import configure as configure_pds
        configure_pds(cache_dir=pds_cache_dir)

    logging.basicConfig(level=logging.INFO)
    create_server().run()
