"""Search of the central context graph for people on the screens.

A word or phrase matches an entity when it is a whole phrase inside the entity's label, an alias, a tag or the catalogue
code, or when the label is a whole phrase inside the query (the rule the Ask page uses to find concepts). When no
entity matches by words, the vocabulary vectors give the closest concepts and skills. Entities of never-leave items of
another company are left out, as every graph view does.
"""
from __future__ import annotations

from typing import Any

from services import context_tools
from services.mesh_graph import _phrase_in, norm_tokens
from shared.registry import is_shared, node as registered_node, node_ids

TYPE_ORDER = ["Concept", "Skill", "Document", "Datapoint", "Role", "Expert", "Asset", "Subsidiary", "Domain"]
LIMIT = 50


def _sharing(g, entity_id: str) -> dict[str, Any] | None:
    d = g.nodes[entity_id]
    kind = d.get("type")
    dp = d if kind == "Datapoint" else (g.nodes.get(d.get("datapoint") or "") or {}) if kind == "Document" else None
    if not dp:
        return None
    return {"ceiling": dp.get("ceiling"), "never_leave": bool(dp.get("never_leave")), "company": dp.get("subsidiary"),
            "item": dp.get("label"), "code": dp.get("code"), "shared": is_shared(str(dp.get("subsidiary") or ""))}


def company_name(subsidiary: str | None) -> str | None:
    """The display name of a node, for the screens."""
    return registered_node(subsidiary).display if subsidiary in node_ids() else None


def search(rt: Any, query: str, company: str, roles: list[str], limit: int = LIMIT) -> dict[str, Any]:
    g = rt.mesh.graph
    tokens = norm_tokens(query)
    if not tokens:
        return {"query": query, "results": [], "by_vector": False}
    scored: dict[str, tuple[int, str]] = {}
    for n, d in g.nodes(data=True):
        kind = d.get("type")
        if not kind or kind == "Unknown" or d.get("retired") or not rt.mesh.shown_to(n, company, roles):
            continue
        label = norm_tokens(d.get("label") or "")
        if label == tokens:
            scored[n] = (4, "label")
            continue
        if label and (_phrase_in(tokens, label) or _phrase_in(label, tokens)):
            scored[n] = (3, "label")
            continue
        names = [*(d.get("aliases") or []), *(d.get("tags") or []), d.get("code") or ""]
        for name in names:
            phrase = norm_tokens(str(name))
            if phrase and (_phrase_in(tokens, phrase) or _phrase_in(phrase, tokens)):
                scored[n] = (2, "alias or tag")
                break
    by_vector = False
    if not scored:
        for cid, score in rt.mesh.resolve(query).get("vector_matches", {}).items():
            if cid in g and rt.mesh.shown_to(cid, company, roles):
                scored[cid] = (1, f"meaning match {score:.2f}")
                by_vector = True
    order = {t: i for i, t in enumerate(TYPE_ORDER)}
    ranked = sorted(scored, key=lambda n: (-scored[n][0], order.get(g.nodes[n].get("type"), 99), g.nodes[n].get("label") or n))
    results = [_result(rt, n, scored[n][1], company, roles) for n in ranked[:limit]]
    return {"query": query, "results": results, "by_vector": by_vector, "total": len(ranked)}


def _result(rt: Any, entity_id: str, matched: str, company: str, roles: list[str]) -> dict[str, Any]:
    g = rt.mesh.graph
    d = g.nodes[entity_id]
    return {"id": entity_id, "type": d.get("type"), "label": d.get("label") or entity_id, "subsidiary": d.get("subsidiary"),
            "company": company_name(d.get("subsidiary")), "owner": d.get("owner"), "matched": matched, "sharing": _sharing(g, entity_id),
            "connections": context_tools._degree(rt, entity_id, lambda e: rt.mesh.shown_to(e, company, roles))}


def entity(rt: Any, entity_id: str, company: str, roles: list[str]) -> dict[str, Any]:
    """One entity with its fields, sharing rule and neighbours grouped by link type, one hop."""
    visible = lambda e: rt.mesh.shown_to(e, company, roles)  # noqa: E731
    base = context_tools.entity(rt, entity_id, visible)
    related = context_tools.related(rt, entity_id, depth=1, statuses=("approved", "proposed", "computed"), visible=visible)
    g = rt.mesh.graph
    return {**base, "subsidiary": g.nodes[entity_id].get("subsidiary"), "company": company_name(g.nodes[entity_id].get("subsidiary")),
            "sharing": _sharing(g, entity_id), "related": related["related"]}
