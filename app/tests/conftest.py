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
os.environ.setdefault("NEURALMESH_CONTEXT_GRAPHS", str(_STATE / "context_graphs"))
os.environ.setdefault("NEURALMESH_GRAPH_NOTES", str(_STATE / "graph_notes"))

# The tests run on a copy of the node packs with the pinned sample talent packs (tests/fixtures), never on the packs an
# application last sent through the import tool, so a live import cannot change what a test expects, and a test never
# writes into the repository's packs or opens its Chroma stores.
_APP = Path(__file__).resolve().parents[1]
_FIXTURES = Path(__file__).resolve().parent / "fixtures"
shutil.copytree(_APP / "neuralmesh_kb_pack" / "data_pack", _STATE / "data_pack")


def _pin_talent_packs() -> None:
    for node in (_FIXTURES / "node_talent").iterdir():
        shutil.copy(node / "pack.json", _STATE / "data_pack" / node.name / "packs" / "talent" / "pack.json")


_pin_talent_packs()
shutil.copytree(_FIXTURES / "talent_import", _STATE / "talent_import")
os.environ["NEURALMESH_DATA_PACK"] = str(_STATE / "data_pack")
os.environ["NEURALMESH_TALENT_IMPORT"] = str(_STATE / "talent_import")


def _start_without_uploads() -> None:
    """The copy starts with no uploaded input. The development data pack holds whatever a person or the sample loader
    (scripts/sample_inputs.py) uploaded, and a test that counts uploads must not depend on that. Every context graph of
    the copy is dropped the way the application drops one, which takes its documents out of the pack files, the keyword
    rows and the vectors. Then the upload records go, so the first upload of a test is U001 again."""
    from knowledge import embedder, packgen
    from services import uploads
    from shared.registry import node_ids

    accepted = [record for node in node_ids() for record in packgen.contributions_of(node)]
    for graph_id in sorted({uploads.graph_ref(record)["id"] for record in accepted}):
        dropped = uploads.drop_graph(graph_id, {"company": "tests"}, build_vectors=embedder.available())
        if dropped["failed"]:
            raise RuntimeError(f"The test copy of the data pack could not be cleared of uploads: {dropped['failed']}")
    for path in (_STATE / "data_pack").glob(f"*/{packgen.CONTRIBUTIONS}/*.json"):
        path.unlink()
    if accepted:
        _pin_talent_packs()  # the drop of an upload under a talent item builds that talent pack again


_start_without_uploads()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)
