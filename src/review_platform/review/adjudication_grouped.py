"""Grouped value/provenance adjudication read projection."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.db.models import User
from review_platform.review import adjudication_reads
from review_platform.review.adjudication_cases import adjudication_case_id, same_case_clause
from review_platform.review.adjudication_drafts import adjudication_draft_response
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.base import ReviewServiceBase
from review_platform.review.grouped_bundle import ReviewGroupedBundleMixin
from review_platform.review.grouping import classify_unit, display_field_label, item_kind
from review_platform.review.models import (
    Adjudication,
    AdjudicationDraft,
    AdjudicationParticipation,
    Assignment,
    Campaign,
    Candidate,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.projections import evidence_response, subject_response
from review_platform.review.relation_display import (
    extracted_value,
    is_neutral_citation_field,
    is_reported_citation_field,
    is_title_field,
)
from review_platform.review.schemas import (
    AdjudicationAssessmentTarget,
    AdjudicationFieldGroup,
    AdjudicationGroupedBundle,
    AdjudicationGroupedItem,
    AdjudicationReviewerIdentity,
    CorrectedProvenanceSpan,
    PseudonymousGroupedSubmission,
    ReviewerCaseHeader,
)


class ReviewAdjudicationGroupedMixin(ReviewServiceBase):
    def adjudication_grouped_bundle(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        artifact_store: ArtifactStore | None = None,
    ) -> AdjudicationGroupedBundle:
        """Return every pending field for the claimed case, while decisions stay per field."""

        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        anchor_adjudication = adjudication_reads.pending_adjudication(
            session, tenant_id=tenant_id, adjudication_id=adjudication_id, principal=principal
        )
        anchor_unit = adjudication_reads.adjudication_unit(
            session, tenant_id=tenant_id, adjudication=anchor_adjudication
        )
        anchor_subject = adjudication_reads.unit_subject(
            session, tenant_id=tenant_id, unit=anchor_unit
        )
        campaign = session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id,
                Campaign.id == anchor_unit.campaign_id,
            )
        )
        if campaign is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")

        case_id = adjudication_case_id(anchor_subject)
        rows = session.execute(
            select(Adjudication, ReviewUnit, ReviewSubject)
            .join(
                AdjudicationParticipation,
                (AdjudicationParticipation.tenant_id == Adjudication.tenant_id)
                & (AdjudicationParticipation.adjudication_id == Adjudication.id),
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Adjudication.tenant_id)
                & (ReviewUnit.id == Adjudication.review_unit_id),
            )
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.status == "pending",
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status == "pending",
                ReviewUnit.campaign_id == anchor_unit.campaign_id,
                same_case_clause(anchor_subject),
            )
        ).all()

        prepared = []
        row_details = []
        for adjudication, unit, subject in rows:
            group = classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name)
            evidence = adjudication_reads.unit_evidence(
                session, tenant_id=tenant_id, unit_id=unit.id
            )
            submitted_assignment = session.scalar(
                select(Assignment)
                .where(
                    Assignment.tenant_id == tenant_id,
                    Assignment.review_unit_id == unit.id,
                    Assignment.status == "submitted",
                )
                .order_by(Assignment.id)
                .limit(1)
            )
            if submitted_assignment is None:  # pragma: no cover - adjudication creation invariant
                continue
            candidates = list(
                session.scalars(
                    select(Candidate)
                    .where(
                        Candidate.tenant_id == tenant_id,
                        Candidate.review_unit_id == unit.id,
                    )
                    .order_by(Candidate.label)
                )
            )
            prepared.append((group, submitted_assignment, unit, subject, evidence))
            row_details.append((adjudication, group, unit, subject, evidence, candidates))

        prepared.sort(key=lambda row: (row[0].order, row[2].created_at, str(row[2].id)))
        row_details.sort(key=lambda row: (row[1].order, row[2].created_at, str(row[2].id)))
        (
            source_render,
            item_anchor_by_unit,
            anchor_unavailable_by_unit,
            _group_anchor_by_id,
            effective_offsets,
        ) = ReviewGroupedBundleMixin._build_source_render(
            session,
            tenant_id=tenant_id,
            prepared=prepared,
            source_snapshot_id=anchor_subject.source_snapshot_id,
            artifact_store=artifact_store,
        )

        items_by_group: dict[str, list[AdjudicationGroupedItem]] = defaultdict(list)
        groups_by_id = {}
        case_title: str | None = None
        neutral_citation_display = None
        reported_citation_display = None
        for adjudication, group, unit, subject, evidence, candidates in row_details:
            candidate_a = next(
                (candidate for candidate in candidates if candidate.label == "A"), None
            )
            if unit.extraction_state == "missing":
                extracted_value_display = "No value extracted"
            else:
                extracted_value_display, _raw_value = extracted_value(
                    candidate_a,
                    fallback=subject.display_title,
                    review_kind=unit.review_kind,
                )
            if case_title is None and is_title_field(unit.field_name, unit.safe_field_label):
                case_title = extracted_value_display
            elif is_neutral_citation_field(unit.field_name, unit.safe_field_label):
                neutral_citation_display = extracted_value_display
            elif is_reported_citation_field(unit.field_name, unit.safe_field_label):
                reported_citation_display = extracted_value_display
            submissions = self._grouped_submissions(session, tenant_id=tenant_id, unit_id=unit.id)
            draft = session.scalar(
                select(AdjudicationDraft).where(
                    AdjudicationDraft.tenant_id == tenant_id,
                    AdjudicationDraft.adjudication_id == adjudication.id,
                    AdjudicationDraft.saved_by == principal.user.id,
                )
            )
            groups_by_id[group.group_id] = group
            items_by_group[group.group_id].append(
                AdjudicationGroupedItem(
                    adjudication_id=adjudication.id,
                    review_unit_id=unit.id,
                    item_id=str(unit.id),
                    item_label=display_field_label(unit.field_name, unit.safe_field_label),
                    item_kind=item_kind(unit.review_kind),
                    extracted_value_display=extracted_value_display,
                    review_kind=unit.review_kind,
                    required_reviews=unit.required_reviews,
                    submitted_reviews=len(submissions),
                    source_anchor_id=item_anchor_by_unit.get(unit.id),
                    source_anchor_unavailable_reason=anchor_unavailable_by_unit.get(unit.id),
                    evidence_window_ids=[item.id for item in evidence],
                    assessment_targets=[
                        AdjudicationAssessmentTarget(
                            id=candidate.id,
                            label=cast(Literal["A", "B"], candidate.label),
                        )
                        for candidate in candidates
                    ],
                    evidence_windows=[
                        evidence_response(
                            item, subject.attributes_json, effective_offsets=effective_offsets
                        )
                        for item in evidence
                    ],
                    submissions=submissions,
                    draft=adjudication_draft_response(draft) if draft is not None else None,
                )
            )

        field_groups = [
            AdjudicationFieldGroup(
                group_id=group.group_id,
                group_label=group.group_label,
                group_kind=group.group_kind,
                description=group.description,
                order=group.order,
                items=items_by_group[group.group_id],
            )
            for group in sorted(groups_by_id.values(), key=lambda item: item.order)
        ]
        return AdjudicationGroupedBundle(
            adjudication_id=anchor_adjudication.id,
            review_subject=subject_response(anchor_subject),
            case_header=ReviewerCaseHeader(
                subject_id=anchor_subject.id,
                subject_kind=anchor_subject.subject_kind,
                case_title=case_title or anchor_subject.display_title,
                case_identifier_display=anchor_subject.external_subject_id,
                neutral_citation_display=neutral_citation_display,
                reported_citation_display=reported_citation_display,
                source_system=anchor_subject.attributes_json.get("source_collection"),
                campaign_name=campaign.name,
            ),
            case_id=case_id,
            campaign_id=campaign.id,
            campaign_name=campaign.name,
            field_groups=field_groups,
            source_render=source_render,
            pending_item_count=sum(len(items) for items in items_by_group.values()),
        )

    @staticmethod
    def _grouped_submissions(
        session: Session, *, tenant_id: uuid.UUID, unit_id: uuid.UUID
    ) -> list[PseudonymousGroupedSubmission]:
        latest_submitted = (
            select(
                ReviewItemAnswer.assignment_id,
                func.max(ReviewItemAnswer.revision_no).label("revision_no"),
            )
            .join(
                Assignment,
                (Assignment.tenant_id == ReviewItemAnswer.tenant_id)
                & (Assignment.id == ReviewItemAnswer.assignment_id),
            )
            .where(
                ReviewItemAnswer.tenant_id == tenant_id,
                Assignment.review_unit_id == unit_id,
                Assignment.status == "submitted",
                ReviewItemAnswer.state == "submitted",
            )
            .group_by(ReviewItemAnswer.assignment_id)
            .subquery()
        )
        answers = session.execute(
            select(ReviewItemAnswer, User)
            .select_from(ReviewItemAnswer)
            .join(
                latest_submitted,
                (latest_submitted.c.assignment_id == ReviewItemAnswer.assignment_id)
                & (latest_submitted.c.revision_no == ReviewItemAnswer.revision_no),
            )
            .where(
                ReviewItemAnswer.tenant_id == tenant_id,
                ReviewItemAnswer.state == "submitted",
            )
            .join(Assignment, Assignment.id == ReviewItemAnswer.assignment_id)
            .join(User, User.id == Assignment.reviewer_id)
            .order_by(ReviewItemAnswer.created_at, ReviewItemAnswer.id)
        ).all()
        return [
            PseudonymousGroupedSubmission(
                submission_id=answer.id,
                pseudonym=f"Reviewer {index}",
                value_correct=answer.value_correct is True,
                provenance_correct=answer.provenance_correct is True,
                corrected_value=answer.corrected_value_json,
                corrected_value_display=answer.corrected_value_display,
                comment=answer.comment,
                failure_reason=answer.failure_reason,
                evidence_ids=[uuid.UUID(value) for value in answer.evidence_ids_json],
                corrected_provenance_spans=[
                    CorrectedProvenanceSpan.model_validate(span)
                    for span in answer.corrected_provenance_spans_json
                ],
                submitted_at=answer.created_at,
                reviewer=AdjudicationReviewerIdentity(
                    display_name=user.display_name or None,
                    email=user.email_normalized,
                ),
            )
            for index, (answer, user) in enumerate(answers, start=1)
        ]
