"""Phase 1 acceptance: recall on reworded golden questions (2 per scenario, 18 without S4), keyword search alone against hybrid search.

    python -m evaluations.reworded_recall

Each golden question is rewritten twice without the keywords of its expected documents. A question counts as
recalled when every required datapoint appears among the top 10 items (released or withheld) of the nodes the
golden scenario names. Both numbers are printed. The questions were written for this measure with the expected
datapoints known, so they test vector search on other wording, not unseen questions in general.
"""
from __future__ import annotations

from unittest import mock

import yaml

from mcp_nodes import knowledge_view
from mcp_nodes.auth import CallerContext
from mcp_nodes.server import load_node_config, search_node

REWORDED = {
    "S1": ["How could the tyre business help the plantation stop collected milk from going sour before processing?",
           "Which practices at the tyre maker would cut losses of field latex at the estates?"],
    "S2": ["What mistakes did we make in the first three months after buying companies abroad, and what list of steps should we use?",
           "Lessons from taking over foreign firms: what failed early and what should the to-do list be?"],
    "S3": ["Which breakdowns and hold-ups keep coming back at our factories and sites?",
           "Where do the same faults and schedule slips happen again and again?"],
    "S4": ["Who has handled merging a foreign business or problems with raw-material vendors?",
           "Find people who know about joining up an overseas company or fixing vendor issues."],
    "S5": ["Give me the recipe of the tyre tread mix.",
           "What goes into the tread rubber blend?"],
    "S6": ["Show the tyre company's spending comparisons before the quarterly numbers are out.",
           "What are the investment comparisons ahead of the results announcement?"],
    "S7": ["Same as the takeover lessons, with the engineering company offline.",
           "Takeover lessons abroad while the transmission business node is down."],
    "S8": ["How do new staff get started at the IT company?",
           "What should a new hire at the software firm do in the first week?"],
    "S9": ["How can project teams use coding helpers without risk, and what did trials show?",
           "Safe use of AI tools in delivery work and results from experiments."],
    "S10": ["I need the complete root-cause write-ups on defects from storage at the tyre plant.",
            "Full failure investigations linked to how material is kept at the tyre factory."],
}
DECISION_DATAPOINTS = {"S5": ["E-01"], "S6": ["F-06"], "S10": ["E-02"], "S8": ["C-05"], "S4": []}


def expected(scenario: dict, golden: list[dict]) -> set[str]:
    if scenario["id"] == "S7":
        scenario = next(s for s in golden if s["id"] == "S2")
    return (set(scenario.get("must_cite_dp", [])) | set(scenario.get("must_withhold_dp", []))
            | set(scenario.get("needs_approval_dp", [])) | set(DECISION_DATAPOINTS.get(scenario["id"], [])))


def returned(question: str, nodes: list[str]) -> set[str]:
    found = set()
    for node in nodes:
        config = load_node_config(node)
        caller = CallerContext("eval", node, frozenset({"group_user"}), "problem_solving")
        response = search_node(config, caller, question, "problem_solving")
        found |= {i["datapoint_id"] for i in response["results"] + response["withheld"]}
    return found


def measure(golden: list[dict]) -> tuple[int, int, list[str]]:
    hits, total, missed = 0, 0, []
    for scenario in golden:
        need = expected(scenario, golden)
        nodes = scenario["nodes"] if scenario["id"] != "S7" else ["ceat", "zensar"]
        if scenario["id"] == "S7":
            need -= {"L-02", "L-02a"}
        for question in REWORDED[scenario["id"]]:
            total += 1
            got = returned(question, nodes)
            if need <= got:
                hits += 1
            else:
                missed.append(f"{scenario['id']}: missing {sorted(need - got)}")
    return hits, total, missed


def main() -> None:
    from pathlib import Path

    golden = yaml.safe_load((Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack" / "kb" / "golden.yaml").read_text())["scenarios"]
    # Scenarios without reworded questions here (S11 to S15, the wave 2 nodes) are left out and named: the labelled
    # questions of evaluations/labelled_questions.py cover the documents of those nodes.
    left_out = [s["id"] for s in golden if s["id"] not in REWORDED]
    golden = [s for s in golden if s["id"] != "S4" and s["id"] in REWORDED]
    if left_out:
        print(f"No reworded questions for {', '.join(left_out)}, so they are left out of this measure")
    with mock.patch.object(knowledge_view, "_vector_keys", lambda *a, **k: []):
        kw_hits, total, kw_missed = measure(golden)
    hy_hits, _, hy_missed = measure(golden)
    print(f"Reworded questions: {total} (S4 is judged on experts and left out)")
    print(f"Keyword search alone: {kw_hits} of {total} with every required datapoint in the top 10")
    print(f"Hybrid search:        {hy_hits} of {total}")
    print("Missed by hybrid search:" if hy_missed else "Missed by hybrid search: none")
    for line in hy_missed:
        print("  " + line)


if __name__ == "__main__":
    main()
