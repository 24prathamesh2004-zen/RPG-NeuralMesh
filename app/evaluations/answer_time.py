"""Answer time: how long the running API takes to answer the golden questions, step by step.

    python -m evaluations.answer_time              # API on 8000, nodes running
    python -m evaluations.answer_time --rounds 3   # each question asked this many times (default 2)

Every golden scenario except S7 (the node outage) is asked with no node choice. The first round of a question is a
cold answer (no cached answer). A repeat of the same question with the same evidence is served from the answer cache,
so the rounds after the first measure the path without the answer model. The script prints the median and the 90th
percentile of the wall time for cold answers and for cached answers, the median of each step of the flow (resolve,
route, fan_out, scope, expand, build_answer) and the slowest question. The target of the plan is a median of 10
seconds for a cold answer.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

import httpx
import yaml

from api.auth import issue_poc_token

API = "http://127.0.0.1:8000/api/v1"
KB = Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack"
STEPS = ["resolve", "route", "fan_out", "scope", "expand", "build_answer", "assemble"]
TARGET_SECONDS = 10.0


def percentile(values: list[float], share: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(share * (len(ordered) - 1))))]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    golden = [s for s in yaml.safe_load((KB / "kb" / "golden.yaml").read_text())["scenarios"] if s["id"] != "S7"]
    token = issue_poc_token({"sub": "timing-eval", "company": "ceat", "roles": ["group_user"]})
    http = httpx.Client(timeout=180, headers={"Authorization": f"Bearer {token}"})
    cold: list[tuple[str, float, dict]] = []
    cached: list[tuple[str, float]] = []
    step_ms: dict[str, list[float]] = {s: [] for s in STEPS}
    for scenario in golden:
        for round_no in range(args.rounds):
            started = time.perf_counter()
            body = http.post(f"{API}/mesh/query", json={"question": scenario["question"], "purpose": "problem_solving"}).json()
            seconds = time.perf_counter() - started
            steps = {s["step"]: s["ms"] for s in body.get("steps", [])}
            if body.get("cached"):
                cached.append((scenario["id"], seconds))
            else:
                cold.append((scenario["id"], seconds, steps))
                for name in STEPS:
                    if name in steps:
                        step_ms[name].append(steps[name])
            status = body.get("answer_status")
            print(f"{scenario['id']:<4} round {round_no + 1}  {seconds:6.2f} s  {'cached' if body.get('cached') else 'cold  '}  "
                  f"{status}  {len(body.get('evidence', []))} records")
    print()
    if cold:
        times = [t for _, t, _ in cold]
        median = statistics.median(times)
        print(f"Cold answers ({len(times)}): median {median:.2f} s, 90th percentile {percentile(times, 0.9):.2f} s, "
              f"slowest {max(cold, key=lambda c: c[1])[0]} at {max(times):.2f} s")
        print(f"Target of the plan: a median of {TARGET_SECONDS:.0f} s for a cold answer, "
              + ("met" if median <= TARGET_SECONDS else "not met"))
        print("Median of each step (cold answers, ms): " + ", ".join(
            f"{name} {statistics.median(values):.0f}" for name, values in step_ms.items() if values))
    if cached:
        times = [t for _, t in cached]
        print(f"Cached answers ({len(times)}): median {statistics.median(times):.2f} s, 90th percentile {percentile(times, 0.9):.2f} s")
    answered = sum(1 for _, _, s in cold if s) if cold else 0
    sys.exit(0 if cold and statistics.median([t for _, t, _ in cold]) <= TARGET_SECONDS else 1)


if __name__ == "__main__":
    main()
