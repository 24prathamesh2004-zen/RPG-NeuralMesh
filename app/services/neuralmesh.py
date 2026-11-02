"""Central LangGraph fan-out to independent subsidiary MCP servers."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict
from urllib.parse import urlsplit

from langgraph.graph import END, StateGraph
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from jose import JWTError, jwt

from api.auth import API_AUDIENCE, POC_ISSUER, issue_poc_token
from shared.config import Settings

NODE_IDS = ("ceat", "kec", "zensar", "harrisons")


class NodeTokenProvider(Protocol):
    async def token_for_node(self, user_assertion: str, node_id: str) -> str: ...


class NodeTransport(Protocol):
    async def search(
        self,
        url: str,
        token: str,
        *,
        query: str,
        purpose: str,
        mode: str | None,
        as_of: str | None,
    ) -> dict[str, Any]: ...

    async def call_tool(self, url: str, token: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class NodeTokenError(Exception):
    pass


class PocNodeTokenProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.node_urls = {
            "ceat": settings.neuralmesh_ceat_url,
            "kec": settings.neuralmesh_kec_url,
            "zensar": settings.neuralmesh_zensar_url,
            "harrisons": settings.neuralmesh_harrisons_url,
        }

    async def token_for_node(self, user_assertion: str, node_id: str) -> str:
        url = self.node_urls.get(node_id)
        if not url:
            raise NodeTokenError("No endpoint is configured for this node")
        try:
            user = jwt.decode(
                user_assertion,
                self.settings.app_secret_key,
                algorithms=["HS256"],
                issuer=POC_ISSUER,
                audience=API_AUDIENCE,
                options={"require_exp": True, "require_sub": True},
            )
        except JWTError as exc:
            raise NodeTokenError("The API session is invalid or expired") from exc

        audience = urlsplit(url)
        node_audience = f"{audience.scheme}://{audience.netloc}"
        return issue_poc_token(
            {
                "sub": user["sub"],
                "company": user["company"],
                "roles": user["roles"],
                "scope": "neuralmesh.query",
            },
            audience=node_audience,
            hours=1,
        )


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

    async def search(
        self,
        url: str,
        token: str,
        *,
        query: str,
        purpose: str,
        mode: str | None,
        as_of: str | None,
    ) -> dict[str, Any]:
        arguments: dict[str, Any] = {"query": query, "purpose": purpose}
        if mode is not None:
            arguments["mode"] = mode
        if as_of is not None:
            arguments["as_of"] = as_of

        return await self.call_tool(url, token, "search", arguments)


@dataclass(frozen=True)
class MeshOrchestrator:
    node_urls: dict[str, str]
    token_provider: NodeTokenProvider
    transport: NodeTransport

    async def fan_out(self, state: dict[str, Any]) -> dict[str, Any]:
        responses = await asyncio.gather(
            *(self._query_node(state, node_id) for node_id in state["nodes"])
        )
        return {"node_results": responses}

    async def _query_node(self, state: dict[str, Any], node_id: str) -> dict[str, Any]:
        url = self.node_urls[node_id]
        try:
            token = await self.token_provider.token_for_node(state["user_assertion"], node_id)
        except NodeTokenError:
            return {"node_id": node_id, "status": "AUTHENTICATION_FAILED", "results": [], "withheld": []}
        except Exception:
            return {"node_id": node_id, "status": "NODE_UNAVAILABLE", "results": [], "withheld": []}

        try:
            response = await self.transport.search(
                url,
                token,
                query=state["question"],
                purpose=state["purpose"],
                mode=state.get("mode"),
                as_of=state.get("as_of"),
            )
            if not isinstance(response, dict):
                raise RuntimeError("Invalid MCP response")
            return {**response, "node_id": node_id}
        except Exception:
            return {"node_id": node_id, "status": "NODE_UNAVAILABLE", "results": [], "withheld": []}

    async def call_node_tool(
        self,
        user_assertion: str,
        node_id: str,
        tool: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        url = self.node_urls[node_id]
        token = await self.token_provider.token_for_node(user_assertion, node_id)
        return await self.transport.call_tool(url, token, tool, arguments)


class MeshQueryState(TypedDict, total=False):
    question: str
    nodes: list[str]
    purpose: str
    mode: str | None
    as_of: str | None
    user_assertion: str
    node_results: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    withheld: list[dict[str, Any]]
    status: str


def build_mesh_graph(orchestrator: MeshOrchestrator):
    graph = StateGraph(MeshQueryState)
    graph.add_node("fan_out", orchestrator.fan_out)
    graph.add_node("assemble", _assemble_results)
    graph.set_entry_point("fan_out")
    graph.add_edge("fan_out", "assemble")
    graph.add_edge("assemble", END)
    return graph.compile()


def _assemble_results(state: MeshQueryState) -> dict[str, Any]:
    node_results = state.get("node_results", [])
    sources = [item for node in node_results for item in node.get("results", [])]
    withheld = [item for node in node_results for item in node.get("withheld", [])]
    unavailable = {"NODE_UNAVAILABLE", "AUTHENTICATION_FAILED"}
    status = "partial" if any(node.get("status") in unavailable for node in node_results) else "ok"
    return {
        "sources": sources,
        "withheld": withheld,
        "status": status,
        "user_assertion": "",
    }


def create_orchestrator(settings: Settings) -> MeshOrchestrator:
    node_urls = {
        "ceat": settings.neuralmesh_ceat_url,
        "kec": settings.neuralmesh_kec_url,
        "zensar": settings.neuralmesh_zensar_url,
        "harrisons": settings.neuralmesh_harrisons_url,
    }
    return MeshOrchestrator(node_urls, PocNodeTokenProvider(settings), MCPNodeTransport())