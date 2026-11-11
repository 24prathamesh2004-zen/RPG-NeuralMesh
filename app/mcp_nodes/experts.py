"""Consented experts, introductions and content access requests of one node."""
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



from mcp_nodes.server_config import NodeConfig

_STOP_WORDS = frozenset({"a", "an", "the", "of", "and", "or", "in", "on", "for", "to", "with", "at", "by", "from", "who",
                         "what", "which", "how", "can", "is", "are", "do", "does", "about", "our", "we", "i", "me", "my",
                         "has", "have", "had", "find", "someone", "people", "person", "expert", "experts"})


# Words of almost every job title: alone they say nothing about what an expert knows ("lead" in "Field service lead").
_JOB_TITLE_WORDS = frozenset({"lead", "manager", "head", "engineer", "officer", "specialist", "analyst", "director",
                              "executive", "coordinator", "supervisor", "consultant", "associate", "assistant",
                              "senior", "junior", "chief"})


def find_experts_node(
    config: NodeConfig,
    caller: Any,
    query: str,
    purpose: str,
    store: AccessStore,
    *,
    trace_id: str | None = None,
    concepts: list[str] | None = None,
) -> dict[str, Any]:
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code == "BLOCKED_BY_POLICY":
        return {"node_id": config.node_id, "decision": caller_decision.code, "experts": []}

    # Words that say nothing about a skill never make a match ("Head of delivery" matched "of"). A word of one of the
    # expert's listed skills counts 2 ("traceability"), a word only of the job title counts 1 ("quality" in "Quality
    # assurance manager"), and a concept of the expert's evidence counts 2. A query of three or more words needs 2, so
    # one skill word finds its expert and one shared title word alone lists no profile.
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()[:500])) - _STOP_WORDS
    needed = 1 if len(query_tokens) <= 2 else 2
    # The concepts of a never-leave document count only for the node's own company and mesh admins: no reader of
    # another company sees an expert listed or ranked higher because of a document that never leaves.
    own = caller.company == config.node_id or "mesh_admin" in caller.roles

    def counted(doc_id: str) -> bool:
        datapoint = str(config.knowledge.documents.get(doc_id, {}).get("datapoint", "")).split(":", 1)[-1]
        return own or not config.datapoints.get(datapoint, {}).get("never_leave")

    matches: list[tuple[int, Mapping[str, Any]]] = []
    for expert in config.experts:
        if expert.get("consent") is not True:
            continue
        skill_tokens = set(re.findall(r"[a-z0-9]+", " ".join(expert.get("skills", [])).lower())) - _STOP_WORDS
        role_words = re.findall(r"[a-z0-9]+", str(expert.get("role", "")).lower())
        role_tokens = set(role_words) - _STOP_WORDS - skill_tokens - _JOB_TITLE_WORDS
        # a phrase of the job title in the question ("quality lead") also counts, so the job word is not lost
        query_text = " " + " ".join(re.findall(r"[a-z0-9]+", query.lower()[:500])) + " "
        # a phrase made only of generic title words and fillers ("head of") says nothing about the expert
        phrases = sum(1 for a, b in zip(role_words, role_words[1:]) if f" {a} {b} " in query_text
                      and not {a, b} <= _JOB_TITLE_WORDS | _STOP_WORDS)
        score = 2 * len(query_tokens & skill_tokens) + len(query_tokens & role_tokens) + phrases
        evidence_concepts = {
            c for doc_id in expert.get("evidence", []) if counted(doc_id)
            for c in config.knowledge.documents.get(doc_id, {}).get("concepts", [])
        }
        score += 2 * len(set(concepts or ()).intersection(evidence_concepts))
        if score >= needed:
            matches.append((score, expert))

    result: list[dict[str, Any]] = []
    for score, expert in sorted(matches, key=lambda match: (-match[0], str(match[1]["id"])))[:10]:
        item = {
            "expert_id": expert["id"],
            "company": config.display,
            "role": expert["role"],
            "skills": expert["skills"],
            "evidence": expert["evidence"],
            "match_score": score,
            "name_available_after_intro_approval": True,
            "schema_version": "1.0",
            "evidence_id": f"{config.node_id}:expert/{expert['id']}",
            "kind": "expert",
            "node": config.node_id,
            "citation": f"{config.display} · F-04 · {expert['id']}",
        }
        grant = store.active_grant(
            caller,
            "F-04",
            "INTRO",
            purpose,
            kind="intro",
            target_id=expert["id"],
        )
        if grant is not None:
            private_data = expert.get("private")
            if isinstance(private_data, dict) and isinstance(private_data.get("name"), str):
                item["name"] = private_data["name"]
                item["name_available_after_intro_approval"] = False
        result.append(item)

    decision = PolicyDecision("ALLOWED", "R-EXPERT-CONSENT", "Consent-filtered expert search", "LIVE")
    store.log_decision(
        caller=caller,
        action="find_experts",
        datapoint_id="F-04",
        decision=decision,
        trace_id=trace_id or str(uuid.uuid4()),
    )
    return {"node_id": config.node_id, "decision": decision.code, "experts": result}


def request_intro_node(
    config: NodeConfig,
    store: AccessStore,
    caller: Any,
    expert_id: str,
    purpose: str,
    justification: str,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code == "BLOCKED_BY_POLICY":
        return {"status": caller_decision.code, "rule_id": caller_decision.rule_id}

    expert = next(
        (item for item in config.experts if item.get("id") == expert_id and item.get("consent") is True),
        None,
    )
    if expert is None:
        decision = PolicyDecision("BLOCKED_BY_POLICY", "R-EXPERT-CONSENT", "Expert is unavailable or has not opted in", "MD")
        store.log_decision(
            caller=caller,
            action="request_intro",
            datapoint_id="F-04",
            decision=decision,
            trace_id=trace_id or str(uuid.uuid4()),
        )
        return {"status": decision.code, "rule_id": decision.rule_id, "reason": decision.reason}

    try:
        request = store.request_access(
            caller,
            "F-04",
            "INTRO",
            purpose,
            justification,
            kind="intro",
            target_id=expert_id,
        )
    except ValueError as exc:
        return {"status": "invalid_request", "reason": str(exc)}

    decision = PolicyDecision("NEEDS_APPROVAL", "R-EXPERT-INTRO", "Expert introduction requires owner approval", "MD")
    store.log_decision(
        caller=caller,
        action="request_intro",
        datapoint_id="F-04",
        decision=decision,
        trace_id=trace_id or str(uuid.uuid4()),
        request_id=request["request_id"],
    )
    return {
        "node_id": config.node_id,
        **request,
        "approver": config.datapoints["F-04"].get("owner_role"),
    }


def request_access_node(
    config: NodeConfig,
    store: AccessStore,
    caller: Any,
    datapoint_id: str,
    mode: str,
    purpose: str,
    justification: str,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code == "BLOCKED_BY_POLICY":
        store.log_decision(
            caller=caller,
            action="request_access",
            datapoint_id=datapoint_id,
            decision=caller_decision,
            trace_id=trace_id or str(uuid.uuid4()),
        )
        return {"status": caller_decision.code, "rule_id": caller_decision.rule_id}

    decision = evaluate_access(config, caller, datapoint_id, mode)
    result: dict[str, Any] = {
        "node_id": config.node_id,
        "decision": decision.code,
        "rule_id": decision.rule_id,
        "reason": decision.reason,
    }
    request_id = None
    if decision.code == "NEEDS_APPROVAL":
        try:
            request = store.request_access(caller, datapoint_id, mode, purpose, justification)
        except ValueError as exc:
            return {**result, "status": "invalid_request", "reason": str(exc)}
        request_id = request["request_id"]
        result.update(request)
        result["approver"] = config.datapoints[datapoint_id].get("owner_role")
    else:
        result["status"] = decision.code

    store.log_decision(
        caller=caller,
        action="request_access",
        datapoint_id=datapoint_id,
        decision=decision,
        trace_id=trace_id or str(uuid.uuid4()),
        request_id=request_id,
    )
    return result


