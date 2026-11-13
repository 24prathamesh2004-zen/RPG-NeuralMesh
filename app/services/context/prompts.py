"""The prompts of the three model steps, each a versioned file in config/prompts.

One place names which file each step uses. The file stem is the prompt version, written to the audit with every
model call and into the cache keys, so a prompt change never serves a cached answer written under the old text.
To change a prompt: add mesh_<step>_v<n+1>.txt, point the step at it here, keep the old file.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "config" / "prompts"
FILES = {
    "answer": "mesh_answer_v5.txt",
    "rerank": "mesh_rerank_v2.txt",
    "classify": "mesh_classify_v1.txt",
    "kind": "mesh_kind_v1.txt",
    "map": "mesh_map_v2.txt",
    "extract": "mesh_extract_v3.txt",
    "describe": "mesh_describe_v1.txt",
    "verify": "mesh_verify_v2.txt",
    "choose": "mesh_choose_v2.txt",
}


@dataclass(frozen=True)
class Prompt:
    step: str
    version: str
    text: str


@lru_cache(maxsize=8)
def load(step: str) -> Prompt:
    name = FILES[step]
    return Prompt(step, Path(name).stem, (PROMPTS_DIR / name).read_text(encoding="utf-8").strip())


def versions() -> dict[str, str]:
    return {step: Path(name).stem for step, name in FILES.items()}
