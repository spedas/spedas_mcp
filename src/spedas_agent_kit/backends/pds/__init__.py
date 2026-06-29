"""Vendored PDS PPI backend (formerly the ``xhelio-pds`` / ``pdsmcp`` package).

Absorbed into spedas_agent_kit (issue #107) so the repo is self-contained. Exposes the
PDS library surface (catalog / metadata / fetch / cache / config / label_parser)
that the spedas_agent_kit facade dispatches to for ``source_type="pds"``. The package's
former standalone MCP server/CLI is dropped — the spedas_agent_kit facade replaces it.
"""

__version__ = "0.3.0"

from spedas_agent_kit.backends.pds.config import configure

__all__ = ["configure", "__version__"]
