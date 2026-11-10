"""Download formats of a context graph that are written as line templates: two built in (Cypher for Neo4j, Mermaid)
and any a mesh admin adds. A template has a header, one line for each entity, one line for each link and a footer.
Placeholders in braces are filled with the escaped value, nothing else runs, and a template with an unknown
placeholder is refused when it is saved. The formats a mesh admin adds are kept as JSON files, one per format."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
FIXED = ("json", "graphml", "csv", "pack")  # written by code in services.uploads.export
NODE_FIELDS = ("id", "key", "type", "label", "company")
EDGE_FIELDS = ("id", "key", "type", "source", "target", "source_key", "target_key", "status")
ESCAPES = ("none", "csv", "json", "xml", "quotes", "mermaid")
MAX_CUSTOM = 20
MAX_TEMPLATE = 2000
PLACEHOLDER = re.compile(r"\{\{|\}\}|\{([a-z_]+)\}")

BUILT_IN: dict[str, dict[str, Any]] = {
    "cypher": {"id": "cypher", "name": "Cypher (for Neo4j)", "extension": "cypher", "escape": "quotes", "header": "",
               "node_line": 'MERGE (n:Entity {{id: "{id}"}}) SET n.type = "{type}", n.label = "{label}", n.company = "{company}";',
               "edge_line": 'MATCH (a:Entity {{id: "{source}"}}), (b:Entity {{id: "{target}"}}) MERGE (a)-[:{key} {{status: "{status}"}}]->(b);',
               "footer": ""},
    "mermaid": {"id": "mermaid", "name": "Mermaid (diagram text)", "extension": "mmd", "escape": "mermaid", "header": "graph LR",
                "node_line": '  {key}["{label}"]', "edge_line": "  {source_key} -->|{type}| {target_key}", "footer": ""},
}


def folder() -> Path:
    return Path(os.getenv("NEURALMESH_EXPORT_FORMATS", str(APP_ROOT / ".neuralmesh" / "export_formats")))


def custom() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(folder().glob("*.json")) if folder().is_dir() else []:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out[item["id"]] = item
    return out


def templates() -> dict[str, dict[str, Any]]:
    return {**BUILT_IN, **custom()}


def ids() -> list[str]:
    return [*FIXED, *templates()]


FIXED_NAMES = {"json": "JSON (entities and links)", "graphml": "GraphML (for graph tools)", "csv": "CSV (one row per entity and link)",
               "pack": "Knowledge pack (the documents)"}


def listing() -> list[dict[str, Any]]:
    """Every format with its name and whether a mesh admin added it."""
    added = custom()
    return ([{"id": f, "name": FIXED_NAMES[f], "custom": False} for f in FIXED]
            + [{"id": t["id"], "name": t["name"], "extension": t["extension"], "custom": t["id"] in added} for t in templates().values()])


class FormatRefused(ValueError):
    pass


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30]


def _check_template(text: str, allowed: tuple[str, ...], what: str) -> None:
    if len(text) > MAX_TEMPLATE:
        raise FormatRefused(f"The {what} has at most {MAX_TEMPLATE} characters.")
    for m in PLACEHOLDER.finditer(text):
        if m.group(1) is not None and m.group(1) not in allowed:
            raise FormatRefused(f"{{{m.group(1)}}} is not a placeholder of the {what}. Placeholders: {', '.join('{' + f + '}' for f in allowed)}.")


def save(fields: dict[str, Any], by: str) -> dict[str, Any]:
    """Check and keep a format a mesh admin wrote. Returns it as kept."""
    name = " ".join(str(fields.get("name", "")).split())
    if not 3 <= len(name) <= 40:
        raise FormatRefused("The name of a format has 3 to 40 characters.")
    fid = _slug(name)
    taken_names = {v.casefold() for v in FIXED_NAMES.values()} | {t["name"].casefold() for t in BUILT_IN.values()}
    if not fid or fid in FIXED or fid in BUILT_IN or name.casefold() in taken_names:
        raise FormatRefused(f'"{name}" is the name of a format that exists. Choose another name.')
    existing = custom()
    if fid in existing:
        raise FormatRefused(f'A format named "{existing[fid]["name"]}" exists. Remove it first, or choose another name.')
    if len(existing) >= MAX_CUSTOM:
        raise FormatRefused(f"At most {MAX_CUSTOM} formats can be added.")
    ext = str(fields.get("extension", "")).strip().lstrip(".").lower()
    if not re.fullmatch(r"[a-z0-9]{1,10}(\.[a-z0-9]{1,10})?", ext):
        raise FormatRefused("The file extension has letters and digits only, for example txt or ttl.")
    escape = str(fields.get("escape") or "none")
    if escape not in ESCAPES:
        raise FormatRefused(f"The escaping is one of {', '.join(ESCAPES)}.")
    item = {"id": fid, "name": name, "extension": ext, "escape": escape}
    for key, allowed, what in (("header", (), "header"), ("node_line", NODE_FIELDS, "line for each entity"),
                               ("edge_line", EDGE_FIELDS, "line for each link"), ("footer", (), "footer")):
        text = str(fields.get(key) or "")
        _check_template(text, allowed, what)
        item[key] = text
    if not item["node_line"].strip() and not item["edge_line"].strip():
        raise FormatRefused("A format needs a line for each entity, a line for each link, or both.")
    item["added_by"] = by
    path = folder() / f"{fid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(item, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return item


SECTIONS = {"header": "header", "entity": "node_line", "link": "edge_line", "footer": "footer"}
TEMPLATE_EXAMPLE = """[extension] mmd
[escape] mermaid
[header]
graph LR
[entity]
  {key}["{label}"]
[link]
  {source_key} -->|{type}| {target_key}
"""


def from_text(file_name: str, text: str, by: str) -> dict[str, Any]:
    """A template file as a person writes it: the lines under [header], [entity], [link] and [footer], and optional
    lines [extension] and [escape]. The name is the file name. A file whose name and content match a kept format
    gives that format back, so the same template can be chosen again by uploading it."""
    name = " ".join(Path(file_name).stem.replace("_", " ").replace("-", " ").split()).capitalize()
    fields: dict[str, Any] = {"name": name, "extension": "txt", "escape": "none"}
    current = None
    for line in text.replace("\r\n", "\n").split("\n"):
        m = re.fullmatch(r"\s*\[(header|entity|link|footer|extension|escape)\]\s*(.*)", line)
        if m and m.group(1) in ("extension", "escape"):
            fields[m.group(1)] = m.group(2).strip()
            current = None
        elif m:
            current = SECTIONS[m.group(1)]
            fields.setdefault(current, [])
        elif current is not None:
            fields[current].append(line)
    for key in SECTIONS.values():
        fields[key] = "\n".join(fields.get(key, [])).strip("\n")
    if not any(fields[k].strip() for k in ("node_line", "edge_line")):
        raise FormatRefused("A template needs the lines under [entity], under [link], or both. Example:\n" + TEMPLATE_EXAMPLE)
    existing = custom().get(_slug(name))
    if existing and all(existing.get(k, "") == fields[k] for k in ("extension", "escape", *SECTIONS.values())):
        return existing
    return save(fields, by)


def remove(fid: str) -> None:
    if fid not in custom():
        raise FormatRefused(f"{fid} is not a format a mesh admin added. The built-in formats stay.")
    (folder() / f"{fid}.json").unlink()


def _key(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", value)


def _esc(value: str, how: str) -> str:
    value = str(value)
    if how == "csv":
        return '"' + value.replace('"', '""') + '"' if any(c in value for c in ',"\n') else value
    if how == "json":
        return json.dumps(value, ensure_ascii=False)[1:-1]
    if how == "xml":
        from xml.sax.saxutils import escape
        return escape(value, {'"': "&quot;"})
    if how == "mermaid":
        return value.replace('"', "#quot;").replace("\n", " ")
    if how == "quotes":
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return value.replace("\n", " ")


def _fill(template: str, values: dict[str, str], how: str) -> str:
    def one(m: re.Match) -> str:
        if m.group(0) == "{{":
            return "{"
        if m.group(0) == "}}":
            return "}"
        return _esc(values.get(m.group(1), ""), how)
    return PLACEHOLDER.sub(one, template)


def render(fid: str, view: dict[str, Any], company_name=lambda s: s) -> tuple[str, str, str]:
    """The graph part in a template format: (content, media type, file extension)."""
    t = templates()[fid]
    lines = [t["header"]] if t.get("header") else []
    if t.get("node_line"):
        for n in view["nodes"]:
            lines.append(_fill(t["node_line"], {"id": n["id"], "key": _key(n["id"]), "type": str(n["type"]), "label": n.get("label", ""),
                                                "company": company_name(n.get("subsidiary") or "")}, t["escape"]))
    if t.get("edge_line"):
        for e in view["edges"]:
            lines.append(_fill(t["edge_line"], {"id": e["id"], "key": _key(e["type"]), "type": e["type"], "source": e["source"], "target": e["target"],
                                                "source_key": _key(e["source"]), "target_key": _key(e["target"]), "status": e.get("status", "")}, t["escape"]))
    if t.get("footer"):
        lines.append(t["footer"])
    return "\n".join(lines) + "\n", "text/plain", t["extension"]
