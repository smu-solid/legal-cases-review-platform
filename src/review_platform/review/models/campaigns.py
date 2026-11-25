"""Campaign-configuration ORM models: campaigns, reviewer pools, and campaign subjects."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from review_platform.db.models import SCHEMA, Base, TimestampMixin, utcnow


class Campaign(Base, TimestampMixin):
    __tablename__ = "campaigns"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_snapshot_id"],
            [f"{SCHEMA}.source_snapshots.tenant_id", f"{SCHEMA}.source_snapshots.id"],
        ),
        UniqueConstraint("tenant_id", "key", name="uq_campaign_tenant_key"),
        UniqueConstraint("tenant_id", "id", name="uq_campaign_tenant_id"),
        CheckConstraint(
            "status IN ('draft','planned','published','paused','closed','pool')",
            name="ck_campaign_status",
        ),
        Index(
            "ix_campaign_tenant_subject_kind",
            "tenant_id",
            "subject_kind",
            "review_kind",
            "status",
        ),
        Index("ix_campaigns_tenant_snapshot", "tenant_id", "source_snapshot_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE")
    )
    key: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="published")
    subject_kind: Mapped[str] = mapped_column(String(40), default="case")
    review_kind: Mapped[str] = mapped_column(String(60), default="metadata_field")
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    allocation_policy_version: Mapped[str | None] = mapped_column(String(80))
    policy_version: Mapped[str] = mapped_column(String(40), default="synthetic-v1")
    policy_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    review_scope_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    manifest_digest: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class ReviewerPool(Base, TimestampMixin):
    __tablename__ = "reviewer_pools"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            [f"{SCHEMA}.campaigns.tenant_id", f"{SCHEMA}.campaigns.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "campaign_id", "name", name="uq_reviewer_pool_name"),
        UniqueConstraint("tenant_id", "id", name="uq_reviewer_pool_tenant_id"),
        CheckConstraint("status IN ('draft','active','closed')", name="ck_reviewer_pool_status"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="draft")
    eligibility_policy_version: Mapped[str] = mapped_column(String(80))
    exclusions_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    pool_digest: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class ReviewerPoolMember(Base):
    __tablename__ = "reviewer_pool_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_pool_id"],
            [f"{SCHEMA}.reviewer_pools.tenant_id", f"{SCHEMA}.reviewer_pools.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "reviewer_pool_id", "reviewer_id", name="uq_reviewer_pool_member"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_reviewer_pool_member_tenant_id"),
        CheckConstraint(
            "eligibility_status IN ('eligible','excluded','inactive','unauthorized','conflicted')",
            name="ck_reviewer_pool_member_status",
        ),
        CheckConstraint("capacity_weight > 0", name="ck_reviewer_pool_member_capacity"),
        Index("ix_reviewer_pool_member_reviewer", "tenant_id", "reviewer_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reviewer_pool_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    eligibility_status: Mapped[str] = mapped_column(String(24), default="eligible")
    exclusion_reason: Mapped[str | None] = mapped_column(String(200))
    workload_limit: Mapped[int | None] = mapped_column(Integer)
    capacity_weight: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CampaignSubject(Base):
    __tablename__ = "campaign_subjects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            [f"{SCHEMA}.campaigns.tenant_id", f"{SCHEMA}.campaigns.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "review_subject_id"],
            [f"{SCHEMA}.review_subjects.tenant_id", f"{SCHEMA}.review_subjects.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "campaign_id", "review_subject_id", name="uq_campaign_subject"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_campaign_subject_tenant_id"),
        CheckConstraint(
            "eligibility_status IN ('eligible','excluded','blocked')",
            name="ck_campaign_subject_status",
        ),
        Index("ix_campaign_subject_rank", "tenant_id", "campaign_id", "selection_rank", "id"),
        Index("ix_campaign_subjects_tenant_subject", "tenant_id", "review_subject_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    subject_kind: Mapped[str] = mapped_column(String(40))
    review_kind: Mapped[str] = mapped_column(String(60))
    eligibility_status: Mapped[str] = mapped_column(String(20), default="eligible")
    eligibility_reason: Mapped[str | None] = mapped_column(String(300))
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    hub_score: Mapped[int | None] = mapped_column(Integer)
    selection_rank: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
