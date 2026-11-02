"""Request and response contracts for the central mesh query endpoint."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field, field_validator

MeshNodeId = Literal["ceat", "kec", "zensar", "harrisons"]
MeshPurpose = Literal["problem_solving", "compliance", "bid_support"]
ExposureMode = Literal["MD", "SUM", "RAG", "LIVE"]


class MeshQueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    nodes: list[MeshNodeId] = Field(min_length=1, max_length=4)
    purpose: MeshPurpose
    mode: ExposureMode | None = None
    as_of: date | None = None

    @field_validator("nodes")
    @classmethod
    def nodes_must_be_unique(cls, nodes: list[MeshNodeId]) -> list[MeshNodeId]:
        if len(set(nodes)) != len(nodes):
            raise ValueError("Node selection cannot contain duplicates")
        return nodes


class MeshNodeResponse(BaseModel):
    node_id: MeshNodeId
    status: str
    results: list[dict] = Field(default_factory=list)
    withheld: list[dict] = Field(default_factory=list)
    error: str | None = None


class MeshQueryResponse(BaseModel):
    question: str
    purpose: MeshPurpose
    status: Literal["ok", "partial"]
    answer: str | None = None
    node_results: list[MeshNodeResponse]
    sources: list[dict]
    withheld: list[dict]