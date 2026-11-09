"""The model backend picks the provider the policy names, and the Claude backend sends and reads the right fields."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from services.context import llm
from services.context import policy as model_policy


def test_policy_names_claude_for_every_step_with_the_anthropic_provider():
    model_policy._load.cache_clear()
    data = model_policy.policy()
    for step in ("answer", "rerank", "classify"):
        choice = model_policy.choice_for(step)
        assert choice.model == "claude-sonnet-5-5" and choice.provider == "anthropic" and choice.tier == "cloud"
        assert choice.api_key_env == "NEURALMESH_ANTHROPIC_API_KEY"
    assert data["models"]["groq-dev"].get("provider", "openai-compatible") == "openai-compatible"


class FakeMessages:
    def __init__(self, log, stop_reason="end_turn"):
        self.log, self.stop_reason = log, stop_reason

    def create(self, **kwargs):
        self.log.append(kwargs)
        return SimpleNamespace(stop_reason=self.stop_reason,
                               content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Two practices cut spoilage.")],
                               usage=SimpleNamespace(input_tokens=321, output_tokens=12))


def test_claude_backend_sends_system_user_and_budget_and_reads_text_and_tokens(monkeypatch):
    monkeypatch.setenv("NEURALMESH_ANTHROPIC_API_KEY", "test-key")
    log: list[dict] = []
    backend = llm.AnthropicBackend(client_factory=lambda key: SimpleNamespace(messages=FakeMessages(log), key=key))
    choice = model_policy.ModelChoice("answer", "claude-sonnet-5-5", "cloud", "", "NEURALMESH_ANTHROPIC_API_KEY", 8000, 1200, "anthropic")
    text, tokens_in, tokens_out = backend.complete(choice, "You answer from the evidence only.", "EVIDENCE ... QUESTION ...")
    assert text == "Two practices cut spoilage." and (tokens_in, tokens_out) == (321, 12)
    sent = log[0]
    assert sent["model"] == "claude-sonnet-5-5" and sent["max_tokens"] == 1200
    assert sent["system"] == "You answer from the evidence only." and sent["messages"] == [{"role": "user", "content": "EVIDENCE ... QUESTION ..."}]
    assert sent["thinking"] == {"type": "adaptive"} and sent["output_config"] == {"effort": "low"}
    assert backend._client("test-key").key == "test-key"


def test_claude_backend_treats_a_refusal_as_an_error_so_the_answer_stays_evidence_only(monkeypatch):
    monkeypatch.setenv("NEURALMESH_ANTHROPIC_API_KEY", "test-key")
    backend = llm.AnthropicBackend(client_factory=lambda key: SimpleNamespace(messages=FakeMessages([], stop_reason="refusal")))
    choice = model_policy.ModelChoice("answer", "claude-sonnet-5-5", "cloud", "", "NEURALMESH_ANTHROPIC_API_KEY", 8000, 1200, "anthropic")
    with pytest.raises(RuntimeError):
        backend.complete(choice, "s", "u")


def test_model_backend_dispatches_by_provider(monkeypatch):
    monkeypatch.setenv("NEURALMESH_ANTHROPIC_API_KEY", "k")
    backend = llm.ModelBackend()
    calls: list[str] = []
    backend._anthropic = SimpleNamespace(complete=lambda c, s, u: calls.append("anthropic") or ("a", 1, 1))
    backend._openai = SimpleNamespace(complete=lambda c, s, u: calls.append("openai") or ("o", 1, 1))
    claude = model_policy.ModelChoice("answer", "claude-sonnet-5-5", "cloud", "", "NEURALMESH_ANTHROPIC_API_KEY", 1, 1, "anthropic")
    groq = model_policy.ModelChoice("answer", "llama", "cloud", "https://api.groq.com/openai/v1", "NEURALMESH_GROQ_API_KEY", 1, 1)
    assert backend.complete(claude, "s", "u")[0] == "a" and backend.complete(groq, "s", "u")[0] == "o"
    assert calls == ["anthropic", "openai"]


def test_no_key_means_no_backend_and_evidence_only_answers(monkeypatch):
    import shared.config

    monkeypatch.delenv("NEURALMESH_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(shared.config, "get_settings", lambda: SimpleNamespace(neuralmesh_anthropic_api_key=""))
    choice = model_policy.ModelChoice("answer", "claude-sonnet-5-5", "cloud", "", "NEURALMESH_ANTHROPIC_API_KEY", 1, 1, "anthropic")
    assert llm.has_api_key(choice) is False
