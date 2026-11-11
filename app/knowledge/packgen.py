"""Build knowledge packs and their vector indexes from the synthetic YAML knowledge base.

    python -m knowledge.packgen          # run from app/, after neuralmesh_kb_pack/kbgen.py

kb/<node>.yaml + kb/annotations.yaml + data_pack/<node>/source front matter
  -> data_pack/<node>/packs/<domain>/pack.json        one pack per subsidiary and domain (19 for the pilot)
  -> data_pack/<node>/packs/<domain>/build/chroma/     the Chroma store of the pack, built from the rows of index.db
The packs are validated together with the group packs (group/*.pack.json). Any error stops the build.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import yaml

from knowledge import embedder
from knowledge.validator import PackCheckFailed, validate_packs
from knowledge.vector_index import ChunkRow, VectorIndex
from shared.registry import embedding_model_name, node_ids

KB_PACK = Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack"
KB = KB_PACK / "kb"
DATA = Path(os.getenv("NEURALMESH_DATA_PACK", str(KB_PACK / "data_pack")))
GROUP = KB_PACK / "group"
TALENT_IMPORT = Path(os.getenv("NEURALMESH_TALENT_IMPORT", str(KB_PACK / "talent_import")))
FORMAT = {"format": "neuralmesh.knowledge-pack", "format_version": "1.0"}
CONTRIBUTIONS = "contributions"  # data_pack/<node>/contributions/<doc>.json: documents people uploaded, kept across rebuilds
ADDED_ITEMS = "added_items"  # data_pack/<node>/added_items/<code>.json: catalogue items a mesh admin named at upload, kept across rebuilds
DOMAIN_OF_LETTER = {"E": "engineering", "O": "operations", "C": "commercial", "R": "research",
                    "F": "corporate", "L": "lessons", "M": "mesh", "T": "talent", "G": "general"}
DOMAIN_TITLES = {"engineering": "engineering knowledge", "operations": "operations knowledge", "commercial": "commercial knowledge",
                 "research": "research and pilot results", "corporate": "corporate functions", "lessons": "lessons learned",
                 "talent": "roles, required skills and expert directory", "mesh": "mesh meta-data", "general": "shared inputs"}

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
                          "chunk_overlap_chars": 0, "vector_store": "chroma"}},
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


def _kept(folder: Path, name: str, incoming: dict[str, dict] | None) -> dict | None:
    """The kept import of this name: the incoming one when an import is being checked, else the file."""
    if incoming and name in incoming:
        return incoming[name]
    path = folder / f"{name}.pack.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def merge_talent_import(node: str, pack: dict, folder: Path | None = None, incoming: dict[str, dict] | None = None) -> dict:
    """A talent pack exported by SkillForge for this subsidiary adds its T-01 datapoint, roles and REQUIRES_SKILL."""
    imported = _kept(folder or TALENT_IMPORT, f"{node}.talent", incoming)
    if imported is None:
        return pack
    known = {d["id"] for d in pack.get("datapoints", [])}
    pack["datapoints"] += [d for d in imported.get("datapoints", []) if d["id"] not in known]
    pack["documents"] += imported.get("documents", [])
    pack.setdefault("entities", []).extend(imported.get("entities", []))
    pack.setdefault("relationships", []).extend(imported.get("relationships", []))
    pack["pack"]["published_at"] = imported["pack"].get("published_at", pack["pack"]["published_at"])
    return pack


def contributions_of(node: str, status: str = "accepted") -> list[dict]:
    """The uploaded documents of a node with this status, oldest first. Each file holds the document fields of the
    pack schema plus ``upload`` (who, when, the file name) and ``status``."""
    folder = DATA / node / CONTRIBUTIONS
    if not folder.is_dir():
        return []
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if record.get("status") == status:
            out.append(record)
    return out


def added_items_of(node: str) -> dict[str, dict]:
    """The catalogue items a mesh admin added to a node at upload: code -> item fields, oldest code first."""
    folder = DATA / node / ADDED_ITEMS
    out: dict[str, dict] = {}
    for path in sorted(folder.glob("*.json")) if folder.is_dir() else []:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[item["code"]] = item
    return out


def merge_contributions(node: str, pack: dict) -> dict:
    """The catalogue items added at upload whose domain is this pack's join its datapoints, then the accepted uploads
    whose datapoint is in this pack join its documents."""
    known = {d["id"] for d in pack.get("datapoints", [])}
    for code, item in added_items_of(node).items():
        if f"{node}:{code}" not in known and domain_of(code) == pack["pack"]["domain"]:
            pack["datapoints"].append(_datapoint(node, code, item, list(DEFAULT_PURPOSES)))
            known.add(f"{node}:{code}")
    have = {d["id"] for d in pack.get("documents", [])}
    for record in contributions_of(node):
        if record["document"]["datapoint"] in known and record["document"]["id"] not in have:
            # One copy of the text: the upload record keeps it, and the pack points to the record.
            doc = {k: v for k, v in record["document"].items() if k != "body"}
            doc["body_file"] = f"{CONTRIBUTIONS}/{doc['id'].split(':', 1)[1]}.json"
            pack["documents"].append(doc)
            have.add(doc["id"])
    return pack


def contribution_rows(node: str, pack: dict) -> list[tuple]:
    """The keyword-index rows of the uploads in this pack, in the shape of index.db: the title for a title-only item,
    the summary for a summary item, chunks of the body for a full-text item, nothing for a live item."""
    dps = {d["id"]: d for d in pack.get("datapoints", [])}
    bodies = {r["document"]["id"]: r["document"].get("body", "") for r in contributions_of(node)}  # the text is read from the record
    ids = set(bodies)
    rows = []
    for doc in pack.get("documents", []):
        if doc["id"] not in ids:
            continue
        dp = dps[doc["datapoint"]]
        ceiling = dp["ceiling"]
        tags = " ".join(doc.get("tags", []))
        version = str(doc.get("version", ""))
        stale = int(version[:4].isdigit() and int(version[:4]) < 2021)
        if dp.get("requires_approval") or ceiling == "MD":
            texts, mode = [(doc["title"], doc["id"])], "MD"
        elif ceiling == "SUM":
            texts, mode = [(doc.get("summary", ""), doc["id"])], "SUM"
        elif ceiling == "RAG":
            texts, mode = [(c, f"{doc['id']}#{i}") for i, c in enumerate(chunk_text(bodies.get(doc["id"]) or doc.get("body", "")))], "RAG"
        else:
            texts, mode = [], "LIVE"
        for text, key in texts:
            rows.append((text, doc["title"], tags, key, dp["catalogue_id"], mode, dp["sensitivity"], version, stale))
    return rows


def chunk_text(body: str, size: int = 600) -> list[str]:
    """Paragraphs, cut at a sentence end when longer than ``size`` characters (the rule of kbgen.py)."""
    out = []
    for para in [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]:
        para = " ".join(para.split())
        while len(para) > size:
            cut = para.rfind(". ", 0, size) + 1 or size
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        if para:
            out.append(para)
    return out


def write_index_rows(node: str, pack: dict) -> int:
    """Replace the index.db rows of the uploads in this pack with rows built now. Returns the number of rows written."""
    rows = contribution_rows(node, pack)
    domain = pack["pack"]["domain"]  # only the uploads of this pack: the rows of uploads in the node's other packs stay
    ids = {r["document"]["id"] for status in ("accepted", "rejected", "removed") for r in contributions_of(node, status)
           if domain_of(r["document"]["datapoint"].split(":", 1)[1]) == domain}
    con = sqlite3.connect(DATA / node / "index.db")
    try:
        for doc_id in ids:
            con.execute("DELETE FROM idx WHERE doc_id = ? OR doc_id LIKE ?", (doc_id, doc_id + "#%"))
        con.executemany("INSERT INTO idx VALUES (?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
    finally:
        con.close()
    return len(rows)


def rebuild_domain_pack(node: str, domain: str, build_vectors: bool = True) -> dict:
    """Rebuild one pack of a node from the knowledge file, the kept talent import and the accepted uploads, after an
    upload. Checked with every other pack, written beside the old file and renamed, then the keyword rows and the
    vectors of the pack are rebuilt. Nothing is written when a check fails."""
    annotations = yaml.safe_load((KB / "annotations.yaml").read_text(encoding="utf-8"))
    built = build_node_packs(node, annotations)
    if domain not in built:
        raise PackCheckFailed(f"{node} has no {domain} pack")
    pack = built[domain]
    if domain == "talent":
        pack = merge_talent_import(node, pack)
    pack = merge_contributions(node, pack)
    others = []
    for path in sorted(DATA.glob("*/packs/*/pack.json")):
        if path.parent.parent.parent.name == node and path.parent.name == domain:
            continue
        others.append((path.name, json.loads(path.read_text(encoding="utf-8"))))
    report = validate_packs([(f"{node}.{domain}.pack.json", pack)] + others + load_group_packs(), strict=True)
    if report.errors:
        raise PackCheckFailed("Pack validation failed: " + " | ".join(report.errors[:5]))
    out_dir = DATA / node / "packs" / domain
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = out_dir / ".pack.json.tmp"
    tmp.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, out_dir / "pack.json")
    rows = write_index_rows(node, pack)
    vectors = None
    if build_vectors:
        if not embedder.available():
            raise PackCheckFailed("The embedding model is missing, so the vector index cannot be built.")
        chunk_rows = [ChunkRow(doc_id, dp, mode, sens, str(version), int(stale), text or "", title or "")
                      for text, title, doc_id, dp, mode, sens, version, stale in index_rows(node)
                      if mode != "LIVE" and domain_of(dp) == domain]
        vectors = VectorIndex(out_dir / "build").build(chunk_rows)
    return {"pack_id": pack["pack"]["pack_id"], "documents": len(pack["documents"]), "index_rows": rows, "vectors": vectors}


def load_group_packs(folder: Path | None = None, incoming: dict[str, dict] | None = None) -> list[tuple[str, dict]]:
    """The group packs: the mesh's own and the group packs applications sent, with ``incoming`` in place of the kept
    file of the same name while an import is checked."""
    talent = folder or TALENT_IMPORT
    out = [(p.name, json.loads(p.read_text(encoding="utf-8"))) for p in sorted(GROUP.glob("*.pack.json"))]
    names = {p.name[: -len(".pack.json")] for p in talent.glob("group.*.pack.json")} if talent.is_dir() else set()
    names |= {name for name in (incoming or {}) if name.startswith("group.")}
    for name in sorted(names):
        pack = _kept(talent, name, incoming)
        if pack is not None:
            out.append((f"{name}.pack.json", pack))
    return out


def index_rows(node: str) -> list[tuple]:
    con = sqlite3.connect(DATA / node / "index.db")
    try:
        return con.execute("SELECT text, title, doc_id, dp, mode, sens, version, stale FROM idx").fetchall()
    finally:
        con.close()


def plan_talent_packs(nodes: list[str], talent_folder: Path | None = None, incoming: dict[str, dict] | None = None):
    """The talent pack of each node in ``nodes`` rebuilt from the kept talent imports, with ``incoming`` (kept name to
    pack) in place of the kept files of the same name, and the strict check of these packs together with every other
    pack on disk and the group packs, as build_all checks them. Writes nothing. The import tool runs this before it
    writes, so a pack is refused with the real reason instead of failing at the rebuild."""
    folder = talent_folder or TALENT_IMPORT
    annotations = yaml.safe_load((KB / "annotations.yaml").read_text(encoding="utf-8"))
    built: dict[str, dict] = {}
    for node in nodes:
        packs = build_node_packs(node, annotations)
        if "talent" in packs:
            built[f"{node}.talent"] = merge_talent_import(node, packs["talent"], folder, incoming)
    on_disk = []
    for path in sorted(DATA.glob("*/packs/*/pack.json")):
        pack = json.loads(path.read_text(encoding="utf-8"))
        if pack["pack"]["pack_id"] not in built:
            on_disk.append((f"{pack['pack']['pack_id']}.pack.json", pack))
    named = [(f"{pid}.pack.json", p) for pid, p in built.items()] + on_disk + load_group_packs(folder, incoming)
    return built, validate_packs(named, strict=True)


def rebuild_talent_packs(nodes: list[str], talent_folder: Path | None = None) -> list[str]:
    """Rebuild only the talent pack of each node in ``nodes`` from the kept talent imports, after an application sent
    new packs through the import tool. The packs are checked as plan_talent_packs checks them, and nothing is written
    when a check fails. The nodes read their pack files again when the files change (mcp_nodes/server.py), so no node
    restarts. The vector stores are not rebuilt: a talent import carries role profiles, not indexed text."""
    built, report = plan_talent_packs(nodes, talent_folder)
    if report.errors:
        raise PackCheckFailed("Pack validation failed: " + " | ".join(report.errors[:5]))
    for pid, pack in built.items():
        node, domain = pid.split(".")
        out_dir = DATA / node / "packs" / domain
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = out_dir / ".pack.json.tmp"  # written beside the pack and renamed: a node reads the old file or the new one
        tmp.write_text(json.dumps(pack, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, out_dir / "pack.json")
    return sorted(built)


def build_all(build_vectors: bool = True) -> dict:
    annotations = yaml.safe_load((KB / "annotations.yaml").read_text(encoding="utf-8"))
    all_packs: dict[str, dict] = {}
    for node in node_ids():
        for domain, pack in build_node_packs(node, annotations).items():
            if domain == "talent":
                pack = merge_talent_import(node, pack)
            pack = merge_contributions(node, pack)
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
            for pid, pack in all_packs.items():  # kbgen.py writes index.db without the uploads, so their rows go back in
                if pid.startswith(node + "."):
                    write_index_rows(node, pack)
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
                    raise SystemExit(f"Canary leaked into the Chroma store of {node}.{domain}: {leaked}")
    return summary


if __name__ == "__main__":
    result = build_all(build_vectors="--no-vectors" not in sys.argv)
    print(json.dumps(result, indent=2))
