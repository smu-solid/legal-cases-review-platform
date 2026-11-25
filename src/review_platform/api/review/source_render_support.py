"""Shared source-render metadata and integrity-checked store reads."""

from __future__ import annotations

import hashlib

from review_platform.common.errors import APIError
from review_platform.review.artifact_store import (
    ArtifactNotFoundError,
    ArtifactStore,
    ArtifactTooLargeError,
)
from review_platform.review.models import SourceRenderArtifact
from review_platform.review.schemas import SourceRenderArtifactMetadata


def source_render_metadata(
    artifact: SourceRenderArtifact, *, prefix: str
) -> SourceRenderArtifactMetadata:
    return SourceRenderArtifactMetadata(
        render_artifact_id=artifact.id,
        source_snapshot_id=artifact.source_snapshot_id,
        subject_kind=artifact.subject_kind,
        source_kind=artifact.source_kind,
        render_profile=artifact.render_profile,
        render_version=artifact.render_version,
        render_mode="sanitized_html",
        content_digest=artifact.content_digest,
        anchor_map_digest=artifact.anchor_map_digest,
        artifact_mime_type=artifact.artifact_mime_type,
        artifact_size_bytes=artifact.artifact_size_bytes,
        body_url=f"{prefix}/body",
        anchor_map_url=f"{prefix}/anchors",
    )


def read_verified_artifact(
    store: ArtifactStore | None, *, object_key: str, kind: str, expected_digest: str
) -> bytes:
    if store is None:
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    try:
        raw = store.read_body(object_key) if kind == "body" else store.read_anchor_map(object_key)
    except ArtifactNotFoundError as exc:
        raise APIError(404, "not_found", "Not found", "The resource was not found.") from exc
    except ArtifactTooLargeError as exc:
        raise APIError(
            500,
            "source_render_unavailable",
            "Source render unavailable",
            "The artifact is invalid.",
        ) from exc
    if hashlib.sha256(raw).hexdigest() != expected_digest:
        raise APIError(
            500,
            "source_render_unavailable",
            "Source render unavailable",
            "The artifact is invalid.",
        )
    return raw
