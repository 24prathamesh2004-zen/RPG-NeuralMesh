"""Sample inputs for the Context graph page: ten synthetic files in four context graphs, uploaded as the mesh admin
through the route of the Add input form, so the page can be checked the way it looks after months of use.

    python -m scripts.sample_inputs status      which sample inputs are loaded, and which other uploads exist
    python -m scripts.sample_inputs load        upload the sample inputs that have no record yet
    python -m scripts.sample_inputs remove      take the sample inputs out again (asks first, --yes skips the question)

Allowed only with APP_ENV=development and a running stack (scripts/dev_stack.sh start). The files and their list are in
neuralmesh_kb_pack/sample_inputs. Every upload goes through POST /api/v1/mesh/uploads, so the text reading, the concept
links, the pack rebuild and the graph refresh are the ones of the application. Two things are written straight into the
upload record afterwards, because no route sets them: the upload date of the list, and the mark ``sample_input`` by which
this script knows its own records. ``remove`` touches only records with that mark: an input a person added stays.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

from knowledge import packgen
from scripts.seed_demo_accounts import DEMO_PASSWORD, DEMO_USERS
from services.uploads import _write_atomic, graph_ref
from shared.config import get_settings
from shared.registry import node_ids

SAMPLES = packgen.KB_PACK / "sample_inputs"
API = os.getenv("NEURALMESH_API", "http://127.0.0.1:8000").rstrip("/")
MARK = "sample_input"
MEDIA = {".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
         ".md": "text/markdown", ".txt": "text/plain", ".csv": "text/csv", ".json": "application/json"}


def _manifest() -> dict:
    return json.loads((SAMPLES / "manifest.json").read_text(encoding="utf-8"))


def _records() -> list[tuple[str, Path, dict]]:
    """(node, file, record) of every upload record of every node, whatever its status."""
    out = []
    for node in node_ids():
        for path in sorted((packgen.DATA / node / packgen.CONTRIBUTIONS).glob("*.json")):
            try:
                out.append((node, path, json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError):
                continue
    return out


def _marked() -> dict[str, tuple[str, Path, dict]]:
    """The records this script made, by the file name of the sample."""
    return {str(record[MARK]): (node, path, record) for node, path, record in _records() if record.get(MARK)}


def _signed_in() -> httpx.Client:
    try:
        health = httpx.get(f"{API}/health", timeout=10)
        health.raise_for_status()
    except httpx.HTTPError as exc:
        raise SystemExit(f"The API does not answer at {API}. Start the stack with scripts/dev_stack.sh start. ({type(exc).__name__})") from None
    http = httpx.Client(base_url=f"{API}/api/v1", timeout=300)
    answer = http.post("/auth/signin", json={"email": DEMO_USERS[0]["email"], "password": DEMO_PASSWORD})
    if answer.status_code != 200:
        raise SystemExit(f"Sign-in as {DEMO_USERS[0]['email']} was refused. Run python -m scripts.seed_demo_accounts first.")
    body = answer.json()
    if "mesh_admin" not in body["user"].get("roles", []):
        raise SystemExit(f"{DEMO_USERS[0]['email']} is not a mesh admin here, so it cannot upload. Check NEURALMESH_ADMIN_EMAILS.")
    http.headers["Authorization"] = f"Bearer {body['access_token']}"
    return http


def _line(key: str, record: dict, state: str) -> str:
    doc = record["document"]
    return f"  {key:<4}{doc['id']:<22}{record['upload']['at'][:10]}  {state:<9}{graph_ref(record)['name']}  |  {doc['title']}"


def status() -> None:
    manifest, marked = _manifest(), _marked()
    loaded = [e for e in manifest["inputs"] if Path(e["file"]).name in marked]
    removed = [e for e in loaded if marked[Path(e["file"]).name][2]["status"] == "removed"]
    print(f"Sample inputs: {len(manifest['inputs'])} in the list, {len(loaded) - len(removed)} loaded, "
          f"{len(removed)} loaded and removed, {len(manifest['inputs']) - len(loaded)} without a record")
    for e in manifest["inputs"]:
        name = Path(e["file"]).name
        if name in marked:
            record = marked[name][2]
            print(_line(e["id"], record, "removed" if record["status"] == "removed" else "loaded"))
        else:
            print(f"  {e['id']:<4}{'no record':<22}{'':<12}{'':<9}{e['graph']}  |  {e['title']}")
    planned = {Path(e["file"]).name for e in manifest["inputs"] if e.get("removed_at")}
    surprise = [e["id"] for e in removed if Path(e["file"]).name not in planned]
    if surprise:
        print(f"  {', '.join(surprise)} removed in the application. To bring them back: remove, then load.")
    others = [(node, record) for node, _, record in _records() if not record.get(MARK)]
    print(f"Other uploads, never touched by this script: {len(others)}")
    for _, record in others:
        print(_line("", record, record["status"] if record["status"] != "accepted" else "kept"))
    print(f"Spare files for adding an input by hand: {len(manifest['spare'])}")
    for e in manifest["spare"]:
        print(f"  {e['id']:<4}{SAMPLES.name}/{e['file']}  |  {e['node_id']} {e['datapoint']}, kind {e['kind']}, graph \"{e['graph']}\"")


def _check_list(http: httpx.Client, entries: list[dict]) -> None:
    """Every entry is checked before the first upload, so a wrong list stops the load before anything is kept."""
    kinds = http.get("/mesh/uploads").json()["kinds"]
    items: dict[str, dict] = {}
    problems = []
    for e in entries:
        if not (SAMPLES / e["file"]).is_file():
            problems.append(f"{e['id']}: the file {e['file']} is missing")
        if e["kind"] not in kinds:
            problems.append(f"{e['id']}: {e['kind']} is not a document kind")
        if e["node_id"] not in items:
            answer = http.get(f"/mesh/uploads/items/{e['node_id']}")
            items[e["node_id"]] = {i["code"]: i for i in answer.json()["items"]} if answer.status_code == 200 else {}
        item = items[e["node_id"]].get(e["datapoint"])
        if item is None:
            problems.append(f"{e['id']}: {e['node_id']} has no catalogue item {e['datapoint']}")
        elif item["ceiling"] == "LIVE":
            problems.append(f"{e['id']}: {e['node_id']} {e['datapoint']} is a live item, which keeps no document")
    if problems:
        raise SystemExit("Nothing was uploaded. The list of sample inputs does not fit this installation:\n  " + "\n  ".join(problems))


def _record_file(doc_id: str) -> Path:
    node, code = doc_id.split(":", 1)
    path = packgen.DATA / node / packgen.CONTRIBUTIONS / f"{code}.json"
    if not path.is_file():
        raise SystemExit(f"The API kept {doc_id}, but its record is not in {packgen.DATA}. The API and this script must use the same "
                         "data pack folder (NEURALMESH_DATA_PACK).")
    return path


def load() -> None:
    manifest = _manifest()
    todo = [e for e in sorted(manifest["inputs"], key=lambda e: e["uploaded_at"]) if Path(e["file"]).name not in _marked()]
    http = _signed_in()
    _check_list(http, todo)
    for e in todo:
        path = SAMPLES / e["file"]
        graphs = {g["name"].casefold(): g["id"] for g in http.get("/mesh/uploads").json()["graphs"]}
        graph = {"graph_id": graphs[e["graph"].casefold()]} if e["graph"].casefold() in graphs else {"graph_name": e["graph"]}
        fields = {"node_id": e["node_id"], "datapoint": e["datapoint"], "kind": e["kind"], "title": e["title"],
                  "tags": ", ".join(e["tags"]), "version": e["uploaded_at"][:7], "synthetic": "true", **graph}  # invented files, marked so
        answer = http.post("/mesh/uploads", data=fields, files={"file": (path.name, path.read_bytes(), MEDIA[path.suffix])})
        if answer.status_code != 201:
            raise SystemExit(f"{e['id']} {path.name} was refused ({answer.status_code}): {answer.json().get('detail', answer.text)}")
        body = answer.json()
        record_path = _record_file(body["document"]["id"])
        record = json.loads(record_path.read_text(encoding="utf-8"))
        record["upload"]["at"] = e["uploaded_at"]
        record[MARK] = path.name
        _write_atomic(record_path, record)
        links, expected = set(body["concept_matches"]), set(e.get("expect_concepts", body["concept_matches"]))
        note = "" if links == expected else f"  links differ from the list: more {sorted(links - expected)}, fewer {sorted(expected - links)}"
        print(f"  {e['id']:<4}{body['document']['id']:<22}{'opens' if 'graph_name' in graph else 'joins'} \"{e['graph']}\", "
              f"{len(links)} concept links, {body['refresh'] or 'no refresh answer'}{note}")
    for e in manifest["inputs"]:  # a draft that a later version replaced: removed the way a person removes an input
        entry = _marked().get(Path(e["file"]).name)
        if not e.get("removed_at") or entry is None:
            continue
        _, record_path, record = entry
        if record["status"] == "accepted":
            answer = http.delete(f"/mesh/uploads/{record['document']['id']}")
            if answer.status_code != 200:
                raise SystemExit(f"{e['id']} could not be removed ({answer.status_code}): {answer.text[:200]}")
            record = json.loads(record_path.read_text(encoding="utf-8"))
            print(f"  {e['id']:<4}{record['document']['id']:<22}removed, as a draft that a later version replaced")
        if record["status"] == "removed" and record.get("removed", {}).get("at") != e["removed_at"]:
            record["removed"]["at"] = e["removed_at"]
            _write_atomic(record_path, record)
    if not todo:
        print("  Every sample input has a record. Nothing was uploaded.")
    status()


def remove(yes: bool) -> None:
    marked = _marked()
    others = [record for _, _, record in _records() if not record.get(MARK)]
    if not marked:
        print("No sample input is loaded. Nothing to remove.")
        return
    print(f"These {len(marked)} sample inputs go, out of the packs, the search, the graph and the upload list:")
    for _, _, record in marked.values():
        print(_line("", record, "removed" if record["status"] == "removed" else "loaded"))
    print(f"These {len(others)} other uploads stay as they are:")
    for record in others:
        print(_line("", record, record["status"] if record["status"] != "accepted" else "kept"))
    if not yes and input(f"Type yes to remove the {len(marked)} sample inputs: ").strip().lower() != "yes":
        print("Nothing was removed.")
        return
    http = _signed_in()
    for name, (_, path, record) in marked.items():
        if record["status"] == "accepted":  # the application takes it out of the pack, the index, the vectors and the graph
            answer = http.delete(f"/mesh/uploads/{record['document']['id']}")
            if answer.status_code != 200:
                raise SystemExit(f"{record['document']['id']} ({name}) could not be removed ({answer.status_code}): {answer.text[:200]}. "
                                 "Its record was kept. Run remove again.")
        path.unlink()
        print(f"  removed {record['document']['id']}  {record['document']['title']}")
    status()


def main() -> None:
    if get_settings().app_env != "development":
        raise SystemExit("Refusing to touch sample inputs outside APP_ENV=development")
    command = sys.argv[1] if len(sys.argv) > 1 else "status"
    if command == "status":
        status()
    elif command == "load":
        load()
    elif command == "remove":
        remove("--yes" in sys.argv[2:])
    else:
        raise SystemExit("usage: python -m scripts.sample_inputs status|load|remove [--yes]")


if __name__ == "__main__":
    main()
