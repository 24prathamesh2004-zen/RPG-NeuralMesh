"""Bearer-token verification and caller context for MCP node requests."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from jose import JWTError, jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

from mcp_nodes.server_types import NodeAuthConfig
from shared.config import get_settings


@dataclass(frozen=True)
class CallerContext:
    subject: str
    company: str
    roles: frozenset[str]
    purpose: str


class JwtTokenVerifier(TokenVerifier):
    def __init__(self, key: str, issuer: str, audience: str, algorithm: str = "RS256") -> None:
        self.key = key
        self.issuer = issuer
        self.audience = audience
        self.algorithm = algorithm

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            claims = jwt.decode(
                token,
                self.key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                audience=self.audience,
                options={"require_exp": True, "require_sub": True},
            )
        except (JWTError, TypeError, ValueError):
            return None

        subject = claims.get("sub")
        company = claims.get("company")
        roles = claims.get("roles")
        if (
            not isinstance(subject, str)
            or not subject
            or not isinstance(company, str)
            or not company
            or not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role for role in roles)
            or not claims.get("iss")
            or not claims.get("aud")
        ):
            return None

        scope_claim = claims.get("scope", "")
        scopes = scope_claim.split() if isinstance(scope_claim, str) else scope_claim
        if not isinstance(scopes, list) or any(not isinstance(scope, str) for scope in scopes):
            return None

        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or claims.get("client_id") or subject),
            scopes=scopes,
            expires_at=int(claims["exp"]),
            resource=self.audience,
            subject=subject,
            claims=claims,
        )


def load_auth_config(node_id: str, port: int) -> tuple[JwtTokenVerifier, AuthSettings]:
    audience = os.getenv(
        f"NEURALMESH_{node_id.upper()}_AUDIENCE",
        f"http://127.0.0.1:{port}",
    )
    issuer = os.getenv("NEURALMESH_POC_JWT_ISSUER", "http://rpg-neuralmesh-poc.local")
    secret = os.getenv("NEURALMESH_POC_JWT_SECRET") or get_settings().app_secret_key
    verifier = JwtTokenVerifier(secret, issuer, audience, algorithm="HS256")
    settings = AuthSettings(
        issuer_url=issuer,
        resource_server_url=audience,
        validate_token_resource=False,
        required_scopes=["neuralmesh.query"],
    )
    return verifier, settings


def caller_context_from_token(token: AccessToken | None, purpose: str) -> CallerContext:
    if token is None:
        raise PermissionError("Authentication required")
    claims: dict[str, Any] = token.claims or {}
    subject = token.subject
    company = claims.get("company")
    roles = claims.get("roles")
    if (
        not subject
        or not isinstance(company, str)
        or not company
        or not isinstance(roles, list)
        or any(not isinstance(role, str) for role in roles)
        or not purpose
    ):
        raise PermissionError("Token does not contain a valid caller context")
    return CallerContext(subject, company, frozenset(roles), purpose)