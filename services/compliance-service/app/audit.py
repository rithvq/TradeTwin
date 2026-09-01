from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.auth import Principal
from app.models import AuditLog

logger = logging.getLogger(__name__)


def write_audit_log(
    db: Session,
    principal: Principal,
    action: str,
    resource_type: str,
    resource_id: str | None,
    status: str = "SUCCESS",
    details: dict[str, Any] | None = None,
) -> None:
    try:
        db.add(
            AuditLog(
                actor_id=principal.actor_id,
                role=principal.role,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                status=status,
                details=details or {},
            )
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        logger.warning("Could not write audit log for %s: %s", action, exc)
