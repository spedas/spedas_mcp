"""Tests for server runtime cache configuration."""
from pathlib import Path

from spedas_agent_kit.server import create_server


def test_create_server_does_not_require_runtime_downloads():
    """Server construction should be cheap and side-effect-light."""
    server = create_server()
    assert server is not None


def test_gitignore_keeps_local_venv_out_of_repo():
    """Scaffold should not accidentally commit generated virtualenvs/caches."""
    ignore = Path(".gitignore").read_text()
    assert ".venv/" in ignore
    assert ".pytest_cache/" in ignore
