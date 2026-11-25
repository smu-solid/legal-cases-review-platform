"""Incremental allocation preview and run persistence (reviewer-pool change handling).

Admin-only preview and persist for incremental allocation runs. Both compose the input-assembly and
pure planner via :class:`AllocationIncrementalInputsMixin`, then map the result to admin-only
response schemas (preview) or persist a planned ``incremental`` run with its movement plan and
planned assignments (persist). Publishing is handled by the separate publish mixin.

All outputs are admin-only. Persisted assignments flow through the existing blinded reviewer queue,
so ordinary reviewers never see overlap, movement, capacity, or peer-progress structure.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.review.allocation.eligible_units import CaseUnits, EligibleUnit
from review_platform.review.allocation.incremental_inputs import AllocationIncrementalInputsMixin
from review_platform.review.allocation.incremental_persistence import (
    persist_incremental_movement_plans,
)
from review_platform.review.allocation.plan_persistence import persist_assignment_plans
from review_platform.review.allocation.projections import (
    incremental_feasibility_out,
    incremental_run_response,
)
from review_platform.review.allocation.schemas import (
    AssignmentCountsOut,
    IncrementalPolicyInput,
    IncrementalPreviewResponse,
    IncrementalRunResponse,
    MovementEntryOut,
    WorkloadSummaryOut,
    counts_for_unit_pairs,
)
from review_platform.review.incremental_planner import (
    INCREMENTAL_PLANNER_VERSION,
    IncrementalAllocationPreview,
    MovementEntry,
)
from review_platform.review.models import (
    AllocationRun,
    AssignmentPlan,
    Campaign,
    IncrementalMovementPlan,
    ReviewerPool,
    ReviewerPoolMember,
)


def _fan_out_to_units(
    movement_plan: Sequence[MovementEntry],
    case_units: CaseUnits,
    kinds: tuple[str, ...] | None = None,
) -> list[tuple[MovementEntry, EligibleUnit]]:
    """Expand case-level movement entries into one entry per in-scope unit of that case.

    The planner decides at case granularity; every durable artefact (``AssignmentPlan``,
    ``IncrementalMovementPlan``, the API's ``MovementEntryOut``) is per review unit, exactly as the
    initial path's persist step fans out. Keeping the fan-out here is what makes a moved case move
    with all of its units instead of leaving fragments behind on the previous reviewer.
    """

    return [
        (entry, unit)
        for entry in movement_plan
        if kinds is None or entry.movement_kind in kinds
        for unit in case_units.get(entry.subject_id, [])
    ]


def _movement_counts(
    movement_plan: Sequence[MovementEntry],
    kind: str,
    case_units: CaseUnits,
) -> AssignmentCountsOut:
    """Count one movement kind at both granularities.

    ``MovementEntry.subject_id`` is a case key, so entries of a given kind are the ``(case,
    reviewer)`` pairs behind ``new_assignment_count``/``moved_assignment_count``; fanning them out
    gives the review-unit count the same movement will actually create.
    """

    pairs = [
        (uuid.UUID(entry.to_reviewer_id), unit.review_unit_id)
        for entry, unit in _fan_out_to_units(movement_plan, case_units, (kind,))
    ]
    case_by_unit = {
        unit.review_unit_id: case_key
        for case_key, members in case_units.items()
        for unit in members
    }
    return counts_for_unit_pairs(pairs, case_by_unit)


class AllocationIncrementalMixin(AllocationIncrementalInputsMixin):
    """Admin-only incremental allocation: preview and persist reviewer-pool changes."""

    # -- preview --------------------------------------------------------------------------------

    def preview_incremental_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        body: IncrementalPolicyInput,
    ) -> IncrementalPreviewResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        base_run = self._load_base_run(
            session, tenant_id=tenant_id, campaign_id=campaign_id, base_run_id=body.base_run_id
        )
        preview, _units, case_units = self._incremental_plan(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            body=body,
            base_run=base_run,
        )
        coverage_gap_count = sum(
            1 for count in preview.coverage_before.values() if count < body.min_reviews_per_subject
        )
        return IncrementalPreviewResponse(
            campaign_id=campaign_id,
            base_run_id=body.base_run_id,
            policy_version=body.allocation_policy_version,
            reviewer_pool_before=[uuid.UUID(rid) for rid in preview.reviewer_pool_before],
            reviewer_pool_after=[uuid.UUID(rid) for rid in preview.reviewer_pool_after],
            # Cases, not review units -- the allocation subject on this path.
            subject_count=len(case_units),
            min_reviews_per_subject=body.min_reviews_per_subject,
            coverage_gap_count=coverage_gap_count,
            new_assignment_count=preview.new_assignment_count,
            moved_assignment_count=preview.moved_assignment_count,
            preserved_assignment_count=preview.preserved_assignment_count,
            new_assignment_counts=_movement_counts(preview.movement_plan, "new", case_units),
            moved_assignment_counts=_movement_counts(preview.movement_plan, "moved", case_units),
            unassigned_subject_count=len(preview.unassigned_subject_ids),
            workload_summaries=[
                WorkloadSummaryOut(
                    reviewer_id=uuid.UUID(ws.reviewer_id),
                    count_before=ws.count_before,
                    count_after=ws.count_after,
                )
                for ws in preview.workload_summaries
            ],
            # Per review unit: the planner decided per case, and this is the per-unit consequence
            # the publish step will materialize.
            movement_plan=[
                MovementEntryOut(
                    subject_id=unit.review_unit_id,
                    from_reviewer_id=(
                        uuid.UUID(e.from_reviewer_id) if e.from_reviewer_id else None
                    ),
                    to_reviewer_id=uuid.UUID(e.to_reviewer_id),
                    movement_kind=e.movement_kind,
                    movement_reason=e.movement_reason,
                )
                for e, unit in _fan_out_to_units(preview.movement_plan, case_units)
            ],
            feasibility=incremental_feasibility_out(preview),
        )

    # -- persist --------------------------------------------------------------------------------

    def persist_incremental_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        body: IncrementalPolicyInput,
        idempotency_key: str,
        request_id: str,
    ) -> IncrementalRunResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        campaign = self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        if campaign.status == "closed":
            raise APIError(
                409,
                "campaign_not_plannable",
                "Campaign not plannable",
                "A closed campaign cannot accept new allocation runs.",
            )
        base_run = self._load_base_run(
            session, tenant_id=tenant_id, campaign_id=campaign_id, base_run_id=body.base_run_id
        )
        operation = f"allocation.incremental.{campaign_id}"
        request_digest = digest_json(body.model_dump(mode="json"))
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            return IncrementalRunResponse.model_validate(record.response_json).model_copy(
                update={"replayed": True}
            )
        preview, units, case_units = self._incremental_plan(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            body=body,
            base_run=base_run,
        )
        if preview.feasibility.status == "blocked_by_reviewer_pool":
            raise APIError(
                422,
                "allocation_infeasible",
                "Allocation infeasible",
                "The incremental allocation is blocked by the reviewer pool.",
            )
        run = self._write_incremental_run(
            session,
            tenant_id=tenant_id,
            campaign=campaign,
            base_run=base_run,
            body=body,
            preview=preview,
            units=units,
            case_units=case_units,
            created_by=principal.user.id,
        )
        response = incremental_run_response(run, preview)
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="allocation.incremental_run_persisted",
            object_type="allocation_run",
            object_id=str(run.id),
            request_id=request_id,
            payload={
                "campaign_id": str(campaign_id),
                "base_run_id": str(body.base_run_id),
                "feasibility_status": run.feasibility_status,
                "new_assignment_count": preview.new_assignment_count,
                "moved_assignment_count": preview.moved_assignment_count,
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

    def _write_incremental_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign: Campaign,
        base_run: AllocationRun,
        body: IncrementalPolicyInput,
        preview: IncrementalAllocationPreview,
        units: list[EligibleUnit],
        case_units: CaseUnits,
        created_by: uuid.UUID,
    ) -> AllocationRun:
        pool_digest = self._pool_digest(body.reviewer_ids)
        snapshot_digest = self._snapshot_digest(units)
        run_key = f"incr-{uuid.uuid4().hex[:24]}"
        pool = ReviewerPool(
            tenant_id=tenant_id,
            campaign_id=campaign.id,
            name=f"pool-{run_key}",
            status="active",
            eligibility_policy_version=body.allocation_policy_version,
            exclusions_json={},
            pool_digest=pool_digest,
            created_by=created_by,
        )
        session.add(pool)
        session.flush()
        for reviewer_id in body.reviewer_ids:
            weight = body.reviewer_capacity_weights.get(str(reviewer_id), 1.0)
            session.add(
                ReviewerPoolMember(
                    tenant_id=tenant_id,
                    reviewer_pool_id=pool.id,
                    reviewer_id=reviewer_id,
                    eligibility_status="eligible",
                    capacity_weight=weight,
                )
            )
        summary_json: dict[str, Any] = {
            "source_unit_ids": sorted(str(unit.review_unit_id) for unit in units),
            "new_assignment_count": preview.new_assignment_count,
            "moved_assignment_count": preview.moved_assignment_count,
            "preserved_assignment_count": preview.preserved_assignment_count,
            "unassigned_subject_count": len(preview.unassigned_subject_ids),
            "workload_summaries": [
                {
                    "reviewer_id": ws.reviewer_id,
                    "count_before": ws.count_before,
                    "count_after": ws.count_after,
                }
                for ws in preview.workload_summaries
            ],
        }
        run = AllocationRun(
            tenant_id=tenant_id,
            campaign_id=campaign.id,
            reviewer_pool_id=pool.id,
            run_key=run_key,
            status="planned",
            allocation_mode="incremental",
            base_allocation_run_id=base_run.id,
            previous_pool_digest=base_run.pool_digest,
            allocation_policy_version=body.allocation_policy_version,
            planner_version=INCREMENTAL_PLANNER_VERSION,
            source_snapshot_id=campaign.source_snapshot_id,
            source_snapshot_digest=snapshot_digest,
            pool_digest=pool_digest,
            random_seed=body.random_seed,
            input_parameters_json=body.model_dump(mode="json"),
            metric_weights_json={},
            feasibility_status=preview.feasibility.status,
            feasibility_report_json={
                "status": preview.feasibility.status,
                "errors": [
                    {"code": e.code, "message": e.message} for e in preview.feasibility.errors
                ],
                "warnings": [
                    {"code": e.code, "message": e.message} for e in preview.feasibility.warnings
                ],
            },
            summary_json=summary_json,
            movement_policy_json=body.movement_policy.model_dump(mode="json"),
            created_by=created_by,
        )
        session.add(run)
        session.flush()
        # One audit row per (unit, movement): the decision is per case, the record is per unit, so
        # publish can keep matching ``IncrementalMovementPlan.subject_id`` to a review unit.
        persist_incremental_movement_plans(
            session,
            (
                IncrementalMovementPlan(
                    tenant_id=tenant_id,
                    allocation_run_id=run.id,
                    subject_id=unit.review_unit_id,
                    from_reviewer_id=(
                        uuid.UUID(entry.from_reviewer_id) if entry.from_reviewer_id else None
                    ),
                    to_reviewer_id=uuid.UUID(entry.to_reviewer_id),
                    movement_kind=entry.movement_kind,
                    movement_reason=entry.movement_reason,
                )
                for entry, unit in _fan_out_to_units(preview.movement_plan, case_units)
            ),
        )
        # A (subject, to_reviewer) pair can appear more than once in the movement plan -- e.g. a
        # coverage-gap "new" pick for a subject can coincide with a removed reviewer's release
        # being attributed to that same already-covering reviewer (see IncrementalPlanner's
        # "reviewer_removed_release_only" fallback). AssignmentPlan has a real
        # (run, unit, reviewer) uniqueness constraint, so collapse to one row per pair here,
        # preferring "moved" so the release still happens; publish sources *which* reviewer(s) to
        # release from the full ``IncrementalMovementPlan`` audit trail below (unconstrained), not
        # from this single collapsed row, so no release is lost to the collapse.
        assignment_entries: dict[tuple[uuid.UUID, str], MovementEntry] = {}
        for entry, unit in _fan_out_to_units(preview.movement_plan, case_units, ("new", "moved")):
            key = (unit.review_unit_id, entry.to_reviewer_id)
            current = assignment_entries.get(key)
            prefers_moved = (
                current is not None
                and current.movement_kind != "moved"
                and entry.movement_kind == "moved"
            )
            if current is None or prefers_moved:
                assignment_entries[key] = entry
        persist_assignment_plans(
            session,
            (
                AssignmentPlan(
                    tenant_id=tenant_id,
                    allocation_run_id=run.id,
                    review_unit_id=unit_id,
                    reviewer_id=uuid.UUID(entry.to_reviewer_id),
                    status="planned",
                    selection_layer="unique",
                    overlap_group_key=None,
                    window_index=None,
                    plan_metadata_json={
                        "movement_kind": entry.movement_kind,
                        "movement_reason": entry.movement_reason,
                    },
                )
                for (unit_id, _reviewer), entry in assignment_entries.items()
            ),
        )
        return run
