"""Shared runtime for independently launched subsidiary MCP servers."""
from __future__ import annotations

import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
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
from mcp_nodes.policy import PolicyDecision, authorize_caller, evaluate_access

NODE_IDS = ("ceat", "kec", "zensar", "harrisons")
_PACK_ROOT = Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack" / "data_pack"
_STATE_ROOT = Path(__file__).resolve().parents[1] / ".neuralmesh" / "nodes"


@dataclass(frozen=True)
class NodeConfig:
    node_id: str
    display: str
    port: int
    level: str
    schema_version: str
    defaults: Mapping[str, Any]
    datapoints: Mapping[str, Mapping[str, Any]]
    experts: tuple[Mapping[str, Any], ...]
    calendar_windows: tuple[Mapping[str, str], ...]
    index_path: Path
    grants_path: Path
    audit_path: Path


def _read_mapping(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a YAML mapping in {path}")
    return value


def load_node_config(node_id: str, data_root: Path | None = None) -> NodeConfig:
    """Load and validate one subsidiary's generated node and policy files."""
    if node_id not in NODE_IDS:
        raise ValueError(f"Unknown subsidiary node: {node_id}")

    node_dir = (data_root or _PACK_ROOT) / node_id
    node = _read_mapping(node_dir / "node.yaml")
    policy = _read_mapping(node_dir / "policy.yaml")
    experts = yaml.safe_load((node_dir / "experts.yaml").read_text(encoding="utf-8"))
    datapoints = policy.get("datapoints")
    defaults = policy.get("defaults", {})
    calendar_name = policy.get("calendar")

    if node.get("node_id") != node_id or policy.get("node") != node_id:
        raise ValueError(f"Node and policy identity do not match {node_id}")
    if not isinstance(datapoints, dict) or not datapoints:
        raise ValueError(f"Node {node_id} has no policy datapoints")
    if not isinstance(defaults, dict):
        raise ValueError(f"Node {node_id} has invalid policy defaults")
    if not isinstance(experts, list) or any(
        not isinstance(expert, dict)
        or not isinstance(expert.get("id"), str)
        or not isinstance(expert.get("role"), str)
        or not isinstance(expert.get("skills"), list)
        or not isinstance(expert.get("evidence"), list)
        or not isinstance(expert.get("consent"), bool)
        for expert in experts
    ):
        raise ValueError(f"Node {node_id} has invalid expert-directory data")

    port = node.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError(f"Node {node_id} has an invalid port: {port!r}")

    for datapoint_id, datapoint in datapoints.items():
        if not isinstance(datapoint, dict) or not all(
            isinstance(datapoint.get(field), str)
            for field in ("title", "sensitivity", "ceiling")
        ):
            raise ValueError(f"Node {node_id} has an invalid datapoint: {datapoint_id}")

    calendar_windows: tuple[Mapping[str, str], ...] = ()
    if calendar_name:
        if not isinstance(calendar_name, str) or Path(calendar_name).name != calendar_name:
            raise ValueError(f"Node {node_id} has an invalid calendar filename")
        calendar = _read_mapping(node_dir / calendar_name)
        windows = calendar.get("windows", [])
        if not isinstance(windows, list) or any(not isinstance(window, dict) for window in windows):
            raise ValueError(f"Node {node_id} has invalid blackout windows")
        for window in windows:
            try:
                start = date.fromisoformat(window["start"])
                end = date.fromisoformat(window["end"])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Node {node_id} has an invalid blackout window") from exc
            if start > end:
                raise ValueError(f"Node {node_id} has an invalid blackout window")
        calendar_windows = tuple(windows)

    return NodeConfig(
        node_id=node_id,
        display=str(node.get("display", node_id)),
        port=port,
        level=str(node.get("level", "L0")),
        schema_version=str(node.get("schema_version", "")),
        defaults=defaults,
        datapoints=datapoints,
        experts=tuple(experts),
        calendar_windows=calendar_windows,
        index_path=node_dir / "index.db",
        grants_path=_STATE_ROOT / node_id / "grants.db",
        audit_path=_STATE_ROOT / node_id / "audit.jsonl",
    )


def health_payload(config: NodeConfig) -> dict[str, str]:
    return {
        "node_id": config.node_id,
        "display": config.display,
        "status": "healthy",
        "schema_version": config.schema_version,
    }


def capabilities_payload(config: NodeConfig, caller: Any) -> dict[str, Any]:
    access = authorize_caller(config, caller)
    if access.code == "BLOCKED_BY_POLICY":
        return {
            "node_id": config.node_id,
            "decision": access.code,
            "rule_id": access.rule_id,
            "datapoints": [],
        }

    return {
        "node_id": config.node_id,
        "display": config.display,
        "schema_version": config.schema_version,
        "decision": access.code,
        "datapoints": [
            {
                "datapoint_id": datapoint_id,
                "title": datapoint["title"],
                "sensitivity": datapoint["sensitivity"],
                "exposure_ceiling": datapoint["ceiling"],
                "approval_upgrade": datapoint.get("upgrade_with_approval"),
            }
            for datapoint_id, datapoint in sorted(config.datapoints.items())
        ],
    }


def _fts_query(query: str) -> str:
    tokens = re.findall(r"[\w-]+", query, flags=re.UNICODE)[:24]
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)


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

    connection = sqlite3.connect(f"file:{config.index_path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """SELECT text, title, doc_id, dp, mode, sens, version, stale,
                      bm25(idx) AS rank
               FROM idx WHERE idx MATCH ? ORDER BY rank LIMIT 30""",
            (normalized_query,),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        connection.close()

    results: list[dict[str, Any]] = []
    withheld: list[dict[str, Any]] = []
    trace_id = trace_id or str(uuid.uuid4())
    for row in rows:
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

    return {
        "node_id": config.node_id,
        "results": results,
        "withheld": withheld,
        "status": "ok",
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
            "citation": f"{config.display} · {datapoint_id} · {metadata.get('id', document_id)}",
            "stale": int(str(metadata.get("version", "2026"))[:4]) < 2021,
            "summary": metadata.get("approved_summary"),
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


def find_experts_node(
    config: NodeConfig,
    caller: Any,
    query: str,
    purpose: str,
    store: AccessStore,
    *,
    trace_id: str | None = None,
) -> dict[str, Any]:
    caller_decision = authorize_caller(config, caller)
    if caller_decision.code == "BLOCKED_BY_POLICY":
        return {"node_id": config.node_id, "decision": caller_decision.code, "experts": []}

    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()[:500]))
    matches: list[tuple[int, Mapping[str, Any]]] = []
    for expert in config.experts:
        if expert.get("consent") is not True:
            continue
        searchable = " ".join([str(expert.get("role", "")), *expert.get("skills", [])]).lower()
        expert_tokens = set(re.findall(r"[a-z0-9]+", searchable))
        score = len(query_tokens.intersection(expert_tokens))
        if score:
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


def create_server(
    config: NodeConfig,
    *,
    token_verifier: TokenVerifier,
    auth_settings: AuthSettings,
    access_store: AccessStore,
    host: str = "127.0.0.1",
    port: int | None = None,
) -> FastMCP:
    """Create one MCP server instance bound to a single subsidiary config."""
    server = FastMCP(
        name=f"{config.display} Mesh Node",
        instructions=(
            f"Expose approved capability metadata for {config.display}. "
            "All access decisions belong to this subsidiary node."
        ),
        host=host,
        port=port or config.port,
        stateless_http=True,
        token_verifier=token_verifier,
        auth=auth_settings,
    )

    @server.tool()
    def health() -> dict[str, str]:
        """Return this node's identity and health status."""
        return health_payload(config)

    @server.tool()
    def describe_capabilities(purpose: str) -> dict[str, Any]:
        """List this node's policy-approved datapoint metadata and exposure ceilings."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return capabilities_payload(config, caller)

    @server.tool()
    def search(
        query: str,
        purpose: str,
        mode: str | None = None,
        as_of: str | None = None,
    ) -> dict[str, Any]:
        """Search this subsidiary's local approved index and return cited policy-allowed results."""
        caller = caller_context_from_token(get_access_token(), purpose)
        try:
            requested_date = date.fromisoformat(as_of) if as_of else None
        except ValueError:
            return {"node_id": config.node_id, "results": [], "withheld": [], "status": "invalid_as_of"}
        return search_node(
            config,
            caller,
            query,
            purpose,
            mode=mode,
            as_of=requested_date,
            access_store=access_store,
        )

    @server.tool()
    def summarize(document_id: str, purpose: str) -> dict[str, Any]:
        """Return only this node's approved summary for one document, with a citation."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return summarize_node(config, caller, document_id, purpose, access_store)

    @server.tool()
    def find_experts(query: str, purpose: str) -> dict[str, Any]:
        """Find opted-in experts by role and skills; names require a separate approved introduction."""
        caller = caller_context_from_token(get_access_token(), purpose)
        return find_experts_node(config, caller, query, purpose, access_store)

    @server.tool()
    def request_access(
        datapoint_id: str,
        mode: str,
        purpose: str,
        justification: str,
        kind: str = "content",
        expert_id: str | None = None,
    ) -> dict[str, Any]:
        """Request content access or a consent-based expert introduction."""
        caller = caller_context_from_token(get_access_token(), purpose)
        if kind == "intro":
            if datapoint_id != "F-04" or mode != "INTRO" or not expert_id:
                return {"status": "invalid_request", "reason": "Intro requests require F-04, INTRO mode, and expert_id"}
            return request_intro_node(
                config,
                access_store,
                caller,
                expert_id,
                purpose,
                justification,
            )
        if kind != "content" or expert_id is not None:
            return {"status": "invalid_request", "reason": "Invalid content access request fields"}
        return request_access_node(
            config,
            access_store,
            caller,
            datapoint_id,
            mode,
            purpose,
            justification,
        )

    return server


def serve_node(node_id: str) -> None:
    """Run one subsidiary server over Streamable HTTP."""
    config = load_node_config(node_id)
    host = os.getenv("NEURALMESH_MCP_HOST", "127.0.0.1")
    port = int(os.getenv(f"NEURALMESH_{node_id.upper()}_PORT", config.port))
    token_verifier, auth_settings = load_auth_config(node_id, port)
    access_store = AccessStore(config.grants_path, config.audit_path, config)
    create_server(
        config,
        token_verifier=token_verifier,
        auth_settings=auth_settings,
        access_store=access_store,
        host=host,
        port=port,
    ).run(transport="streamable-http")