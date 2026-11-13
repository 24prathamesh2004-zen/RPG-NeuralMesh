"""Scoping after the fan-out: group per document, select the top 12, confirm each with a re-rank.
A document the re-rank rejects moves to "also found" and keeps its citation. It is never dropped."""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from contracts.evidence import EvidenceRecord
from services.context import prompts

TOP_DOCUMENTS = 12
KEEP_AT_LEAST = 6  # documents a re-rank leaves in the evidence at least, the best ranked first
TEXTS_PER_DOCUMENT = 3



@dataclass
class Scope:
    selected: dict[str, list[EvidenceRecord]] = field(default_factory=dict)
    also_found: dict[str, list[EvidenceRecord]] = field(default_factory=dict)
    verdicts: dict[str, dict] = field(default_factory=dict)
    rerank: str = "not_run"


def group_by_document(records: list[EvidenceRecord]) -> dict[str, list[EvidenceRecord]]:
    groups: dict[str, list[EvidenceRecord]] = {}
    for r in records:
        groups.setdefault(r.document or r.evidence_id, []).append(r)
    return groups


def select(records: list[EvidenceRecord]) -> tuple[dict[str, list[EvidenceRecord]], dict[str, list[EvidenceRecord]]]:
    """Top documents taken round-robin by each node's own rank (rank 1 of every node, then rank 2, ...), so a node
    with many hits cannot crowd out the best document of another node. Ties go to the higher node score."""
    groups = group_by_document(records)

    def order(item):
        doc, recs = item
        return (min((r.rank or 99) for r in recs), -max((r.score or 0.0) for r in recs), recs[0].node, doc)

    ranked = sorted(groups.items(), key=order)
    return dict(ranked[:TOP_DOCUMENTS]), dict(ranked[TOP_DOCUMENTS:])


def apply_verdicts(selected: dict[str, list[EvidenceRecord]], verdicts: dict[str, dict]) -> Scope:
    """Reuse stored re-rank verdicts for the same question and documents, without a model call."""
    scope = Scope(selected=dict(selected), verdicts=dict(verdicts), rerank="cached")
    for doc in list(scope.selected):
        if verdicts.get(doc, {}).get("relevant") is False:
            scope.also_found[doc] = scope.selected.pop(doc)
    return scope


def rerank(question: str, selected: dict[str, list[EvidenceRecord]], call_model) -> Scope:
    scope = Scope(selected=dict(selected))
    if not selected:
        scope.rerank = "nothing_to_rank"
        return scope
    if call_model is None:
        scope.rerank = "skipped_no_model"
        return scope
    blocks = []
    for doc, recs in selected.items():
        texts = [r.text for r in recs if r.text][:TEXTS_PER_DOCUMENT]
        blocks.append(f"Document: {doc}\nTitle: {recs[0].title}\n" + "\n".join(f"- {t}" for t in texts))
    prompt = f"Question:\n{question}\n\nDocuments:\n\n" + "\n\n".join(blocks)
    rerank_prompt = prompts.load("rerank")
    text = call_model("rerank", rerank_prompt.text, prompt, prompt_version=rerank_prompt.version)
    if text is None:
        scope.rerank = "skipped_model_unavailable"
        return scope
    try:
        cleaned = text.strip().strip("`")
        cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
        verdicts = {v["document"]: v for v in json.loads(cleaned) if isinstance(v, dict) and "document" in v}
    except (ValueError, TypeError):
        scope.rerank = "skipped_unreadable_reply"
        return scope
    scope.verdicts = verdicts
    for doc in list(scope.selected):
        if verdicts.get(doc, {}).get("relevant") is False:
            scope.also_found[doc] = scope.selected.pop(doc)
    scope.rerank = "done"
    return scope
