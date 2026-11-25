"""Set-based allocation-run counts shared by publish responses."""

from __future__ import annotations

import uuid

from sqlalchemy import String, cast, func, literal, select
from sqlalchemy.orm import Session

from review_platform.review.allocation.schemas import AssignmentCountsOut
from review_platform.review.models import AssignmentPlan, ReviewSubject, ReviewUnit


def run_assignment_counts(
    session: Session, *, tenant_id: uuid.UUID, run_id: uuid.UUID
) -> AssignmentCountsOut:
    """Count review-unit assignments and distinct case/reviewer pairs without loading plan rows."""

    case_id = ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
    fallback_case_id = literal("subject:") + func.coalesce(
        ReviewSubject.external_subject_id, cast(ReviewSubject.id, String)
    )
    case_key = func.coalesce(func.nullif(case_id, ""), fallback_case_id)
    case_reviewer_pairs = (
        select(AssignmentPlan.reviewer_id, case_key.label("case_key"))
        .select_from(AssignmentPlan)
        .join(
            ReviewUnit,
            (ReviewUnit.tenant_id == AssignmentPlan.tenant_id)
            & (ReviewUnit.id == AssignmentPlan.review_unit_id),
        )
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(
            AssignmentPlan.tenant_id == tenant_id,
            AssignmentPlan.allocation_run_id == run_id,
        )
        .distinct()
        .subquery()
    )
    review_units = (
        select(func.count())
        .select_from(AssignmentPlan)
        .where(
            AssignmentPlan.tenant_id == tenant_id,
            AssignmentPlan.allocation_run_id == run_id,
        )
        .scalar_subquery()
    )
    cases = select(func.count()).select_from(case_reviewer_pairs).scalar_subquery()
    case_count, review_unit_count = session.execute(select(cases, review_units)).one()
    return AssignmentCountsOut(cases=case_count, review_units=review_unit_count)
