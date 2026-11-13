"""Ingested context graphs over REST, under /api/v1/context-graphs (services/context_graph_ingest.py).

    POST   /api/v1/context-graphs                ingest the JSON in the body. ?check=true checks it and keeps nothing. A graph_id of
                                                 a graph made by Upload input makes the JSON its correction (mesh admins)
    GET    /api/v1/context-graphs                the graphs the caller may see
    GET    /api/v1/context-graphs/sample         a sample JSON in the format, for the caller's company
    GET    /api/v1/context-graphs/{id}           the graph in the same format, with its graph_id, to change and send back
    GET    /api/v1/context-graphs/{id}/view      its nodes and edges for the graph drawing of the page
    POST   /api/v1/context-graphs/{id}/query     one of {"question": ...}, {"node": ..., "hops": 1 or 2},
                                                 {"nodes": {"type", "name", "properties"}}, {"edges": {"type", "source", "target"}},
                                                 {"path": {"from", "to", "max_hops"}}, {"similar": {"node", "top"}}, {"overview": true}
    DELETE /api/v1/context-graphs/{id}           drop the graph (its company or a mesh admin)

Every route needs a bearer token: a signed-in person's token, or an application's service token, whose company is
"group", so it sees the graphs shared with the group only and cannot ingest. A graph with sharing "company" is shown to
that company and to mesh admins, one with sharing "group" to every signed-in user. A graph the caller may not see answers
404, as one that does not exist. "relationships" is read as another name for "edges", in the JSON and in a query. Each
query writes one line to the central audit with the caller, the graph id and the kind of query, never the question or
what was found.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from api.auth import require_user
from services import context_graph_ingest as ingested, uploads
from services.context.llm import audit
from shared.config import get_settings

router = APIRouter()
BODY_BYTES = 8_000_000
QUERY_KINDS = ("question", "node", "nodes", "edges", "path", "similar", "overview")
NOT_SHOWN = "No context graph with this id is shown to you."
UNPROCESSABLE = 422  # the content cannot be used: a field to fix


def _person(user: dict) -> tuple[str, list[str]]:
    return str(user.get("company", "")), list(user.get("roles", []))


def _no_constant(name: str) -> Any:
    raise ValueError(f"{name} is not a JSON value")


async def _body(request: Request) -> Any:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > BODY_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"The JSON has more than {BODY_BYTES:,} bytes.")
    raw = bytearray()
    async for chunk in request.stream():  # read up to the limit, never the whole of a larger body
        raw += chunk
        if len(raw) > BODY_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"The JSON has more than {BODY_BYTES:,} bytes.")
    try:
        return json.loads(bytes(raw).decode("utf-8") or "null", parse_constant=_no_constant)
    except UnicodeDecodeError:
        raise HTTPException(UNPROCESSABLE, "The JSON is not UTF-8 text.") from None
    except RecursionError:
        raise HTTPException(UNPROCESSABLE, "The JSON is nested too deeply to be read.") from None
    except ValueError as exc:
        raise HTTPException(UNPROCESSABLE, f"The body is not valid JSON: {exc}.") from None


async def _shown(graph_id: str, user: dict) -> dict[str, Any]:
    """The graph as a record the query functions read: an ingested graph from its file, or a graph made by Upload
    input, put into the same shape from what the caller may see (uploads.as_graph_record)."""
    company, roles = _person(user)
    try:
        return await asyncio.to_thread(ingested.shown, graph_id, company, roles)  # the file is read off the event loop
    except KeyError:
        pass
    if ingested.GRAPH_ID.fullmatch(graph_id or ""):
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_SHOWN)
    corrected = next((r for r in await asyncio.to_thread(ingested.records) if r.get("corrects") == graph_id and ingested.may_see(r, company, roles)), None)
    if corrected:  # the drawing a person loaded for this uploaded graph stands in its place
        return corrected
    try:
        from api.routers.mesh import runtime
        rt = await asyncio.to_thread(runtime)
        return await asyncio.to_thread(uploads.as_graph_record, rt, graph_id, company, roles)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_SHOWN) from None


@router.post("", status_code=status.HTTP_201_CREATED)
async def ingest(request: Request, check: bool = False, user: dict = Depends(require_user)):
    """Keep the JSON as a context graph, or replace the graph its graph_id names. Answers the graph's id, name and
    counts with what was filled in, the defaults used, the fields not read and the warnings. When anything has to be
    fixed nothing is kept, and the answer is 422 with "problems". check=true checks and keeps nothing."""
    data = await _body(request)
    try:
        result = await asyncio.to_thread(ingested.ingest, data, user, check_only=check, uploaded=uploads.upload_graph_info)
    except ingested.IngestRefused as exc:
        report = exc.report
        return JSONResponse({"detail": f"The graph was not {'checked' if check else 'created'}: "
                                       f"{len(report['problems'])} {'field needs' if len(report['problems']) == 1 else 'fields need'} a change.",
                             **report}, status_code=UNPROCESSABLE)
    code = status.HTTP_200_OK if check or result["unchanged"] or result["replaced"] else status.HTTP_201_CREATED
    return JSONResponse(result, status_code=code)


@router.get("")
async def graphs(uploaded: bool = False, user: dict = Depends(require_user)) -> dict:
    """The graphs ingested as JSON that the caller may see. With uploaded=true also the graphs made by Upload input, in
    "uploaded": id, name, description, inputs and the same three addresses."""
    company, roles = _person(user)
    out: dict[str, Any] = {"graphs": await asyncio.to_thread(ingested.visible, company, roles)}
    if uploaded:
        from api.routers.mesh import runtime
        from services import graph_describe
        rt = await asyncio.to_thread(runtime)
        found = await asyncio.to_thread(graph_describe._uploaded, rt, company, roles)
        out["uploaded"] = [{"id": g["id"], "name": g["name"], "description": g["description"], "companies": g["nodes"], "endpoints": ingested.endpoints(g["id"])}
                           for g in sorted(found, key=lambda g: g["name"].casefold())]
    return out


@router.get("/sample")
async def sample(user: dict = Depends(require_user)) -> dict:
    """A small invented graph in the format, for the caller's company."""
    return ingested.sample(str(user.get("company", "")))


@router.post("/query")
async def query_any(request: Request, user: dict = Depends(require_user)) -> dict:
    """A question with no graph id: {"question": "..."}. The model reads the question with the graphs the caller may
    see (services.graph_describe.choose) and decides what is meant and which graph holds the answer. A clear question
    is answered from that graph, as the model understood it, and the reply names the graph and why. A question that is
    too short, unclear or about nothing the graphs hold gets no answer: the reply gives up to three full questions the
    caller could ask instead. The other kinds of query need a graph id."""
    body = await _body(request)
    question = body.get("question") if isinstance(body, dict) else None
    if not isinstance(question, str) or not question.strip():
        raise HTTPException(UNPROCESSABLE, 'Send {"question": "..."}. To ask one graph, use /context-graphs/{graph_id}/query.')
    if len(question) > ingested.QUESTION_MAX:
        raise HTTPException(UNPROCESSABLE, f"A question has at most {ingested.QUESTION_MAX:,} characters.")
    from api.routers.mesh import runtime
    from services import graph_describe
    from services.context.pii import strip_contact_details
    from services.mesh_runtime import _backend
    question, _ = strip_contact_details(" ".join(question.split()))
    company, roles = _person(user)
    rt = await asyncio.to_thread(runtime)
    backend = await asyncio.to_thread(_backend)
    result = await asyncio.to_thread(graph_describe.choose, rt, question, set(), company, roles, graph_describe.model_caller(backend, get_settings().app_env))
    head = {"question": question, "intent": result["intent"], "understood_as": result["understood_as"], "chosen_by": result["by"], "why": result["reason"],
            "also_close": [{"id": g["id"], "name": g["name"]} for g in result["close"][:3]]}
    if not result["chosen"]:
        note = {"unclear": "The question is too short or unclear to answer well. Ask one of the suggested questions, or say more.",
                "off_topic": "None of the context graphs you may see is about this question.",
                "greeting": "Ask a question about the context graphs you may see.",
                }.get(result["intent"], f"No graph was chosen: {result['reason']}." if result["reason"] else "No graph was chosen.")
        if result["intent"] == "clear":
            note = "None of the context graphs you may see holds the answer to this question."
        return {**head, "graph": None, "suggestions": result["suggestions"], "answer": None, "answer_note": note}
    first = result["chosen"][0]
    record = await _shown(first["id"], user)
    await asyncio.to_thread(audit, {"event": "context_graph_query", "graph_id": record["id"], "graph_company": record["company"], "kind": "question_any_graph",
                                    "chosen_by": result["by"], "caller_company": str(user.get("company", "")), "caller_sub": str(user.get("sub", ""))})
    answer = await asyncio.to_thread(ingested.ask, record, result["understood_as"], app_env=get_settings().app_env, backend_factory=_backend)
    return {**head, "graph": {"id": record["id"], "name": record["name"], "company": record["company"], "company_name": ingested.company_name(record["company"])},
            "also_chosen": [{"id": g["id"], "name": g["name"]} for g in result["chosen"][1:]], "suggestions": [], **{k: v for k, v in answer.items() if k != "question"}}


@router.get("/{graph_id}")
async def graph(graph_id: str, user: dict = Depends(require_user)) -> dict:
    return ingested.as_json(await _shown(graph_id, user))


@router.get("/{graph_id}/view")
async def graph_view(graph_id: str, user: dict = Depends(require_user)) -> dict:
    record = await _shown(graph_id, user)
    company, roles = _person(user)
    return {**ingested.view(record), "graph": ingested.summary(record, company, roles), "quality": ingested.quality(record)}


@router.post("/{graph_id}/query")
async def query(graph_id: str, request: Request, user: dict = Depends(require_user)) -> dict:
    """One query of a graph by its id: a question (the nodes it names, the edges around them and a written answer
    when the model policy allows one), a node with its neighbours, nodes by type, name or properties, edges by type,
    source or target, the shortest paths between two nodes, the nodes most similar to one, or an overview of the
    node types and edge types."""
    record = await _shown(graph_id, user)
    body = await _body(request)
    if isinstance(body, dict) and "relationships" in body and "edges" not in body:
        body = {**{k: v for k, v in body.items() if k != "relationships"}, "edges": body["relationships"]}
    kinds = [k for k in QUERY_KINDS if isinstance(body, dict) and body.get(k) not in (None, "", {}, False)]
    if len(kinds) != 1:
        raise HTTPException(UNPROCESSABLE,
                            'Send one of {"question": "..."}, {"node": "<id or name>", "hops": 1}, '
                            '{"nodes": {"type": "...", "name": "...", "properties": {...}}}, {"edges": {"type": "...", "source": "...", "target": "..."}}, '
                            '{"path": {"from": "...", "to": "...", "max_hops": 4}}, {"similar": {"node": "...", "top": 5}} or {"overview": true}.')
    kind = kinds[0]
    await asyncio.to_thread(audit, {"event": "context_graph_query", "graph_id": record["id"], "graph_company": record["company"], "kind": kind,
                                    "caller_company": str(user.get("company", "")), "caller_sub": str(user.get("sub", ""))})
    head = {"graph": {"id": record["id"], "name": record["name"], "company": record["company"],
                      "company_name": ingested.company_name(record["company"])}, "kind": kind}
    try:
        if kind == "question":
            question = body["question"]
            if not isinstance(question, str) or not question.strip():
                raise HTTPException(UNPROCESSABLE, "question is a text in quotes.")
            if len(question) > ingested.QUESTION_MAX:
                raise HTTPException(UNPROCESSABLE, f"A question has at most {ingested.QUESTION_MAX:,} characters.")
            from services.mesh_runtime import _backend
            answer = await asyncio.to_thread(ingested.ask, record, question, app_env=get_settings().app_env, backend_factory=_backend)
            return {**head, **answer}
        if kind == "node":
            hops = body.get("hops", 1)
            if type(hops) is not int or hops not in (1, 2):
                raise HTTPException(UNPROCESSABLE, "hops is 1 or 2, written without quotes.")
            return {**head, **await asyncio.to_thread(ingested.query_node, record, body["node"], hops)}
        if kind == "overview":
            return {**head, **ingested.overview(record)}
        if kind == "path":
            ask_for = body["path"]
            hops = ask_for.get("max_hops", 4) if isinstance(ask_for, dict) else None
            if not isinstance(ask_for, dict) or ask_for.get("from") in (None, "") or ask_for.get("to") in (None, "") or set(ask_for) - {"from", "to", "max_hops"}:
                raise HTTPException(UNPROCESSABLE, 'path is an object with "from" and "to" (a node id, name or other name) and "max_hops" if wanted.')
            if type(hops) is not int or not 1 <= hops <= ingested.PATH_HOPS_MAX:
                raise HTTPException(UNPROCESSABLE, f"max_hops is a whole number from 1 to {ingested.PATH_HOPS_MAX}, written without quotes.")
            return {**head, **await asyncio.to_thread(ingested.query_path, record, ask_for["from"], ask_for["to"], hops)}
        if kind == "similar":
            ask_for = body["similar"]
            top = ask_for.get("top", 5) if isinstance(ask_for, dict) else None
            if not isinstance(ask_for, dict) or ask_for.get("node") in (None, "") or set(ask_for) - {"node", "top"}:
                raise HTTPException(UNPROCESSABLE, 'similar is an object with "node" (a node id, name or other name) and "top" if wanted.')
            if type(top) is not int or not 1 <= top <= ingested.SIMILAR_MAX:
                raise HTTPException(UNPROCESSABLE, f"top is a whole number from 1 to {ingested.SIMILAR_MAX}, written without quotes.")
            return {**head, **await asyncio.to_thread(ingested.query_similar, record, ask_for["node"], top)}
        filters = body[kind]
        allowed = {"nodes": {"type", "name", "properties"}, "edges": {"type", "source", "target"}}[kind]
        if not isinstance(filters, dict) or not set(filters) & allowed or set(filters) - allowed:
            raise HTTPException(UNPROCESSABLE, f'{kind} is an object with one or more of {", ".join(sorted(allowed))}.')
        if kind == "nodes" and not isinstance(filters.get("properties", {}), dict):
            raise HTTPException(UNPROCESSABLE, 'properties is an object, for example {"material": "FKM"}.')
        found = await asyncio.to_thread(ingested.query_nodes if kind == "nodes" else ingested.query_edges, record, filters)
        return {**head, **found}
    except ingested.NodeNotFound as exc:
        close = f" Close names: {', '.join(exc.close)}." if exc.close else ""
        raise HTTPException(status.HTTP_404_NOT_FOUND, f'No node with the id, name or other name "{exc.ref[:80]}" in this graph.{close}') from None
    except ingested.NodeAmbiguous as exc:
        return JSONResponse({"detail": f'"{exc.ref[:80]}" names {len(exc.candidates)} nodes. Send the id of one.', "candidates": exc.candidates},
                            status_code=status.HTTP_409_CONFLICT)


@router.delete("/{graph_id}")
async def drop(graph_id: str, user: dict = Depends(require_user)) -> dict:
    """Delete the graph. The ingest log keeps its id, name, company and counts, never its content."""
    try:
        return await asyncio.to_thread(ingested.drop, graph_id, user)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_SHOWN) from None
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
