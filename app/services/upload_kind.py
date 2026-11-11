"""The kind of an uploaded document when the person leaves it to the mesh: a model step reads the file name, the title
and the first lines and picks one of the kinds of the pack format. When the model may not see the item's records (the
model policy refuses its sensitivity), is not configured, or gives no usable reply, a few word rules decide instead.
The record keeps which way decided, so the choice can be checked."""
from __future__ import annotations

import json
import re
from typing import Any

FIRST_CHARS = 1200  # the part of the text the model reads: the opening is where a document says what it is

# (kind, words in the file name, title or first lines that point to it), tried in this order
RULES: list[tuple[str, tuple[str, ...]]] = [
    ("post_mortem", ("post-mortem", "post mortem", "postmortem", "lessons learned", "lessons from", "after action", "first 100 days")),
    ("rca", ("root cause", "rca", "teardown", "failure analysis", "why-why", "5 whys", "out of specification", "out-of-specification", "investigation")),
    ("sop", ("sop", "standard operating procedure", "procedure", "work instruction")),
    ("playbook", ("playbook", "runbook", "checklist", "guide", "cut-over", "cutover")),
    ("policy", ("policy", "guidance note", "code of conduct", "responsible ai", "rules for")),
    ("standard", ("specification", "standard", "grades", "limits", "tolerance")),
    ("role_profile", ("role profile", "job description", "duties", "responsibilities of the role")),
    ("study_material", ("training", "course", "module", "lesson plan", "study material")),
    ("note", ("minutes", "note", "memo", "meeting")),
    ("report", ("report", "audit", "findings", "results", "study", "review", "survey", "pilot", "scorecard", "summary", "trial", "status")),
]


def _looks_like_a_table(head: str) -> bool:
    """Plain text whose lines carry the same number of commas, at least 3 each, over at least 4 lines."""
    rows = [line.count(",") for line in head.splitlines() if line.strip()]
    return len(rows) >= 4 and min(rows) >= 3 and max(rows) == min(rows)


def by_rules(title: str, filename: str, text: str, fmt: str = "") -> dict[str, Any]:
    """The kind from word rules: a table of figures is aggregate, otherwise the first rule whose words appear."""
    name = f"{filename} {title}".lower().replace("_", " ")
    head = text[:FIRST_CHARS].lower()
    if fmt == "csv" or (fmt not in ("json", "pdf", "docx") and _looks_like_a_table(text[:FIRST_CHARS])):
        return {"kind": "aggregate", "label": "", "by": "rules", "reason": "a table of figures"}
    for where, place in ((name, "file name or title"), (head, "first lines")):  # what the file calls itself counts first
        for kind, words in RULES:
            hit = next((w for w in words if re.search(rf"(?<![a-z]){re.escape(w)}(?![a-z])", where)), None)
            if hit:
                return {"kind": kind, "label": "", "by": "rules", "reason": f'the words "{hit}" in the {place}'}
    return {"kind": "report", "label": "", "by": "rules", "reason": "no rule matched, report is the default"}


def detect(title: str, filename: str, text: str, kinds: list[str], *, fmt: str = "", call_model=None) -> dict[str, Any]:
    """The kind of the document: by the model when ``call_model`` gives a usable reply, otherwise by the rules.
    ``call_model`` is the caller of services.context.llm.make_caller, already bound to the item's sensitivity."""
    if call_model is not None:
        from services.context import prompts
        try:
            prompt = prompts.load("kind")
            reply = call_model("kind", prompt.text, f"File name: {filename}\nTitle: {title}\n\nFirst lines:\n{text[:FIRST_CHARS]}", prompt.version)
        except Exception:  # noqa: BLE001 - a step missing from the model policy, or a failed call: the rules decide
            reply = None
        if reply:
            try:
                cleaned = reply.strip().strip("`")
                cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
                parsed = json.loads(cleaned[cleaned.find("{"): cleaned.rfind("}") + 1])
                kind = str(parsed.get("kind", "")).strip()
                label = " ".join(str(parsed.get("label") or "").split())[:60]
                if kind in kinds and (kind != "other" or len(label) >= 2):
                    return {"kind": kind, "label": label if kind == "other" else "", "by": "model", "reason": str(parsed.get("reason", ""))[:120]}
            except (ValueError, AttributeError):
                pass
    return by_rules(title, filename, text, fmt)
