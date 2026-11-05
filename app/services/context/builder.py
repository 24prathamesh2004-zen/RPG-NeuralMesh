"""Context builder: fit evidence records into the answer prompt within a fixed budget and priority order.

Order: question, routing explanation, relationships, aggregates, summaries, chunks, withheld items.
Blocks 1 to 4 and 7 are protected. Summaries share 60% and chunks 40% of what remains. Text is cut only at a
sentence end, and what does not fit is counted in an omission note, never silently dropped.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from contracts.evidence import EvidenceRecord
from services.context.records import strip_injection

BUDGET_CHARS = 24_000
CAPS = {"question": 1_000, "routing": 600, "relationships": 20, "aggregates": 30, "summaries_per_node": 10,
        "chunks_per_document": 3, "withheld": 15}


@dataclass
class BuiltContext:
    prompt: str = ""
    included: list[str] = field(default_factory=list)
    omitted: int = 0
    skipped_reason: str | None = None
    chars: int = 0


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[:limit]
    end = max(head.rfind(". "), head.rfind(".\n"))
    return head[: end + 1] if end > 0 else ""


def _line(r: EvidenceRecord) -> str:
    stale = " (stale)" if r.stale else ""
    return f"[{r.evidence_id}] {r.citation} · {r.title} · version {r.version}{stale} · {r.mode}\n{r.text or ''}"


def build(question: str, purpose: str, company: str, routing: str, relationships: list[EvidenceRecord],
          records: list[EvidenceRecord], withheld: list[EvidenceRecord], budget: int = BUDGET_CHARS,
          today: date | None = None) -> BuiltContext:
    out = BuiltContext()
    bundle_docs = {r.document for r in records if r.document}
    usable = [strip_injection(r) for r in records if not (r.superseded_by and r.superseded_by in bundle_docs)]
    out.omitted += len(records) - len(usable)
    usable.sort(key=lambda r: (r.stale, r.rank or 99))

    aggregates = [r for r in usable if r.kind == "aggregate"][: CAPS["aggregates"]]
    summaries, per_node = [], {}
    for r in usable:
        if r.kind == "summary":
            per_node[r.node] = per_node.get(r.node, 0) + 1
            if per_node[r.node] <= CAPS["summaries_per_node"]:
                summaries.append(r)
            else:
                out.omitted += 1
    chunks, per_doc = [], {}
    for r in usable:
        if r.kind == "chunk":
            per_doc[r.document] = per_doc.get(r.document, 0) + 1
            if per_doc[r.document] <= CAPS["chunks_per_document"]:
                chunks.append(r)
            else:
                out.omitted += 1
    rels = relationships[: CAPS["relationships"]]
    out.omitted += max(0, len(relationships) - CAPS["relationships"])
    held = withheld[: CAPS["withheld"]]
    out.omitted += max(0, len(withheld) - CAPS["withheld"])

    protected = [
        "## Question\n" + _cut(f"{question}\nPurpose: {purpose}. Asked by a user of {company} on {(today or date.today()).isoformat()}.",
                               CAPS["question"]),
        "## Why these subsidiaries were asked\n" + _cut(routing, CAPS["routing"]),
        "## Approved links between documents\n" + ("\n".join(
            f"[{r.evidence_id}] {r.relationship.source} {r.relationship.type} {r.relationship.target}: {r.relationship.note or ''}"
            for r in rels) or "None."),
        "## Aggregate facts\n" + ("\n\n".join(_line(r) for r in aggregates) or "None."),
    ]
    tail = "## Withheld items (no text may be used)\n" + ("\n".join(
        f"[{r.evidence_id}] {r.title} · {r.datapoint} · {r.reason or r.decision}" for r in held) or "None.")
    fixed = "\n\n".join(protected + [tail])
    if len(fixed) >= budget:
        out.skipped_reason = "protected blocks exceed the budget"
        return out
    remaining = budget - len(fixed) - 200

    def fill(items: list[EvidenceRecord], limit: int, heading: str) -> str:
        lines, used = [heading], len(heading)
        for i, r in enumerate(items):
            line = _line(r)
            if used + len(line) + 2 > limit:
                cut = _cut(line, limit - used - 2)
                if cut and len(cut) > len(line.split("\n", 1)[0]) + 20:
                    lines.append(cut)
                    out.included.append(r.evidence_id)
                    i += 1
                left = len(items) - i
                if left:
                    out.omitted += left
                    lines.append(f"{left} further items omitted for size, treat this as a partial set.")
                break
            lines.append(line)
            out.included.append(r.evidence_id)
            used += len(line) + 2
        return "\n\n".join(lines)

    summary_block = fill(summaries, int(remaining * 0.6), "## Approved summaries")
    chunk_block = fill(chunks, remaining - len(summary_block), "## Cited text chunks")
    out.included += [r.evidence_id for r in rels + aggregates]
    out.prompt = "\n\n".join(protected + [summary_block, chunk_block, tail])
    if out.omitted:
        out.prompt += f"\n\nNote: {out.omitted} items were omitted for size or as superseded. Treat the evidence as a partial set."
    out.chars = len(out.prompt)
    return out


def cited_ids(answer: str) -> list[str]:
    return re.findall(r"\[([a-z]+:[^\]\s]+)\]", answer)
