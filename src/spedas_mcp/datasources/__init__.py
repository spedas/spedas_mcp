"""Optional external data-source adapters for SPEDAS MCP (issues #21, #22).

This package hosts data-source adapters that reach archives outside the three
bundled SPEDAS backend families (CDAWeb / PDS / SPICE):

- :mod:`spedas_mcp.datasources.hapi` — generic HAPI servers (CDAWeb, PDS-PPI,
  ISWA, LISIRD, university networks) via ``hapiclient`` (issue #21).
- :mod:`spedas_mcp.datasources.fdsn` — FDSN/MTH5 magnetotelluric magnetic-field
  stations from EarthScope via ``pyspedas.mth5`` (``mth5`` + ``obspy``)
  (issue #22).

Design contract (mirrors the optional :mod:`spedas_mcp.analysis` layer):

- **Optional, lazily imported.** Importing this package never imports
  ``hapiclient``/``mth5``/``obspy``/``pyspedas``. Each adapter imports its
  backend lazily and returns a clear, structured ``status="error"`` payload
  (``code="missing_dependency"``) telling the caller which extra to install when
  the backend is absent. Base install and MCP ``list_tools`` work without any of
  these extras.
- **Artifact-first.** Bulk time-series are written to ``output_dir`` as CSV/JSON
  files; tools return only the file path plus compact metadata (rows, parameter/
  channel summaries). Raw arrays are never returned inline.
- **Structured errors.** Error payloads share the ``{status, code, message,
  hint, ...}`` envelope used across the server so agents branch on
  ``status``/``code`` rather than parsing free text.
"""

from __future__ import annotations

from typing import Any
import importlib.util


class DataSourceDependencyError(RuntimeError):
    """Raised when an optional data-source backend is unavailable.

    Carries the name of the extra to install so callers can build an actionable
    ``missing_dependency`` error envelope.
    """

    def __init__(self, message: str, *, extra: str) -> None:
        super().__init__(message)
        self.extra = extra


def _error(
    message: str,
    *,
    code: str = "invalid_argument",
    hint: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build the uniform structured error payload for data-source tools.

    Mirrors the server's ``_error_response`` envelope so these errors share the
    same ``{status: "error", code, message, ...}`` contract as every other
    user-facing tool error. The server wraps these dicts with ``_json`` and the
    ``_safe_tool`` size guard; truly-unexpected exceptions raised by a backend
    are converted to the same envelope by ``_safe_tool``'s exception handler.
    """
    payload: dict[str, Any] = {"status": "error", "code": code, "message": message}
    if hint is not None:
        payload["hint"] = hint
    payload.update(extra)
    return payload


def _missing_dependency_error(exc: DataSourceDependencyError) -> dict[str, Any]:
    """Structured ``missing_dependency`` payload for an absent optional backend."""
    return _error(
        str(exc),
        code="missing_dependency",
        hint=f"Install the optional backend with: pip install 'spedas-mcp[{exc.extra}]'.",
        extra=exc.extra,
    )


def require_hapiclient():
    """Lazily import and return the ``hapiclient.hapi`` callable.

    Returns
    -------
    callable
        The ``hapiclient.hapi`` function.

    Raises
    ------
    DataSourceDependencyError
        If ``hapiclient`` cannot be imported, with ``extra="hapi"``.
    """
    try:
        from hapiclient import hapi as hapi_fn
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch in tests
        raise DataSourceDependencyError(
            "This tool requires the optional HAPI backend (hapiclient). "
            "hapiclient is intentionally not part of the base install. "
            f"(import error: {exc})",
            extra="hapi",
        ) from exc
    return hapi_fn


def _optional_module_state(name: str) -> str:
    """Return a compact diagnostic for an optional dependency without importing it."""
    try:
        spec = importlib.util.find_spec(name)
    except Exception as exc:  # pragma: no cover - import machinery edge case
        return f"unavailable ({type(exc).__name__}: {exc})"
    if spec is None:
        return "not installed"
    if spec.origin is None:
        return "namespace package only (no importable module file)"
    return "installed"


def require_mth5():
    """Lazily import and return the ``pyspedas.mth5`` module.

    Importing ``pyspedas.mth5`` triggers the package's own ``mth5``/``obspy``
    import guards, so a missing ``mth5``/``obspy`` surfaces here as a
    :class:`DataSourceDependencyError` with ``extra="fdsn"`` rather than an
    opaque traceback.

    Returns
    -------
    module
        The imported ``pyspedas.mth5`` module.

    Raises
    ------
    DataSourceDependencyError
        If ``pyspedas.mth5`` (or its ``mth5``/``obspy`` backends) cannot be
        imported, with ``extra="fdsn"``.
    """
    try:
        import pyspedas.mth5 as mth5_module  # noqa: F401
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch in tests
        component_state = {
            "pyspedas.mth5": _optional_module_state("pyspedas.mth5"),
            "mth5": _optional_module_state("mth5"),
            "obspy": _optional_module_state("obspy"),
        }
        raise DataSourceDependencyError(
            "This tool requires the optional FDSN/MTH5 backend "
            "(pyspedas with mth5 + obspy), which is not fully importable in "
            "this environment. These packages are intentionally not part of "
            "the base install. "
            f"Dependency check: {component_state}. "
            f"Original import failed with {type(exc).__name__}.",
            extra="fdsn",
        ) from exc
    return mth5_module


__all__ = [
    "DataSourceDependencyError",
    "require_hapiclient",
    "require_mth5",
]
