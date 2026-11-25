"""Local single-page-app origin: CORS and CSRF-Origin acceptance for browser auth.

Local frontend<->backend auth is a same-site loopback topology (SPA at http://localhost:5173,
API at http://localhost:8000). These tests pin the two backend guarantees the topology relies on:
the frontend origin is auto-allowed in non-production only, and both the CORS layer and the CSRF
Origin check accept credentialed browser calls from it. Cookies stay Lax/Secure/__Host-.
"""

from __future__ import annotations

import httpx
import pytest

from review_platform.settings import LOCAL_FRONTEND_DEV_ORIGINS, Settings
from tests.support.clients import csrf, login
from tests.support.identities import AdminIdentity

LOCAL_FRONTEND_ORIGIN = "http://localhost:5173"


def _production_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "database_url": "postgresql+psycopg://app:pw@db/app",
        "migration_database_url": "postgresql+psycopg://mig:pw@db/app",
        "session_hmac_key": "prod-session-key-0000000000000000000000000",
        "activation_hmac_key": "prod-activation-key-00000000000000000000",
        "rate_limit_hmac_key": "prod-rate-limit-key-00000000000000000000",
        "audit_hmac_key": "prod-audit-key-000000000000000000000000000",
        "cookie_secure": True,
        "allowed_origins": ("https://app.review.example",),
        "allowed_hosts": ("app.review.example",),
    }
    base.update(overrides)
    return Settings(_env_file=None, **base)  # type: ignore[arg-type]


@pytest.mark.no_db
def test_local_frontend_origin_auto_allowed_in_dev() -> None:
    settings = Settings(
        _env_file=None, environment="development", allowed_origins=("https://localhost",)
    )
    assert LOCAL_FRONTEND_ORIGIN in LOCAL_FRONTEND_DEV_ORIGINS
    assert LOCAL_FRONTEND_ORIGIN in settings.origin_strings


@pytest.mark.no_db
def test_local_frontend_origin_not_duplicated_when_already_listed() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        allowed_origins=(LOCAL_FRONTEND_ORIGIN,),
    )
    assert settings.origin_strings.count(LOCAL_FRONTEND_ORIGIN) == 1


@pytest.mark.no_db
def test_local_frontend_origin_absent_in_production() -> None:
    settings = _production_settings()
    assert LOCAL_FRONTEND_ORIGIN not in settings.origin_strings


@pytest.mark.anyio
async def test_cors_preflight_allows_local_frontend_origin(client: httpx.AsyncClient) -> None:
    response = await client.options(
        "/api/v1/auth/logout",
        headers={
            "Origin": LOCAL_FRONTEND_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-csrf-token",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == LOCAL_FRONTEND_ORIGIN
    assert response.headers["access-control-allow-credentials"] == "true"


@pytest.mark.anyio
async def test_me_accepted_from_local_frontend_origin(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    await login(client, admin.email, admin.password)
    response = await client.get("/api/v1/auth/me", headers={"Origin": LOCAL_FRONTEND_ORIGIN})
    assert response.status_code == 200
    # The credentialed frontend origin is echoed on the actual response, not just the preflight.
    assert response.headers["access-control-allow-origin"] == LOCAL_FRONTEND_ORIGIN


@pytest.mark.anyio
async def test_bodyless_logout_from_local_frontend_origin(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    """The real SPA logout (local origin, CSRF header, no body/Content-Type) succeeds."""

    await login(client, admin.email, admin.password)
    session_csrf = await csrf(client)
    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Origin": LOCAL_FRONTEND_ORIGIN, "X-CSRF-Token": session_csrf},
    )
    assert logout.status_code == 200
    assert logout.headers["access-control-allow-origin"] == LOCAL_FRONTEND_ORIGIN
