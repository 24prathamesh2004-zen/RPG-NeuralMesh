"""Aggregate views of one node: grouped figures computed now from the company's own database, never row by row.

A datapoint names its views in the policy file (for example O-05 names v_spoilage_by_month). A view is a SQL view
of the node's structured database whose every row covers a group of at least ``min_group`` members (the n_* column).
The node reads the view at request time, drops any row under the minimum, and returns the rows as one evidence
record of kind ``aggregate``. Row-level data never leaves the database, and nothing is stored in the mesh.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import date, datetime, timezone
from typing import Any

from mcp_nodes.access_store import AccessStore
from mcp_nodes.policy import PolicyDecision, authorize_caller, evaluate_access
from mcp_nodes.server_config import NodeConfig

MAX_ROWS = 48  # groups shown in one record
READ_LIMIT = 500  # rows read from a view at most
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PERIOD = re.compile(r"\d{4}(-\d{2}){0,2}")  # a year, a month or a day as the first column of a view


def view_words(view: str) -> str:
    """``v_spoilage_by_month`` as ``spoilage by month``."""
    return re.sub(r"^v_", "", view).replace("_", " ")


def _record(config: NodeConfig, datapoint_id: str, view: str, decision: PolicyDecision, *, text: str | None,
            rows: int, mode: str, released: bool) -> dict[str, Any]:
    dp = config.datapoints.get(datapoint_id, {})
    return {
        "evidence_id": f"{config.node_id}:{datapoint_id}@{view}",
        "kind": "aggregate" if released else "metadata",
        "node": config.node_id,
        "datapoint": f"{config.node_id}:{datapoint_id}",
        "datapoint_id": datapoint_id,
        "document": None,
        "title": f"{dp.get('title', datapoint_id)} · {view_words(view)}",
        "view": view,
        "version": "computed",
        "mode": mode,
        "sensitivity": dp.get("sensitivity"),
        "decision": decision.code,
        "rule_id": decision.rule_id,
        "reason": decision.reason,
        "text": text,
        "rows": rows,
        "citation": f"{config.display} · {datapoint_id} · {view_words(view)}",
        "computed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def read_view(config: NodeConfig, datapoint_id: str, view: str) -> tuple[list[str], list[tuple], int]:
    """Columns, the rows at or above the group minimum, and the count of rows dropped under it."""
    dp = config.datapoints.get(datapoint_id, {})
    if config.structured_db is None or not config.structured_db.is_file():
        raise FileNotFoundError("structured database missing")
    connection = sqlite3.connect(f"file:{config.structured_db.as_posix()}?mode=ro", uri=True)
    try:
        columns = [c[1] for c in connection.execute(f"PRAGMA table_info({view})")]
        rows = connection.execute(f"SELECT * FROM {view} LIMIT {READ_LIMIT}").fetchall()
    finally:
        connection.close()
    group_col = next((i for i, c in enumerate(columns) if c.startswith("n_")), None)
    minimum = int(dp.get("min_group", 3))
    kept = [r for r in rows if group_col is None or (r[group_col] or 0) >= minimum]
    return columns, kept, len(rows) - len(kept)


def aggregate_node(config: NodeConfig, caller: Any, datapoint_id: str, view: str, purpose: str,
                   access_store: AccessStore | None = None, *, as_of: date | None = None) -> dict[str, Any]:
    """One aggregate view as an evidence record, or a withheld record with the policy decision."""
    trace_id = str(uuid.uuid4())

    def log(decision: PolicyDecision) -> None:
        if access_store is not None:
            access_store.log_decision(caller=caller, action=f"aggregate:{view}", datapoint_id=datapoint_id,
                                      decision=decision, trace_id=trace_id)

    dp = config.datapoints.get(datapoint_id)
    if dp is None or not _NAME.match(view or "") or view not in (dp.get("views") or []):
        decision = PolicyDecision("NOT_AVAILABLE", "R-AGG-00", "No such aggregate view for this datapoint", "MD")
        log(decision)
        return _record(config, datapoint_id, view, decision, text=None, rows=0, mode="MD", released=False)
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code != "ALLOWED":
        log(caller_decision)
        return _record(config, datapoint_id, view, caller_decision, text=None, rows=0, mode="MD", released=False)
    # a view is a summary of many rows: it leaves at the summary level, or as a live figure for a live datapoint
    mode = "LIVE" if dp.get("ceiling") == "LIVE" else "SUM"
    decision = evaluate_access(config, caller, datapoint_id, mode, as_of=as_of)
    if decision.code not in ("ALLOWED", "ALLOWED_SUMMARY_ONLY"):
        log(decision)
        return _record(config, datapoint_id, view, decision, text=None, rows=0, mode="MD", released=False)
    try:
        columns, rows, dropped = read_view(config, datapoint_id, view)
    except (sqlite3.Error, FileNotFoundError) as exc:
        decision = PolicyDecision("NOT_AVAILABLE", "R-AGG-02", f"The view could not be read: {type(exc).__name__}", "MD")
        log(decision)
        return _record(config, datapoint_id, view, decision, text=None, rows=0, mode="MD", released=False)
    shown, by_period = rows, False
    if len(rows) > MAX_ROWS:
        # a view over periods (a month or a year in its first column) shows the latest periods, any other view its first rows
        by_period = bool(columns) and all(_PERIOD.fullmatch(str(r[0] or "")) for r in rows)
        shown = sorted(rows, key=lambda r: str(r[0]), reverse=True)[:MAX_ROWS] if by_period else rows[:MAX_ROWS]
    lines = [f"Computed now from {config.structured_db.name if config.structured_db else 'the company database'}: "
             f"{len(rows)} groups, each of at least {int(dp.get('min_group', 3))} members"
             + (f", {dropped} smaller groups suppressed" if dropped else "") + "."]
    lines += [", ".join(f"{c} {v}" for c, v in zip(columns, r)) for r in shown]
    if len(rows) > MAX_ROWS:
        lines.append(f"The latest {MAX_ROWS} groups by {columns[0]} are shown, {len(rows) - MAX_ROWS} earlier groups not shown."
                     if by_period else f"{len(rows) - MAX_ROWS} further groups not shown.")
    decision = PolicyDecision("ALLOWED", str(dp.get("rule_id", "R-AGG-01")), "Aggregate view released at group level", mode)
    log(decision)
    return _record(config, datapoint_id, view, decision, text="\n".join(lines), rows=len(rows), mode=mode, released=True)
