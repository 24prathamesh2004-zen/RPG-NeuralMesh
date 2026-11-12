"""Many inputs at once for Upload input: several files, a folder, or one .zip of a folder.

The layout is the one of the input request format: one folder for an application, one subfolder for each topic. Each
subfolder becomes one context graph named after it, and a file beside the subfolders goes into the graph named after the
folder or the zip. A file ``inputs.csv`` at the top may give, for a file, its topic (the graph name), its title, its
company, its catalogue item code and whether it is real data. Columns it does not know are named in the plan and not
read. Without the list, the company and the catalogue item chosen on the form apply to every file.

``plan`` reads every file and keeps nothing: it says for each file the graph it goes to, its title and kind, or why it
is refused. ``save`` keeps the files of a plan one after the other through services.uploads.add_upload, so each file
gets the same reading, concept links, pack rebuild and extraction as a single upload. A file that is refused does not
stop the others.

A zip is opened in memory and never written to disk. An entry with an absolute path or ".." is refused, a zip inside
the zip is not opened, and the number of files and the unpacked size have limits, checked from the zip's own list
before any entry is read.
"""
from __future__ import annotations

import csv
import hashlib
import io
import zipfile
from pathlib import PurePosixPath
from typing import Any

from services import upload_kind, upload_suggest, uploads
from services.context_graph_ingest import company_of

MAX_FILES = 100
MAX_TOTAL_BYTES = 200_000_000  # all files together, unpacked
LIST_FILE = "inputs.csv"
LIST_COLUMNS = ("file", "topic", "title", "company", "item", "real_data")
READ = (".txt", ".md", ".csv", ".json", ".pdf", ".docx")


class BatchRefused(ValueError):
    """Nothing can be planned: the zip cannot be read, or the files are over a limit."""


def _clean(path: str) -> str | None:
    """The path with forward slashes, or None for one that leaves its folder."""
    path = path.replace("\\", "/").strip()
    parts = [p for p in path.split("/") if p not in ("", ".")]
    if path.startswith("/") or ".." in parts or not parts or (len(parts[0]) == 2 and parts[0][1] == ":"):
        return None
    return "/".join(parts)


def _hidden(path: str) -> bool:
    parts = path.split("/")
    return parts[0] == "__MACOSX" or any((p.startswith(".") and p != "..") or p.startswith("~$") for p in parts) or parts[-1] in ("Thumbs.db", "desktop.ini")


def unpack(files: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[dict[str, str]], str]:
    """(files as (path, bytes), entries refused before reading, the name of the zip or ""). One .zip is opened, any
    other set of files is taken as it is."""
    refused: list[dict[str, str]] = []
    root = ""
    if len(files) == 1 and files[0][0].lower().endswith(".zip"):
        root = PurePosixPath(files[0][0].replace("\\", "/")).stem
        try:
            archive = zipfile.ZipFile(io.BytesIO(files[0][1]))
            infos = [i for i in archive.infolist() if not i.is_dir()]
        except zipfile.BadZipFile:
            raise BatchRefused("The zip file could not be opened.") from None
        kept = [i for i in infos if not _hidden(i.filename.replace("\\", "/"))]
        if len(kept) > MAX_FILES:
            raise BatchRefused(f"The zip holds {len(kept)} files. At most {MAX_FILES} are taken at once.")
        if sum(i.file_size for i in kept) > MAX_TOTAL_BYTES:
            raise BatchRefused(f"The files of the zip have more than {MAX_TOTAL_BYTES // 1_000_000} MB together when unpacked.")
        out, read = [], 0
        for info in kept:
            path = _clean(info.filename)
            if path is None:
                refused.append({"path": info.filename[:200], "reason": "The path leaves the folder of the zip."})
            elif info.flag_bits & 0x1:
                refused.append({"path": path, "reason": "The file is protected by a password."})
            elif info.file_size > uploads.MAX_BYTES:
                refused.append({"path": path, "reason": f"The file is larger than {uploads.MAX_BYTES // 1_000_000} MB."})
            else:
                with archive.open(info) as fh:  # read up to the limit, whatever size the zip's list states
                    data = fh.read(uploads.MAX_BYTES + 1)
                read += len(data)
                if read > MAX_TOTAL_BYTES:  # the zip's list understated its sizes
                    raise BatchRefused(f"The files of the zip have more than {MAX_TOTAL_BYTES // 1_000_000} MB together when unpacked.")
                if len(data) > uploads.MAX_BYTES:
                    refused.append({"path": path, "reason": f"The file is larger than {uploads.MAX_BYTES // 1_000_000} MB."})
                else:
                    out.append((path, data))
        files = out
    else:
        out = []
        for name, data in files:
            path = _clean(name)
            if path is None:
                refused.append({"path": name[:200], "reason": "The path leaves its folder."})
            elif not _hidden(path):
                out.append((path, data))
        if len(out) > MAX_FILES:
            raise BatchRefused(f"{len(out)} files were chosen. At most {MAX_FILES} are taken at once.")
        if sum(len(d) for _, d in out) > MAX_TOTAL_BYTES:
            raise BatchRefused(f"The files have more than {MAX_TOTAL_BYTES // 1_000_000} MB together.")
        files = out
    # one folder that holds everything is the folder of the application: its name is the name of the set
    tops = {p.split("/")[0] for p, _ in files if "/" in p}
    if files and len(tops) == 1 and all("/" in p for p, _ in files):
        root = tops.pop()
        files = [(p.split("/", 1)[1], d) for p, d in files]
    return files, refused, root


def _words(name: str) -> str:
    """A folder or file name as a graph name: "leave_and_attendance" becomes "Leave and attendance"."""
    text = " ".join(name.replace("_", " ").replace("-", " ").split())
    return (text[:1].upper() + text[1:])[: uploads.GRAPH_NAME_MAX]


def _list(files: list[tuple[str, bytes]]) -> tuple[dict[str, dict[str, str]], list[str]]:
    """The rows of inputs.csv by file path, and notes on the list."""
    data = next((d for p, d in files if p.lower() == LIST_FILE), None)
    if data is None:
        return {}, []
    notes: list[str] = []
    try:
        reader = csv.DictReader(io.StringIO(data.decode("utf-8-sig")))
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in row.items()} for row in reader]
        columns = [c.strip().lower() for c in (reader.fieldnames or [])]
    except (UnicodeDecodeError, csv.Error):
        return {}, [f"{LIST_FILE} could not be read, so the folders decide the graphs."]
    if "file" not in columns:
        return {}, [f'{LIST_FILE} has no column "file", so the folders decide the graphs.']
    unread = [c for c in columns if c and c not in LIST_COLUMNS]
    if unread:
        notes.append(f"Columns of {LIST_FILE} that are not read: {', '.join(unread)}.")
    return {(_clean(r.get("file", "")) or ""): r for r in rows if r.get("file")}, notes


def plan(rt: Any, files: list[tuple[str, bytes]], node: str, code: str, *, new_item_title: str = "", new_item_area: str = "",
         graph_name: str = "") -> dict[str, Any]:
    """What a save would do with each file. Nothing is kept. Each entry carries "data" for save, which the route leaves
    out of its answer. ``new_item_title`` and ``new_item_area`` name a new catalogue item of the form's company: the
    first file kept opens it and the others go under it. ``graph_name`` replaces the name taken from the folder or the
    zip, for the files that are in no subfolder."""
    files, refused, root = unpack(files)
    new_item_title = " ".join(new_item_title.split())
    if new_item_title:
        if len(new_item_title) < 3:
            raise BatchRefused("The name of the new catalogue item has at least 3 letters.")
        if new_item_area not in {a["domain"] for a in uploads.new_item_areas(node)}:
            raise BatchRefused(f"{uploads.company_label(node)} takes no new catalogue item in this area.")
    set_name = _words(root) if root else ""
    root = " ".join(graph_name.split()) or root
    rows, notes = _list(files)
    listed = set(rows)
    files = [(p, d) for p, d in files if p.lower() != LIST_FILE]
    if not files and not refused:
        raise BatchRefused("No file to read was found.")
    by_name = {uploads.graph_ref(r)["name"].casefold(): uploads.graph_ref(r) for _, r in uploads._all_records()}
    by_sha = {r["upload"].get("sha256"): r for _, r in uploads._all_records()}
    entries: list[dict[str, Any]] = [{"path": r["path"], "status": "refused", "reason": r["reason"]} for r in refused]
    seen: dict[str, str] = {}
    for path, data in sorted(files):
        name = path.rsplit("/", 1)[-1]
        row = rows.get(path, {})
        entry: dict[str, Any] = {"path": path, "file": name, "status": "ok"}
        folder = path.split("/")[0] if "/" in path else ""
        graph = (row.get("topic") or _words(folder or root))[: uploads.GRAPH_NAME_MAX]  # empty for a loose file: its title names its graph
        entry_node, entry_code = node, code
        try:
            if not name.lower().endswith(READ):
                raise uploads.UploadRefused(f"{'.' + name.rsplit('.', 1)[-1] if '.' in name else 'A file without an extension'} is not read. "
                                            "Files read: .txt, .md, .csv, .json, .pdf or .docx.")
            if row.get("company"):
                entry_node = company_of(row["company"]) or ""
                if not entry_node:
                    raise uploads.UploadRefused(f'{LIST_FILE} names the company "{row["company"][:60]}", which is not a company of the mesh.')
                entry_code = row.get("item") or (code if entry_node == node else "")
                if not entry_code:
                    raise uploads.UploadRefused(f'{LIST_FILE} names another company than the form. Write its catalogue item code in the column "item".')
            elif row.get("item"):
                entry_code = row["item"]
            items = uploads.datapoints_of(entry_node)
            new_item = bool(new_item_title) and entry_node == node and not row.get("item")
            if new_item:
                entry_code = ""
            elif entry_code not in items:
                raise uploads.UploadRefused(f"{uploads.company_label(entry_node)} has no catalogue item {entry_code[:20]}.")
            if not new_item and items[entry_code]["ceiling"] == "LIVE":
                raise uploads.UploadRefused(f"{entry_code} is a live item. A document is not kept under it.")
            text, fmt = uploads.extract_text(name, data)
            sha = hashlib.sha256(data).hexdigest()
            if sha in by_sha:
                raise uploads.UploadRefused(f'The same file is already an input of "{uploads.graph_ref(by_sha[sha])["name"]}".')
            if sha in seen:
                raise uploads.UploadRefused(f"The same file as {seen[sha]}.")
            seen[sha] = path
            title = row.get("title") or upload_suggest.title_of(name, text, fmt)
            kind = upload_kind.by_rules(title, name, text, fmt)["kind"]
            if len(graph) < 3 and folder and root:  # a short folder name such as "hr" is said with the name of the set
                graph = f"{_words(root)} {folder}"[: uploads.GRAPH_NAME_MAX]
            graph = graph if len(graph) >= 3 else " ".join(title.split())[: uploads.GRAPH_NAME_MAX].strip()
            if len(graph) < 3:
                raise uploads.UploadRefused("The name of the graph, taken from the folder or the title, has fewer than 3 characters.")
            existing = by_name.get(graph.casefold())
            entry.update(graph=existing["name"] if existing else graph, graph_id=existing["id"] if existing else None, title=title[:200], kind=kind,
                         node_id=entry_node, company=uploads.company_label(entry_node), item=entry_code, new_item=new_item, chars=len(text),
                         title_from="list" if row.get("title") else "file",
                         synthetic=row.get("real_data", "").lower() in ("no", "false", "0"), data=data)
        except uploads.UploadRefused as exc:
            entry.update(status="refused", reason=str(exc))
        entries.append(entry)
    # a heading several files share, such as the company name, says nothing about one file: each takes its file name
    titles: dict[str, int] = {}
    for x in entries:
        if x["status"] == "ok":
            titles[x["title"].casefold()] = titles.get(x["title"].casefold(), 0) + 1
    for x in entries:
        if x["status"] == "ok" and x["title_from"] == "file" and titles[x["title"].casefold()] > 1:
            x["title"] = _words(x["file"].rsplit(".", 1)[0])[:200]
    missing = sorted(listed - {p for p, _ in files})
    if missing:
        notes.append(f"{LIST_FILE} lists {len(missing)} {'file that is' if len(missing) == 1 else 'files that are'} not in the folder: {', '.join(missing[:5])}.")
    ok = [x for x in entries if x["status"] == "ok"]
    graphs: dict[str, dict[str, Any]] = {}
    for x in ok:
        g = graphs.setdefault(x["graph"].casefold(), {"name": x["graph"], "id": x["graph_id"], "new": x["graph_id"] is None, "files": 0})
        g["files"] += 1
    return {"name": set_name, "new_item": {"title": new_item_title, "area": new_item_area} if new_item_title else None, "entries": entries, "graphs": list(graphs.values()), "ok": len(ok), "refused": len(entries) - len(ok), "notes": notes}


def save(rt: Any, user: dict[str, Any], planned: dict[str, Any]) -> dict[str, Any]:
    """Keep every file of the plan that can be kept. The first file of a new graph opens it and the next ones join it."""
    ids = {g["name"].casefold(): g["id"] for g in planned["graphs"]}
    saved, refused = [], [x for x in planned["entries"] if x["status"] != "ok"]
    item_code = ""  # the code of the new catalogue item, once the first file opened it
    made = None
    for x in (e for e in planned["entries"] if e["status"] == "ok"):
        graph_id = ids.get(x["graph"].casefold())
        opens = x.get("new_item") and not item_code
        try:
            record = uploads.add_upload(rt, user, x["node_id"], item_code if x.get("new_item") and item_code else x["item"] or "new", uploads.AUTO_KIND,
                                        x["title"], x["file"], x["data"], graph_id=graph_id, graph_name=None if graph_id else x["graph"],
                                        synthetic=x["synthetic"], new_item_title=planned["new_item"]["title"] if opens else None,
                                        new_item_area=planned["new_item"]["area"] if opens else None)
        except uploads.UploadRefused as exc:
            refused.append({**x, "status": "refused", "reason": str(exc)})
            continue
        if opens and record.get("new_item"):
            item_code, made = record["new_item"]["code"], record["new_item"]
        ids[x["graph"].casefold()] = record["context_graph"]["id"]
        saved.append({"path": x["path"], **record})
    graphs: dict[str, dict[str, Any]] = {}
    for r in saved:
        g = graphs.setdefault(r["context_graph"]["id"], {**r["context_graph"], "files": 0})
        g["files"] += 1
    return {"saved": saved, "refused": [public(x) for x in refused], "graphs": list(graphs.values()), "new_item": made, "notes": planned["notes"]}


def public(entry: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in entry.items() if k not in ("data", "title_from")}
