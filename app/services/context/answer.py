"""Answer step: the model writes from the evidence records only, citing evidence IDs."""
from __future__ import annotations

from services.context import prompts

PROMPT_VERSION = prompts.load("answer").version
NO_EVIDENCE = "[NOT IN EVIDENCE]"


def system_prompt() -> str:
    return prompts.load("answer").text


def answer(call_model, context_prompt: str) -> str | None:
    return call_model("answer", system_prompt(), context_prompt, prompt_version=PROMPT_VERSION)
