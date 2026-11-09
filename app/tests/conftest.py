"""Pytest fixtures."""
from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# Test runs never write into app/.neuralmesh: the central graph store and the central audit go to a temp folder.
_STATE = Path(tempfile.mkdtemp(prefix="neuralmesh-tests-"))
os.environ.setdefault("NEURALMESH_GRAPH_DB", str(_STATE / "mesh_graph.db"))
os.environ.setdefault("NEURALMESH_CENTRAL_AUDIT", str(_STATE / "central_audit.jsonl"))

# The tests run on a copy of the node packs with the pinned sample talent packs (tests/fixtures), never on the packs an
# application last sent through the import tool, so a live import cannot change what a test expects, and a test never
# writes into the repository's packs or opens its Chroma stores.
_APP = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
shutil.copytree(_APP / "neuralmesh_kb_pack" / "data_pack", _STATE / "data_pack")
for _node in (_FIXTURES / "node_talent").iterdir():
    shutil.copy(_node / "pack.json", _STATE / "data_pack" / _node.name / "packs" / "talent" / "pack.json")
shutil.copytree(_FIXTURES / "talent_import", _STATE / "talent_import")
os.environ["NEURALMESH_DATA_PACK"] = str(_STATE / "data_pack")
os.environ["NEURALMESH_TALENT_IMPORT"] = str(_STATE / "talent_import")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
