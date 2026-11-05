"""Turn what the nodes return into evidence records of contracts/evidence.py."""
from __future__ import annotations

import re
from typing import Any

from contracts.evidence import EvidenceRecord, RelationshipRef, validate_record

_INJECTION = re.compile(r"[^.!?]*\b(ignore\s+previous\s+instructions|disregard\s+the\s+system\s+prompt)\b[^.!?]*[.!?]?", re.I)


def from_node_results(node_results: list[dict[str, Any]]) -> tuple[list[EvidenceRecord], list[EvidenceRecord]]:
    """Released records and withheld records, in node rank order."""
    released, withheld = [], []
    for node in node_results:
        for item in node.get("results", []):
            if "evidence_id" in item:
                released.append(validate_record(item))
        for item in node.get("withheld", []):
            if "evidence_id" in item:
                record = validate_record({**item, "kind": "metadata", "text": None})
                withheld.append(record)
    return released, withheld


def from_summary(response: dict[str, Any]) -> EvidenceRecord | None:
    """A summarize response becomes a summary record (its text lives in the summary field)."""
    if response.get("decision") not in ("ALLOWED", "ALLOWED_SUMMARY_ONLY") or "evidence_id" not in response:
        return None
    return validate_record({**response, "kind": "summary", "text": response.get("summary")})


def from_relationship(rel: dict[str, Any]) -> EvidenceRecord:
    return EvidenceRecord(
        evidence_id=rel["id"], kind="relationship", node=rel["source"].split(":", 1)[0],
        title=f"{rel['source']} {rel['type']} {rel['target']}", citation=rel["id"],
        relationship=RelationshipRef(id=rel["id"], type=rel["type"], source=rel["source"], target=rel["target"],
                                     note=rel.get("note"), approvals=rel.get("approvals", [])),
    )


def strip_injection(record: EvidenceRecord) -> EvidenceRecord:
    """Remove the sentence that matched the injection pattern from a suspicious record."""
    if not record.suspicious or not record.text or not _INJECTION.search(record.text):
        return record
    cleaned = _INJECTION.sub(" ", record.text)
    cleaned = " ".join(cleaned.split()) + " [instruction-like text removed]"
    return record.model_copy(update={"text": cleaned})


def removed_instructions(record: EvidenceRecord) -> list[str]:
    if not record.text:
        return []
    return [m.group(0).strip() for m in _INJECTION.finditer(record.text)]
