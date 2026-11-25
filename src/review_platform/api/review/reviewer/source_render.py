"""Assignment-scoped source-render artifact routes (reviewer-safe sanitized HTML delivery).

Three endpoints share one assignment-scoped authorization chain (see ``source_render_service``):

- ``/source-render``    -> reviewer-safe metadata + same-origin body/anchor URLs;
- ``/source-render/body``   -> the sanitized ``text/html`` artifact, for a sandboxed iframe;
- ``/source-render/anchors``-> the offset-only anchor map.

Each endpoint re-authorizes independently and never trusts a prior request. Body/anchor bytes are
read from the private artifact store and integrity-checked against the metadata digest before
delivery; a missing store, missing file, or digest mismatch fails closed. The sandbox CSP and frame
policy for the HTML body are applied by the application security middleware for the body path.
"""

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

_BASE = "/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render"


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
        operation_id="getAssignmentSourceRender",
    )
    def source_render(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> SourceRenderArtifactMetadata:
        artifact = context.review.source_render_artifact(
            session, tenant_id=tenant_id, assignment_id=assignment_id, principal=principal
        )
        prefix = f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render"
        return source_render_metadata(artifact, prefix=prefix)

    @router.get(
        f"{_BASE}/body",
        operation_id="getAssignmentSourceRenderBody",
        response_class=Response,
        responses={200: {"content": {"text/html": {}}}},
    )
    def source_render_body(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> Response:
        artifact = context.review.source_render_artifact(
            session, tenant_id=tenant_id, assignment_id=assignment_id, principal=principal
        )
        body = read_verified_artifact(
            context.artifact_store,
            object_key=artifact.object_key,
            kind="body",
            expected_digest=artifact.content_digest,
        )
        return Response(content=body, media_type="text/html; charset=utf-8")

    @router.get(
        f"{_BASE}/anchors",
        response_model=SourceRenderAnchorMap,
        operation_id="getAssignmentSourceRenderAnchors",
    )
    def source_render_anchors(
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal = Depends(principal_dependency),  # noqa: B008
        session: Session = Depends(session_dependency),  # noqa: B008
    ) -> SourceRenderAnchorMap:
        artifact = context.review.source_render_artifact(
            session, tenant_id=tenant_id, assignment_id=assignment_id, principal=principal
        )
        raw = read_verified_artifact(
            context.artifact_store,
            object_key=artifact.object_key,
            kind="anchors",
            expected_digest=artifact.anchor_map_digest,
        )
        payload = json.loads(raw)
        anchors = [SourceRenderAnchor(**anchor) for anchor in payload.get("anchors", [])]
        return SourceRenderAnchorMap(render_artifact_id=artifact.id, anchors=anchors)
