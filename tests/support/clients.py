from __future__ import annotations

from contextlib import AsyncExitStack

import httpx

from review_platform.main import create_app
from review_platform.settings import Settings
from tests.support.identities import ReviewIdentity


async def csrf(client: httpx.AsyncClient) -> str:
    response = await client.get("/api/v1/auth/csrf")
    assert response.status_code == 200
    return str(response.json()["csrf_token"])


def mutation_headers(csrf_token: str, *, origin: str = "https://testserver") -> dict[str, str]:
    return {
        "Origin": origin,
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf_token,
    }


async def login(client: httpx.AsyncClient, email: str, password: str) -> tuple[httpx.Response, str]:
    """Login."""

    csrf_token = await csrf(client)
    response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
        headers=mutation_headers(csrf_token),
    )
    return response, csrf_token


async def open_clients(
    stack: AsyncExitStack, settings: Settings, count: int
) -> list[httpx.AsyncClient]:
    app = create_app(settings)
    # Register before clients so their async exits run before the pools are disposed.
    stack.callback(app.state.context.database.dispose)
    clients: list[httpx.AsyncClient] = []
    for _ in range(count):
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="https://testserver",
        )
        clients.append(await stack.enter_async_context(client))
    return clients


async def authenticate(client: httpx.AsyncClient, identity: ReviewIdentity) -> str:
    response, csrf_token = await login(client, identity.email, identity.password)
    assert response.status_code == 200
    return csrf_token
