"""CSRF-protected, assignment-authorized reviewer proposal mutations."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, Literal

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from review_platform.api.params import (
    LOCK_VERSION_RESPONSE_HEADERS,
    IdempotencyKey,
    IfMatch,
    expected_version,
    set_lock_version_etag,
)
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas.citation_duplicates import CitationDuplicateCheck
from review_platform.review.schemas.proposals import (
    ProposalDuplicateInput,
    ProposalInput,
    ReviewerProposal,
)


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    @router.post(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/proposals/{proposal_id}/duplicate-check",
        response_model=CitationDuplicateCheck,
        operation_id="checkReviewerProposalDuplicates",
    )
    def check_duplicates(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        proposal_id: uuid.UUID,
        body: ProposalDuplicateInput,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> CitationDuplicateCheck:
        return context.review.check_proposal_duplicates(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            proposal_id=proposal_id,
            principal=principal,
            body=body,
            artifact_store=context.artifact_store,
        )

    @router.put(
        "/tenants/{tenant_id}/review/assignments/{assignment_id}/proposals/{proposal_id}/{state}",
        response_model=ReviewerProposal,
        operation_id="saveReviewerProposal",
        responses={200: {"headers": LOCK_VERSION_RESPONSE_HEADERS}},
    )
    def save_proposal(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        proposal_id: uuid.UUID,
        state: Literal["draft", "submitted", "removed"],
        body: ProposalInput,
        response: Response,
        idempotency_key: IdempotencyKey,
        if_match: IfMatch,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ReviewerProposal:
        result = context.review.save_proposal(
            session,
            tenant_id=tenant_id,
            assignment_id=assignment_id,
            proposal_id=proposal_id,
            principal=principal,
            body=body,
            state=state,
            expected_version=expected_version(if_match),
            idempotency_key=idempotency_key,
            artifact_store=context.artifact_store,
        )
        set_lock_version_etag(response, result.lock_version)
        return result
