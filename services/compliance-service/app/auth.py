from __future__ import annotations

from dataclasses import dataclass
from secrets import compare_digest
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import settings


@dataclass(frozen=True)
class Principal:
    actor_id: str
    role: str


bearer_scheme = HTTPBearer(auto_error=False)
ROLE_RANK = {"viewer": 1, "operator": 2, "admin": 3}


def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> Principal:
    if credentials is None:
        if settings.auth_required:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        return Principal(actor_id="local-demo-admin", role="admin")

    principal = principal_for_token(credentials.credentials)
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        )
    return principal


def require_role(minimum_role: str):
    def dependency(principal: Annotated[Principal, Depends(get_current_principal)]) -> Principal:
        if ROLE_RANK[principal.role] < ROLE_RANK[minimum_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"{minimum_role} role required",
            )
        return principal

    return dependency


def principal_for_token(token: str) -> Principal | None:
    token_roles = {
        settings.tradetwin_viewer_token: Principal("demo-viewer", "viewer"),
        settings.tradetwin_operator_token: Principal("demo-operator", "operator"),
        settings.tradetwin_admin_token: Principal("demo-admin", "admin"),
    }
    for configured_token, principal in token_roles.items():
        if configured_token and compare_digest(token, configured_token):
            return principal
    return None
