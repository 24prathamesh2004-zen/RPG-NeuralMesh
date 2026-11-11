"""Live facts of one node, read at request time from the subsidiary's own system and never stored in the mesh."""
from __future__ import annotations


import os
import re
import sqlite3
import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import yaml
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from mcp_nodes.auth import caller_context_from_token, load_auth_config
from mcp_nodes.access_store import AccessStore
from mcp_nodes.knowledge_view import NodeKnowledge, fts_query, hybrid_rank, load_node_knowledge
from mcp_nodes.policy import PolicyDecision, authorize_caller
from shared.registry import node_ids



from mcp_nodes.server_config import NodeConfig

LIVE_DIR = Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack" / "kb" / "live"


def lookup_node(config: NodeConfig, caller: Any, fact: str, key: str, access_store: AccessStore | None = None) -> dict[str, Any]:
    """Live facts come from the subsidiary's own system (here a synthetic file per node). The caller must be
    authorised, the fact must exist, and the answer carries the time of the lookup. Nothing is cached."""
    from datetime import datetime, timezone

    decision = authorize_caller(config, caller)
    now = datetime.now(timezone.utc).isoformat()
    if decision.code != "ALLOWED":
        if access_store is not None:
            access_store.log_decision(caller=caller, action=f"lookup:{fact}", datapoint_id="LIVE", decision=decision, trace_id=str(uuid.uuid4()))
        return {"decision": decision.code, "rule_id": decision.rule_id, "reason": decision.reason, "value": None, "looked_up_at": now, "mode": "LIVE"}
    path = LIVE_DIR / f"{config.node_id}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except (ValueError, OSError):
        data = {}
    table = data.get(fact) if isinstance(data, dict) else None
    entry = table.get(key) if isinstance(table, dict) else None
    entry = entry if isinstance(entry, dict) else None
    decision = PolicyDecision("ALLOWED" if entry is not None else "NOT_AVAILABLE", "R-LIVE-01",
                              "Live fact released to an authorised caller" if entry is not None else "No live record for this key", "LIVE")
    if access_store is not None:
        access_store.log_decision(caller=caller, action=f"lookup:{fact}", datapoint_id="LIVE", decision=decision, trace_id=str(uuid.uuid4()))
    return {"decision": decision.code, "rule_id": decision.rule_id, "reason": decision.reason, "mode": "LIVE", "looked_up_at": now,
            "value": entry.get("value") if entry else None, "details": {k: v for k, v in (entry or {}).items() if k != "value"}}


