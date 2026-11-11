"""Central LangGraph orchestrator over the independent subsidiary MCP servers.

Steps: resolve, route, fan out, scope, expand, build, answer, check (plan v2, section 3.6). The answer model reads
evidence records only. When no approved model can run, the response carries the evidence and citations alone.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict
from urllib.parse import urlsplit

import jwt
from jwt import PyJWTError as JWTError
from langgraph.graph import END, StateGraph
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from api.auth import API_AUDIENCE, POC_ISSUER, issue_poc_token
from contracts.evidence import EvidenceRecord
from services.context import builder, check, prompts, records, scoping
from services.context.answer import PROMPT_VERSION, answer as write_answer
from services.context.cache import ANSWER_CACHE, RERANK_CACHE, bundle_key, rerank_key
from services.context.llm import ChatBackend, make_caller
from services.context.pii import strip_contact_details
from services.context.policy import choice_for
from observability import tracing
from services.mesh_graph import MeshGraph
from shared.config import Settings
from shared.registry import node_ids, registered_nodes

NODE_IDS = node_ids()
MESH_SERVICE_ROLE = "mesh_service"



class NodeTokenProvider(Protocol):
    async def token_for_node(self, user_assertion: str, node_id: str) -> str: ...


class NodeTransport(Protocol):
    async def search(self, url: str, token: str, *, query: str, purpose: str, mode: str | None,
                     as_of: str | None) -> dict[str, Any]: ...

    async def call_tool(self, url: str, token: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class NodeTokenError(Exception):
    pass


class PocNodeTokenProvider:
    def __init__(self, settings: Settings, node_urls: dict[str, str] | None = None) -> None:
        self.settings = settings
        self.node_urls = node_urls or {n.node_id: n.url for n in registered_nodes()}

    def _audience(self, node_id: str) -> str:
        url = self.node_urls.get(node_id)
        if not url:
            raise NodeTokenError("No endpoint is configured for this node")
        parts = urlsplit(url)
        return f"{parts.scheme}://{parts.netloc}"

    async def token_for_node(self, user_assertion: str, node_id: str) -> str:
        audience = self._audience(node_id)
        try:
            user = jwt.decode(user_assertion, self.settings.app_secret_key, algorithms=["HS256"], issuer=POC_ISSUER,
                              audience=API_AUDIENCE, options={"require": ["exp", "sub"]})
        except JWTError as exc:
            raise NodeTokenError("The API session is invalid or expired") from exc
        return issue_poc_token({"sub": user["sub"], "company": user["company"], "roles": user["roles"],
                                "scope": "neuralmesh.query"}, audience=audience, hours=1)

    async def service_token_for_node(self, node_id: str) -> str:
        return issue_poc_token({"sub": "svc:mesh-registry", "company": "group", "roles": [MESH_SERVICE_ROLE],
                                "scope": "neuralmesh.query"}, audience=self._audience(node_id), hours=1)


class MCPNodeTransport:
    async def call_tool(self, url: str, token: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        async with streamablehttp_client(url, headers={"Authorization": f"Bearer {token}"}) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
        if result.isError:
            raise RuntimeError(f"MCP tool {tool} returned an error")
        if isinstance(result.structuredContent, dict):
            return result.structuredContent
        raise RuntimeError(f"MCP tool {tool} returned no structured result")

    async def search(self, url: str, token: str, *, query: str, purpose: str, mode: str | None, as_of: str | None,
                     domains: list[str] | None = None, concepts: list[str] | None = None) -> dict[str, Any]:
        arguments: dict[str, Any] = {"query": query, "purpose": purpose}
        for key, value in (("mode", mode), ("as_of", as_of), ("domains", domains), ("concepts", concepts)):
            if value:
                arguments[key] = value
        return await self.call_tool(url, token, "search", arguments)


MAX_AGGREGATE_VIEWS = 4


def _accepts(fn: Any, name: str) -> bool:
    try:
        return name in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


class MeshQueryState(TypedDict, total=False):
    question: str
    nodes: list[str] | None
    purpose: str
    mode: str | None
    as_of: str | None
    user_assertion: str
    company: str
    roles: list[str]
    trace_id: str
    context: dict[str, Any] | None
    resolved: dict[str, Any]
    routing: dict[str, Any]
    node_results: list[dict[str, Any]]
    records: list[dict[str, Any]]
    withheld_records: list[dict[str, Any]]
    scope: dict[str, Any]
    relationships: dict[str, Any]
    context: dict[str, Any]
    answer: dict[str, Any]
    model_calls: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    withheld: list[dict[str, Any]]
    status: str
    steps: list[dict[str, Any]]


@dataclass
class MeshOrchestrator:
    node_urls: dict[str, str]
    token_provider: NodeTokenProvider
    transport: NodeTransport
    mesh: MeshGraph | None = None
    backend: ChatBackend | None = None
    app_env: str = "development"
    canaries: list[str] = field(default_factory=list)

    # ── resolve and route ───────────────────────────────────────────────────
    async def resolve(self, state: MeshQueryState) -> dict[str, Any]:
        question, removed = strip_contact_details(state["question"])
        if self.mesh is None:
            return {"question": question, "resolved": {"concepts": {}, "named_subsidiaries": [], "contact_details_removed": removed}}
        resolved = self.mesh.resolve(question)
        resolved["contact_details_removed"] = removed
        return {"question": question, "resolved": resolved}

    async def route(self, state: MeshQueryState) -> dict[str, Any]:
        chosen = [n for n in (state.get("nodes") or []) if n in self.node_urls]
        resolved = state.get("resolved", {})
        concepts = sorted(resolved.get("concepts", {}))
        routing: dict[str, Any] = {"concepts": concepts, "concept_labels": {}, "domains": {}, "narrowed_out": [],
                                   "named_subsidiaries": resolved.get("named_subsidiaries", []), "datapoints": []}
        if self.mesh is not None:
            routing["concept_labels"] = {c: self.mesh.label(c) for c in concepts}
        if chosen:
            routing.update(method="user", subsidiaries=chosen)
            if self.mesh is not None and concepts:
                graph_route = self.mesh.route(set(concepts), set(resolved.get("named_subsidiaries", [])))
                routing["domains"] = {k: sorted(v) for k, v in graph_route["domains"].items() if k in chosen}
            return {"routing": routing}
        if self.mesh is not None and concepts:
            graph_route = self.mesh.route(set(concepts), set(resolved.get("named_subsidiaries", [])))
            subs = sorted(s for s in graph_route["subsidiaries"] if s in self.node_urls)
            if state.get("context"):
                from services.context_tools import context_documents
                docs, owners = context_documents(_RuntimeView(self.mesh, self), state["context"])
                subs = sorted(set(subs) | {o for o in owners if o in self.node_urls})
                routing["context_documents"] = sorted(docs)
            if subs:
                routing.update(method="graph", subsidiaries=subs,
                               domains={k: sorted(v) for k, v in graph_route["domains"].items()},
                               narrowed_out=sorted(graph_route["narrowed_out"]),
                               datapoints=sorted(graph_route["datapoints"]),
                               hop_concepts=sorted(graph_route["hop_concepts"]))
                return {"routing": routing}
        named = [n for n in resolved.get("named_subsidiaries", []) if n in self.node_urls]
        if named:
            routing.update(method="named", subsidiaries=named)
            return {"routing": routing}
        if state.get("context") and self.mesh is not None:
            from services.context_tools import context_documents
            docs, owners = context_documents(_RuntimeView(self.mesh, self), state["context"])
            owners = sorted(o for o in owners if o in self.node_urls)
            if owners:
                routing.update(method="context", subsidiaries=owners, context_documents=sorted(docs))
                return {"routing": routing}
        classified = await self._classify(state)
        own = state.get("company") or ""
        if classified["nodes"]:
            routing.update(method="classifier", subsidiaries=classified["nodes"], reason=classified["reason"])
        elif own in self.node_urls:
            # Nothing in the wording points to a company: a question about the asker's own work goes to their company.
            routing.update(method="own", subsidiaries=[own], reason="No company matched the wording, so the asker's own company was asked.")
        else:
            routing.update(method="none", subsidiaries=[], reason=classified["reason"])
        return {"routing": routing}

    async def _classify(self, state: MeshQueryState) -> dict[str, Any]:
        if self.mesh is None or self.backend is None:
            return {"nodes": [], "reason": "No concept matched and no classifier model is configured."}
        profiles = "\n".join(f"- {n}: {p}" for n, p in self.mesh_profiles().items())
        calls: list[dict] = []
        call = make_caller(self.backend, app_env=self.app_env, trace_id=state.get("trace_id", ""),
                           sensitivities={"Internal"}, all_synthetic=True, calls=calls)
        classify_prompt = prompts.load("classify")
        text = await asyncio.to_thread(call, "classify", classify_prompt.text, f"Nodes:\n{profiles}\n\nQuestion: {state['question']}",
                                       classify_prompt.version)
        if text is None:
            return {"nodes": [], "reason": "The classifier could not run."}
        try:
            cleaned = text.strip().strip("`")
            cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
            parsed = json.loads(cleaned)
            nodes = [n for n in parsed.get("nodes", []) if n in self.node_urls]
            return {"nodes": nodes, "reason": str(parsed.get("reason", ""))[:200]}
        except (ValueError, AttributeError):
            return {"nodes": [], "reason": "The classifier reply could not be read."}

    def mesh_profiles(self) -> dict[str, str]:
        if self.mesh is None:
            return {}
        g = self.mesh.graph
        return {n.split(":", 1)[1]: d.get("profile", "") for n, d in g.nodes(data=True)
                if d.get("type") == "Subsidiary" and d.get("profile")}

    # ── fan out ─────────────────────────────────────────────────────────────
    async def fan_out(self, state: MeshQueryState) -> dict[str, Any]:
        nodes = state.get("routing", {}).get("subsidiaries") or state.get("nodes") or []
        responses = await asyncio.gather(*(self._query_node(state, node_id) for node_id in nodes))
        return {"node_results": list(responses)}

    async def _query_node(self, state: MeshQueryState, node_id: str) -> dict[str, Any]:
        url = self.node_urls[node_id]
        try:
            token = await self.token_provider.token_for_node(state["user_assertion"], node_id)
        except NodeTokenError:
            return {"node_id": node_id, "status": "AUTHENTICATION_FAILED", "results": [], "withheld": []}
        except Exception:
            return {"node_id": node_id, "status": "NODE_UNAVAILABLE", "results": [], "withheld": []}
        routing = state.get("routing", {})
        kwargs: dict[str, Any] = {"query": state["question"], "purpose": state["purpose"], "mode": state.get("mode"),
                                  "as_of": state.get("as_of")}
        domains = routing.get("domains", {}).get(node_id)
        concepts = routing.get("concepts", []) + routing.get("hop_concepts", [])
        if domains and _accepts(self.transport.search, "domains"):
            kwargs["domains"] = domains
        if concepts and _accepts(self.transport.search, "concepts"):
            kwargs["concepts"] = concepts
        try:
            with tracing.span("execute_tool search", {"mesh.node": node_id, "gen_ai.tool.name": "search"}):
                response = await self.transport.search(url, token, **kwargs)
            if not isinstance(response, dict):
                raise RuntimeError("Invalid MCP response")
            return {**response, "node_id": node_id}
        except Exception:
            return {"node_id": node_id, "status": "NODE_UNAVAILABLE", "results": [], "withheld": []}

    async def call_node_tool(self, user_assertion: str, node_id: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        with tracing.span(f"execute_tool {tool}", {"mesh.node": node_id, "gen_ai.tool.name": tool}):
            return await self._call_node_tool(user_assertion, node_id, tool, arguments)

    async def _call_node_tool(self, user_assertion: str, node_id: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        url = self.node_urls[node_id]
        token = await self.token_provider.token_for_node(user_assertion, node_id)
        return await self.transport.call_tool(url, token, tool, arguments)

    async def export_node_graph(self, node_id: str) -> dict[str, Any]:
        url = self.node_urls[node_id]
        token = await self.token_provider.service_token_for_node(node_id)  # type: ignore[attr-defined]
        with tracing.span("execute_tool export_graph", {"mesh.node": node_id, "gen_ai.tool.name": "export_graph"}):
            return await self.transport.call_tool(url, token, "export_graph", {})

    # ── scope and expand ────────────────────────────────────────────────────
    def _caller(self, state: MeshQueryState, calls: list[dict], recs: list[EvidenceRecord]):
        if self.backend is None:
            return None
        sens = {r.sensitivity for r in recs if r.sensitivity}
        return make_caller(self.backend, app_env=self.app_env, trace_id=state.get("trace_id", ""), sensitivities=sens,
                           all_synthetic=True, calls=calls)

    async def scope(self, state: MeshQueryState) -> dict[str, Any]:
        released, withheld = records.from_node_results(state.get("node_results", []))
        released = [records.strip_injection(r) for r in released]
        selected, overflow = scoping.select(released)
        calls = list(state.get("model_calls", []))
        key = (rerank_key(state["question"], selected, choice_for("rerank").model, prompts.load("rerank").version)
               if (self.backend and selected) else None)
        stored = RERANK_CACHE.get(key) if key else None
        if stored is not None:
            result = scoping.apply_verdicts(selected, stored)
        else:
            call = self._caller(state, calls, released)
            result = await asyncio.to_thread(scoping.rerank, state["question"], selected, call)
            if key and result.rerank == "done":
                RERANK_CACHE.put(key, result.verdicts)
        if selected and not result.selected:
            kept = dict(list(selected.items())[:3])  # a re-rank is a precision boost, never an empty answer
            for doc in kept:
                result.also_found.pop(doc, None)
            result.selected = kept
            result.rerank += "_all_rejected_kept_top3"
        result.also_found.update(overflow)
        return {
            "records": [r.model_dump() for recs in result.selected.values() for r in recs],
            "withheld_records": [r.model_dump() for r in withheld],
            "scope": {"rerank": result.rerank, "verdicts": result.verdicts,
                      "also_found": [r.model_dump() for recs in result.also_found.values() for r in recs]},
            "model_calls": calls,
        }

    async def aggregates(self, state: MeshQueryState) -> list[dict]:
        """The grouped views of the released datapoints, asked of their nodes now. One record per view, at most
        MAX_AGGREGATE_VIEWS in a query, and a node's placeholder row for a live datapoint is replaced by the figures."""
        selected = [EvidenceRecord.model_validate(r) for r in state.get("records", [])]
        released_dps = {r.datapoint for r in selected if r.datapoint}
        wanted: list[tuple[str, str, str]] = []
        for node in state.get("node_results", []):
            for item in node.get("results", []):
                dp = item.get("datapoint")
                for view in item.get("views") or []:
                    key = (node["node_id"], str(dp).split(":", 1)[1] if dp else "", view)
                    if dp in released_dps and key not in wanted and key[1]:
                        wanted.append(key)
        added: list[dict] = []
        for node_id, dp, view in wanted[:MAX_AGGREGATE_VIEWS]:
            try:
                response = await self.call_node_tool(state["user_assertion"], node_id, "aggregate",
                                                     {"datapoint_id": dp, "view": view, "purpose": state["purpose"]})
            except Exception:
                continue
            if response.get("decision") == "ALLOWED" and response.get("kind") == "aggregate":
                added.append(records.validate_record(response).model_dump())
        return added

    async def expand(self, state: MeshQueryState) -> dict[str, Any]:
        aggregates = await self.aggregates(state)
        with_figures = {a["datapoint"] for a in aggregates}
        # a live datapoint's index row is a placeholder ("… live aggregate") that the computed figures replace
        base = [r for r in state.get("records", []) if not (r.get("kind") == "aggregate" and r.get("datapoint") in with_figures)]
        if self.mesh is None:
            return {"relationships": {"used": [], "proposed": [], "hidden": []}, "records": base + aggregates}
        selected = [EvidenceRecord.model_validate(r) for r in base]
        documents = {r.document for r in selected if r.document}
        blocked = {n["node_id"] for n in state.get("node_results", []) if n.get("status") == "BLOCKED_BY_POLICY"}
        routing = state.get("routing", {})
        chosen = set(routing.get("subsidiaries") or []) if routing.get("method") == "user" else None
        links = self.mesh.expand(documents, blocked, only=chosen)
        available = {n["node_id"] for n in state.get("node_results", []) if n.get("status") == "ok"}
        added: list[dict] = []
        for link in links["used"]:
            for end in (link["source"], link["target"]):
                node_id = end.split(":", 1)[0]
                if end in documents or node_id not in self.node_urls or node_id in blocked:
                    continue
                if node_id not in available and node_id not in (state.get("routing", {}).get("subsidiaries") or []):
                    continue
                try:
                    summary = await self.call_node_tool(state["user_assertion"], node_id, "summarize",
                                                        {"document_id": end.split(":", 1)[1], "purpose": state["purpose"]})
                except Exception:
                    continue
                record = records.from_summary(summary)
                if record is not None:
                    added.append(record.model_dump())
                    documents.add(end)
        return {"relationships": links, "records": base + aggregates + added}

    # ── build, answer and check ─────────────────────────────────────────────
    async def build_answer(self, state: MeshQueryState) -> dict[str, Any]:
        recs = [EvidenceRecord.model_validate(r) for r in state.get("records", [])]
        withheld = [EvidenceRecord.model_validate(r) for r in state.get("withheld_records", [])]
        rels = [records.from_relationship(link) for link in state.get("relationships", {}).get("used", [])]
        routing = state.get("routing", {})
        labels = routing.get("concept_labels", {})
        explanation = (f"Method: {routing.get('method')}. Concepts: {', '.join(labels.get(c, c) for c in routing.get('concepts', [])) or 'none'}. "
                       f"Subsidiaries asked: {', '.join(routing.get('subsidiaries', [])) or 'none'}.")
        built = builder.build(state["question"], state["purpose"], state.get("company", ""), explanation, rels, recs, withheld)
        context = {"chars": built.chars, "omitted": built.omitted, "included": built.included, "skipped_reason": built.skipped_reason}
        calls = list(state.get("model_calls", []))
        outcome: dict[str, Any] = {"text": None, "status": "evidence_only", "reason": None, "checks": [], "cached": False}
        if not recs:
            released_any = any(n.get("results") for n in state.get("node_results", []))
            for_purpose = [w for w in withheld if w.rule_id == "R-PURPOSE-01"]
            if released_any:
                outcome["reason"] = "Every released record was set aside by the re-rank step, so no answer was written."
            elif for_purpose:
                # the documents exist, but their owners do not release them for this purpose: say what to try
                purpose = str(state["purpose"]).replace("_", " ")
                outcome["reason"] = (f"The documents that match are not shared for the purpose {purpose}. "
                                     "If the question has another purpose, ask it again with that purpose."
                                     if len(for_purpose) == len(withheld) else
                                     f"Some documents that match are not shared for the purpose {purpose}, and their owners "
                                     "keep the others back for other reasons. Another purpose may release the first ones.")
            else:
                outcome["reason"] = "No evidence was released for this question."
            return {"context": context, "answer": outcome, "model_calls": calls}
        if built.skipped_reason:
            outcome["reason"] = f"Answer step skipped: {built.skipped_reason}."
            return {"context": context, "answer": outcome, "model_calls": calls}
        if self.backend is None:
            outcome["reason"] = "No answer model is configured, so the evidence is shown alone."
            return {"context": context, "answer": outcome, "model_calls": calls}

        model = choice_for("answer").model
        key = bundle_key(state["question"], state["purpose"], state.get("company", ""), state.get("roles", []),
                         state.get("as_of"), recs, [r.evidence_id for r in rels], model, PROMPT_VERSION)
        partial = any(n.get("status") != "ok" for n in state.get("node_results", []))
        cached = ANSWER_CACHE.get(key)
        if cached is not None:
            return {"context": context, "answer": {**cached, "cached": True}, "model_calls": calls}

        call = self._caller(state, calls, recs)
        text = await asyncio.to_thread(write_answer, call, built.prompt)
        if text is None:
            last = calls[-1] if calls else {}
            outcome["reason"] = f"The answer model did not run ({last.get('decision', 'unavailable')}: {last.get('reason', '')})."
            return {"context": context, "answer": outcome, "model_calls": calls}

        also = {r["document"] or r["evidence_id"] for r in state.get("scope", {}).get("also_found", [])}
        conflicts = [(link["source"], link["target"]) for link in state.get("relationships", {}).get("used", [])
                     if link["type"] == "CONFLICTS_WITH"]
        removed = [i for r in recs if r.suspicious for i in records.removed_instructions(r)]
        bundle_ids = set(built.included) | {r.document for r in recs if r.document} | {w.evidence_id for w in withheld}
        failures = check.run_checks(text, bundle_ids, also - bundle_ids, withheld, conflicts, removed, self.canaries)
        retried = False
        if failures:
            # One second try with each broken rule named, then the checks again. A second failure is shown in words.
            fix = "\n".join(f"- {check.fix_line(f)}" for f in failures[:6])
            again = await asyncio.to_thread(write_answer, call, f"{built.prompt}\n\nYour first answer broke these rules. "
                                                               f"Write the whole answer again and keep every rule:\n{fix}")
            retried = True
            if again is not None:
                second = check.run_checks(again, bundle_ids, also - bundle_ids, withheld, conflicts, removed, self.canaries)
                if len(second) <= len(failures):
                    text, failures = again, second
        outcome.update(checks=failures)
        if failures:
            outcome.update(status="check_failed", reason=check.plain_reason(failures))
            from services.context.llm import audit
            audit({"event": "answer_check_failed", "trace_id": state.get("trace_id"), "rules": sorted({f["rule"] for f in failures}),
                   "retried": retried})
            return {"context": context, "answer": outcome, "model_calls": calls}
        outcome.update(text=text, status="answered", citations=builder.cited_ids(text))
        if not partial:
            ANSWER_CACHE.put(key, {k: v for k, v in outcome.items() if k != "cached"})
        return {"context": context, "answer": outcome, "model_calls": calls}


class _RuntimeView:
    """The two attributes context_tools reads, so the orchestrator can use it without the full runtime."""
    def __init__(self, mesh, orchestrator):
        self.mesh, self.orchestrator = mesh, orchestrator


def _assemble_results(state: MeshQueryState) -> dict[str, Any]:
    node_results = state.get("node_results", [])
    sources = [item for node in node_results for item in node.get("results", [])]
    withheld = [item for node in node_results for item in node.get("withheld", [])]
    unavailable = {"NODE_UNAVAILABLE", "AUTHENTICATION_FAILED"}
    if not node_results and not (state.get("routing", {}).get("subsidiaries")):
        status = "needs_node_choice"
    else:
        status = "partial" if any(node.get("status") in unavailable for node in node_results) else "ok"
    return {"sources": sources, "withheld": withheld, "status": status, "user_assertion": ""}


def _timed(name: str, fn):
    """Wrap a step so the state records its name and duration. This is the per-step trace of one question."""
    async def run(state: MeshQueryState) -> dict[str, Any]:
        started = time.perf_counter()
        with tracing.span(f"mesh.{name}", {"mesh.trace_id": state.get("trace_id"), "mesh.purpose": state.get("purpose")}):
            out = fn(state)
            result = await out if inspect.isawaitable(out) else out
        steps = list(state.get("steps", [])) + [{"step": name, "ms": round((time.perf_counter() - started) * 1000)}]
        return {**result, "steps": steps}
    return run


def build_mesh_graph(orchestrator: MeshOrchestrator):
    """The seven steps of one question, in a fixed order, compiled without a checkpointer.

    No checkpointer by design: a question is one short run with no pause for a person and nothing to resume, and a
    checkpointer would persist the evidence text outside the owning node's control. What is kept instead: one trace
    ID through every audit line, one model_call event per model step with its prompt version, and the steps list
    with the duration of each step in the response."""
    graph = StateGraph(MeshQueryState)
    graph.add_node("resolve", _timed("resolve", orchestrator.resolve))
    graph.add_node("route", _timed("route", orchestrator.route))
    graph.add_node("fan_out", _timed("fan_out", orchestrator.fan_out))
    graph.add_node("scope", _timed("scope", orchestrator.scope))
    graph.add_node("expand", _timed("expand", orchestrator.expand))
    graph.add_node("build_answer", _timed("build_answer", orchestrator.build_answer))
    graph.add_node("assemble", _timed("assemble", _assemble_results))
    graph.set_entry_point("resolve")
    for a, b in (("resolve", "route"), ("route", "fan_out"), ("fan_out", "scope"), ("scope", "expand"),
                 ("expand", "build_answer"), ("build_answer", "assemble")):
        graph.add_edge(a, b)
    graph.add_edge("assemble", END)
    return graph.compile()


def new_trace_id() -> str:
    return str(uuid.uuid4())


def create_orchestrator(settings: Settings, mesh: MeshGraph | None = None, backend: ChatBackend | None = None,
                        canaries: list[str] | None = None) -> MeshOrchestrator:
    node_urls = {n.node_id: n.url for n in registered_nodes()}
    return MeshOrchestrator(node_urls, PocNodeTokenProvider(settings, dict(node_urls)), MCPNodeTransport(), mesh=mesh,
                            backend=backend, app_env=settings.app_env, canaries=canaries or [])
