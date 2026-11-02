"""Node-local time-boxed grants and content-free decision audit."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from mcp_nodes.auth import CallerContext
from mcp_nodes.policy import PolicyDecision
from mcp_nodes.server_types import NodeAuthConfig

_GENESIS = "0" * 64


class AccessStore:
    def __init__(self, database_path: Path, audit_path: Path, config: NodeAuthConfig) -> None:
        self.database_path = database_path
        self.audit_path = audit_path
        self.config = config
        database_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS access_requests (
                    request_id TEXT PRIMARY KEY,
                    requester_sub TEXT NOT NULL,
                    requester_company TEXT NOT NULL,
                    kind TEXT NOT NULL DEFAULT 'content',
                    datapoint_id TEXT NOT NULL,
                    target_id TEXT,
                    mode TEXT NOT NULL,
                    purpose TEXT NOT NULL,
                    justification TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','approved','denied','revoked','expired')),
                    requested_at TEXT NOT NULL,
                    approver TEXT,
                    approved_at TEXT,
                    expires_at TEXT,
                    grant_id TEXT UNIQUE
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS access_grants_lookup "
                "ON access_requests(requester_sub, requester_company, datapoint_id, mode, status)"
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(access_requests)")}
            if "kind" not in columns:
                connection.execute("ALTER TABLE access_requests ADD COLUMN kind TEXT NOT NULL DEFAULT 'content'")
            if "target_id" not in columns:
                connection.execute("ALTER TABLE access_requests ADD COLUMN target_id TEXT")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def request_access(
        self,
        caller: CallerContext,
        datapoint_id: str,
        mode: str,
        purpose: str,
        justification: str,
        *,
        kind: str = "content",
        target_id: str | None = None,
    ) -> dict[str, Any]:
        if len(justification.strip()) < 10 or len(justification) > 500:
            raise ValueError("Justification must be between 10 and 500 characters")
        datapoint = self.config.datapoints.get(datapoint_id)
        if datapoint is None:
            raise ValueError("Unknown datapoint")
        if kind == "content":
            approval_mode = datapoint.get("upgrade_with_approval") or (
                datapoint.get("ceiling") if datapoint.get("requires_approval") else None
            )
            if datapoint.get("never_leave") or datapoint.get("ceiling") == "MD" or mode != approval_mode:
                raise ValueError("This datapoint does not permit the requested approval mode")
            if target_id is not None:
                raise ValueError("Content access requests cannot include an expert target")
        elif kind == "intro":
            expert = next((item for item in self.config.experts if item.get("id") == target_id), None)
            if (
                datapoint_id != "F-04"
                or mode != "INTRO"
                or not datapoint.get("consent_required")
                or expert is None
                or expert.get("consent") is not True
            ):
                raise ValueError("Introduction request is not allowed for this expert")
        else:
            raise ValueError("Request kind must be content or intro")
        request_id = f"AR-{uuid.uuid4().hex[:12].upper()}"
        requested_at = _now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO access_requests
                   (request_id, requester_sub, requester_company, kind, datapoint_id,
                    target_id, mode, purpose, justification, status, requested_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    request_id,
                    caller.subject,
                    caller.company,
                    kind,
                    datapoint_id,
                    target_id,
                    mode,
                    purpose,
                    justification.strip(),
                    requested_at,
                ),
            )
        return {"request_id": request_id, "status": "pending", "datapoint_id": datapoint_id, "mode": mode}

    def active_grant(
        self,
        caller: CallerContext,
        datapoint_id: str,
        mode: str,
        purpose: str,
        *,
        kind: str = "content",
        target_id: str | None = None,
    ) -> sqlite3.Row | None:
        now = _now()
        with self._connect() as connection:
            return connection.execute(
                """SELECT request_id, grant_id, requester_sub, requester_company,
                                                    datapoint_id, mode, purpose, approver, expires_at, kind, target_id
                   FROM access_requests
                   WHERE requester_sub = ? AND requester_company = ?
                     AND datapoint_id = ? AND mode = ? AND status = 'approved'
                                         AND purpose = ? AND kind = ? AND target_id IS ? AND expires_at > ?
                   ORDER BY expires_at DESC LIMIT 1""",
                                (caller.subject, caller.company, datapoint_id, mode, purpose, kind, target_id, now),
            ).fetchone()

    def pending(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT request_id, requester_sub, requester_company, kind, datapoint_id,
                          target_id, mode, purpose, requested_at
                   FROM access_requests WHERE status = 'pending' ORDER BY requested_at"""
            ).fetchall()
        return [dict(row) for row in rows]

    def review(
        self,
        request_id: str,
        approver: str,
        decision: str,
        *,
        hours: int = 24,
    ) -> dict[str, Any]:
        if decision not in {"approve", "deny"}:
            raise ValueError("Decision must be approve or deny")
        if not approver.strip():
            raise ValueError("Approver is required")

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM access_requests WHERE request_id = ?", (request_id,)
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown access request: {request_id}")
            if row["status"] != "pending":
                raise ValueError(f"Request is not pending: {row['status']}")
            datapoint = self.config.datapoints.get(row["datapoint_id"])
            if datapoint is None:
                raise ValueError("Request references an unknown datapoint")
            expected_approver = str(datapoint.get("owner_role", ""))
            if approver.strip().casefold() != expected_approver.casefold():
                raise ValueError(f"Only the designated owner role may review this request: {expected_approver}")

            event: dict[str, Any] = {
                "node_id": self.config.node_id,
                "caller_sub": row["requester_sub"],
                "caller_company": row["requester_company"],
                "action": "approval_review",
                "datapoint_id": row["datapoint_id"],
                "decision": "ALLOWED" if decision == "approve" else "BLOCKED_BY_POLICY",
                "rule_id": "R-OWNER-APPROVAL" if decision == "approve" else "R-OWNER-DENIAL",
                "request_id": request_id,
                "grant_id": None,
                "approver": approver.strip(),
            }

            if decision == "deny":
                connection.execute(
                    "UPDATE access_requests SET status='denied', approver=? WHERE request_id=?",
                    (approver.strip(), request_id),
                )
                return {"request_id": request_id, "status": "denied", "audit_event": event}

            if not 1 <= hours <= 168:
                raise ValueError("Grant duration must be from 1 to 168 hours")
            if datapoint.get("never_leave") or datapoint.get("ceiling") == "MD":
                raise ValueError("Never-leave and metadata-only datapoints cannot be approved")
            allowed_grant = datapoint.get("upgrade_with_approval") or (
                datapoint.get("ceiling") if datapoint.get("requires_approval") else None
            )
            if row["kind"] == "intro":
                expert = next((item for item in self.config.experts if item.get("id") == row["target_id"]), None)
                if row["datapoint_id"] != "F-04" or row["mode"] != "INTRO" or not expert or not expert.get("consent"):
                    raise ValueError("Introduction grant is not permitted for this expert")
            elif row["kind"] != "content" or row["mode"] != allowed_grant:
                raise ValueError("Requested mode exceeds this datapoint's approval ceiling")

            grant_id = f"GR-{uuid.uuid4().hex[:12].upper()}"
            approved_at = _now()
            expires_at = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
            connection.execute(
                """UPDATE access_requests
                   SET status='approved', approver=?, approved_at=?, expires_at=?, grant_id=?
                   WHERE request_id=?""",
                (approver.strip(), approved_at, expires_at, grant_id, request_id),
            )
            event["grant_id"] = grant_id
            return {
                "request_id": request_id,
                "grant_id": grant_id,
                "status": "approved",
                "mode": row["mode"],
                "expires_at": expires_at,
                "audit_event": event,
            }

    def revoke(self, grant_id: str, approver: str) -> dict[str, Any]:
        if not approver.strip():
            raise ValueError("Approver is required")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                     """SELECT request_id, requester_sub, requester_company, datapoint_id,
                                  grant_id
                   FROM access_requests WHERE grant_id=? AND status='approved'""",
                (grant_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"Unknown active grant: {grant_id}")
            datapoint = self.config.datapoints.get(row["datapoint_id"])
            expected_approver = str(datapoint.get("owner_role", "")) if datapoint else ""
            if approver.strip().casefold() != expected_approver.casefold():
                raise ValueError(f"Only the designated owner role may revoke this grant: {expected_approver}")
            connection.execute(
                "UPDATE access_requests SET status='revoked', approver=? WHERE grant_id=?",
                (approver.strip(), grant_id),
            )
        return {
            "request_id": row["request_id"],
            "grant_id": row["grant_id"],
            "status": "revoked",
            "audit_event": {
                "node_id": self.config.node_id,
                "caller_sub": row["requester_sub"],
                "caller_company": row["requester_company"],
                "action": "grant_revocation",
                "datapoint_id": row["datapoint_id"],
                "decision": "BLOCKED_BY_POLICY",
                "rule_id": "R-GRANT-REVOKED",
                "request_id": row["request_id"],
                "grant_id": row["grant_id"],
                "approver": approver.strip(),
            },
        }

    def log_decision(
        self,
        *,
        caller: CallerContext,
        action: str,
        datapoint_id: str,
        decision: PolicyDecision,
        trace_id: str,
        request_id: str | None = None,
        grant_id: str | None = None,
        approver: str | None = None,
    ) -> str:
        event: dict[str, Any] = {
            "timestamp": _now(),
            "trace_id": trace_id,
            "node_id": self.config.node_id,
            "caller_sub": caller.subject,
            "caller_company": caller.company,
            "action": action,
            "datapoint_id": datapoint_id,
            "decision": decision.code,
            "rule_id": decision.rule_id,
            "request_id": request_id,
            "grant_id": grant_id,
        }
        if approver is not None:
            event["approver"] = approver
        return self.append_event(event)

    def append_event(self, event: dict[str, Any]) -> str:
        record = {**event}
        record.setdefault("timestamp", _now())
        record.setdefault("trace_id", str(uuid.uuid4()))
        previous_hash = _GENESIS
        with _file_lock(self.audit_path):
            if self.audit_path.exists() and self.audit_path.stat().st_size:
                if not verify_audit(self.audit_path):
                    raise ValueError("Refusing to append to an invalid audit chain")
                with self.audit_path.open("rb") as stream:
                    stream.seek(max(0, self.audit_path.stat().st_size - 8192))
                    lines = stream.read().splitlines()
                if lines:
                    previous_hash = json.loads(lines[-1])["entry_hash"]
            hash_input = json.dumps(
                {"event": record, "previous_hash": previous_hash},
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            entry_hash = hashlib.sha256(hash_input).hexdigest()
            record.update(previous_hash=previous_hash, entry_hash=entry_hash)
            with self.audit_path.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n")
        return entry_hash


def verify_audit(path: Path) -> bool:
    previous_hash = _GENESIS
    if not path.exists():
        return True
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            entry_hash = record.pop("entry_hash")
            recorded_previous = record.pop("previous_hash")
            if recorded_previous != previous_hash:
                return False
            expected = hashlib.sha256(
                json.dumps(
                    {"event": record, "previous_hash": previous_hash},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            if entry_hash != expected:
                return False
            previous_hash = entry_hash
    return True


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def _file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_mode = "r+b" if lock_path.exists() else "w+b"
    with lock_path.open(lock_mode) as lock_file:
        if os.name == "nt":
            import msvcrt

            lock_file.seek(0)
            if lock_file.read(1) == b"":
                lock_file.seek(0)
                lock_file.write(b"0")
                lock_file.flush()
            lock_file.seek(0)
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                import msvcrt

                lock_file.seek(0)
                msvcrt.locking(lock_file.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)