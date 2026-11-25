"""Review-owned proposals, scoped to an author and case, never extraction records."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from review_platform.db.models import SCHEMA, Base, utcnow


class ReviewerAddedProposal(Base):
    __tablename__ = "reviewer_added_proposals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            [f"{SCHEMA}.campaigns.tenant_id", f"{SCHEMA}.campaigns.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [f"{SCHEMA}.assignments.tenant_id", f"{SCHEMA}.assignments.id"],
            ondelete="CASCADE",
        ),
        CheckConstraint("state IN ('draft','submitted','removed')", name="ck_proposal_state"),
        CheckConstraint(
            "state != 'submitted' OR (length(btrim(value)) > 0 AND "
            "jsonb_array_length(provenance_json) > 0 AND submitted_at IS NOT NULL)",
            name="ck_proposal_submission",
        ),
        Index("ix_proposal_owner_case", "tenant_id", "campaign_id", "reviewer_id", "case_id"),
        Index("ix_proposal_assignment", "tenant_id", "assignment_id"),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    case_id: Mapped[str] = mapped_column(String(240))
    group_id: Mapped[str] = mapped_column(String(60))
    value_schema: Mapped[str] = mapped_column(String(60))
    original_value: Mapped[str] = mapped_column(String(10_000))
    value: Mapped[str] = mapped_column(String(10_000))
    note: Mapped[str] = mapped_column(String(10_000))
    provenance_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    revisions_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    state: Mapped[str] = mapped_column(String(20), default="draft")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
