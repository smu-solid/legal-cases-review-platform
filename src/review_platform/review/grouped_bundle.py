"""Case-scoped, campaign-scoped, group-based reviewer workspace bundle
(reviewer-grouping-bundle/v1).

Grouped by the reviewed case, not by the anchor unit's own subject: each field/relation of a
case is persisted as its own ``ReviewSubject``/``ReviewUnit`` (one item per row), tagged
with the case's own external id in ``attributes_json["snapshot_local_case_external_id"]``
(see ``review_platform.review.campaign_conflicts``). This bundle aggregates every review
unit the calling reviewer owns that shares that case id *and* the anchor's campaign --
campaign scoping matters here because the same case can be reviewed under different field
selections in more than one active campaign at once (``campaign_conflicts`` prevents the
same case+field-group from being open in two campaigns simultaneously, but different
field-groups of the same case legitimately are)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.base import ReviewServiceBase
from review_platform.review.grouped_items import GroupedItemsMixin, _PreparedRow
from review_platform.review.grouped_source import GroupedSourceMixin
from review_platform.review.grouping import (
    GroupDefinition,
    classify_unit,
)
from review_platform.review.models import (
    Assignment,
    Campaign,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.proposal_projection import attach_proposals
from review_platform.review.reviewer_provenance_context import attach_context
from review_platform.review.schemas import (
    GroupedProgress,
    ReviewerCaseHeader,
    ReviewerGroupingBundle,
)


class ReviewGroupedBundleMixin(GroupedItemsMixin, GroupedSourceMixin, ReviewServiceBase):
    @staticmethod
    def _scope_allows(campaign: Campaign | None, group: GroupDefinition, unit: ReviewUnit) -> bool:
        if campaign is None or not campaign.review_scope_json:
            return True
        group_ids = set(campaign.review_scope_json.get("group_ids") or [])
        review_kinds = set(campaign.review_scope_json.get("review_kinds") or [])
        return (not group_ids or group.group_id in group_ids) and (
            not review_kinds or unit.review_kind in review_kinds
        )

    def grouped_bundle(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
        artifact_store: ArtifactStore | None = None,
    ) -> ReviewerGroupingBundle:
        """Case-scoped, campaign-scoped, group-based presentation of a reviewer's owned units.

        Only *live* assignments are owned work. A ``released`` row is the audit trace of a unit an
        incremental rebalance moved to another reviewer, so it is neither a valid anchor (404) nor
        a field of the case: rendering them put units the reviewer no longer holds into her
        workspace, where every write answered 409 and the case could never be submitted."""

        self._require_role(session, principal, tenant_id, "reviewer")
        self._set_tenant_scope(session, tenant_id)
        anchor_assignment = session.scalar(
            select(Assignment).where(
                Assignment.tenant_id == tenant_id,
                Assignment.id == assignment_id,
                Assignment.reviewer_id == principal.user.id,
                assignment_is_live(),
            )
        )
        if anchor_assignment is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        anchor_unit = session.scalar(
            select(ReviewUnit).where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.id == anchor_assignment.review_unit_id,
            )
        )
        if anchor_unit is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        subject = session.scalar(
            select(ReviewSubject).where(
                ReviewSubject.tenant_id == tenant_id,
                ReviewSubject.id == anchor_unit.review_subject_id,
            )
        )
        if subject is None:  # pragma: no cover - composite FK invariant
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        campaign = session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id,
                Campaign.id == anchor_unit.campaign_id,
            )
        )
        case_id = subject.attributes_json.get("snapshot_local_case_external_id")
        owned_query = (
            select(Assignment, ReviewUnit, ReviewSubject)
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .join(
                ReviewSubject,
                (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                & (ReviewSubject.id == ReviewUnit.review_subject_id),
            )
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.reviewer_id == principal.user.id,
                ReviewUnit.campaign_id == anchor_unit.campaign_id,
                assignment_is_live(),
            )
        )
        if case_id is not None:
            owned_query = owned_query.where(
                ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext == case_id
            )
        else:  # pragma: no cover - defensive: unexpected data missing the case id
            owned_query = owned_query.where(ReviewUnit.review_subject_id == subject.id)
        owned_rows = session.execute(owned_query).all()
        # Order by allowlisted group order, then stable creation order within a group.
        prepared: list[_PreparedRow] = []
        for assignment, unit, unit_subject in owned_rows:
            group = classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name)
            if not self._scope_allows(campaign, group, unit):
                continue
            evidence = list(
                session.scalars(
                    select(EvidenceWindow)
                    .where(
                        EvidenceWindow.tenant_id == tenant_id,
                        EvidenceWindow.review_unit_id == unit.id,
                    )
                    .order_by(EvidenceWindow.ordinal)
                )
            )
            prepared.append((group, assignment, unit, unit_subject, evidence))
        prepared.sort(key=lambda row: (row[0].order, row[2].created_at, str(row[2].id)))

        (
            source_render,
            item_anchor_by_unit,
            anchor_unavailable_by_unit,
            group_anchor_by_id,
            effective_offsets,
        ) = self._build_source_render(
            session,
            tenant_id=tenant_id,
            prepared=prepared,
            source_snapshot_id=subject.source_snapshot_id,
            artifact_store=artifact_store,
        )
        (
            items_by_group,
            neutral_citation_display,
            reported_citation_display,
            case_title,
        ) = self._build_group_items(
            session,
            tenant_id=tenant_id,
            prepared=prepared,
            item_anchor_by_unit=item_anchor_by_unit,
            anchor_unavailable_by_unit=anchor_unavailable_by_unit,
            effective_offsets=effective_offsets,
            fallback_title=subject.display_title,
        )
        field_groups, group_progress = self._assemble_field_groups(
            items_by_group, group_anchor_by_id
        )
        total_items = sum(group.item_count for group in field_groups)
        completed_items = sum(group.completed_count for group in field_groups)
        editable = any(
            item.status != "submitted" for items in items_by_group.values() for item in items
        )
        result = ReviewerGroupingBundle(
            case_header=ReviewerCaseHeader(
                subject_id=subject.id,
                subject_kind=subject.subject_kind,
                case_title=case_title,
                case_identifier_display=subject.external_subject_id,
                neutral_citation_display=neutral_citation_display,
                reported_citation_display=reported_citation_display,
                source_system=subject.attributes_json.get("source_collection"),
                campaign_name=campaign.name if campaign is not None else None,
            ),
            field_groups=field_groups,
            source_render=source_render,
            progress=GroupedProgress(
                total_items=total_items,
                completed_items=completed_items,
                remaining_items=total_items - completed_items,
                group_progress=group_progress,
            ),
            allowed_actions=["save_draft", "submit"] if editable else [],
            lock_version=anchor_assignment.lock_version,
        )

        result = attach_proposals(
            result,
            session,
            tenant_id=tenant_id,
            campaign_id=anchor_unit.campaign_id,
            case_id=str(case_id or subject.id),
            reviewer_id=principal.user.id,
            campaign_open=campaign is not None and campaign.status == "published",
        )
        attach_context(result, session, tenant_id, prepared, artifact_store)
        return result
