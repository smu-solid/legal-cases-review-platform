"""Pure mappers from planner previews and persisted runs to allocation API response schemas."""

from __future__ import annotations

import uuid
from typing import cast

from review_platform.review.allocation import AllocationPreview
from review_platform.review.allocation.schemas import (
    AllocationRunResponse,
    FeasibilityIssueOut,
    FeasibilityOut,
    FeasibilityStatus,
    IncrementalFeasibilityIssueOut,
    IncrementalFeasibilityOut,
    IncrementalRunResponse,
    ReviewerWorkloadOut,
    RunStatus,
    SubjectCoverageOut,
)
from review_platform.review.incremental_planner import IncrementalAllocationPreview
from review_platform.review.models import AllocationRun


def feasibility_out(preview: AllocationPreview) -> FeasibilityOut:
    feasibility = preview.feasibility
    return FeasibilityOut(
        status=feasibility.status,
        errors=[
            FeasibilityIssueOut(code=issue.code, message=issue.message)
            for issue in feasibility.errors
        ],
        warnings=[
            FeasibilityIssueOut(code=issue.code, message=issue.message)
            for issue in feasibility.warnings
        ],
        computed_totals={key: float(value) for key, value in feasibility.computed_totals.items()},
        suggested_adjustments=list(feasibility.suggested_adjustments),
    )


def workloads_out(preview: AllocationPreview) -> list[ReviewerWorkloadOut]:
    return [
        ReviewerWorkloadOut(
            reviewer_id=uuid.UUID(summary.reviewer_id),
            planned_assignment_count=summary.planned_assignment_count,
            unique_assignment_count=summary.unique_assignment_count,
            pairwise_overlap_count=summary.pairwise_overlap_count,
            global_overlap_count=summary.global_overlap_count,
        )
        for summary in preview.reviewer_workloads
    ]


def coverage_out(preview: AllocationPreview) -> SubjectCoverageOut | None:
    coverage = preview.subject_coverage
    if coverage is None:
        return None
    return SubjectCoverageOut(
        total_eligible_subjects=coverage.total_eligible_subjects,
        total_distinct_subjects=coverage.total_distinct_subjects,
        assigned_distinct_subjects=coverage.assigned_distinct_subjects,
        unassigned_eligible_count=coverage.unassigned_eligible_count,
        hub_subject_count=coverage.hub_subject_count,
        random_subject_count=coverage.random_subject_count,
        expected_total_assignments=coverage.expected_total_assignments,
        coverage_ratio=coverage.coverage_ratio,
        overlap_ratio=coverage.overlap_ratio,
    )


def run_response(run: AllocationRun, preview: AllocationPreview | None) -> AllocationRunResponse:
    summary = run.summary_json
    workloads = summary.get("reviewer_workloads", [])
    planned = sum(int(item["planned_assignment_count"]) for item in workloads)
    coverage = summary.get("subject_coverage") or {}
    distinct = int(coverage.get("assigned_distinct_subjects", 0))
    return AllocationRunResponse(
        run_id=run.id,
        campaign_id=run.campaign_id,
        status=cast(RunStatus, run.status),
        feasibility_status=cast(FeasibilityStatus, run.feasibility_status),
        allocation_policy_version=run.allocation_policy_version,
        planner_version=run.planner_version,
        source_snapshot_digest=run.source_snapshot_digest,
        pool_digest=run.pool_digest,
        planned_assignment_count=planned,
        distinct_subject_count=distinct,
        reviewer_count=len(workloads),
        created_at=run.created_at,
        published_at=run.published_at,
        lock_version=run.lock_version,
    )


def incremental_feasibility_out(
    preview: IncrementalAllocationPreview,
) -> IncrementalFeasibilityOut:
    feasibility = preview.feasibility
    return IncrementalFeasibilityOut(
        status=feasibility.status,
        errors=[
            IncrementalFeasibilityIssueOut(code=issue.code, message=issue.message)
            for issue in feasibility.errors
        ],
        warnings=[
            IncrementalFeasibilityIssueOut(code=issue.code, message=issue.message)
            for issue in feasibility.warnings
        ],
    )


def incremental_run_response(
    run: AllocationRun, preview: IncrementalAllocationPreview
) -> IncrementalRunResponse:
    summary = run.summary_json
    return IncrementalRunResponse(
        run_id=run.id,
        campaign_id=run.campaign_id,
        base_run_id=run.base_allocation_run_id,
        status=cast(RunStatus, run.status),
        allocation_mode="incremental",
        feasibility_status=preview.feasibility.status,
        allocation_policy_version=run.allocation_policy_version,
        planner_version=run.planner_version,
        new_assignment_count=int(summary.get("new_assignment_count", 0)),
        moved_assignment_count=int(summary.get("moved_assignment_count", 0)),
        preserved_assignment_count=int(summary.get("preserved_assignment_count", 0)),
        created_at=run.created_at,
        published_at=run.published_at,
        lock_version=run.lock_version,
    )
