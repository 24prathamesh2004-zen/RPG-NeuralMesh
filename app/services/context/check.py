"""Check step: code, not a model. An answer that fails any rule is not shown."""
from __future__ import annotations

import re

from contracts.evidence import EvidenceRecord
from services.context.answer import NO_EVIDENCE
from services.context.pii import has_contact_details

MAX_SENTENCES = 10
_STOP = frozenset("that this with from have been were their there these those which would could should about after before".split())
# Words a sentence may use when it only names a withheld item, besides the item's own title, reason, rule and datapoint.
_WITHHOLD_WORDS = frozenset(
    "withheld withhold restricted metadata only access approval approved approve owner policy rule record document item title "
    "available released release blocked block hidden content text full detail details request requested needs need requires "
    "required under shown share shared cannot because kept stays within subsidiary company node exposure ceiling mode summary "
    "confidential internal public datapoint window blackout results pending grant cross boundary leave leaves formulation".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3 and w not in _STOP}


def sentences(answer: str) -> list[str]:
    parts = re.split(r"(?<=[.!?\]])\s+(?=[A-Z\[])", answer.strip())
    return [p.strip() for p in parts if p.strip() and len(p.strip()) > 2]


def run_checks(answer: str, bundle_ids: set[str], also_found_ids: set[str], withheld: list[EvidenceRecord],
               conflicts: list[tuple[str, str]], removed_instructions: list[str], canaries: list[str]) -> list[dict]:
    failures = []
    withheld_by_id = {w.evidence_id: w for w in withheld}
    parts = sentences(answer)
    if len(parts) > MAX_SENTENCES:
        failures.append({"rule": 7, "detail": f"{len(parts)} sentences, the limit is {MAX_SENTENCES}"})
    for s in parts:
        cites = re.findall(r"\[([^\]]+)\]", s)
        cites = [c for c in cites if c != NO_EVIDENCE.strip("[]")]
        if s.startswith(NO_EVIDENCE):
            continue
        if not cites:
            failures.append({"rule": 1, "detail": f"sentence without citation: {s[:80]}"})
        for c in cites:
            if c in also_found_ids:
                failures.append({"rule": 1, "detail": f"cites an also-found document {c}"})
            elif c not in bundle_ids:
                failures.append({"rule": 1, "detail": f"cites {c}, which is not in the bundle"})
        if cites and all(c in withheld_by_id for c in cites):
            allowed = set(_WITHHOLD_WORDS)
            for c in cites:
                w = withheld_by_id[c]
                allowed |= _words(" ".join(filter(None, [w.title, w.reason, w.rule_id, w.datapoint, w.decision, w.node])))
            extra = _words(re.sub(r"\[[^\]]+\]", " ", s)) - allowed
            if extra:
                failures.append({"rule": 3, "detail": f"content attributed to withheld item {cites[0]}: {', '.join(sorted(extra))[:80]}"})
    for c in canaries:
        if c in answer:
            failures.append({"rule": 2, "detail": "canary string in the answer"})
    for w in withheld:
        if w.text and w.text in answer:
            failures.append({"rule": 3, "detail": f"text of withheld item {w.evidence_id}"})
    for a, b in conflicts:
        if not (a in answer and b in answer):
            failures.append({"rule": 4, "detail": f"conflict between {a} and {b} not shown on both sides"})
    for instr in removed_instructions:
        probe = instr.lower()[:40]
        if probe and probe in answer.lower():
            failures.append({"rule": 5, "detail": "repeats a removed instruction"})
    if has_contact_details(answer):
        failures.append({"rule": 6, "detail": "email address or phone number in the answer"})
    return failures
