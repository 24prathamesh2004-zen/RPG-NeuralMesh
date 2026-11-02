"""Local subsidiary-owner CLI for reviewing MCP access requests."""
from __future__ import annotations

import argparse
import json
import uuid
from datetime import datetime, timezone

from mcp_nodes.access_store import AccessStore, verify_audit
from mcp_nodes.server import NODE_IDS, load_node_config


def _store(node_id: str) -> AccessStore:
    config = load_node_config(node_id)
    return AccessStore(config.grants_path, config.audit_path, config)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", required=True, choices=NODE_IDS)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="List pending access requests")

    for action in ("approve", "deny"):
        command = commands.add_parser(action)
        command.add_argument("request_id")
        command.add_argument("--approver", required=True)
        if action == "approve":
            command.add_argument("--hours", type=int, default=24)

    revoke = commands.add_parser("revoke", help="Revoke an active grant")
    revoke.add_argument("grant_id")
    revoke.add_argument("--approver", required=True)
    commands.add_parser("verify-audit", help="Verify the local audit hash chain")

    args = parser.parse_args()
    config = load_node_config(args.node)
    store = AccessStore(config.grants_path, config.audit_path, config)

    if args.command == "list":
        result = store.pending()
    elif args.command in ("approve", "deny"):
        result = store.review(
            args.request_id,
            args.approver,
            args.command,
            hours=getattr(args, "hours", 24),
        )
        _append_audit_result(store, result)
    elif args.command == "revoke":
        result = store.revoke(args.grant_id, args.approver)
        _append_audit_result(store, result)
    else:
        result = {"valid": verify_audit(config.audit_path)}

    print(json.dumps(result, indent=2, default=str))


def _append_audit_result(store: AccessStore, result: dict) -> None:
    event = result.pop("audit_event", None)
    if event:
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        event["trace_id"] = str(uuid.uuid4())
        store.append_event(event)


if __name__ == "__main__":
    main()