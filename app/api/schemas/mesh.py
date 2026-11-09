"""Request and response contracts for the central mesh query endpoint."""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from shared.registry import node_ids

MeshPurpose = Literal["problem_solving", "compliance", "bid_support", "learning", "career_mobility", "inspection"]
ExposureMode = Literal["MD", "SUM", "RAG", "LIVE"]


def check_node_list(nodes: list[str] | None) -> list[str] | None:
    if nodes is None:
        return None
    unknown = set(nodes) - set(node_ids())
    if unknown:
        raise ValueError(f"Unknown subsidiary node: {', '.join(sorted(unknown))}")
    if len(set(nodes)) != len(nodes):
        raise ValueError("Node selection cannot contain duplicates")
    return nodes


class MeshQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    nodes: list[str] | None = Field(default=None, min_length=1, max_length=16)
    purpose: MeshPurpose
    mode: ExposureMode | None = None
    as_of: date | None = None

    @field_validator("nodes")
    @classmethod
    def nodes_must_be_registered_and_unique(cls, nodes: list[str] | None) -> list[str] | None:
        return check_node_list(nodes)


class MeshNodeResponse(BaseModel):
    node_id: str
    status: str
    results: list[dict] = Field(default_factory=list)
    withheld: list[dict] = Field(default_factory=list)
    error: str | None = None


class MeshQueryResponse(BaseModel):
    schema_version: str = "1.0"
    question: str
    purpose: MeshPurpose
    status: Literal["ok", "partial", "needs_node_choice"]
    answer: str | None = None
    answer_status: str = "evidence_only"
    answer_reason: str | None = None
    citations: list[str] = Field(default_factory=list)
    checks: list[dict] = Field(default_factory=list)
    cached: bool = False
    routing: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list)
    also_found: list[dict] = Field(default_factory=list)
    relationships: list[dict] = Field(default_factory=list)
    proposed_relationships: list[dict] = Field(default_factory=list)
    omitted: int = 0
    model_calls: list[dict] = Field(default_factory=list)
    trace_id: str | None = None
    steps: list[dict] = Field(default_factory=list)
    node_results: list[MeshNodeResponse]
    sources: list[dict]
    withheld: list[dict]
