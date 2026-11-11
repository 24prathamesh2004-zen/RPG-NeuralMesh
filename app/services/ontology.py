"""The graph rules of every domain, read from config/graph/*.yaml and merged into one registry.

The code asks the registry which node and edge types exist, which node types an edge may join, which edge types
form a group (structure, hop, judgement, similarity), which edges the loader derives from node fields, and which
namespaces a source may write. Nothing about a type is written in the code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

GRAPH_RULES_DIR = Path(__file__).resolve().parents[1] / "config" / "graph"


@dataclass(frozen=True)
class EdgeType:
    name: str
    from_types: frozenset[str]
    to_types: frozenset[str]
    symmetric: bool
    group: str
    domain: str


@dataclass
class Ontology:
    domains: list[str] = field(default_factory=list)
    node_types: dict[str, dict] = field(default_factory=dict)
    edge_types: dict[str, EdgeType] = field(default_factory=dict)
    groups: dict[str, frozenset[str]] = field(default_factory=dict)
    derived_edges: list[dict] = field(default_factory=list)
    ownership: dict[str, list[str]] = field(default_factory=dict)

    def group(self, name: str) -> frozenset[str]:
        return self.groups.get(name, frozenset())

    def allows(self, edge_type: str, from_type: str | None, to_type: str | None) -> tuple[bool, str]:
        et = self.edge_types.get(edge_type)
        if et is None:
            return False, f"edge type {edge_type} is not in the graph rules"
        if from_type and from_type not in et.from_types:
            return False, f"{edge_type} from {from_type} is not allowed, expected {sorted(et.from_types)}"
        if to_type and to_type not in et.to_types:
            return False, f"{edge_type} to {to_type} is not allowed, expected {sorted(et.to_types)}"
        return True, "ok"

    def required_properties(self, node_type: str) -> list[str]:
        return list(self.node_types.get(node_type, {}).get("required", []))

    def owned_namespaces(self, source: str) -> set[str] | None:
        """The namespaces a source may write, or None when no rule names the source."""
        if source in self.ownership:
            return set(self.ownership[source])
        for pattern, namespaces in self.ownership.items():
            head = pattern.split("{", 1)[0]
            if "{" in pattern and source.startswith(head):
                bound = source[len(head):]
                return {n.replace("{node}", bound).replace("{pack}", bound).replace("{company}", bound.split(".", 1)[0]) for n in namespaces}
        return None

    def may_write(self, source: str, namespace: str) -> bool:
        """Ownership rule. An exact source name wins, then a pattern like node:{node} binds {node} to the source's own name."""
        if source in self.ownership:
            return namespace in set(self.ownership[source])
        for pattern, namespaces in self.ownership.items():
            head = pattern.split("{", 1)[0]
            if "{" in pattern and source.startswith(head):
                bound = source[len(head):]
                allowed = {n.replace("{node}", bound).replace("{pack}", bound).replace("{company}", bound.split(".", 1)[0]) for n in namespaces}
                return namespace in allowed
            if pattern == source:
                return namespace in set(namespaces)
        return False  # a source without a rule may write nothing


def _merge(files: list[Path]) -> Ontology:
    onto = Ontology()
    for path in sorted(files):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        domain = data.get("domain", path.stem)
        onto.domains.append(domain)
        for name, spec in (data.get("node_types") or {}).items():
            onto.node_types[name] = {**onto.node_types.get(name, {}), **(spec or {}), "domain": onto.node_types.get(name, {}).get("domain", domain)}
        for name, spec in (data.get("edge_types") or {}).items():
            onto.edge_types[name] = EdgeType(name, frozenset(spec.get("from", [])), frozenset(spec.get("to", [])),
                                             bool(spec.get("symmetric", False)), spec.get("group", "structure"), domain)
        for name, members in (data.get("groups") or {}).items():
            onto.groups[name] = onto.groups.get(name, frozenset()) | frozenset(members)
        onto.derived_edges += data.get("derived_edges") or []
        onto.ownership.update(data.get("ownership") or {})
    return onto


@lru_cache(maxsize=4)
def _load(folder: str) -> Ontology:
    return _merge(list(Path(folder).glob("*.yaml")))


def ontology() -> Ontology:
    return _load(os.getenv("NEURALMESH_GRAPH_RULES_DIR", str(GRAPH_RULES_DIR)))


def reload() -> None:
    _load.cache_clear()
