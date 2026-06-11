"""spedas-mcp — unified SPEDAS-oriented MCP facade over XHelio CDAWeb, PDS, and SPICE tools."""

__version__ = "0.1.0"


def main() -> None:
    """Console entry point for the SPEDAS MCP server."""
    try:
        from spedas_mcp.server import serve
    except ImportError as exc:
        print(
            "Error: SPEDAS MCP server requires the MCP extra and xhelio dependencies.\n"
            "Install with: pip install 'spedas-mcp[mcp]'"
        )
        raise SystemExit(1) from exc
    serve()
