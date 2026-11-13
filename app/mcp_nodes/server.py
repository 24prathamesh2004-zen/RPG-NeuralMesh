"""One MCP server per subsidiary: the tools, bound to that node's config, policy, indexes and access store.

The tool implementations live beside this file: server_config (config, capabilities, export), search (search and
summaries), experts (experts, introductions, access requests), live (live facts). They are re-exported here so
callers import them from one place.
"""
from __future__ import annotations


import os
from datetime import date
from pathlib import Path
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from mcp_nodes.auth import caller_context_from_token, load_auth_config
from mcp_nodes.access_store import AccessStore



from mcp_nodes.server_config import (  # noqa: F401 - re-exported
    NODE_IDS, SEARCH_LIMIT, MESH_SERVICE_ROLE, NodeConfig, load_node_config, health_payload, capabilities_payload,
    pack_listing, node_profile, export_graph_node,
)
from mcp_nodes.search import search_node, summarize_node  # noqa: F401 - re-exported
from mcp_nodes.experts import find_experts_node, request_intro_node, request_access_node  # noqa: F401 - re-exported
from mcp_nodes.live import lookup_node, LIVE_DIR  # noqa: F401 - re-exported
from mcp_nodes.aggregate import aggregate_node  # noqa: F401 - re-exported


class LiveNode:
    """The node's config and access store. With reload on, they are read again when a pack, the policy, the node file
    or the expert directory changes on disk, so a rebuilt pack (knowledge.packgen, or a talent import) reaches the node
    without a restart. A file that fails to load keeps the config of before and is logged."""

    def __init__(self, config: NodeConfig, access_store: AccessStore, *, reload: bool = False, data_root: Path | None = None) -> None:
        import threading
        self._config, self._store, self._reload = config, access_store, reload
        self._guard = threading.Lock()
        from mcp_nodes.server_config import _PACK_ROOT
        self._root = data_root or _PACK_ROOT
        self._stamp = self._read_stamp() if reload else None

    def _read_stamp(self) -> tuple:
        node_dir = self._root / self._config.node_id
        files = [node_dir / "node.yaml", node_dir / "policy.yaml", node_dir / "experts.yaml", *sorted(node_dir.glob("packs/*/pack.json")), *sorted(node_dir.glob("added_items/*.json"))]
        return tuple((str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files if f.is_file())

    def _check(self) -> None:
        if not self._reload:
            return
        with self._guard:  # one reload at a time, so concurrent calls never build two access stores
            self._reload_if_changed()

    def _reload_if_changed(self) -> None:
        stamp = self._read_stamp()
        if stamp == self._stamp:
            return
        self._stamp = stamp
        try:
            config = load_node_config(self._config.node_id, self._root)
        except Exception as exc:  # noqa: BLE001 - keep serving the config of before
            import logging
            logging.getLogger("mcp_nodes.server").warning("node %s kept its packs: %s", self._config.node_id, exc)
            return
        self._config = config
        self._store = AccessStore(config.grants_path, config.audit_path, config)

    @property
    def config(self) -> NodeConfig:
        self._check()
        return self._config

    @property
    def access_store(self) -> AccessStore:
        self._check()
        return self._store


def create_server(
    config: NodeConfig,
    *,
    token_verifier: TokenVerifier,
    auth_settings: AuthSettings,
    access_store: AccessStore,
    host: str = "127.0.0.1",
    port: int | None = None,
    reload: bool = False,
) -> FastMCP:
    """Create one MCP server instance bound to a single subsidiary config. reload=True reads the node's files again
    when they change (LiveNode)."""
    server = FastMCP(
        name=f"{config.display} Mesh Node",
        instructions=(
            f"Expose approved capability metadata for {config.display}. "
            "All access decisions belong to this subsidiary node."
        ),
        host=host,
        port=port or config.port,
        stateless_http=True,
        token_verifier=token_verifier,
        auth=auth_settings,
    )

    live = LiveNode(config, access_store, reload=reload)

    @server.tool()
    def health() -> dict[str, str]:
        """Return this node's identity and health status."""
        return health_payload(live.config)

    @server.tool()
    def describe_capabilities(purpose: str) -> dict[str, Any]:
        """List this node's policy-approved datapoint metadata and exposure ceilings."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return capabilities_payload(live.config, caller)

    @server.tool()
    def search(
        query: str,
        purpose: str,
        mode: str | None = None,
        as_of: str | None = None,
        domains: list[str] | None = None,
        concepts: list[str] | None = None,
    ) -> dict[str, Any]:
        """Search this subsidiary's local approved index and return cited policy-allowed results."""
        caller = caller_context_from_token(get_access_token(), purpose)
        try:
            requested_date = date.fromisoformat(as_of) if as_of else None
        except ValueError:
            return {"node_id": live.config.node_id, "results": [], "withheld": [], "status": "invalid_as_of"}
        return search_node(
            live.config,
            caller,
            query,
            purpose,
            mode=mode,
            as_of=requested_date,
            access_store=live.access_store,
            domains=domains,
            concepts=concepts,
        )

    @server.tool()
    def summarize(document_id: str, purpose: str) -> dict[str, Any]:
        """Return only this node's approved summary for one document, with a citation."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return summarize_node(live.config, caller, document_id, purpose, live.access_store)

    @server.tool()
    def find_experts(query: str, purpose: str, concepts: list[str] | None = None) -> dict[str, Any]:
        """Find opted-in experts by role, skills and the concepts of their evidence; names need an approved introduction."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return find_experts_node(live.config, caller, query, purpose, live.access_store, concepts=concepts)

    @server.tool()
    def lookup(fact: str, key: str, purpose: str = "problem_solving") -> dict[str, Any]:
        """A live fact of this subsidiary (for example cover_status of an asset), read now and never stored in the mesh."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return lookup_node(live.config, caller, fact, key, live.access_store)

    @server.tool()
    def aggregate(datapoint_id: str, view: str, purpose: str = "problem_solving") -> dict[str, Any]:
        """A grouped view of this subsidiary's own database (for example spoilage by month), computed now at group level."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return aggregate_node(live.config, caller, datapoint_id, view, purpose, live.access_store)

    @server.tool()
    def export_graph() -> dict[str, Any]:
        """Metadata-only export of this node's packs for the central mesh graph (mesh service identity only)."""
        caller = caller_context_from_token(get_access_token(), "problem_solving")
        return export_graph_node(live.config, caller)

    @server.tool()
    def request_access(
        datapoint_id: str,
        mode: str,
        purpose: str,
        justification: str,
        kind: str = "content",
        expert_id: str | None = None,
    ) -> dict[str, Any]:
        """Request content access or a consent-based expert introduction."""
        caller = caller_context_from_token(get_access_token(), purpose)
        if kind == "intro":
            if datapoint_id != "F-04" or mode != "INTRO" or not expert_id:
                return {"status": "invalid_request", "reason": "Intro requests require F-04, INTRO mode, and expert_id"}
            return request_intro_node(
                live.config,
                live.access_store,
                caller,
                expert_id,
                purpose,
                justification,
            )
        if kind != "content" or expert_id is not None:
            return {"status": "invalid_request", "reason": "Invalid content access request fields"}
        return request_access_node(
            live.config,
            live.access_store,
            caller,
            datapoint_id,
            mode,
            purpose,
            justification,
        )

    return server



def serve_node(node_id: str) -> None:
    """Run one subsidiary server over Streamable HTTP."""
    config = load_node_config(node_id)
    host = os.getenv("NEURALMESH_MCP_HOST", "127.0.0.1")
    port = int(os.getenv(f"NEURALMESH_{node_id.upper()}_PORT", config.port))
    token_verifier, auth_settings = load_auth_config(node_id, port)
    access_store = AccessStore(config.grants_path, config.audit_path, config)
    create_server(
        config,
        token_verifier=token_verifier,
        auth_settings=auth_settings,
        access_store=access_store,
        host=host,
        port=port,
        reload=True,
    ).run(transport="streamable-http")