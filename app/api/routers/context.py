"""Context API for SkillForge: the six context tools and the talent pack import, under /api/v1/context.

The caller is SkillForge's service identity (role context_client). Each request names the end user
(an opaque user ID, the company and the roles) and the purpose, so every node applies its policy to the real
user. No level, CV or name is accepted or returned.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel, Field, field_validator

from api.auth import API_AUDIENCE, POC_ISSUER
from services import context_api
from services.context.pii import strip_contact_details
from services.mesh_runtime import runtime
from shared.config import get_settings
from shared.registry import node_ids

router = APIRouter()
_bearer = HTTPBearer(auto_error=True)
CONTEXT_CLIENT_ROLE = "context_client"
TALENT_EXPORTER_ROLE = "talent_exporter"
ContextPurpose = Literal["problem_solving", "learning", "career_mobility"]
Level = Literal["L", "M", "A"]


def require_context_client(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    try:
        claims = jwt.decode(creds.credentials, get_settings().app_secret_key, algorithms=["HS256"], issuer=POC_ISSUER,
                            audience=API_AUDIENCE, options={"require_exp": True, "require_sub": True})
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired service token") from exc
    if CONTEXT_CLIENT_ROLE not in claims.get("roles", []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "This route is for the context client service identity")
    return claims


class EndUserIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    company: str
    roles: list[str] = Field(default_factory=lambda: ["group_user"], min_length=1)

    @field_validator("company")
    @classmethod
    def registered(cls, value: str) -> str:
        if value not in node_ids():
            raise ValueError("The company has no registered Mesh Node")
        return value

    def end_user(self) -> context_api.EndUser:
        return context_api.EndUser(self.user_id, self.company, tuple(self.roles))


class RoleContextIn(BaseModel):
    role_id: str | None = None
    title: str | None = None
    company: str | None = None


class SkillContextIn(BaseModel):
    user: EndUserIn
    skill: str
    level: Level | None = None
    purpose: ContextPurpose = "learning"


class AskIn(BaseModel):
    user: EndUserIn
    question: str = Field(min_length=3, max_length=2000)
    purpose: ContextPurpose = "learning"


class LearningIn(BaseModel):
    user: EndUserIn
    skill: str
    target_level: Level


class MentorsIn(BaseModel):
    skill: str


class TalentImportIn(BaseModel):
    packs: list[dict] = Field(min_length=1, max_length=20)


@router.post("/role_context")
async def role_context(body: RoleContextIn, client: dict = Depends(require_context_client)) -> dict:
    try:
        return context_api.role_context(runtime(), body.role_id, body.title, body.company)
    except context_api.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown role {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/skill_context")
async def skill_context(body: SkillContextIn, client: dict = Depends(require_context_client)) -> dict:
    try:
        return await context_api.skill_context(runtime(), body.user.end_user(), body.skill, body.level, body.purpose)
    except context_api.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown skill {exc}") from exc


@router.post("/ask")
async def ask(body: AskIn, client: dict = Depends(require_context_client)) -> dict:
    from api.routers.mesh import run_query  # the router's compiled flow, shared with /mesh/query

    question, removed = strip_contact_details(body.question)
    user = body.user.end_user()
    result = await run_query(question=question, purpose=body.purpose, nodes=None, mode=None, as_of=None,
                             user_assertion=user.assertion(), company=user.company, roles=list(user.roles))
    result["contact_details_removed"] = removed
    return {"schema_version": "1.0", **result}


@router.post("/learning_sources")
async def learning_sources(body: LearningIn, client: dict = Depends(require_context_client)) -> dict:
    try:
        return await context_api.learning_sources(runtime(), body.user.end_user(), body.skill, body.target_level)
    except context_api.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown skill {exc}") from exc


@router.post("/find_mentors")
async def find_mentors(body: MentorsIn, client: dict = Depends(require_context_client)) -> dict:
    try:
        return context_api.find_mentors(runtime(), body.skill)
    except context_api.NotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown skill {exc}") from exc


@router.get("/vocabulary_export")
async def vocabulary_export(client: dict = Depends(require_context_client)) -> dict:
    return context_api.vocabulary_export(runtime())


@router.post("/talent-packs")
async def import_talent_packs(body: TalentImportIn, client: dict = Depends(require_context_client)) -> dict:
    if TALENT_EXPORTER_ROLE not in client.get("roles", []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the talent exporter identity may import talent packs")
    try:
        result = context_api.import_talent_packs(runtime(), body.packs)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if not result["accepted"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, result)
    return result
