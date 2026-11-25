"""Allocation preview and run persistence (write side of the planning workflow)."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.review.allocation import PLANNER_VERSION, AllocationPreview
from review_platform.review.allocation.eligible_units import CaseUnits, EligibleUnit
from review_platform.review.allocation.plan_persistence import persist_assignment_plans
from review_platform.review.allocation.projections import (
    coverage_out,
    feasibility_out,
    run_response,
    workloads_out,
)
from review_platform.review.allocation.schemas import (
    AllocationPolicyInput,
    AllocationPreviewResponse,
    AllocationRunResponse,
    AssignmentCountsOut,
    SubjectPoolPreviewRequest,
    SubjectPoolPreviewResponse,
    SubjectPoolSample,
)
from review_platform.review.allocation.selection import (
    DEFAULT_SELECTION_SEED,
    INBOUND_METRIC,
    OUTBOUND_METRIC,
    citation_metric,
    rank_subjects,
)
from review_platform.review.allocation.service_base import AllocationServiceBase
from review_platform.review.models import (
    AllocationRun,
    AllocationRunReviewer,
    AllocationRunSubject,
    AssignmentPlan,
    Campaign,
    ReviewerPool,
    ReviewerPoolMember,
)


class AllocationPlanningMixin(AllocationServiceBase):
    def preview_subjects(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        body: SubjectPoolPreviewRequest,
    ) -> SubjectPoolPreviewResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        units = self._eligible_units(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            subject_kind=body.subject_kind,
            review_kind=body.review_kind,
        )
        selection = rank_subjects(
            units,
            strategy=body.selection_strategy,
            random_seed=body.random_seed or DEFAULT_SELECTION_SEED,
        )
        samples = [
            SubjectPoolSample(
                review_subject_id=unit.review_subject_id,
                subject_kind=unit.subject_kind,
                review_kind=unit.review_kind,
                display_title=unit.display_title,
                selection_rank=rank,
                inbound_citation_count=citation_metric(unit, INBOUND_METRIC),
                outbound_citation_count=citation_metric(unit, OUTBOUND_METRIC),
            )
            for rank, unit in enumerate(selection.units[: body.limit])
        ]
        # ``pool_digest`` identifies the eligible pool regardless of display order, so it stays
        # stable across selection strategies for the same campaign snapshot.
        return SubjectPoolPreviewResponse(
            subject_kind=body.subject_kind,
            review_kind=body.review_kind,
            eligible_subject_count=len(units),
            pool_digest=self._snapshot_digest(units),
            selection_strategy=body.selection_strategy,
            metrics_available=selection.metrics_available,
            diagnostic=selection.diagnostic,
            samples=samples,
        )

    def preview_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        body: AllocationPolicyInput,
    ) -> AllocationPreviewResponse:
        self._require_campaign_manager(session, principal, tenant_id)
        self._set_tenant_scope(session, tenant_id)
        self._load_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        preview, units, case_units = self._plan(
            session, tenant_id=tenant_id, campaign_id=campaign_id, policy_input=body
        )
        return AllocationPreviewResponse(
            feasibility=feasibility_out(preview),
            pairwise_overlap_matrix=preview.pairwise_overlap_matrix,
            reviewer_workloads=workloads_out(preview),
            subject_coverage=coverage_out(preview),
            # Counted exactly the way ``persist_run`` materializes the plan below, so the number the
            # admin previews is the number the publish result reports.
            planned_assignment_counts=AssignmentCountsOut(
                cases=len(preview.assignments),
                review_units=sum(
                    len(case_units[assignment.subject_id]) for assignment in preview.assignments
                ),
            ),
            pool_digest=self._pool_digest(body.reviewer_ids),
            source_snapshot_digest=self._snapshot_digest(units),
            allocation_policy_version=body.allocation_policy_version,
            planner_version=PLANNER_VERSION,
        )

    def persist_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign_id: uuid.UUID,
        principal: Principal,
        body: AllocationPolicyInput,
        idempotency_key: str,
        request_id: str,
    ) -> AllocationRunResponse:
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
        operation = f"allocation.persist.{campaign_id}"
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
            return AllocationRunResponse.model_validate(record.response_json).model_copy(
                update={"replayed": True}
            )
        preview, units, case_units = self._plan(
            session, tenant_id=tenant_id, campaign_id=campaign_id, policy_input=body
        )
        if preview.feasibility.status in {"infeasible", "blocked_by_reviewer_pool"}:
            raise APIError(
                422,
                "allocation_infeasible",
                "Allocation infeasible",
                f"The allocation request is {preview.feasibility.status}; "
                "preview it to inspect the feasibility report before persisting.",
            )
        run = self._write_run(
            session,
            tenant_id=tenant_id,
            campaign=campaign,
            body=body,
            preview=preview,
            units=units,
            case_units=case_units,
            created_by=principal.user.id,
        )
        response = run_response(run, preview)
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="allocation.run_persisted",
            object_type="allocation_run",
            object_id=str(run.id),
            request_id=request_id,
            payload={
                "campaign_id": str(campaign_id),
                "feasibility_status": run.feasibility_status,
                "planned_assignment_count": response.planned_assignment_count,
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

    def _write_run(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign: Campaign,
        body: AllocationPolicyInput,
        preview: AllocationPreview,
        units: list[EligibleUnit],
        case_units: CaseUnits,
        created_by: uuid.UUID,
    ) -> AllocationRun:
        pool_digest = self._pool_digest(body.reviewer_ids)
        snapshot_digest = self._snapshot_digest(units)
        run_key = f"run-{uuid.uuid4().hex[:24]}"
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
            session.add(
                ReviewerPoolMember(
                    tenant_id=tenant_id,
                    reviewer_pool_id=pool.id,
                    reviewer_id=reviewer_id,
                    eligibility_status="eligible",
                )
            )
        summary_json = {
            "source_unit_ids": sorted(str(unit.review_unit_id) for unit in units),
            "pairwise_overlap_matrix": preview.pairwise_overlap_matrix,
            "reviewer_workloads": [
                workload.model_dump(mode="json") for workload in workloads_out(preview)
            ],
            "subject_coverage": (
                coverage.model_dump(mode="json")
                if (coverage := coverage_out(preview)) is not None
                else None
            ),
        }
        run = AllocationRun(
            tenant_id=tenant_id,
            campaign_id=campaign.id,
            reviewer_pool_id=pool.id,
            run_key=run_key,
            status="planned",
            allocation_policy_version=body.allocation_policy_version,
            planner_version=PLANNER_VERSION,
            source_snapshot_id=campaign.source_snapshot_id,
            source_snapshot_digest=snapshot_digest,
            pool_digest=pool_digest,
            random_seed=body.random_seed,
            input_parameters_json=body.model_dump(mode="json"),
            metric_weights_json=dict(body.metric_weights),
            feasibility_status=preview.feasibility.status,
            feasibility_report_json=feasibility_out(preview).model_dump(mode="json"),
            summary_json=summary_json,
            created_by=created_by,
        )
        session.add(run)
        session.flush()

        # Case-native persistence: a planned subject is a whole case. Record one
        # ``AllocationRunSubject`` per selected case (its representative field-subject) ...
        layer_by_case: dict[str, str] = {}
        for assignment in preview.assignments:
            layer_by_case.setdefault(assignment.subject_id, assignment.selection_layer)
        for case_key, selection_layer in layer_by_case.items():
            representative_subject = case_units[case_key][0]
            session.add(
                AllocationRunSubject(
                    tenant_id=tenant_id,
                    allocation_run_id=run.id,
                    review_subject_id=representative_subject.review_subject_id,
                    selection_layer=selection_layer,
                    metrics_json={},
                )
            )
        for workload in workloads_out(preview):
            session.add(
                AllocationRunReviewer(
                    tenant_id=tenant_id,
                    allocation_run_id=run.id,
                    reviewer_id=workload.reviewer_id,
                    planned_assignment_count=workload.planned_assignment_count,
                    unique_assignment_count=workload.unique_assignment_count,
                    pairwise_overlap_count=workload.pairwise_overlap_count,
                    global_overlap_count=workload.global_overlap_count,
                    workload_json=workload.model_dump(mode="json"),
                )
            )
        # ... and fan each planned (case, reviewer) out into one per-unit ``AssignmentPlan`` for
        # every in-scope field of that case. The durable assignment/answer/adjudication model stays
        # per-unit, so publishing, claiming, and reviewer blindness are unchanged downstream; only
        # the *selection* granularity moved from field to case.
        persist_assignment_plans(
            session,
            (
                AssignmentPlan(
                    tenant_id=tenant_id,
                    allocation_run_id=run.id,
                    review_unit_id=unit.review_unit_id,
                    reviewer_id=uuid.UUID(assignment.reviewer_id),
                    status="planned",
                    selection_layer=assignment.selection_layer,
                    overlap_group_key=assignment.overlap_group_key,
                    window_index=assignment.window_index,
                    plan_metadata_json={},
                )
                for assignment in preview.assignments
                for unit in case_units[assignment.subject_id]
            ),
        )
        return run
