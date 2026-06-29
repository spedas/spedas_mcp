"""
SPICE kernel download, caching, and loading.

KernelManager is a thread-safe singleton that handles:
- Downloading kernels from NAIF on first use
- Caching kernels in the backward-compatible ~/.xhelio_spice/kernels/ cache (override via XHELIO_SPICE_KERNEL_DIR)
- Loading/unloading kernels via spiceypy.furnsh/kclear
- Tracking loaded kernels to avoid double-loading
"""

import importlib.resources
import json
import logging
import os
import threading
from datetime import date
from html.parser import HTMLParser
from pathlib import Path

import spiceypy as spice

from .missions import GENERIC_KERNELS, MISSION_KERNELS

logger = logging.getLogger("spedas_agent_kit.backends.spice")


class _LinkExtractor(HTMLParser):
    """Extract href attributes from <a> tags in HTML directory listings."""

    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance = None
_instance_lock = threading.Lock()


def get_kernel_manager() -> "KernelManager":
    """Return the KernelManager singleton."""
    global _instance
    if _instance is not None:
        return _instance
    with _instance_lock:
        if _instance is not None:
            return _instance
        _instance = KernelManager()
        return _instance


class KernelManager:
    """Thread-safe manager for SPICE kernel download, cache, and loading.

    SPICE has a global kernel pool, so all operations are serialized
    via an RLock to prevent concurrent furnsh/spkpos calls from
    corrupting state.
    """

    def __init__(self, kernel_dir: Path | str | None = None):
        self._lock = threading.RLock()
        self._loaded_kernels: set[str] = set()
        self._generic_loaded = False
        self._mission_kernels_loaded: set[str] = set()
        self._segmented_files_loaded: set[str] = set()

        if kernel_dir is not None:
            self._kernel_dir = Path(kernel_dir)
        else:
            base = os.environ.get("XHELIO_SPICE_KERNEL_DIR")
            if base:
                self._kernel_dir = Path(base)
            else:
                self._kernel_dir = Path.home() / ".xhelio_spice" / "kernels"
        self._kernel_dir.mkdir(parents=True, exist_ok=True)

    @property
    def lock(self) -> threading.RLock:
        """Expose the lock for external callers that need SPICE thread safety."""
        return self._lock

    @property
    def kernel_dir(self) -> Path:
        return self._kernel_dir

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_kernel(self, url: str, filename: str) -> Path:
        """Download a kernel file if not already cached.

        Args:
            url: HTTP(S) URL to fetch from.
            filename: Local filename to save as.

        Returns:
            Path to the cached file.

        Raises:
            RuntimeError: If the download fails.
        """
        local_path = self._kernel_dir / filename
        if local_path.exists() and local_path.stat().st_size > 0:
            logger.debug("Kernel cached: %s", filename)
            return local_path

        logger.info("Downloading kernel: %s", filename)
        import requests
        try:
            resp = requests.get(url, stream=True, timeout=300)
            resp.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Failed to download kernel {filename} from {url}: {e}") from e

        # Write to temp file then rename for atomicity
        tmp_path = local_path.with_suffix(".tmp")
        try:
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=1024 * 1024):
                    f.write(chunk)
            tmp_path.rename(local_path)
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

        logger.info("Downloaded kernel: %s (%d bytes)", filename, local_path.stat().st_size)
        return local_path

    # ------------------------------------------------------------------
    # Load / unload
    # ------------------------------------------------------------------

    def load_kernel(self, path: Path) -> None:
        """Load a kernel into the SPICE pool (idempotent).

        Args:
            path: Path to the kernel file.
        """
        key = str(path.resolve())
        with self._lock:
            if key in self._loaded_kernels:
                return
            spice.furnsh(key)
            self._loaded_kernels.add(key)
            logger.debug("Loaded kernel: %s", path.name)

    def unload_all(self) -> None:
        """Unload all kernels and clear state."""
        with self._lock:
            spice.kclear()
            self._loaded_kernels.clear()
            self._generic_loaded = False
            self._mission_kernels_loaded.clear()
            self._segmented_files_loaded.clear()
            logger.info("Unloaded all SPICE kernels")

    def list_loaded(self) -> list[str]:
        """Return list of currently loaded kernel file names."""
        with self._lock:
            return [Path(k).name for k in sorted(self._loaded_kernels)]

    # ------------------------------------------------------------------
    # High-level ensure methods
    # ------------------------------------------------------------------

    def ensure_generic_kernels(self) -> None:
        """Download and load generic kernels (LSK, PCK, planetary SPK).

        Idempotent — safe to call multiple times.
        Loading order: LSK -> PCK -> SPK (dependencies first).
        """
        if self._generic_loaded:
            return

        # Order matters: LSK first (time conversion), then PCK, then SPK
        ordered_files = [
            "naif0012.tls",   # Leap seconds
            "pck00011.tpc",   # Planetary constants
            "gm_de440.tpc",   # Gravitational parameters
            "de440s.bsp",     # Planetary ephemerides
        ]

        for filename in ordered_files:
            url = GENERIC_KERNELS.get(filename)
            if url is None:
                continue
            path = self.download_kernel(url, filename)
            self.load_kernel(path)

        self._generic_loaded = True
        logger.info("Generic kernels loaded")

    def ensure_mission_kernels(self, mission_key: str) -> None:
        """Download and load mission-specific kernels.

        Also ensures generic kernels are loaded first.

        Args:
            mission_key: Canonical mission key (e.g., "PSP", "SOLO").

        Raises:
            KeyError: If no kernels are defined for this mission.
        """
        if mission_key in self._mission_kernels_loaded:
            return

        self.ensure_generic_kernels()

        kernels = MISSION_KERNELS.get(mission_key)
        if kernels is None:
            from .missions import SEGMENTED_MISSIONS
            if mission_key in SEGMENTED_MISSIONS:
                raise KeyError(
                    f"Mission '{mission_key}' uses segmented kernels. "
                    f"Use ensure_segmented_kernels() with a time range instead."
                )
            raise KeyError(
                f"No SPICE kernels defined for mission '{mission_key}'. "
                f"Available: {', '.join(sorted(MISSION_KERNELS.keys()))}"
            )

        for filename, url in kernels.items():
            path = self.download_kernel(url, filename)
            self.load_kernel(path)

        self._mission_kernels_loaded.add(mission_key)
        logger.info("Mission kernels loaded: %s", mission_key)

    # ------------------------------------------------------------------
    # Segmented kernel support
    # ------------------------------------------------------------------

    def _load_manifest(self, mission_key: str) -> list[dict]:
        """Load a segment manifest JSON for a mission.

        Args:
            mission_key: Canonical mission key (e.g., "CASSINI").

        Returns:
            List of segment dicts with keys: file, url, start, stop.
        """
        from .missions import SEGMENTED_MISSIONS
        manifest_file = SEGMENTED_MISSIONS[mission_key]
        ref = importlib.resources.files("spedas_agent_kit.backends.spice.manifests").joinpath(manifest_file)
        return json.loads(ref.read_text(encoding="utf-8"))

    def ensure_segmented_kernels(
        self, mission_key: str, time_start: date, time_end: date
    ) -> None:
        """Download and load segmented kernels covering a time range.

        Loads only the segments that overlap [time_start, time_end].

        Args:
            mission_key: Canonical mission key (e.g., "CASSINI").
            time_start: Start date of the query window.
            time_end: End date of the query window.

        Raises:
            ValueError: If no segments cover the requested time range.
        """
        self.ensure_generic_kernels()

        manifest = self._load_manifest(mission_key)

        # Find segments overlapping [time_start, time_end]
        matching = []
        for seg in manifest:
            seg_start = date.fromisoformat(seg["start"])
            seg_stop = date.fromisoformat(seg["stop"])
            if seg_start <= time_end and seg_stop >= time_start:
                matching.append(seg)

        if not matching:
            # Build coverage summary for error message
            if manifest:
                first = manifest[0]["start"]
                last = manifest[-1]["stop"]
                raise ValueError(
                    f"No kernel segments for {mission_key} cover "
                    f"{time_start} to {time_end}. "
                    f"Available coverage: {first} to {last}."
                )
            else:
                raise ValueError(
                    f"Manifest for {mission_key} is empty — no segments available."
                )

        for seg in matching:
            filename = seg["file"]
            if filename in self._segmented_files_loaded:
                continue
            path = self.download_kernel(seg["url"], filename)
            self.load_kernel(path)
            self._segmented_files_loaded.add(filename)

        logger.info(
            "Segmented kernels loaded for %s: %d segments (%s to %s)",
            mission_key, len(matching),
            matching[0]["start"], matching[-1]["stop"],
        )

    # ------------------------------------------------------------------
    # Remote kernel checking
    # ------------------------------------------------------------------

    def check_remote_kernels(self, mission_key: str) -> dict:
        """Check a remote NAIF directory for .bsp files not in the configured set.

        Only works for single-file missions (not segmented).

        Args:
            mission_key: Canonical mission key (e.g., "PSP", "JUNO").

        Returns:
            Dict with mission, configured_files, directories (each with url,
            all_bsp_files, and optional error), and other_files.

        Raises:
            KeyError: If mission_key is segmented or has no kernels defined.
        """
        from .missions import SEGMENTED_MISSIONS

        if mission_key in SEGMENTED_MISSIONS:
            raise KeyError(
                f"Mission '{mission_key}' uses segmented kernels. "
                f"check_remote_kernels only supports single-file missions."
            )

        kernels = MISSION_KERNELS.get(mission_key)
        if kernels is None:
            raise KeyError(
                f"No SPICE kernels defined for mission '{mission_key}'. "
                f"Available: {', '.join(sorted(MISSION_KERNELS.keys()))}"
            )

        configured_files = sorted(kernels.keys())

        # Derive unique parent directory URLs
        parent_urls: dict[str, None] = {}  # ordered set
        for url in kernels.values():
            parent = url.rsplit("/", 1)[0] + "/"
            parent_urls[parent] = None

        import requests

        directories = []
        all_other: list[str] = []

        for dir_url in parent_urls:
            entry: dict = {"url": dir_url}
            try:
                resp = requests.get(dir_url, timeout=30)
                resp.raise_for_status()
                parser = _LinkExtractor()
                parser.feed(resp.text)
                bsp_files = sorted(
                    link for link in parser.links
                    if link.lower().endswith(".bsp")
                )
                entry["all_bsp_files"] = bsp_files
            except Exception as e:
                entry["all_bsp_files"] = []
                entry["error"] = str(e)
                bsp_files = []

            directories.append(entry)

            # Files in directory but not in configured set
            for f in bsp_files:
                if f not in configured_files:
                    all_other.append(f)

        return {
            "mission": mission_key,
            "configured_files": configured_files,
            "directories": directories,
            "other_files": sorted(set(all_other)),
        }

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    @staticmethod
    def _build_file_to_mission_map() -> dict[str, str]:
        """Build a mapping from kernel filename to mission key."""
        from .missions import GENERIC_KERNELS, SEGMENTED_MISSIONS
        file_map: dict[str, str] = {}
        for fname in GENERIC_KERNELS:
            file_map[fname] = "GENERIC"
        for mission_key, kernels in MISSION_KERNELS.items():
            for fname in kernels:
                file_map[fname] = mission_key
        for mission_key, manifest_file in SEGMENTED_MISSIONS.items():
            try:
                ref = importlib.resources.files("spedas_agent_kit.backends.spice.manifests").joinpath(manifest_file)
                manifest = json.loads(ref.read_text(encoding="utf-8"))
                for seg in manifest:
                    file_map[seg["file"]] = mission_key
            except Exception:
                pass
        return file_map

    def get_cache_size_bytes(self) -> int:
        """Return total size of cached kernel files in bytes."""
        total = 0
        if self._kernel_dir.exists():
            for f in self._kernel_dir.iterdir():
                if f.is_file() and not f.name.endswith(".tmp"):
                    total += f.stat().st_size
        return total

    def get_cache_info(self) -> dict:
        """Return cache summary grouped by mission.

        Returns:
            Dict with kernel_dir, total_size_mb, file_count,
            and missions dict mapping mission keys to their cached files.
        """
        files = []
        if self._kernel_dir.exists():
            files = [
                f for f in self._kernel_dir.iterdir()
                if f.is_file() and not f.name.endswith(".tmp")
            ]
        total = sum(f.stat().st_size for f in files)

        file_map = self._build_file_to_mission_map()
        missions: dict[str, dict] = {}
        for f in sorted(files):
            mission = file_map.get(f.name, "UNKNOWN")
            if mission not in missions:
                missions[mission] = {"size_mb": 0.0, "file_count": 0, "files": []}
            size_mb = round(f.stat().st_size / (1024 * 1024), 2)
            missions[mission]["size_mb"] = round(missions[mission]["size_mb"] + size_mb, 2)
            missions[mission]["file_count"] += 1
            missions[mission]["files"].append({"name": f.name, "size_mb": size_mb})

        return {
            "kernel_dir": str(self._kernel_dir),
            "total_size_mb": round(total / (1024 * 1024), 2),
            "file_count": len(files),
            "missions": missions,
        }

    def delete_cached_files(self, filenames: list[str]) -> dict:
        """Delete specific cached kernel files from disk.

        Also unloads them from the SPICE pool if loaded.

        Args:
            filenames: List of kernel filenames to delete.

        Returns:
            Dict with deleted files, freed_mb, and any errors.
        """
        deleted = []
        errors = []
        freed = 0

        with self._lock:
            for fname in filenames:
                path = self._kernel_dir / fname
                if not path.exists():
                    errors.append(f"{fname}: not found in cache")
                    continue
                size = path.stat().st_size
                # Unload from SPICE if loaded
                key = str(path.resolve())
                if key in self._loaded_kernels:
                    try:
                        spice.unload(key)
                    except Exception:
                        pass
                    self._loaded_kernels.discard(key)
                self._segmented_files_loaded.discard(fname)
                try:
                    path.unlink()
                    deleted.append(fname)
                    freed += size
                except Exception as e:
                    errors.append(f"{fname}: {e}")

            # Invalidate mission-level caches if any of their files were deleted
            file_map = self._build_file_to_mission_map()
            invalidated_missions = {file_map.get(f) for f in deleted} - {None}
            self._mission_kernels_loaded -= invalidated_missions
            if "GENERIC" in invalidated_missions:
                self._generic_loaded = False

        result: dict = {
            "deleted": deleted,
            "freed_mb": round(freed / (1024 * 1024), 2),
        }
        if errors:
            result["errors"] = errors
        logger.info("Deleted %d cached files (%.1f MB freed)", len(deleted), freed / (1024 * 1024))
        return result

    def delete_mission_cache(self, mission_key: str) -> dict:
        """Delete all cached kernel files for a specific mission.

        Args:
            mission_key: Canonical mission key (e.g., "PSP", "CASSINI", "GENERIC").

        Returns:
            Dict with deleted files and freed_mb.
        """
        file_map = self._build_file_to_mission_map()
        # Find cached files belonging to this mission
        to_delete = []
        if self._kernel_dir.exists():
            for f in self._kernel_dir.iterdir():
                if f.is_file() and not f.name.endswith(".tmp"):
                    if file_map.get(f.name) == mission_key:
                        to_delete.append(f.name)
        if not to_delete:
            return {"deleted": [], "freed_mb": 0.0, "message": f"No cached files for {mission_key}"}
        return self.delete_cached_files(to_delete)

    def purge_cache(self) -> dict:
        """Delete ALL cached kernel files and unload everything.

        Returns:
            Dict with deleted count and freed_mb.
        """
        self.unload_all()
        files = []
        if self._kernel_dir.exists():
            files = [
                f for f in self._kernel_dir.iterdir()
                if f.is_file() and not f.name.endswith(".tmp")
            ]
        freed = 0
        deleted = 0
        errors = []
        for f in files:
            try:
                freed += f.stat().st_size
                f.unlink()
                deleted += 1
            except Exception as e:
                errors.append(f"{f.name}: {e}")

        result: dict = {
            "deleted_count": deleted,
            "freed_mb": round(freed / (1024 * 1024), 2),
        }
        if errors:
            result["errors"] = errors
        logger.info("Purged cache: %d files, %.1f MB freed", deleted, freed / (1024 * 1024))
        return result


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

def check_remote_kernels(mission: str) -> dict:
    """Check for new kernel files in the remote directory for a mission.

    Resolves the mission name, then checks the remote NAIF directory
    for .bsp files not in the currently configured set.

    Args:
        mission: Mission name (e.g., "Juno", "PSP", "Parker Solar Probe").

    Returns:
        Dict with mission, configured_files, directories, and other_files.
    """
    from .missions import resolve_mission
    _, mission_key = resolve_mission(mission)
    return get_kernel_manager().check_remote_kernels(mission_key)
