"""Evidence record contract, schema_version 1.0.

One evidence record is one fact a node allowed to leave (an approved summary, a cited chunk, an aggregate
row set), one withheld title, one approved relationship or one consented expert. Nodes, the orchestrator,
the Ask page and the SkillForge context API all read and write this one shape. An expert record keeps the
role, level, evidence and name rule inside its expert field. A relationship in a query response has the
RelationshipRef shape.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"
EvidenceKind = Literal["summary", "chunk", "aggregate", "metadata", "relationship", "expert"]


class RelationshipRef(BaseModel):
    id: str
    type: str
    source: str
    target: str
    note: str | None = None
    approvals: list[dict] = Field(default_factory=list)
    status: str | None = None
    source_title: str | None = None
    target_title: str | None = None


class EvidenceRecord(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    evidence_id: str
    kind: EvidenceKind
    node: str
    datapoint: str | None = None
    document: str | None = None
    title: str | None = None
    version: str | None = None
    pack_version: str | None = None
    stale: bool = False
    superseded_by: str | None = None
    mode: str | None = None
    sensitivity: str | None = None
    decision: str | None = None
    rule_id: str | None = None
    reason: str | None = None
    text: str | None = None
    citation: str | None = None
    concepts: list[str] = Field(default_factory=list)
    score: float | None = None
    rank: int | None = None
    suspicious: bool = False
    relationship: RelationshipRef | None = None
    expert: dict | None = None
    # learning_sources only: the EXPLAINS_SKILL level the document reaches, and how the text is delivered
    explains_level: str | None = None
    delivery: Literal["by_reference"] | None = None


def validate_record(raw: dict) -> EvidenceRecord:
    return EvidenceRecord.model_validate({k: v for k, v in raw.items() if k in EvidenceRecord.model_fields})
