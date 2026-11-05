#!/usr/bin/env python3
"""Validate NeuralMesh knowledge packs: JSON Schema first, then the rules a schema cannot express.

    pip install jsonschema
    python validate_packs.py examples/*.pack.json          # warnings for references to packs not loaded
    python validate_packs.py --strict examples/*.pack.json # unresolved references are errors

Exit code 0 when no errors are found, 1 otherwise.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("knowledge-pack.schema.json")
GROUP_NAMESPACES = {"org", "domain", "skill", "concept", "role", "rel"}
SYMMETRIC = {"RELATED_TO", "SAME_AS", "CONFLICTS_WITH", "SIMILAR_TO"}

# Allowed (from type, to type) pairs for each relationship type a pack may contain.
ENDPOINTS = {
    "MENTIONS": {("Document", "Concept"), ("Document", "Asset")},
    "EXPLAINS_SKILL": {("Document", "Skill")},
    "PART_OF_SKILL": {("Concept", "Skill")},
    "BROADER": {("Concept", "Concept"), ("Skill", "Skill")},
    "RELATED_TO": {("Concept", "Concept"), ("Skill", "Skill")},
    "SAME_AS": {("Concept", "Concept"), ("Skill", "Skill")},
    "CORROBORATES": {("Document", "Document")},
    "CONFLICTS_WITH": {("Document", "Document")},
    "SUPERSEDES": {("Document", "Document")},
    "ADDRESSES_GAP": {("Document", "Document")},
    "REQUIRES_SKILL": {("Role", "Skill")},
    "PREREQUISITE_OF": {("Skill", "Skill")},
    "HAS_SKILL": {("Expert", "Skill")},
    "EVIDENCED_BY": {("Expert", "Document")},
    "SIMILAR_TO": {("Role", "Role")},
}
# Type implied by an ID that is not in the loaded packs, so endpoint rules still apply to external references.
PREFIX_TYPES = {"skill": "Skill", "concept": "Concept", "domain": "Domain", "org": "Subsidiary"}


def namespace(entity_id: str) -> str:
    return entity_id.split(":", 1)[0]


def subsidiary_of(entity_id: str) -> str | None:
    ns = namespace(entity_id)
    return None if ns in GROUP_NAMESPACES else ns


def implied_type(entity_id: str) -> str | None:
    ns, local = entity_id.split(":", 1)
    if ns in PREFIX_TYPES:
        return PREFIX_TYPES[ns]
    if local.startswith("role/"):
        return "Role"
    if local.startswith("expert/"):
        return "Expert"
    if local.startswith("asset/"):
        return "Asset"
    if local.count("-") >= 2:
        return "Document"
    return None


class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"ERROR   {where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"WARNING {where}: {message}")


def expand_relationships(pack: dict) -> list[dict]:
    """Written relationships plus the ones implied by short forms on documents and experts."""
    pid = pack["pack"]["pack_id"]
    rels = list(pack.get("relationships", []))
    for doc in pack.get("documents", []):
        for concept in doc.get("concepts", []):
            rels.append({"id": f"short:{pid}", "type": "MENTIONS", "from": doc["id"], "to": concept, "status": "approved"})
        for item in doc.get("skills", []):
            rels.append({"id": f"short:{pid}", "type": "EXPLAINS_SKILL", "from": doc["id"], "to": item["skill"],
                         "status": "approved", "properties": {"level": item["level"]}})
        if doc.get("supersedes"):
            rels.append({"id": f"short:{pid}", "type": "SUPERSEDES", "from": doc["id"], "to": doc["supersedes"],
                         "status": "approved"})
    for expert in pack.get("experts", []):
        for item in expert.get("skills", []):
            rels.append({"id": f"short:{pid}", "type": "HAS_SKILL", "from": expert["id"], "to": item["skill"],
                         "status": "approved"})
        for evidence in expert.get("evidence", []):
            rels.append({"id": f"short:{pid}", "type": "EVIDENCED_BY", "from": expert["id"], "to": evidence,
                         "status": "approved"})
    return rels


def validate(paths: list[Path], strict: bool) -> int:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    report = Report()
    packs: list[tuple[Path, dict]] = []

    for path in paths:
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            report.error(path.name, f"cannot read JSON ({exc})")
            continue
        schema_errors = sorted(validator.iter_errors(pack), key=lambda e: list(e.absolute_path))
        for err in schema_errors:
            location = "/".join(str(p) for p in err.absolute_path) or "(root)"
            if err.validator == "not" and err.json_path == "$":
                message = "a pack with synthetic false must not carry test_fixtures"
            elif len(err.message) > 240:
                message = f"breaks the rule at {err.json_path} ({err.validator})"
            else:
                message = err.message
            report.error(path.name, f"schema: {location}: {message}")
        if not schema_errors:
            packs.append((path, pack))

    # Index every owned item across packs.
    types: dict[str, str] = {}
    owner_pack: dict[str, str] = {}
    datapoints: dict[str, dict] = {}
    documents: dict[str, dict] = {}
    for path, pack in packs:
        pid = pack["pack"]["pack_id"]
        owned = (
            [(d["id"], "Datapoint") for d in pack.get("datapoints", [])]
            + [(d["id"], "Document") for d in pack.get("documents", [])]
            + [(e["id"], e["type"]) for e in pack.get("entities", [])]
            + [(x["id"], "Expert") for x in pack.get("experts", [])]
        )
        for item_id, item_type in owned:
            if item_id in types:
                report.error(path.name, f"{item_id} is already defined in {owner_pack[item_id]}")
            types[item_id] = item_type
            owner_pack[item_id] = pid
        datapoints.update({d["id"]: d for d in pack.get("datapoints", [])})
        documents.update({d["id"]: d for d in pack.get("documents", [])})

    unresolved: Counter[str] = Counter()
    seen_pairs: dict[tuple[str, str, str], str] = {}
    totals: Counter[str] = Counter()

    for path, pack in packs:
        meta = pack["pack"]
        pid, scope, sub = meta["pack_id"], meta["scope"], meta["subsidiary"]
        where = path.name

        if scope == "subsidiary" and pid != f"{sub}.{meta['domain']}":
            report.error(where, f"pack_id must be '{sub}.{meta['domain']}'")
        if scope == "group" and not pid.startswith("group."):
            report.error(where, "a group pack_id starts with 'group.'")

        # Ownership: a subsidiary pack owns only its own namespace, a group pack only group namespaces.
        for item_id, pack_id in owner_pack.items():
            if pack_id != pid:
                continue
            ns = namespace(item_id)
            if scope == "subsidiary" and ns != sub:
                report.error(where, f"{item_id} is outside the namespace '{sub}' of this pack")
            if scope == "group" and ns not in GROUP_NAMESPACES:
                report.error(where, f"{item_id} belongs to a subsidiary, not to a group pack")

        pack_dps = {d["id"]: d for d in pack.get("datapoints", [])}
        for doc in pack.get("documents", []):
            dp = pack_dps.get(doc["datapoint"])
            if dp is None:
                report.error(where, f"{doc['id']} points to datapoint {doc['datapoint']}, which is not in this pack")
                continue
            ceiling = dp["ceiling"]
            if ceiling in ("SUM", "RAG", "LIVE") and not doc.get("summary"):
                report.error(where, f"{doc['id']} needs an approved summary because its datapoint allows {ceiling}")
            if ceiling == "RAG" and not (doc.get("body") or doc.get("body_file")):
                report.error(where, f"{doc['id']} needs a body because its datapoint allows RAG")
            if doc.get("gated") and not (dp.get("requires_approval") or dp.get("upgrade_with_approval")):
                report.error(where, f"{doc['id']} is gated but {dp['id']} declares no approval path")
            if doc.get("skills") and ceiling == "MD":
                report.error(where, f"{doc['id']} cannot explain a skill: its datapoint is metadata only")
            if doc.get("skills") and "learning" not in dp.get("purposes_allowed", []):
                report.warn(where, f"{doc['id']} explains a skill but {dp['id']} does not allow the purpose "
                                   f"'learning', so SkillForge cannot use it as study material")

        for expert in pack.get("experts", []):
            if not expert["consent"]:
                report.warn(where, f"{expert['id']} has no consent: kept at the node, never searchable or published")

        for rel in expand_relationships(pack):
            totals[rel["type"]] += 1
            a, b, rtype = rel["from"], rel["to"], rel["type"]
            label = rel["id"] if not rel["id"].startswith("short:") else f"{a} {rtype} {b}"
            if a == b:
                report.error(where, f"{label} points to itself")
            for end in (a, b):
                if end not in types:
                    unresolved[end] += 1
            ta = types.get(a) or implied_type(a)
            tb = types.get(b) or implied_type(b)
            if ta and tb and (ta, tb) not in ENDPOINTS[rtype]:
                report.error(where, f"{label}: {rtype} cannot join {ta} to {tb}")

            sa, sb = subsidiary_of(a), subsidiary_of(b)
            crosses = sa is not None and sb is not None and sa != sb
            if crosses and scope != "group":
                report.error(where, f"{label} joins {sa} and {sb}, so it belongs in a group links pack")
            if crosses and rel.get("status") == "approved":
                approved_by = {item["subsidiary"] for item in rel.get("approvals", [])}
                missing = {sa, sb} - approved_by
                if missing:
                    report.error(where, f"{label} is approved without an approval from {', '.join(sorted(missing))}")
            if scope == "subsidiary":
                for end, ns in ((a, sa), (b, sb)):
                    if ns is not None and ns != sub:
                        report.error(where, f"{label} refers to {end}, owned by another subsidiary")

            key = (rtype, *sorted((a, b))) if rtype in SYMMETRIC else (rtype, a, b)
            if key in seen_pairs:
                report.error(where, f"{label} repeats a relationship already in {seen_pairs[key]}")
            seen_pairs[key] = pid

    # Canary strings may appear only in test_fixtures.
    for path, pack in packs:
        canaries = [c["value"] for c in pack.get("test_fixtures", {}).get("canaries", [])]
        stripped = {k: v for k, v in pack.items() if k != "test_fixtures"}
        text = json.dumps(stripped, ensure_ascii=False)
        for value in canaries:
            if value in text:
                report.error(path.name, f"canary {value} appears outside test_fixtures")
        for other_path, other in packs:
            if other_path != path:
                other_text = json.dumps(other, ensure_ascii=False)
                for value in canaries:
                    if value in other_text:
                        report.error(other_path.name, f"canary {value} of {path.name} appears in this pack")

    for ref, count in sorted(unresolved.items()):
        message = f"{ref} is referenced {count} time(s) but defined in none of the loaded packs"
        (report.error if strict else report.warn)("references", message)

    for line in report.errors + report.warnings:
        print(line)
    print()
    print(f"Packs read: {len(paths)}, valid against the schema: {len(packs)}")
    for path, pack in packs:
        counts = {k: len(pack.get(k, [])) for k in ("datapoints", "documents", "entities", "experts", "relationships")}
        print(f"  {pack['pack']['pack_id']}: " + ", ".join(f"{v} {k}" for k, v in counts.items() if v))
    print("Relationships after short forms are expanded: "
          + ", ".join(f"{t} {n}" for t, n in sorted(totals.items())))
    print(f"Errors: {len(report.errors)}, warnings: {len(report.warnings)}")
    return 1 if report.errors else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("packs", nargs="+", type=Path)
    parser.add_argument("--strict", action="store_true", help="treat references to packs not loaded as errors")
    args = parser.parse_args()
    sys.exit(validate(args.packs, args.strict))


if __name__ == "__main__":
    main()
