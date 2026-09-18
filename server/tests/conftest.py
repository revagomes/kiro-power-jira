"""Pytest fixtures for the JIRA MCP server.

Imports the server module without triggering .env bootstrap or requiring a live
JIRA instance. All network access is mocked at the ``_api_request`` seam.
"""

import importlib
import os
import sys
import pathlib

import pytest

# Ensure the server directory is importable as a top-level module.
_SERVER_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(_SERVER_DIR))


@pytest.fixture()
def jira():
    """Import a fresh copy of the server module with test config.

    - Skips .env bootstrap via _JIRA_MCP_SKIP_ENV.
    - Provides required config env vars so _check_config passes.
    - Reloads the module so module-level config constants pick up the env.
    """
    os.environ["_JIRA_MCP_SKIP_ENV"] = "1"
    os.environ["JIRA_PAT"] = "test-token"
    os.environ["JIRA_BASE_URL"] = "https://jira.example.com"
    os.environ["JIRA_PROJECT"] = "TEST"

    if "jira_mcp" in sys.modules:
        module = importlib.reload(sys.modules["jira_mcp"])
    else:
        module = importlib.import_module("jira_mcp")
    return module
