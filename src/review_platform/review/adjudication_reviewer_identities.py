"""Adjudicator-authorized reviewer identity projections."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.db.models import User
from review_platform.review.models import Assignment
from review_platform.review.schemas import AdjudicationReviewerIdentity


def pending_reviewer_identities_by_unit(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    review_unit_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[AdjudicationReviewerIdentity]]:
    pending: dict[uuid.UUID, list[AdjudicationReviewerIdentity]] = defaultdict(list)
    for review_unit_id, display_name, email in session.execute(
        select(Assignment.review_unit_id, User.display_name, User.email_normalized)
        .join(User, User.id == Assignment.reviewer_id)
        .where(
            Assignment.tenant_id == tenant_id,
            Assignment.review_unit_id.in_(review_unit_ids),
            Assignment.status.in_(("claimed", "revision_requested")),
        )
        .order_by(User.display_name, User.email_normalized, Assignment.id)
    ):
        pending[review_unit_id].append(
            AdjudicationReviewerIdentity(display_name=display_name or None, email=email)
        )
    return dict(pending)
