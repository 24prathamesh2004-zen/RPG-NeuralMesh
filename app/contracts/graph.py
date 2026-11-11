"""Graph record contract, schema_version 1.0: the one shape of a node and of an edge, whatever the input format.

Every adapter produces these two records. The validator checks them against the graph rules of the domain
(config/graph/*.yaml). The loader writes them to the store. The shape holds nothing about a purpose: the kinds of
node and edge a domain allows live in its rules file, not here.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = "1.0"
ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*:[A-Za-z0-9][A-Za-z0-9._/#-]*$")
EdgeStatus = Literal["proposed", "approved", "rejected", "retired"]
Method = Literal["authored", "imported", "extracted", "computed"]


class Provenance(BaseModel):
    method: Method
    by_role: str
    created_at: str | None = None
    evidence: list[str] = Field(default_factory=list)


class GraphNode(BaseModel):
    id: str
    type: str
    label: str
    aliases: list[str] = Field(default_factory=list)
    description: str | None = None
    owner: str | None = None
    sensitivity: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    external_refs: list[dict[str, str]] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_shape(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError(f"id {value!r} is not <namespace>:<local>")
        return value

    @property
    def namespace(self) -> str:
        return self.id.split(":", 1)[0]


class GraphEdge(BaseModel):
    id: str
    type: str
    from_id: str = Field(alias="from")
    to_id: str = Field(alias="to")
    status: EdgeStatus = "approved"
    provenance: Provenance
    properties: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    approvals: list[dict[str, Any]] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @field_validator("from_id", "to_id")
    @classmethod
    def _end_shape(cls, value: str) -> str:
        if not ID_PATTERN.fullmatch(value):
            raise ValueError(f"edge end {value!r} is not <namespace>:<local>")
        return value

    def as_store_row(self) -> dict[str, Any]:
        """The dict the graph store writes."""
        return {"id": self.id, "type": self.type, "from": self.from_id, "to": self.to_id, "status": self.status,
                "properties": {**self.properties, **({"confidence": self.confidence} if self.confidence is not None else {})},
                "provenance": self.provenance.model_dump(exclude_none=True), "approvals": self.approvals}


def json_schema() -> dict[str, Any]:
    """The schema both sides of an exchange can test against (SkillForge, Snap and Score, a CSV sender)."""
    return {"schema_version": SCHEMA_VERSION, "node": GraphNode.model_json_schema(), "edge": GraphEdge.model_json_schema(by_alias=True)}


def write_json_schema(path: Path) -> None:
    path.write_text(json.dumps(json_schema(), indent=2) + "\n", encoding="utf-8")
