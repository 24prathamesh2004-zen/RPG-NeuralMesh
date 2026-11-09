"""Node search and summaries: FTS5 plus Chroma merged by rank fusion, policy per item, summaries by document."""
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
from mcp_nodes.policy import PolicyDecision, authorize_caller, evaluate_access
from shared.registry import node_ids



from mcp_nodes.server_config import NodeConfig, SEARCH_LIMIT, _KIND_OF_MODE

def _fts_query(query: str) -> str:
    return fts_query(query)


def _evidence_fields(config: NodeConfig, row_key: str, mode: str, released: bool, score: float | None,
                     rank: int | None) -> dict[str, Any]:
    """Fields of the evidence record contract (contracts/evidence.py) for one returned row."""
    document = row_key.split("#", 1)[0]
    doc = config.knowledge.documents.get(document, {})
    kind = _KIND_OF_MODE.get(mode, "metadata") if released else "metadata"
    return {
        "schema_version": "1.0",
        "evidence_id": row_key,
        "kind": kind,
        "node": config.node_id,
        "document": document if not document.endswith(":live") else None,
        "pack_version": doc.get("pack_version"),
        "superseded_by": config.knowledge.superseded_by.get(document),
        "concepts": list(doc.get("concepts", [])),
        "score": round(score, 6) if score is not None else None,
        "rank": rank,
    }


def search_node(
    config: NodeConfig,
    caller: Any,
    query: str,
    purpose: str,
    *,
    mode: str | None = None,
    as_of: date | None = None,
    access_store: AccessStore | None = None,
    trace_id: str | None = None,
    domains: list[str] | None = None,
    concepts: list[str] | None = None,
    limit: int = SEARCH_LIMIT,
) -> dict[str, Any]:
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code == "BLOCKED_BY_POLICY":
        return {
            "node_id": config.node_id,
            "results": [],
            "withheld": [],
            "status": caller_decision.code,
            "rule_id": caller_decision.rule_id,
        }

    normalized_query = _fts_query(query[:1000])
    if not normalized_query:
        return {"node_id": config.node_id, "results": [], "withheld": [], "status": "empty_query"}

    ranked, trace = hybrid_rank(
        config.index_path,
        config.knowledge,
        query[:1000],
        domains=set(domains) if domains else None,
        concepts=set(concepts) if concepts else None,
        limit=max(1, min(limit, 30)),
    )
    connection = sqlite3.connect(f"file:{config.index_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        by_key = {
            row["doc_id"]: row
            for row in connection.execute(
                f"SELECT text, title, doc_id, dp, mode, sens, version, stale FROM idx WHERE doc_id IN ({','.join('?' * len(ranked))})",
                [key for key, _, _ in ranked],
            ).fetchall()
        } if ranked else {}
    finally:
        connection.close()
    rows = [(by_key[key], score, rank) for key, score, rank in ranked if key in by_key]

    results: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    trace_id = trace_id or str(uuid.uuid4())
    for row, score, rank in rows:
        requested_mode = mode or row["mode"]
        grant = (
            access_store.active_grant(caller, row["dp"], requested_mode, purpose)
            if access_store is not None
            else None
        )
        decision = evaluate_access(
            config,
            caller,
            row["dp"],
            requested_mode,
            as_of=as_of,
            grant_mode=grant["mode"] if grant is not None else None,
        )
        item_mode = requested_mode
        item = {
            "doc_id": row["doc_id"],
            "datapoint_id": row["dp"],
            "title": row["title"],
            "mode": item_mode,
            "sensitivity": row["sens"],
            "citation": f"{config.display} · {row['dp']} · {row['doc_id'].split(':', 1)[-1].split('#', 1)[0]}",
            "stale": bool(row["stale"]),
            "decision": decision.code,
            "rule_id": decision.rule_id,
        }

        if row["mode"] == "MD" and requested_mode == "MD":
            if decision.code == "ALLOWED":
                # metadata may be listed, so the item says what policy decides about the content itself
                decision = evaluate_access(config, caller, row["dp"], "SUM", as_of=as_of)
                item["decision"], item["rule_id"] = decision.code, decision.rule_id
            item["reason"] = decision.reason
            withheld.append(item)
        elif decision.code in ("ALLOWED", "ALLOWED_SUMMARY_ONLY"):
            if requested_mode == "RAG" and row["mode"] != "RAG":
                body = _read_gated_body(config, row["doc_id"], row["dp"])
                if body is not None and grant is not None:
                    item["text"] = body
                elif row["mode"] == "MD":
                    decision = PolicyDecision(
                        "BLOCKED_BY_POLICY",
                        "R-GATED-MISSING",
                        "Approved gated content is unavailable",
                        "MD",
                    )
                    item["reason"] = decision.reason
                    item["decision"] = decision.code
                    item["rule_id"] = decision.rule_id
                    withheld.append(item)
                else:
                    item["text"] = row["text"]
            elif decision.code in ("ALLOWED", "ALLOWED_SUMMARY_ONLY"):
                item["text"] = row["text"]
            if decision.code in ("ALLOWED", "ALLOWED_SUMMARY_ONLY"):
                item["suspicious"] = bool(
                    re.search(
                        r"ignore\s+previous\s+instructions|disregard\s+the\s+system\s+prompt",
                        item.get("text", ""),
                        re.I,
                    )
                )
                results.append(item)
            elif not any(existing is item for existing in withheld):
                item["reason"] = decision.reason
                withheld.append(item)
        elif row["mode"] == "MD":
            item["reason"] = decision.reason
            withheld.append(item)
        else:
            item["reason"] = decision.reason
            withheld.append(item)

        if access_store is not None:
            access_store.log_decision(
                caller=caller,
                action="search",
                datapoint_id=row["dp"],
                decision=decision,
                trace_id=trace_id,
                request_id=grant["request_id"] if grant is not None else None,
                grant_id=grant["grant_id"] if grant is not None else None,
            )

    scored = {row["doc_id"]: (score, rank) for row, score, rank in rows}
    for released, items in ((True, results), (False, withheld)):
        for item in items:
            score, rank = scored.get(item["doc_id"], (None, None))
            item.update(_evidence_fields(config, item["doc_id"], item["mode"], released, score, rank))
            item["datapoint"] = f"{config.node_id}:{item['datapoint_id']}"
            item["version"] = str(by_key[item["doc_id"]]["version"]) if item["doc_id"] in by_key else None
            item["reason"] = item.get("reason")
            if not released:
                item.pop("text", None)

    return {
        "node_id": config.node_id,
        "results": results,
        "withheld": withheld,
        "status": "ok",
        "search": {**trace, "domains": sorted(domains or []), "concepts": sorted(concepts or [])},
    }


def _read_gated_body(config: NodeConfig, doc_id: str, datapoint_id: str) -> str | None:
    document_id = doc_id.split(":", 1)[-1].split("#", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", document_id):
        return None
    path = config.index_path.parent / "gated" / f"{document_id}.md"
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        return None
    _, _, remainder = content.partition("---\n")
    _, separator, body = remainder.partition("\n---\n")
    if not separator:
        return None
    metadata = yaml.safe_load(remainder.split("\n---\n", 1)[0])
    if not isinstance(metadata, dict) or metadata.get("datapoint_id") != datapoint_id:
        return None
    return body.strip() or None


def _read_source_metadata(config: NodeConfig, document_id: str) -> dict[str, Any] | None:
    normalized_id = document_id.split(":", 1)[-1].split("#", 1)[0]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", normalized_id):
        return None
    path = config.index_path.parent / "source" / f"{normalized_id}.md"
    if not path.is_file():
        return None
    content = path.read_text(encoding="utf-8")
    if not content.startswith("---\n"):
        return None
    _, _, remainder = content.partition("---\n")
    metadata_text, separator, _ = remainder.partition("\n---\n")
    if not separator:
        return None
    metadata = yaml.safe_load(metadata_text)
    return metadata if isinstance(metadata, dict) else None


def _summary_record(config: NodeConfig, metadata: dict, datapoint: Mapping[str, Any], decision: PolicyDecision,
                    *, released: bool) -> dict[str, Any]:
    document = str(metadata.get("id"))
    fields = _evidence_fields(config, document, "SUM", released, None, None)
    fields.update({
        "datapoint": f"{config.node_id}:{metadata.get('datapoint_id')}",
        "version": str(metadata.get("version")),
        "mode": "SUM" if released else "MD",
        "sensitivity": datapoint.get("sensitivity"),
        "rule_id": decision.rule_id,
    })
    return fields


def summarize_node(
    config: NodeConfig,
    caller: Any,
    document_id: str,
    purpose: str,
    store: AccessStore,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code == "BLOCKED_BY_POLICY":
        return {"node_id": config.node_id, "decision": caller_decision.code, "rule_id": caller_decision.rule_id}

    metadata = _read_source_metadata(config, document_id)
    if metadata is None or metadata.get("company") != config.node_id:
        return {"node_id": config.node_id, "decision": "NOT_FOUND", "summary": None}

    datapoint_id = metadata.get("datapoint_id")
    datapoint = config.datapoints.get(datapoint_id)
    if datapoint is None:
        return {"node_id": config.node_id, "decision": "BLOCKED_BY_POLICY", "summary": None}

    requested_mode = "SUM"
    grant = None
    if datapoint.get("requires_approval"):
        requested_mode = str(datapoint.get("ceiling", "SUM"))
        grant = store.active_grant(
            caller,
            datapoint_id,
            requested_mode,
            purpose,
        )
    decision = evaluate_access(
        config,
        caller,
        datapoint_id,
        requested_mode,
        grant_mode=grant["mode"] if grant is not None else None,
    )
    if decision.code in ("ALLOWED", "ALLOWED_SUMMARY_ONLY"):
        response = {
            "node_id": config.node_id,
            "decision": "ALLOWED_SUMMARY_ONLY",
            "rule_id": decision.rule_id,
            "datapoint_id": datapoint_id,
            "title": metadata.get("title"),
            "citation": f"{config.display} · {datapoint_id} · {str(metadata.get('id', document_id)).split(':', 1)[-1]}",
            "stale": int(str(metadata.get("version", "2026"))[:4]) < 2021,
            "summary": metadata.get("approved_summary"),
            **_summary_record(config, metadata, datapoint, decision, released=True),
        }
    else:
        response = {
            "node_id": config.node_id,
            "decision": decision.code,
            "rule_id": decision.rule_id,
            "datapoint_id": datapoint_id,
            "title": metadata.get("title"),
            "summary": metadata.get("approved_summary") if decision.code == "NEEDS_APPROVAL" else None,
            "reason": decision.reason,
            **_summary_record(config, metadata, datapoint, decision, released=False),
        }

    store.log_decision(
        caller=caller,
        action="summarize",
        datapoint_id=datapoint_id,
        decision=decision,
        trace_id=trace_id or str(uuid.uuid4()),
        request_id=grant["request_id"] if grant is not None else None,
        grant_id=grant["grant_id"] if grant is not None else None,
    )
    return response


