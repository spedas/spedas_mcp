"""
Coordinate frame transforms via SPICE.

Provides frame alias mapping and vector transform functions.
Uses spice.pxform() for standard NAIF frames.
RTN (Radial-Tangential-Normal) is computed manually from the
spacecraft position vector relative to the Sun.
"""

import logging

import numpy as np
import spiceypy as spice

from .kernel_manager import get_kernel_manager
from .missions import resolve_mission, get_spice_body_id, MISSION_KERNELS, SEGMENTED_MISSIONS

logger = logging.getLogger("spedas_agent_kit.backends.spice")


# ---------------------------------------------------------------------------
# Frame aliases — map common heliophysics names to SPICE frame strings
# ---------------------------------------------------------------------------

FRAME_ALIASES: dict[str, str] = {
    # Inertial frames
    "J2000": "J2000",
    "ECLIPJ2000": "ECLIPJ2000",
    "ECLIPB1950": "ECLIPB1950",
    # Heliospheric frames (require heliospheric FK loaded)
    "HCI": "HCI",             # Heliocentric Inertial
    "HEE": "HEE",             # Heliocentric Earth Ecliptic
    "HAE": "HAE",             # Heliocentric Aries Ecliptic
    "HEEQ": "HEEQ",           # Heliocentric Earth Equatorial
    # Earth-centered frames
    "GSE": "GSE",              # Geocentric Solar Ecliptic
    "GEI": "GEI",              # Geocentric Equatorial Inertial
    # Spacecraft-dependent
    "RTN": "RTN",              # Radial-Tangential-Normal (computed manually)
    # Convenience aliases
    "ECLIPTIC": "ECLIPJ2000",
    "EQUATORIAL": "J2000",
    "INERTIAL": "J2000",
}

# Descriptions for each canonical frame (used by list_coordinate_frames tool)
FRAME_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "J2000": {
        "full_name": "Earth Mean Equator and Equinox of J2000",
        "description": "Inertial frame with XY plane on Earth's equator at epoch J2000.0. "
                       "Standard SPICE reference frame.",
        "use_when": "General-purpose inertial reference. Planetary orbits appear tilted ~23.4 deg "
                    "due to Earth's axial tilt.",
    },
    "ECLIPJ2000": {
        "full_name": "Ecliptic plane at J2000 epoch",
        "description": "Inertial frame with XY plane on the ecliptic (the plane the planets "
                       "orbit in) at epoch J2000.0. X-axis toward vernal equinox.",
        "use_when": "Orbit plots and trajectory visualization. Planetary and spacecraft orbits "
                    "lie roughly in the XY plane. Good default for heliocentric positions.",
    },
    "ECLIPB1950": {
        "full_name": "Ecliptic plane at B1950 epoch",
        "description": "Ecliptic inertial frame at the older B1950 epoch.",
        "use_when": "Legacy data or catalogs that use B1950 coordinates.",
    },
    "HCI": {
        "full_name": "Heliocentric Inertial",
        "description": "Sun-centered inertial frame. Z-axis along solar rotation axis, "
                       "X-axis toward ascending node of solar equator on ecliptic.",
        "use_when": "Heliospheric structure analysis. Solar wind studies where solar rotation "
                    "axis matters.",
    },
    "HEE": {
        "full_name": "Heliocentric Earth Ecliptic",
        "description": "Sun-centered frame. X-axis toward Earth, Z-axis toward ecliptic north. "
                       "Rotates with the Sun-Earth line.",
        "use_when": "Sun-Earth geometry. CME propagation studies, solar wind arrival at Earth.",
    },
    "HAE": {
        "full_name": "Heliocentric Aries Ecliptic",
        "description": "Sun-centered ecliptic frame. Nearly identical to ECLIPJ2000.",
        "use_when": "Similar to ECLIPJ2000 but centered on the Sun.",
    },
    "HEEQ": {
        "full_name": "Heliocentric Earth Equatorial (Stonyhurst)",
        "description": "Sun-centered frame. Z-axis along solar rotation axis, X-axis in plane "
                       "containing Sun-Earth line. Also known as Stonyhurst coordinates.",
        "use_when": "Mapping features to solar surface (active regions, coronal holes). "
                    "Comparing spacecraft positions relative to solar longitude.",
    },
    "GSE": {
        "full_name": "Geocentric Solar Ecliptic",
        "description": "Earth-centered frame. X-axis toward Sun, Z-axis toward ecliptic north. "
                       "Rotates with the Sun-Earth line.",
        "use_when": "Near-Earth spacecraft (THEMIS, Van Allen Probes). Magnetospheric physics, "
                    "bow shock and magnetopause studies.",
    },
    "GEI": {
        "full_name": "Geocentric Equatorial Inertial",
        "description": "Earth-centered inertial frame. Equivalent to J2000 but Earth-centered.",
        "use_when": "Earth-orbiting satellites. Similar to J2000 for near-Earth work.",
    },
    "RTN": {
        "full_name": "Radial-Tangential-Normal",
        "description": "Spacecraft-dependent frame. R points from Sun to spacecraft, T is in "
                       "the direction of orbital motion (perpendicular to R in orbital plane), "
                       "N completes the right-handed system.",
        "use_when": "Solar wind analysis at a spacecraft. Magnetic field and plasma velocity "
                    "decomposition (e.g., PSP, Solar Orbiter). Requires spacecraft parameter.",
    },
}

# Frames that require manual computation (not standard SPICE pxform)
_MANUAL_FRAMES = {"RTN"}

# Frames that are standard SPICE and can use pxform directly



def _resolve_frame(name: str) -> str:
    """Resolve a frame name through aliases.

    Args:
        name: Frame name (case-insensitive).

    Returns:
        Canonical SPICE frame string.

    Raises:
        KeyError: If the frame name is not recognized.
    """
    key = name.strip().upper()
    if key in FRAME_ALIASES:
        return FRAME_ALIASES[key]
    # Try as-is (SPICE might know it)
    return key


def _compute_rtn_matrix(spacecraft: str, time_et: float) -> np.ndarray:
    """Compute the RTN rotation matrix for a spacecraft at a given time.

    Uses the shared rtn_matrix_from_position() from ephemeris module
    after resolving the spacecraft position from Sun in J2000.

    Args:
        spacecraft: Spacecraft name or NAIF ID string.
        time_et: SPICE ephemeris time.

    Returns:
        3x3 rotation matrix (J2000 -> RTN).
    """
    from .ephemeris import rtn_matrix_from_position

    try:
        _, sc_key = resolve_mission(spacecraft)
        sc_id = get_spice_body_id(sc_key)
    except KeyError:
        sc_id = int(spacecraft)
        sc_key = spacecraft

    km = get_kernel_manager()
    km.ensure_generic_kernels()
    if sc_key in MISSION_KERNELS:
        km.ensure_mission_kernels(sc_key)
    elif sc_key in SEGMENTED_MISSIONS:
        from datetime import date
        with km.lock:
            utc_str = spice.et2utc(time_et, "ISOC", 0)
        t_date = date.fromisoformat(utc_str[:10])
        km.ensure_segmented_kernels(sc_key, t_date, t_date)

    with km.lock:
        pos_j2000, _ = spice.spkpos(str(sc_id), time_et, "J2000", "NONE", "10")

    return rtn_matrix_from_position(np.asarray(pos_j2000, dtype=float))


def transform_vector(
    vector: list | np.ndarray,
    time: str,
    from_frame: str,
    to_frame: str,
    spacecraft: str = "",
) -> np.ndarray:
    """Transform a 3-vector between coordinate frames.

    Args:
        vector: 3-element vector [x, y, z].
        time: UTC time string (ISO 8601).
        from_frame: Source frame name.
        to_frame: Target frame name.
        spacecraft: Spacecraft name (required for RTN transforms).

    Returns:
        Transformed 3-vector as numpy array.

    Raises:
        ValueError: If RTN is used without specifying a spacecraft.
        KeyError: If a frame cannot be resolved.
    """
    v = np.asarray(vector, dtype=float)
    if v.shape != (3,):
        raise ValueError(f"Expected 3-element vector, got shape {v.shape}")

    src = _resolve_frame(from_frame)
    dst = _resolve_frame(to_frame)

    if src == dst:
        return v

    km = get_kernel_manager()
    km.ensure_generic_kernels()

    with km.lock:
        et = spice.utc2et(time)

    # Handle RTN cases
    if src == "RTN" or dst == "RTN":
        if not spacecraft:
            raise ValueError("spacecraft parameter is required for RTN transforms")

        rtn_mat = _compute_rtn_matrix(spacecraft, et)  # J2000 -> RTN

        if src == "RTN" and dst == "RTN":
            return v

        if src == "RTN":
            # RTN -> J2000 -> dst
            v_j2000 = rtn_mat.T @ v  # RTN -> J2000 (inverse = transpose)
            if dst == "J2000":
                return v_j2000
            with km.lock:
                mat = spice.pxform("J2000", dst, et)
            return np.array(mat) @ v_j2000

        if dst == "RTN":
            # src -> J2000 -> RTN
            if src == "J2000":
                v_j2000 = v
            else:
                with km.lock:
                    mat = spice.pxform(src, "J2000", et)
                v_j2000 = np.array(mat) @ v
            return rtn_mat @ v_j2000

    # Standard SPICE frame-to-frame
    with km.lock:
        try:
            mat = spice.pxform(src, dst, et)
        except Exception as e:
            raise KeyError(
                f"Cannot transform from '{src}' to '{dst}' via SPICE: {e}. "
                f"Available frames: {', '.join(sorted(FRAME_ALIASES.keys()))}"
            ) from e

    return np.array(mat) @ v


def list_available_frames() -> list[str]:
    """Return list of supported coordinate frame names."""
    return sorted(FRAME_ALIASES.keys())


def list_frames_with_descriptions() -> list[dict[str, str]]:
    """Return available coordinate frames with descriptions and usage guidance.

    Only returns canonical frames (not convenience aliases like ECLIPTIC).
    """
    frames = []
    for name, info in FRAME_DESCRIPTIONS.items():
        frames.append({
            "frame": name,
            "full_name": info["full_name"],
            "description": info["description"],
            "use_when": info["use_when"],
        })
    return frames
