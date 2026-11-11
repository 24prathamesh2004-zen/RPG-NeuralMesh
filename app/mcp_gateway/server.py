"""Central MCP gateway: every context tool of the catalogue over MCP (Streamable HTTP, port 8100).

    python -m mcp_gateway.server

One tool per catalogue tool (services/context_catalogue.py). Its arguments are the request envelope without the tool
name (purpose, caller, input, schema_version) and its result is the same answer the REST route gives, from the same
dispatcher (services/context_dispatch.py). A refusal that says what is needed comes back as a normal result with its
status. A fault of the identity or the envelope comes back as an MCP tool error whose text is exactly the Problem as JSON.
The arguments reach the dispatcher as they were sent, so the contract, not the MCP library, checks them: a wrong field
gives the contract's refusal or Problem, never the library's own error text. The tool list shows the contract's input
schema all the same.
Tools that write to the graph through the intake on a large scale (import) are served by the API only: the API is the
one process that rebuilds packs and refreshes the graph, the gateway reloads when the store's revision moves.
"""
from __future__ import annotations

import inspect
import asyncio
import json
import os
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.utilities.func_metadata import func_metadata
from mcp.types import CallToolResult, TextContent

from api.auth import API_AUDIENCE, POC_ISSUER
from contracts.context import CONTRACT_VERSION, Caller, problem
from mcp_nodes.auth import JwtTokenVerifier
from services.context_catalogue import CATALOGUE, ToolSpec
from services.context_dispatch import dispatch
from services.mesh_runtime import runtime
from shared.config import get_settings

GATEWAY_PORT = int(os.getenv("NEURALMESH_GATEWAY_PORT", "8100"))
SCOPE = "neuralmesh.context"
API_ONLY = frozenset({"import"})


class _Refused(Exception):
    """The identity may not use the gateway. Carries the Problem the caller gets."""

    def __init__(self, payload: dict[str, Any]) -> None:
        super().__init__(payload.get("code"))
        self.payload = payload


def _claims() -> dict[str, Any]:
    token = get_access_token()
    claims = (token.claims or {}) if token else {}
    if "context_client" not in claims.get("roles", []):
        raise _Refused(problem("not_allowed", "This gateway is for a registered application's service identity.",
                               http=True).model_dump(mode="json", exclude_none=True))
    return claims


def _error(payload: dict[str, Any]) -> CallToolResult:
    """An MCP tool error whose text is the Problem as JSON and nothing else. Returned, not raised: a raised error reaches
    the client with the library's prefix "Error executing tool ..." in front of the JSON."""
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload))], structuredContent=payload, isError=True)


def _input_schema(spec: ToolSpec) -> dict[str, Any]:
    """The input schema the tool list shows: the envelope without the tool name, with this tool's own input model."""
    async def strict(purpose: str, caller: Caller, input: Any, schema_version: str = CONTRACT_VERSION) -> None:  # noqa: A002
        return None

    P = inspect.Parameter
    strict.__signature__ = inspect.Signature(
        [P("purpose", P.POSITIONAL_OR_KEYWORD, annotation=str), P("caller", P.POSITIONAL_OR_KEYWORD, annotation=Caller),
         P("input", P.POSITIONAL_OR_KEYWORD, annotation=spec.input_model),
         P("schema_version", P.POSITIONAL_OR_KEYWORD, default=CONTRACT_VERSION, annotation=str)])
    return func_metadata(strict).arg_model.model_json_schema(by_alias=True)


def _tool(spec: ToolSpec):
    """The tool takes its arguments as they come, so the dispatcher checks them against the contract."""
    async def call(purpose: Any = None, caller: Any = None, input: Any = None,  # noqa: A002
                   schema_version: Any = CONTRACT_VERSION) -> dict[str, Any]:
        body = {"schema_version": schema_version, "tool": spec.name, "purpose": purpose, "caller": caller, "input": input}
        try:
            claims = _claims()
        except _Refused as refused:
            return _error(refused.payload)
        status, payload = await dispatch(claims, spec.name, body, await asyncio.to_thread(runtime))
        return payload if status == 200 else _error(payload)

    call.__name__ = spec.name
    call.__doc__ = spec.summary
    return call


def create_gateway(host: str = "127.0.0.1", port: int = GATEWAY_PORT) -> FastMCP:
    settings = get_settings()
    server = FastMCP(
        name="NeuralMesh context gateway",
        instructions=("Context tools of RPG NeuralMesh for registered applications. Every call names the purpose and the caller "
                      "(the end user's company, roles and an opaque reference, or the group for a service call). A refusal says "
                      "what is needed: the closest known ids, a company to choose, or the fields and allowed values."),
        host=host, port=port, stateless_http=True,
        token_verifier=JwtTokenVerifier(settings.app_secret_key, POC_ISSUER, API_AUDIENCE, algorithm="HS256"),
        auth=AuthSettings(issuer_url=POC_ISSUER, resource_server_url=f"http://{host}:{port}", validate_token_resource=False,
                          required_scopes=[SCOPE]),
    )
    for name, spec in sorted(CATALOGUE.items()):
        if name not in API_ONLY:
            server.add_tool(_tool(spec), name=name, description=spec.summary)
            # the list shows the contract's schema, the call accepts what was sent (FastMCP has no public setter)
            server._tool_manager.get_tool(name).parameters = _input_schema(spec)
    return server


def main() -> None:
    runtime()  # loads the graph the API wrote. The API is the one writer, the gateway reloads on a new revision.
    create_gateway(os.getenv("NEURALMESH_MCP_HOST", "127.0.0.1")).run(transport="streamable-http")


if __name__ == "__main__":
    main()
