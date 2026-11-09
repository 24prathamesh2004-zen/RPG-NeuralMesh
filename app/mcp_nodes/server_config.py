"""Node configuration, capability listing and the metadata-only graph export of one subsidiary node."""
from __future__ import annotations


import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml

from mcp_nodes.knowledge_view import NodeKnowledge, load_node_knowledge
from mcp_nodes.policy import authorize_caller
from shared.registry import node_ids




NODE_IDS = node_ids()
SEARCH_LIMIT = 10
MESH_SERVICE_ROLE = "mesh_service"
_KIND_OF_MODE = {"SUM": "summary", "RAG": "chunk", "LIVE": "aggregate", "MD": "metadata"}
# The node packs. NEURALMESH_DATA_PACK moves them out of the repository (a deployment, or the tests' pinned copy).
_PACK_ROOT = Path(os.getenv("NEURALMESH_DATA_PACK", str(Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack" / "data_pack")))
_STATE_ROOT = Path(__file__).resolve().parents[1] / ".neuralmesh" / "nodes"


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    display: str
    port: int
    level: str
    schema_version: str
    defaults: Mapping[str, Any]
    datapoints: Mapping[str, Mapping[str, Any]]
    experts: tuple[Mapping[str, Any], ...]
    calendar_windows: tuple[Mapping[str, str], ...]
    index_path: Path
    grants_path: Path
    audit_path: Path
    knowledge: NodeKnowledge = field(default_factory=NodeKnowledge)


def _read_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return value


def load_node_config(node_id: str, data_root: Path | None = None) -> NodeConfig:
    """Load and validate one subsidiary's generated node and policy files."""
    if node_id not in NODE_IDS:
        raise ValueError(f"Unknown subsidiary node: {node_id}")

    node_dir = (data_root or _PACK_ROOT) / node_id
    node = _read_mapping(node_dir / "node.yaml")
    policy = _read_mapping(node_dir / "policy.yaml")
    experts = yaml.safe_load((node_dir / "experts.yaml").read_text(encoding="utf-8"))
    datapoints = policy.get("datapoints")
    defaults = policy.get("defaults", {})
    calendar_name = policy.get("calendar")

    if node.get("node_id") != node_id or policy.get("node") != node_id:
        raise ValueError(f"Node and policy identity do not match {node_id}")
    if not isinstance(datapoints, dict) or not datapoints:
        raise ValueError(f"Node {node_id} has no policy datapoints")
    if not isinstance(defaults, dict):
        raise ValueError(f"Node {node_id} has invalid policy defaults")
    if not isinstance(experts, list) or any(
        not isinstance(expert, dict)
        or not isinstance(expert.get("id"), str)
        or not isinstance(expert.get("role"), str)
        or not isinstance(expert.get("skills"), list)
        or not isinstance(expert.get("evidence"), list)
        or not isinstance(expert.get("consent"), bool)
        for expert in experts
    ):
        raise ValueError(f"Node {node_id} has invalid expert-directory data")

    port = node.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"Node {node_id} has an invalid port: {port!r}")

    for datapoint_id, datapoint in datapoints.items():
        if not isinstance(datapoint, dict) or not all(
            isinstance(datapoint.get(field), str)
            for field in ("title", "sensitivity", "ceiling")
        ):
            raise ValueError(f"Node {node_id} has an invalid datapoint: {datapoint_id}")

    calendar_windows: tuple[Mapping[str, str], ...] = ()
    if calendar_name:
        if not isinstance(calendar_name, str) or Path(calendar_name).name != calendar_name:
            raise ValueError(f"Node {node_id} has an invalid calendar filename")
        calendar = _read_mapping(node_dir / calendar_name)
        windows = calendar.get("windows", [])
        if not isinstance(windows, list) or any(not isinstance(window, dict) for window in windows):
            raise ValueError(f"Node {node_id} has invalid blackout windows")
        for window in windows:
            try:
                start = date.fromisoformat(window["start"])
                end = date.fromisoformat(window["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Node {node_id} has an invalid blackout window") from exc
            if start > end:
                raise ValueError(f"Node {node_id} has an invalid blackout window")
        calendar_windows = tuple(windows)

    knowledge = load_node_knowledge(node_dir)
    datapoints = {
        code: {**dp, "purposes_allowed": knowledge.datapoint_purposes[code]}
        if code in knowledge.datapoint_purposes else dp
        for code, dp in datapoints.items()
    }

    return NodeConfig(
        node_id=node_id,
        display=str(node.get("display", node_id)),
        port=port,
        level=str(node.get("level", "L0")),
        schema_version=str(node.get("schema_version", "")),
        defaults=defaults,
        datapoints=datapoints,
        experts=tuple(experts),
        calendar_windows=calendar_windows,
        index_path=node_dir / "index.db",
        grants_path=_STATE_ROOT / node_id / "grants.db",
        audit_path=_STATE_ROOT / node_id / "audit.jsonl",
        knowledge=knowledge,
    )


def health_payload(config: NodeConfig) -> dict[str, str]:
    return {
        "node_id": config.node_id,
        "display": config.display,
        "status": "healthy",
        "schema_version": config.schema_version,
    }


def capabilities_payload(config: NodeConfig, caller: Any) -> dict[str, Any]:
    access = authorize_caller(config, caller)
    if access.code == "BLOCKED_BY_POLICY":
        return {
            "node_id": config.node_id,
            "decision": access.code,
            "rule_id": access.rule_id,
            "datapoints": [],
        }

    # A never-leave datapoint is listed only to the node's own company and to mesh admins, as in the central graph.
    own = caller.company == config.node_id or "mesh_admin" in caller.roles
    return {
        "node_id": config.node_id,
        "display": config.display,
        "schema_version": config.schema_version,
        "decision": access.code,
        "datapoints": [
            {
                "datapoint_id": datapoint_id,
                "title": datapoint["title"],
                "sensitivity": datapoint["sensitivity"],
                "exposure_ceiling": datapoint["ceiling"],
                "approval_upgrade": datapoint.get("upgrade_with_approval"),
            }
            for datapoint_id, datapoint in sorted(config.datapoints.items())
            if own or not datapoint.get("never_leave")
        ],
        "packs": pack_listing(config),
        "profile": node_profile(config),
    }


def pack_listing(config: NodeConfig) -> list[dict[str, Any]]:
    return [
        {
            "pack_id": pack["pack"]["pack_id"],
            "domain": pack["pack"]["domain"],
            "documents": len(pack.get("documents", [])),
            "embedding_model": pack["pack"].get("index", {}).get("embedding_model"),
            "published_at": pack["pack"]["published_at"],
        }
        for pack in config.knowledge.packs
    ]


def node_profile(config: NodeConfig, concept_labels: dict[str, str] | None = None) -> str:
    """Short text built from listed metadata only: no summary, no body, nothing of a hidden datapoint. A never-leave
    datapoint is left out with its documents' concepts: the profile reaches every group user and the router."""
    parts = [f"{config.display}, level {config.level}, {len(config.knowledge.packs)} packs."]
    concepts: list[str] = []
    for pack in config.knowledge.packs:
        listed = [d for d in pack.get("datapoints", [])
                  if d.get("graph_visibility", "listed") == "listed" and not d.get("never_leave")]
        if not listed:
            continue
        docs = [d for d in pack.get("documents", []) if d["datapoint"] in {x["id"] for x in listed}]
        datapoints = ", ".join(f"{d['catalogue_id']} {d['title']} ({d['ceiling']})" for d in listed)
        parts.append(f"{pack['pack']['domain'].capitalize()}: {len(docs)} documents in {datapoints}.")
        for doc in docs:
            concepts.extend(c for c in doc.get("concepts", []) if c not in concepts)
    if concepts:
        names = [(concept_labels or {}).get(c, c.split(":", 1)[1].replace("-", " ")) for c in concepts]
        parts.append("Concepts: " + ", ".join(names) + ".")
    parts.append(f"{sum(1 for e in config.experts if e.get('consent') is True)} consented experts.")
    return " ".join(parts)


def export_graph_node(config: NodeConfig, caller: Any) -> dict[str, Any]:
    """Metadata-only part of the node's packs for the central mesh graph. Only the mesh service identity may call it."""
    if MESH_SERVICE_ROLE not in caller.roles:
        return {"node_id": config.node_id, "decision": "BLOCKED_BY_POLICY", "rule_id": "R-EXPORT-01"}
    datapoints, documents, experts, relationships = [], [], [], []
    for pack in config.knowledge.packs:
        listed = set()
        for dp in pack.get("datapoints", []):
            datapoints.append({k: dp[k] for k in ("id", "catalogue_id", "title", "sensitivity", "ceiling", "owner_role",
                                                  "purposes_allowed", "graph_visibility") if k in dp}
                              | {"domain": pack["pack"]["domain"], "never_leave": bool(dp.get("never_leave"))})
            if dp.get("graph_visibility", "listed") == "listed":
                listed.add(dp["id"])
        for doc in pack.get("documents", []):
            if doc["datapoint"] not in listed:
                continue
            documents.append({k: doc[k] for k in ("id", "datapoint", "title", "kind", "version", "tags", "concepts",
                                                   "skills", "supersedes") if k in doc})
        for expert in pack.get("experts", []):
            if expert.get("consent") is True:
                experts.append({k: expert[k] for k in ("id", "role", "skills", "keywords", "evidence")})
        relationships.extend(r for r in pack.get("relationships", []) if r.get("status") == "approved")
    entities = [e for pack in config.knowledge.packs for e in pack.get("entities", [])]
    return {
        "node_id": config.node_id,
        "decision": "ALLOWED",
        "display": config.display,
        "level": config.level,
        "packs": pack_listing(config),
        "datapoints": datapoints,
        "documents": documents,
        "experts": experts,
        "entities": entities,
        "relationships": relationships,
        "profile": node_profile(config),
    }


