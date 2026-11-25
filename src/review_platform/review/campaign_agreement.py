"""Human-reviewer pairwise agreement metrics for a campaign — campaign_manager only.

Split out of ``review_platform.review.campaign_admin`` to keep that file under the repository's
production-file size guardrail; this mixin owns only the agreement-metrics read path.
"""

from __future__ import annotations

import uuid
from collections import Counter, defaultdict
from collections.abc import Sequence
from itertools import combinations
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.review.base import ReviewServiceBase
from review_platform.review.models import AnnotationRevision, Assignment, ReviewUnit
from review_platform.review.schemas import (
    ReviewerAgreementMetricsResponse,
    ReviewerPairAgreement,
)


class ReviewCampaignAgreementMixin(ReviewServiceBase):
    def reviewer_agreement_metrics(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID | None,
        review_kind: str | None,
    ) -> ReviewerAgreementMetricsResponse:
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        statement = (
            select(AnnotationRevision, Assignment, ReviewUnit)
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
                AnnotationRevision.state == "submitted",
                Assignment.status == "submitted",
            )
            .order_by(ReviewUnit.id, Assignment.reviewer_id)
        )
        if campaign_id is not None:
            statement = statement.where(ReviewUnit.campaign_id == campaign_id)
        if review_kind is not None:
            statement = statement.where(ReviewUnit.review_kind == review_kind)
        submissions_by_unit: dict[uuid.UUID, list[tuple[uuid.UUID, str]]] = defaultdict(list)
        submission_count = 0
        for revision, assignment, unit in session.execute(statement).all():
            submissions_by_unit[unit.id].append((assignment.reviewer_id, revision.outcome))
            submission_count += 1
        all_pairs: list[tuple[str, str]] = []
        reviewer_pair_values: dict[tuple[uuid.UUID, uuid.UUID], list[tuple[str, str]]] = (
            defaultdict(list)
        )
        for submissions in submissions_by_unit.values():
            for left, right in combinations(submissions, 2):
                left_reviewer, left_outcome = left
                right_reviewer, right_outcome = right
                reviewer_key = (
                    (left_reviewer, right_reviewer)
                    if str(left_reviewer) <= str(right_reviewer)
                    else (right_reviewer, left_reviewer)
                )
                if reviewer_key[0] == left_reviewer:
                    ordered_pair = (left_outcome, right_outcome)
                else:
                    ordered_pair = (right_outcome, left_outcome)
                all_pairs.append(ordered_pair)
                reviewer_pair_values[reviewer_key].append(ordered_pair)
        overall = self._reviewer_metrics(all_pairs)
        return ReviewerAgreementMetricsResponse(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            review_kind=cast(Any, review_kind),
            review_unit_count=len(submissions_by_unit),
            submission_count=submission_count,
            **overall,
            reviewer_pairs=[
                ReviewerPairAgreement(
                    reviewer_a_id=reviewer_a_id,
                    reviewer_b_id=reviewer_b_id,
                    **self._reviewer_metrics(pairs),
                )
                for (reviewer_a_id, reviewer_b_id), pairs in sorted(
                    reviewer_pair_values.items(),
                    key=lambda item: (str(item[0][0]), str(item[0][1])),
                )
            ],
        )

    @staticmethod
    def _reviewer_metrics(pairs: Sequence[tuple[str, str]]) -> dict[str, Any]:
        total = len(pairs)
        confusion: dict[str, dict[str, int]] = defaultdict(dict)
        row_counts: Counter[str] = Counter()
        col_counts: Counter[str] = Counter()
        agree_count = 0
        for left, right in pairs:
            confusion[left][right] = confusion[left].get(right, 0) + 1
            row_counts[left] += 1
            col_counts[right] += 1
            if left == right:
                agree_count += 1
        labels = sorted(set(row_counts) | set(col_counts))
        if total == 0:
            agreement_percent = cohen_kappa = pabak = None
        else:
            observed = agree_count / total
            expected = sum(row_counts[label] * col_counts[label] for label in labels) / (
                total * total
            )
            agreement_percent = observed * 100
            cohen_kappa = 1.0 if expected >= 1.0 else (observed - expected) / (1 - expected)
            pabak = (2 * observed) - 1
        return {
            "pair_count": total,
            "agree_count": agree_count,
            "agreement_percent": agreement_percent,
            "cohen_kappa": cohen_kappa,
            "pabak": pabak,
            "labels": labels,
            "confusion": {label: dict(confusion.get(label, {})) for label in labels},
        }
