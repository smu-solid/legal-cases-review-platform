"""Reviewer campaign visibility and queue identity helpers."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.base import ReviewServiceBase
from review_platform.review.grouping import GROUP_DEFINITIONS
from review_platform.review.models import (
    Assignment,
    Campaign,
    ReviewSubject,
    ReviewUnit,
)

_ALL_GROUP_IDS: tuple[str, ...] = tuple(definition.group_id for definition in GROUP_DEFINITIONS)


class ReviewerQueueIdentityMixin(ReviewServiceBase):
    def _reviewer_campaign_ids(
        self, session: Session, *, tenant_id: uuid.UUID, reviewer_id: uuid.UUID
    ) -> set[uuid.UUID]:
        """Campaigns this reviewer may see.

        A campaign with a curated reviewer roster (``policy_json.selected_reviewer_ids``
        non-empty     -- set via the campaign reviewer add/remove endpoints while
        active) is restricted to     that roster. A campaign with no curated roster
        stays open to every active reviewer in the     tenant -- this is the deliberate
        "immediately reviewable" behaviour for a synthetic/real     import published
        without going through reviewer selection (see
        ``ReviewImportMixin.import_synthetic``'s docstring). Either way, a reviewer who
        already     holds an assignment in a campaign always sees it, independent of the
        current roster (a     published allocation run assigns units directly, and
        roster changes must never orphan     existing work from view).

        ``closed`` and ``pool`` are excluded from the no-roster fallback: a closed campaign
        has been     deliberately ended and a ``pool`` campaign is the internal
        preloaded-case holding area,     never a browsable campaign in its own right
        (see ``campaign_availability_contract.md``) --     neither should become
        reviewer-visible just because it happens to lack a curated roster.

        A ``released`` assignment means the reviewer no longer owns that unit (incremental
        publish     moved it to someone else, or the reviewer released it directly) --
        it must not count toward     "already holding an assignment there", or a removed
        reviewer with no other roster ties would     stay permanently visible via a
        stale released row. ``claimed``/``submitted``/     ``revision_requested`` are
        current ownership and still grant visibility."""

        rows = session.execute(
            select(Campaign.id, Campaign.policy_json).where(
                Campaign.tenant_id == tenant_id,
                Campaign.status.not_in(("draft", "closed", "pool")),
            )
        ).all()
        reviewer_key = str(reviewer_id)
        visible = set()
        for row in rows:
            roster = (row.policy_json or {}).get("selected_reviewer_ids") or []
            if not roster or reviewer_key in roster:
                visible.add(row.id)
        assigned = set(
            session.scalars(
                select(ReviewUnit.campaign_id.distinct())
                .join(
                    Assignment,
                    (Assignment.tenant_id == ReviewUnit.tenant_id)
                    & (Assignment.review_unit_id == ReviewUnit.id),
                )
                .where(
                    Assignment.tenant_id == tenant_id,
                    Assignment.reviewer_id == reviewer_id,
                    assignment_is_live(),
                )
            )
        )
        return visible | assigned


def _selected_group_ids(campaign: Campaign) -> list[str]:
    """The campaign's review-scope field groups, or every group when unrestricted."""

    group_ids = (campaign.review_scope_json or {}).get("group_ids") or []
    return list(group_ids) if group_ids else list(_ALL_GROUP_IDS)


def _case_id(subject: ReviewSubject) -> str:
    """Real case identity for a review unit's per-field subject (see ``ReviewQueueItem.case_id``).

    Falls back to the subject's own id only for the defensive case of data missing the case-id
    attribute (should not happen for imported data; matches the same fallback in ``case_queue`` and
    ``grouped_bundle.py``).
    """

    return subject.attributes_json.get("snapshot_local_case_external_id") or str(subject.id)


def _keyset(after: dict[str, object]) -> tuple[datetime, uuid.UUID]:
    """Decode the available-queue keyset payload, failing closed on a malformed cursor."""

    try:
        created_at = datetime.fromisoformat(str(after["created_at"]))
        unit_id = uuid.UUID(str(after["id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise APIError(422, "cursor_invalid", "Invalid cursor", "The cursor is invalid.") from exc
    return created_at, unit_id
