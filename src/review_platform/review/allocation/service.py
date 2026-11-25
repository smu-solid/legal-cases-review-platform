"""Admin-only orchestration for reviewer allocation runs.

``AllocationService`` wraps the pure :class:`AllocationPlanner` with review-owned
persistence, authorization, idempotency, audit, and a source-snapshot drift guard. It
composes three operation mixins over
:class:`review_platform.review.allocation.service_base.AllocationServiceBase`: planning and
run persistence (:mod:`review_platform.review.allocation.planning`), run lifecycle
(:mod:`review_platform.review.allocation.lifecycle`), read-only run views
(:mod:`review_platform.review.allocation.queries`), and incremental reviewer-pool change
handling (:mod:`review_platform.review.allocation.incremental`).

Reviewer blindness is preserved structurally: overlap-group keys, pairwise/all-reviewer
markers, and peer reviewer identities live only on admin-facing run/matrix payloads.
Publishing creates plain per-reviewer assignments that flow through the existing blinded
reviewer queue."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.review.allocation.incremental import AllocationIncrementalMixin
from review_platform.review.allocation.incremental_publish import (
    AllocationIncrementalPublishMixin,
)
from review_platform.review.allocation.lifecycle import (
    PUBLISHED_ASSIGNMENT_LEASE,
    AllocationLifecycleMixin,
)
from review_platform.review.allocation.planning import AllocationPlanningMixin
from review_platform.review.allocation.queries import AllocationQueryMixin
from review_platform.review.allocation.schemas import (
    AllocationPolicyInput,
    AllocationPublishResponse,
)

__all__ = ["PUBLISHED_ASSIGNMENT_LEASE", "AllocationService"]


class AllocationService(
    AllocationPlanningMixin,
    AllocationLifecycleMixin,
    AllocationQueryMixin,
    AllocationIncrementalMixin,
    AllocationIncrementalPublishMixin,
):
    """Reviewer allocation runs: preview, persist, publish, discard, read, and incremental."""

    def publish_from_policy(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        body: AllocationPolicyInput,
        idempotency_key: str,
        request_id: str,
    ) -> AllocationPublishResponse:
        """Persist a plan from ``body`` and publish it in the same request/transaction.

        The admin UI only offers Preview + Publish; a saved-but-unpublished run is an internal
        durability/audit detail (drift guard, idempotent replay, discard-ability), not a product
        step. ``persist_run``/``publish_run`` are unchanged and still reachable directly for the
        run-inspection/discard surface.
        """
        persisted = self.persist_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            principal=principal,
            body=body,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
        return self.publish_run(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            run_id=persisted.run_id,
            principal=principal,
            idempotency_key=idempotency_key,
            request_id=request_id,
        )
