#!/usr/bin/env python3
"""Routing check for the central mesh graph of RPG NeuralMesh.

Builds the mesh graph (metadata only) from the synthetic knowledge base, the
example group packs and the check vocabulary, then runs the resolve, route and
expand steps of the planned query flow on the ten golden scenarios.

    python route_check.py            # needs PyYAML and NetworkX

Inputs
  app/neuralmesh_kb_pack/kb/<node>.yaml            datapoints, documents, experts (46 documents)
  app/neuralmesh_kb_pack/kb/golden.yaml            the ten golden scenarios
  planning_docs/knowledge_pack_format/examples/    ceat.engineering (concepts per document),
                                                   group.vocabulary (12 concepts), group.links (5 links)
  planning_docs/graph_check/group.vocabulary-check.pack.json   25 concepts added for the check
  planning_docs/graph_check/document_concepts.json             concepts of the documents outside the example packs

Nothing is written. The script prints the result tables.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import networkx as nx
import yaml

ROOT = Path(__file__).resolve().parents[2]
KB = ROOT / "app" / "neuralmesh_kb_pack" / "kb"
EXAMPLES = ROOT / "planning_docs" / "knowledge_pack_format" / "examples"
HERE = Path(__file__).resolve().parent

NODES = ("ceat", "kec", "zensar", "harrisons")
ORG_ALIASES = {
    "ceat": ["ceat"],
    "kec": ["kec", "kec international"],
    "zensar": ["zensar", "zensar technologies"],
    "harrisons": ["harrisons", "harrisons malayalam"],
}
DOMAIN_OF_LETTER = {"E": "engineering", "O": "operations", "C": "commercial", "R": "research",
                    "F": "corporate", "L": "lessons", "M": "mesh", "T": "talent"}
HOP_TYPES = {"RELATED_TO", "BROADER", "SAME_AS"}
JUDGEMENT_TYPES = {"CORROBORATES", "CONFLICTS_WITH", "ADDRESSES_GAP", "SUPERSEDES"}

# Expected results per golden scenario. Datapoints come from must_cite_dp, must_withhold_dp and
# needs_approval_dp of golden.yaml. S5, S6 and S10 give a decision instead of a datapoint list, so
# the datapoint behind the decision is written here. S4 is judged on experts and S7 repeats S2.
DECISION_DATAPOINTS = {"S5": ["E-01"], "S6": ["F-06"], "S10": ["E-02"]}
S8_DATAPOINTS = ["C-05"]


def norm_tokens(text: str) -> list[str]:
    text = text.lower().replace("/", " ").replace("-", " ")
    tokens = re.findall(r"[a-z0-9]+", text)
    out = []
    for t in tokens:
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


def phrase_in(phrase: list[str], tokens: list[str]) -> bool:
    n = len(phrase)
    return any(tokens[i:i + n] == phrase for i in range(len(tokens) - n + 1))


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_graph() -> tuple[nx.MultiDiGraph, dict]:
    g = nx.MultiDiGraph()
    info = {"links": []}

    def add_rel(rtype, a, b, status="approved", rel_id=None, approvals=()):
        g.add_edge(a, b, key=rtype, type=rtype, status=status, rel_id=rel_id, approvals=tuple(approvals))

    for d in DOMAIN_OF_LETTER.values():
        g.add_node(f"domain:{d}", type="Domain", label=d)

    for node in NODES:
        cfg = yaml.safe_load((KB / f"{node}.yaml").read_text(encoding="utf-8"))
        g.add_node(f"org:{node}", type="Subsidiary", label=cfg["display"], aliases=ORG_ALIASES[node])
        for code, dp in cfg["datapoints"].items():
            dp_id = f"{node}:{code}"
            domain = "talent" if code == "F-04" else DOMAIN_OF_LETTER[code[0]]
            g.add_node(dp_id, type="Datapoint", label=dp["title"], subsidiary=node, code=code,
                       ceiling=dp["ceiling"], never_leave=bool(dp.get("never_leave")),
                       requires_approval=bool(dp.get("requires_approval")))
            add_rel("IN_DOMAIN", dp_id, f"domain:{domain}")
            add_rel("OWNED_BY", dp_id, f"org:{node}")
        for doc in cfg["docs"]:
            doc_id = f"{node}:{doc['id']}"
            g.add_node(doc_id, type="Document", label=doc["title"], subsidiary=node, datapoint=f"{node}:{doc['dp']}")
            add_rel("IN_DATAPOINT", doc_id, f"{node}:{doc['dp']}")
        for ex in cfg["experts"]:
            ex_id = f"{node}:expert/{ex['id']}"
            g.add_node(ex_id, type="Expert", label=ex["role"], subsidiary=node, consent=bool(ex["consent"]))
            for ev in ex["evidence"]:
                add_rel("EVIDENCED_BY", ex_id, f"{node}:{ev}")

    for pack_path in (EXAMPLES / "group.vocabulary.pack.json", HERE / "group.vocabulary-check.pack.json"):
        pack = load_json(pack_path)
        for ent in pack["entities"]:
            if ent["type"] in ("Concept", "Skill"):
                g.add_node(ent["id"], type=ent["type"], label=ent["label"], aliases=ent.get("aliases", []))
        for rel in pack.get("relationships", []):
            add_rel(rel["type"], rel["from"], rel["to"], rel["status"], rel["id"])

    ceat_eng = load_json(EXAMPLES / "ceat.engineering.pack.json")
    for doc in ceat_eng["documents"]:
        for c in doc.get("concepts", []):
            add_rel("MENTIONS", doc["id"], c)
        if doc.get("supersedes"):
            add_rel("SUPERSEDES", doc["id"], doc["supersedes"])
    for rel in ceat_eng.get("relationships", []):
        add_rel(rel["type"], rel["from"], rel["to"], rel["status"], rel["id"])

    for doc_id, concepts in load_json(HERE / "document_concepts.json").items():
        assert doc_id in g, f"document_concepts.json names an unknown document {doc_id}"
        for c in concepts:
            assert c in g, f"document_concepts.json names an unknown concept {c}"
            if not g.has_edge(doc_id, c, key="MENTIONS"):
                add_rel("MENTIONS", doc_id, c)

    for rel in load_json(EXAMPLES / "group.links.pack.json")["relationships"]:
        add_rel(rel["type"], rel["from"], rel["to"], rel["status"], rel["id"],
                [a["subsidiary"] for a in rel.get("approvals", [])])
        info["links"].append(rel)

    missing = [n for n in g.nodes if "type" not in g.nodes[n]]
    assert not missing, f"relationships point to undefined entities: {missing}"
    return g, info


def resolve(g: nx.MultiDiGraph, question: str, use_aliases: bool) -> tuple[dict, set]:
    tokens = norm_tokens(question)
    concepts: dict[str, str] = {}
    orgs: set[str] = set()
    for n, data in g.nodes(data=True):
        if data["type"] not in ("Concept", "Skill", "Subsidiary"):
            continue
        names = [data["label"]] + (list(data.get("aliases", [])) if use_aliases else [])
        for name in names:
            if phrase_in(norm_tokens(name), tokens):
                if data["type"] == "Subsidiary":
                    orgs.add(n.split(":", 1)[1])
                else:
                    concepts.setdefault(n, name)
                break
    return concepts, orgs


def route(g: nx.MultiDiGraph, concepts: set[str], named_orgs: set[str]) -> dict:
    hop = set()
    for c in concepts:
        for a, b, data in list(g.out_edges(c, data=True)) + list(g.in_edges(c, data=True)):
            if data["type"] in HOP_TYPES and data["status"] == "approved":
                hop.add(b if a == c else a)
    hop -= concepts
    direct_docs = {a for c in concepts for a, _, d in g.in_edges(c, data=True) if d["type"] == "MENTIONS"}
    hop_docs = {a for c in hop for a, _, d in g.in_edges(c, data=True) if d["type"] == "MENTIONS"} - direct_docs
    docs = direct_docs | hop_docs
    datapoints = {g.nodes[d]["datapoint"] for d in docs}
    orgs = {g.nodes[d]["subsidiary"] for d in docs} | set(named_orgs)
    experts = sorted(
        a for d in docs for a, _, data in g.in_edges(d, data=True)
        if data["type"] == "EVIDENCED_BY" and g.nodes[a]["consent"]
    )
    result = {"hop_concepts": hop, "direct_docs": direct_docs, "hop_docs": hop_docs, "docs": docs,
              "datapoints": datapoints, "orgs": orgs, "experts": sorted(set(experts)), "narrowed_out": set()}
    if named_orgs:
        narrow(g, result, set(named_orgs))
    return result


def narrow(g: nx.MultiDiGraph, r: dict, named: set[str]) -> None:
    """A question that names subsidiaries is sent to those. Another routed subsidiary stays in the route
    only when one of its routed documents is joined by an approved cross-subsidiary link to a document
    in a routed datapoint of a named subsidiary."""
    keep = set(named)
    for a, b, data in g.edges(data=True):
        if data["type"] not in JUDGEMENT_TYPES or data["status"] != "approved":
            continue
        if g.nodes[a]["type"] != "Document" or g.nodes[b]["type"] != "Document":
            continue
        for x, y in ((a, b), (b, a)):
            sx, sy = g.nodes[x]["subsidiary"], g.nodes[y]["subsidiary"]
            if (x in r["docs"] and sx not in named and sy in named
                    and g.nodes[y]["datapoint"] in r["datapoints"]):
                keep.add(sx)
    r["narrowed_out"] = r["orgs"] - keep
    r["orgs"] = r["orgs"] & keep
    r["docs"] = {d for d in r["docs"] if g.nodes[d]["subsidiary"] in keep}
    r["direct_docs"] = r["direct_docs"] & r["docs"]
    r["hop_docs"] = r["hop_docs"] & r["docs"]
    r["datapoints"] = {g.nodes[d]["datapoint"] for d in r["docs"]}
    r["experts"] = [e for e in r["experts"] if g.nodes[e]["subsidiary"] in keep]


def expand(g: nx.MultiDiGraph, routed_datapoints: set[str], blocked_orgs: set[str] = frozenset()) -> dict:
    used, proposed, hidden = [], [], []
    for a, b, data in g.edges(data=True):
        if data["type"] not in JUDGEMENT_TYPES:
            continue
        if g.nodes[a]["type"] != "Document" or g.nodes[b]["type"] != "Document":
            continue
        if g.nodes[a]["datapoint"] not in routed_datapoints or g.nodes[b]["datapoint"] not in routed_datapoints:
            continue
        label = f"{a} {data['type']} {b}"
        if data["status"] != "approved":
            proposed.append(label)
        elif g.nodes[a]["subsidiary"] in blocked_orgs or g.nodes[b]["subsidiary"] in blocked_orgs:
            hidden.append(label)
        else:
            used.append(label)
    return {"used": sorted(used), "proposed": sorted(proposed), "hidden": sorted(hidden)}


def expected_for(scn: dict, golden: dict) -> tuple[set[str], set[str]]:
    sid = scn["id"]
    if sid == "S7":
        scn = next(s for s in golden if s["id"] == "S2")
    codes = set(scn.get("must_cite_dp", [])) | set(scn.get("must_withhold_dp", [])) | set(scn.get("needs_approval_dp", []))
    codes |= set(DECISION_DATAPOINTS.get(sid, []))
    if sid == "S8":
        codes |= set(S8_DATAPOINTS)
    orgs = set()
    if sid == "S4":
        orgs = set(scn["nodes"])
    return codes, orgs


def datapoint_owner(g: nx.MultiDiGraph, code: str, candidate_orgs: list[str]) -> set[str]:
    return {o for o in candidate_orgs if f"{o}:{code}" in g}


def main() -> None:
    t0 = time.perf_counter()
    g, info = build_graph()
    build_ms = (time.perf_counter() - t0) * 1000
    golden = yaml.safe_load((KB / "golden.yaml").read_text(encoding="utf-8"))["scenarios"]

    counts = {}
    for _, data in g.nodes(data=True):
        counts[data["type"]] = counts.get(data["type"], 0) + 1
    rel_counts = {}
    for _, _, data in g.edges(data=True):
        rel_counts[data["type"]] = rel_counts.get(data["type"], 0) + 1
    print("MESH GRAPH BUILT FROM THE SYNTHETIC KNOWLEDGE BASE")
    print(f"  entities: {sum(counts.values())}  " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    print(f"  relationships: {sum(rel_counts.values())}  " + ", ".join(f"{k} {v}" for k, v in sorted(rel_counts.items())))
    print(f"  build time: {build_ms:.1f} ms")
    print()

    for use_aliases in (False, True):
        title = "LABELS AND ALIASES" if use_aliases else "LABELS ONLY (no aliases)"
        print(f"ROUTING WITH {title}")
        header = f"{'id':4} {'resolved concepts':38} {'routed nodes':28} {'expected nodes':26} {'nodes':9} {'datapoints':11} extra nodes"
        print(header)
        complete_nodes = complete_dps = 0
        route_times = []
        details = {}
        for scn in golden:
            t1 = time.perf_counter()
            concepts, named = resolve(g, scn["question"], use_aliases)
            if scn["id"] == "S7":
                concepts, named = resolve(g, next(s for s in golden if s["id"] == "S2")["question"], use_aliases)
            r = route(g, set(concepts), named)
            route_times.append((time.perf_counter() - t1) * 1000)
            exp_codes, exp_orgs = expected_for(scn, golden)
            scenario_nodes = scn["nodes"] if scn["id"] != "S7" else ["ceat", "kec", "zensar"]
            for code in exp_codes:
                exp_orgs |= datapoint_owner(g, code, scenario_nodes)
            routed_codes = {dp.split(":", 1)[1] for dp in r["datapoints"]}
            nodes_ok = exp_orgs <= r["orgs"]
            dps_ok = exp_codes <= routed_codes
            if scn["id"] == "S4":
                nodes_ok = bool(r["experts"]) and all(
                    not any(e.endswith(f"/{bad}") for e in r["experts"]) for bad in scn["must_not_return"])
                dps_ok = nodes_ok
            complete_nodes += nodes_ok
            complete_dps += dps_ok
            extra = sorted(r["orgs"] - exp_orgs)
            resolved = ", ".join(c.split(":", 1)[1] for c in concepts) or "-"
            print(f"{scn['id']:4} {resolved[:38]:38} {', '.join(sorted(r['orgs'])) or '-':28} "
                  f"{', '.join(sorted(exp_orgs)) or '-':26} {'yes' if nodes_ok else 'NO':9} {'yes' if dps_ok else 'NO':11} {', '.join(extra) or '-'}")
            details[scn["id"]] = (concepts, named, r, exp_codes, routed_codes)
        print(f"  nodes complete: {complete_nodes} of 10, datapoints complete: {complete_dps} of 10, "
              f"route time per question: max {max(route_times):.2f} ms")
        print()

    print("DETAIL OF THE RESOLVE AND ROUTE STEPS (labels and aliases)")
    for sid, (concepts, named, r, exp_codes, routed_codes) in details.items():
        print(f"{sid}: matched " + ("; ".join(f"{c.split(':',1)[1]} <- '{a}'" for c, a in concepts.items()) or "nothing")
              + (f" | named subsidiaries: {', '.join(sorted(named))}" if named else ""))
        print(f"     one hop adds: {', '.join(sorted(c.split(':',1)[1] for c in r['hop_concepts'])) or '-'}")
        print(f"     documents direct {len(r['direct_docs'])}, via one hop {len(r['hop_docs'])}: "
              + ", ".join(sorted(r["docs"])))
        print(f"     datapoints routed: {', '.join(sorted(routed_codes))} | expected: {', '.join(sorted(exp_codes)) or '-'}")
        if r["narrowed_out"]:
            print(f"     narrowed out because the question names subsidiaries and no approved link joins them: "
                  + ", ".join(sorted(r["narrowed_out"])))
        if sid == "S4":
            print(f"     consented experts with evidence in the routed documents: {', '.join(r['experts'])}")

    print()
    print("EXPAND STEP: approved links between documents of the routed datapoints")
    for sid in ("S1", "S2", "S3", "S9"):
        r = details[sid][2]
        ex = expand(g, r["datapoints"])
        print(f"{sid}: used {len(ex['used'])}: " + ("; ".join(ex["used"]) or "none"))
        if ex["proposed"]:
            print(f"     not used, status proposed: " + "; ".join(ex["proposed"]))

    print()
    print("POLICY FILTER ON RELATIONSHIPS: a caller blocked at the Harrisons node, scenario S1")
    ex = expand(g, details["S1"][2]["datapoints"], blocked_orgs={"harrisons"})
    print("  still used: " + ("; ".join(ex["used"]) or "none"))
    print("  hidden because one end is at Harrisons: " + ("; ".join(ex["hidden"]) or "none"))
    assert all("harrisons" not in label for label in ex["used"]), "a Harrisons relationship leaked past the filter"

    print()
    print("DOCUMENTS WITHOUT ANY CONCEPT (unreachable by routing)")
    orphans = [n for n, d in g.nodes(data=True) if d["type"] == "Document"
               and not any(x["type"] == "MENTIONS" for _, _, x in g.out_edges(n, data=True))]
    print("  " + (", ".join(sorted(orphans)) or "none"))


if __name__ == "__main__":
    main()
