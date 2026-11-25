"""Private adjudicator decision targets referencing immutable reviewer proposals."""

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from review_platform.db.models import SCHEMA, Base, utcnow


class ProposalAdjudicationItem(Base):
    __tablename__ = "proposal_adjudication_items"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            [f"{SCHEMA}.campaigns.tenant_id", f"{SCHEMA}.campaigns.id"],
        ),
        ForeignKeyConstraint(
            ["tenant_id", "extracted_adjudication_id"],
            [f"{SCHEMA}.adjudications.tenant_id", f"{SCHEMA}.adjudications.id"],
        ),
        CheckConstraint(
            "state IN ('pending','submitted','superseded')", name="ck_proposal_adjudication_state"
        ),
        Index(
            "ix_proposal_adjudicator_case", "tenant_id", "campaign_id", "case_id", "adjudicator_id"
        ),
        Index(
            "uq_proposal_extracted_target",
            "tenant_id",
            "adjudicator_id",
            "extracted_adjudication_id",
            unique=True,
            postgresql_where=text("((state)::text <> 'superseded'::text)"),
        ),
        {"schema": SCHEMA},
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    case_id: Mapped[str] = mapped_column(String(240))
    group_id: Mapped[str] = mapped_column(String(60))
    adjudicator_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id"))
    extracted_adjudication_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    proposal_ids_json: Mapped[list[str]] = mapped_column(JSONB)
    origin: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20), default="pending")
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    draft_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    decision_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    final_value: Mapped[str | None] = mapped_column(String(10_000))
    final_provenance_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
