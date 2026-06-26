"""Unified SPEDAS-oriented MCP server.

The server follows Jason's updated A+B direction:

A. Present one SPEDAS data layer organized by data source categories.
B. Add a SPEDAS science-workflow layer so agents can plan a study before using
   source-specific data and geometry operations.

The focused XHelio packages remain internal backends, not the user-facing mental
model. Outward-facing tools should speak in terms of SPEDAS data sources such as
CDAWeb, PDS, and SPICE/geometry.
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
from typing import Any, Literal

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
            "SPEDAS MCP facade for heliophysics workflows. Start with the SPEDAS "
            "science-workflow tools to plan a study, then use the unified data-layer "
            "tools with source_type=cdaweb, pds, or spice. CDAWeb and PDS provide "
            "measurement/archive data; SPICE provides geometry, ephemeris, frames, "
            "and trajectory context. Focus on SPEDAS data sources rather than backend "
            "package names. Plan/discover before fetching; write bulk data to files; "
            "return compact metadata and paths."
        ),
    )

    @mcp.tool()
    def spedas_overview() -> str:
        """Describe available SPEDAS MCP capabilities and the recommended workflow."""
        return _json({
            "status": "success",
            "server": "spedas-mcp",
            "capability_groups": {
                "data": [
                    "browse_data_sources",
                    "load_data_source",
                    "browse_data_parameters",
                    "fetch_data_product",
                    "manage_data_cache",
                ],
                "science_workflows": [
                    "search_spedas_data_sources",
                    "plan_spedas_observation",
                    "compare_cdaweb_pds_spice",
                    "create_spedas_analysis_bundle",
                ],
                "geometry": [
                    "list_spice_missions",
                    "get_ephemeris",
                    "compute_distance",
                    "transform_coordinates",
                    "list_coordinate_frames",
                ],
                "analysis": {
                    "status": "optional pyspedas backend; install with spedas-mcp[analysis]",
                    "tools": [
                        "transform_timeseries_coordinates",
                        "generate_fac_matrix",
                        "analyze_minvar_coordinates",
                    ],
                },
                "compatibility_low_level": {
                    "status": "supported compatibility surface; not the preferred starting point",
                    "prefer": [
                        "browse_data_sources",
                        "load_data_source",
                        "browse_data_parameters",
                        "fetch_data_product",
                        "manage_data_cache",
                    ],
                    "available_for_existing_clients": [
                        "browse_observatories",
                        "load_observatory",
                        "browse_parameters",
                        "fetch_data",
                        "browse_pds_missions",
                        "load_pds_mission",
                        "browse_pds_parameters",
                        "fetch_pds_data",
                        "manage_cdaweb_cache",
                        "manage_pds_cache",
                        "manage_spice_kernels",
                    ],
                },
            },
            "workflow": [
                "Start with search_spedas_data_sources or plan_spedas_observation for open-ended science requests.",
                "Use browse_data_sources(source_type='all') to inspect SPEDAS data-source categories.",
                "Use load_data_source, browse_data_parameters, fetch_data_product, and manage_data_cache for the unified data layer.",
                "load_data_source(source_type='cdaweb', ...) enumerates dataset_ids so you can call browse_data_parameters without guessing; pass the science goal to search_spedas_data_sources via question= (query= is accepted as an alias).",
                "Treat source-specific CDAWeb/PDS cache/fetch/browse tools as compatibility tools for existing clients; do not choose them first for new agent workflows.",
                "Use geometry tools directly when the request is SPICE-specific ephemeris, frame, distance, or transform work.",
                "Use create_spedas_analysis_bundle to preserve request/provenance intent before bulk fetches.",
                "For bulk data, always provide output_dir/output_file and return paths only.",
            ],
        })

    @mcp.tool()
    def search_spedas_data_sources(
        question: str = "",
        target: str | None = None,
        observables: list[str] | None = None,
        query: str | None = None,
    ) -> str:
        """Recommend whether a SPEDAS request should start with CDAWeb, PDS, SPICE, or a mix.

        Pass the natural-language science goal as ``question``. ``query`` is accepted
        as a backward-compatible alias so callers familiar with
        ``browse_data_sources(query=...)`` are not silently given empty results;
        ``question`` takes precedence when both are provided.
        """
        from spedas_mcp.workflows import search_data_sources

        return _json(
            search_data_sources(
                question=question,
                target=target,
                observables=observables,
                query=query,
            )
        )

    @mcp.tool()
    def plan_spedas_observation(
        science_goal: str,
        start: str | None = None,
        stop: str | None = None,
        target: str | None = None,
        observables: list[str] | None = None,
        data_sources: list[str] | None = None,
    ) -> str:
        """Plan a SPEDAS science workflow before choosing data-layer or geometry calls."""
        from spedas_mcp.workflows import plan_observation

        return _json(plan_observation(
            science_goal=science_goal,
            start=start,
            stop=stop,
            target=target,
            observables=observables,
            data_sources=data_sources,
        ))

    @mcp.tool()
    def compare_cdaweb_pds_spice(science_goal: str = "") -> str:
        """Compare CDAWeb, PDS, and SPICE roles for a SPEDAS MCP science request."""
        from spedas_mcp.workflows import compare_sources

        return _json(compare_sources(science_goal=science_goal))

    @mcp.tool()
    def create_spedas_analysis_bundle(
        study_name: str,
        output_dir: str,
        science_goal: str = "",
        target: str | None = None,
        start: str | None = None,
        stop: str | None = None,
        data_sources: list[str] | None = None,
    ) -> str:
        """Create a lightweight request/provenance bundle for a planned SPEDAS analysis."""
        from spedas_mcp.workflows import create_analysis_bundle

        return _json(create_analysis_bundle(
            study_name=study_name,
            output_dir=output_dir,
            science_goal=science_goal,
            target=target,
            start=start,
            stop=stop,
            data_sources=data_sources,
        ))

    @mcp.tool()
    def browse_observatories() -> str:
        """Compatibility: list CDAWeb observatories. Prefer browse_data_sources(source_type="cdaweb") for new workflows."""
        from cdawebmcp.catalog import browse_observatories as _browse_observatories

        return _json(_browse_observatories())

    @mcp.tool()
    def load_observatory(observatory_id: str) -> str:
        """Compatibility: load CDAWeb observatory context. Prefer load_data_source(source_type="cdaweb", source_id=...)."""
        from cdawebmcp.prompts import build_observatory_prompt

        return build_observatory_prompt(observatory_id)

    @mcp.tool()
    def browse_parameters(dataset_id: str, dataset_ids: list[str] | None = None) -> str:
        """Compatibility: browse CDAWeb variables. Prefer browse_data_parameters(source_type="cdaweb", ...)."""
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
        """Compatibility: fetch CDAWeb time-series data. Prefer fetch_data_product(source_type="cdaweb", ...)."""
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
        """Compatibility: list PDS PPI missions. Prefer browse_data_sources(source_type="pds") for new workflows."""
        from pdsmcp.catalog import browse_missions as _browse_missions

        return _json(_browse_missions(query=query))

    @mcp.tool()
    def load_pds_mission(mission_id: str) -> str:
        """Compatibility: load PDS mission context. Prefer load_data_source(source_type="pds", source_id=...)."""
        from pdsmcp.prompts import build_mission_prompt

        return build_mission_prompt(mission_id)

    @mcp.tool()
    def browse_pds_parameters(dataset_id: str | None = None, dataset_ids: list[str] | None = None) -> str:
        """Compatibility: browse PDS variables. Prefer browse_data_parameters(source_type="pds", ...)."""
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
        """Compatibility: fetch PDS archive data. Prefer fetch_data_product(source_type="pds", ...)."""
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
        """Compatibility: manage CDAWeb cache. Prefer manage_data_cache(source_type="cdaweb", ...)."""
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
        """Compatibility: manage PDS cache. Prefer manage_data_cache(source_type="pds", ...)."""
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
        """Manage SPICE kernels/cache; use manage_data_cache(source_type="spice") for data-layer cache status."""
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


    def _normalize_source_type(source_type: str | None) -> str:
        value = (source_type or "all").strip().lower().replace("-", "_")
        aliases = {
            "all_sources": "all",
            "all": "all",
            "cda": "cdaweb",
            "cda_web": "cdaweb",
            "cdaweb": "cdaweb",
            "pds_ppi": "pds",
            "pds": "pds",
            "spice_geometry": "spice",
            "geometry": "spice",
            "spice": "spice",
        }
        return aliases.get(value, value)

    def _payload_has_error(payload: Any) -> bool:
        if isinstance(payload, dict):
            status = str(payload.get("status", "")).lower()
            if status in {"error", "failed", "failure"}:
                return True
            if payload.get("error"):
                return True
            return any(_payload_has_error(value) for value in payload.values())
        if isinstance(payload, list):
            return any(_payload_has_error(value) for value in payload)
        return False

    def _wrap_data_payload(source_type: str, raw: str, **extra: Any) -> str:
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw
        status = "error" if _payload_has_error(payload) else "success"
        return _json({"status": status, "source_type": source_type, "payload": payload, **extra})

    def _filter_json_records(raw: str, query: str | None) -> str:
        """Apply a compact query filter to list-shaped backend JSON payloads."""
        if not query:
            return raw
        try:
            payload = json.loads(raw)
        except Exception:
            return raw
        if not isinstance(payload, list):
            return raw
        needle = query.casefold()
        filtered = [
            entry for entry in payload
            if needle in json.dumps(entry, default=str).casefold()
        ]
        return _json(filtered)

    def _normalize_pds_source_id(source_id: str) -> str:
        value = (source_id or "").strip().lower().replace("-", "_")
        if value.endswith("_ppi"):
            value = value[:-4]
        return value

    # Byte budget for the structured dataset catalog added to a load_data_source
    # response. The observatory prompt payload itself is ~38KB for large
    # observatories (e.g. MMS); capping the structured list keeps the total
    # response within the MCP stdio response-size safety expectation (<64KB).
    _DATASET_ENUM_BYTE_BUDGET = 16000

    def _enumerate_cdaweb_datasets(source_id: str) -> dict[str, Any] | None:
        """Return a compact, JSON-serializable dataset catalog for a CDAWeb observatory.

        Reads the observatory JSON directly so agents can move from
        ``load_data_source`` to ``browse_data_parameters`` without guessing
        dataset IDs (issue #31). Entries carry the dataset id, instrument key,
        and coverage dates — enough to plan a fetch — while human-readable
        descriptions remain in the prompt payload. The list is bounded by the
        actual serialized size of the structured enumeration payload and reports
        ``datasets_truncated``/``dataset_count`` so very large observatories stay
        size-safe without hiding the true total.

        Returns ``None`` if enumeration is unavailable so the existing
        observatory prompt payload is preserved unchanged.
        """
        try:
            from cdawebmcp.catalog import load_observatory_json
        except Exception:  # pragma: no cover - backend not installed
            return None
        stem = (source_id or "").strip().lower().replace("-", "_")
        try:
            observatory = load_observatory_json(stem)
        except Exception:
            # Unknown/invalid observatory stem: leave discovery to the prompt payload.
            return None

        instruments = observatory.get("instruments", {})
        if not isinstance(instruments, dict):
            return None

        all_entries: list[dict[str, Any]] = []
        for inst_key, inst_data in sorted(instruments.items()):
            if not isinstance(inst_data, dict):
                continue
            for ds_id, ds_info in sorted(inst_data.get("datasets", {}).items()):
                ds_info = ds_info if isinstance(ds_info, dict) else {}
                all_entries.append({
                    "dataset_id": ds_id,
                    "instrument": inst_key,
                    "start_date": ds_info.get("start_date"),
                    "stop_date": ds_info.get("stop_date"),
                })

        total = len(all_entries)
        instrument_names = sorted(instruments.keys())

        def _dataset_note(shown: int) -> str:
            return (
                f"Showing {shown} of {total} datasets to stay within the "
                "response-size limit. Use browse_data_sources(source_type='cdaweb', "
                "query=...) to filter, or the compatibility load_observatory tool for "
                "the full per-instrument catalog."
            )

        def _dataset_payload(entries: list[dict[str, Any]]) -> dict[str, Any]:
            truncated = len(entries) < total
            payload: dict[str, Any] = {
                "dataset_count": total,
                "datasets": entries,
                "datasets_truncated": truncated,
                "instruments": instrument_names,
            }
            if truncated:
                payload["datasets_note"] = _dataset_note(len(entries))
            return payload

        def _serialized_dataset_bytes(entries: list[dict[str, Any]]) -> int:
            return len(json.dumps(_dataset_payload(entries), default=str, indent=2).encode("utf-8"))

        datasets: list[dict[str, Any]] = []
        for entry in all_entries:
            candidate = [*datasets, entry]
            if _serialized_dataset_bytes(candidate) > _DATASET_ENUM_BYTE_BUDGET and datasets:
                break
            datasets.append(entry)

        return _dataset_payload(datasets)

    @mcp.tool()
    def browse_data_sources(source_type: str = "all", query: str | None = None) -> str:
        """Primary data layer: browse SPEDAS source categories (CDAWeb, PDS, SPICE)."""
        source = _normalize_source_type(source_type)
        if source == "all":
            return _json({
                "status": "success",
                "data_layer": "spedas",
                "source_types": [
                    {
                        "source_type": "cdaweb",
                        "label": "CDAWeb heliophysics time-series",
                        "best_for": "observatory/dataset/parameter discovery and measurement fetches",
                        "next_tools": ["browse_data_sources(source_type='cdaweb')", "load_data_source", "browse_data_parameters", "fetch_data_product"],
                    },
                    {
                        "source_type": "pds",
                        "label": "PDS Planetary Plasma Interactions archive",
                        "best_for": "planetary mission/dataset/parameter discovery and archive-backed fetches",
                        "next_tools": ["browse_data_sources(source_type='pds')", "load_data_source", "browse_data_parameters", "fetch_data_product"],
                    },
                    {
                        "source_type": "spice",
                        "label": "SPICE geometry and ephemeris",
                        "best_for": "trajectory, distance, frames, coordinate transforms, and geometry context",
                        "next_tools": ["browse_data_sources(source_type='spice')", "load_data_source", "get_ephemeris", "compute_distance", "transform_coordinates"],
                    },
                ],
                "query": query,
                "note": "Use source_type to drill into one category. XHelio package names are internal backend details.",
            })
        if source == "cdaweb":
            return _wrap_data_payload(source, _filter_json_records(browse_observatories(), query), query=query)
        if source == "pds":
            return _wrap_data_payload(source, browse_pds_missions(query=query), query=query)
        if source == "spice":
            return _wrap_data_payload(source, _filter_json_records(list_spice_missions(), query), query=query, note="SPICE is exposed as the geometry data-source category.")
        return _json({"status": "error", "error": f"unknown source_type: {source_type}", "allowed": ["all", "cdaweb", "pds", "spice"]})

    @mcp.tool()
    def load_data_source(source_type: str, source_id: str) -> str:
        """Primary data layer: load source context for a CDAWeb observatory, PDS mission, or SPICE mission/frame.

        For CDAWeb observatories the response also includes an enumerated
        ``datasets`` list (``dataset_id``, ``instrument``, coverage dates) plus
        ``dataset_count``/``datasets_truncated``, so agents can pass a concrete
        ``dataset_id`` straight to ``browse_data_parameters`` without guessing.
        """
        source = _normalize_source_type(source_type)
        if source == "cdaweb":
            enumeration = _enumerate_cdaweb_datasets(source_id)
            extra: dict[str, Any] = {"source_id": source_id}
            if enumeration is not None:
                # Additive discovery fields (issue #31): agents can read dataset_ids
                # here and pass them straight to browse_data_parameters.
                extra.update(enumeration)
            return _wrap_data_payload(source, load_observatory(source_id), **extra)
        if source == "pds":
            normalized_source_id = _normalize_pds_source_id(source_id)
            return _wrap_data_payload(
                source,
                load_pds_mission(normalized_source_id),
                source_id=source_id,
                normalized_source_id=normalized_source_id,
            )
        if source == "spice":
            return _wrap_data_payload(
                source,
                list_coordinate_frames(),
                source_id=source_id,
                note="SPICE source loading returns the global coordinate-frame catalog; use geometry tools with mission/target arguments for mission-specific context.",
            )
        return _json({"status": "error", "error": f"unknown source_type: {source_type}", "allowed": ["cdaweb", "pds", "spice"]})

    @mcp.tool()
    def browse_data_parameters(
        source_type: str,
        dataset_id: str,
        dataset_ids: list[str] | None = None,
    ) -> str:
        """Primary data layer: browse parameters/metadata using source_type rather than source-specific tool names."""
        source = _normalize_source_type(source_type)
        if source == "cdaweb":
            return _wrap_data_payload(source, browse_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids), dataset_id=dataset_id)
        if source == "pds":
            return _wrap_data_payload(source, browse_pds_parameters(dataset_id=dataset_id, dataset_ids=dataset_ids), dataset_id=dataset_id)
        if source == "spice":
            return _wrap_data_payload(
                source,
                list_coordinate_frames(),
                dataset_id=dataset_id,
                note="SPICE does not expose measurement parameters; use frames/targets/observer geometry instead.",
            )
        return _json({"status": "error", "error": f"unknown source_type: {source_type}", "allowed": ["cdaweb", "pds", "spice"]})

    @mcp.tool()
    def fetch_data_product(
        source_type: str,
        dataset_id: str,
        parameters: list[str],
        start: str | None = None,
        stop: str | None = None,
        output_dir: str | None = None,
        format: Literal["csv", "json"] = "csv",
        limit: int | None = None,
    ) -> str:
        """Primary data layer: fetch CDAWeb/PDS measurement or archive products; route SPICE geometry to geometry tools."""
        source = _normalize_source_type(source_type)
        if source == "cdaweb":
            if start is None or stop is None or output_dir is None:
                return _json({"status": "error", "error": "cdaweb fetch requires start, stop, and output_dir"})
            return _wrap_data_payload(source, fetch_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop, output_dir=output_dir, format=format), dataset_id=dataset_id)
        if source == "pds":
            if start is None or stop is None or output_dir is None:
                return _json({"status": "error", "source_type": "pds", "error": "pds fetch requires start, stop, and output_dir"})
            if limit is not None:
                return _json({
                    "status": "error",
                    "source_type": "pds",
                    "error": "PDS fetch_data_product does not support a limit argument yet; narrow start/stop/parameters or omit limit.",
                    "unsupported_argument": "limit",
                })
            return _wrap_data_payload(source, fetch_pds_data(dataset_id=dataset_id, parameters=parameters, start=start, stop=stop, output_dir=output_dir, format=format), dataset_id=dataset_id)
        if source == "spice":
            return _json({
                "status": "error",
                "source_type": "spice",
                "error": "SPICE is geometry/ephemeris, not a measurement product fetch. Use get_ephemeris, compute_distance, or transform_coordinates.",
                "recommended_tools": ["get_ephemeris", "compute_distance", "transform_coordinates"],
            })
        return _json({"status": "error", "error": f"unknown source_type: {source_type}", "allowed": ["cdaweb", "pds", "spice"]})

    @mcp.tool()
    def manage_data_cache(
        source_type: str = "all",
        action: Literal["status", "clean"] = "status",
        cache_dir: str | None = None,
        mission: str | None = None,
    ) -> str:
        """Primary data layer: manage cache status/maintenance by source_type."""
        source = _normalize_source_type(source_type)
        cache_note = None
        if cache_dir:
            cache_note = "cache_dir is configured by the MCP server/environment; unified manage_data_cache does not override backend cache roots per call."
        if source == "all":
            return _json({
                "status": "success",
                "source_type": "all",
                "caches": {
                    "cdaweb": json.loads(manage_cdaweb_cache(action=action)),
                    "pds": json.loads(manage_pds_cache(action=action, mission=mission)),
                    "spice": json.loads(manage_spice_kernels(action=action, mission=mission)),
                },
                "note": cache_note,
            })
        if source == "cdaweb":
            return _wrap_data_payload(source, manage_cdaweb_cache(action=action), note=cache_note)
        if source == "pds":
            return _wrap_data_payload(source, manage_pds_cache(action=action, mission=mission), note=cache_note)
        if source == "spice":
            return _wrap_data_payload(source, manage_spice_kernels(action=action, mission=mission), note=cache_note)
        return _json({"status": "error", "error": f"unknown source_type: {source_type}", "allowed": ["all", "cdaweb", "pds", "spice"]})

    # ------------------------------------------------------------------
    # Analysis layer (Phase 1: coordinate transforms). Optional pyspedas
    # backend via the spedas-mcp[analysis] extra; tools import it lazily and
    # return a clear install error when the extra is missing.
    # ------------------------------------------------------------------

    @mcp.tool()
    def transform_timeseries_coordinates(
        input_file: str,
        coord_in: str,
        coord_out: str,
        output_file: str,
        time_col: str = "time",
        vector_cols: list[str] | None = None,
    ) -> str:
        """Analysis: transform an Nx3 vector time-series between GSE/GSM/SM/GEI/GEO/MAG/J2000.

        Reads a fetched CSV/JSON artifact, transforms with pyspedas cotrans,
        writes the transformed series to output_file, and returns paths plus
        per-component summary stats only. Requires spedas-mcp[analysis].
        """
        from spedas_mcp.analysis.coords import transform_timeseries_coordinates as _impl

        return _json(_impl(
            input_file=input_file,
            coord_in=coord_in,
            coord_out=coord_out,
            output_file=output_file,
            time_col=time_col,
            vector_cols=vector_cols,
        ))

    @mcp.tool()
    def generate_fac_matrix(
        mag_file: str,
        output_file: str,
        other_dim: str = "xgse",
        pos_file: str | None = None,
        time_col: str = "time",
        vector_cols: list[str] | None = None,
        mag_coord: str = "gse",
    ) -> str:
        """Analysis: build per-sample field-aligned-coordinate (FAC) 3x3 rotation matrices.

        Backend: pyspedas fac_matrix_make. Writes the (N,3,3) matrix stack to
        output_file (.npy/.npz) and returns shape + mode + path only. Position-
        dependent modes (rgeo/mrgeo/phigeo/mphigeo/phism/mphism) require a GEI
        position series via pos_file. Requires spedas-mcp[analysis].
        """
        from spedas_mcp.analysis.coords import generate_fac_matrix as _impl

        return _json(_impl(
            mag_file=mag_file,
            output_file=output_file,
            other_dim=other_dim,
            pos_file=pos_file,
            time_col=time_col,
            vector_cols=vector_cols,
            mag_coord=mag_coord,
        ))

    @mcp.tool()
    def analyze_minvar_coordinates(
        input_file: str,
        output_dir: str,
        twindow: float | None = None,
        tslide: float | None = None,
        time_col: str = "time",
        vector_cols: list[str] | None = None,
    ) -> str:
        """Analysis: minimum-variance analysis (MVA) / LMN boundary-normal frame.

        Backend: pyspedas minvar / minvar_matrix_make. Full-interval mode
        (twindow=None) returns eigenvalues, eigenvectors, the normal vector, and
        the intermediate/min ratio plus a rotated-series file path. Sliding-window
        mode writes per-window rotation matrices. Requires spedas-mcp[analysis].
        """
        from spedas_mcp.analysis.coords import analyze_minvar_coordinates as _impl

        return _json(_impl(
            input_file=input_file,
            output_dir=output_dir,
            twindow=twindow,
            tslide=tslide,
            time_col=time_col,
            vector_cols=vector_cols,
        ))

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
