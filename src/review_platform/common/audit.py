"""Transactional append-only authentication and administration audit events."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from review_platform.db.models import AuditEvent

AUDIT_LOCK_ID = 1_914_220_241
GENESIS_HASH = "0" * 64


def append_audit_event(
    session: Session,
    *,
    actor_user_id: uuid.UUID | None,
    actor_type: str,
    event_type: str,
    object_type: str,
    object_id: str,
    request_id: str,
    payload: dict[str, Any],
    key: str,
) -> AuditEvent:
    """Serialize the hash chain and append within the caller's transaction."""

    session.execute(text("SELECT pg_advisory_xact_lock(:lock_id)"), {"lock_id": AUDIT_LOCK_ID})
    sequence = session.scalar(text("SELECT nextval('review_platform.audit_event_sequence')"))
    if sequence is None:
        raise RuntimeError("audit sequence allocation failed")
    previous = session.scalar(select(AuditEvent).order_by(AuditEvent.sequence.desc()).limit(1))
    prev_hash = previous.event_hash if previous is not None else GENESIS_HASH
    occurred_at = datetime.now(UTC)
    canonical = json.dumps(
        {
            "sequence": sequence,
            "actor_user_id": str(actor_user_id) if actor_user_id else None,
            "actor_type": actor_type,
            "event_type": event_type,
            "object_type": object_type,
            "object_id": object_id,
            "request_id": request_id,
            "occurred_at": occurred_at.isoformat(),
            "payload": payload,
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    event = AuditEvent(
        sequence=sequence,
        occurred_at=occurred_at,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        event_type=event_type,
        object_type=object_type,
        object_id=object_id,
        request_id=request_id,
        payload_json=payload,
        prev_hash=prev_hash,
        event_hash=hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest(),
    )
    session.add(event)
    session.flush()
    return event
