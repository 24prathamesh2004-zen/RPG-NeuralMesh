"""Model calls through an OpenAI-compatible chat endpoint (the group gateway, Ollama, or Groq in development) or
through the Claude API (provider "anthropic" in the model policy). ModelBackend picks the one the policy names.
Every call is checked against the model policy and its token budget first, and writes a central audit event
with step, model, tier, tokens and decision. The prompt and the answer are never written to the audit."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol

import httpx

from services.context import policy as model_policy
from services.context import prompts
from observability import tracing

AUDIT_PATH = Path(__file__).resolve().parents[2] / ".neuralmesh" / "central_audit.jsonl"
_audit_lock = threading.Lock()


class ChatBackend(Protocol):
    def complete(self, choice: model_policy.ModelChoice, system: str, user: str) -> tuple[str, int, int]: ...


def api_key_for(choice: model_policy.ModelChoice) -> str:
    """The key named by the policy entry, from the environment or from app/.env. Empty when none is named."""
    key = os.getenv(choice.api_key_env, "") if choice.api_key_env else ""
    if choice.api_key_env and not key:
        from shared.config import get_settings
        key = getattr(get_settings(), choice.api_key_env.lower(), "") or ""
    if choice.api_key_env and not key:
        raise RuntimeError(f"{choice.api_key_env} is not set")
    return key


def has_api_key(choice: model_policy.ModelChoice) -> bool:
    try:
        return bool(api_key_for(choice)) or not choice.api_key_env
    except RuntimeError:
        return False


THINKING_MIN_OUTPUT_TOKENS = 1000


class AnthropicBackend:
    """The Claude API through the official SDK. Thinking stays on (the model decides how much), effort low because
    the answer step writes from selected evidence only. A refusal is an error, so the mesh falls back to evidence only."""

    def __init__(self, client_factory: Callable[[str], object] | None = None) -> None:
        self._factory = client_factory
        self._clients: dict[str, object] = {}

    def _client(self, key: str):
        if key not in self._clients:
            if self._factory is not None:
                self._clients[key] = self._factory(key)
            else:
                import anthropic
                self._clients[key] = anthropic.Anthropic(api_key=key, max_retries=2, timeout=60.0)
        return self._clients[key]

    def complete(self, choice: model_policy.ModelChoice, system: str, user: str) -> tuple[str, int, int]:
        extra: dict = {}
        if choice.max_output_tokens >= THINKING_MIN_OUTPUT_TOKENS:  # thinking tokens count against max_tokens, so a small cap leaves no room for the text
            extra = {"thinking": {"type": "adaptive"}, "output_config": {"effort": "low"}}
        response = self._client(api_key_for(choice)).messages.create(
            model=choice.model, max_tokens=choice.max_output_tokens, system=system,
            messages=[{"role": "user", "content": user}], **extra,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("the model declined the request")
        text = "".join(block.text for block in response.content if getattr(block, "type", "") == "text")
        if not text.strip() and response.stop_reason == "max_tokens":
            raise RuntimeError("the model reached its output limit before writing any text")
        return text, int(response.usage.input_tokens), int(response.usage.output_tokens)


class ModelBackend:
    """Dispatches each call to the backend of the provider named in the model policy."""

    def __init__(self) -> None:
        self._openai = OpenAICompatibleBackend()
        self._anthropic = AnthropicBackend()

    def complete(self, choice: model_policy.ModelChoice, system: str, user: str) -> tuple[str, int, int]:
        backend = self._anthropic if choice.provider == "anthropic" else self._openai
        return backend.complete(choice, system, user)


class OpenAICompatibleBackend:
    def complete(self, choice: model_policy.ModelChoice, system: str, user: str) -> tuple[str, int, int]:
        key = api_key_for(choice)
        response = httpx.post(
            f"{choice.base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}"} if key else {},
            json={"model": choice.model, "temperature": 0, "max_tokens": choice.max_output_tokens,
                  "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        usage = body.get("usage", {})
        return body["choices"][0]["message"]["content"], int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))


def audit(event: dict) -> None:
    path = Path(os.getenv("NEURALMESH_CENTRAL_AUDIT", str(AUDIT_PATH)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with _audit_lock:
        previous = ""
        if path.exists():
            lines = path.read_text(encoding="utf-8").splitlines()
            previous = json.loads(lines[-1]).get("hash", "") if lines else ""
        event = {"timestamp": datetime.now(timezone.utc).isoformat(), **event, "previous_hash": previous}
        event["hash"] = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")


def make_caller(backend: ChatBackend, *, app_env: str, trace_id: str, sensitivities: set[str], all_synthetic: bool,
                calls: list[dict]) -> Callable[[str, str, str], str | None]:
    """Return call_model(step, system, user, prompt_version=None) -> text or None. None means the call was not made or failed."""

    def call_model(step: str, system: str, user: str, prompt_version: str | None = None) -> str | None:
        choice = model_policy.choice_for(step)
        event = {"event": "model_call", "trace_id": trace_id, "step": step, "model": choice.model, "tier": choice.tier,
                 "prompt_version": prompt_version or prompts.versions().get(step, "inline")}
        ok, reason = model_policy.allowed(choice, app_env, sensitivities, all_synthetic)
        tokens_in = model_policy.estimate_tokens(system + user)
        if not ok:
            event.update(decision="blocked_by_policy", reason=reason)
        elif tokens_in > choice.max_input_tokens:
            event.update(decision="skipped_by_budget", reason=f"{tokens_in} tokens over {choice.max_input_tokens}")
        else:
            started = time.perf_counter()
            try:
                with tracing.span(f"chat {choice.model}", {"gen_ai.request.model": choice.model, "gen_ai.operation.name": "chat",
                                                          "mesh.step": step, "mesh.trace_id": trace_id, "mesh.prompt_version": event["prompt_version"]}):
                    text, used_in, used_out = backend.complete(choice, system, user)
                event.update(decision="made", tokens_in=used_in or tokens_in, tokens_out=used_out,
                             ms=round((time.perf_counter() - started) * 1000))
                audit(event)
                calls.append(event)
                return text
            except Exception as exc:  # noqa: BLE001 - a failed call degrades to evidence only
                event.update(decision="failed", reason=type(exc).__name__ + ": " + str(exc)[:160])
        audit(event)
        calls.append(event)
        return None

    return call_model
