"""Vendored CDAWeb backend (formerly the ``xhelio-cdaweb`` / ``cdawebmcp`` package).

Absorbed into spedas_agent_kit (issue #107) so the repo is self-contained. Exposes the
CDAWeb library surface (catalog / metadata / fetch / cache / config) that the
spedas_agent_kit facade dispatches to for ``source_type="cdaweb"``. The package's former
standalone MCP server/CLI is intentionally dropped — the spedas_agent_kit facade replaces it.
"""

__version__ = "0.3.0"

from spedas_agent_kit.backends.cdaweb.config import configure

__all__ = ["configure", "__version__"]
