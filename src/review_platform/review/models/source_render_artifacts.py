"""Derived source-render artifact metadata (review-owned, immutable, metadata-only).

One row describes one derived render artifact for a source snapshot. The artifact body (sanitized
HTML) and anchor map live in the store, addressed by the opaque ``object_key`` -- never in a
hot database column. Rows are append-only (a DB trigger rejects UPDATE/DELETE) so a served artifact
is content-addressable and cannot be silently altered; re-rendering emits a new row/version through
an approved job. A partial unique index keeps at most one ``is_current`` artifact per snapshot.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from review_platform.db.models import SCHEMA, Base, utcnow


class SourceRenderArtifact(Base):
    __tablename__ = "source_render_artifacts"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "source_snapshot_id"],
            [f"{SCHEMA}.source_snapshots.tenant_id", f"{SCHEMA}.source_snapshots.id"],
            ondelete="CASCADE",
        ),
        UniqueConstraint("tenant_id", "id", name="uq_source_render_artifact_tenant_id"),
        Index(
            "uq_source_render_artifact_current",
            "tenant_id",
            "source_snapshot_id",
            unique=True,
            postgresql_where=text("is_current"),
        ),
        CheckConstraint("render_mode = 'sanitized_html'", name="ck_source_render_mode"),
        CheckConstraint("char_length(content_digest) = 64", name="ck_source_render_content_digest"),
        CheckConstraint(
            "char_length(anchor_map_digest) = 64", name="ck_source_render_anchor_digest"
        ),
        CheckConstraint("artifact_size_bytes >= 0", name="ck_source_render_size_bytes"),
        CheckConstraint("render_version >= 1", name="ck_source_render_version"),
        Index("ix_source_render_artifacts_tenant_snapshot", "tenant_id", "source_snapshot_id"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    source_snapshot_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True))
    subject_kind: Mapped[str] = mapped_column(String(40))
    source_system: Mapped[str] = mapped_column(String(40))
    source_kind: Mapped[str] = mapped_column(String(40))
    render_profile: Mapped[str] = mapped_column(String(60))
    render_version: Mapped[int] = mapped_column(Integer)
    render_mode: Mapped[str] = mapped_column(String(20))
    content_digest: Mapped[str] = mapped_column(String(64))
    anchor_map_digest: Mapped[str] = mapped_column(String(64))
    object_key: Mapped[str] = mapped_column(String(128))
    artifact_mime_type: Mapped[str] = mapped_column(String(80))
    artifact_size_bytes: Mapped[int] = mapped_column(Integer)
    is_current: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    created_by_job: Mapped[str] = mapped_column(String(120))
