"""Help chat about the NeuralMesh application (the chat icon at the bottom right of every page)."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.auth import require_user
from services import help_chat
from shared.config import get_settings

router = APIRouter()


class HelpTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)


class HelpChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    history: list[HelpTurn] = Field(default_factory=list, max_length=20)
    page: str | None = Field(default=None, max_length=200)


class HelpSource(BaseModel):
    source: str
    title: str
    section: str


class HelpChatResponse(BaseModel):
    answer: str
    sources: list[HelpSource]
    mode: Literal["model", "passages"]


@router.post("/chat", response_model=HelpChatResponse)
async def help_chat_endpoint(request: HelpChatRequest, user: dict = Depends(require_user)) -> HelpChatResponse:
    result = await asyncio.to_thread(
        help_chat.answer,
        request.question,
        [turn.model_dump() for turn in request.history],
        request.page,
        None,
        get_settings().app_env,
    )
    return HelpChatResponse(**result)
