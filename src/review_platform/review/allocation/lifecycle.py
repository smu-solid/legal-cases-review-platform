"""Allocation run lifecycle: publish (with drift/pool guards) and discard."""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.review.allocation.publication import publish_initial_assignments
from review_platform.review.allocation.schemas import (
    AllocationDiscardResponse,
    AllocationPolicyInput,
    AllocationPublishResponse,
)
from review_platform.review.allocation.service_base import AllocationServiceBase
from review_platform.review.models import AllocationRun

PUBLISHED_ASSIGNMENT_LEASE = timedelta(days=365)


class AllocationLifecycleMixin(AllocationServiceBase):
    def publish_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal,
        idempotency_key: str,
        request_id: str,
    ) -> AllocationPublishResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        campaign = self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        operation = f"allocation.publish.{run_id}"
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
            return AllocationPublishResponse.model_validate(record.response_json).model_copy(
                update={"replayed": True}
            )
        run = self._load_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            for_update=True,
        )
        if run.status != "planned":
            raise APIError(
                409,
                "allocation_run_not_publishable",
                "Allocation run not publishable",
                "Only a planned allocation run can be published.",
            )
        if campaign.status in {"paused", "closed"}:
            raise APIError(
                409,
                "campaign_not_publishable",
                "Campaign not publishable",
                "The campaign status does not permit publishing assignments.",
            )
        self._guard_snapshot_and_pool(session, tenant_id=tenant_id, run=run)
        created = self._publish_assignments(session, tenant_id=tenant_id, run=run)
        run.status = "published"
        run.published_by = principal.user.id
        run.published_at = now_utc()
        run.lock_version += 1
        campaign.status = "published"
        campaign.lock_version += 1
        # ``review_units`` is the same number the old ``select(count())`` returned -- one row per
        # planned ``(review unit, reviewer)`` pair -- so this replaces that query rather than adding
        # one, and additionally yields the case-level pair count the pre-publish panel quotes.
        published_counts = self._run_assignment_counts(session, tenant_id=tenant_id, run_id=run.id)
        response = AllocationPublishResponse(
            run_id=run.id,
            status="published",
            published_assignment_count=published_counts.review_units,
            created_assignment_count=created,
            published_assignment_counts=published_counts,
            published_at=run.published_at,
        )
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="allocation.run_published",
            object_type="allocation_run",
            object_id=str(run.id),
            request_id=request_id,
            payload={
                "campaign_id": str(campaign_id),
                "published_assignment_count": response.published_assignment_count,
                "created_assignment_count": created,
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

    def _guard_snapshot_and_pool(
        self, session: Session, *, tenant_id: uuid.UUID, run: AllocationRun
    ) -> None:
        body = AllocationPolicyInput.model_validate(run.input_parameters_json)
        units = self._eligible_units(
            session,
            tenant_id=tenant_id,
            campaign_id=run.campaign_id,
            subject_kind=body.subject_kind,
            review_kind=body.review_kind,
        )
        if self._snapshot_digest(units) != run.source_snapshot_digest:
            raise APIError(
                409,
                "blocked_by_snapshot_drift",
                "Blocked by snapshot drift",
                "The candidate subject pool changed since this run was planned.",
            )
        reviewers = self._reviewer_inputs(
            session, tenant_id=tenant_id, reviewer_ids=body.reviewer_ids
        )
        if any(not (reviewer.active and reviewer.authorized) for reviewer in reviewers):
            raise APIError(
                409,
                "blocked_by_reviewer_pool",
                "Blocked by reviewer pool",
                "A reviewer in the planned pool is no longer active or authorized.",
            )

    @staticmethod
    def _publish_assignments(session: Session, *, tenant_id: uuid.UUID, run: AllocationRun) -> int:
        return publish_initial_assignments(
            session,
            tenant_id=tenant_id,
            run_id=run.id,
            lease_expires_at=now_utc() + PUBLISHED_ASSIGNMENT_LEASE,
        )

    def discard_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        run_id: uuid.UUID,
        principal: Principal,
        idempotency_key: str,
        request_id: str,
    ) -> AllocationDiscardResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        operation = f"allocation.discard.{run_id}"
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
            return AllocationDiscardResponse.model_validate(record.response_json).model_copy(
                update={"replayed": True}
            )
        run = self._load_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=run_id,
            for_update=True,
        )
        if run.status == "published":
            raise APIError(
                409,
                "allocation_run_published",
                "Allocation run published",
                "A published allocation run cannot be discarded.",
            )
        if run.status != "planned":
            raise APIError(
                409,
                "allocation_run_not_discardable",
                "Allocation run not discardable",
                "Only a planned allocation run can be discarded.",
            )
        run.status = "discarded"
        run.lock_version += 1
        session.execute(
            text(
                "UPDATE review_platform.assignment_plans SET status='cancelled' "
                "WHERE tenant_id=:tenant_id AND allocation_run_id=:run_id AND status='planned'"
            ),
            {"tenant_id": str(tenant_id), "run_id": str(run_id)},
        )
        response = AllocationDiscardResponse(run_id=run.id, status="discarded")
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="allocation.run_discarded",
            object_type="allocation_run",
            object_id=str(run.id),
            request_id=request_id,
            payload={"campaign_id": str(campaign_id)},
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
