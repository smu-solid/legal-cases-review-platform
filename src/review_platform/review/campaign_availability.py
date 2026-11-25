"""Read-only availability calculations and feasibility decisions."""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.orm import Session

from review_platform.review.availability_queries import (
    CampaignOverlapSummary,
    _campaign_unit_stats,
    _CampaignUnitRow,
    _claimed_campaign_overlaps_for_cases,
    _claimed_groups_for_cases,
    _stats_from_rows,
)

FeasibilityStatus = Literal[
    "feasible_exact",
    "feasible_with_smaller_count",
    "feasible_with_remaining_fields_only",
    "infeasible_no_cases",
    "infeasible_no_fields",
]


CaseCountRequest = int | Literal["all"]


@dataclass(frozen=True)
class CampaignAvailability:
    requested_case_count: int | None  # None == "all"
    requested_field_scope: list[str]
    eligible_cases_count: int
    eligible_review_units_count: int
    unavailable_cases_count: int
    unavailable_review_units_count: int
    fields_fully_exhausted: list[str]
    fields_partially_available: list[str]
    cases_available_for_all_selected_fields: int
    cases_available_for_some_selected_fields_only: int
    feasibility: FeasibilityStatus
    infeasible_message: str | None
    overlap_cases_count: int = 0
    overlap_group_counts: tuple[tuple[str, int], ...] = ()
    overlap_campaigns: tuple[CampaignOverlapSummary, ...] = ()


def lock_pool_claims(session: Session, *, tenant_id: uuid.UUID) -> None:
    """Serialize pool availability+claim decisions for one tenant until transaction end."""

    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:tenant_id, 0))"),
        {"tenant_id": str(tenant_id)},
    )


def compute_availability(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    pool_campaign_id: uuid.UUID,
    source_families: list[str],
    group_ids: list[str],
    requested_case_count: CaseCountRequest,
    synthesize_missing: bool = False,
    allowed_case_keys: frozenset[tuple[str, str]] | None = None,
    target_campaign_id: uuid.UUID | None = None,
    pool_rows: list[_CampaignUnitRow] | None = None,
) -> CampaignAvailability:
    """Compute availability for a source filter + field scope against the current pool state."""

    # Availability never needs unit identities, so it consumes per-(case, group) COUNTS. The
    # aggregation happens in the database on the direct path; a caller that already holds the
    # serialized full-row snapshot (the claim path, which must go on to move those exact units)
    # has its rows folded into identical stats instead of being re-queried.
    stats = (
        _stats_from_rows(pool_rows)
        if pool_rows is not None
        else _campaign_unit_stats(session, tenant_id=tenant_id, campaign_id=pool_campaign_id)
    )
    if source_families:
        stats = [stat for stat in stats if stat.source_system in source_families]
    if allowed_case_keys is not None:
        stats = [stat for stat in stats if stat.case_key in allowed_case_keys]
    scoped = bool(group_ids)
    requested_groups = (
        sorted(set(group_ids)) if scoped else sorted({stat.group_id for stat in stats})
    )

    by_case: dict[tuple[str, str], set[str]] = defaultdict(set)
    units_by_case: Counter[tuple[str, str]] = Counter()
    scoped_units_by_case: Counter[tuple[str, str]] = Counter()
    requested_set = set(group_ids)
    for stat in stats:
        if stat.case_key is None:
            continue
        by_case[stat.case_key].add(stat.group_id)
        units_by_case[stat.case_key] += stat.unit_count
        if stat.group_id in requested_set:
            scoped_units_by_case[stat.case_key] += stat.unit_count

    claimed_by_case = _claimed_groups_for_cases(
        session,
        tenant_id=tenant_id,
        pool_campaign_id=pool_campaign_id,
        case_keys=set(by_case),
        target_campaign_id=target_campaign_id,
    )
    overlap_campaigns = _claimed_campaign_overlaps_for_cases(
        session,
        tenant_id=tenant_id,
        pool_campaign_id=pool_campaign_id,
        case_keys=set(by_case),
        target_campaign_id=target_campaign_id,
        requested_groups=requested_set if scoped else None,
    )
    overlapping_cases = {
        case_key
        for case_key, groups in claimed_by_case.items()
        if not scoped or bool(groups & requested_set)
    }
    overlap_groups = Counter(
        group
        for case_key in overlapping_cases
        for group in (
            claimed_by_case[case_key] & requested_set if scoped else claimed_by_case[case_key]
        )
    )

    total_cases = len(by_case)
    if not scoped or synthesize_missing:
        # Unscoped: every pooled case is eligible, as before. Scoped + synthesize_missing: every
        # pooled case is eligible too -- a requested group a case doesn't have yet is a synthesis
        # gap, never an eligibility exclusion (the new rule, opt-in only).
        cases_all = set(by_case) - overlapping_cases if synthesize_missing else set(by_case)
        cases_some: set[tuple[str, str]] = set()
    else:
        # Pre-existing default behaviour, unchanged: strict all-or-nothing intersection.
        cases_all = {
            case_id
            for case_id, groups in by_case.items()
            if requested_set <= groups and case_id not in overlapping_cases
        }
        cases_some = {
            case_id
            for case_id, groups in by_case.items()
            if case_id not in cases_all and (groups & requested_set)
        }
    unavailable_review_units_count = 0
    if not scoped:
        fields_fully_exhausted: list[str] = []
        fields_partially_available: list[str] = []
        eligible_review_units_count = sum(units_by_case[case_id] for case_id in cases_all)
    elif synthesize_missing:
        fields_fully_exhausted = [
            group
            for group in requested_groups
            if not any(group in by_case[case_id] for case_id in cases_all)
        ]
        fields_partially_available = [
            group
            for group in requested_groups
            if group not in fields_fully_exhausted
            and any(group not in by_case[case_id] for case_id in cases_all)
        ]
        # Count synthesized-missing slots the same as already-extracted units: every requested
        # group a case doesn't already have becomes exactly one review unit once materialized.
        missing_slots = sum(len(requested_set - by_case[case_id]) for case_id in cases_all)
        eligible_review_units_count = (
            sum(scoped_units_by_case[case_id] for case_id in cases_all) + missing_slots
        )
    else:
        # Pre-existing default behaviour, unchanged.
        fields_fully_exhausted = [
            group
            for group in requested_groups
            if not any(group in groups for groups in by_case.values())
        ]
        fields_partially_available = [
            group
            for group in requested_groups
            if group not in fields_fully_exhausted
            and any(group not in groups for groups in by_case.values())
        ]
        eligible_review_units_count = sum(scoped_units_by_case[case_id] for case_id in cases_all)
        unavailable_review_units_count = sum(
            len(requested_set - by_case.get(case_id, set())) for case_id in by_case
        )
    unavailable_cases_count = total_cases - len(cases_all)

    cap = None if requested_case_count == "all" else requested_case_count
    feasibility, message = _feasibility(
        cap=cap,
        eligible_cases_count=len(cases_all),
        cases_some=len(cases_some),
        fields_fully_exhausted=fields_fully_exhausted,
        requested_groups=requested_groups,
    )
    if feasibility in {"infeasible_no_cases", "infeasible_no_fields"}:
        groups = ", ".join(requested_groups) if requested_groups else "all available field groups"
        if feasibility == "infeasible_no_fields":
            exhausted = ", ".join(fields_fully_exhausted) or groups
            message = (
                f"No eligible cases remain in the case pool. Exhausted field groups: {exhausted}. "
                f"0 cases satisfy all selected fields; {len(cases_some)} cases have only a subset."
            )
        else:
            message = (
                f"No eligible cases remain for {groups}. 0 cases are currently "
                "available in the pool for this scope."
            )

    return CampaignAvailability(
        requested_case_count=cap,
        requested_field_scope=requested_groups,
        eligible_cases_count=len(cases_all),
        eligible_review_units_count=eligible_review_units_count,
        unavailable_cases_count=unavailable_cases_count,
        unavailable_review_units_count=unavailable_review_units_count,
        fields_fully_exhausted=fields_fully_exhausted,
        fields_partially_available=fields_partially_available,
        cases_available_for_all_selected_fields=len(cases_all),
        cases_available_for_some_selected_fields_only=len(cases_some),
        feasibility=feasibility,
        infeasible_message=message,
        overlap_cases_count=len(overlapping_cases),
        overlap_group_counts=tuple(sorted(overlap_groups.items())),
        overlap_campaigns=overlap_campaigns,
    )


def _feasibility(
    *,
    cap: int | None,
    eligible_cases_count: int,
    cases_some: int,
    fields_fully_exhausted: list[str],
    requested_groups: list[str],
) -> tuple[FeasibilityStatus, str | None]:
    if eligible_cases_count == 0 and cases_some == 0:
        if requested_groups and len(fields_fully_exhausted) == len(requested_groups):
            return "infeasible_no_fields", (
                "The selected fields are exhausted for this source: no eligible cases remain."
            )
        return "infeasible_no_cases", "No eligible cases are available for this source/field scope."
    if eligible_cases_count == 0 and cases_some > 0:
        return "feasible_with_remaining_fields_only", (
            "No case has every selected field available, but some cases have a subset of the "
            "selected fields remaining."
        )
    if cap is None or eligible_cases_count >= cap:
        return "feasible_exact", None
    return "feasible_with_smaller_count", (
        f"Only {eligible_cases_count} eligible cases are available for this field scope "
        f"(requested {cap})."
    )
