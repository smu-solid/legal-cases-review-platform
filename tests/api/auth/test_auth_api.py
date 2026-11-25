from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from review_platform.db.models import AuditEvent
from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.accounts import create_activated_user
from tests.support.campaigns import add_review_user
from tests.support.clients import login, mutation_headers
from tests.support.identities import TEST_PASSWORD, AdminIdentity


@pytest.mark.anyio
async def test_me_and_logout(client: httpx.AsyncClient, admin: AdminIdentity) -> None:
    first, csrf_one = await login(client, admin.email, admin.password)
    assert first.status_code == 200

    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["global_roles"] == ["super_admin"]
    assert me.json()["global_capabilities"] == ["global:admin"]
    assert me.json()["memberships"][0]["roles"] == ["user_admin"]
    assert me.json()["session_expires_at"] is not None

    logout = await client.post("/api/v1/auth/logout", json={}, headers=mutation_headers(csrf_one))
    assert logout.status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.anyio
async def test_logout_accepts_bodyless_request_without_content_type(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    """The SPA logs out with a body-less POST and no Content-Type; it must not 415."""

    _, session_csrf = await login(client, admin.email, admin.password)
    # Deliberately omit Content-Type and any body, matching the real fetch-based logout.
    logout = await client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": session_csrf},
    )
    assert logout.status_code == 200
    assert logout.json()["status"] == "logged_out"


@pytest.mark.anyio
async def test_bodyless_mutation_still_enforces_csrf_and_origin(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    """Dropping the JSON media-type gate for empty bodies must not weaken CSRF/Origin."""

    _, session_csrf = await login(client, admin.email, admin.password)
    bad_origin = await client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://evil.invalid", "X-CSRF-Token": session_csrf},
    )
    assert bad_origin.status_code == 403
    bad_csrf = await client.post(
        "/api/v1/auth/logout",
        headers={"Origin": "https://testserver", "X-CSRF-Token": "wrong-token"},
    )
    assert bad_csrf.status_code == 403
    # The identity is unaffected by the rejected mutation attempts.
    assert (await client.get("/api/v1/auth/me")).status_code == 200


@pytest.mark.anyio
async def test_csrf_origin_and_content_type_fail_closed(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    _, session_csrf = await login(client, admin.email, admin.password)
    bad_origin = await client.post(
        "/api/v1/auth/logout",
        json={},
        headers=mutation_headers(session_csrf, origin="https://evil.invalid"),
    )
    assert bad_origin.status_code == 403
    bad_token = await client.post(
        "/api/v1/auth/logout", json={}, headers=mutation_headers("wrong-token")
    )
    assert bad_token.status_code == 403
    bad_type = await client.post(
        "/api/v1/auth/logout",
        content="not-json",
        headers={"Origin": "https://testserver", "X-CSRF-Token": session_csrf},
    )
    assert bad_type.status_code == 415
    client.cookies.set("__Host-review_csrf", "tampered", domain="testserver", path="/")
    bound = await client.post("/api/v1/auth/logout", json={}, headers=mutation_headers("tampered"))
    assert bound.status_code == 403


@pytest.mark.anyio
async def test_csrf_remains_valid_across_tabs(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    _, first_csrf = await login(client, admin.email, admin.password)
    rotated = await client.get("/api/v1/auth/csrf")
    assert rotated.json()["csrf_token"] == first_csrf


@pytest.mark.anyio
async def test_tenant_roles_reauthentication_and_authorization(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    user_id, membership_id, user_csrf = await create_activated_user(client, admin)
    denied = await client.put(
        f"/api/v1/admin/memberships/{membership_id}/role",
        json={"password": TEST_PASSWORD, "role": "reviewer", "active": True},
        headers=mutation_headers(user_csrf),
    )
    assert denied.status_code == 403

    _, admin_csrf = await login(client, admin.email, admin.password)
    bad_reauth = await client.put(
        f"/api/v1/admin/memberships/{membership_id}/role",
        json={"password": "wrong", "role": "reviewer", "active": True},
        headers=mutation_headers(admin_csrf),
    )
    assert bad_reauth.status_code == 403
    granted = await client.put(
        f"/api/v1/admin/memberships/{membership_id}/role",
        json={"password": admin.password, "role": "reviewer", "active": True},
        headers=mutation_headers(admin_csrf),
    )
    assert granted.status_code == 200
    invalid = await client.put(
        f"/api/v1/admin/memberships/{membership_id}/role",
        json={"password": admin.password, "role": "super_admin", "active": True},
        headers=mutation_headers(admin_csrf),
    )
    assert invalid.status_code == 422
    assert user_id


@pytest.mark.anyio
async def test_final_superuser_protection_and_global_grant(
    client: httpx.AsyncClient, admin: AdminIdentity, database: Database, settings: Settings
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="promoted@example.test", role="reviewer"
    )
    user_id = reviewer.user_id
    _, admin_csrf = await login(client, admin.email, admin.password)
    protected = await client.put(
        f"/api/v1/admin/users/{admin.user_id}/status",
        json={"password": admin.password, "status": "suspended", "reason": "rotation"},
        headers=mutation_headers(admin_csrf),
    )
    assert protected.status_code == 409
    assert protected.json()["code"] == "final_superuser_protected"

    temporary_grant = await client.put(
        f"/api/v1/admin/users/{user_id}/global-role",
        json={
            "password": admin.password,
            "active": True,
            "reason": "planned rotation",
            "expires_at": (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        },
        headers=mutation_headers(admin_csrf),
    )
    assert temporary_grant.status_code == 200
    still_protected = await client.put(
        f"/api/v1/admin/users/{admin.user_id}/status",
        json={"password": admin.password, "status": "suspended", "reason": "rotation"},
        headers=mutation_headers(admin_csrf),
    )
    assert still_protected.status_code == 409
    durable_grant = await client.put(
        f"/api/v1/admin/users/{user_id}/global-role",
        json={"password": admin.password, "active": True, "reason": "durable rotation"},
        headers=mutation_headers(admin_csrf),
    )
    assert durable_grant.status_code == 200
    suspended = await client.put(
        f"/api/v1/admin/users/{admin.user_id}/status",
        json={"password": admin.password, "status": "suspended", "reason": "rotation"},
        headers=mutation_headers(admin_csrf),
    )
    assert suspended.status_code == 200
    disabled = await client.get("/api/v1/auth/me")
    assert disabled.status_code == 401
    assert disabled.json()["code"] == "authentication_required"


@pytest.mark.anyio
async def test_audit_events_created_without_secret_material(
    client: httpx.AsyncClient, admin: AdminIdentity, db_session: object, settings: Settings
) -> None:
    user_id, _, _ = await create_activated_user(client, admin)
    session = db_session
    assert hasattr(session, "scalars")
    events = list(session.scalars(select(AuditEvent).order_by(AuditEvent.sequence)))  # type: ignore[union-attr]
    assert events
    serialized = " ".join(str(event.payload_json) for event in events)
    assert "correct horse" not in serialized
    assert "csrf_token" not in serialized
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    previous = "0" * 64
    key = settings.audit_hmac_key.get_secret_value()  # type: ignore[union-attr]
    for event in events:
        canonical = json.dumps(
            {
                "sequence": event.sequence,
                "actor_user_id": str(event.actor_user_id) if event.actor_user_id else None,
                "actor_type": event.actor_type,
                "event_type": event.event_type,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "request_id": event.request_id,
                "occurred_at": event.occurred_at.isoformat(),
                "payload": event.payload_json,
                "prev_hash": previous,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        assert event.prev_hash == previous
        assert (
            event.event_hash
            == hmac.new(key.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        )
        previous = event.event_hash
    assert user_id
