"""Load the verified source document or fall back to evidence snippets."""

from __future__ import annotations

import uuid
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.review.artifact_store import ArtifactStore, read_verified_body
from review_platform.review.grouped_items import _PreparedRow
from review_platform.review.grouped_source_text import GroupedSourceTextMixin
from review_platform.review.models import (
    SourceRenderArtifact,
)
from review_platform.review.schemas import (
    AnchorUnavailableReason,
    SourceRender,
)
from review_platform.review.source_render import plain_text_from_safe_html


class GroupedSourceMixin(GroupedSourceTextMixin):
    @staticmethod
    def _build_source_render(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        prepared: list[_PreparedRow],
        source_snapshot_id: uuid.UUID,
        artifact_store: ArtifactStore | None,
    ) -> tuple[
        SourceRender,
        dict[uuid.UUID, str],
        dict[uuid.UUID, AnchorUnavailableReason],
        dict[str, str],
        dict[uuid.UUID, tuple[int, int]],
    ]:
        """Assemble the reviewer-facing safe-text render for this case's source document.

        Prefers the full document: when a current ``SourceRenderArtifact`` exists and its body is
        readable, rederives the artifact's own full plain text (deterministic from its persisted
        ``safe_html``, see ``source_render.plain_text_from_safe_html``) and reuses each evidence
        window's own import-time offsets as anchors -- those offsets already address this exact
        text (``real_import._add_evidence``). An older null-offset reported citation can receive a
        display-only header offset when its primary citation is unambiguous. Falls back to the
        legacy snippet-collage render (``_build_source_render_from_snippets``) when no artifact
        exists (synthetic fixtures) or its body cannot be read.
        """

        artifact = session.scalar(
            select(SourceRenderArtifact).where(
                SourceRenderArtifact.tenant_id == tenant_id,
                SourceRenderArtifact.source_snapshot_id == source_snapshot_id,
                SourceRenderArtifact.is_current.is_(True),
            )
        )
        if artifact is not None:
            body = read_verified_body(
                artifact_store,
                object_key=artifact.object_key,
                expected_digest=artifact.content_digest,
            )
            if body is not None:
                try:
                    safe_html = body.decode("utf-8")
                    plain_text = plain_text_from_safe_html(
                        cast(Literal["sample_a", "sample_b"], artifact.source_system), safe_html
                    )
                except (UnicodeDecodeError, ValueError):  # pragma: no cover - defensive
                    plain_text = None
                if plain_text is not None:
                    offsets: dict[uuid.UUID, tuple[int, int]] = {}
                    source, items, unavailable, groups = (
                        GroupedSourceMixin._build_source_render_from_full_text(
                            prepared, source_snapshot_id, plain_text, offsets
                        )
                    )
                    return source, items, unavailable, groups, offsets
        source, items, unavailable, groups = GroupedSourceMixin._build_source_render_from_snippets(
            prepared, source_snapshot_id
        )
        return source, items, unavailable, groups, {}
