"""Hard removal of unsubmitted additions and their cached draft payloads."""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from review_platform.auth.service import now_utc
from review_platform.common.errors import APIError
from review_platform.review.models import IdempotencyRecord
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.schemas.proposals import ReviewerProposal


def removed_response(
    session: Session,
    tenant_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    proposal_id: uuid.UUID,
    state: str,
) -> ReviewerProposal | None:
    # A content-free retry receipt prevents delayed draft writes resurrecting a deleted item.
    record = session.scalar(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.user_id == reviewer_id,
            IdempotencyRecord.operation == f"review.proposal.{proposal_id}.removed",
        )
        .limit(1)
    )
    if record and state != "removed":
        raise APIError(409, "proposal_locked", "Item removed", "This item has been removed.")
    return ReviewerProposal.model_validate(record.response_json) if record else None


def remove_proposal(
    session: Session,
    proposal: ReviewerAddedProposal | None,
    *,
    tenant_id: uuid.UUID,
    reviewer_id: uuid.UUID,
    proposal_id: uuid.UUID,
    group_id: str,
) -> ReviewerProposal:
    result = ReviewerProposal(
        id=proposal_id,
        group_id=group_id,
        value_schema="cited_case_text/v1"
        if group_id == "cited_cases"
        else "statute_reference_text/v1",
        original_value="",
        state="removed",
        lock_version=proposal.lock_version + 1 if proposal else 2,
        created_at=proposal.created_at if proposal else now_utc(),
    )
    if proposal is not None:
        session.delete(proposal)
    session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.user_id == reviewer_id,
            IdempotencyRecord.operation.in_(
                [f"review.proposal.{proposal_id}.{state}" for state in ("draft", "submitted")]
            ),
        )
    )
    session.flush()
    return result
