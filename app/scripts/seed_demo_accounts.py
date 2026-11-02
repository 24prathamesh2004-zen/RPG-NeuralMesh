"""Seed reserved synthetic demo accounts and approval activity for presentations."""
from __future__ import annotations

import json

from api.account_store import AccountStore
from mcp_nodes.access_store import AccessStore
from mcp_nodes.auth import CallerContext
from mcp_nodes.server import load_node_config, request_access_node, request_intro_node
from shared.config import get_settings

DEMO_PASSWORD = "MeshPilot!2026"
DEMO_USERS = [
    {
        "email": "presenter@neuralmesh.local",
        "display_name": "NeuralMesh Presenter",
        "company": "zensar",
    },
    {
        "email": "ceat.expert@neuralmesh.local",
        "display_name": "Aarav Materials Expert",
        "company": "ceat",
        "expert_title": "Raw-material quality lead",
        "expert_skills": ["natural rubber", "lot acceptance", "supplier quality"],
    },
    {
        "email": "kec.expert@neuralmesh.local",
        "display_name": "Mira Integration Expert",
        "company": "kec",
        "expert_title": "International integration programme director",
        "expert_skills": ["cross-border integration", "mobilisation", "labour"],
    },
    {
        "email": "zensar.expert@neuralmesh.local",
        "display_name": "Dev AI Delivery Expert",
        "company": "zensar",
        "expert_title": "AI delivery excellence lead",
        "expert_skills": ["AI-assisted delivery", "testing", "integration playbooks"],
    },
    {
        "email": "harrisons.expert@neuralmesh.local",
        "display_name": "Anika Estate Operations Expert",
        "company": "harrisons",
        "expert_title": "Estate operations manager",
        "expert_skills": ["latex handling", "collection logistics", "monsoon operations"],
    },
]


def main() -> None:
    if get_settings().app_env != "development":
        raise RuntimeError("Refusing to seed presentation accounts outside APP_ENV=development")

    store = AccountStore()
    users = {
        item["email"]: store.seed_demo_user(password=DEMO_PASSWORD, **item)
        for item in DEMO_USERS
    }
    presenter = users["presenter@neuralmesh.local"]
    caller = CallerContext(
        subject=presenter["user_id"],
        company=presenter["company"],
        roles=frozenset(presenter["roles"]),
        purpose="problem_solving",
    )

    kec_config = load_node_config("kec")
    kec_store = AccessStore(kec_config.grants_path, kec_config.audit_path, kec_config)
    pending = next((
        item for item in kec_store.pending()
        if item["requester_sub"] == caller.subject
        and item["datapoint_id"] == "L-02a"
        and item["kind"] == "content"
    ), None)
    if pending is None:
        pending = request_access_node(
            kec_config,
            kec_store,
            caller,
            "L-02a",
            "RAG",
            "problem_solving",
            "Prepare a cross-subsidiary integration lessons presentation for the pilot council.",
            trace_id="demo-seed-kec-approval",
        )

    ceat_config = load_node_config("ceat")
    ceat_store = AccessStore(ceat_config.grants_path, ceat_config.audit_path, ceat_config)
    intro = next((
        item for item in ceat_store.pending()
        if item["requester_sub"] == caller.subject
        and item["kind"] == "intro"
        and item["target_id"] == "CE-1"
    ), None)
    if intro is None:
        intro = request_intro_node(
            ceat_config,
            ceat_store,
            caller,
            "CE-1",
            "problem_solving",
            "Discuss synthetic natural-rubber quality learnings for a pilot presentation.",
            trace_id="demo-seed-ceat-intro",
        )

    print(json.dumps({
        "seeded_accounts": [
            {
                "email": user["email"],
                "password": DEMO_PASSWORD,
                "company": user["company_name"],
                "expert_opt_in": user["expert_profile"] is not None,
            }
            for user in users.values()
        ],
        "demo_requests": {
            "kec_access": {"request_id": pending.get("request_id"), "status": pending.get("status", "pending")},
            "ceat_expert_intro": {"request_id": intro.get("request_id"), "status": intro.get("status", "pending")},
        },
        "note": "Synthetic local POC accounts only. Run this script again to reset their shared demo password. Pending requests are seeded once.",
    }, indent=2))


if __name__ == "__main__":
    main()