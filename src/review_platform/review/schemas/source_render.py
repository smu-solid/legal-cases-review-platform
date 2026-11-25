"""Reviewer-safe schemas for the assignment-scoped source-render artifact API."""

from __future__ import annotations

import uuid
from typing import Literal

from review_platform.review.schemas.common import ReviewModel, SubjectKind

SourceRenderMode = Literal["sanitized_html"]


class SourceRenderAnchor(ReviewModel):
    """One normalized source anchor, addressing offsets into the rendered artifact body."""

    anchor_id: str
    char_start: int | None = None
    char_end: int | None = None
    label: str | None = None


class SourceRenderAnchorMap(ReviewModel):
    """The offset-only anchor map served alongside a rendered artifact body."""

    render_artifact_id: uuid.UUID
    anchors: list[SourceRenderAnchor]
    schema_version: Literal["source-render-anchor-map/v1"] = "source-render-anchor-map/v1"


class SourceRenderArtifactMetadata(ReviewModel):
    """Reviewer-safe metadata for the current derived render artifact of an assignment's
    subject."""

    render_artifact_id: uuid.UUID
    source_snapshot_id: uuid.UUID
    subject_kind: SubjectKind
    source_kind: str
    render_profile: str
    render_version: int
    render_mode: SourceRenderMode
    content_digest: str
    anchor_map_digest: str
    artifact_mime_type: str
    artifact_size_bytes: int
    # Same-origin API URLs, never object-store locators.
    body_url: str
    anchor_map_url: str
    schema_version: Literal["source-render-artifact/v1"] = "source-render-artifact/v1"
