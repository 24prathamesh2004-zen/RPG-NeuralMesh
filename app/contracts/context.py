"""Context contract, version 1.0: one request, one answer and one refusal for every tool and every application.

The plan is planning_docs/RPG_NeuralMesh_Generic_Context_Delivery_Standard_Plan.md. An application sends a request
envelope to POST /api/v1/context/<tool> (or calls the same tool on the MCP gateway) and gets a ContextAnswer back.
A call NeuralMesh refuses because of the caller's identity or envelope gets an HTTP error status with a Problem as
the body. A call refused because of a value (an unknown id, a missing company choice, a wrong field) is a normal
answer with a status and a Problem, so the caller can say what is needed. The published schemas are generated from
these models and the tool catalogue (services/context_catalogue.py), never written by hand.
"""
from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from contracts.evidence import EvidenceRecord

CONTRACT_VERSION = "1.1"
SUPPORTED_VERSIONS = ("1.0", "1.1")  # 1.1 adds the problem code unauthenticated and closes the answer and problem objects
SUPPORTED_MAJORS = frozenset(v.split(".")[0] for v in SUPPORTED_VERSIONS)
PROBLEM_TYPE = "urn:rpg-neuralmesh:problem:"

Status = Literal["ok", "partial", "no_evidence", "blocked", "needs_input", "refused"]
STATUSES: tuple[str, ...] = get_args(Status)

# code: (HTTP status, answer status, title). An HTTP status other than 200 means the problem is the whole body.
PROBLEM_CODES: dict[str, tuple[int, str | None, str]] = {
    "unauthenticated": (401, None, "The service token is missing, invalid or expired"),
    "unsupported_version": (400, None, "The contract version is not served"),
    "not_an_envelope": (400, None, "The body is not a request envelope"),
    "tool_mismatch": (400, None, "The path and the body name different tools"),
    "unknown_tool": (404, None, "No such tool"),
    "not_allowed": (403, None, "This application may not make this call"),
    "service_unavailable": (503, None, "NeuralMesh could not complete the call"),
    "invalid_input": (200, "refused", "An input field is missing or wrong"),
    "not_found": (200, "refused", "The id is not in the context graph"),
    "company_not_connected": (200, "refused", "The caller's company has no Mesh Node"),
    "needs_choice": (200, "needs_input", "A choice is needed"),
    "not_released": (200, "blocked", "The owners released nothing for this purpose"),
    "node_unavailable": (200, "partial", "At least one company did not answer"),
    "pack_refused": (200, None, "At least one pack was not loaded"),
}


class Caller(BaseModel):
    """Who the call is for: the end user's company and roles in the application, or the group for a service call."""
    model_config = ConfigDict(extra="forbid")

    subsidiary: str = Field(pattern=r"^[a-z][a-z0-9-]{0,39}$")
    roles: list[str] = Field(min_length=1, max_length=10)
    user_ref: str | None = Field(default=None, min_length=1, max_length=120)


class ContextRequest(BaseModel):
    """The one request envelope. Fields a newer minor version adds are ignored, the tool's input is checked by the tool."""
    model_config = ConfigDict(extra="ignore")

    schema_version: str = Field(pattern=r"^\d+\.\d+$")
    tool: str = Field(pattern=r"^[a-z][a-z_]{0,59}$")
    purpose: str = Field(min_length=1, max_length=40)
    caller: Caller
    input: dict[str, Any] = Field(default_factory=dict)


class ProblemField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    problem: str
    allowed: list[str] | None = None


class Choice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str


class Suggestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    label: str
    score: float


class Problem(BaseModel):
    """Why a call was refused and what is needed. Field names follow RFC 9457 (type, title, status, detail)."""
    model_config = ConfigDict(extra="forbid")

    type: str
    code: str
    title: str
    detail: str | None = None
    status: int | None = None  # set only when the problem is the body of an HTTP error
    fields: list[ProblemField] = Field(default_factory=list)
    choices: list[Choice] = Field(default_factory=list)
    suggestions: list[Suggestion] = Field(default_factory=list)
    loaded: bool | None = None
    allowed: dict[str, list[str]] | None = None


class AnswerText(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    check: Literal["passed", "failed"]


class ContextAnswer(BaseModel):
    """The one answer of every tool. Its own fields are closed: a field outside this list is never sent."""
    model_config = ConfigDict(extra="forbid")

    schema_version: str = CONTRACT_VERSION
    tool: str
    status: Status
    records: list[EvidenceRecord] = Field(default_factory=list)
    answer: AnswerText | None = None
    also_found: list[str] = Field(default_factory=list)
    omitted: int = Field(default=0, ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
    problem: Problem | None = None
    trace_id: str


def problem(code: str, detail: str | None = None, *, http: bool = False, **extra: Any) -> Problem:
    """A Problem of one of the fixed codes. http=True sets the status field, for a problem sent as an HTTP error body."""
    status, _, title = PROBLEM_CODES[code]
    return Problem(type=PROBLEM_TYPE + code, code=code, title=title, detail=detail, status=status if http else None, **extra)


def answer_status_of(code: str) -> str | None:
    return PROBLEM_CODES[code][1]


def http_status_of(code: str) -> int:
    return PROBLEM_CODES[code][0]
