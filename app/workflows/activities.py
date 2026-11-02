"""Temporal activities — the side-effecting steps a workflow orchestrates.

Activities run in the worker process (workers/worker.py). Keep them
idempotent where possible; Temporal may retry them. The LangGraph turn runs
inside ``run_agent_turn`` so every turn is traced and durable.
"""
from __future__ import annotations

import json
from typing import Any

from temporalio import activity

from agents.graph import compiled_graph
from api.dependencies import get_redis_direct
from shared.logger import get_logger

log = get_logger("workflows.activities")

_SESSION_TTL_SECONDS = 86_400 * 30  # 30 days


@activity.defn
async def run_agent_turn(state: dict[str, Any]) -> dict[str, Any]:
    """Execute one turn of the LangGraph supervisor loop and return new state."""
    result = await compiled_graph.ainvoke(state)
    return dict(result)


@activity.defn
async def persist_session_to_redis(session_id: str, state: dict[str, Any]) -> None:
    redis = await get_redis_direct()
    try:
        await redis.setex(f"session:{session_id}", _SESSION_TTL_SECONDS, json.dumps(state))
    finally:
        await redis.aclose()


@activity.defn
async def persist_session_to_db(session_id: str, state: dict[str, Any]) -> None:
    """Upsert the session row. Wire this to db.models.Session for durability."""
    # from sqlalchemy.dialects.postgresql import insert
    # from db.base import get_db_session
    # from db.models import Session
    # async with get_db_session() as db: ...
    log.info("persist_session_to_db", session_id=session_id, step=state.get("current_step"))


@activity.defn
async def send_status_notification(session_id: str, status: str) -> None:
    """Notify the customer of a status change (email/SMS). Stubbed by default."""
    log.info("send_status_notification", session_id=session_id, status=status)
