"""Adjudicator-authorized private proposal read and write endpoints."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from review_platform.api.params import IdempotencyKey
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas.proposal_adjudication import (
    ProposalAdjudicationWorkspace,
    ProposalDecisionWrite,
    ProposalMembershipChange,
)


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    path = "/tenants/{tenant_id}/review/adjudications/{adjudication_id}/proposal-items"

    @router.get(
        path,
        response_model=ProposalAdjudicationWorkspace,
        operation_id="getProposalAdjudicationWorkspace",
    )
    def read(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ProposalAdjudicationWorkspace:
        return context.review.proposal_adjudication_workspace(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            artifact_store=context.artifact_store,
        )

    @router.post(
        path + "/membership",
        response_model=ProposalAdjudicationWorkspace,
        operation_id="changeProposalMembership",
    )
    def membership(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        body: ProposalMembershipChange,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ProposalAdjudicationWorkspace:
        return context.review.mutate_proposal_adjudication(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            body=body,
            item_id=None,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            artifact_store=context.artifact_store,
        )

    @router.put(
        path + "/{item_id}",
        response_model=ProposalAdjudicationWorkspace,
        operation_id="writeProposalDecision",
    )
    def decision(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        item_id: uuid.UUID,
        body: ProposalDecisionWrite,
        request: Request,
        idempotency_key: IdempotencyKey,
        principal: Principal = Depends(csrf_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> ProposalAdjudicationWorkspace:
        return context.review.mutate_proposal_adjudication(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            body=body,
            item_id=item_id,
            idempotency_key=idempotency_key,
            request_id=request.state.request_id,
            artifact_store=context.artifact_store,
        )
