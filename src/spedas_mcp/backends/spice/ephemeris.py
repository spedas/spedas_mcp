"""
Spacecraft position and trajectory computation via SPICE.

All functions resolve mission names, ensure kernels are loaded,
and call SpiceyPy under the KernelManager lock for thread safety.
"""

import logging
from datetime import date, datetime

import numpy as np
import pandas as pd
import spiceypy as spice

from .missions import resolve_mission, get_spice_body_id
from .kernel_manager import get_kernel_manager

logger = logging.getLogger("spedas_mcp.backends.spice")

# Astronomical unit in km (IAU 2012)
AU_KM = 149597870.7

# Whether a frame requires manual rotation instead of passing to SPICE
_RTN_FRAME = "RTN"

# Sun's north pole in J2000 (IAU_SUN: RA=286.13°, Dec=63.87°)
_SUN_NORTH_J2000 = np.array([
    np.cos(np.radians(63.87)) * np.cos(np.radians(286.13)),
    np.cos(np.radians(63.87)) * np.sin(np.radians(286.13)),
    np.sin(np.radians(63.87)),
])


def rtn_matrix_from_position(pos_j2000: np.ndarray) -> np.ndarray:
    """Build the J2000→RTN rotation matrix from a Sun-centered position.

    Args:
        pos_j2000: 3-element position vector from Sun in J2000 (km).

    Returns:
        3x3 rotation matrix whose rows are R, T, N unit vectors in J2000.
    """
    r_hat = pos_j2000 / np.linalg.norm(pos_j2000)

    t_hat = np.cross(_SUN_NORTH_J2000, r_hat)
    t_norm = np.linalg.norm(t_hat)
    if t_norm < 1e-10:
        t_hat = np.array([0.0, 1.0, 0.0])
    else:
        t_hat = t_hat / t_norm

    n_hat = np.cross(r_hat, t_hat)
    n_hat = n_hat / np.linalg.norm(n_hat)

    return np.array([r_hat, t_hat, n_hat])


def _resolve_body(name: str) -> tuple[int, str]:
    """Resolve a body name to (SPICE body ID, canonical key).

    Tries mission registry first, then falls back to SPICE bodn2c.
    Returns the body ID that the SPK kernel actually uses (which may
    differ from the 'official' NAIF assignment for some missions).
    """
    try:
        _, key = resolve_mission(name)
        return get_spice_body_id(key), key
    except KeyError:
        pass

    # Let SPICE try
    km = get_kernel_manager()
    km.ensure_generic_kernels()
    with km.lock:
        try:
            naif_id = spice.bodn2c(name.strip())
            return naif_id, name.strip().upper()
        except Exception:
            raise KeyError(f"Cannot resolve body name '{name}'")


def _to_date(time_input) -> date:
    """Extract a date from a string, datetime, or date object."""
    if isinstance(time_input, datetime):
        return time_input.date()
    if isinstance(time_input, date):
        return time_input
    # Parse first 10 chars as ISO date (YYYY-MM-DD)
    return date.fromisoformat(str(time_input).strip()[:10])


def _ensure_kernels(
    target_key: str,
    observer_key: str,
    time_start: date | None = None,
    time_end: date | None = None,
) -> None:
    """Ensure relevant kernels are loaded for both target and observer."""
    km = get_kernel_manager()
    km.ensure_generic_kernels()

    from .missions import MISSION_KERNELS, SEGMENTED_MISSIONS
    for key in (target_key, observer_key):
        if key in MISSION_KERNELS:
            km.ensure_mission_kernels(key)
        elif key in SEGMENTED_MISSIONS:
            if time_start is None or time_end is None:
                raise ValueError(
                    f"Mission '{key}' uses segmented kernels and requires "
                    f"a time range. Provide time_start and time_end."
                )
            km.ensure_segmented_kernels(key, time_start, time_end)


def _to_et(time_input) -> float:
    """Convert a datetime or ISO string to SPICE ephemeris time (ET).

    Args:
        time_input: datetime object, ISO 8601 string, or "YYYY-MM-DDTHH:MM:SS".

    Returns:
        SPICE ephemeris time (seconds past J2000).
    """
    if isinstance(time_input, datetime):
        time_str = time_input.strftime("%Y-%m-%dT%H:%M:%S")
    elif isinstance(time_input, str):
        time_str = time_input.strip()
    else:
        time_str = str(time_input)

    return spice.utc2et(time_str)


def _parse_step(step: str) -> float:
    """Parse a step string like '1h', '30m', '1d' into seconds."""
    step = step.strip().lower()
    if step.endswith("d"):
        result = float(step[:-1]) * 86400
    elif step.endswith("h"):
        result = float(step[:-1]) * 3600
    elif step.endswith("m"):
        result = float(step[:-1]) * 60
    elif step.endswith("s"):
        result = float(step[:-1])
    else:
        result = float(step)  # assume seconds
    if result <= 0:
        raise ValueError(f"Time step must be positive, got '{step}' ({result}s)")
    return result


def get_position(
    target: str,
    observer: str = "SUN",
    time: str | datetime = "2024-01-01T00:00:00",
    frame: str = "ECLIPJ2000",
) -> dict:
    """Get the position of a target relative to an observer at a single time.

    Args:
        target: Target body name (e.g., "PSP", "Earth", "Cassini").
        observer: Observer body name (default: "SUN").
        time: UTC time as ISO string or datetime.
        frame: Reference frame (default: "ECLIPJ2000").

    Returns:
        Dict with keys: x_km, y_km, z_km (position in km),
        r_km (distance in km), r_au (distance in AU),
        light_time_s, target, observer, frame, time.
    """
    target_id, target_key = _resolve_body(target)
    observer_id, observer_key = _resolve_body(observer)
    t_date = _to_date(time)
    _ensure_kernels(target_key, observer_key, time_start=t_date, time_end=t_date)

    is_rtn = frame.strip().upper() == _RTN_FRAME
    spice_frame = "J2000" if is_rtn else frame

    km = get_kernel_manager()
    with km.lock:
        et = _to_et(time)
        pos, lt = spice.spkpos(str(target_id), et, spice_frame, "NONE", str(observer_id))

    pos = np.asarray(pos, dtype=float)
    if is_rtn:
        # Get target position from Sun for RTN matrix
        with km.lock:
            sun_pos, _ = spice.spkpos(str(target_id), et, "J2000", "NONE", "10")
        rtn_mat = rtn_matrix_from_position(np.asarray(sun_pos, dtype=float))
        pos = rtn_mat @ pos

    x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
    r_km = float(np.sqrt(x**2 + y**2 + z**2))

    return {
        "x_km": x,
        "y_km": y,
        "z_km": z,
        "r_km": r_km,
        "r_au": r_km / AU_KM,
        "light_time_s": float(lt),
        "target": target_key,
        "observer": observer_key,
        "frame": frame,
        "time": str(time),
    }


def get_state(
    target: str,
    observer: str = "SUN",
    time: str | datetime = "2024-01-01T00:00:00",
    frame: str = "ECLIPJ2000",
) -> dict:
    """Get position and velocity of a target at a single time.

    Args:
        target: Target body name.
        observer: Observer body name.
        time: UTC time as ISO string or datetime.
        frame: Reference frame.

    Returns:
        Dict with keys: x_km, y_km, z_km (position in km),
        vx_km_s, vy_km_s, vz_km_s (velocity in km/s),
        r_km (distance in km), r_au (distance in AU),
        speed_km_s, light_time_s, target, observer, frame, time.
    """
    target_id, target_key = _resolve_body(target)
    observer_id, observer_key = _resolve_body(observer)
    t_date = _to_date(time)
    _ensure_kernels(target_key, observer_key, time_start=t_date, time_end=t_date)

    is_rtn = frame.strip().upper() == _RTN_FRAME
    spice_frame = "J2000" if is_rtn else frame

    km = get_kernel_manager()
    with km.lock:
        et = _to_et(time)
        state, lt = spice.spkezr(str(target_id), et, spice_frame, "NONE", str(observer_id))

    pos = np.asarray(state[:3], dtype=float)
    vel = np.asarray(state[3:], dtype=float)

    if is_rtn:
        with km.lock:
            sun_pos, _ = spice.spkpos(str(target_id), et, "J2000", "NONE", "10")
        rtn_mat = rtn_matrix_from_position(np.asarray(sun_pos, dtype=float))
        pos = rtn_mat @ pos
        vel = rtn_mat @ vel

    x, y, z = float(pos[0]), float(pos[1]), float(pos[2])
    vx, vy, vz = float(vel[0]), float(vel[1]), float(vel[2])
    r_km = float(np.sqrt(x**2 + y**2 + z**2))
    speed = float(np.sqrt(vx**2 + vy**2 + vz**2))

    return {
        "x_km": x,
        "y_km": y,
        "z_km": z,
        "vx_km_s": vx,
        "vy_km_s": vy,
        "vz_km_s": vz,
        "r_km": r_km,
        "r_au": r_km / AU_KM,
        "speed_km_s": speed,
        "light_time_s": float(lt),
        "target": target_key,
        "observer": observer_key,
        "frame": frame,
        "time": str(time),
    }


def get_trajectory(
    target: str,
    observer: str = "SUN",
    time_start: str | datetime = "2024-01-01",
    time_end: str | datetime = "2024-01-31",
    step: str = "1h",
    frame: str = "ECLIPJ2000",
    include_velocity: bool = False,
) -> pd.DataFrame:
    """Compute a trajectory (position timeseries) over a time range.

    Args:
        target: Target body name (e.g., "PSP", "Earth").
        observer: Observer body name (default: "SUN").
        time_start: Start time (ISO string or datetime).
        time_end: End time (ISO string or datetime).
        step: Time step (e.g., "1h", "30m", "1d"). Default: "1h".
        frame: Reference frame (default: "ECLIPJ2000").
        include_velocity: If True, include vx, vy, vz columns.

    Returns:
        DataFrame with DatetimeIndex and columns:
        x_km, y_km, z_km, r_km, r_au (+ vx_km_s, vy_km_s, vz_km_s if requested).
    """
    target_id, target_key = _resolve_body(target)
    observer_id, observer_key = _resolve_body(observer)
    _ensure_kernels(
        target_key, observer_key,
        time_start=_to_date(time_start),
        time_end=_to_date(time_end),
    )

    is_rtn = frame.strip().upper() == _RTN_FRAME
    spice_frame = "J2000" if is_rtn else frame

    km = get_kernel_manager()
    step_s = _parse_step(step)

    with km.lock:
        et_start = _to_et(time_start)
        et_end = _to_et(time_end)

    n_steps = max(1, int((et_end - et_start) / step_s) + 1)
    if n_steps > 1_000_000:
        logger.warning(
            "Trajectory request has %s points — this may use significant memory "
            "(~%.0f MB). Consider a larger step size.",
            f"{n_steps:,}",
            n_steps * 24 / 1e6 * 8,  # 3 pos floats × 8 bytes, rough estimate
        )

    et_times = np.linspace(et_start, et_end, n_steps)

    # Compute positions (and optionally velocities) under lock
    positions = np.empty((n_steps, 3))
    velocities = np.empty((n_steps, 3)) if include_velocity else None
    utc_times = []

    with km.lock:
        for i, et in enumerate(et_times):
            if include_velocity:
                state, _ = spice.spkezr(str(target_id), et, spice_frame, "NONE", str(observer_id))
                positions[i] = state[:3]
                velocities[i] = state[3:]
            else:
                pos, _ = spice.spkpos(str(target_id), et, spice_frame, "NONE", str(observer_id))
                positions[i] = pos

            if is_rtn:
                sun_pos, _ = spice.spkpos(str(target_id), et, "J2000", "NONE", "10")
                rtn_mat = rtn_matrix_from_position(np.asarray(sun_pos, dtype=float))
                positions[i] = rtn_mat @ positions[i]
                if include_velocity:
                    velocities[i] = rtn_mat @ velocities[i]

            utc_times.append(spice.et2utc(et, "ISOC", 3))

    # Build DataFrame
    index = pd.to_datetime(utc_times)
    r_km = np.sqrt(np.sum(positions**2, axis=1))

    data = {
        "x_km": positions[:, 0],
        "y_km": positions[:, 1],
        "z_km": positions[:, 2],
        "r_km": r_km,
        "r_au": r_km / AU_KM,
    }

    if include_velocity:
        data["vx_km_s"] = velocities[:, 0]
        data["vy_km_s"] = velocities[:, 1]
        data["vz_km_s"] = velocities[:, 2]

    df = pd.DataFrame(data, index=index)
    df.index.name = "time"

    logger.info(
        "Computed trajectory: %s rel. %s, %d points, %s to %s",
        target_key, observer_key, n_steps,
        utc_times[0] if utc_times else "?",
        utc_times[-1] if utc_times else "?",
    )

    return df
