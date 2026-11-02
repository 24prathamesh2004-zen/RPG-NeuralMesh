"""Local shared-secret identity for the synthetic-data POC."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from shared.config import get_settings

POC_ISSUER = "http://rpg-neuralmesh-poc.local"
API_AUDIENCE = "neuralmesh-api"
POC_TOKEN_ALGORITHM = "HS256"
_bearer = HTTPBearer(auto_error=True)


def issue_poc_token(claims: dict, *, audience: str = API_AUDIENCE, hours: int = 12) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        **claims,
        "iss": POC_ISSUER,
        "aud": audience,
        "iat": now,
        "exp": now + timedelta(hours=hours),
    }
    return jwt.encode(payload, get_settings().app_secret_key, algorithm=POC_TOKEN_ALGORITHM)


async def require_user(
    creds: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    """Verify a local POC bearer token and return its user claims."""
    try:
        return jwt.decode(
            creds.credentials,
            get_settings().app_secret_key,
            algorithms=[POC_TOKEN_ALGORITHM],
            issuer=POC_ISSUER,
            audience=API_AUDIENCE,
            options={"require_exp": True, "require_sub": True},
        )
    except JWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired session") from exc
