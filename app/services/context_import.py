"""The import tool: an application sends packs through the one contract (plan 2.6).

Each pack is checked against the application's registry file: is this pack id allowed, does its company have a Mesh
Node, and does the pack hold only what the rule allows (its entity and relationship types, the company's own
namespace, no approvals, only the company's own role profile datapoint with purposes the application serves). Then it
is checked strictly, as the rebuild will check it: the talent packs of the affected nodes rebuilt with the incoming
packs, together with every other node pack on disk and the group packs. A reference that no pack defines is refused with
its name and the packs that use it, so a pack that can never load is never answered with "send it again later". A pack
whose content equals the one already kept changes nothing. Changed packs are kept in the talent import folder under the id the registry names, the talent packs
of the affected nodes are rebuilt, the nodes read their changed pack files, and the graph is refreshed from the node
exports, so a role reaches the graph the same way after a restart as right after the import.

A call whose packs all fail the checks that need nothing kept (the registry rule, the node, the content rules) takes
no lock and writes nothing. A pack is reported as loaded only when its company's node answered the refresh. Otherwise it stays kept, its hash is
not recorded, and the next send loads it. When a step fails, the kept packs and the node packs of before are put back.
The import runs to its end even when the caller stops waiting, so a timeout never leaves half a change.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from contracts.context import problem
from knowledge.validator import PackCheckFailed
from services import context_api
from shared.logger import get_logger
from shared.registry import node_ids

try:
    import fcntl
except ImportError:  # Windows has no fcntl: imports are then kept one at a time within one process only
    fcntl = None

log = get_logger("services.context_import")
LOG_FILE = "import_log.json"
LOCK_FILE = ".import.lock"  # held while an import runs, so a second process waits for it
_lock = asyncio.Lock()
if fcntl is None:
    log.warning("context_import.no_folder_lock", reason="fcntl is not available, so imports are one at a time per process only")


@asynccontextmanager
async def _folder_lock(folder: Path):
    """An exclusive OS lock on a file in the import folder for the length of one import, so a second process waits.
    The wait runs in a thread, so the event loop goes on serving other calls. When the wait is cancelled (the process
    stops), the file is closed only after the thread has returned, and closing it releases a lock the thread got late.
    The OS releases the lock when the process ends."""
    if fcntl is None:
        yield
        return
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(folder / LOCK_FILE, os.O_RDWR | os.O_CREAT, 0o644)
    waiting = asyncio.ensure_future(asyncio.to_thread(fcntl.flock, fd, fcntl.LOCK_EX))
    try:
        await asyncio.shield(waiting)
    except BaseException:
        waiting.add_done_callback(lambda _done: os.close(fd))
        raise
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _sha(pack: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(pack, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _read_log(folder: Path) -> dict[str, Any]:
    path = folder / LOG_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (OSError, ValueError):
        return {}


def _write_atomic(path: Path, data: bytes) -> None:
    """Write to a temporary file beside the target and rename it, so a reader sees the old file or the new one."""
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _counts(pack: dict[str, Any]) -> dict[str, int]:
    ents = pack.get("entities", [])
    return {"roles": sum(1 for e in ents if e.get("type") == "Role"), "skills": sum(1 for e in ents if e.get("type") == "Skill"),
            "requirements": sum(1 for r in pack.get("relationships", []) if r.get("type") == "REQUIRES_SKILL")}


def _listed(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _plain(error: str) -> str:
    """A validator line without its level prefix, as one sentence."""
    text = error.removeprefix("ERROR   ").removeprefix("WARNING ").strip()
    return text if text.endswith(".") else text + "."


def _validate(folder: Path, incoming: dict[str, dict[str, Any]], companies_of: dict[str, str | None]) -> dict[str, list[str]]:
    """The errors of each incoming pack (by the name it is kept as), from the strict check of what the load would
    build: the talent packs of the affected nodes rebuilt with the incoming packs, every other node pack on disk and the
    group packs (packgen.plan_talent_packs). A reference that no pack defines is blamed on the incoming packs that use
    it, else on the incoming group packs, one of which stopped defining it. A pack that fails is left out and the rest
    are checked again, so the packs that pass also pass together."""
    from knowledge import packgen
    errors: dict[str, list[str]] = {k: [] for k in incoming}
    left = dict(incoming)
    while left:
        group_changed = any(companies_of[k] is None for k in left)
        companies = {companies_of[k] for k in left if companies_of[k]}
        nodes = sorted(node_ids()) if group_changed else sorted(companies & set(node_ids()))
        _, report = packgen.plan_talent_packs(nodes, folder, left)
        if not report.errors:
            break
        blamed: dict[str, list[str]] = {}
        unresolved = getattr(report, "unresolved_in", {})
        groups = [k for k in left if companies_of[k] is None]
        for ref, users in unresolved.items():
            using = [k for k in left if k in users]
            reason = (f"{ref} is used in {_listed(users)}, but no pack defines it. If two entries were joined, list "
                      f"{ref} under replaces of the entry that was kept.")
            for k in using or groups or list(left):
                blamed.setdefault(k, []).append(reason)
        for err in report.errors:
            if err.startswith("ERROR   references:"):
                continue
            owner = [k for k in left if f"{k}.pack.json" in err]
            for k in owner or list(left):
                blamed.setdefault(k, []).append(_plain(err))
        if not blamed:
            break
        for k, found in blamed.items():
            errors[k] += found
            left.pop(k, None)
    return errors


def _node_pack(node: str) -> Path:
    from knowledge import packgen
    return packgen.DATA / node / "packs" / "talent" / "pack.json"


async def apply_changes(rt: Any, companies: set[str], group_changed: bool, folder: Path) -> dict[str, str]:
    """Rebuild the talent packs of the affected nodes and refresh the graph from the node exports. Returns the refresh
    result of each node ("loaded ..." when the node answered)."""
    from knowledge import packgen
    nodes = sorted(node_ids()) if group_changed else sorted(companies & set(node_ids()))
    if nodes:
        await asyncio.to_thread(packgen.rebuild_talent_packs, nodes, folder)
    return await rt.refresh_from_nodes() or {}


def _refusal(pack_id: str, code: str, reason: str) -> dict[str, Any]:
    return {"pack_id": pack_id, "kept_as": None, "result": "refused", "code": code, "reason": reason}


async def import_packs(ctx: Any, packs: list[dict[str, Any]]):
    # The import runs to its end even when the caller stops waiting (a client timeout cancels the request, not this).
    return await asyncio.shield(asyncio.ensure_future(_import(ctx, packs)))


async def _import(ctx: Any, packs: list[dict[str, Any]]):
    results, passed = _screen(ctx.app, packs)
    if passed:
        # One import at a time: the asyncio lock inside this process, the folder lock across processes (an API that runs
        # with several workers), so two imports never read the same log and write over each other's packs. A call whose
        # every pack the screen refuses takes no lock and touches no pack file.
        async with _lock:
            folder: Path = context_api.TALENT_IMPORT
            async with _folder_lock(folder):
                results += await _apply(ctx, passed, folder)
    answer = _answer(ctx, packs, results)
    try:  # the Applications page shows the latest result of each pack the registry allows the application to send
        mine = [r for r in results if ctx.app.import_rule(r["pack_id"]) is not None]
        # to the microsecond, so two calls never read as one send
        ctx.rt.store.record_send(ctx.app.id, datetime.now(timezone.utc).isoformat(timespec="microseconds"), mine)
    except Exception as exc:  # noqa: BLE001 - the import itself is done, the record is for the page only
        log.warning("context_import.send_not_recorded", error=f"{type(exc).__name__}: {str(exc)[:200]}")
    return answer


def _screen(app: Any, packs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[tuple[dict[str, Any], str, str, str | None]]]:
    """The checks that need nothing kept: a pack id the registry allows, a Mesh Node for its company, the company's own
    name in the pack, and only what its rule allows. Returns the refusals and the packs that passed, each as (pack, sent
    pack id, kept name, company)."""
    refused: list[dict[str, Any]] = []
    passed: list[tuple[dict[str, Any], str, str, str | None]] = []
    allowed = ", ".join(r.pack for r in app.imports) or "no packs"
    for pack in packs:
        header = pack.get("pack") if isinstance(pack.get("pack"), dict) else {}
        pid = str(header.get("pack_id") or "")
        found = app.import_rule(pid) if pid else None
        if found is None:
            refused.append(_refusal(pid or "(no pack_id)", "pack_refused", f"{app.name} may send {allowed}."))
            continue
        rule, (kept_as, company) = found
        if company and company not in node_ids():
            refused.append(_refusal(pid, "company_not_connected",
                                    f"{company} has no Mesh Node, so its roles stay out of the graph until it is connected."))
            continue
        if company and header.get("subsidiary") not in (None, company):
            refused.append(_refusal(pid, "pack_refused", f"the pack names subsidiary {header.get('subsidiary')}, not {company}."))
            continue
        beyond = rule.problems(pack, company, app.purposes)
        if beyond:
            refused.append(_refusal(pid, "pack_refused", "The pack holds more than its rule allows: " + "; ".join(beyond[:5]) + "."))
            continue
        passed.append((pack, pid, kept_as, company))
    return refused, passed


async def _apply(ctx: Any, passed: list[tuple[dict[str, Any], str, str, str | None]], folder: Path) -> list[dict[str, Any]]:
    """Under the locks: compare with the kept packs, validate, write, rebuild the node packs, refresh and log. Returns
    one result for each pack it was given."""
    app = ctx.app
    kept_log = _read_log(folder)
    results: list[dict[str, Any]] = []
    incoming: dict[str, dict[str, Any]] = {}
    meta: dict[str, tuple[str, str | None, str]] = {}  # kept_as -> (sent pack id, company, sha)
    for pack, pid, kept_as, company in passed:
        if kept_as in incoming:
            results.append(_refusal(pid, "pack_refused", f"{kept_as} was sent twice in one call."))
            continue
        sha = _sha(pack)
        if kept_log.get(kept_as, {}).get("sha256") == sha and (folder / f"{kept_as}.pack.json").is_file():
            results.append({"pack_id": pid, "kept_as": kept_as, "result": "unchanged", **_counts(pack)})
            continue
        stored = copy.deepcopy(pack)
        stored["pack"]["pack_id"] = kept_as
        incoming[kept_as] = stored
        meta[kept_as] = (pid, company, sha)
    if incoming:
        errors = await asyncio.to_thread(_validate, folder, incoming, {k: meta[k][1] for k in incoming})
        for kept_as in list(incoming):
            if errors[kept_as]:
                results.append(_refusal(meta[kept_as][0], "pack_refused", " ".join(errors[kept_as][:3]) + " Nothing was changed."))
                incoming.pop(kept_as)
    if incoming:
        companies = {meta[k][1] for k in incoming if meta[k][1]}
        group_changed = any(meta[k][1] is None for k in incoming)
        affected = sorted(node_ids()) if group_changed else sorted(companies)
        folder.mkdir(parents=True, exist_ok=True)
        kept_paths = [folder / f"{k}.pack.json" for k in incoming]
        node_paths = [_node_pack(n) for n in affected]
        backup = {p: (p.read_bytes() if p.is_file() else None) for p in kept_paths + node_paths}
        refreshed: dict[str, str] = {}
        try:
            for kept_as, pack in incoming.items():
                _write_atomic(folder / f"{kept_as}.pack.json", (json.dumps(pack, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
            refreshed = await apply_changes(ctx.rt, companies, group_changed, folder)
        except BaseException as exc:  # noqa: BLE001 - put back the kept packs and the node packs, then report every pack of this call
            log.warning("context_import.failed", error=f"{type(exc).__name__}: {str(exc)[:300]}")
            for path, old in backup.items():
                if old is None:
                    path.unlink(missing_ok=True)
                else:
                    _write_atomic(path, old)
            try:
                await ctx.rt.refresh_from_nodes()
            except Exception as again:  # noqa: BLE001 - the files of before are back, the next refresh loads them
                log.error("context_import.restore_refresh_failed", error=f"{type(again).__name__}: {str(again)[:200]}")
            # A check that failed at the rebuild names its reason, and sending the same pack again will not help. Any
            # other failure (a node or the store) is passing, so the next send tries again.
            reason = (f"{_plain(str(exc).removeprefix('Pack validation failed: '))} Nothing was changed."
                      if isinstance(exc, PackCheckFailed) else "NeuralMesh could not finish the load, so nothing was changed. Send it again later.")
            for kept_as in incoming:
                results.append(_refusal(meta[kept_as][0], "pack_refused", reason))
            incoming = {}
            if not isinstance(exc, Exception):
                raise
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for kept_as, pack in incoming.items():
            pid, company, sha = meta[kept_as]
            # A company pack reaches the graph through its node's export. The group pack loads in the centre.
            waiting = [company] if company and not str(refreshed.get(company, "")).startswith("loaded") else []
            if waiting:
                results.append(_refusal(pid, "node_unavailable", f"Kept, but {', '.join(waiting)} did not answer the refresh. "
                                                                "It loads at the next refresh or the next send."))
                continue
            kept_log[kept_as] = {"sent_as": pid, "by": app.id, "sha256": sha, "at": now}
            results.append({"pack_id": pid, "kept_as": kept_as, "result": "loaded", **_counts(pack)})
        if incoming:
            _write_atomic(folder / LOG_FILE, (json.dumps(kept_log, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return results


def _answer(ctx: Any, packs: list[dict[str, Any]], results: list[dict[str, Any]]):
    from services.context_catalogue import ToolResult
    order = {str(p.get("pack", {}).get("pack_id", "")) if isinstance(p.get("pack"), dict) else "": i for i, p in enumerate(packs)}
    results.sort(key=lambda r: order.get(r["pack_id"], len(order)))
    refused_ = [r for r in results if r["result"] == "refused"]
    taken = [r for r in results if r["result"] != "refused"]
    g = ctx.rt.mesh.graph
    data = {"packs": results, "revision": ctx.rt.store.revision(),
            "graph": {"roles": sum(1 for _, d in g.nodes(data=True) if d.get("type") == "Role" and not d.get("retired")),
                      "skills": sum(1 for _, d in g.nodes(data=True) if d.get("type") == "Skill" and not d.get("retired"))}}
    if not refused_:
        return ToolResult(data=data)
    detail = "Not loaded: " + ", ".join(f"{r['pack_id']} ({r['code']})" for r in refused_) + "."
    return ToolResult(status="partial" if taken else "refused", data=data, problem=problem("pack_refused", detail))
