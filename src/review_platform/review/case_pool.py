"""Eligible case pool and protected campaign ownership."""

from __future__ import annotations

import uuid

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from review_platform.common.json import digest_json
from review_platform.review.models import (
    AllocationRun,
    AnnotationRevision,
    Assignment,
    Campaign,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.proposal_scope import campaign_has_proposals
from review_platform.review.subject_attributes import subject_attribute as _subject_attr

POOL_CAMPAIGN_KEY = "case_pool"
POOL_CAMPAIGN_NAME = "Case pool (preloaded)"


def get_or_create_pool_campaign(
    session: Session, *, tenant_id: uuid.UUID, created_by: uuid.UUID
) -> Campaign:
    """Return the tenant's single reserved pool campaign, creating it if this is the first
    preload.

    Never reviewable directly: ``status='pool'`` is excluded from every
    campaign-listing/allocation/ reviewer-queue path (it is not one of
    ``ReviewCampaignLifecycleMixin``'s editable/publishable statuses, and
    campaign-progress/reviewer-queue listings filter it out explicitly)."""

    campaign = session.scalar(
        select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.key == POOL_CAMPAIGN_KEY)
    )
    if campaign is not None:
        return campaign
    campaign = Campaign(
        tenant_id=tenant_id,
        key=POOL_CAMPAIGN_KEY,
        name=POOL_CAMPAIGN_NAME,
        status="pool",
        policy_version="case-pool-v1",
        # minimum_reviews_per_case is never read for the pool campaign itself (it has no reviewers
        # or assignments); each real campaign created from the pool sets its own value at creation.
        policy_json={"minimum_reviews_per_case": 2, "case_pool": True},
        review_scope_json=None,
        manifest_digest=digest_json({"case_pool": True}),
        created_by=created_by,
    )
    session.add(campaign)
    session.flush()
    return campaign


def return_units_to_pool(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    created_by: uuid.UUID,
) -> tuple[int, int]:
    """Return ``campaign``'s review units to the tenant's pool campaign.

    Only campaigns without saved/submitted/revision work may use this path. Untouched
    assignments are deleted first and the original units are re-pointed, preserving
    every candidate and evidence child keyed by unit id. The pool campaign is created on
    first use if needed. Returns ``(cases_freed, units_freed)``; a no-op ``(0, 0)`` when
    the campaign owns no units."""

    if campaign_has_started_work(session, tenant_id=tenant_id, campaign_id=campaign.id):
        raise ValueError("campaign review work cannot be returned to the pool")

    units_freed = (
        session.scalar(
            select(func.count())
            .select_from(ReviewUnit)
            .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign.id)
        )
        or 0
    )
    if not units_freed:
        return 0, 0
    case_id_col = _subject_attr("snapshot_local_case_external_id")
    cases_freed = (
        session.scalar(
            select(func.count(func.distinct(case_id_col)))
            .select_from(ReviewSubject)
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == ReviewSubject.tenant_id)
                & (ReviewUnit.review_subject_id == ReviewSubject.id),
            )
            .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign.id)
        )
        or 0
    )
    pool = get_or_create_pool_campaign(session, tenant_id=tenant_id, created_by=created_by)

    campaign_unit_ids = select(ReviewUnit.id).where(
        ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign.id
    )
    # A published/allocated campaign owns allocation runs whose ``assignment_plans`` reference its
    # assignments via an ON DELETE SET NULL composite ``(tenant_id, assignment_id)`` FK. Deleting
    # the assignments while those plans still point at them would try to null the NOT NULL
    # ``tenant_id`` and raise. Delete the campaign's allocation runs first; ``assignment_plans``
    # (and the other run children) cascade-delete from ``allocation_runs``, so the assignment delete
    # below has no plan rows referencing it and the units can then re-enter the pool cleanly.
    session.execute(
        delete(AllocationRun)
        .where(AllocationRun.tenant_id == tenant_id, AllocationRun.campaign_id == campaign.id)
        .execution_options(synchronize_session=False)
    )
    session.execute(
        delete(Assignment)
        .where(
            Assignment.tenant_id == tenant_id,
            Assignment.review_unit_id.in_(campaign_unit_ids),
        )
        .execution_options(synchronize_session=False)
    )
    # Re-point the units into the pool and reset their status to ``pending``. A unit that lives in
    # the pool must be ``pending`` by invariant: the allocation eligibility query treats any subject
    # holding a unit in ``in_adjudication``/``resolved`` as blocked, so a unit returned with an
    # advanced status would silently make its whole case ineligible for a future campaign. This path
    # only ever returns campaigns without started work (units are already ``pending``), so the reset
    # is a no-op today, but it keeps the invariant explicit and correct for any future return path.
    session.execute(
        update(ReviewUnit)
        .where(
            ReviewUnit.tenant_id == tenant_id,
            ReviewUnit.campaign_id == campaign.id,
        )
        .values(campaign_id=pool.id, status="pending", lock_version=ReviewUnit.lock_version + 1)
        .execution_options(synchronize_session=False)
    )
    return cases_freed, units_freed


def campaign_has_started_work(
    session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID
) -> bool:
    """Lock campaign assignments, then detect reviewer-authored or submitted state.

    The assignment locks are held until transaction end. Reviewer draft/submission writes take the
    same row lock before inserting a child revision, so a concurrent delete either observes the
    committed work and refuses or deletes first and makes the writer fail without persisting. This
    closes the work-check/assignment-delete window where a cascading delete could otherwise erase a
    just-created answer or annotation.
    """

    assignments = list(
        session.execute(
            select(Assignment.id, Assignment.status)
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .where(
                Assignment.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign_id,
            )
            .with_for_update(of=Assignment)
        )
    )
    if any(status in {"submitted", "revision_requested"} for _assignment_id, status in assignments):
        return True
    if campaign_has_proposals(session, tenant_id, campaign_id):
        return True
    if not assignments:
        return False
    return bool(
        session.scalar(
            select(ReviewItemAnswer.id)
            .join(
                Assignment,
                (Assignment.tenant_id == ReviewItemAnswer.tenant_id)
                & (Assignment.id == ReviewItemAnswer.assignment_id),
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .where(
                ReviewItemAnswer.tenant_id == tenant_id,
                Assignment.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign_id,
            )
            .limit(1)
        )
        or session.scalar(
            select(AnnotationRevision.id)
            .join(
                Assignment,
                (Assignment.tenant_id == AnnotationRevision.tenant_id)
                & (Assignment.id == AnnotationRevision.assignment_id),
            )
            .join(
                ReviewUnit,
                (ReviewUnit.tenant_id == Assignment.tenant_id)
                & (ReviewUnit.id == Assignment.review_unit_id),
            )
            .where(
                AnnotationRevision.tenant_id == tenant_id,
                Assignment.tenant_id == tenant_id,
                ReviewUnit.campaign_id == campaign_id,
            )
            .limit(1)
        )
    )


def count_pool_cases_by_source(session: Session, *, tenant_id: uuid.UUID) -> dict[str, int]:
    """Distinct real-world cases currently sitting in the tenant's pool, keyed by source system."""

    pool = session.scalar(
        select(Campaign).where(Campaign.tenant_id == tenant_id, Campaign.key == POOL_CAMPAIGN_KEY)
    )
    if pool is None:
        return {}
    case_id_col = _subject_attr("snapshot_local_case_external_id")
    source_col = _subject_attr("source_collection")
    rows = session.execute(
        select(source_col, func.count(func.distinct(case_id_col)))
        .select_from(ReviewUnit)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == pool.id)
        .group_by(source_col)
    )
    return {source: count for source, count in rows if source is not None}
