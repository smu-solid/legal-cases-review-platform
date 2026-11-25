from __future__ import annotations

import uuid

import httpx

from tests.support.clients import login
from tests.support.identities import AdminIdentity, ReviewIdentity


async def login_get(
    client: httpx.AsyncClient,
    identity: ReviewIdentity,
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    await login(client, identity.email, identity.password)
    return await client.get(path, params=params or {})


async def admin_get(
    client: httpx.AsyncClient,
    admin: AdminIdentity,
    path: str,
    *,
    params: dict[str, str] | None = None,
) -> httpx.Response:
    await login(client, admin.email, admin.password)
    return await client.get(path, params=params or {})


def progress_path(tenant_id: uuid.UUID) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaign-progress"


def workload_path(tenant_id: uuid.UUID) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/reviewer-workload"


def scope_catalog_path(tenant_id: uuid.UUID) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/scope-catalog"
