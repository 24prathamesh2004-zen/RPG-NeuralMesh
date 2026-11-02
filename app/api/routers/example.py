"""Example session router — start / resume / fetch an agent session.

Runs the LangGraph turn inline and persists state to Redis, so the app works
end-to-end without a Temporal worker. To make runs durable, swap the inline
``compiled_graph.ainvoke`` for a Temporal workflow start (see the commented
block) and let workers/worker.py execute the turn.
"""
from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis

from agents.graph import compiled_graph
from api.dependencies import get_redis
from api.schemas.input import ResumeRequest, StartRequest
from api.schemas.output import SessionResponse
from shared.logger import get_logger

router = APIRouter()
log = get_logger("api.example")

_SESSION_TTL = 86_400 * 30  # 30 days


async def _load(redis: Redis, session_id: str) -> dict:
    raw = await redis.get(f"session:{session_id}")
    if not raw:
        raise HTTPException(404, f"session {session_id} not found")
    return json.loads(raw)


async def _save(redis: Redis, session_id: str, state: dict) -> None:
    await redis.setex(f"session:{session_id}", _SESSION_TTL, json.dumps(state))


@router.post("/start", response_model=SessionResponse)
async def start(req: StartRequest, redis: Redis = Depends(get_redis)) -> SessionResponse:
    session_id = f"S-{uuid.uuid4().hex[:8].upper()}"
    state: dict = {
        "session_id": session_id,
        "messages": [{"role": "user", "content": req.message}] if req.message else [],
        "collected": req.context or {},
        "current_step": "start",
        "step_status": "in_progress",
        "turn_count": 0,
    }

    # ── Durable alternative (Temporal) ──────────────────────────────────────────
    # from temporalio.client import Client
    # from workflows.example_workflow import ExampleWorkflow
    # from shared.config import get_settings
    # s = get_settings()
    # client = await Client.connect(s.temporal_host, namespace=s.temporal_namespace)
    # state = await client.execute_workflow(
    #     ExampleWorkflow.run, state,
    #     id=f"example-{session_id}", task_queue=s.temporal_task_queue_agents,
    # )
    state = dict(await compiled_graph.ainvoke(state))

    await _save(redis, session_id, state)
    return SessionResponse.from_state(state)


@router.post("/resume", response_model=SessionResponse)
async def resume(req: ResumeRequest, redis: Redis = Depends(get_redis)) -> SessionResponse:
    state = await _load(redis, req.session_id)
    state.setdefault("messages", []).append({"role": "user", "content": req.message})
    state["step_status"] = "in_progress"
    state["turn_count"] = 0
    state = dict(await compiled_graph.ainvoke(state))
    await _save(redis, req.session_id, state)
    return SessionResponse.from_state(state)


@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str, redis: Redis = Depends(get_redis)) -> SessionResponse:
    return SessionResponse.from_state(await _load(redis, session_id))
