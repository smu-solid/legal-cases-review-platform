"""Normalized document artifacts."""

from review_platform.review.source_render.document import (
    RenderedArtifact,
    plain_text_from_safe_html,
    render_source_document,
)

SourceSystem = str
ARTIFACT_MIME_TYPE = "text/html"
__all__ = [
    "RenderedArtifact",
    "plain_text_from_safe_html",
    "render_source_document",
    "SourceSystem",
    "ARTIFACT_MIME_TYPE",
]
