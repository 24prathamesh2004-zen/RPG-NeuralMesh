"""The application registry: one file per application in config/applications (plan 2.1).

A registry file names the service identity of the application, the companies it may speak for, how its role names map
to NeuralMesh roles, the purposes it may use, the tools it may call and the packs it may send. The dispatcher checks
every call against it, and the Applications page reads it, so a new application needs a file here and no code.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REGISTRY_DIR = Path(__file__).resolve().parents[1] / "config" / "applications"
NEVER_GRANTED = frozenset({"mesh_admin"})
SERVICE_ROLE = "service"
GROUP_CALLER = "group"


PACK_KEYS = frozenset({"format", "format_version", "pack", "entities", "relationships", "datapoints", "documents"})
DATAPOINT_KEYS = frozenset({"id", "catalogue_id", "title", "sensitivity", "ceiling", "owner_role", "purposes_allowed", "domain",
                            "refresh", "source_system"})


@dataclass(frozen=True)
class ImportRule:
    pack: str       # a pack id, or a pattern with {company}
    target: str     # the pack id NeuralMesh keeps, or a pattern with {company}
    entities: tuple[str, ...] = ()        # the entity types the pack may hold
    relationships: tuple[str, ...] = ()   # the relationship types the pack may hold
    datapoints: tuple[str, ...] = ()      # the catalogue ids of the datapoints a company pack may hold
    documents: tuple[str, ...] = ()       # the document kinds a company pack may hold

    def problems(self, pack: dict[str, Any], company: str | None, purposes: tuple[str, ...]) -> list[str]:
        """Why the pack holds more than this rule allows: an application sends only its own facts, never another
        company's entities, a sharing rule of a node, an approval or a datapoint the node itself defines."""
        out: list[str] = []
        extra = sorted(set(pack) - PACK_KEYS)
        if extra:
            out.append(f"the pack may not carry {', '.join(extra)}")
        ids = set()
        for e in pack.get("entities") or []:
            ids.add(e.get("id"))
            if e.get("type") not in self.entities:
                out.append(f"entity {e.get('id')} of type {e.get('type')} (allowed: {', '.join(self.entities) or 'none'})")
            namespace = str(e.get("id", "")).split(":", 1)[0]
            if company and namespace != company:
                out.append(f"entity {e.get('id')} is not in the namespace {company}")
        for r in pack.get("relationships") or []:
            if r.get("type") not in self.relationships:
                out.append(f"relationship {r.get('id')} of type {r.get('type')} (allowed: {', '.join(self.relationships) or 'none'})")
            if r.get("approvals"):
                out.append(f"relationship {r.get('id')} carries approvals, which only the owning companies give")
            if company and r.get("from") not in ids:
                out.append(f"relationship {r.get('id')} starts at {r.get('from')}, which this pack does not hold")
        for d in pack.get("datapoints") or []:
            if not company or d.get("catalogue_id") not in self.datapoints or d.get("id") != f"{company}:{d.get('catalogue_id')}":
                out.append(f"datapoint {d.get('id')} (allowed: {', '.join(f'{company}:{c}' for c in self.datapoints) or 'none'})")
            if set(d) - DATAPOINT_KEYS:
                out.append(f"datapoint {d.get('id')} may not set {', '.join(sorted(set(d) - DATAPOINT_KEYS))}")
            wider = sorted(set(d.get("purposes_allowed") or []) - set(purposes))
            if wider:
                out.append(f"datapoint {d.get('id')} opens purposes the application does not serve: {', '.join(wider)}")
        allowed_dp = {f"{company}:{c}" for c in self.datapoints} if company else set()
        for doc in pack.get("documents") or []:
            if not company or doc.get("kind") not in self.documents or doc.get("datapoint") not in allowed_dp \
                    or not str(doc.get("id", "")).startswith(f"{company}:"):
                out.append(f"document {doc.get('id')} (allowed: kinds {', '.join(self.documents) or 'none'} in {', '.join(sorted(allowed_dp)) or 'no datapoint'})")
        return out[:20]

    def match(self, pack_id: str) -> tuple[str, str | None] | None:
        """(the pack id NeuralMesh keeps, the company) when the rule covers pack_id, else None."""
        if "{company}" not in self.pack:
            return (self.target, None) if pack_id == self.pack else None
        pattern = "^" + re.escape(self.pack).replace(re.escape("{company}"), "(?P<company>[a-z][a-z0-9-]*)") + "$"
        found = re.match(pattern, pack_id)
        if not found:
            return None
        company = found.group("company")
        return self.target.replace("{company}", company), company


@dataclass(frozen=True)
class Application:
    id: str
    name: str
    domain: str
    identity: str
    token_roles: tuple[str, ...]
    companies: tuple[str, ...]
    role_map: dict[str, str]
    default_role: str
    purposes: tuple[str, ...]
    tools: tuple[str, ...]
    reads: tuple[str, ...]
    imports: tuple[ImportRule, ...]
    graph_sources: tuple[str, ...]
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    note: str = ""

    def mesh_roles(self, roles: list[str]) -> tuple[str, ...]:
        """The NeuralMesh roles of an end user. A role the file does not list gets the default role, and a role that
        NeuralMesh never grants through a request (mesh_admin) is dropped, so it cannot be asserted."""
        out = []
        for role in roles:
            mapped = self.role_map.get(role, self.default_role)
            if mapped not in NEVER_GRANTED and mapped not in out:
                out.append(mapped)
        return tuple(out or (self.default_role,))

    def import_target(self, pack_id: str) -> tuple[str, str | None] | None:
        found = self.import_rule(pack_id)
        return found[1] if found else None

    def import_rule(self, pack_id: str) -> tuple[ImportRule, tuple[str, str | None]] | None:
        for rule in self.imports:
            found = rule.match(pack_id)
            if found:
                return rule, found
        return None

    def card(self) -> dict[str, Any]:
        """The fields the Applications page and the contract route show."""
        return {"id": self.id, "name": self.name, "domain": self.domain,
                "identity": f"{self.identity} ({', '.join(self.token_roles)})", "tools": list(self.tools),
                "companies": list(self.companies), "purposes": list(self.purposes), "note": self.note}


def _read(path: Path) -> Application:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    roles = raw.get("roles") or {}
    app = Application(
        id=str(raw["id"]), name=str(raw["name"]), domain=str(raw["domain"]), identity=str(raw["identity"]),
        token_roles=tuple(raw.get("token_roles") or ["context_client"]), companies=tuple(raw.get("companies") or []),
        role_map=dict(roles.get("map") or {}), default_role=str(roles.get("default", "group_user")),
        purposes=tuple(raw.get("purposes") or []), tools=tuple(raw.get("tools") or []), reads=tuple(raw.get("reads") or []),
        imports=tuple(ImportRule(str(r["pack"]), str(r.get("as", r["pack"])), tuple(r.get("entities") or ()),
                                 tuple(r.get("relationships") or ()), tuple(r.get("datapoints") or ()), tuple(r.get("documents") or ()))
                      for r in raw.get("imports") or []),
        graph_sources=tuple(raw.get("graph_sources") or []), facts=dict(raw.get("facts") or {}), note=str(raw.get("note", "")))
    if app.default_role in NEVER_GRANTED or NEVER_GRANTED & set(app.role_map.values()):
        raise ValueError(f"{path.name}: mesh_admin is never granted through a request")
    if path.stem != app.id:
        raise ValueError(f"{path.name}: the file name must be the application id {app.id}")
    return app


@lru_cache
def applications() -> dict[str, Application]:
    """Every registered application by id, read once per process."""
    apps = [_read(p) for p in sorted(REGISTRY_DIR.glob("*.yaml"))]
    identities = [a.identity for a in apps]
    if len(set(identities)) != len(identities):
        raise ValueError("two applications share one service identity")
    return {a.id: a for a in apps}


def by_identity(subject: str | None) -> Application | None:
    """The application whose service identity signed the token, or None for an unregistered caller."""
    return next((a for a in applications().values() if a.identity == subject), None)
