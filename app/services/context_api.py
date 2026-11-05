"""The six context tools NeuralMesh offers to SkillForge (plan v2, section 5.2), plus the talent pack import.

Every call carries the end user's company and roles and a purpose. Document text is fetched from the owning
node with that user's identity, so each node applies its own policy to the real user. NeuralMesh receives no
level, no CV and no name. Results are evidence records of contracts/evidence.py where text or a citation is returned.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from typing import Any

from api.auth import issue_poc_token
from knowledge.validator import validate_packs
from services.context.records import from_summary
from services.mesh_runtime import GROUP_FOLDERS, KB_PACK, MeshRuntime

LEVEL_ORDER = {"L": 1, "M": 2, "A": 3}
SIMILAR_MIN_SHARE = 0.6
TALENT_IMPORT = KB_PACK / "talent_import"


@dataclass(frozen=True)
class EndUser:
    user_id: str
    company: str
    roles: tuple[str, ...]

    def assertion(self) -> str:
        """A short-lived API assertion for this end user, from which node tokens are minted as for any user."""
        return issue_poc_token({"sub": f"skillforge:{self.user_id}", "company": self.company, "roles": list(self.roles)}, hours=1)


class NotFound(LookupError):
    pass


def _skill_id(value: str) -> str:
    """Accept a mesh skill ID or SkillForge's name_key ('quality management' -> skill:quality-management)."""
    if value.startswith("skill:"):
        return value
    return "skill:" + "-".join(value.lower().replace("&", "and").replace("/", " ").split())


def _required(rt: MeshRuntime, role_id: str) -> list[dict[str, Any]]:
    out = []
    for skill, data in rt.mesh.neighbours(role_id, "REQUIRES_SKILL"):
        props = data["properties"]
        out.append({"skill": skill, "label": rt.mesh.label(skill), "level": props.get("level"),
                    "importance": props.get("importance")})
    return sorted(out, key=lambda s: s["skill"])


def _live(rt: MeshRuntime, entity_id: str, kind: str) -> bool:
    data = rt.mesh.graph.nodes.get(entity_id)
    return bool(data) and data.get("type") == kind and not data.get("retired")


def _roles(rt: MeshRuntime) -> list[str]:
    return sorted(n for n, d in rt.mesh.graph.nodes(data=True) if d.get("type") == "Role" and not d.get("retired"))


def similar_roles(rt: MeshRuntime, role_id: str) -> list[dict[str, Any]]:
    """SIMILAR_TO, computed by code: shared skills divided by all skills of both roles, at least 60%."""
    mine = {s["skill"] for s in _required(rt, role_id)}
    out = []
    for other in _roles(rt):
        if other == role_id:
            continue
        theirs = {s["skill"] for s in _required(rt, other)}
        union = mine | theirs
        share = len(mine & theirs) / len(union) if union else 0.0
        if share >= SIMILAR_MIN_SHARE:
            out.append({"role": other, "label": rt.mesh.label(other), "subsidiary": other.split(":", 1)[0],
                        "shared_skill_share": round(share, 2)})
    return sorted(out, key=lambda r: -r["shared_skill_share"])


def similar_role_pairs(rt: MeshRuntime) -> list[tuple[str, str, float]]:
    pairs = []
    for a, b in combinations(_roles(rt), 2):
        sa, sb = {s["skill"] for s in _required(rt, a)}, {s["skill"] for s in _required(rt, b)}
        if sa | sb and len(sa & sb) / len(sa | sb) >= SIMILAR_MIN_SHARE:
            pairs.append((a, b, round(len(sa & sb) / len(sa | sb), 2)))
    return pairs


def _skill_documents(rt: MeshRuntime, skill: str) -> list[tuple[str, str | None]]:
    """Documents that explain the skill, directly or through a concept that is part of the skill."""
    g = rt.mesh.graph
    docs: dict[str, str | None] = {}
    for doc, data in rt.mesh.neighbours(skill, "EXPLAINS_SKILL", "in"):
        docs[doc] = data["properties"].get("level")
    for concept, _ in rt.mesh.neighbours(skill, "PART_OF_SKILL", "in"):
        for doc, _ in rt.mesh.neighbours(concept, "MENTIONS", "in"):
            docs.setdefault(doc, None)
    return sorted((d, lvl) for d, lvl in docs.items() if g.nodes.get(d, {}).get("type") == "Document")


def _experts_for(rt: MeshRuntime, skill: str) -> list[dict[str, Any]]:
    g = rt.mesh.graph
    out = []
    for expert, data in rt.mesh.neighbours(skill, "HAS_SKILL", "in"):
        node = g.nodes[expert]
        out.append({"schema_version": "1.0", "kind": "expert", "evidence_id": expert, "node": node.get("subsidiary"),
                    "title": node.get("label"),
                    "expert": {"role": node.get("label"), "level": data["properties"].get("level"),
                               "evidence": [d for d, _ in rt.mesh.neighbours(expert, "EVIDENCED_BY")],
                               "name_available_after_intro_approval": True}})
    return out


def _datapoint_allows(rt: MeshRuntime, doc: str, purpose: str) -> bool:
    g = rt.mesh.graph
    dp = g.nodes.get(doc, {}).get("datapoint")
    return purpose in (g.nodes.get(dp, {}).get("purposes_allowed") or []) if dp else False


async def _fetch_summary(rt: MeshRuntime, user: EndUser, doc: str, purpose: str) -> dict[str, Any] | None:
    node_id, local = doc.split(":", 1)
    if node_id not in rt.orchestrator.node_urls:
        return None
    try:
        response = await rt.orchestrator.call_node_tool(user.assertion(), node_id, "summarize",
                                                        {"document_id": local, "purpose": purpose})
    except Exception:  # noqa: BLE001 - a down node leaves the item out, the list says so
        return {"evidence_id": doc, "node": node_id, "decision": "NODE_UNAVAILABLE"}
    record = from_summary(response)
    if record is None:
        return {"evidence_id": doc, "node": node_id, "decision": response.get("decision"), "rule_id": response.get("rule_id"),
                "reason": response.get("reason"), "title": response.get("title")}
    return record.model_dump()


# ── the six tools ───────────────────────────────────────────────────────────
def role_context(rt: MeshRuntime, role_id: str | None = None, title: str | None = None, company: str | None = None) -> dict[str, Any]:
    if not role_id:
        if not (title and company):
            raise ValueError("Give a role ID, or a title and a company")
        role_id = f"{company}:role/{'-'.join(title.lower().split())}"
    if not _live(rt, role_id, "Role"):
        raise NotFound(role_id)
    skills = []
    for item in _required(rt, role_id):
        concepts = [c for c, _ in rt.mesh.neighbours(item["skill"], "PART_OF_SKILL", "in")]
        skills.append({**item, "concepts": [{"id": c, "label": rt.mesh.label(c)} for c in concepts],
                       "documents": len(_skill_documents(rt, item["skill"])),
                       "consented_experts": len(_experts_for(rt, item["skill"]))})
    return {"schema_version": "1.0", "role": role_id, "label": rt.mesh.label(role_id),
            "subsidiary": role_id.split(":", 1)[0], "required_skills": skills, "similar_roles": similar_roles(rt, role_id)}


async def skill_context(rt: MeshRuntime, user: EndUser, skill: str, level: str | None, purpose: str) -> dict[str, Any]:
    skill = _skill_id(skill)
    g = rt.mesh.graph
    if not _live(rt, skill, "Skill"):
        raise NotFound(skill)
    related = sorted({b for b, _ in rt.mesh.neighbours(skill, "RELATED_TO")} | {a for a, _ in rt.mesh.neighbours(skill, "RELATED_TO", "in")})
    broader = [b for b, _ in rt.mesh.neighbours(skill, "BROADER")]
    roles = sorted({r for r, _ in rt.mesh.neighbours(skill, "REQUIRES_SKILL", "in")})
    docs = [d for d, lvl in _skill_documents(rt, skill)
            if g.nodes.get(d, {}).get("kind") != "role_profile" and _datapoint_allows(rt, d, purpose)
            and (level is None or lvl is None or LEVEL_ORDER[lvl] >= LEVEL_ORDER[level])]
    fetched = [r for r in [await _fetch_summary(rt, user, d, purpose) for d in docs[:5]] if r]
    evidence = [r for r in fetched if r.get("schema_version") == "1.0"]
    not_released = [r for r in fetched if r.get("schema_version") != "1.0"]
    return {"schema_version": "1.0", "skill": skill, "label": rt.mesh.label(skill),
            "description": g.nodes[skill].get("description"), "aliases": g.nodes[skill].get("aliases") or [],
            "broader": broader, "related": related,
            "concepts": [{"id": c, "label": rt.mesh.label(c)} for c, _ in rt.mesh.neighbours(skill, "PART_OF_SKILL", "in")],
            "roles_requiring": [{"role": r, "label": rt.mesh.label(r)} for r in roles],
            "evidence": evidence, "not_released": not_released, "documents_total": len(docs), "consented_experts": _experts_for(rt, skill)}


async def learning_sources(rt: MeshRuntime, user: EndUser, skill: str, target_level: str) -> dict[str, Any]:
    """Documents whose datapoint allows learning and whose EXPLAINS_SKILL level reaches the target. Own company
    first, then newer versions. Superseded and stale documents are dropped. Delivered by reference."""
    skill = _skill_id(skill)
    g = rt.mesh.graph
    if not _live(rt, skill, "Skill"):
        raise NotFound(skill)
    superseded = {b for a, b, d in g.edges(data=True) if d["type"] == "SUPERSEDES" and d["status"] == "approved"}
    candidates, dropped = [], []
    for doc, lvl in rt.mesh.neighbours(skill, "EXPLAINS_SKILL", "in"):
        level = lvl["properties"].get("level")
        node = g.nodes.get(doc, {})
        reason = None
        if node.get("kind") == "role_profile":
            reason = "a role profile, not study material"
        elif doc in superseded:
            reason = "superseded"
        elif str(node.get("version", "2026"))[:4] < "2021":
            reason = "stale"
        elif not _datapoint_allows(rt, doc, "learning"):
            reason = "learning not allowed by the datapoint owner"
        elif LEVEL_ORDER.get(level or "L", 1) < LEVEL_ORDER[target_level]:
            reason = f"explains the skill up to level {level} only"
        if reason:
            dropped.append({"document": doc, "reason": reason})
        else:
            candidates.append((doc, level, node.get("version") or ""))
    candidates.sort(key=lambda c: (c[0].split(":", 1)[0] != user.company, [-ord(ch) for ch in c[2]]))
    items, not_released = [], []
    for doc, level, _ in candidates:
        record = await _fetch_summary(rt, user, doc, "learning")
        if record and record.get("schema_version") == "1.0":
            items.append({**record, "explains_level": level, "delivery": "by_reference"})
        elif record:
            not_released.append(record)
    return {"schema_version": "1.0", "skill": skill, "target_level": target_level, "sources": items,
            "not_released": not_released, "dropped": dropped}


def find_mentors(rt: MeshRuntime, skill: str) -> dict[str, Any]:
    skill = _skill_id(skill)
    if not _live(rt, skill, "Skill"):
        raise NotFound(skill)
    return {"schema_version": "1.0", "skill": skill, "mentors": _experts_for(rt, skill),
            "note": "Names are released only after the owning node approves an introduction (request_access, kind intro)."}


def vocabulary_export(rt: MeshRuntime) -> dict[str, Any]:
    """Concepts and skills with aliases and descriptions, as one group pack. No subsidiary text."""
    g = rt.mesh.graph
    entities = []
    for n, d in sorted(g.nodes(data=True)):
        if d.get("type") in ("Concept", "Skill"):
            entities.append({k: v for k, v in {"id": n, "type": d["type"], "label": d.get("label"),
                                               "aliases": d.get("aliases") or [], "description": d.get("description"),
                                               "domain": d.get("domain")}.items() if v not in (None, [])})
    rels = [{"id": d["id"], "type": d["type"], "from": a, "to": b, "status": "approved",
             "provenance": d.get("provenance") or {"method": "authored", "by_role": "Mesh knowledge curator", "created_at": "2026-11-05"}}
            for a, b, d in g.edges(data=True)
            if d["type"] in ("BROADER", "RELATED_TO", "SAME_AS", "PART_OF_SKILL", "PREREQUISITE_OF") and d["status"] == "approved"]
    for r in rels:
        r["provenance"] = {k: v for k, v in r["provenance"].items() if k in ("method", "by_role", "created_at", "evidence")}
        r["provenance"].setdefault("created_at", "2026-11-05")
        r["provenance"].setdefault("method", "authored")
        r["provenance"].setdefault("by_role", "Mesh knowledge curator")
    from knowledge.packgen import embedding_model_name
    return {"format": "neuralmesh.knowledge-pack", "format_version": "1.0",
            "pack": {"pack_id": "group.vocabulary-export", "scope": "group", "subsidiary": "group",
                     "title": "Group vocabulary export for SkillForge", "owner_role": "Mesh knowledge curator",
                     "language": "en", "published_at": "2026-11-05", "synthetic": True},
            "entities": entities, "relationships": rels, "embedding_model": embedding_model_name()}


# ── talent pack import from SkillForge ──────────────────────────────────────
def import_talent_packs(rt: MeshRuntime, packs: list[dict[str, Any]]) -> dict[str, Any]:
    """Accept SkillForge's export: one group.skills pack (skills with aliases, PREREQUISITE_OF) and one
    <company>.talent pack per subsidiary (roles with aliases, T-01 role profiles, REQUIRES_SKILL).
    Validated with the group packs. Unknown skill IDs are errors (strict). Nothing about people is accepted."""
    for pack in packs:
        pid = pack.get("pack", {}).get("pack_id", "")
        if pid != "group.skills" and not pid.endswith(".talent"):
            raise ValueError(f"{pid or 'a pack'} is not group.skills or <company>.talent")
        if pack.get("experts"):
            raise ValueError(f"{pid} carries experts. The expert directory stays with each node's own pack.")
    incoming = {p["pack"]["pack_id"] for p in packs}
    existing = []
    for folder in GROUP_FOLDERS:
        for path in sorted(folder.glob("*.pack.json")) if folder.is_dir() else []:
            pack = json.loads(path.read_text(encoding="utf-8"))
            if pack["pack"]["pack_id"] not in incoming and (pack["pack"]["scope"] == "group" or folder == TALENT_IMPORT):
                existing.append((path.name, pack))
    named = existing + [(f"{p['pack']['pack_id']}.pack.json", p) for p in packs]
    report = validate_packs(named, strict=False)
    known_skills = {e["id"] for _, p in named for e in p.get("entities", []) if e["type"] == "Skill"}
    unknown = sorted({r["to"] for p in packs for r in p.get("relationships", [])
                      if r["type"] == "REQUIRES_SKILL" and r["to"] not in known_skills})
    errors = list(report.errors) + [f"unknown skill ID {s}" for s in unknown]
    if errors:
        return {"accepted": False, "errors": errors, "warnings": report.warnings}
    TALENT_IMPORT.mkdir(parents=True, exist_ok=True)
    for pack in packs:
        path = TALENT_IMPORT / f"{pack['pack']['pack_id']}.pack.json"
        path.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rt.mesh.load_group_pack(pack, source=f"talent:{pack['pack']['pack_id']}")
    rt.mesh.rebuild()
    roles = sum(1 for p in packs for e in p.get("entities", []) if e["type"] == "Role")
    reqs = sum(1 for p in packs for r in p.get("relationships", []) if r["type"] == "REQUIRES_SKILL")
    return {"accepted": True, "packs": sorted(incoming), "roles": roles, "requirements": reqs, "warnings": report.warnings,
            "note": "Subsidiary talent packs reach each node's own pack on the next pack build (knowledge.packgen)."}


def talent_import_folder() -> Path:
    return TALENT_IMPORT
