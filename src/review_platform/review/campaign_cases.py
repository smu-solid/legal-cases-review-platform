"""Split out of ``review_platform.review.campaign_lifecycle`` to keep that file under the
repository's production-file size guardrail."""

from __future__ import annotations

import uuid

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.errors import APIError
from review_platform.common.pagination import decode_cursor, encode_cursor
from review_platform.review.assignment_status import count_live
from review_platform.review.base import ReviewServiceBase
from review_platform.review.grouping import classify_unit
from review_platform.review.models import Assignment, CaseSubmission, ReviewSubject, ReviewUnit
from review_platform.review.schemas import CampaignCaseProgressItem, CampaignCaseProgressPage

_CASE_ID_COL = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext


class ReviewCampaignCasesMixin(ReviewServiceBase):
    def campaign_cases(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        limit: int,
        cursor: str | None,
    ) -> CampaignCaseProgressPage:
        """Paginated per-case progress table for a campaign's detail view (large campaigns).

        One row per distinct case (grouped by ``snapshot_local_case_external_id``), aggregating
        across every ``ReviewSubject``/``ReviewUnit`` that belongs to that case -- never one row
        per review unit.
        """

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        stmt = (
            select(
                _CASE_ID_COL.label("case_id"),
                func.min(ReviewSubject.display_title).label("display_title"),
                func.array_agg(ReviewUnit.review_kind.distinct()).label("review_kinds"),
                func.array_agg(ReviewUnit.review_kind).label("unit_review_kinds"),
                func.array_agg(ReviewUnit.safe_field_label).label("unit_safe_field_labels"),
                func.count(ReviewUnit.id.distinct()).label("unit_count"),
                count_live(Assignment.id).label("assignment_count"),
                func.count(case((Assignment.status == "submitted", Assignment.id))).label(
                    "submitted_count"
                ),
                func.count(case((ReviewUnit.status == "resolved", ReviewUnit.id)).distinct()).label(
                    "resolved_count"
                ),
                count_live(Assignment.reviewer_id, distinct=True).label("reviewers_assigned_count"),
                # A correlated subquery, not a join: CaseSubmission has no ReviewUnit/ReviewSubject
                # row to join through (it is keyed directly by case_id/campaign_id/reviewer_id, see
                # that model's docstring). Every ReviewSubject row folded into one case-id group
                # shares the same case_id, so the subquery's result is identical for every row in
                # the group -- wrapped in MAX (not a real aggregation) only so it type-checks
                # alongside the other GROUP BY aggregates.
                func.max(
                    select(func.count(CaseSubmission.id))
                    .where(
                        CaseSubmission.tenant_id == tenant_id,
                        CaseSubmission.campaign_id == campaign_id,
                        CaseSubmission.case_id == _CASE_ID_COL,
                    )
                    .correlate(ReviewSubject)
                    .scalar_subquery()
                ).label("reviewers_completed_count"),
            )
            .select_from(ReviewSubject)
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
                & (ReviewUnit.review_subject_id == ReviewSubject.id),
            )
            .outerjoin(
                Assignment,
                (Assignment.tenant_id == ReviewUnit.tenant_id)
                & (Assignment.review_unit_id == ReviewUnit.id),
            )
            .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign_id)
            .group_by(_CASE_ID_COL)
            .order_by(_CASE_ID_COL)
            .limit(limit + 1)
        )
        after = decode_cursor(cursor)
        if after is not None:
            stmt = stmt.having(_case_keyset(after) < _CASE_ID_COL)
        rows = session.execute(stmt).all()
        has_more = len(rows) > limit
        page = rows[:limit]
        items = [
            CampaignCaseProgressItem(
                case_id=row.case_id,
                display_title=row.display_title,
                review_kinds=sorted(row.review_kinds),
                field_group_labels=_field_group_labels(
                    row.unit_review_kinds, row.unit_safe_field_labels
                ),
                unit_count=row.unit_count,
                assignment_count=row.assignment_count,
                submitted_count=row.submitted_count,
                resolved_count=row.resolved_count,
                reviewers_assigned_count=row.reviewers_assigned_count,
                reviewers_completed_count=row.reviewers_completed_count,
            )
            for row in page
        ]
        next_cursor: str | None = None
        if has_more:
            next_cursor = encode_cursor({"case_id": page[-1].case_id})
        return CampaignCaseProgressPage(
            campaign_id=campaign_id, items=items, next_cursor=next_cursor, has_more=has_more
        )


def _field_group_labels(review_kinds: list[str], safe_field_labels: list[str]) -> list[str]:
    """Distinct, display-safe field-group labels for a case, ordered by the group allowlist.

    Classification is per unit (``review_kind`` + ``safe_field_label``), not per raw
    ``review_kind`` alone -- ``metadata_field`` units span several groups (case metadata,
    citations, court/hearing, parties) depending on which field they carry, so grouping by
    ``review_kind`` alone would merge unrelated fields into one bucket.
    """

    groups = {
        classify_unit(review_kind, safe_field_label)
        for review_kind, safe_field_label in zip(review_kinds, safe_field_labels, strict=True)
    }
    return [group.group_label for group in sorted(groups, key=lambda group: group.order)]


def _case_keyset(after: dict[str, object]) -> str:
    """Decode the campaign-cases keyset payload, failing closed on a malformed cursor."""

    try:
        return str(after["case_id"])
    except (KeyError, TypeError) as exc:
        raise APIError(422, "cursor_invalid", "Invalid cursor", "The cursor is invalid.") from exc
