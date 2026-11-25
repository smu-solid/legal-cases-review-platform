"""Test reviewer invitation email."""

from __future__ import annotations

import uuid

import httpx
import pytest
from sqlalchemy import func, select

from review_platform.db.models import AuditEvent, RoleGrant, TenantMembership, User
from review_platform.db.session import Database
from review_platform.email.message import EmailDeliveryError, EmailMessage
from review_platform.main import create_app
from review_platform.settings import Settings
from tests.support.clients import login, mutation_headers
from tests.support.identities import AdminIdentity

REVIEWER_EMAIL = "invited-notify@example.test"


class _RecordingSender:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class _FailingSender:
    def send(self, message: EmailMessage) -> None:
        raise EmailDeliveryError("provider unavailable")


async def _client(app: object) -> httpx.AsyncClient:
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)  # type: ignore[arg-type]
    return httpx.AsyncClient(transport=transport, base_url="https://testserver")


async def _invite(
    client: httpx.AsyncClient, admin: AdminIdentity, csrf_token: str, email: str
) -> httpx.Response:
    return await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/reviewers",
        json={"email": email},
        headers=mutation_headers(csrf_token),
    )


def _counts(database: Database) -> tuple[int, int, int, int]:
    with database.session() as session:
        users = session.scalar(
            select(func.count()).select_from(User).where(User.email_normalized == REVIEWER_EMAIL)
        )
        memberships = session.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .join(User, User.id == TenantMembership.user_id)
            .where(User.email_normalized == REVIEWER_EMAIL)
        )
        grants = session.scalar(
            select(func.count())
            .select_from(RoleGrant)
            .join(TenantMembership, TenantMembership.id == RoleGrant.membership_id)
            .join(User, User.id == TenantMembership.user_id)
            .where(User.email_normalized == REVIEWER_EMAIL, RoleGrant.role_code == "reviewer")
        )
        audits = session.scalar(
            select(func.count())
            .select_from(AuditEvent)
            .where(AuditEvent.event_type == "admin.reviewer_invited")
        )
    return users or 0, memberships or 0, grants or 0, audits or 0


@pytest.mark.anyio
async def test_new_pending_invite_sends_exactly_one_email(
    settings: Settings, admin: AdminIdentity, database: Database
) -> None:
    app = create_app(settings)
    recorder = _RecordingSender()
    async with await _client(app) as client:
        app.state.context.email = recorder
        _, csrf_token = await login(client, admin.email, admin.password)
        response = await _invite(client, admin, csrf_token, REVIEWER_EMAIL)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["invitation_email"] == "sent"
    assert len(recorder.sent) == 1
    message = recorder.sent[0]
    assert message.to_address == REVIEWER_EMAIL
    assert settings.app_base_url in message.text_body
    assert "/activate?token=" in message.text_body
    assert "choose a password" in message.text_body.lower()
    assert "password_hash" not in message.text_body and "smtp" not in message.text_body.lower()


@pytest.mark.anyio
async def test_delivery_failure_rolls_back_the_roster_write(
    settings: Settings, admin: AdminIdentity, database: Database
) -> None:
    app = create_app(settings)
    app.state.context.email = _FailingSender()
    async with await _client(app) as client:
        _, csrf_token = await login(client, admin.email, admin.password)
        response = await _invite(client, admin, csrf_token, REVIEWER_EMAIL)

    assert response.status_code == 502, response.text
    body = response.json()
    assert body["code"] == "invitation_email_delivery_failed"
    # No SMTP/body details leak into the problem response.
    assert "provider unavailable" not in response.text

    users, memberships, grants, audits = _counts(database)
    assert (users, memberships, grants, audits) == (0, 0, 0, 0)


@pytest.mark.anyio
async def test_pending_reinvite_resends_without_duplicating_roster_rows(
    settings: Settings, admin: AdminIdentity, database: Database
) -> None:
    app = create_app(settings)
    recorder = _RecordingSender()
    async with await _client(app) as client:
        app.state.context.email = recorder
        _, csrf_token = await login(client, admin.email, admin.password)
        first = await _invite(client, admin, csrf_token, REVIEWER_EMAIL)
        assert first.status_code == 201, first.text
        assert first.json()["invitation_email"] == "sent"

        second = await _invite(client, admin, csrf_token, REVIEWER_EMAIL)
        assert second.status_code == 201, second.text
        assert second.json()["invitation_email"] == "resent"

    assert len(recorder.sent) == 2
    assert first.json()["user_id"] == second.json()["user_id"]
    assert first.json()["membership_id"] == second.json()["membership_id"]

    users, memberships, grants, _audits = _counts(database)
    assert (users, memberships, grants) == (1, 1, 1)


@pytest.mark.anyio
async def test_already_active_reviewer_receives_no_email(
    settings: Settings, admin: AdminIdentity, database: Database
) -> None:
    # Each phase uses its own app instance (mirrors test_reviewer_invite_only_lifecycle.py) so a
    # dev-header identity switch never has to contend with a persistent client-level header set by
    # an earlier login on the same client.
    invite_app = create_app(settings)
    recorder = _RecordingSender()
    invite_app.state.context.email = recorder
    async with await _client(invite_app) as client:
        _, csrf_token = await login(client, admin.email, admin.password)
        invited = await _invite(client, admin, csrf_token, REVIEWER_EMAIL)
    assert invited.status_code == 201, invited.text
    user_id = invited.json()["user_id"]

    from urllib.parse import parse_qs, urlparse

    from tests.support.clients import csrf
    from tests.support.identities import TEST_PASSWORD

    link = next(word for word in recorder.sent[0].text_body.split() if "/activate?token=" in word)
    token = parse_qs(urlparse(link).query)["token"][0]
    activation_app = create_app(settings)
    async with await _client(activation_app) as reviewer_client:
        token_csrf = await csrf(reviewer_client)
        activation = await reviewer_client.post(
            "/api/v1/auth/activate",
            json={"token": token, "password": TEST_PASSWORD},
            headers=mutation_headers(token_csrf),
        )
        assert activation.status_code == 200, activation.text
        signed_in, _ = await login(reviewer_client, REVIEWER_EMAIL, TEST_PASSWORD)
        assert signed_in.status_code == 200
        me = await reviewer_client.get("/api/v1/auth/me")
    assert me.json()["status"] == "active"

    reinvite_app = create_app(settings)
    reinvite_app.state.context.email = recorder
    async with await _client(reinvite_app) as client:
        _, csrf_token = await login(client, admin.email, admin.password)
        again = await _invite(client, admin, csrf_token, REVIEWER_EMAIL)

    assert again.status_code == 201, again.text
    body = again.json()
    assert body["invitation_email"] == "not_sent_already_active"
    assert body["user_status"] == "active"
    assert body["membership_status"] == "active"
    assert body["user_id"] == user_id
    # Only the original invite email was ever sent; the reinvite of an active reviewer sent none.
    assert len(recorder.sent) == 1


@pytest.mark.anyio
async def test_invite_response_never_exposes_email_body_or_smtp_details(
    settings: Settings, admin: AdminIdentity
) -> None:
    app = create_app(settings)
    app.state.context.email = _RecordingSender()
    email = f"body-check-{uuid.uuid4().hex}@example.test"
    async with await _client(app) as client:
        _, csrf_token = await login(client, admin.email, admin.password)
        response = await _invite(client, admin, csrf_token, email)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {
        "user_id",
        "membership_id",
        "user_status",
        "membership_status",
        "invitation_email",
    }
