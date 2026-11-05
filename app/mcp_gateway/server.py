"""Central MCP gateway for SkillForge: the six context tools over MCP (Streamable HTTP, port 8100).

    python -m mcp_gateway.server

The same functions as /api/v1/context. The caller is SkillForge's service identity (role context_client,
scope neuralmesh.context). Each tool names the end user and the purpose, so every node applies its own policy.
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from api.auth import API_AUDIENCE, POC_ISSUER
from mcp_nodes.auth import JwtTokenVerifier
from services import context_api, mesh_query
from services.context.pii import strip_contact_details
from services.mesh_runtime import runtime
from shared.config import get_settings
from shared.registry import node_ids

GATEWAY_PORT = int(os.getenv("NEURALMESH_GATEWAY_PORT", "8100"))
SCOPE = "neuralmesh.context"


def _service() -> dict[str, Any]:
    token = get_access_token()
    claims = (token.claims or {}) if token else {}
    if "context_client" not in claims.get("roles", []):
        raise PermissionError("This gateway is for the context client service identity")
    return claims


def _user(user_id: str, company: str, roles: list[str] | None) -> context_api.EndUser:
    if company not in node_ids():
        raise ValueError("The company has no registered Mesh Node")
    return context_api.EndUser(user_id, company, tuple(roles or ["group_user"]))


def create_gateway(host: str = "127.0.0.1", port: int = GATEWAY_PORT) -> FastMCP:
    settings = get_settings()
    server = FastMCP(
        name="NeuralMesh context gateway",
        instructions="Context tools for SkillForge. Every call names the end user and a purpose. No level, CV or name is accepted.",
        host=host, port=port, stateless_http=True,
        token_verifier=JwtTokenVerifier(settings.app_secret_key, POC_ISSUER, API_AUDIENCE, algorithm="HS256"),
        auth=AuthSettings(issuer_url=POC_ISSUER, resource_server_url=f"http://{host}:{port}", validate_token_resource=False,
                          required_scopes=[SCOPE]),
    )

    @server.tool()
    def role_context(role_id: str | None = None, title: str | None = None, company: str | None = None) -> dict[str, Any]:
        """Required skills with levels, similar roles in other subsidiaries, concepts, document and expert counts per skill."""
        _service()
        return context_api.role_context(runtime(), role_id, title, company)

    @server.tool()
    async def skill_context(user_id: str, company: str, skill: str, level: str | None = None,
                            purpose: str = "learning", roles: list[str] | None = None) -> dict[str, Any]:
        """Description, aliases, broader and related skills, concepts, roles requiring it, cited documents, consented experts."""
        _service()
        return await context_api.skill_context(runtime(), _user(user_id, company, roles), skill, level, purpose)

    @server.tool()
    async def ask(user_id: str, company: str, question: str, purpose: str = "learning",
                  roles: list[str] | None = None) -> dict[str, Any]:
        """A cited answer from the mesh query flow, as evidence records."""
        _service()
        user = _user(user_id, company, roles)
        question, removed = strip_contact_details(question)
        rt = runtime()
        result = await mesh_query.run_query(mesh_query.graph_for(rt.orchestrator), question=question, purpose=purpose,
                                            nodes=None, mode=None, as_of=None, user_assertion=user.assertion(),
                                            company=user.company, roles=list(user.roles))
        return {"schema_version": "1.0", **result, "contact_details_removed": removed}

    @server.tool()
    async def learning_sources(user_id: str, company: str, skill: str, target_level: str,
                               roles: list[str] | None = None) -> dict[str, Any]:
        """Study documents allowed under learning that reach the target level, by reference."""
        _service()
        return await context_api.learning_sources(runtime(), _user(user_id, company, roles), skill, target_level)

    @server.tool()
    def find_mentors(skill: str) -> dict[str, Any]:
        """Consented experts with role and evidence. Names only after an approved introduction."""
        _service()
        return context_api.find_mentors(runtime(), skill)

    @server.tool()
    def vocabulary_export() -> dict[str, Any]:
        """The group vocabulary (skills and concepts with aliases) as one knowledge pack."""
        _service()
        return context_api.vocabulary_export(runtime())

    return server


def main() -> None:
    rt = runtime()
    asyncio.run(rt.refresh_from_nodes())
    create_gateway(os.getenv("NEURALMESH_MCP_HOST", "127.0.0.1")).run(transport="streamable-http")


if __name__ == "__main__":
    main()
