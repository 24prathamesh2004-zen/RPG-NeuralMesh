"""One shared mesh runtime for the API and the MCP gateway: graph store, mesh graph, orchestrator, model backend."""
from __future__ import annotations

import asyncio
import json
import os
from functools import lru_cache
from pathlib import Path

from services.context import policy as model_policy
from services.context.llm import ModelBackend, has_api_key
from services.graph_store import GraphStore
from services.mesh_graph import MeshGraph, load_group_pack_files
from services.neuralmesh import MeshOrchestrator, create_orchestrator
from shared.config import get_settings
from shared.logger import get_logger
from shared.registry import node_ids

log = get_logger("services.mesh_runtime")
APP_ROOT = Path(__file__).resolve().parents[1]
KB_PACK = APP_ROOT / "neuralmesh_kb_pack"
# The packs applications send through the import tool. NEURALMESH_TALENT_IMPORT moves them out of the repository.
TALENT_IMPORT = Path(os.getenv("NEURALMESH_TALENT_IMPORT", str(KB_PACK / "talent_import")))
GROUP_FOLDERS = [KB_PACK / "group", TALENT_IMPORT]
APPLICATIONS = KB_PACK / "applications"


def load_application_files(mesh: MeshGraph) -> list[str]:
    """Each application folder holds an ontology.json (its vocabulary, loaded as proposed entries) and optional
    *.pack.json files with the links it authored. Source app:<name>, so the ownership rule applies."""
    from knowledge import adapters
    loaded = []
    if not APPLICATIONS.is_dir():
        return loaded
    for folder in sorted(p for p in APPLICATIONS.iterdir() if p.is_dir()):
        onto = folder / "ontology.json"
        if onto.is_file():
            try:
                nodes, edges = adapters.from_inspection_ontology(json.loads(onto.read_text(encoding="utf-8")), folder.name)
                report = mesh.load_records(f"app:{folder.name}", nodes, edges)
                loaded.append(f"app:{folder.name} ({report.nodes} entities, {report.edges} links" + (f", errors: {report.errors[0]}" if report.errors else "") + ")")
            except (ValueError, KeyError, TypeError) as exc:
                loaded.append(f"app:{folder.name} failed: {type(exc).__name__}: {str(exc)[:120]}")
        for pack_file in sorted(folder.glob("*.pack.json")):
            name = f"app:{folder.name}/{pack_file.name}"
            try:
                pack = json.loads(pack_file.read_text(encoding="utf-8"))
                name = f"app:{folder.name}/{pack['pack']['pack_id']}"
                mesh.load_group_pack(pack, source=name)
                loaded.append(name)
            except (ValueError, KeyError, TypeError) as exc:
                loaded.append(f"{name} failed: {type(exc).__name__}: {str(exc)[:120]}")
    return loaded


def _graph_path() -> Path:
    return Path(os.getenv("NEURALMESH_GRAPH_DB", str(APP_ROOT / ".neuralmesh" / "mesh_graph.db")))


def _backend():
    """The answer model is used only when its key is set (or it runs inside the group network)."""
    choice = model_policy.choice_for("answer")
    if choice.tier == "local":
        return ModelBackend()
    return ModelBackend() if has_api_key(choice) else None


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
        self.group_packs = load_group_pack_files(self.mesh, GROUP_FOLDERS) + load_application_files(self.mesh)
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
            except ValueError as exc:  # the intake refused the export
                return node_id, f"refused by the intake: {str(exc)[:160]}"
            except Exception as exc:  # noqa: BLE001
                return node_id, f"unavailable: {type(exc).__name__}"
        results = dict(await asyncio.gather(*(one(n) for n in node_ids())))
        for stale in sorted(self.store.exported_sources() - {f"node:{n}" for n in node_ids()}):
            count = self.store.retire_source(stale)
            results[stale.split(":", 1)[1]] = f"left the registry: {count} entries retired"
        self.group_packs = load_group_pack_files(self.mesh, GROUP_FOLDERS) + load_application_files(self.mesh)
        await asyncio.to_thread(self.mesh.rebuild)  # embeds the vocabulary: off the event loop, so other calls go on
        self.export_status = results
        log.info("mesh.graph.refreshed", **{k: v[:40] for k, v in results.items()})
        return results


@lru_cache(maxsize=1)
def _runtime() -> MeshRuntime:
    return MeshRuntime()


def runtime() -> MeshRuntime:
    """The shared runtime. Before every use the in-memory graph is rebuilt if another process wrote the store
    (one revision read on SQLite), so the gateway and the API never serve different graphs."""
    rt = _runtime()
    rt.mesh.refresh_if_stale()
    return rt
