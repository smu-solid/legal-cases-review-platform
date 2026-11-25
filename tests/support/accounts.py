"""Shared HTTP workflow scenario support."""

from __future__ import annotations

import uuid

import httpx
from sqlalchemy import select

from review_platform.db.models import User
from tests.support.clients import login, mutation_headers
from tests.support.identities import TEST_PASSWORD, AdminIdentity


async def create_activated_user(
    client: httpx.AsyncClient, admin: AdminIdentity, *, email: str = "reviewer@example.test"
) -> tuple[uuid.UUID, uuid.UUID, str]:
    response, admin_csrf = await login(client, admin.email, admin.password)
    assert response.status_code == 200
    invited = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/reviewers",
        json={"email": email, "display_name": "Review User"},
        headers=mutation_headers(admin_csrf),
    )
    assert invited.status_code == 201
    transport = client._transport
    app = transport.app
    with app.state.context.database.session() as session, session.begin():
        user = session.scalar(select(User).where(User.email_normalized == email))
        assert user is not None
        token = app.state.context.auth.issue_activation(session, user.id)
    activated = await client.post(
        "/api/v1/auth/activate",
        json={"token": token, "password": TEST_PASSWORD},
        headers=mutation_headers(admin_csrf),
    )
    assert activated.status_code == 200, activated.text
    response, user_csrf = await login(client, email, TEST_PASSWORD)
    assert response.status_code == 200, response.text
    me = (await client.get("/api/v1/auth/me")).json()
    return uuid.UUID(me["id"]), uuid.UUID(me["memberships"][0]["membership_id"]), user_csrf
