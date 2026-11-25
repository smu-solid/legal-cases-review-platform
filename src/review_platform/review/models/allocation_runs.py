"""Allocation-run ORM models: runs, their subjects/reviewers, and planned assignments."""

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
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from review_platform.db.models import SCHEMA, Base, TimestampMixin, utcnow


class AllocationRun(Base, TimestampMixin):
    __tablename__ = "allocation_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            [f"{SCHEMA}.campaigns.tenant_id", f"{SCHEMA}.campaigns.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "reviewer_pool_id"],
            [f"{SCHEMA}.reviewer_pools.tenant_id", f"{SCHEMA}.reviewer_pools.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint("tenant_id", "campaign_id", "run_key", name="uq_allocation_run_key"),
        UniqueConstraint("tenant_id", "id", name="uq_allocation_run_tenant_id"),
        CheckConstraint(
            "status IN ('previewed','planned','published','discarded','superseded')",
            name="ck_allocation_run_status",
        ),
        CheckConstraint(
            "feasibility_status IN ('feasible','feasible_with_warnings','infeasible',"
            "'blocked_by_snapshot_drift','blocked_by_reviewer_pool',"
            "'blocked_by_capacity','blocked_by_immutable_work')",
            name="ck_allocation_feasibility_status",
        ),
        CheckConstraint(
            "allocation_mode IN ('initial','incremental')",
            name="ck_allocation_run_mode",
        ),
        Index("ix_allocation_run_campaign_status", "tenant_id", "campaign_id", "status"),
        Index("ix_allocation_runs_tenant_snapshot", "tenant_id", "source_snapshot_id"),
        ForeignKeyConstraint(
            ["tenant_id", "source_snapshot_id"],
            ["review_platform.source_snapshots.tenant_id", "review_platform.source_snapshots.id"],
            name="allocation_runs_tenant_id_source_snapshot_id_fkey",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reviewer_pool_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    run_key: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), default="previewed")
    allocation_policy_version: Mapped[str] = mapped_column(String(80))
    planner_version: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(80), default="allocation-run/v1")
    source_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    source_snapshot_digest: Mapped[str] = mapped_column(String(64))
    pool_digest: Mapped[str] = mapped_column(String(64))
    random_seed: Mapped[str] = mapped_column(String(200))
    input_parameters_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    metric_weights_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    feasibility_status: Mapped[str] = mapped_column(String(40))
    feasibility_report_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    # Incremental allocation (reviewer-pool change handling). ``initial`` runs leave these unset.
    allocation_mode: Mapped[str] = mapped_column(String(20), default="initial")
    base_allocation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA}.allocation_runs.id", ondelete="RESTRICT"),
    )
    previous_pool_digest: Mapped[str | None] = mapped_column(String(64))
    movement_policy_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AllocationRunSubject(Base):
    __tablename__ = "allocation_run_subjects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "allocation_run_id"],
            [f"{SCHEMA}.allocation_runs.tenant_id", f"{SCHEMA}.allocation_runs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "review_subject_id"],
            [f"{SCHEMA}.review_subjects.tenant_id", f"{SCHEMA}.review_subjects.id"],
            ondelete="RESTRICT",
        ),
        UniqueConstraint(
            "tenant_id", "allocation_run_id", "review_subject_id", name="uq_run_subject"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_run_subject_tenant_id"),
        CheckConstraint(
            "selection_layer IN ('global_hub','pairwise','rolling','unique')",
            name="ck_run_subject_layer",
        ),
        Index(
            "ix_run_subject_layer",
            "tenant_id",
            "allocation_run_id",
            "selection_layer",
            "id",
        ),
        Index("ix_allocation_run_subjects_tenant_subject", "tenant_id", "review_subject_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    allocation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    selection_layer: Mapped[str] = mapped_column(String(20))
    overlap_group_key: Mapped[str | None] = mapped_column(String(120))
    window_index: Mapped[int | None] = mapped_column(Integer)
    metrics_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AllocationRunReviewer(Base):
    __tablename__ = "allocation_run_reviewers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "allocation_run_id"],
            [f"{SCHEMA}.allocation_runs.tenant_id", f"{SCHEMA}.allocation_runs.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "allocation_run_id", "reviewer_id", name="uq_run_reviewer"),
        UniqueConstraint("tenant_id", "id", name="uq_run_reviewer_tenant_id"),
        Index("ix_run_reviewer_reviewer", "tenant_id", "reviewer_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    allocation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    planned_assignment_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_assignment_count: Mapped[int] = mapped_column(Integer, default=0)
    pairwise_overlap_count: Mapped[int] = mapped_column(Integer, default=0)
    global_overlap_count: Mapped[int] = mapped_column(Integer, default=0)
    workload_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AssignmentPlan(Base):
    __tablename__ = "assignment_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "allocation_run_id"],
            [f"{SCHEMA}.allocation_runs.tenant_id", f"{SCHEMA}.allocation_runs.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "review_unit_id"],
            [f"{SCHEMA}.review_units.tenant_id", f"{SCHEMA}.review_units.id"],
            ondelete="RESTRICT",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [f"{SCHEMA}.assignments.tenant_id", f"{SCHEMA}.assignments.id"],
            ondelete="SET NULL",
        ),
        UniqueConstraint(
            "tenant_id",
            "allocation_run_id",
            "review_unit_id",
            "reviewer_id",
            name="uq_assignment_plan_reviewer_unit",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_assignment_plan_tenant_id"),
        CheckConstraint(
            "status IN ('planned','published','cancelled')", name="ck_assignment_plan_status"
        ),
        CheckConstraint(
            "selection_layer IN ('global_hub','pairwise','rolling','unique')",
            name="ck_assignment_plan_layer",
        ),
        Index("ix_assignment_plan_reviewer", "tenant_id", "reviewer_id", "status"),
        Index("ix_assignment_plan_run_status", "tenant_id", "allocation_run_id", "status"),
        Index("ix_assignment_plan_assignment", "tenant_id", "assignment_id"),
        Index("ix_assignment_plans_tenant_unit", "tenant_id", "review_unit_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    allocation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="planned")
    selection_layer: Mapped[str] = mapped_column(String(20))
    overlap_group_key: Mapped[str | None] = mapped_column(String(120))
    window_index: Mapped[int | None] = mapped_column(Integer)
    plan_metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class IncrementalMovementPlan(Base):
    """Per-assignment movement audit record for incremental allocation runs."""

    __tablename__ = "incremental_movement_plans"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "allocation_run_id"],
            [f"{SCHEMA}.allocation_runs.tenant_id", f"{SCHEMA}.allocation_runs.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_movement_plan_tenant_id"),
        CheckConstraint(
            "movement_kind IN ('new','moved','preserved','skipped')",
            name="ck_movement_kind",
        ),
        Index("ix_movement_plan_run", "tenant_id", "allocation_run_id", "movement_kind"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    allocation_run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    from_reviewer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    to_reviewer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    movement_kind: Mapped[str] = mapped_column(String(20))
    movement_reason: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
