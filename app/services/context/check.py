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
    "withheld withhold reason restricted metadata only access approval approved approve owner policy rule record document item title "
    "available released release blocked block hidden content text full detail details request requested needs need requires "
    "required under shown share shared cannot because kept stays within subsidiary company node exposure ceiling mode summary "
    "confidential internal public datapoint window blackout results pending grant cross boundary leave leaves formulation".split()
)


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 3 and w not in _STOP}


_MARK = "\x00NOEVIDENCE\x00"
# A sentence ends at ., ! or ? (or a closing citation bracket) followed by a space and a capital letter, a citation or
# the marker. Not after an abbreviation such as "e.g." or "i.e.", which never ends a sentence of an answer.
_SENTENCE_END = re.compile(
    r"(?<=[.!?\]])(?<!\be\.g\.)(?<!\bE\.g\.)(?<!\bi\.e\.)(?<!\bI\.e\.)(?<!\bvs\.)(?<!\bcf\.)(?<!\bapprox\.)(?<!\bincl\.)"
    r"(?<!\bNo\.)(?<!\bno\.)(?<!\bDr\.)(?<!\bMr\.)(?<!\bMs\.)(?<!\bMrs\.)\s+(?=[A-Z\[\x00])")


def sentences(answer: str) -> list[str]:
    """Split on sentence ends. The [NOT IN EVIDENCE] marker opens a sentence, so it must not count as one."""
    text = answer.strip().replace(NO_EVIDENCE, _MARK)
    parts = _SENTENCE_END.split(text)
    return [p.strip().replace(_MARK, NO_EVIDENCE) for p in parts if p.strip() and len(p.strip()) > 2]


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


def _cited(detail: str) -> str:
    words = [w for w in detail.replace(",", " ").split() if ":" in w]
    return words[0] if words else "a record"


def fix_line(failure: dict) -> str:
    """One broken rule as an instruction for the answer model's second try."""
    rule, detail = failure.get("rule"), str(failure.get("detail", ""))
    if rule == 1 and detail.startswith("sentence without citation"):
        return f"This sentence cites no record: \"{detail.split(': ', 1)[-1]}\". Cite a record for it, or leave it out."
    if rule == 1:
        return f"It cites {_cited(detail)}, which is not one of the records given. Cite only the records given."
    if rule == 3:
        return f"It says more about the withheld item {_cited(detail)} than its title and reason. Say only that it is withheld and why."
    if rule == 4:
        a, _, b = detail.removeprefix("conflict between ").partition(" and ")
        b = b.split(" not shown")[0]
        return f"The records {a} and {b} conflict. Show both sides, each with its citation."
    if rule == 5:
        return "It repeats an instruction that was removed from a record. Leave it out."
    if rule == 6:
        return "It holds an email address or a phone number. Leave it out."
    if rule == 7:
        return f"It is too long ({detail}). Use at most {MAX_SENTENCES} sentences."
    return "It holds a test string. Leave it out."


def plain_reason(failures: list[dict]) -> str:
    """Why the written answer is not shown, in words for the person who asked."""
    why = []
    for failure in failures:
        rule, detail = failure.get("rule"), str(failure.get("detail", ""))
        if rule == 1:
            text = ("a sentence cited no record" if detail.startswith("sentence without citation")
                    else "it cited a record that is not part of the evidence")
        elif rule == 3:
            text = "it said more about a withheld item than its title and reason"
        elif rule == 4:
            a, _, b = detail.removeprefix("conflict between ").partition(" and ")
            text = f"it did not show both sides of the conflict between {a} and {b.split(' not shown')[0]}"
        elif rule == 5:
            text = "it repeated an instruction that was removed from a record"
        elif rule == 6:
            text = "it held an email address or a phone number"
        elif rule == 7:
            text = f"it was longer than {MAX_SENTENCES} sentences"
        else:
            text = "it held a test string"
        if text not in why:
            why.append(text)
    listed = why[0] if len(why) == 1 else ", ".join(why[:-1]) + " and " + why[-1]
    return f"The written answer is not shown, because {listed}, also after a second try. The evidence is listed below."
