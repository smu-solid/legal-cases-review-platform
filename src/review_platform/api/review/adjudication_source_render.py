"""Adjudication-authorized façade over the shared source-render artifact service."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from review_platform.api.review.source_render_support import (
    read_verified_artifact,
    source_render_metadata,
)
from review_platform.api.review.support import ReviewContext
from review_platform.auth.service import Principal
from review_platform.review.schemas import (
    SourceRenderAnchor,
    SourceRenderAnchorMap,
    SourceRenderArtifactMetadata,
)

_BASE = "/tenants/{tenant_id}/review/adjudications/{adjudication_id}/source-render"


def register_routes(
    router: APIRouter,
    context: ReviewContext,
    *,
    session_dependency: Callable[..., Any],
    principal_dependency: Callable[..., Any],
    csrf_dependency: Callable[..., Any],
) -> None:
    del csrf_dependency

    @router.get(
        _BASE,
        response_model=SourceRenderArtifactMetadata,
        operation_id="getAdjudicationSourceRender",
    )
    def source_render(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> SourceRenderArtifactMetadata:
        resolved = context.review.adjudication_source_render_artifact(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
        )
        prefix = f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/source-render"
        return source_render_metadata(resolved.artifact, prefix=prefix)

    @router.get(
        f"{_BASE}/body",
        operation_id="getAdjudicationSourceRenderBody",
        response_class=Response,
        responses={200: {"content": {"text/html": {}}}},
    )
    def source_render_body(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        review_unit_id: uuid.UUID | None = None,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> Response:
        resolved = context.review.adjudication_source_render_artifact(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
            review_unit_id=review_unit_id,
        )
        body = read_verified_artifact(
            context.artifact_store,
            object_key=resolved.artifact.object_key,
            kind="body",
            expected_digest=resolved.artifact.content_digest,
        )
        return Response(content=body, media_type="text/html; charset=utf-8")

    @router.get(
        f"{_BASE}/anchors",
        response_model=SourceRenderAnchorMap,
        operation_id="getAdjudicationSourceRenderAnchors",
    )
    def source_render_anchors(
        tenant_id: uuid.UUID,
        adjudication_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> SourceRenderAnchorMap:
        resolved = context.review.adjudication_source_render_artifact(
            session,
            tenant_id=tenant_id,
            adjudication_id=adjudication_id,
            principal=principal,
        )
        raw = read_verified_artifact(
            context.artifact_store,
            object_key=resolved.artifact.object_key,
            kind="anchors",
            expected_digest=resolved.artifact.anchor_map_digest,
        )
        payload = json.loads(raw)
        return SourceRenderAnchorMap(
            render_artifact_id=resolved.artifact.id,
            anchors=[SourceRenderAnchor(**anchor) for anchor in payload.get("anchors", [])],
        )
