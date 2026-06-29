"""Shared optional-backend probes for SPEDAS Agent Kit."""

from __future__ import annotations

import importlib
import importlib.util

ANALYSIS_TOOL_NAMES = (
    "transform_timeseries_coordinates",
    "generate_fac_matrix",
    "tvector_rotate",
    "analyze_minvar_coordinates",
    "dynamic_power_spectrum",
    "wavelet_transform",
    "evaluate_magnetic_field",
    "calculate_lshell",
    "build_particle_distribution_artifact",
    "load_particle_distribution_artifact",
    "compute_particle_moments",
    "compute_particle_spectra",
    "render_tplot",
)

# Modules/attributes exercised by the optional analysis tools. This is more
# precise than checking only ``import pyspedas``: several pyspedas builds expose
# mission loaders but not the legacy tplot/cotrans/wavelet/particle helpers that
# these tools call. If any required backend is missing, the server omits the
# whole analysis registration group from MCP ``list_tools`` and the planner must
# not claim those tools are available.
ANALYSIS_REQUIRED_IMPORTS = (
    ("pyspedas", None),
    ("matplotlib", None),
    ("pywt", None),
    ("pyspedas.cotrans_tools.cotrans", "cotrans"),
    ("pyspedas.cotrans_tools.fac_matrix_make", "fac_matrix_make"),
    ("pyspedas.cotrans_tools.minvar", "minvar"),
    ("pyspedas.cotrans_tools.minvar_matrix_make", "minvar_matrix_make"),
    ("pyspedas.tplot_tools", "store_data"),
    ("pyspedas.tplot_tools.tplot_math.dpwrspc", "dpwrspc"),
    ("pyspedas.analysis.wavelet", "idl_wavelet_scales"),
    ("pyspedas.analysis.wave_signif", "wave_signif"),
    ("pyspedas.geopack", None),
    ("pyspedas.particles.moments", "moments_3d"),
    # These spd_pgs_* helpers live in per-function SUBMODULES of
    # spd_part_products (e.g. ...spd_part_products.spd_pgs_make_e_spec), not as
    # attributes of the package itself, and are imported lazily — so probing the
    # package with hasattr() returns False until the submodule is imported,
    # which gated off ALL analysis tools even with [analysis] installed. Probe
    # the submodule path directly, matching how analysis/particles.py imports
    # them and how the other entries above target function-bearing modules.
    ("pyspedas.particles.spd_part_products.spd_pgs_make_e_spec", "spd_pgs_make_e_spec"),
    ("pyspedas.particles.spd_part_products.spd_pgs_make_phi_spec", "spd_pgs_make_phi_spec"),
    ("pyspedas.particles.spd_part_products.spd_pgs_make_theta_spec", "spd_pgs_make_theta_spec"),
    ("pyspedas.particles.spd_part_products.spd_pgs_do_fac", "spd_pgs_do_fac"),
)


def required_imports_available(required_imports=ANALYSIS_REQUIRED_IMPORTS) -> bool:
    """Return whether all optional backend modules/attributes are importable."""
    for module_name, attr_name in required_imports:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            return False
        if attr_name is not None and not hasattr(module, attr_name):
            return False
    return True


def analysis_dependencies_available() -> bool:
    """Return whether the optional ``spedas-agent-kit[analysis]`` stack is usable."""
    return required_imports_available(ANALYSIS_REQUIRED_IMPORTS)


def module_available(module_name: str) -> bool:
    """Return whether a module appears importable without importing it fully."""
    try:
        return importlib.util.find_spec(module_name) is not None
    except Exception:
        return False
