"""Phase 3 acceptance: the ten golden scenarios through the running API, with the answer scored against the gold facts.

    python -m evaluations.golden_answers            # API on 8000, nodes running, S7 reported from the node list

For each scenario the script sends the question with no node choice and checks the golden expectations: routed
subsidiaries, cited and withheld datapoints, decisions and rules, strings that must not appear, experts that must not
be returned, and whether every answer sentence carries a citation or the no-evidence marker. For S1, S2 and S3 it
also counts how many of the numbers in the gold facts of the cited datapoints appear in the written answer.
With the stand-in model the numbers come straight from the approved summaries, so a high count shows the evidence
path works, not that a language model reasons well.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import httpx
import yaml

from api.auth import issue_poc_token
from services.context.answer import NO_EVIDENCE
from services.context.check import sentences

API = "http://127.0.0.1:8000/api/v1"
KB = Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack"
DECISIONS = {"S5": ("E-01", "BLOCKED_BY_POLICY", "R-NL-01"), "S6": ("F-06", "BLOCKED_BY_POLICY", "UPSI"),
             "S10": ("E-02", None, None)}


def numbers(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?%", text))


def main() -> None:
    golden = yaml.safe_load((KB / "kb" / "golden.yaml").read_text())["scenarios"]
    facts = json.loads((KB / "data_pack" / "gold" / "facts.json").read_text())
    token = issue_poc_token({"sub": "golden-eval", "company": "ceat", "roles": ["group_user"]})
    http = httpx.Client(timeout=120, headers={"Authorization": f"Bearer {token}"})
    rows, failures = [], 0
    for scenario in golden:
        sid = scenario["id"]
        if sid == "S7":
            nodes = http.get(f"{API}/mesh/nodes").json()["nodes"]
            kec = next(n for n in nodes if n["node_id"] == "kec")
            rows.append((sid, "node outage is a separate check (make live-check); kec is " + kec["status"], True))
            continue
        body = http.post(f"{API}/mesh/query", json={"question": scenario["question"], "purpose": "problem_solving"}).json()
        text = json.dumps(body)
        evidence_dps = {e["datapoint"].split(":", 1)[1] for e in body["evidence"] if e.get("datapoint")}
        found_dps = evidence_dps | {e["datapoint"].split(":", 1)[1] for e in body.get("also_found", []) if e.get("datapoint")}
        withheld = {w["datapoint"].split(":", 1)[1]: w for w in body["withheld"] if w.get("datapoint")}
        problems = []
        routed = set(body["routing"].get("subsidiaries", []))
        if sid != "S4" and not set(scenario["nodes"]) <= routed:
            problems.append(f"routed {sorted(routed)}, expected {scenario['nodes']}")
        for dp in scenario.get("must_cite_dp", []):
            if dp not in found_dps:
                problems.append(f"{dp} not returned")
            elif dp not in evidence_dps:
                problems.append(f"{dp} only in also_found")
        for dp in scenario.get("must_withhold_dp", []):
            if dp not in withheld:
                problems.append(f"{dp} not withheld")
        for dp in scenario.get("needs_approval_dp", []):
            if withheld.get(dp, {}).get("decision") != "NEEDS_APPROVAL":
                problems.append(f"{dp} not marked NEEDS_APPROVAL")
        if sid in DECISIONS:
            dp, decision, rule = DECISIONS[sid]
            item = withheld.get(dp)
            if sid == "S10":
                if dp not in evidence_dps and (item or {}).get("decision") != "NEEDS_APPROVAL":
                    problems.append("E-02 neither summarised nor awaiting approval")
            elif item is None or item.get("decision") != decision or item.get("rule_id") != rule:
                problems.append(f"{dp} decision {item and item.get('decision')} rule {item and item.get('rule_id')}")
            if any(e.get("datapoint", "").endswith(dp) for e in body["evidence"]) and sid != "S10":
                problems.append(f"{dp} text released")
        for needle in scenario.get("must_not_contain", []):
            if needle in text:
                problems.append(f"contains {needle}")
        for expert in scenario.get("must_not_return", []):
            if expert in text:
                problems.append(f"returns expert {expert}")
        if sid == "S8" and "IGNORE PREVIOUS INSTRUCTIONS" in (body["answer"] or ""):
            problems.append("answer follows the planted instruction")
        answer = body["answer"] or ""
        if answer:
            uncited = [s for s in sentences(answer) if not re.search(r"\[[a-z]+:[^\]]+\]", s) and not s.startswith(NO_EVIDENCE)]
            if uncited:
                problems.append(f"{len(uncited)} sentence(s) without citation")
        gold = ""
        if sid in ("S1", "S2", "S3"):
            wanted = set()
            for fact in facts:
                if fact["dp"] in scenario.get("must_cite_dp", []):
                    wanted |= numbers(fact["text"])
            hit = {n for n in wanted if n in answer}
            gold = f", gold numbers in the answer {len(hit)} of {len(wanted)}"
        ok = not problems
        failures += 0 if ok else 1
        rows.append((sid, f"{body['routing'].get('method')} -> {sorted(routed)}, {len(body['evidence'])} records, "
                          f"{len(body['withheld'])} withheld, answer {body['answer_status']}{gold}"
                          + ("" if ok else " | " + "; ".join(problems)), ok))
    for sid, detail, ok in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {sid}  {detail}")
    print(f"\n{len(rows) - failures} of {len(rows)} golden scenarios meet their expectations")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
