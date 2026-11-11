"""Node registry: the single list of Mesh Nodes, read from config/nodes.yaml."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

REGISTRY_PATH = Path(__file__).resolve().parents[1] / "config" / "nodes.yaml"


@dataclass(frozen=True)
class RegisteredNode:
    node_id: str
    display: str
    port: int
    level: str
    tone: str
    shared: bool = False  # keeps the inputs that belong to no one company, read by every connected company

    @property
    def url(self) -> str:
        override = os.getenv(f"NEURALMESH_{self.node_id.upper()}_URL")
        if override:
            return override
        port = int(os.getenv(f"NEURALMESH_{self.node_id.upper()}_PORT", self.port))
        return f"http://127.0.0.1:{port}/mcp"


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[RegisteredNode, ...]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    nodes = []
    seen: set[str] = set()
    for raw in data.get("nodes", []):
        node_id = str(raw["id"])
        if node_id in seen:
            raise ValueError(f"Node {node_id} is registered twice in {path}")
        seen.add(node_id)
        nodes.append(RegisteredNode(node_id, str(raw["display"]), int(raw["port"]), str(raw.get("level", "L0")),
                                    str(raw.get("tone", "#868e96")), bool(raw.get("shared", False))))
    if not nodes:
        raise ValueError(f"No nodes are registered in {path}")
    return tuple(nodes)


def registered_nodes() -> tuple[RegisteredNode, ...]:
    return _load(os.getenv("NEURALMESH_NODE_REGISTRY", str(REGISTRY_PATH)))


def node_ids() -> tuple[str, ...]:
    return tuple(node.node_id for node in registered_nodes())


def company_nodes() -> tuple[RegisteredNode, ...]:
    """The nodes that are companies: people sign up for them and a question can name them. The shared node is left out."""
    return tuple(node for node in registered_nodes() if not node.shared)


def is_shared(node_id: str) -> bool:
    """True for the node that keeps the inputs that belong to no one company."""
    return any(item.node_id == node_id and item.shared for item in registered_nodes())


def node(node_id: str) -> RegisteredNode:
    for item in registered_nodes():
        if item.node_id == node_id:
            return item
    raise KeyError(node_id)


def embedding_model_name() -> str:
    data = yaml.safe_load(Path(os.getenv("NEURALMESH_NODE_REGISTRY", str(REGISTRY_PATH))).read_text(encoding="utf-8"))
    return str(data.get("embedding_model", "all-MiniLM-L6-v2"))
