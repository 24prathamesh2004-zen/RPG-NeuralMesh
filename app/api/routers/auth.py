"""Sign-up and sign-in endpoints for the synthetic-data POC."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from api.account_store import AccountStore
from api.auth import issue_poc_token, require_user
from api.schemas.auth import AccountResponse, SignInRequest, SignUpRequest

router = APIRouter()
_store = AccountStore()
@router.post("/signup", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def signup(request: SignUpRequest) -> AccountResponse:
    try:
        user = _store.create_user(
            email=request.email,
            password=request.password,
            display_name=request.display_name,
            company=request.company,
            expert_opt_in=request.expert_opt_in,
            expert_title=request.expert_title,
            expert_skills=request.expert_skills,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        if "UNIQUE constraint failed" in str(exc):
            raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists") from exc
        raise
    claims = {"sub": user["user_id"], "email": user["email"], "company": user["company"], "roles": user["roles"]}
    return AccountResponse(access_token=issue_poc_token(claims), user=user)


@router.post("/signin", response_model=AccountResponse)
def signin(request: SignInRequest) -> AccountResponse:
    user = _store.authenticate(request.email, request.password)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Email or password is incorrect")
    claims = {"sub": user["user_id"], "email": user["email"], "company": user["company"], "roles": user["roles"]}
    return AccountResponse(access_token=issue_poc_token(claims), user=user)


@router.get("/me")
def me(user: dict = Depends(require_user)) -> dict:
    full_user = _store.get_user(user["sub"])
    if full_user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    return full_user