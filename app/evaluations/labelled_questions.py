"""A labelled question set for retrieval quality, and the two measures on it: recall at 10 and nDCG at 10.

build:    for every released document of every node, the answer model writes two questions a person might ask that
          this document answers, without reusing the words of its title. Saved with the expected node, datapoint
          and document to neuralmesh_kb_pack/kb/labelled_questions.yaml. Run once, reviewed by a person, kept.
measure:  for every labelled question, search the expected node with keyword search alone and with hybrid search,
          take the top 10 documents, and compute recall at 10 (is the expected document in the top 10) and nDCG at 10
          (how high it sits: 1 at rank 1, falling with the rank). Prints both measures for both search modes.

Run from app:  ../.venv/bin/python -m evaluations.labelled_questions build
               ../.venv/bin/python -m evaluations.labelled_questions measure
"""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import yaml

from mcp_nodes import knowledge_view
from mcp_nodes.auth import CallerContext
from mcp_nodes.server import load_node_config, search_node
from services.context import policy as model_policy
from services.context.llm import ModelBackend, has_api_key
from shared.registry import node_ids

APP = Path(__file__).resolve().parents[1]
KB = APP / "neuralmesh_kb_pack" / "kb"
OUT = KB / "labelled_questions.yaml"
SYSTEM = ("You write test questions for a search system. For each document you are given its title and summary. Write two short questions, "
          "in plain words, that a person in another company of the group might ask and that this document answers. Do not reuse any word of "
          "the title longer than three letters. Reply with ONLY a JSON object: {\"<document id>\": [\"question 1\", \"question 2\"], ...}")


def _documents(node: str) -> list[dict]:
    cfg = yaml.safe_load((KB / f"{node}.yaml").read_text(encoding="utf-8"))
    return [{"id": f"{node}:{d['id']}", "datapoint": d["dp"], "title": d["title"], "summary": d.get("summary", "")} for d in cfg.get("docs", [])
            if d.get("summary")]


def build() -> None:
    choice = model_policy.choice_for("answer")
    if not has_api_key(choice):
        raise SystemExit(f"{choice.api_key_env} is not set, the questions cannot be written")
    backend = ModelBackend()
    out: list[dict] = []
    for node in node_ids():
        docs = _documents(node)
        for i in range(0, len(docs), 8):
            batch = docs[i:i + 8]
            user = "\n\n".join(f"Document {d['id']}\nTitle: {d['title']}\nSummary: {d['summary']}" for d in batch)
            text, _, _ = backend.complete(choice, SYSTEM, user)
            cleaned = text.strip().strip("`")
            cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
            parsed = json.loads(cleaned)
            for d in batch:
                for q in parsed.get(d["id"], [])[:2]:
                    out.append({"question": q, "node": node, "datapoint": d["datapoint"], "document": d["id"]})
    OUT.write_text(yaml.safe_dump({"note": "Written by the answer model from each document's title and summary, to be reviewed by a person. "
                                           "Expected document and datapoint are the ones the question was written from.",
                                   "model": choice.model, "questions": out}, sort_keys=False, allow_unicode=True), encoding="utf-8")
    print(f"wrote {len(out)} questions to {OUT}")


def _top10(node: str, question: str, hybrid: bool) -> list[str]:
    config = load_node_config(node)
    caller = CallerContext("eval", node, frozenset({"group_user"}), "problem_solving")
    if hybrid:
        response = search_node(config, caller, question, "problem_solving")
    else:
        original = knowledge_view._vector_keys
        knowledge_view._vector_keys = lambda *a, **k: []
        try:
            response = search_node(config, caller, question, "problem_solving")
        finally:
            knowledge_view._vector_keys = original
    ids = []
    for item in response["results"] + response["withheld"]:
        doc = re.sub(r"#\d+$", "", item.get("evidence_id") or item.get("doc_id") or "")
        if doc and doc not in ids:
            ids.append(doc)
    return ids[:10]


def measure() -> None:
    data = yaml.safe_load(OUT.read_text(encoding="utf-8"))["questions"]
    for hybrid in (False, True):
        recall, ndcg = 0.0, 0.0
        for q in data:
            top = _top10(q["node"], q["question"], hybrid)
            if q["document"] in top:
                rank = top.index(q["document"]) + 1
                recall += 1
                ndcg += 1 / math.log2(rank + 1)
        n = len(data)
        print(f"{'hybrid ' if hybrid else 'keyword'} search: recall@10 {recall / n:.2f}, nDCG@10 {ndcg / n:.2f} over {n} questions")


if __name__ == "__main__":
    {"build": build, "measure": measure}[sys.argv[1] if len(sys.argv) > 1 else "measure"]()
