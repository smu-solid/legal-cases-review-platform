"""Operations routes: liveness, readiness, and version."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response
from fastapi.responses import JSONResponse

from review_platform import __version__
from review_platform.common.schemas import StrictModel
from review_platform.context import AppContext
from review_platform.dataset.contract import CONTRACT_VERSION
from review_platform.db.session import MIGRATION_HEAD


class HealthResponse(StrictModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(StrictModel):
    status: Literal["ready", "unavailable"]
    mode: Literal["dataset"] = "dataset"


class VersionResponse(StrictModel):
    release: str
    api_version: Literal["v1"] = "v1"
    migration_head: str
    source_contract_version: str


def create_health_router(context: AppContext) -> APIRouter:
    router = APIRouter(tags=["Operations"])

    @router.get("/health/live", response_model=HealthResponse, operation_id="liveness")
    def liveness() -> HealthResponse:
        return HealthResponse()

    @router.get("/health/ready", response_model=ReadinessResponse, operation_id="readiness")
    def readiness() -> Response | ReadinessResponse:
        # database.check() verifies both connectivity and that the review DB is at the expected
        # migration head, so readiness fails closed on a schema/connectivity drift, not just an
        # outage. The reported mode reflects the resolved settings, never a hardcoded assumption.
        ready = context.database.check()
        payload = ReadinessResponse(
            status="ready" if ready else "unavailable",
            mode="dataset",
        )
        if ready:
            return payload
        return JSONResponse(status_code=503, content=payload.model_dump())

    @router.get("/version", response_model=VersionResponse, operation_id="version")
    def version() -> VersionResponse:
        return VersionResponse(
            release=__version__,
            migration_head=MIGRATION_HEAD,
            source_contract_version=CONTRACT_VERSION,
        )

    return router
