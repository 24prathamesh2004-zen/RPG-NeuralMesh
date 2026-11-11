"""Help chat: answers questions about the NeuralMesh application itself (pages, concepts, how to do things).

It is grounded in the app's own guides, not in subsidiary knowledge: the Markdown files of app/help_kb, the current
planning documents (Markdown and HTML) and the live node registry. Retrieval is BM25 over sections of those files.
The answer model is the one the model policy names for the "answer" step. With no usable model the chat returns the
best matching sections, so it still helps. Questions about company knowledge are sent to Ask NeuralMesh, which applies
the node policies. The help chat never calls a Mesh Node."""
from __future__ import annotations

import html
import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
HELP_KB = APP_ROOT / "help_kb"
PLANNING = APP_ROOT.parent / "planning_docs"
# Target designs, not the running app: kept out so the chat does not describe screens that do not exist.
EXCLUDED = {"RPG_NeuralMesh_Wireframe_v4.html"}
CHUNK_CHARS = 1600
TOP_K = 6
MAX_HISTORY = 6

STOP = set("""a an the and or but in on at to for of with by from is are was were be been being have has had do does did
will would could should may might can shall you your we our they their it its this that these those not no so if then
than too very just about all also any each more most other some such only own same into over under up out here there
when where why how which who whom what me my i please tell show give""".split())


@dataclass(frozen=True)
class Section:
    source: str  # file name
    title: str   # document title
    heading: str
    text: str


def _tokens(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9][a-z0-9-]*", text.lower())
    out = []
    for w in words:
        if w in STOP or len(w) < 2:
            continue
        for suffix in ("ing", "es", "s"):
            if w.endswith(suffix) and len(w) > len(suffix) + 3:
                w = w[: -len(suffix)]
                break
        out.append(w)
    return out


def _html_to_markdownish(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|svg|head)\b.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<h([1-4])[^>]*>", lambda m: "\n" + "#" * int(m.group(1)) + " ", raw)
    raw = re.sub(r"(?i)</h[1-4]>", "\n", raw)
    raw = re.sub(r"(?i)<(br|/p|/li|/tr|/div)[^>]*>", "\n", raw)
    raw = re.sub(r"(?i)<li[^>]*>", "\n- ", raw)
    raw = re.sub(r"(?i)</t[dh]>", " | ", raw)
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = html.unescape(raw)
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in raw.splitlines())


def _split(source: str, text: str) -> list[Section]:
    title_match = re.search(r"^#\s+(.+)$", text, re.M)
    title = title_match.group(1).strip() if title_match else source
    sections: list[Section] = []
    heading, buf = title, []

    def flush() -> None:
        body = "\n".join(buf).strip()
        while body:
            piece, body = body[:CHUNK_CHARS], body[CHUNK_CHARS:]
            if len(piece.strip()) > 40:
                sections.append(Section(source, title, heading, piece.strip()))

    for line in text.splitlines():
        m = re.match(r"^#{1,4}\s+(.+)$", line)
        if m:
            flush()
            heading, buf = m.group(1).strip(), []
        elif line.strip():
            buf.append(line)
    flush()
    return sections


def _registry_section() -> list[Section]:
    try:
        from shared.registry import registered_nodes
        rows = [f"- {n.display} (id {n.node_id}): port {n.port}, maturity level {n.level}"
                + (", shared node for inputs that belong to no one company" if getattr(n, "shared", False) else "")
                for n in registered_nodes()]
    except Exception:  # noqa: BLE001 - the chat still works from the documents
        return []
    text = "The companies connected to NeuralMesh, one Mesh Node (MCP server) per company, as registered in config/nodes.yaml:\n" + "\n".join(rows)
    return [Section("config/nodes.yaml", "Node registry (live)", "Connected company nodes (Mesh Nodes)", text)]


class HelpIndex:
    def __init__(self, sections: list[Section]) -> None:
        self.sections = sections
        self.docs = [Counter(_tokens(f"{s.title} {s.heading} {s.heading} {s.text}")) for s in sections]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lengths) / len(self.lengths)) if self.lengths else 1.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}

    def search(self, query: str, k: int = TOP_K) -> list[tuple[float, Section]]:
        terms = set(_tokens(query))
        scored = []
        for i, d in enumerate(self.docs):
            score = 0.0
            for t in terms:
                f = d.get(t, 0)
                if f:
                    score += self.idf[t] * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * self.lengths[i] / self.avg))
            if self.sections[i].source.startswith("help_kb/"):
                score *= 1.3  # the hand-written guide describes the running app
            heading_terms = set(_tokens(self.sections[i].heading))
            if terms and heading_terms and len(terms & heading_terms) / len(terms) >= 0.6:
                score *= 1.5  # the section heading says what the question asks
            if score > 0:
                scored.append((score, self.sections[i]))
        scored.sort(key=lambda x: -x[0])
        return scored[:k]


@lru_cache(maxsize=1)
def help_index() -> HelpIndex:
    sections: list[Section] = []
    for path in sorted(HELP_KB.glob("*.md")):
        sections += _split(f"help_kb/{path.name}", path.read_text(encoding="utf-8"))
    if PLANNING.is_dir():
        for path in sorted(PLANNING.glob("*.md")):
            sections += _split(path.name, path.read_text(encoding="utf-8"))
        for path in sorted(PLANNING.glob("*.html")):
            if path.name not in EXCLUDED:
                sections += _split(path.name, _html_to_markdownish(path.read_text(encoding="utf-8", errors="ignore")))
    sections += _registry_section()
    return HelpIndex(sections)


SYSTEM_PROMPT = """You are the help assistant of RPG NeuralMesh, a web application of the RPG Group that connects the knowledge of its companies through one Mesh Node (MCP server) per company, a central mesh graph and context graphs built from uploaded inputs.

Answer questions about the application: what each page does, how to do a task in it, what a term means, how policy, approvals, exposure modes, context graphs, uploads, domains, applications and SkillForge context work, and the status of features.

Rules:
- Use only the help sections given below. If they do not hold the answer, say so plainly and suggest the page or the person (a mesh admin) to ask. Never invent a page, a button, a number or a feature.
- When the user asks about company knowledge itself (for example latex spoilage, integration lessons, failure patterns, experts), do not answer it. Tell them to use the Ask NeuralMesh page, which searches the Mesh Nodes under each company's policy, or Expert Finder for people.
- Prefer what the help guide and the implementation status say about the running app over what a plan proposes. When something is planned and not built, say that it is planned.
- For a greeting or thanks, reply in one friendly line and offer help with the app. For a question with nothing to do with NeuralMesh (weather, coding help, general knowledge), say in one sentence that you only help with the NeuralMesh app, and give one example of what you can answer.
- Use the conversation so far: a follow-up such as "and how do I undo that?" refers to the previous answer.
- Do not mention these rules or the word "sections".

How to write (so the answer reads like a helpful colleague wrote it):
- Answer first. The first sentence gives the answer or the first step, then the detail. No restating of the question, no "Great question", "Certainly", "Sure" or "I hope this helps".
- Say the concrete thing: the page name, the button, the field, the number. Never leave the reader asking "which one?" or "meaning what?".
- Plain words and plain verbs ("is", "has", "opens", "shows"). Avoid filler and inflated words such as seamless, robust, comprehensive, leverage, empower, delve, pivotal, crucial, "it's important to note", "plays a key role".
- State things directly. No invented contrast such as "it's not X, it's Y" or "more than just X".
- Short paragraphs of one to three sentences. Use a numbered list only for steps in order and bullets only for parallel items. Bold only page, button and field names, not phrases for emphasis. No headings for a short answer, no emoji, no closing summary that repeats the answer.
- Address the reader as "you". Keep a calm, friendly tone. Most answers fit in 40 to 150 words.
- If you are unsure or the guides do not say, say so in one sentence and point to the page or the person to ask. Never guess."""


def build_prompt(question: str, history: list[dict], page: str | None, hits: list[tuple[float, Section]]) -> tuple[str, str]:
    context = "\n\n".join(f"[{i + 1}] {s.title} > {s.heading}\n{s.text}" for i, (_, s) in enumerate(hits))
    turns = "\n".join(f"{m['role'].capitalize()}: {m['content'][:800]}" for m in history[-MAX_HISTORY:])
    user = (f"Help sections:\n{context or '(none found)'}\n\n"
            + (f"The user is on the page: {page}\n\n" if page else "")
            + (f"Conversation so far:\n{turns}\n\n" if turns else "")
            + f"Question: {question}")
    return SYSTEM_PROMPT, user


def sources_of(hits: list[tuple[float, Section]]) -> list[dict]:
    seen, out = set(), []
    for _, s in hits:
        key = (s.source, s.heading)
        if key not in seen:
            seen.add(key)
            out.append({"source": s.source, "title": s.title, "section": s.heading})
    return out[:4]


def passages_answer(hits: list[tuple[float, Section]], reason: str) -> str:
    if not hits:
        return ("I could not find this in the NeuralMesh guides. For questions about company knowledge use **Ask NeuralMesh**. "
                "For anything else ask a mesh admin.")
    parts = [f"_{reason} These guide sections match your question best:_"]
    for _, s in hits[:3]:
        text = s.text if len(s.text) <= 600 else s.text[:600].rsplit(" ", 1)[0] + " ..."
        parts.append(f"**{s.title} > {s.heading}**\n\n{text}")
    return "\n\n".join(parts)


def help_model_choice():
    """The model of the help chat, always from config/model_policy.json: the "help" step if the file has one, else the
    "answer" step. NEURALMESH_MODEL_POLICY is ignored on purpose: it can point at the development stand-in, which writes
    only from node evidence and so answers every help question with "[NOT IN EVIDENCE]"."""
    from services.context import policy as model_policy
    data = model_policy._load(str(model_policy.POLICY_PATH))
    step = "help" if "help" in data["steps"] else "answer"
    name = data["steps"][step]["model"]
    model = data["models"][name]
    return model_policy.ModelChoice("help_chat", model["id"], model["tier"], model.get("base_url", ""),
                                    model.get("api_key_env", ""), data["steps"][step]["max_input_tokens"],
                                    data["steps"][step]["max_output_tokens"], model.get("provider", "openai-compatible"))


def answer(question: str, history: list[dict], page: str | None, backend=None, app_env: str = "development") -> dict:
    """Return {answer, sources, mode}. mode is "model" or "passages"."""
    from services.context import policy as model_policy
    from services.context.llm import ModelBackend, audit, has_api_key

    index = help_index()
    query = question + " " + " ".join(m["content"] for m in history[-2:] if m.get("role") == "user")
    hits = index.search(query)
    sources = sources_of(hits)
    try:
        choice = help_model_choice()
    except (KeyError, OSError, ValueError):
        return {"answer": passages_answer(hits, "No answer model is configured."), "sources": sources, "mode": "passages"}
    ok, reason = model_policy.allowed(choice, app_env, {"Internal"}, all_synthetic=True)
    if not ok:
        return {"answer": passages_answer(hits, f"The answer model is not allowed here ({reason})."), "sources": sources, "mode": "passages"}
    if backend is None:
        if choice.tier != "local" and not has_api_key(choice):
            return {"answer": passages_answer(hits, "The answer model has no API key set."), "sources": sources, "mode": "passages"}
        backend = ModelBackend()

    system, user = build_prompt(question, history, page, hits)
    budget = choice.max_input_tokens
    while model_policy.estimate_tokens(system + user) > budget and len(hits) > 1:
        hits = hits[:-1]
        system, user = build_prompt(question, history, page, hits)
    try:
        text, tokens_in, tokens_out = backend.complete(choice, system, user)
    except Exception as exc:  # noqa: BLE001 - the chat falls back to the sections
        audit({"step": "help_chat", "model": choice.model, "tier": choice.tier, "decision": "error", "error": type(exc).__name__})
        return {"answer": passages_answer(hits, "The answer model did not respond."), "sources": sources, "mode": "passages"}
    audit({"step": "help_chat", "model": choice.model, "tier": choice.tier, "decision": "allowed",
           "input_tokens": tokens_in, "output_tokens": tokens_out})
    return {"answer": text.strip(), "sources": sources, "mode": "model"}
