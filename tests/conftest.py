"""Pytest configuration and test environment setup."""

import pytest
from dotenv import load_dotenv

load_dotenv()

from backend.app.graph.client import GraphClient
from backend.app.graph.errors import GraphUnavailable
from backend.app.services.graph_client import reset_graph_repository_cache
from backend.app.settings import get_settings


def is_falkordb_reachable() -> bool:
    try:
        client = GraphClient()
        client.ping()
        return True
    except (GraphUnavailable, Exception):
        return False


@pytest.fixture(autouse=True)
def configure_test_environment(monkeypatch):
    """Default unit and route test suites to DEV_MOCKS=True for deterministic mock contract tests.

    Live integration tests (like test_falkordb_live.py) explicitly override DEV_MOCKS=False.
    """
    monkeypatch.setenv("DEV_MOCKS", "true")
    get_settings.cache_clear()
    reset_graph_repository_cache()
