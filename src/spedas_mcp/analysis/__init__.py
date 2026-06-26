"""Optional pyspedas-backed analysis layer for SPEDAS MCP.

This package hosts downstream analysis tools that operate on artifact files
produced by the data layer (CSV/JSON time-series). Unlike the data/geometry
tools, these depend on `pyspedas`, which is an **optional** dependency installed
via the ``spedas-mcp[analysis]`` extra. Importing this package never imports
pyspedas; each tool imports it lazily and returns a clear, actionable error when
the extra is missing (mirroring the ``[mcp]`` guard in ``server.py``).
"""

from __future__ import annotations


class AnalysisDependencyError(RuntimeError):
    """Raised when an optional analysis backend (pyspedas) is unavailable."""


_INSTALL_HINT = (
    "This tool requires the optional analysis backend. Install it with: "
    "pip install 'spedas-mcp[analysis]' (provides pyspedas). "
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


__all__ = ["AnalysisDependencyError", "require_pyspedas"]
