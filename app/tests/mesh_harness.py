"""In-process mesh for tests: the real node functions, the real tokens, the real graph and context layer.

LocalTransport stands in for MCP over HTTP only. It decodes the node token the orchestrator minted and calls
the node's own search, summarize, find_experts and export_graph functions, so every policy decision is real.
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import jwt

from mcp_nodes.access_store import AccessStore
from mcp_nodes.auth import CallerContext
from mcp_nodes.server import (
    NODE_IDS,
    export_graph_node,
    find_experts_node,
    load_node_config,
    lookup_node,
    search_node,
    summarize_node,
    aggregate_node,
)
from services.context.policy import ModelChoice
from services.graph_store import GraphStore
from services.mesh_graph import MeshGraph, load_group_pack_files
from services.mesh_runtime import GROUP_FOLDERS
from services.neuralmesh import MeshOrchestrator, PocNodeTokenProvider
from shared.config import get_settings


class LocalTransport:
    def __init__(self, down: set[str] | None = None) -> None:
        self.state = Path(tempfile.mkdtemp(prefix="mesh-nodes-"))
        self.configs = {n: load_node_config(n) for n in NODE_IDS}
        self.stores = {n: AccessStore(self.state / n / "grants.db", self.state / n / "audit.jsonl", c)
                       for n, c in self.configs.items()}
        self.down = down or set()
        self.calls: list[tuple[str, str, dict]] = []

    def _node(self, url: str) -> str:
        port = int(url.split(":")[2].split("/")[0])
        return next(n for n, c in self.configs.items() if c.port == port)

    def _caller(self, token: str, purpose: str) -> CallerContext:
        claims = jwt.decode(token, options={"verify_signature": False})
        return CallerContext(claims["sub"], claims["company"], frozenset(claims["roles"]), purpose)

    async def search(self, url: str, token: str, *, query: str, purpose: str, mode: str | None = None,
                     as_of: str | None = None, domains: list[str] | None = None,
                     concepts: list[str] | None = None) -> dict[str, Any]:
        node = self._node(url)
        self.calls.append((node, "search", {"query": query, "domains": domains, "concepts": concepts}))
        if node in self.down:
            raise ConnectionError("node stopped for the test")
        from datetime import date
        return search_node(self.configs[node], self._caller(token, purpose), query, purpose, mode=mode,
                           as_of=date.fromisoformat(as_of) if as_of else None, access_store=self.stores[node],
                           domains=domains, concepts=concepts)

    async def call_tool(self, url: str, token: str, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        node = self._node(url)
        self.calls.append((node, tool, arguments))
        if node in self.down:
            raise ConnectionError("node stopped for the test")
        config, store = self.configs[node], self.stores[node]
        if tool == "export_graph":
            return export_graph_node(config, self._caller(token, "problem_solving"))
        caller = self._caller(token, arguments["purpose"])
        if tool == "summarize":
            return summarize_node(config, caller, arguments["document_id"], arguments["purpose"], store)
        if tool == "find_experts":
            return find_experts_node(config, caller, arguments["query"], arguments["purpose"], store,
                                     concepts=arguments.get("concepts"))
        if tool == "lookup":
            return lookup_node(config, caller, arguments["fact"], arguments["key"], store)
        if tool == "aggregate":
            return aggregate_node(config, caller, arguments["datapoint_id"], arguments["view"], arguments["purpose"], store)
        raise AssertionError(f"tool {tool} is not part of the harness")


class FakeBackend:
    """Answers by citing the first evidence IDs it is given, as a well-behaved model would."""

    def __init__(self, reply: str | None = None) -> None:
        self.reply = reply
        self.calls: list[tuple[str, str]] = []

    def complete(self, choice: ModelChoice, system: str, user: str) -> tuple[str, int, int]:
        self.calls.append((choice.step, user))
        if choice.step == "rerank":
            return "[]", 100, 5
        if choice.step == "classify":
            return '{"nodes": ["zensar"], "reason": "test"}', 50, 5
        if self.reply is not None:
            return self.reply, 100, 20
        import re
        ids = [i for i in re.findall(r"\[([a-z]+:[A-Za-z0-9#:._/-]+)\]", user) if not i.startswith("rel:")][:2]
        text = " ".join(f"Point {n + 1} comes from the evidence [{i}]." for n, i in enumerate(ids))
        return text or "[NOT IN EVIDENCE] Nothing was returned.", 100, 20


def build_mesh(down: set[str] | None = None, backend: Any = None) -> tuple[MeshOrchestrator, LocalTransport, MeshGraph]:
    transport = LocalTransport(down)
    store = GraphStore(Path(tempfile.mkdtemp(prefix="mesh-graph-")) / "graph.db")
    mesh = MeshGraph(store)
    load_group_pack_files(mesh, GROUP_FOLDERS)
    service = CallerContext("svc:mesh-registry", "group", frozenset({"mesh_service"}), "problem_solving")
    for node in NODE_IDS:
        mesh.load_node_export(export_graph_node(transport.configs[node], service))
    mesh.rebuild()
    urls = {n: f"http://127.0.0.1:{c.port}/mcp" for n, c in transport.configs.items()}
    orchestrator = MeshOrchestrator(urls, PocNodeTokenProvider(get_settings(), urls), transport, mesh=mesh,
                                    backend=backend, app_env="development",
                                    canaries=["CANARY-CEAT-FORMULA-7731", "CANARY-CEAT-RCA-2208", "CANARY-KEC-CLAIMS-4410"])
    return orchestrator, transport, mesh
