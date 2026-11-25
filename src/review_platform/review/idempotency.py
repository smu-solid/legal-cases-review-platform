"""Shared idempotency and tenant-scope helpers for review-owned services.

Both the review workflow service and the allocation service persist idempotency records against the
same review-owned table and set the transaction-local tenant used by fail-closed PostgreSQL RLS
policies. This mixin owns that shared behavior so the two service bases stay in step.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models import IdempotencyRecord


class IdempotencyMixin:
    """Advisory-locked idempotency lookup/store and tenant-scope configuration."""

    @staticmethod
    def _key_digest(key: str) -> str:
        return hashlib.sha256(key.encode()).hexdigest()

    @staticmethod
    def _set_tenant_scope(session: Session, tenant_id: uuid.UUID) -> None:
        """Set the transaction-local tenant used by fail-closed PostgreSQL RLS policies."""

        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )

    def _idempotent_response(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        operation: str,
        key: str,
        request_digest: str,
    ) -> IdempotencyRecord | None:
        scope = f"{tenant_id}:{user_id}:{operation}:{self._key_digest(key)}"
        lock_id = int.from_bytes(hashlib.sha256(scope.encode()).digest()[:8], signed=True)
        session.execute(
            text("SELECT pg_advisory_xact_lock(:lock_id)"),
            {"lock_id": lock_id},
        )
        record = session.scalar(
            select(IdempotencyRecord).where(
                IdempotencyRecord.tenant_id == tenant_id,
                IdempotencyRecord.user_id == user_id,
                IdempotencyRecord.operation == operation,
                IdempotencyRecord.key_digest == self._key_digest(key),
            )
        )
        if record is not None and record.request_digest != request_digest:
            raise APIError(
                409,
                "idempotency_conflict",
                "Idempotency conflict",
                "The idempotency key was already used with a different request.",
            )
        return record

    def _store_idempotency(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        operation: str,
        key: str,
        request_digest: str,
        response: dict[str, Any],
        etag: str | None = None,
    ) -> None:
        session.add(
            IdempotencyRecord(
                tenant_id=tenant_id,
                user_id=user_id,
                operation=operation,
                key_digest=self._key_digest(key),
                request_digest=request_digest,
                response_json=response,
                response_etag=etag,
            )
        )
