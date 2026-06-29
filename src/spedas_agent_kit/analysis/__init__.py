"""Optional pyspedas-backed analysis layer for SPEDAS Agent Kit.

This package hosts downstream analysis tools that operate on artifact files
produced by the data layer (CSV/JSON time-series). Unlike the data/geometry
tools, these depend on `pyspedas`, which is an **optional** dependency installed
via the ``spedas-agent-kit[analysis]`` extra. Importing this package never imports
pyspedas; each tool imports it lazily and returns a clear, actionable error when
the extra is missing (mirroring the ``[mcp]`` guard in ``server.py``).
"""

from __future__ import annotations


class AnalysisDependencyError(RuntimeError):
    """Raised when an optional analysis backend (pyspedas) is unavailable."""


_INSTALL_HINT = (
    "This tool requires the optional analysis backend. Install it with: "
    "pip install 'spedas-agent-kit[analysis]' (provides pyspedas). "
    "pyspedas is intentionally not part of the base install."
)


def require_pyspedas():
    """Lazily import and return the ``pyspedas`` module.

    Returns
    -------
    module
        The imported ``pyspedas`` module.

    Raises
    ------
    AnalysisDependencyError
        If ``pyspedas`` cannot be imported. The message tells the caller how to
        install the optional ``[analysis]`` extra.
    """
    try:
        import pyspedas  # noqa: F401  (imported for side effect + return)
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise AnalysisDependencyError(f"{_INSTALL_HINT} (import error: {exc})") from exc
    return pyspedas


_MATPLOTLIB_HINT = (
    "This tool requires the optional analysis backend. Install it with: "
    "pip install 'spedas-agent-kit[analysis]' (provides matplotlib via pyspedas). "
    "matplotlib is intentionally not part of the base install."
)


def require_matplotlib():
    """Lazily import and return the ``matplotlib`` module on the Agg backend.

    The plotting tool (:func:`spedas_agent_kit.analysis.plotting.render_tplot`, issue
    #20) renders headlessly, so this forces the non-interactive ``Agg`` backend
    before pyplot is imported and never opens a display.

    Returns
    -------
    module
        The imported ``matplotlib`` module.

    Raises
    ------
    AnalysisDependencyError
        If ``matplotlib`` cannot be imported. The message tells the caller how to
        install the optional ``[analysis]`` extra.
    """
    try:
        import matplotlib  # noqa: F401  (imported for side effect + return)

        matplotlib.use("Agg", force=True)
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise AnalysisDependencyError(
            f"{_MATPLOTLIB_HINT} (import error: {exc})"
        ) from exc
    return matplotlib


__all__ = ["AnalysisDependencyError", "require_pyspedas", "require_matplotlib"]
