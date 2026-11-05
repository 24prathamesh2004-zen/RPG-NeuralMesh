"""Answer step: the model writes from the evidence records only, citing evidence IDs."""
from __future__ import annotations

from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parents[2] / "config" / "prompts" / "mesh_answer_v1.txt"
PROMPT_VERSION = "mesh_answer_v1"
NO_EVIDENCE = "[NOT IN EVIDENCE]"


def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def answer(call_model, context_prompt: str) -> str | None:
    return call_model("answer", system_prompt(), context_prompt)
