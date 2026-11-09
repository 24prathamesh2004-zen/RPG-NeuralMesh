"""The tool catalogue: every context tool declared once, with its input schema, data schema, purposes and handler (plan 2.5).

A handler is a generic operation (entity, related, similar, live, ask, import), which works on any domain through the
graph rules, or a named plugin for a tool with its own rules (role_context, learning_sources, the inspection tools).
Every handler returns a ToolResult. The dispatcher (services/context_dispatch.py) turns it into the one answer of the
contract, and the published bundle (bundle()) is generated from this file, so the code and the contract cannot differ.
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from contracts.context import (CONTRACT_VERSION, PROBLEM_CODES, STATUSES, SUPPORTED_VERSIONS, Choice, ContextAnswer,
                               ContextRequest, Problem, Suggestion, problem)
from services import context_api, context_tools, mesh_query
from services.context.pii import strip_contact_details
from services.context_api import EndUser, NotFound
from shared.registry import node_ids

Level = Literal["L", "M", "A"]
UNAVAILABLE = frozenset({"NODE_UNAVAILABLE", "AUTHENTICATION_FAILED"})
SUGGEST_MAX = 3
SUGGEST_MIN_SCORE = 0.5
NEVER_SUGGESTED = frozenset({"Document", "Datapoint", "Expert", "Inspection", "Unknown"})


# ── what a handler gets and returns ─────────────────────────────────────────
@dataclass
class CallContext:
    rt: Any
    app: Any                    # services.applications.Application
    purpose: str
    user: EndUser | None        # None for a service call
    trace_id: str

    def visible(self, node_id: str) -> bool:
        """Whether this call may see the entity: a live entity of a type on the application's read list, a document or
        datapoint only when its datapoint allows the purpose of the call (plan 2.1), and an entity of a never-leave
        datapoint only for a person of the company that holds it."""
        g = self.rt.mesh.graph
        d = g.nodes.get(node_id)
        if not d or d.get("retired") or d.get("type") == "Unknown":
            return False
        kind = d.get("type")
        if self.app.reads and kind not in self.app.reads:
            return False
        if kind == "Document" and self.purpose not in (g.nodes.get(d.get("datapoint"), {}).get("purposes_allowed") or []):
            return False
        if kind == "Datapoint" and self.purpose not in (d.get("purposes_allowed") or []):
            return False
        return not self.never_leave_hidden(node_id)

    def never_leave_hidden(self, node_id: str) -> bool:
        """An entity of a never-leave datapoint of another company, or any such entity for a service call."""
        owner = self.rt.mesh.never_leave_owner(node_id)
        return owner is not None and (self.user is None or self.user.company != owner)


class InputProblem(ValueError):
    """A handler's own finding that the caller's input cannot be served. The dispatcher answers invalid_input. Any
    other error of a handler is NeuralMesh's fault and answers service_unavailable, with nothing internal shown."""


@dataclass
class ToolResult:
    status: str = "ok"
    records: list[dict[str, Any]] = field(default_factory=list)
    answer: dict[str, Any] | None = None
    also_found: list[str] = field(default_factory=list)
    omitted: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    problem: Problem | None = None


def refused(code: str, detail: str, status: str | None = None, **extra: Any) -> ToolResult:
    from contracts.context import answer_status_of
    return ToolResult(status=status or answer_status_of(code) or "refused", problem=problem(code, detail, **extra))


# ── input models: one per tool, unknown fields refused so a typo is named ──
class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoleContextIn(_In):
    role: str | None = Field(default=None, max_length=200, description="The role's id, for example ceat:role/quality-engineer")
    title: str | None = Field(default=None, max_length=200, description="A role title, used with company when the id is not known")
    company: str | None = Field(default=None, max_length=40, description="The company id of the title, for example ceat")

    @model_validator(mode="after")
    def _one_way(self) -> "RoleContextIn":
        if not self.role and not (self.title and self.company):
            raise ValueError("give role, or title and company")
        return self


class SkillIn(_In):
    skill: str = Field(min_length=1, max_length=200, description="A skill id (skill:quality-management) or the skill's name")


class SkillLevelIn(SkillIn):
    level: Level | None = Field(default=None, description="The level asked for: L, M or A")


class LearningIn(SkillIn):
    level: Level = Field(description="The level the learner has to reach: L, M or A")


class AskContextIn(_In):
    asset: str = Field(min_length=1, max_length=200)
    conditions: list[str] = Field(default_factory=list, max_length=50)
    grade: str | None = Field(default=None, max_length=50)


class AskIn(_In):
    question: str = Field(min_length=3, max_length=2000)
    nodes: list[str] | None = Field(default=None, max_length=10, description="Companies to ask. Empty: NeuralMesh routes the question")
    context: AskContextIn | None = None


class NoInput(_In):
    pass


class IdIn(_In):
    id: str = Field(min_length=1, max_length=200)


class RelatedIn(IdIn):
    edge_types: list[str] | None = Field(default=None, max_length=20)
    group: str | None = Field(default=None, max_length=40)
    depth: int = Field(default=1, ge=1, le=2)


class SimilarIn(IdIn):
    k: int = Field(default=5, ge=1, le=20)


class LiveIn(IdIn):
    fact: str = Field(default="cover_status", min_length=1, max_length=60)


class AssetIn(_In):
    asset: str = Field(min_length=1, max_length=200)


class RecordInspectionIn(_In):
    inspection_id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    asset: str = Field(min_length=1, max_length=200)
    grade: str | None = Field(default=None, max_length=50)
    conditions: list[str] = Field(default_factory=list, max_length=50)
    review_status: str | None = Field(default=None, max_length=40)
    defect_area_pct: float | None = Field(default=None, ge=0, le=100)
    inspected_at: str | None = Field(default=None, max_length=40)
    image_ref: str | None = Field(default=None, max_length=300)


class ImportIn(_In):
    packs: list[dict[str, Any]] = Field(min_length=1, max_length=20, description="Knowledge packs the registry allows this application to send")


# ── data models: what each tool puts in data, open to fields a minor version adds ─
class _Data(BaseModel):
    model_config = ConfigDict(extra="allow")


class Ref(_Data):
    id: str
    type: str | None = None
    label: str


class SimilarRole(_Data):
    id: str
    label: str
    subsidiary: str
    shared_skill_share: float


class RequiredSkill(_Data):
    skill: str
    label: str
    level: str | None = None
    importance: str | None = None
    concepts: list[dict[str, Any]] = Field(default_factory=list)
    documents: int = 0
    consented_experts: int = 0


class RoleContextData(_Data):
    role: str
    label: str
    subsidiary: str
    required_skills: list[RequiredSkill]
    similar_roles: list[SimilarRole]


class SkillContextData(_Data):
    skill: str
    label: str
    description: str | None = None
    aliases: list[str] = Field(default_factory=list)
    broader: list[str] = Field(default_factory=list)
    related: list[str] = Field(default_factory=list)
    concepts: list[dict[str, Any]] = Field(default_factory=list)
    roles_requiring: list[dict[str, Any]] = Field(default_factory=list)
    documents_total: int = 0
    consented_experts: list[dict[str, Any]] = Field(default_factory=list)
    not_released: list[dict[str, Any]] = Field(default_factory=list)


class LearningData(_Data):
    skill: str
    level: str
    not_released: list[dict[str, Any]] = Field(default_factory=list)
    dropped: list[dict[str, Any]] = Field(default_factory=list)


class MentorsData(_Data):
    skill: str
    note: str


class VocabularyEntity(_Data):
    id: str
    type: str
    label: str | None = None
    aliases: list[str] = Field(default_factory=list)


class VocabularyData(_Data):
    format: str
    pack: dict[str, Any]
    entities: list[VocabularyEntity]
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    embedding_model: str | None = None


class AskData(_Data):
    question: str
    answer_status: str
    answer_reason: str | None = None
    citations: list[Any] = Field(default_factory=list)
    checks: list[Any] = Field(default_factory=list)
    routing: dict[str, Any] = Field(default_factory=dict)
    relationships: list[dict[str, Any]] = Field(default_factory=list)
    withheld: list[dict[str, Any]] = Field(default_factory=list)
    also_found_records: list[dict[str, Any]] = Field(default_factory=list)
    contact_details_removed: int = 0


class EntityData(_Data):
    id: str
    type: str | None = None
    label: str
    layer: str | None = None
    owner: str | None = None
    retired: bool = False
    aliases: list[str] = Field(default_factory=list)
    properties: dict[str, Any] = Field(default_factory=dict)
    connections: dict[str, int] = Field(default_factory=dict)


class RelatedData(_Data):
    entity: Ref
    depth: int
    related: dict[str, list[dict[str, Any]]]


class SimilarData(_Data):
    entity: Ref
    similar: list[dict[str, Any]]
    note: str | None = None


class LiveData(_Data):
    entity: Ref
    fact: str
    decision: str | None = None
    value: Any = None


class InspectionProfileData(_Data):
    asset: Ref
    owner: str | None = None
    views: list[dict[str, Any]] = Field(default_factory=list)
    conditions: list[dict[str, Any]] = Field(default_factory=list)
    grade_scale: dict[str, Any] | None = None
    expected_cover: list[dict[str, Any]] = Field(default_factory=list)
    standards: list[dict[str, Any]] = Field(default_factory=list)


class InspectionHistoryData(_Data):
    asset: Ref
    inspections: list[dict[str, Any]]


class RecordInspectionData(_Data):
    accepted: bool
    inspection: str
    asset: str
    edges: int
    revision: int


class PackResult(_Data):
    pack_id: str
    kept_as: str | None = None
    result: Literal["loaded", "unchanged", "refused"]
    code: str | None = None
    reason: str | None = None
    roles: int = 0
    skills: int = 0
    requirements: int = 0


class ImportData(_Data):
    packs: list[PackResult]
    revision: int | None = None
    graph: dict[str, Any] = Field(default_factory=dict)


# ── suggestions for an unknown id: by code, never a document ───────────────
def _words(text: str) -> str:
    text = re.sub(r"^[a-z0-9-]+:", "", text.lower())
    text = re.sub(r"^(role|asset|condition|skill|concept)/", "", text)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", text).split())


def _score(wanted: str, names: list[str]) -> float:
    target = _words(wanted)
    if not target:
        return 0.0
    want_tokens = set(target.split())
    best = 0.0
    for name in names:
        cand = _words(name)
        if not cand:
            continue
        tokens = set(cand.split())
        jaccard = len(want_tokens & tokens) / len(want_tokens | tokens)
        best = max(best, difflib.SequenceMatcher(None, target, cand).ratio(), jaccard)
    return best


def suggest(rt: Any, wanted: str, kind: str | None, visible: Callable[[str], bool] | None = None) -> tuple[list[Suggestion], bool | None]:
    """Up to three live entities of the expected kind whose names are close to the unknown id, and whether NeuralMesh
    holds any entity of that kind for the id's company. Documents, datapoints, experts and inspections are never
    suggested, so a suggestion cannot reveal what an owner has not released, and an entity the caller may not read
    (services/applications reads) is never suggested either."""
    g = rt.mesh.graph
    namespace = wanted.split(":", 1)[0] if ":" in wanted else None
    scored, loaded = [], False
    for node_id, d in g.nodes(data=True):
        node_type = d.get("type")
        if d.get("retired") or node_type in NEVER_SUGGESTED or (kind and node_type != kind) or (visible and not visible(node_id)):
            continue
        if namespace and node_id.split(":", 1)[0] == namespace:
            loaded = True
        names = [node_id, d.get("label") or "", *(d.get("aliases") or [])]
        score = _score(wanted, names)
        if namespace and node_id.split(":", 1)[0] == namespace:
            score = min(1.0, score + 0.05)
        if score >= SUGGEST_MIN_SCORE:
            scored.append(Suggestion(id=node_id, label=d.get("label") or node_id, score=round(score, 2)))
    scored.sort(key=lambda s: (-s.score, s.id))
    return scored[:SUGGEST_MAX], (loaded if kind and namespace else None)


def not_found(ctx: CallContext, wanted: str, kind: str | None) -> ToolResult:
    suggestions, loaded = suggest(ctx.rt, wanted, kind, ctx.visible)
    what = (kind or "entity").lower()
    detail = f"NeuralMesh holds no {what} {wanted}."
    if loaded is False:
        detail += f" It holds no {what} of {wanted.split(':', 1)[0]} at all."
    return refused("not_found", detail, suggestions=suggestions, loaded=loaded)


def connected_choices(rt: Any) -> list[Choice]:
    g = rt.mesh.graph
    return [Choice(id=n, label=(g.nodes.get(f"org:{n}", {}).get("label") or n)) for n in node_ids()]


# ── status from what was released and what was withheld ─────────────────────
def released_status(records: list[dict[str, Any]], withheld: list[dict[str, Any]]) -> tuple[str, Problem | None]:
    down = sorted({w.get("node") or w.get("evidence_id", "").split(":", 1)[0] for w in withheld if w.get("decision") in UNAVAILABLE})
    rules = sorted({f"{w.get('rule_id')} ({w.get('node') or w.get('evidence_id', '').split(':', 1)[0]})"
                    for w in withheld if w.get("decision") not in UNAVAILABLE and w.get("rule_id")})
    if down:
        return "partial", problem("node_unavailable", "No answer from " + ", ".join(down) + ".",
                                  choices=[Choice(id=n, label=n) for n in down])
    if records:
        return "ok", None
    if withheld:
        return "blocked", problem("not_released", "Withheld by the owners' rules: " + (", ".join(rules) or "no rule named") + ".")
    return "no_evidence", None


# ── handlers ────────────────────────────────────────────────────────────────
async def h_role_context(ctx: CallContext, inp: RoleContextIn) -> ToolResult:
    try:
        out = context_api.role_context(ctx.rt, inp.role, inp.title, inp.company)
    except NotFound as exc:
        return not_found(ctx, str(exc), "Role")
    out.pop("schema_version", None)
    out["similar_roles"] = [{"id": r["role"], "label": r["label"], "subsidiary": r["subsidiary"],
                             "shared_skill_share": r["shared_skill_share"]} for r in out["similar_roles"]]
    return ToolResult(data=out)


async def h_skill_context(ctx: CallContext, inp: SkillLevelIn) -> ToolResult:
    try:
        out = await context_api.skill_context(ctx.rt, ctx.user, inp.skill, inp.level, ctx.purpose)
    except NotFound as exc:
        return not_found(ctx, str(exc), "Skill")
    out.pop("schema_version", None)
    records = out.pop("evidence")
    status, prob = released_status(records, out["not_released"])
    return ToolResult(status=status, records=records, data=out, problem=prob)


async def h_learning_sources(ctx: CallContext, inp: LearningIn) -> ToolResult:
    try:
        out = await context_api.learning_sources(ctx.rt, ctx.user, inp.skill, inp.level)
    except NotFound as exc:
        return not_found(ctx, str(exc), "Skill")
    records = out["sources"]
    status, prob = released_status(records, out["not_released"])
    return ToolResult(status=status, records=records, problem=prob,
                      data={"skill": out["skill"], "level": out["target_level"], "not_released": out["not_released"], "dropped": out["dropped"]})


async def h_find_mentors(ctx: CallContext, inp: SkillIn) -> ToolResult:
    try:
        out = context_api.find_mentors(ctx.rt, inp.skill)
    except NotFound as exc:
        return not_found(ctx, str(exc), "Skill")
    for mentor in out["mentors"]:  # the evidence of an expert never names a never-leave document of another company
        expert = mentor.get("expert") or {}
        expert["evidence"] = [doc for doc in expert.get("evidence", []) if not ctx.never_leave_hidden(doc)]
    return ToolResult(status="ok" if out["mentors"] else "no_evidence", records=out["mentors"],
                      data={"skill": out["skill"], "note": out["note"]})


async def h_vocabulary_export(ctx: CallContext, inp: NoInput) -> ToolResult:
    return ToolResult(data=context_api.vocabulary_export(ctx.rt))


async def h_ask(ctx: CallContext, inp: AskIn) -> ToolResult:
    unknown = sorted(set(inp.nodes or []) - set(node_ids()))
    group = [n for n in unknown if n in ctx.app.companies]
    if group:
        return refused("company_not_connected", f"{', '.join(group)} {'has' if len(group) == 1 else 'have'} no Mesh Node yet.",
                       fields=[{"field": "input.nodes", "problem": f"{n} has no Mesh Node", "allowed": list(node_ids())} for n in group],
                       choices=connected_choices(ctx.rt))
    if unknown:
        return refused("invalid_input", f"{', '.join(unknown)} {'is' if len(unknown) == 1 else 'are'} not a connected company.",
                       fields=[{"field": "input.nodes", "problem": "not a connected company", "allowed": list(node_ids())}])
    question, removed = strip_contact_details(inp.question)
    rt = ctx.rt
    result = await mesh_query.run_query(mesh_query.graph_for(rt.orchestrator), question=question, purpose=ctx.purpose,
                                        nodes=inp.nodes or None, mode=None, as_of=None, user_assertion=ctx.user.assertion(),
                                        company=ctx.user.company, roles=list(ctx.user.roles),
                                        context=inp.context.model_dump() if inp.context else None)
    data = {"question": result.get("question", question), "answer_status": result.get("answer_status", "evidence_only"),
            "answer_reason": result.get("answer_reason"), "citations": result.get("citations", []), "checks": result.get("checks", []),
            "routing": result.get("routing", {}), "relationships": result.get("relationships", []),
            "withheld": result.get("withheld", []), "also_found_records": result.get("also_found", []),
            "contact_details_removed": int(removed or 0)}
    if result.get("status") == "needs_node_choice":
        return ToolResult(status="needs_input", data=data, problem=problem(
            "needs_choice", "The question matches no company. Ask again naming one of the connected companies, or send input.nodes.",
            choices=connected_choices(rt)))
    records = result.get("evidence", [])
    text = result.get("answer")
    answer = {"text": text, "check": "passed" if data["answer_status"] == "answered" else "failed"} if text else None
    also = sorted({r.get("node") for r in result.get("also_found", []) if r.get("node")})
    down = [n["node_id"] for n in result.get("node_results", []) if n.get("status") in UNAVAILABLE]
    withheld = result.get("withheld", []) + [{"node": n, "decision": "NODE_UNAVAILABLE"} for n in down]
    status, prob = released_status(records if (records or text) else [], withheld)
    return ToolResult(status=status, records=records, answer=answer, also_found=also, omitted=int(result.get("omitted", 0) or 0),
                      data=data, problem=prob)


async def h_entity(ctx: CallContext, inp: IdIn) -> ToolResult:
    try:
        out = context_tools.entity(ctx.rt, inp.id, ctx.visible)
    except NotFound as exc:
        return not_found(ctx, str(exc), None)
    out.pop("schema_version", None)
    return ToolResult(data=out)


async def h_related(ctx: CallContext, inp: RelatedIn) -> ToolResult:
    try:
        out = context_tools.related(ctx.rt, inp.id, inp.edge_types, inp.group, inp.depth, visible=ctx.visible)
    except NotFound as exc:
        return not_found(ctx, str(exc), None)
    out.pop("schema_version", None)
    return ToolResult(data=out)


async def h_similar(ctx: CallContext, inp: SimilarIn) -> ToolResult:
    try:
        out = context_tools.similar(ctx.rt, inp.id, inp.k, ctx.visible)
    except NotFound as exc:
        return not_found(ctx, str(exc), None)
    out.pop("schema_version", None)
    return ToolResult(data=out)


async def h_live(ctx: CallContext, inp: LiveIn) -> ToolResult:
    try:
        out = await context_tools.live(ctx.rt, ctx.user, inp.id, inp.fact)
    except NotFound as exc:
        return not_found(ctx, str(exc), None)
    out.pop("schema_version", None)
    decision = out.get("decision")
    if decision == "NODE_UNKNOWN":
        return ToolResult(status="refused", data=out, problem=problem(
            "company_not_connected", f"The owner of {out['entity']['id']} has no Mesh Node, so the live fact cannot be asked."))
    if decision in UNAVAILABLE:
        return ToolResult(status="partial", data=out, problem=problem("node_unavailable", f"No answer from {out.get('node') or 'the owner'}."))
    if decision and decision.startswith("BLOCKED"):
        return ToolResult(status="blocked", data=out, problem=problem("not_released", f"Withheld by the owner's rule {out.get('rule_id')}."))
    return ToolResult(data=out)


async def h_inspection_profile(ctx: CallContext, inp: AssetIn) -> ToolResult:
    try:
        out = context_tools.inspection_profile(ctx.rt, inp.asset, ctx.visible)
    except NotFound as exc:
        return not_found(ctx, str(exc), "Asset")
    out.pop("schema_version", None)
    return ToolResult(data=out)


async def h_inspection_history(ctx: CallContext, inp: AssetIn) -> ToolResult:
    try:
        out = context_tools.history(ctx.rt, inp.asset)
    except NotFound as exc:
        return not_found(ctx, str(exc), "Asset")
    out.pop("schema_version", None)
    return ToolResult(status="ok" if out["inspections"] else "no_evidence", data=out)


async def h_record_inspection(ctx: CallContext, inp: RecordInspectionIn) -> ToolResult:
    try:
        out = await asyncio.to_thread(context_tools.record_inspection, ctx.rt, ctx.user, inp.model_dump())
    except NotFound as exc:
        return not_found(ctx, str(exc), "Asset")
    if not out["accepted"]:
        return refused("invalid_input", "The inspection was not recorded.",
                       fields=[{"field": "input", "problem": e} for e in out["errors"][:10]])
    return ToolResult(data=out)


async def h_import(ctx: CallContext, inp: ImportIn) -> ToolResult:
    from services import context_import
    return await context_import.import_packs(ctx, inp.packs)


# ── the catalogue ───────────────────────────────────────────────────────────
Handler = Callable[[CallContext, Any], Awaitable[ToolResult]]


@dataclass(frozen=True)
class ToolSpec:
    name: str
    summary: str
    kind: Literal["generic", "plugin"]
    caller: Literal["person", "service", "either"]   # person: needs the end user's identity and a connected company
    input_model: type[BaseModel]
    data_model: type[BaseModel]
    handler: Handler
    purposes: tuple[str, ...] | None = None          # None: any purpose of the application
    records: str = "none"                            # what records holds

    def describe(self) -> dict[str, Any]:
        return {"summary": self.summary, "kind": self.kind, "caller": self.caller,
                "purposes": list(self.purposes) if self.purposes else "any purpose of the application",
                "records": self.records, "input": self.input_model.model_json_schema(), "data": self.data_model.model_json_schema()}


CATALOGUE: dict[str, ToolSpec] = {s.name: s for s in [
    ToolSpec("role_context", "Required skills of a role with levels, concepts, document and expert counts, and similar roles elsewhere",
             "plugin", "either", RoleContextIn, RoleContextData, h_role_context),
    ToolSpec("skill_context", "A skill with its description, aliases, related skills, roles that require it and released evidence",
             "plugin", "person", SkillLevelIn, SkillContextData, h_skill_context, records="released evidence records"),
    ToolSpec("learning_sources", "Study documents other companies allow for learning that reach the level, by reference",
             "plugin", "person", LearningIn, LearningData, h_learning_sources, purposes=("learning",), records="released study documents"),
    ToolSpec("find_mentors", "Consented experts of a skill, without names", "plugin", "either", SkillIn, MentorsData, h_find_mentors,
             records="expert records"),
    ToolSpec("vocabulary_export", "The group vocabulary of skills and concepts with aliases, as one pack", "plugin", "service",
             NoInput, VocabularyData, h_vocabulary_export, purposes=("career_mobility",)),
    ToolSpec("ask", "A written answer from cited documents, checked sentence by sentence, with the evidence records",
             "generic", "person", AskIn, AskData, h_ask, records="the evidence of the answer"),
    ToolSpec("entity", "One entity of the context graph", "generic", "either", IdIn, EntityData, h_entity),
    ToolSpec("related", "Neighbours of an entity grouped by link type, one or two hops", "generic", "either", RelatedIn, RelatedData, h_related),
    ToolSpec("similar", "Computed SIMILAR_TO neighbours with reason and score", "generic", "either", SimilarIn, SimilarData, h_similar),
    ToolSpec("live", "A fact that is never stored, asked of the owning node now with the user's identity", "generic", "person",
             LiveIn, LiveData, h_live, purposes=("inspection",)),
    ToolSpec("inspection_profile", "Conditions, views, grade scale, expected cover and governing standards of an asset", "plugin",
             "either", AssetIn, InspectionProfileData, h_inspection_profile),
    ToolSpec("inspection_history", "Past inspections of an asset, newest first", "plugin", "either", AssetIn, InspectionHistoryData,
             h_inspection_history),
    ToolSpec("record_inspection", "Record one inspection as an event in the graph. Images stay with the application", "plugin",
             "person", RecordInspectionIn, RecordInspectionData, h_record_inspection, purposes=("inspection",)),
    ToolSpec("import", "Send packs the registry allows. Each pack is loaded, unchanged or refused with its reason", "generic",
             "service", ImportIn, ImportData, h_import),
]}


# ── the published bundle (plan 2.7) ─────────────────────────────────────────
def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def bundle() -> dict[str, Any]:
    """The contract as one document: version, request, answer, problem codes and every tool's input and data schema,
    with the SHA-256 hash of its own content (the hash field excluded)."""
    body = {
        "contract": "rpg-neuralmesh.context",
        "version": CONTRACT_VERSION,
        "supported_versions": list(SUPPORTED_VERSIONS),
        "endpoint": "POST /api/v1/context/{tool}",
        "statuses": list(STATUSES),
        "problem_codes": {code: {"http": h, "status": s, "title": t} for code, (h, s, t) in PROBLEM_CODES.items()},
        "rules": [
            "data follows the tool's data schema when the status is ok, partial, no_evidence or blocked",
            "a reader ignores fields it does not know and logs an unknown problem code by its title",
            "the six statuses are fixed within a major version",
        ],
        "request": ContextRequest.model_json_schema(),
        "answer": ContextAnswer.model_json_schema(),
        "tools": {name: spec.describe() for name, spec in sorted(CATALOGUE.items())},
    }
    return {**body, "sha256": hashlib.sha256(_canonical(body).encode("utf-8")).hexdigest()}
