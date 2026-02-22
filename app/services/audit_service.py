"""Audit log helpers."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import AuditLog, User


def log_action(
    db: Session,
    *,
    actor: User | None,
    action_type: str,
    order_id: int | None = None,
    before_snapshot: dict[str, Any] | None = None,
    after_snapshot: dict[str, Any] | None = None,
) -> None:
    actor_identifier = "anonymous"
    actor_id = None
    if actor is not None:
        actor_id = actor.id
        actor_identifier = actor.email or actor.username

    db.add(
        AuditLog(
            actor_user_id=actor_id,
            actor_identifier=actor_identifier,
            action_type=action_type,
            order_id=order_id,
            before_snapshot=before_snapshot,
            after_snapshot=after_snapshot,
        )
    )
