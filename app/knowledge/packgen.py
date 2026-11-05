"""Build knowledge packs and their vector indexes from the synthetic YAML knowledge base.

    python -m knowledge.packgen          # run from app/, after neuralmesh_kb_pack/kbgen.py

kb/<node>.yaml + kb/annotations.yaml + data_pack/<node>/source front matter
  -> data_pack/<node>/packs/<domain>/pack.json        one pack per subsidiary and domain (19 for the pilot)
  -> data_pack/<node>/packs/<domain>/build/            vectors.faiss and chunks.db, built from the rows of index.db
The packs are validated together with the group packs (group/*.pack.json). Any error stops the build.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

import yaml

from knowledge import embedder
from knowledge.validator import validate_packs
from knowledge.vector_index import ChunkRow, VectorIndex
from shared.registry import embedding_model_name, node_ids

KB_PACK = Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack"
KB = KB_PACK / "kb"
DATA = KB_PACK / "data_pack"
GROUP = KB_PACK / "group"
TALENT_IMPORT = KB_PACK / "talent_import"
FORMAT = {"format": "neuralmesh.knowledge-pack", "format_version": "1.0"}
DOMAIN_OF_LETTER = {"E": "engineering", "O": "operations", "C": "commercial", "R": "research",
                    "F": "corporate", "L": "lessons", "M": "mesh", "T": "talent"}
DOMAIN_TITLES = {"engineering": "engineering knowledge", "operations": "operations knowledge", "commercial": "commercial knowledge",
                 "research": "research and pilot results", "corporate": "corporate functions", "lessons": "lessons learned",
                 "talent": "roles, required skills and expert directory", "mesh": "mesh meta-data"}

DEFAULT_PURPOSES = ["problem_solving", "compliance", "bid_support"]


def domain_of(code: str) -> str:
    return "talent" if code in ("F-04", "T-01") else DOMAIN_OF_LETTER[code[0]]


def _front_matter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}
    meta, _, _ = text[4:].partition("\n---\n")
    return yaml.safe_load(meta) or {}


def _kind(doc: dict, code: str) -> str:
    tags = {t.lower() for t in doc.get("tags", [])}
    title = doc["title"].lower()
    if "sop" in tags or title.startswith("sop"):
        return "sop"
    if "post-mortem" in tags or "post-mortem" in title:
        return "post_mortem"
    if "rca" in tags or " rca" in title:
        return "rca"
    if "playbook" in title or "checklist" in title or "guide" in title:
        return "playbook"
    if "policy" in tags:
        return "policy"
    if code.startswith("O-05"):
        return "aggregate"
    if "wiki" in tags:
        return "wiki"
    if "legacy" in tags:
        return "note"
    return "report"


def _tag(t: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", t.lower()).strip("-")


def _datapoint(node: str, code: str, dp: dict, purposes: list[str]) -> dict:
    out = {"id": f"{node}:{code}", "catalogue_id": code, "title": dp["title"], "sensitivity": dp["sensitivity"],
           "ceiling": dp["ceiling"], "owner_role": dp["owner_role"], "purposes_allowed": purposes}
    for key in ("never_leave", "requires_approval", "upgrade_with_approval", "consent_required", "rule_id", "views", "min_group"):
        if dp.get(key) not in (None, False):
            out[key] = dp[key]
    if dp.get("blackout"):
        out["blackout"] = "results_calendar"
    return out


def build_node_packs(node: str, annotations: dict) -> dict[str, dict]:
    cfg = yaml.safe_load((KB / f"{node}.yaml").read_text(encoding="utf-8"))
    node_dir = DATA / node
    purposes = annotations["datapoint_purposes"]
    doc_notes = annotations["documents"]
    published = str(annotations.get("published_at", "2026-11-05"))
    packs: dict[str, dict] = {}

    def pack_for(domain: str) -> dict:
        if domain not in packs:
            packs[domain] = {**FORMAT, "pack": {
                "pack_id": f"{node}.{domain}", "scope": "subsidiary", "subsidiary": node, "domain": domain,
                "title": f"{cfg['display']} {DOMAIN_TITLES[domain]}", "owner_role": "Node owner",
                "maturity_level": cfg["level"], "language": "en", "published_at": published, "synthetic": True,
                "index": {"embedding_model": embedding_model_name(), "dimensions": 384, "chunk_chars": 600,
                          "chunk_overlap_chars": 0, "faiss_index_type": "Flat"}},
                "datapoints": [], "documents": []}
        return packs[domain]

    for code, dp in cfg["datapoints"].items():
        pack = pack_for(domain_of(code))
        pack["datapoints"].append(_datapoint(node, code, dp, purposes.get(f"{node}:{code}", list(DEFAULT_PURPOSES))))
        if pack["pack"]["owner_role"] == "Node owner":
            pack["pack"]["owner_role"] = dp["owner_role"]

    for doc in cfg["docs"]:
        code = doc["dp"]
        dp = cfg["datapoints"][code]
        gated = bool(dp.get("requires_approval")) or dp.get("upgrade_with_approval") is not None
        meta = _front_matter(node_dir / "source" / f"{doc['id']}.md")
        doc_id = f"{node}:{doc['id']}"
        item = {"id": doc_id, "datapoint": f"{node}:{code}", "title": doc["title"], "kind": _kind(doc, code),
                "version": str(doc.get("version", meta.get("version", "2026-01"))),
                "tags": list(dict.fromkeys(_tag(t) for t in doc["tags"])),
                "summary": meta.get("approved_summary") or doc["summary"],
                "body_file": f"{'gated' if gated else 'source'}/{doc['id']}.md"}
        if gated:
            item["gated"] = True
        notes = doc_notes.get(doc_id, {})
        if notes.get("concepts"):
            item["concepts"] = list(notes["concepts"])
        if notes.get("skills"):
            item["skills"] = [{"skill": s.split("@")[0], "level": s.split("@")[1]} for s in notes["skills"]]
        if notes.get("supersedes"):
            item["supersedes"] = notes["supersedes"]
        pack_for(domain_of(code))["documents"].append(item)

    for rel in annotations.get("relationships", []):
        if rel["from"].startswith(node + ":"):
            code = rel["from"].split(":", 1)[1].rsplit("-", 1)[0]
            pack_for(domain_of(code)).setdefault("relationships", []).append(rel)

    talent = pack_for("talent")
    expert_skills = annotations.get("expert_skills", {})
    talent["experts"] = []
    for e in cfg["experts"]:
        mapped = expert_skills.get(e["id"])
        if not mapped:
            print(f"note: expert {node}:{e['id']} has no group skill in annotations.yaml, so it is left out of the talent pack "
                  f"(keyword search at the node still finds it)")
            continue
        talent["experts"].append({
            "id": f"{node}:expert/{e['id']}", "role": e["role"],
            "skills": [{"skill": item.split("@")[0], "level": item.split("@")[1]} for item in mapped],
            "keywords": list(dict.fromkeys(e["skills"])), "evidence": [f"{node}:{x}" for x in e["evidence"]],
            "consent": bool(e["consent"]), "private": {"name": e["private_name"]}})

    canaries = cfg.get("canaries", [])
    for domain, pack in packs.items():
        pack_canaries = []
        for c in canaries:
            for doc in cfg["docs"]:
                body = (doc.get("body") or "") + (doc.get("private_body") or "")
                if c in body and domain_of(doc["dp"]) == domain:
                    pack_canaries.append({"value": c, "document": f"{node}:{doc['id']}"})
        if pack_canaries:
            pack["test_fixtures"] = {"canaries": pack_canaries}
    return packs


def merge_talent_import(node: str, pack: dict) -> dict:
    """A talent pack exported by SkillForge for this subsidiary adds its T-01 datapoint, roles and REQUIRES_SKILL."""
    path = TALENT_IMPORT / f"{node}.talent.pack.json"
    if not path.is_file():
        return pack
    imported = json.loads(path.read_text(encoding="utf-8"))
    known = {d["id"] for d in pack.get("datapoints", [])}
    pack["datapoints"] += [d for d in imported.get("datapoints", []) if d["id"] not in known]
    pack["documents"] += imported.get("documents", [])
    pack.setdefault("entities", []).extend(imported.get("entities", []))
    pack.setdefault("relationships", []).extend(imported.get("relationships", []))
    pack["pack"]["published_at"] = imported["pack"].get("published_at", pack["pack"]["published_at"])
    return pack


def load_group_packs() -> list[tuple[str, dict]]:
    out = [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(GROUP.glob("*.pack.json"))]
    if TALENT_IMPORT.is_dir():
        out += [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(TALENT_IMPORT.glob("group.*.pack.json"))]
    return out


def index_rows(node: str) -> list[tuple]:
    con = sqlite3.connect(DATA / node / "index.db")
    try:
        return con.execute("SELECT text, title, doc_id, dp, mode, sens, version, stale FROM idx").fetchall()
    finally:
        con.close()


def build_all(build_vectors: bool = True) -> dict:
    annotations = yaml.safe_load((KB / "annotations.yaml").read_text(encoding="utf-8"))
    all_packs: dict[str, dict] = {}
    for node in node_ids():
        for domain, pack in build_node_packs(node, annotations).items():
            if domain == "talent":
                pack = merge_talent_import(node, pack)
            all_packs[pack["pack"]["pack_id"]] = pack
    named = [(f"{pid}.pack.json", p) for pid, p in all_packs.items()] + load_group_packs()
    report = validate_packs(named, strict=True)
    if report.errors:
        raise SystemExit("Pack validation failed:\n" + "\n".join(report.errors))

    summary = {"packs": len(all_packs), "warnings": len(report.warnings), "vectors": {}}
    for pid, pack in all_packs.items():
        node, domain = pid.split(".")
        out_dir = DATA / node / "packs" / domain
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "pack.json").write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    if build_vectors:
        if not embedder.available():
            raise SystemExit("The embedding model is missing, so the vector indexes cannot be built.")
        for node in node_ids():
            cfg = yaml.safe_load((KB / f"{node}.yaml").read_text(encoding="utf-8"))
            canaries = cfg.get("canaries", [])
            by_domain: dict[str, list[ChunkRow]] = {}
            for text, title, doc_id, dp, mode, sens, version, stale in index_rows(node):
                if mode == "LIVE":
                    continue
                by_domain.setdefault(domain_of(dp), []).append(
                    ChunkRow(doc_id, dp, mode, sens, str(version), int(stale), text or "", title or ""))
            for domain in {pid.split(".")[1] for pid in all_packs if pid.startswith(node + ".")}:
                index = VectorIndex(DATA / node / "packs" / domain / "build")
                summary["vectors"][f"{node}.{domain}"] = index.build(by_domain.get(domain, []))
                stored = index.all_text()
                leaked = [c for c in canaries if c in stored]
                if leaked:
                    raise SystemExit(f"Canary leaked into the vector chunk table of {node}.{domain}: {leaked}")
    return summary


if __name__ == "__main__":
    result = build_all(build_vectors="--no-vectors" not in sys.argv)
    print(json.dumps(result, indent=2))
