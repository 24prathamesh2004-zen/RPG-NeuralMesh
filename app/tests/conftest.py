"""Pytest fixtures."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

# Test runs never write into app/.neuralmesh: the central graph store and the central audit go to a temp folder.
_STATE = Path(tempfile.mkdtemp(prefix="neuralmesh-tests-"))
os.environ.setdefault("NEURALMESH_GRAPH_DB", str(_STATE / "mesh_graph.db"))
os.environ.setdefault("NEURALMESH_CENTRAL_AUDIT", str(_STATE / "central_audit.jsonl"))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
