from datetime import timedelta

import pytest
from sqlalchemy import select

from review_platform.auth.principal import now_utc
from review_platform.db.models import ServerSession, User, UserActivationChallenge
from tests.support.clients import csrf, login, mutation_headers
from tests.support.identities import TEST_PASSWORD


@pytest.mark.anyio
async def test_password_session_expiry_revocation_and_cookie_policy(client, admin, database):
    response, token = await login(client, admin.email, admin.password)
    assert response.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=lax" in cookie
    with database.session() as session, session.begin():
        row = session.scalar(select(ServerSession).where(ServerSession.user_id == admin.user_id))
        assert row is not None
        row.idle_expires_at = now_utc() - timedelta(seconds=1)
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    response, token = await login(client, admin.email, admin.password)
    assert response.status_code == 200
    assert (
        await client.post("/api/v1/auth/logout", headers=mutation_headers(token))
    ).status_code == 200
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.anyio
async def test_wrong_password_does_not_authenticate_and_attempts_persist(client, admin, database):
    token = await csrf(client)
    for _ in range(20):
        response = await client.post(
            "/api/v1/auth/login",
            json={"email": admin.email, "password": "wrong-password"},
            headers=mutation_headers(token),
        )
        assert response.status_code == 401
    limited = await client.post(
        "/api/v1/auth/login",
        json={"email": admin.email, "password": admin.password},
        headers=mutation_headers(token),
    )
    assert limited.status_code == 429
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.anyio
async def test_invitation_activation_is_one_time_and_password_reset_revokes_sessions(
    client, admin, database, settings
):
    from httpx import ASGITransport, AsyncClient

    from review_platform.main import create_app
    from tests.support.accounts import create_activated_user

    user_id, _, user_csrf = await create_activated_user(
        client, admin, email="password-flow@example.test"
    )
    old_cookie = client.cookies.get("__Host-review_session")
    response, admin_csrf = await login(client, admin.email, admin.password)
    assert response.status_code == 200
    reset = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/users/{user_id}/password-reset",
        json={"password": admin.password},
        headers=mutation_headers(admin_csrf),
    )
    assert reset.status_code == 200
    token = reset.json()["reset_token"]
    done = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": "a-new-password-value"},
        headers=mutation_headers(admin_csrf),
    )
    assert done.status_code == 200
    reused = await client.post(
        "/api/v1/auth/reset-password",
        json={"token": token, "password": TEST_PASSWORD},
        headers=mutation_headers(admin_csrf),
    )
    assert reused.status_code == 400
    app = create_app(settings)
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="https://testserver"
        ) as old_client:
            old_client.cookies.set("__Host-review_session", old_cookie)
            assert (await old_client.get("/api/v1/auth/me")).status_code == 401
    finally:
        app.state.context.database.dispose()
    assert (await login(client, "password-flow@example.test", TEST_PASSWORD))[0].status_code == 401
    assert (await login(client, "password-flow@example.test", "a-new-password-value"))[
        0
    ].status_code == 200


@pytest.mark.anyio
async def test_expired_activation_and_oversize_unicode_password_fail_safely(
    client, admin, database, settings
):
    from review_platform.auth.service import AuthService

    with database.session() as session, session.begin():
        user = User(
            email_normalized="pending@example.test", display_name="Pending", status="pending"
        )
        session.add(user)
        session.flush()
        token = AuthService(settings).issue_activation(session, user.id)
    csrf_token = await csrf(client)
    oversized = await client.post(
        "/api/v1/auth/activate",
        json={"token": token, "password": "判" * 400},
        headers=mutation_headers(csrf_token),
    )
    assert oversized.status_code == 422
    with database.session() as session, session.begin():
        challenge = session.scalar(select(UserActivationChallenge))
        challenge.expires_at = now_utc() - timedelta(seconds=1)
    expired = await client.post(
        "/api/v1/auth/activate",
        json={"token": token, "password": TEST_PASSWORD},
        headers=mutation_headers(csrf_token),
    )
    assert expired.status_code == 400
