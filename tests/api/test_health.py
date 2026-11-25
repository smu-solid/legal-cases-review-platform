from __future__ import annotations

import json

import httpx
import pytest

import review_platform.main as main_module
from review_platform.dataset.contract import CONTRACT_VERSION
from review_platform.db.session import MIGRATION_HEAD
from review_platform.main import create_app
from review_platform.review import schemas as review_schemas
from review_platform.review.schemas.assignment import AssignmentSummary
from review_platform.review.schemas.bundle import AssignmentBundle
from review_platform.settings import Settings


def test_minimal_module_import() -> None:
    paths = set(create_app(Settings(_env_file=None)).openapi()["paths"])
    assert {"/health/live", "/health/ready", "/version"} <= paths


def test_review_schema_package_preserves_compatibility_exports() -> None:
    assert review_schemas.AssignmentSummary is AssignmentSummary
    assert review_schemas.AssignmentBundle is AssignmentBundle
    assert hasattr(review_schemas, "ReviewItemAnswerInput")


@pytest.mark.anyio
async def test_operational_endpoints_and_security_headers(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    log_records: list[dict[str, object]] = []
    monkeypatch.setattr(
        main_module.logger,
        "log",
        lambda _level, message: log_records.append(json.loads(message)),
    )
    liveness = await client.get(
        "/health/live",
        headers={
            "X-Request-ID": "request_12345678",
            "X-Correlation-ID": "correlation_12345678",
            "Origin": "https://testserver",
        },
    )
    assert liveness.status_code == 200
    assert liveness.json() == {"status": "ok"}
    assert liveness.headers["x-request-id"] == "request_12345678"
    assert liveness.headers["x-correlation-id"] == "correlation_12345678"
    assert liveness.headers["x-content-type-options"] == "nosniff"
    assert liveness.headers["x-frame-options"] == "DENY"
    assert liveness.headers["access-control-expose-headers"] == (
        "X-Request-ID, X-Correlation-ID, ETag"
    )

    completed = log_records[-1]
    assert completed["event"] == "request.completed"
    assert completed["level"] == "info"
    assert completed["severity"] == "INFO"
    assert completed["request_id"] == "request_12345678"
    assert completed["correlation_id"] == "correlation_12345678"
    assert completed["method"] == "GET"
    assert completed["route"] == "/health/live"
    assert completed["status_code"] == 200
    assert isinstance(completed["duration_ms"], (int, float))
    assert "timestamp" in completed
    # No sensitive request data leaks into the structured access-log event.
    assert not any(
        key in completed for key in ("authorization", "cookie", "set-cookie", "password")
    )

    replaced = await client.get(
        "/health/live",
        headers={"X-Request-ID": "bad", "X-Correlation-ID": "also bad"},
    )
    assert replaced.headers["x-request-id"] != "bad"
    assert replaced.headers["x-correlation-id"] == replaced.headers["x-request-id"]

    readiness = await client.get("/health/ready")
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready", "mode": "dataset"}

    version = await client.get("/version")
    assert version.json() == {
        "release": "0.0.0",
        "api_version": "v1",
        "migration_head": MIGRATION_HEAD,
        "source_contract_version": CONTRACT_VERSION,
    }


@pytest.mark.anyio
async def test_version_reports_operational_identity_without_secrets(
    client: httpx.AsyncClient,
) -> None:
    # Operators need to confirm the running image's schema head, source contract, and mode without
    # any endpoint exposing a path, host, or credential.
    version = (await client.get("/version")).json()
    assert version["migration_head"] == MIGRATION_HEAD
    assert version["source_contract_version"] == CONTRACT_VERSION
    readiness = (await client.get("/health/ready")).json()
    assert readiness["mode"] == "dataset"

    combined = json.dumps(version) + json.dumps(readiness)
    for leak in ("://", "/Users/", "password", "secret", "hmac", "database_url", "postgresql"):
        assert leak not in combined.lower(), leak


@pytest.mark.anyio
async def test_openapi_contains_approved_surfaces(client: httpx.AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    paths = set(response.json()["paths"])
    assert paths == {
        "/health/live",
        "/health/ready",
        "/version",
        "/api/v1/auth/csrf",
        "/api/v1/auth/logout",
        "/api/v1/auth/login",
        "/api/v1/auth/activate",
        "/api/v1/auth/reset-password",
        "/api/v1/auth/me",
        "/api/v1/admin/tenants/{tenant_id}/users/{user_id}/password-reset",
        "/api/v1/admin/memberships/{membership_id}/role",
        "/api/v1/admin/users/{user_id}/status",
        "/api/v1/admin/users/{user_id}/global-role",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/complete",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/reviewers",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/reviewers/{reviewer_id}",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/allocation-summary",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/pool-cases",
        "/api/v1/admin/tenants/{tenant_id}/review/campaign-case-filters/apply",
        "/api/v1/admin/tenants/{tenant_id}/review/campaign-case-ids/apply",
        "/api/v1/admin/tenants/{tenant_id}/review/campaign-case-filters/corrections",
        "/api/v1/admin/tenants/{tenant_id}/review/campaign-case-filters/export",
        "/api/v1/admin/tenants/{tenant_id}/review/campaign-availability",
        "/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases",
        "/api/v1/admin/tenants/{tenant_id}/review/import-synthetic",
        "/api/v1/admin/tenants/{tenant_id}/review/scope-catalog",
        "/api/v1/admin/tenants/{tenant_id}/review/submissions",
        "/api/v1/admin/tenants/{tenant_id}/review/agreement-metrics",
        "/api/v1/admin/tenants/{tenant_id}/review/campaign-progress",
        "/api/v1/admin/tenants/{tenant_id}/review/reviewer-workload",
        "/api/v1/admin/tenants/{tenant_id}/review/assignments/{assignment_id}/request-revision",
        "/api/v1/admin/tenants/{tenant_id}/reviewers",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/subjects/preview",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/preview",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/{run_id}",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/{run_id}/matrix",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/"
        "{run_id}/reviewer-workloads",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/"
        "{run_id}/subject-coverage",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/{run_id}/publish",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/publish",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/{run_id}/discard",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/"
        "incremental-preview",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/incremental",
        "/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs/"
        "{run_id}/publish-incremental",
        "/api/v1/tenants/{tenant_id}/review/queue",
        "/api/v1/tenants/{tenant_id}/review/campaigns",
        "/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases",
        "/api/v1/tenants/{tenant_id}/review/claim",
        "/api/v1/tenants/{tenant_id}/review/assignments",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/renew",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/release",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/reopen",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/bundle",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render/body",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render/anchors",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/draft",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/submit",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/draft",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/submit",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/case-submit",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/proposals/{proposal_id}/{state}",
        "/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/proposals/{proposal_id}/duplicate-check",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/proposal-items",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/proposal-items/membership",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/proposal-items/{item_id}",
        "/api/v1/tenants/{tenant_id}/review/adjudications",
        "/api/v1/tenants/{tenant_id}/review/adjudication-campaigns",
        "/api/v1/tenants/{tenant_id}/review/adjudication-campaigns/{campaign_id}/cases",
        "/api/v1/tenants/{tenant_id}/review/adjudication-campaigns/{campaign_id}/cases/neighbors",
        "/api/v1/tenants/{tenant_id}/review/adjudications/claim",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/case-workspace",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/bundle",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/grouped-bundle",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/source-render",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/source-render/body",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/source-render/anchors",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/draft",
        "/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/submit",
    }
    serialized = response.text
    assert "source_path" not in serialized
    assert '"AdjudicationCase":' not in serialized
    assert "AssignmentBundle" in serialized
    assert "ReviewSubjectResponse" in serialized
    assert "ReviewerGroupingBundle" in serialized
    assert "ReviewItemAnswerInput" in serialized
    assert "AdjudicationGroupedBundle" in serialized

    operation_ids = {
        operation["operationId"]
        for path_item in response.json()["paths"].values()
        for operation in path_item.values()
    }
    assert {
        "importSyntheticReviewCampaign",
        "previewAllocationRun",
        "persistIncrementalAllocationRun",
        "listTenantReviewers",
        "listReviewQueue",
        "getOwnAssignmentBundle",
        "getGroupedReviewBundle",
        "getAdjudicationGroupedBundle",
        "listAdjudicationCampaigns",
        "listAdjudicationCampaignCases",
        "getAdjudicationCaseNeighbors",
        "getAdjudicationCaseWorkspace",
        "getAdjudicationSourceRenderBody",
        "saveReviewItemAnswerDraft",
        "saveAdjudicationDraft",
        "submitAdjudicationDecision",
    } <= operation_ids

    by_operation_id = {
        operation["operationId"]: operation
        for path_item in response.json()["paths"].values()
        for operation in path_item.values()
    }
    lock_version_responses = {
        "claimReviewUnit": "201",
        "getOwnAssignmentBundle": "200",
        "getGroupedReviewBundle": "200",
        "renewAssignmentLease": "200",
        "releaseAssignment": "200",
        "saveAnnotationDraft": "200",
        "submitAnnotation": "201",
        "saveReviewItemAnswerDraft": "200",
        "submitReviewItemAnswer": "201",
    }
    for operation_id, status_code in lock_version_responses.items():
        headers = by_operation_id[operation_id]["responses"][status_code]["headers"]
        assert headers["ETag"]["schema"]["pattern"] == r'^"[1-9][0-9]*"$'
        assert headers["Cache-Control"]["schema"]["const"] == "no-store"

    claim_properties = response.json()["components"]["schemas"]["ClaimRequest"]["properties"]
    assert "next eligible unit" in claim_properties["review_unit_id"]["description"]
    claim_descriptions = " ".join(
        prop.get("description", "") for prop in claim_properties.values()
    ).lower()
    assert "batch" not in claim_descriptions
    assert "field allowlist" not in claim_descriptions


@pytest.mark.anyio
async def test_unavailable_database_unmatched_route_and_unhandled_error() -> None:
    unavailable_app = create_app(
        Settings(
            environment="test",
            database_url=None,
            session_hmac_key="s" * 32,
            activation_hmac_key="a" * 32,
            allowed_origins=("https://testserver",),
            allowed_hosts=("testserver",),
        )
    )
    transport = httpx.ASGITransport(app=unavailable_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as isolated:
        readiness = await isolated.get("/health/ready")
        assert readiness.status_code == 503
        csrf_response = await isolated.get("/api/v1/auth/csrf")
        assert csrf_response.status_code == 503
        assert csrf_response.json()["code"] == "service_unavailable"
        missing = await isolated.get("/missing-route")
        assert missing.status_code == 404
        assert missing.headers["content-type"].startswith("application/problem+json")
        assert missing.json()["code"] == "not_found"
        assert missing.json()["request_id"] == missing.headers["x-request-id"]
        assert missing.headers["x-correlation-id"] == missing.headers["x-request-id"]

        wrong_method = await isolated.post("/health/live")
        assert wrong_method.status_code == 405
        assert wrong_method.headers["content-type"].startswith("application/problem+json")
        assert wrong_method.json()["code"] == "method_not_allowed"

        def broken_check() -> bool:
            raise RuntimeError("forced readiness failure")

        unavailable_app.state.context.database.check = broken_check
        internal = await isolated.get("/health/ready")
        assert internal.status_code == 500
        assert internal.json()["code"] == "internal_error"


@pytest.mark.anyio
async def test_loopback_host_is_accepted_outside_production() -> None:
    loopback_app = create_app(
        Settings(
            environment="development",
            database_url=None,
            session_hmac_key="s" * 32,
            activation_hmac_key="a" * 32,
            allowed_origins=("https://localhost",),
            allowed_hosts=("localhost",),
        )
    )
    transport = httpx.ASGITransport(app=loopback_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as loopback:
        response = await loopback.get("/health/live")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
