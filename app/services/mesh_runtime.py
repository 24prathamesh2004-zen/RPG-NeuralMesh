"""One shared mesh runtime for the API and the MCP gateway: graph store, mesh graph, orchestrator, model backend."""
from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from pathlib import Path

from services.context import policy as model_policy
from services.context.llm import OpenAICompatibleBackend
from services.graph_store import GraphStore
from services.mesh_graph import MeshGraph, load_group_pack_files
from services.neuralmesh import MeshOrchestrator, create_orchestrator
from shared.config import get_settings
from shared.logger import get_logger
from shared.registry import node_ids

log = get_logger("services.mesh_runtime")
APP_ROOT = Path(__file__).resolve().parents[1]
KB_PACK = APP_ROOT / "neuralmesh_kb_pack"
GROUP_FOLDERS = [KB_PACK / "group", KB_PACK / "talent_import"]


def _graph_path() -> Path:
    return Path(os.getenv("NEURALMESH_GRAPH_DB", str(APP_ROOT / ".neuralmesh" / "mesh_graph.db")))


def _backend():
    """The answer model is used only when its key is set (or it runs inside the group network)."""
    choice = model_policy.choice_for("answer")
    if choice.tier == "local":
        return OpenAICompatibleBackend()
    settings = get_settings()
    key = os.getenv(choice.api_key_env) or getattr(settings, choice.api_key_env.lower(), "")
    return OpenAICompatibleBackend() if key else None


def _synthetic_canaries() -> list[str]:
    """Development only: the canary strings of the synthetic packs, so the check step can prove no leak."""
    if get_settings().app_env != "development":
        return []
    out: list[str] = []
    for path in (KB_PACK / "data_pack").glob("*/packs/*/pack.json"):
        pack = json.loads(path.read_text(encoding="utf-8"))
        if pack["pack"].get("synthetic"):
            out += [c["value"] for c in pack.get("test_fixtures", {}).get("canaries", [])]
    return sorted(set(out))


class MeshRuntime:
    def __init__(self) -> None:
        settings = get_settings()
        self.policy_problems = model_policy.check_startup(settings.app_env)
        self.store = GraphStore(_graph_path())
        self.mesh = MeshGraph(self.store)
        self.group_packs = load_group_pack_files(self.mesh, GROUP_FOLDERS)
        self.mesh.rebuild()
        self.orchestrator: MeshOrchestrator = create_orchestrator(settings, self.mesh, _backend(), _synthetic_canaries())
        self.export_status: dict[str, str] = {}

    async def refresh_from_nodes(self) -> dict[str, str]:
        """Ask every registered node for its metadata export and reload the graph. A down node keeps its last export."""
        async def one(node_id: str) -> tuple[str, str]:
            try:
                export = await self.orchestrator.export_node_graph(node_id)
                if export.get("decision") != "ALLOWED":
                    return node_id, f"refused: {export.get('rule_id')}"
                counts = self.mesh.load_node_export(export)
                return node_id, f"loaded {counts['entities']} entities, {counts['relationships']} relationships"
            except Exception as exc:  # noqa: BLE001
                return node_id, f"unavailable: {type(exc).__name__}"
        results = dict(await asyncio.gather(*(one(n) for n in node_ids())))
        for stale in sorted(self.store.exported_sources() - {f"node:{n}" for n in node_ids()}):
            count = self.store.retire_source(stale)
            results[stale.split(":", 1)[1]] = f"left the registry: {count} entries retired"
        self.group_packs = load_group_pack_files(self.mesh, GROUP_FOLDERS)
        self.mesh.rebuild()
        self.export_status = results
        log.info("mesh.graph.refreshed", **{k: v[:40] for k, v in results.items()})
        return results


@lru_cache(maxsize=1)
def runtime() -> MeshRuntime:
    return MeshRuntime()
