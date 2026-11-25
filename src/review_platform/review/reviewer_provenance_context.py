"""Author-only group evidence projected onto the verified displayed document."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.review.artifact_store import ArtifactStore, read_verified_body
from review_platform.review.models import EvidenceWindow, ReviewSubject, SourceRenderArtifact
from review_platform.review.proposal_scope import PROPOSAL_GROUPS
from review_platform.review.proposal_validation import source_version
from review_platform.review.schemas.citation_duplicates import ReviewerProvenanceContext
from review_platform.review.schemas.grouped_bundle import GroupItem, ReviewerGroupingBundle
from review_platform.review.source_render import plain_text_from_safe_html

if TYPE_CHECKING:
    from review_platform.review.grouped_items import _PreparedRow


def attach_context(
    bundle: ReviewerGroupingBundle,
    session: Session,
    tenant_id: uuid.UUID,
    prepared: list[_PreparedRow],
    artifact_store: ArtifactStore | None,
) -> None:
    render = bundle.source_render
    version = source_version(render.content)
    artifacts = {
        a.source_snapshot_id: a
        for a in session.scalars(
            select(SourceRenderArtifact).where(
                SourceRenderArtifact.tenant_id == tenant_id,
                SourceRenderArtifact.source_snapshot_id.in_(
                    [r[3].source_snapshot_id for r in prepared]
                ),
                SourceRenderArtifact.is_current.is_(True),
            )
        )
    }
    displayed = artifacts.get(render.source_snapshot_id)
    full_document = _matches_render(displayed, artifact_store, render.content)
    verified = {render.source_snapshot_id}
    if displayed and full_document:
        verified.update(
            sid
            for sid, a in artifacts.items()
            if (a.source_system, a.content_digest)
            == (displayed.source_system, displayed.content_digest)
        )
    bundle.proposal_source_snapshot_ids = sorted(verified, key=str)
    rows = {unit.id: (subject, evidence) for _, _, unit, subject, evidence in prepared}
    for group in bundle.field_groups:
        if group.group_id not in PROPOSAL_GROUPS:
            continue
        for item in group.items:
            subject, evidence = rows[item.review_unit_id]
            _item_context(bundle, item, group.group_id, subject, evidence, verified, full_document)
    for proposal in bundle.reviewer_additions:
        for proposal_span in proposal.provenance:
            if (
                proposal_span.source_snapshot_id in verified
                and proposal_span.source_version == version
            ):
                _append(
                    bundle,
                    proposal.id,
                    proposal.group_id,
                    proposal.value,
                    "Your added item",
                    False,
                    proposal_span.char_start,
                    proposal_span.char_end,
                )


def _append(
    bundle: ReviewerGroupingBundle,
    item_id: uuid.UUID,
    group_id: str,
    value: str,
    kind: Literal["Extracted", "Your correction", "Your added item"],
    superseded: bool,
    start: int | None,
    end: int | None,
) -> None:
    length = len(bundle.source_render.content.encode("utf-16-le")) // 2
    if start is None or end is None or not 0 <= start < end <= length:
        return
    bundle.provenance_context.append(
        ReviewerProvenanceContext(
            item_id=item_id,
            group_id=group_id,
            value=value,
            kind=kind,
            superseded=superseded,
            source_snapshot_id=bundle.source_render.source_snapshot_id,
            source_version=source_version(bundle.source_render.content),
            char_start=start,
            char_end=end,
        )
    )


def _matches_render(
    artifact: SourceRenderArtifact | None, store: ArtifactStore | None, content: str
) -> bool:
    if artifact is None:
        return False
    body = read_verified_body(
        store, object_key=artifact.object_key, expected_digest=artifact.content_digest
    )
    if body is None:
        return False
    try:
        text = plain_text_from_safe_html(
            cast(Literal["sample_a", "sample_b"], artifact.source_system), body.decode("utf-8")
        )
        return text.startswith(content)
    except (UnicodeDecodeError, ValueError):
        return False


def _item_context(
    bundle: ReviewerGroupingBundle,
    item: GroupItem,
    group_id: str,
    subject: ReviewSubject,
    evidence: list[EvidenceWindow],
    verified: set[uuid.UUID],
    full_document: bool,
) -> None:
    summary = item.answer_summary
    superseded = bool(
        summary and (summary.provenance_correct is False or summary.corrected_provenance_spans)
    )
    anchor = next(
        (a for a in bundle.source_render.anchors if a.anchor_id == item.source_anchor_id), None
    )
    if full_document and subject.source_snapshot_id in verified:
        for window in evidence:
            if window.anchor_status != "other_document":
                _append(
                    bundle,
                    item.review_unit_id,
                    group_id,
                    item.extracted_value_display,
                    "Extracted",
                    superseded,
                    window.char_start,
                    window.char_end,
                )
    elif anchor and not full_document:
        _append(
            bundle,
            item.review_unit_id,
            group_id,
            item.extracted_value_display,
            "Extracted",
            superseded,
            anchor.char_start,
            anchor.char_end,
        )
    if summary:
        allowed = {e.id for e in evidence}
        legacy_allowed = {e.id for e in evidence if e.anchor_status != "other_document"}
        for span in summary.corrected_provenance_spans:
            versioned = (
                span.source_snapshot_id in verified
                and span.source_version == bundle.proposal_source_version
            )
            legacy = (
                span.evidence_window_id in legacy_allowed
                and span.source_snapshot_id is None
                and subject.source_snapshot_id in verified
            )
            if span.evidence_window_id in allowed and (versioned or legacy):
                _append(
                    bundle,
                    item.review_unit_id,
                    group_id,
                    summary.corrected_value_display or item.extracted_value_display,
                    "Your correction",
                    False,
                    span.char_start,
                    span.char_end,
                )
