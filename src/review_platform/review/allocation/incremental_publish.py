"""Incremental allocation run publishing (reviewer-pool change handling).

Publishes a planned ``incremental`` allocation run: re-validates the source-snapshot digest,
then materializes the planned ``new``/``moved`` assignments as plain per-reviewer
assignments. Moved work releases the prior claim on the unit. Publishing is idempotent and
admin-only; the resulting assignments flow through the existing blinded reviewer queue."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.review.allocation.incremental_publication import (
    publish_incremental_assignments,
)
from review_platform.review.allocation.schemas import (
    IncrementalPolicyInput,
    IncrementalPublishResponse,
    counts_for_unit_pairs,
)
from review_platform.review.allocation.service_base import AllocationServiceBase
from review_platform.review.assignment_status import assignment_is_live
from review_platform.review.models import (
    AllocationRun,
    Assignment,
    IncrementalMovementPlan,
    ReviewUnit,
)


class AllocationIncrementalPublishMixin(AllocationServiceBase):
    """Admin-only publish of a planned incremental allocation run."""

    def publish_incremental_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal,
        idempotency_key: str,
        request_id: str,
    ) -> IncrementalPublishResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        campaign = self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status in {"paused", "closed"}:
            raise APIError(
                409,
                "campaign_not_publishable",
                "Campaign not publishable",
                "The campaign status does not permit publishing assignments.",
            )
        operation = f"allocation.incremental.publish.{run_id}"
        request_digest = digest_json({"run_id": str(run_id)})
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            return IncrementalPublishResponse.model_validate(record.response_json).model_copy(
                update={"replayed": True}
            )
        run = self._load_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            for_update=True,
        )
        if run.allocation_mode != "incremental":
            raise APIError(
                409,
                "not_an_incremental_run",
                "Not an incremental run",
                "Use the standard publish endpoint for initial allocation runs.",
            )
        if run.status != "planned":
            raise APIError(
                409,
                "allocation_run_not_publishable",
                "Allocation run not publishable",
                "Only a planned allocation run can be published.",
            )
        body = IncrementalPolicyInput.model_validate(run.input_parameters_json)
        units = self._eligible_units(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            subject_kind=body.subject_kind,
            review_kind=body.review_kind,
        )
        if self._snapshot_digest(units) != run.source_snapshot_digest:
            raise APIError(
                409,
                "blocked_by_snapshot_drift",
                "Blocked by snapshot drift",
                "The candidate subject pool changed since this incremental run was planned.",
            )
        new_pairs, moved_pairs = self._publish_incremental_assignments(
            session, tenant_id=tenant_id, run=run
        )
        new_count = len(new_pairs)
        moved_count = len(moved_pairs)
        case_by_unit = self._case_keys_for_units(
            session,
            tenant_id=tenant_id,
            unit_ids={unit_id for _, unit_id in new_pairs + moved_pairs},
        )
        revoked_reviewer_ids = self._revoked_reviewer_ids(
            session, tenant_id=tenant_id, campaign_id=campaign_id, run_id=run.id
        )
        run.status = "published"
        run.published_by = principal.user.id
        run.published_at = now_utc()
        run.lock_version += 1
        response = IncrementalPublishResponse(
            run_id=run.id,
            status="published",
            published_assignment_count=new_count + moved_count,
            new_assignment_count=new_count,
            moved_assignment_count=moved_count,
            new_assignment_counts=counts_for_unit_pairs(new_pairs, case_by_unit),
            moved_assignment_counts=counts_for_unit_pairs(moved_pairs, case_by_unit),
            revoked_reviewer_ids=revoked_reviewer_ids,
            published_at=run.published_at,
        )
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="allocation.incremental_run_published",
            object_type="allocation_run",
            object_id=str(run.id),
            request_id=request_id,
            payload={
                "campaign_id": str(campaign_id),
                "new_assignment_count": new_count,
                "moved_assignment_count": moved_count,
                "revoked_reviewer_ids": [str(rid) for rid in revoked_reviewer_ids],
            },
            key=self.audit_key,
        )
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
            response=response.model_dump(mode="json"),
        )
        return response

    def _publish_incremental_assignments(
        self, session: Session, *, tenant_id: uuid.UUID, run: AllocationRun
    ) -> tuple[list[tuple[uuid.UUID, uuid.UUID]], list[tuple[uuid.UUID, uuid.UUID]]]:
        """Publish planned incremental assignment entries.

        Returns the ``(reviewer_id, review_unit_id)`` pairs actually published as new and as moved.
        Their lengths are the ``new_assignment_count``/``moved_assignment_count`` this has always
        reported -- the pairs are collected at exactly the sites that used to increment those
        counters -- and carrying the identities lets the caller also report the same movements as
        ``(case, reviewer)`` pairs.
        """
        return publish_incremental_assignments(session, tenant_id=tenant_id, run_id=run.id)

    @staticmethod
    def _revoked_reviewer_ids(
        session: Session, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID, run_id: uuid.UUID
    ) -> list[uuid.UUID]:
        """Reviewers this run released work from who now hold zero live assignments here.

        Read after ``_publish_incremental_assignments`` has applied its releases, so this reflects
        the real post-publish state rather than trusting the plan alone. Drives the "N reviewer(s)
        lost access" summary in the publish response/UI.
        """
        moved_from = list(
            session.scalars(
                select(IncrementalMovementPlan.from_reviewer_id)
                .where(
                    IncrementalMovementPlan.tenant_id == tenant_id,
                    IncrementalMovementPlan.allocation_run_id == run_id,
                    IncrementalMovementPlan.movement_kind == "moved",
                    IncrementalMovementPlan.from_reviewer_id.is_not(None),
                )
                .distinct()
            )
        )
        if not moved_from:
            return []
        still_live = set(
            session.scalars(
                select(Assignment.reviewer_id.distinct())
                .join(
                    ReviewUnit,
                    (ReviewUnit.tenant_id == Assignment.tenant_id)
                    & (ReviewUnit.id == Assignment.review_unit_id),
                )
                .where(
                    Assignment.tenant_id == tenant_id,
                    ReviewUnit.campaign_id == campaign_id,
                    Assignment.reviewer_id.in_(moved_from),
                    assignment_is_live(),
                )
            )
        )
        return sorted(
            (rid for rid in moved_from if rid is not None and rid not in still_live), key=str
        )
