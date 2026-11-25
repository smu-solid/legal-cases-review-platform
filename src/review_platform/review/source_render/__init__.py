"""Generic document rendering and evidence anchoring."""

from review_platform.review.source_render.anchor_map import (
    AnchorHit,
    build_anchor_map,
    folded_contains,
)
from review_platform.review.source_render.artifacts import (
    ARTIFACT_MIME_TYPE,
    RenderedArtifact,
    plain_text_from_safe_html,
    render_source_document,
)

__all__ = [
    "AnchorHit",
    "build_anchor_map",
    "folded_contains",
    "ARTIFACT_MIME_TYPE",
    "RenderedArtifact",
    "plain_text_from_safe_html",
    "render_source_document",
]
