"""Help chat: grounded in the app guides, falls back to guide sections, needs a signed-in user."""
from __future__ import annotations

from fastapi.testclient import TestClient

from services import help_chat


class FakeBackend:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def complete(self, choice, system, user):
        self.calls.append((system, user))
        return "Open **Context graph** and choose **Add input**.", 120, 12


def test_index_reads_the_guide_and_the_node_registry():
    index = help_chat.help_index()
    sources = {s.source for s in index.sections}
    assert "help_kb/help_chat_and_ask_neuralmesh.md" in sources
    assert "config/nodes.yaml" in sources
    assert "RPG_NeuralMesh_Wireframe_v4.html" not in sources


def test_search_finds_the_upload_steps():
    hits = help_chat.help_index().search("how do I add an input to a context graph")
    assert hits
    assert any("Common tasks" == s.heading for _, s in hits)


def test_answer_uses_the_model_with_the_guide_sections():
    backend = FakeBackend()
    result = help_chat.answer("How do I add an input to a context graph?", [], "/context-graph", backend=backend)
    assert result["mode"] == "model"
    assert "Add input" in result["answer"]
    system, user = backend.calls[0]
    assert "Ask NeuralMesh" in system
    assert "Add to the graph" in user  # the guide section went into the prompt
    assert "/context-graph" in user
    assert result["sources"]


def test_answer_falls_back_to_sections_when_the_model_fails():
    class Broken:
        def complete(self, *args):
            raise RuntimeError("down")

    result = help_chat.answer("What do the exposure modes mean?", [], None, backend=Broken())
    assert result["mode"] == "passages"
    assert "**" in result["answer"]


def test_endpoint_needs_a_signed_in_user():
    from api.main import app
    response = TestClient(app).post("/api/v1/help/chat", json={"question": "What is a datapoint?"})
    assert response.status_code in (401, 403)


def test_help_chat_ignores_the_development_stand_in(monkeypatch):
    monkeypatch.setenv("NEURALMESH_MODEL_POLICY", "config/model_policy.dev-standin.json")
    choice = help_chat.help_model_choice()
    assert not choice.model.startswith("standin")
    assert choice.step == "help_chat"
