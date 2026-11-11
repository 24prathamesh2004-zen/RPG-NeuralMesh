"""The one dispatcher of the context contract (plan 2.2 to 2.5), shared by the REST route and the MCP gateway.

Order of the checks: the registered application, the envelope and its version, the tool, what the registry allows
(tool, purpose, company), then the values (caller kind, input fields, a connected company). A fault of the identity
or the envelope is an HTTP error with a Problem body. A fault of a value is a normal answer with a status and a
Problem that says what is needed. Every answer is checked against the contract models before it leaves, so NeuralMesh
never sends a shape the published bundle does not describe.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

from pydantic import ValidationError

from contracts.context import (SUPPORTED_MAJORS, SUPPORTED_VERSIONS, Choice, ContextAnswer, ContextRequest, ProblemField,
                               http_status_of, problem)
from services import applications
from services.context_api import EndUser
from services.context_catalogue import CATALOGUE, CallContext, InputProblem, ToolResult, connected_choices
from shared.logger import get_logger
from shared.registry import node_ids

log = get_logger("services.context_dispatch")
DATA_STATUSES = frozenset({"ok", "partial", "no_evidence", "blocked"})


def _http(code: str, detail: str, **extra: Any) -> tuple[int, dict[str, Any]]:
    return http_status_of(code), problem(code, detail, http=True, **extra).model_dump(mode="json", exclude_none=True)


def _fields(exc: ValidationError, prefix: str) -> list[ProblemField]:
    """Each wrong field with what is wrong and, where the schema fixes them, the allowed values."""
    out = []
    for err in exc.errors()[:10]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        allowed = None
        expected = (err.get("ctx") or {}).get("expected")
        if err.get("type") in ("literal_error", "enum") and isinstance(expected, str):
            allowed = [v.strip(" '\"") for v in expected.replace(" or ", ", ").split(",") if v.strip(" '\"")]
        out.append(ProblemField(field=f"{prefix}.{loc}" if loc else prefix, problem=err.get("msg", "invalid"), allowed=allowed))
    return out


def _refused(trace_id: str, tool: str, result: ToolResult) -> tuple[int, dict[str, Any]]:
    answer = ContextAnswer(tool=tool, status=result.status, problem=result.problem, trace_id=trace_id)
    return 200, answer.model_dump(mode="json")


async def dispatch(claims: dict[str, Any], path_tool: str, body: Any, rt: Any) -> tuple[int, dict[str, Any]]:
    """(HTTP status, body) for one call. claims are the verified service token's claims."""
    started = time.perf_counter()
    trace_id = uuid.uuid4().hex
    app = applications.by_identity(claims.get("sub"))
    if app is None:
        return _http("not_allowed", f"{claims.get('sub')} is not a registered application.")
    if not isinstance(body, dict):
        return _http("not_an_envelope", "The body is not a JSON object.")
    try:
        req = ContextRequest.model_validate(body)
    except ValidationError as exc:
        return _http("not_an_envelope", "The envelope is not readable.", fields=_fields(exc, "envelope"))
    if req.schema_version.split(".")[0] not in SUPPORTED_MAJORS:
        return _http("unsupported_version", f"Version {req.schema_version} is not served.", allowed={"versions": list(SUPPORTED_VERSIONS)})
    if req.tool != path_tool:
        return _http("tool_mismatch", f"The path names {path_tool} and the body names {req.tool}.")
    spec = CATALOGUE.get(req.tool)
    if spec is None:
        return _http("unknown_tool", f"There is no tool {req.tool}.", allowed={"tools": list(app.tools)})
    if req.tool not in app.tools:
        return _http("not_allowed", f"{app.name} may not call {req.tool}.", allowed={"tools": list(app.tools)})
    if req.purpose not in app.purposes:
        return _http("not_allowed", f"{app.name} may not use the purpose {req.purpose}.", allowed={"purposes": list(app.purposes)})
    service_call = req.caller.subsidiary == applications.GROUP_CALLER
    if not service_call and req.caller.subsidiary not in app.companies:
        return _http("not_allowed", f"{app.name} may not speak for {req.caller.subsidiary}.", allowed={"companies": list(app.companies)})

    def refuse(code: str, detail: str, **extra: Any) -> tuple[int, dict[str, Any]]:
        from services.context_catalogue import refused
        out = _refused(trace_id, req.tool, refused(code, detail, **extra))
        _log(app.id, req, out[1], started)
        return out

    if spec.purposes and req.purpose not in spec.purposes:
        return refuse("invalid_input", f"{req.tool} serves the purposes {', '.join(spec.purposes)}.",
                      fields=[ProblemField(field="purpose", problem="not served by this tool", allowed=list(spec.purposes))])
    if spec.caller == "service" and not service_call:
        return refuse("invalid_input", f"{req.tool} is called by the application for no person.",
                      fields=[ProblemField(field="caller.subsidiary", problem="must be group for this tool", allowed=["group"])])
    if spec.caller == "person" and service_call:
        return refuse("invalid_input", f"{req.tool} is called for a person.",
                      fields=[ProblemField(field="caller.subsidiary", problem="must be the person's company", allowed=list(app.companies))])
    if spec.caller == "person" and not req.caller.user_ref:
        return refuse("invalid_input", f"{req.tool} needs the person's reference.",
                      fields=[ProblemField(field="caller.user_ref", problem="required for this tool")])
    if spec.caller == "person" and req.caller.subsidiary not in node_ids():
        return refuse("company_not_connected", f"{req.caller.subsidiary} has no Mesh Node yet, so its people cannot ask the owners' nodes.",
                      fields=[ProblemField(field="caller.subsidiary", problem=f"{req.caller.subsidiary} has no Mesh Node")],
                      choices=[Choice(id=c.id, label=c.label) for c in connected_choices(rt)])
    try:
        inp = spec.input_model.model_validate(req.input)
    except ValidationError as exc:
        return refuse("invalid_input", f"The input of {req.tool} is not valid.", fields=_fields(exc, "input"))

    user = None
    if not service_call:
        user = EndUser(req.caller.user_ref or f"{app.id}:anonymous", req.caller.subsidiary, app.mesh_roles(req.caller.roles), app.id)
    ctx = CallContext(rt=rt, app=app, purpose=req.purpose, user=user, trace_id=trace_id)
    try:
        result = await spec.handler(ctx, inp)
    except InputProblem as exc:
        return refuse("invalid_input", str(exc)[:300])
    except Exception as exc:  # noqa: BLE001 - a model, a node or the store failed: the caller falls back
        log.warning("context.unavailable", tool=req.tool, app=app.id, error=f"{type(exc).__name__}: {str(exc)[:200]}")
        return _http("service_unavailable", f"{req.tool} could not be completed. Try again later.")
    try:
        if result.status in DATA_STATUSES and result.data:
            spec.data_model.model_validate(result.data)
        answer = ContextAnswer(tool=req.tool, status=result.status, records=result.records, answer=result.answer,
                               also_found=result.also_found, omitted=result.omitted, data=result.data, problem=result.problem,
                               trace_id=trace_id)
    except ValidationError as exc:
        log.error("context.off_contract", tool=req.tool, errors=exc.error_count(), first=str(exc.errors()[0])[:200])
        return _http("service_unavailable", f"The answer of {req.tool} did not match the contract. The fault is logged.")
    out = answer.model_dump(mode="json")
    _log(app.id, req, out, started)
    return 200, out


def _log(app_id: str, req: ContextRequest, out: dict[str, Any], started: float) -> None:
    log.info("context.call", app=app_id, tool=req.tool, purpose=req.purpose, company=req.caller.subsidiary,
             status=out.get("status"), problem=(out.get("problem") or {}).get("code"), ms=round((time.perf_counter() - started) * 1000))
