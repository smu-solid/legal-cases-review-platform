"""Review-subject ORM models: source snapshots, subjects, units, candidates, and evidence."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from review_platform.db.models import SCHEMA, Base, TimestampMixin, utcnow


class SourceSnapshot(Base):
    __tablename__ = "source_snapshots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "external_item_key", name="uq_snapshot_external_item"),
        UniqueConstraint("tenant_id", "id", name="uq_snapshot_tenant_id"),
        CheckConstraint("source_mode IN ('synthetic', 'dataset')", name="ck_snapshot_source_mode"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.tenants.id", ondelete="CASCADE")
    )
    contract_version: Mapped[str] = mapped_column(String(80))
    source_mode: Mapped[str] = mapped_column(String(20), default="synthetic")
    source_version: Mapped[str] = mapped_column(String(100))
    external_item_key: Mapped[str] = mapped_column(String(240))
    input_digest: Mapped[str] = mapped_column(String(64))
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ReviewSubject(Base):
    __tablename__ = "review_subjects"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_snapshot_id"],
            [f"{SCHEMA}.source_snapshots.tenant_id", f"{SCHEMA}.source_snapshots.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "source_snapshot_id", name="uq_subject_snapshot"),
        UniqueConstraint("tenant_id", "id", name="uq_subject_tenant_id"),
        # Expression indexes over the two attributes_json keys the importer filters on
        # (real_import: the per-unit logical-presence probe and the refresh path's
        # removed-input sweep). Without them each probe re-scans every pooled subject and
        # JSONB-parses attributes_json row by row, so provisioning degrades quadratically as
        Index(
            "ix_subject_logical_external_item",
            "tenant_id",
            text("(attributes_json ->> 'logical_external_item_key')"),
        ),
        Index(
            "ix_subject_snapshot_local_case",
            "tenant_id",
            text("(attributes_json ->> 'snapshot_local_case_external_id')"),
        ),
        Index("ix_subject_logical_key_col", "tenant_id", "logical_external_item_key"),
        Index("ix_subject_snapshot_case_col", "tenant_id", "snapshot_local_case_external_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    subject_kind: Mapped[str] = mapped_column(String(40))
    external_subject_id: Mapped[str] = mapped_column(String(100))
    display_title: Mapped[str] = mapped_column(String(300))
    display_subtitle: Mapped[str | None] = mapped_column(String(300))
    source_version: Mapped[str | None] = mapped_column(String(100))
    primary_source_ref: Mapped[str] = mapped_column(String(120))
    attributes_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    # STORED generated mirrors of the two attributes_json keys the importer probes per unit. Under
    # FORCE RLS the planner cannot use an index over ``->>`` (not leakproof); plain text columns
    # compare with the leakproof ``=`` and their indexes stay usable for RLS-subject roles.
    logical_external_item_key: Mapped[str | None] = mapped_column(
        Text, Computed("(attributes_json ->> 'logical_external_item_key')", persisted=True)
    )
    snapshot_local_case_external_id: Mapped[str | None] = mapped_column(
        Text, Computed("(attributes_json ->> 'snapshot_local_case_external_id')", persisted=True)
    )


class ReviewUnit(Base, TimestampMixin):
    __tablename__ = "review_units"
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
            "tenant_id",
            "campaign_id",
            "review_subject_id",
            "review_kind",
            name="uq_review_unit_input",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_review_unit_tenant_id"),
        CheckConstraint(
            "status IN ('pending','in_review','in_adjudication','resolved')",
            name="ck_review_unit_status",
        ),
        CheckConstraint("required_reviews >= 2", name="ck_review_unit_required_reviews"),
        CheckConstraint(
            "extraction_state IN ('present','missing')",
            name="ck_review_unit_extraction_state",
        ),
        Index("ix_review_unit_queue", "tenant_id", "status", "created_at", "id"),
        Index("ix_review_units_tenant_subject", "tenant_id", "review_subject_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    campaign_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_kind: Mapped[str] = mapped_column(String(60))
    question: Mapped[str] = mapped_column(String(1000))
    safe_field_label: Mapped[str] = mapped_column(String(160))
    # Stable source column name (e.g. ``cases.citation_neutral``) an atomic metadata unit was
    # imported from -- the grouping key, decoupled from the renamable display ``safe_field_label``.
    # Null for relation units (grouped by ``review_kind``) and legacy rows imported before this
    field_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="pending")
    required_reviews: Mapped[int] = mapped_column(Integer, default=2)
    lock_version: Mapped[int] = mapped_column(Integer, default=1)
    input_digest: Mapped[str] = mapped_column(String(64))
    extraction_state: Mapped[str] = mapped_column(String(20), default="present")


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_unit_id"],
            [f"{SCHEMA}.review_units.tenant_id", f"{SCHEMA}.review_units.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "review_unit_id", "label", name="uq_candidate_label"),
        UniqueConstraint("tenant_id", "id", name="uq_candidate_tenant_id"),
        CheckConstraint("label IN ('A','B')", name="ck_candidate_label"),
        CheckConstraint("source_kind IN ('deterministic','model')", name="ck_candidate_source"),
        Index("ix_candidates_tenant_unit", "tenant_id", "review_unit_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    label: Mapped[str] = mapped_column(String(1))
    source_kind: Mapped[str] = mapped_column(String(20))
    verdict: Mapped[str] = mapped_column(String(40))
    value_json: Mapped[Any | None] = mapped_column(JSONB)
    rationale: Mapped[str] = mapped_column(String(10_000))
    supporting_quote: Mapped[str | None] = mapped_column(String(10_000))


class EvidenceWindow(Base):
    __tablename__ = "evidence_windows"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "review_unit_id"],
            [f"{SCHEMA}.review_units.tenant_id", f"{SCHEMA}.review_units.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "review_unit_id", "ordinal", name="uq_evidence_ordinal"),
        UniqueConstraint("tenant_id", "id", name="uq_evidence_tenant_id"),
        CheckConstraint("char_start IS NULL OR char_start >= 0", name="ck_evidence_char_start"),
        CheckConstraint(
            "char_end IS NULL OR char_start IS NULL OR char_end >= char_start",
            name="ck_evidence_char_end",
        ),
        CheckConstraint(
            "anchor_status IS NULL OR anchor_status IN ('anchored', 'expected_unanchored', "
            "'unexpected_unresolved', 'other_document')",
            name="ck_evidence_anchor_status",
        ),
        Index("ix_evidence_windows_tenant_anchor_status", "tenant_id", "anchor_status"),
        Index("ix_evidence_windows_tenant_unit", "tenant_id", "review_unit_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    review_unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    ordinal: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(40))
    snippet: Mapped[str] = mapped_column(String(20_000))
    line_start: Mapped[int | None] = mapped_column(Integer)
    line_end: Mapped[int | None] = mapped_column(Integer)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    source_sha256: Mapped[str] = mapped_column(String(64))
    provenance_external_id: Mapped[str | None] = mapped_column(String(64))
    body_grounded: Mapped[bool | None] = mapped_column(Boolean)
    source_region: Mapped[str | None] = mapped_column(String(40))
    anchor_status: Mapped[str | None] = mapped_column(String(32))
