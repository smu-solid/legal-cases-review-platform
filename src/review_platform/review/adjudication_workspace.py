"""Authorized editable/read-only adjudication case workspace projection."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.review import adjudication_reads
from review_platform.review.adjudication_campaigns import ReviewAdjudicationCampaignMixin
from review_platform.review.adjudication_cases import adjudication_case_id, same_case_clause
from review_platform.review.adjudication_drafts import adjudication_draft_response
from review_platform.review.adjudication_grouped import ReviewAdjudicationGroupedMixin
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.base import ReviewServiceBase
from review_platform.review.grouped_bundle import ReviewGroupedBundleMixin
from review_platform.review.grouping import classify_unit, display_field_label, item_kind
from review_platform.review.models import (
    Adjudication,
    AdjudicationDecision,
    AdjudicationDraft,
    AdjudicationParticipation,
    Assignment,
    Campaign,
    Candidate,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.projections import adjudication_decision_response, evidence_response
from review_platform.review.relation_display import (
    extracted_value,
    is_neutral_citation_field,
    is_reported_citation_field,
    is_title_field,
)
from review_platform.review.schemas import (
    AdjudicationAssessmentTarget,
    AdjudicationCaseWorkspace,
    AdjudicationWorkspaceFieldGroup,
    AdjudicationWorkspaceItem,
    ReviewerCaseHeader,
)


class ReviewAdjudicationWorkspaceMixin(ReviewServiceBase):
    def adjudication_case_workspace(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal,
        artifact_store: ArtifactStore | None = None,
        request_id: str = "adjudication-case-workspace",
    ) -> AdjudicationCaseWorkspace:
        self._require_role(session, principal, tenant_id, "adjudicator", allow_global_admin=True)
        self._set_tenant_scope(session, tenant_id)
        self._reconcile_inactive_adjudicators(session, tenant_id=tenant_id, request_id=request_id)
        anchor = session.execute(
            select(Adjudication, AdjudicationParticipation, ReviewUnit, ReviewSubject)
            .join(
                AdjudicationParticipation,
                AdjudicationParticipation.adjudication_id == Adjudication.id,
            )
            .join(ReviewUnit, ReviewUnit.id == Adjudication.review_unit_id)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.id == adjudication_id,
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status.in_(("pending", "submitted")),
            )
        ).first()
        if anchor is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        anchor_adjudication, _anchor_participation, anchor_unit, anchor_subject = anchor
        campaign = session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id, Campaign.id == anchor_unit.campaign_id
            )
        )
        if campaign is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        rows = session.execute(
            select(Adjudication, AdjudicationParticipation, ReviewUnit, ReviewSubject)
            .join(
                AdjudicationParticipation,
                AdjudicationParticipation.adjudication_id == Adjudication.id,
            )
            .join(ReviewUnit, ReviewUnit.id == Adjudication.review_unit_id)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(
                Adjudication.tenant_id == tenant_id,
                AdjudicationParticipation.adjudicator_id == principal.user.id,
                AdjudicationParticipation.status.in_(("pending", "submitted")),
                ReviewUnit.campaign_id == campaign.id,
                same_case_clause(anchor_subject),
            )
        ).all()
        prepared = []
        details = []
        for adjudication, participation, unit, subject in rows:
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
            if submitted_assignment is None:  # pragma: no cover - adjudication invariant
                continue
            candidates = list(
                session.scalars(
                    select(Candidate)
                    .where(Candidate.tenant_id == tenant_id, Candidate.review_unit_id == unit.id)
                    .order_by(Candidate.label)
                )
            )
            prepared.append((group, submitted_assignment, unit, subject, evidence))
            details.append(
                (adjudication, participation, group, unit, subject, evidence, candidates)
            )
        prepared.sort(key=lambda row: (row[0].order, row[2].created_at, str(row[2].id)))
        details.sort(key=lambda row: (row[2].order, row[3].created_at, str(row[3].id)))
        source_render, anchors, unavailable, _group_anchors, effective_offsets = (
            ReviewGroupedBundleMixin._build_source_render(
                session,
                tenant_id=tenant_id,
                prepared=prepared,
                source_snapshot_id=anchor_subject.source_snapshot_id,
                artifact_store=artifact_store,
            )
        )
        items_by_group: dict[str, list[AdjudicationWorkspaceItem]] = defaultdict(list)
        groups = {}
        case_title: str | None = None
        neutral_citation = reported_citation = None
        for adjudication, participation, group, unit, subject, evidence, candidates in details:
            candidate_a = next((item for item in candidates if item.label == "A"), None)
            value = (
                "No value extracted"
                if unit.extraction_state == "missing"
                else extracted_value(
                    candidate_a, fallback=subject.display_title, review_kind=unit.review_kind
                )[0]
            )
            if case_title is None and is_title_field(unit.field_name, unit.safe_field_label):
                case_title = value
            elif is_neutral_citation_field(unit.field_name, unit.safe_field_label):
                neutral_citation = value
            elif is_reported_citation_field(unit.field_name, unit.safe_field_label):
                reported_citation = value
            draft = None
            if participation.status == "pending":
                stored_draft = session.scalar(
                    select(AdjudicationDraft).where(
                        AdjudicationDraft.tenant_id == tenant_id,
                        AdjudicationDraft.adjudication_id == adjudication.id,
                        AdjudicationDraft.saved_by == principal.user.id,
                    )
                )
                draft = (
                    adjudication_draft_response(stored_draft) if stored_draft is not None else None
                )
            final = session.scalar(
                select(AdjudicationDecision).where(
                    AdjudicationDecision.tenant_id == tenant_id,
                    AdjudicationDecision.adjudication_id == adjudication.id,
                    AdjudicationDecision.decided_by == principal.user.id,
                )
            )
            groups[group.group_id] = group
            items_by_group[group.group_id].append(
                AdjudicationWorkspaceItem(
                    membership_version=participation.membership_version,
                    adjudication_id=adjudication.id,
                    review_unit_id=unit.id,
                    item_id=str(unit.id),
                    item_label=display_field_label(unit.field_name, unit.safe_field_label),
                    item_kind=item_kind(unit.review_kind),
                    extracted_value_display=value,
                    review_kind=unit.review_kind,
                    required_reviews=unit.required_reviews,
                    submitted_reviews=len(
                        ReviewAdjudicationGroupedMixin._grouped_submissions(
                            session, tenant_id=tenant_id, unit_id=unit.id
                        )
                    ),
                    source_anchor_id=anchors.get(unit.id),
                    source_anchor_unavailable_reason=unavailable.get(unit.id),
                    evidence_window_ids=[item.id for item in evidence],
                    assessment_targets=[
                        AdjudicationAssessmentTarget(
                            id=item.id, label=cast(Literal["A", "B"], item.label)
                        )
                        for item in candidates
                    ],
                    evidence_windows=[
                        evidence_response(
                            item, subject.attributes_json, effective_offsets=effective_offsets
                        )
                        for item in evidence
                    ],
                    submissions=ReviewAdjudicationGroupedMixin._grouped_submissions(
                        session, tenant_id=tenant_id, unit_id=unit.id
                    ),
                    draft=draft,
                    participation_status=cast(
                        Literal["pending", "submitted"], participation.status
                    ),
                    submitted_decision=(
                        adjudication_decision_response(
                            final,
                            review_unit_id=unit.id,
                            resolved=adjudication.status == "resolved",
                        )
                        if final is not None
                        else None
                    ),
                )
            )
        field_groups = [
            AdjudicationWorkspaceFieldGroup(
                group_id=group.group_id,
                group_label=group.group_label,
                group_kind=group.group_kind,
                description=group.description,
                order=group.order,
                items=items_by_group[group.group_id],
            )
            for group in sorted(groups.values(), key=lambda item: item.order)
        ]
        projections = ReviewAdjudicationCampaignMixin._adjudication_case_projections(
            session,
            tenant_id=tenant_id,
            campaign=campaign,
            adjudicator_id=principal.user.id,
        )
        case_id = adjudication_case_id(anchor_subject)
        case_projection = next(row.item for row in projections if row.item.case_id == case_id)
        result = AdjudicationCaseWorkspace(
            anchor_adjudication_id=anchor_adjudication.id,
            case_id=case_id,
            campaign=ReviewAdjudicationCampaignMixin._campaign_summary(campaign, projections),
            case=case_projection,
            case_header=ReviewerCaseHeader(
                subject_id=anchor_subject.id,
                subject_kind=anchor_subject.subject_kind,
                case_title=case_title or anchor_subject.display_title,
                case_identifier_display=anchor_subject.external_subject_id,
                neutral_citation_display=neutral_citation,
                reported_citation_display=reported_citation,
                source_system=anchor_subject.attributes_json.get("source_collection"),
                campaign_name=campaign.name,
            ),
            field_groups=field_groups,
            source_render=source_render,
            mode="edit" if any(row[1].status == "pending" for row in rows) else "read_only",
        )
        return result
