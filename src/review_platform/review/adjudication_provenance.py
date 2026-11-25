"""Authorization-bound source text and validation for adjudicator corrections."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.common.text_coordinates import utf16_length
from review_platform.review.adjudication_cases import same_case_clause
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.grouped_bundle import ReviewGroupedBundleMixin
from review_platform.review.grouping import classify_unit
from review_platform.review.models import (
    Adjudication,
    AdjudicationParticipation,
    Assignment,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.schemas import AdjudicationDraftInput


def adjudication_source_text(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    adjudication_id: uuid.UUID,
    adjudicator_id: uuid.UUID,
    artifact_store: ArtifactStore | None,
) -> str:
    """Rebuild the exact caller-authorized plain-text workspace projection."""

    anchor = session.execute(
        select(ReviewUnit, ReviewSubject)
        .join(Adjudication, Adjudication.review_unit_id == ReviewUnit.id)
        .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
        .where(Adjudication.tenant_id == tenant_id, Adjudication.id == adjudication_id)
    ).first()
    if anchor is None:  # pragma: no cover - checked by the mutation before this helper
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    anchor_unit, anchor_subject = anchor
    rows = session.execute(
        select(ReviewUnit, ReviewSubject)
        .join(Adjudication, Adjudication.review_unit_id == ReviewUnit.id)
        .join(
            AdjudicationParticipation,
            AdjudicationParticipation.adjudication_id == Adjudication.id,
        )
        .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
        .where(
            Adjudication.tenant_id == tenant_id,
            ReviewUnit.campaign_id == anchor_unit.campaign_id,
            AdjudicationParticipation.adjudicator_id == adjudicator_id,
            AdjudicationParticipation.status.in_(("pending", "submitted")),
            same_case_clause(anchor_subject),
        )
    ).all()
    prepared = []
    for unit, subject in rows:
        assignment = session.scalar(
            select(Assignment)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.review_unit_id == unit.id,
                Assignment.status == "submitted",
            )
            .order_by(Assignment.id)
            .limit(1)
        )
        if assignment is None:  # pragma: no cover - adjudication readiness invariant
            continue
        prepared.append(
            (
                classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name),
                assignment,
                unit,
                subject,
                list(
                    session.scalars(
                        select(EvidenceWindow)
                        .where(
                            EvidenceWindow.tenant_id == tenant_id,
                            EvidenceWindow.review_unit_id == unit.id,
                        )
                        .order_by(EvidenceWindow.id)
                    )
                ),
            )
        )
    prepared.sort(key=lambda row: (row[0].order, row[2].created_at, str(row[2].id)))
    source_render, _anchors, _unavailable, _groups, _offsets = (
        ReviewGroupedBundleMixin._build_source_render(
            session,
            tenant_id=tenant_id,
            prepared=prepared,
            source_snapshot_id=anchor_subject.source_snapshot_id,
            artifact_store=artifact_store,
        )
    )
    return source_render.content


def validate_adjudication_provenance(
    decision: AdjudicationDraftInput,
    *,
    allowed_evidence_ids: set[uuid.UUID],
    source_length: int,
) -> None:
    spans = decision.corrected_provenance_spans
    if spans and decision.outcome != "all_wrong":
        raise APIError(
            422,
            "corrected_provenance_spans_invalid",
            "Invalid corrected provenance spans",
            "Corrected provenance may only accompany an all-wrong decision.",
        )
    evidence_ids = [span.evidence_window_id for span in spans]
    if len(evidence_ids) != len(set(evidence_ids)) or not set(evidence_ids).issubset(
        allowed_evidence_ids
    ):
        raise APIError(
            422,
            "corrected_provenance_spans_invalid",
            "Invalid corrected provenance spans",
            "Corrected provenance must reference unique evidence from this adjudication field.",
        )
    if any(span.char_end > source_length for span in spans):
        raise APIError(
            422,
            "corrected_provenance_spans_invalid",
            "Invalid corrected provenance spans",
            "Corrected provenance offsets must address the authorized rendered plain text.",
        )


def validate_adjudication_correction(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    adjudication_id: uuid.UUID,
    adjudicator_id: uuid.UUID,
    review_unit_id: uuid.UUID,
    decision: AdjudicationDraftInput,
    artifact_store: ArtifactStore | None,
) -> None:
    """Validate a draft/final correction against its unit and exact workspace text."""

    evidence_ids = set(
        session.scalars(
            select(EvidenceWindow.id).where(
                EvidenceWindow.tenant_id == tenant_id,
                EvidenceWindow.review_unit_id == review_unit_id,
            )
        )
    )
    source_text = adjudication_source_text(
        session,
        tenant_id=tenant_id,
        adjudication_id=adjudication_id,
        adjudicator_id=adjudicator_id,
        artifact_store=artifact_store,
    )
    validate_adjudication_provenance(
        decision,
        allowed_evidence_ids=evidence_ids,
        source_length=utf16_length(source_text),
    )
