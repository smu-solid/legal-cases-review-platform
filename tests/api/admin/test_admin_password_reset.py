"""Admin-triggered password reset: RBAC, reauth, tenant scope, and token exposure gating."""

from __future__ import annotations

import uuid

import httpx
import pytest
from pydantic import SecretStr

from review_platform.db.models import Tenant
from review_platform.db.session import Database
from review_platform.email.message import EmailMessage
from review_platform.main import create_app
from review_platform.settings import Settings
from tests.support.accounts import create_activated_user
from tests.support.campaigns import add_review_user
from tests.support.clients import login, mutation_headers
from tests.support.identities import TEST_PASSWORD, AdminIdentity


class _RecordingSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


async def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="https://testserver")


@pytest.mark.anyio
async def test_admin_reset_requires_tenant_admin(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    user_id, _, user_csrf = await create_activated_user(client, admin, email="rbac@example.test")
    # The reviewer holds no admin role, so it cannot trigger a reset (even for itself).
    denied = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/users/{user_id}/password-reset",
        json={"password": TEST_PASSWORD},
        headers=mutation_headers(user_csrf),
    )
    assert denied.status_code == 403


@pytest.mark.anyio
async def test_admin_reset_requires_fresh_reauthentication(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    user_id, _, _ = await create_activated_user(client, admin, email="reauth@example.test")
    _, admin_csrf = await login(client, admin.email, admin.password)
    bad = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/users/{user_id}/password-reset",
        json={"password": "wrong password"},
        headers=mutation_headers(admin_csrf),
    )
    assert bad.status_code == 403
    assert bad.json()["code"] == "reauth_required"


@pytest.mark.anyio
async def test_admin_reset_is_tenant_scoped(
    client: httpx.AsyncClient, admin: AdminIdentity, database: Database
) -> None:
    user_id, _, _ = await create_activated_user(client, admin, email="scoped@example.test")
    with database.session() as session, session.begin():
        other = Tenant(key="other-tenant", name="Other Tenant")
        session.add(other)
        session.flush()
        other_tenant_id = other.id
    _, admin_csrf = await login(client, admin.email, admin.password)
    # The reviewer is not a member of the other tenant, so the reset cannot cross the boundary.
    response = await client.post(
        f"/api/v1/admin/tenants/{other_tenant_id}/users/{user_id}/password-reset",
        json={"password": admin.password},
        headers=mutation_headers(admin_csrf),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_admin_reset_rejects_suspended_account(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    user_id, _, _ = await create_activated_user(client, admin, email="suspended@example.test")
    _, admin_csrf = await login(client, admin.email, admin.password)
    suspend = await client.put(
        f"/api/v1/admin/users/{user_id}/status",
        json={"password": admin.password, "status": "suspended", "reason": "policy"},
        headers=mutation_headers(admin_csrf),
    )
    assert suspend.status_code == 200
    conflict = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/users/{user_id}/password-reset",
        json={"password": admin.password},
        headers=mutation_headers(admin_csrf),
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "user_unusable"


@pytest.mark.anyio
async def test_admin_reset_unknown_user_is_not_found(
    client: httpx.AsyncClient, admin: AdminIdentity
) -> None:
    _, admin_csrf = await login(client, admin.email, admin.password)
    response = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/users/{uuid.uuid4()}/password-reset",
        json={"password": admin.password},
        headers=mutation_headers(admin_csrf),
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_admin_reset_emails_link_and_keeps_token_in_dev(
    settings: Settings, admin: AdminIdentity, database: Database
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="devlink@example.test", role="reviewer"
    )
    user_id = reviewer.user_id
    app = create_app(settings)
    recorder = _RecordingSender()
    async with await _client(app) as client:
        app.state.context.email = recorder  # record only the reset link
        _, admin_csrf = await login(client, admin.email, admin.password)
        response = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/users/{user_id}/password-reset",
            json={"password": admin.password},
            headers=mutation_headers(admin_csrf),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["email_sent"] is True
    assert body["reset_token"]  # non-production keeps the raw token for local testing
    assert [message.to_address for message in recorder.sent] == ["devlink@example.test"]
    assert body["reset_token"] in recorder.sent[0].text_body


@pytest.mark.anyio
async def test_admin_reset_hides_token_in_production(
    settings: Settings, admin: AdminIdentity, database: Database
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="prodlink@example.test", role="reviewer"
    )
    user_id = reviewer.user_id

    prod_app = create_app(
        settings.model_copy(
            update={
                "environment": "production",
                "email_mode": "smtp",
                "email_smtp_host": "smtp.test",
                "email_smtp_username": "mailer",
                "email_smtp_password": SecretStr("smtp-secret"),
                "email_from_address": "no-reply@app.test",
            }
        )
    )
    recorder = _RecordingSender()
    prod_app.state.context.email = recorder

    async with await _client(prod_app) as client:
        _, admin_csrf = await login(client, admin.email, admin.password)
        response = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/users/{user_id}/password-reset",
            json={"password": admin.password},
            headers=mutation_headers(admin_csrf),
        )
    assert response.status_code == 200
    body = response.json()
    assert body["email_sent"] is True
    assert body["reset_token"] is None
    assert [message.to_address for message in recorder.sent] == ["prodlink@example.test"]
