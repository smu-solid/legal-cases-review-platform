"""Review-execution ORM models: assignments, annotation/answer revisions, adjudications.

Includes the cross-cutting :class:`IdempotencyRecord`, which stores the de-duplicated response
for each idempotent write across the review-execution surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from review_platform.db.models import SCHEMA, Base, TimestampMixin, utcnow


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_unit_id"],
            [f"{SCHEMA}.review_units.tenant_id", f"{SCHEMA}.review_units.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "review_unit_id", "reviewer_id", name="uq_assignment_reviewer"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_assignment_tenant_id"),
        CheckConstraint(
            "status IN ('claimed','submitted','released','revision_requested')",
            name="ck_assignment_status",
        ),
        Index("ix_assignment_reviewer", "tenant_id", "reviewer_id", "status"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    status: Mapped[str] = mapped_column(String(20), default="claimed")
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lease_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_requested_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    revision_reason: Mapped[str | None] = mapped_column(String(1_000))
    lock_version: Mapped[int] = mapped_column(Integer, default=1)


class AnnotationRevision(Base):
    __tablename__ = "annotation_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [f"{SCHEMA}.assignments.tenant_id", f"{SCHEMA}.assignments.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "assignment_id", "revision_no", name="uq_annotation_revision"
        ),
        UniqueConstraint(
            "tenant_id", "assignment_id", "client_request_id", name="uq_annotation_request"
        ),
        CheckConstraint("state IN ('draft','submitted')", name="ck_annotation_state"),
        CheckConstraint(
            "outcome IN ('candidate_a_preferred','candidate_b_preferred',"
            "'equivalent_supported','both_wrong','unsupported_or_not_locatable',"
            "'exceptional_skip')",
            name="ck_annotation_outcome",
        ),
        CheckConstraint(
            "(outcome NOT IN ('both_wrong','unsupported_or_not_locatable','exceptional_skip') "
            "AND corrected_value_json IS NULL AND corrected_value_display IS NULL) "
            "OR length(btrim(comment)) > 0",
            name="ck_annotation_comment_required",
        ),
        CheckConstraint(
            "jsonb_array_length(assessments_json) = 2",
            name="ck_annotation_two_assessments",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision_no: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(60))
    corrected_value_json: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))
    corrected_value_display: Mapped[str | None] = mapped_column(String(10_000))
    comment: Mapped[str | None] = mapped_column(Text)
    assessments_json: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB)
    client_request_id: Mapped[str] = mapped_column(String(128))
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewItemAnswer(Base):
    """Append-only value/provenance answer revisions for the grouped reviewer workspace.

    Distinct from :class:`AnnotationRevision` (candidate comparison): the reviewer records whether
    the extracted value and its provenance are correct. Tri-state correctness is stored as nullable
    booleans so a draft can be partial; a submitted revision must answer both (DB-enforced).
    """

    __tablename__ = "review_item_answers"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "assignment_id"],
            [f"{SCHEMA}.assignments.tenant_id", f"{SCHEMA}.assignments.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id", "assignment_id", "revision_no", name="uq_item_answer_revision"
        ),
        UniqueConstraint(
            "tenant_id", "assignment_id", "client_request_id", name="uq_item_answer_request"
        ),
        CheckConstraint("state IN ('draft','submitted')", name="ck_item_answer_state"),
        CheckConstraint(
            "state = 'draft' OR value_correct IS NOT NULL",
            name="ck_item_answer_value_answered",
        ),
        CheckConstraint(
            "state = 'draft' OR provenance_correct IS NOT NULL",
            name="ck_item_answer_provenance_answered",
        ),
        CheckConstraint(
            "failure_reason IS NULL OR length(btrim(failure_reason)) > 0",
            name="ck_item_answer_failure_reason",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    assignment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    revision_no: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20))
    value_correct: Mapped[bool | None] = mapped_column(Boolean)
    provenance_correct: Mapped[bool | None] = mapped_column(Boolean)
    corrected_value_json: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))
    corrected_value_display: Mapped[str | None] = mapped_column(String(10_000))
    comment: Mapped[str | None] = mapped_column(Text)
    failure_reason: Mapped[str | None] = mapped_column(String(80))
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB)
    corrected_provenance_spans_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    client_request_id: Mapped[str] = mapped_column(String(128))
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseSubmission(Base):
    """Distinct from every review unit's own ``Assignment.status == 'submitted'``: a case can
    have every one of its owned fields individually submitted while this row still does
    not exist -- campaign-level progress (``queue.py``'s
    ``case_queue``/``campaign_queue``) counts a case as complete only once the reviewer
    has explicitly confirmed from the case-submit preview, not merely because every
    field happens to be done. Append-only (no update/delete path is ever exposed) and
    unique per reviewer+case+campaign, so a resubmit attempt is a no-op replay, not a
    second row. ``case_id`` is the same ``snapshot_local_case_external_id`` used everywhere
    else for real case identity (``campaign_cases.py``, ``grouped_bundle.py``,
    ``queue.py``)."""

    __tablename__ = "case_submissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "campaign_id", "case_id", "reviewer_id", name="uq_case_submission"
        ),
        UniqueConstraint("tenant_id", "id", name="uq_case_submission_tenant_id"),
        Index("ix_case_submission_campaign", "tenant_id", "campaign_id"),
        ForeignKeyConstraint(
            ["tenant_id", "campaign_id"],
            ["review_platform.campaigns.tenant_id", "review_platform.campaigns.id"],
            name="case_submissions_tenant_id_campaign_id_fkey",
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    case_id: Mapped[str] = mapped_column(String(240))
    reviewer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Adjudication(Base, TimestampMixin):
    __tablename__ = "adjudications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_unit_id"],
            [f"{SCHEMA}.review_units.tenant_id", f"{SCHEMA}.review_units.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_adjudication_tenant_id"),
        UniqueConstraint("tenant_id", "review_unit_id", name="uq_adjudication_review_unit"),
        CheckConstraint("status IN ('pending','resolved')", name="ck_adjudication_status"),
        Index("ix_adjudications_tenant_unit", "tenant_id", "review_unit_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdjudicationParticipation(Base):
    """Stable per-adjudicator authorization and progress for shared adjudication work."""

    __tablename__ = "adjudication_participations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "adjudication_id"],
            [f"{SCHEMA}.adjudications.tenant_id", f"{SCHEMA}.adjudications.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "adjudication_id",
            "adjudicator_id",
            name="uq_adjudication_participation_adjudicator",
        ),
        CheckConstraint(
            "status IN ('pending','submitted','waived')",
            name="ck_adjudication_participation_status",
        ),
        Index(
            "ix_adjudication_participation_user_status",
            "tenant_id",
            "adjudicator_id",
            "status",
            "adjudication_id",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    adjudication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    adjudicator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")
    membership_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AdjudicationDecision(Base):
    """Immutable final adjudication decision for one adjudication task."""

    __tablename__ = "adjudication_decisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "adjudication_id"],
            [f"{SCHEMA}.adjudications.tenant_id", f"{SCHEMA}.adjudications.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "adjudication_id",
            "decided_by",
            name="uq_adjudication_decision_adjudicator",
        ),
        CheckConstraint(
            "outcome IN ('candidate_a_preferred','candidate_b_preferred',"
            "'equivalent_supported','both_wrong','unsupported_or_not_locatable',"
            "'exceptional_skip','reviewer_assessments_recorded','reviewer_preferred',"
            "'all_equivalent_supported','all_wrong')",
            name="ck_adjudication_decision_outcome",
        ),
        CheckConstraint(
            "(outcome NOT IN ('both_wrong','all_wrong','unsupported_or_not_locatable',"
            "'exceptional_skip') "
            "AND corrected_value_json IS NULL AND corrected_value_display IS NULL) "
            "OR length(btrim(comment)) > 0",
            name="ck_adjudication_decision_comment_required",
        ),
        CheckConstraint(
            "jsonb_typeof(assessments_json) = 'array' "
            "AND jsonb_array_length(assessments_json) >= 2",
            name="ck_adjudication_decision_assessments",
        ),
        ForeignKeyConstraint(
            ["tenant_id"],
            ["review_platform.tenants.id"],
            name="adjudication_decisions_tenant_id_fkey",
            ondelete="CASCADE",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    adjudication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    outcome: Mapped[str] = mapped_column(String(60))
    corrected_value_json: Mapped[Any | None] = mapped_column(JSONB(none_as_null=True))
    corrected_value_display: Mapped[str | None] = mapped_column(String(10_000))
    comment: Mapped[str | None] = mapped_column(Text)
    assessments_json: Mapped[list[dict[str, str]]] = mapped_column(JSONB)
    evidence_ids_json: Mapped[list[str]] = mapped_column(JSONB)
    corrected_provenance_spans_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, default=list
    )
    preferred_proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.reviewer_added_proposals.id")
    )
    client_request_id: Mapped[str] = mapped_column(String(128))
    decided_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AdjudicationDraft(Base, TimestampMixin):
    """Mutable adjudicator work-in-progress, separate from the immutable final decision."""

    __tablename__ = "adjudication_drafts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "adjudication_id"],
            [f"{SCHEMA}.adjudications.tenant_id", f"{SCHEMA}.adjudications.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint(
            "tenant_id",
            "adjudication_id",
            "saved_by",
            name="uq_adjudication_draft_adjudicator",
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    adjudication_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    decision_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    saved_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id")
    )


class IdempotencyRecord(Base, TimestampMixin):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "user_id", "operation", "key_digest", name="uq_idempotency_scope"
        ),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE")
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE")
    )
    operation: Mapped[str] = mapped_column(String(160))
    key_digest: Mapped[str] = mapped_column(String(64))
    request_digest: Mapped[str] = mapped_column(String(64))
    response_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    response_etag: Mapped[str | None] = mapped_column(String(40))
