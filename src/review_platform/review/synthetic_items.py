"""Synthetic item mapping, conflict checks, and review-owned row persistence."""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError, FieldProblem
from review_platform.dataset.contract import SnapshotItem, opaque_content_key
from review_platform.review.campaign_conflicts import CaseFieldCandidate, find_case_field_conflicts
from review_platform.review.models import (
    Campaign,
    Candidate,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)


def _review_kind(item: SnapshotItem) -> str:
    return "citation_link" if item.target.field == "citation_neutral" else "metadata_field"


if TYPE_CHECKING:
    from review_platform.review.synthetic_import import ReviewImportMixin


def _check_case_field_conflicts(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    items: list[SnapshotItem],
    exclude_campaign_id: uuid.UUID | None = None,
) -> None:
    """``exclude_campaign_id`` is the campaign being written into: a top-up import re-checking
    items already owned by this same campaign must not treat them as conflicting with
    themselves (see ``_top_up_synthetic_campaign``)."""

    candidates = [
        CaseFieldCandidate(
            case_id=item.target.external_id,
            review_kind=_review_kind(item),
            safe_field_label=item.target.field.replace("_", " ").title(),
        )
        for item in items
    ]
    conflicts = find_case_field_conflicts(
        session,
        tenant_id=tenant_id,
        exclude_campaign_id=exclude_campaign_id,
        candidates=candidates,
    )
    if conflicts:
        raise APIError(
            409,
            "campaign_case_field_conflict",
            "Campaign case/field conflict",
            "One or more selected case/field groups are already assigned to another active "
            "campaign.",
            errors=[
                FieldProblem(
                    path=["review_scope"],
                    code="case_field_conflict",
                    message=(
                        f"Case {conflict.case_id} field group '{conflict.group_label}' is "
                        f"already assigned in campaign '{conflict.campaign_key}'."
                    ),
                )
                for conflict in conflicts
            ],
        )


def _import_item(
    self: ReviewImportMixin,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    item: SnapshotItem,
    required_reviews: int,
) -> None:
    item_payload = item.model_dump(mode="json")
    item_digest = self._request_digest(item_payload)
    content_key = opaque_content_key(item)
    snapshot = session.scalar(
        select(SourceSnapshot).where(
            SourceSnapshot.tenant_id == tenant_id,
            SourceSnapshot.external_item_key == content_key,
        )
    )
    if snapshot is None:
        snapshot = SourceSnapshot(
            tenant_id=tenant_id,
            contract_version="review-dataset-snapshot/v1",
            source_version=item.source_revision,
            external_item_key=content_key,
            input_digest=item_digest,
        )
        session.add(snapshot)
        session.flush()
    elif snapshot.input_digest != item_digest:  # pragma: no cover - v0001 is immutable
        raise APIError(
            409,
            "snapshot_input_conflict",
            "Snapshot input conflict",
            "An immutable snapshot key has different bytes.",
        )
    subject = session.scalar(
        select(ReviewSubject).where(
            ReviewSubject.tenant_id == tenant_id,
            ReviewSubject.source_snapshot_id == snapshot.id,
        )
    )
    if subject is None:
        source_ref = hashlib.sha256(
            f"{item.source_document.source_system}:{item.source_document.sha256}".encode()
        ).hexdigest()[:32]
        subject = ReviewSubject(
            tenant_id=tenant_id,
            source_snapshot_id=snapshot.id,
            subject_kind="case",
            external_subject_id=f"subject_{content_key[:32]}",
            display_title=item.extraction.display_value,
            display_subtitle=item.target.field.replace("_", " ").title(),
            source_version=item.source_revision,
            primary_source_ref=f"source_{source_ref}",
            attributes_json={
                "field_label": item.target.field.replace("_", " ").title(),
                "source_collection": item.source_document.source_system,
                "snapshot_local_target_external_id": item.target.external_id,
                "snapshot_local_source_external_id": item.source_document.external_id,
                "source_sha256": item.source_document.sha256,
                "reference_semantics": "snapshot-local-soft-no-cross-database-fk",
                # See the ``snapshot_local_case_external_id`` note in
                # ``real_import._persist_unit``: today this equals
                # ``snapshot_local_target_external_id`` (synthetic v0001 is metadata-only, one
                # item per case), kept distinct for a future synthetic relation item whose
                # target differs from its case.
                "snapshot_local_case_external_id": item.target.external_id,
            },
        )
        session.add(subject)
        session.flush()
    unit = ReviewUnit(
        tenant_id=tenant_id,
        campaign_id=campaign.id,
        review_subject_id=subject.id,
        review_kind=self._review_kind(item),
        question=f"Review the {item.target.field.replace('_', ' ')} candidate pair.",
        safe_field_label=item.target.field.replace("_", " ").title(),
        required_reviews=required_reviews,
        input_digest=item_digest,
    )
    session.add(unit)
    session.flush()
    for candidate in item.validator_candidates:
        session.add(
            Candidate(
                tenant_id=tenant_id,
                review_unit_id=unit.id,
                label=candidate.display_label,
                source_kind=candidate.validator_kind,
                verdict=candidate.normalized_verdict,
                value_json=candidate.value,
                rationale=candidate.rationale,
                supporting_quote=candidate.supporting_quote,
            )
        )
    for evidence in item.evidence:
        session.add(
            EvidenceWindow(
                tenant_id=tenant_id,
                review_unit_id=unit.id,
                ordinal=evidence.ordinal,
                kind=evidence.kind,
                snippet=evidence.snippet,
                line_start=evidence.line_start,
                line_end=evidence.line_end,
                char_start=evidence.char_start,
                char_end=evidence.char_end,
                source_sha256=evidence.source_hash,
            )
        )
