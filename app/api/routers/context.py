"""The context contract over REST, under /api/v1/context (planning_docs/RPG_NeuralMesh_Generic_Context_Delivery_Standard_Plan.md).

    POST /api/v1/context/<tool>     one request envelope, one answer or a refusal that says what is needed
    GET  /api/v1/context/contract   the published bundle: every schema of the contract and its SHA-256 hash

The caller is a registered application's service identity (role context_client, config/applications/<app>.yaml).
Each request names the end user (an opaque reference, the company and the roles in the application) and the purpose,
so every node applies its policy to the real user. The checks and the tools are in services/context_dispatch.py.
"""
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from jwt import PyJWTError as JWTError

from api.auth import API_AUDIENCE, POC_ISSUER
from contracts.context import http_status_of, problem
from services.context_catalogue import bundle
from services.context_dispatch import dispatch
from services.mesh_runtime import runtime
from shared.config import get_settings

router = APIRouter()
_bearer = HTTPBearer(auto_error=False)
CONTEXT_CLIENT_ROLE = "context_client"
BODY_BYTES = 8_000_000


class ProblemError(Exception):
    """An identity or envelope fault answered with the contract's problem body (api/main.py registers the handler)."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.status = http_status_of(code)
        self.body = problem(code, detail, http=True).model_dump(mode="json", exclude_none=True)


def problem_response(exc: ProblemError) -> JSONResponse:
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    return JSONResponse(exc.body, status_code=exc.status, media_type="application/problem+json", headers=headers)


def require_context_client(creds: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> dict:
    if creds is None:
        raise ProblemError("unauthenticated", "Send the application's service token as a Bearer token.")
    try:
        claims = jwt.decode(creds.credentials, get_settings().app_secret_key, algorithms=["HS256"], issuer=POC_ISSUER,
                            audience=API_AUDIENCE, options={"require": ["exp", "sub"]})
    except JWTError as exc:
        raise ProblemError("unauthenticated", "The service token is invalid or expired.") from exc
    if CONTEXT_CLIENT_ROLE not in claims.get("roles", []):
        raise ProblemError("not_allowed", "This route is for a registered application's service identity.")
    return claims


@router.get("/contract")
async def contract(client: dict = Depends(require_context_client)) -> dict:
    """The published contract. An application compares its sha256 with the one of its pinned copy."""
    return bundle()


@router.post("/{tool}")
async def call_tool(tool: str, request: Request, client: dict = Depends(require_context_client)) -> JSONResponse:
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > BODY_BYTES:  # refused before any of it is read. The status stays the contract's own for this problem
        return problem_response(ProblemError("not_an_envelope", f"The body is larger than {BODY_BYTES:,} bytes."))
    raw = bytearray()
    async for chunk in request.stream():  # read up to the limit, never the whole of a larger body
        raw += chunk
        if len(raw) > BODY_BYTES:
            return problem_response(ProblemError("not_an_envelope", f"The body is larger than {BODY_BYTES:,} bytes."))
    try:
        body = json.loads(bytes(raw) or b"null")
    except ValueError:
        body = None
    status_code, payload = await dispatch(client, tool, body, await asyncio.to_thread(runtime))
    return JSONResponse(payload, status_code=status_code,
                        media_type="application/json" if status_code == 200 else "application/problem+json")
