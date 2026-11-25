from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest

from review_platform.db.session import Database
from review_platform.review.grouping import (
    DEFAULT_ATOMIC_GROUP_ID,
    GROUP_DEFINITIONS,
    SUPPORTED_REVIEW_KINDS,
)
from review_platform.settings import Settings
from tests.support.admin_stats import admin_get, login_get, scope_catalog_path
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_scope_catalog_unauthenticated(settings: Settings, admin: AdminIdentity) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await client.get(scope_catalog_path(admin.tenant_id))
    assert r.status_code == 401


@pytest.mark.anyio
async def test_scope_catalog_reviewer_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="scope-reviewer@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(client, reviewer, scope_catalog_path(admin.tenant_id))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_scope_catalog_wrong_tenant_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="scope-mgr-wrong@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(client, manager, scope_catalog_path(uuid.uuid4()))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_scope_catalog_manager_sees_closed_allowlist(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="scope-mgr@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await authenticate(client, manager)
        r = await client.get(scope_catalog_path(admin.tenant_id))

    assert r.status_code == 200
    body = r.json()
    assert body["contract_version"] == "campaign-scope-catalog/v1"
    assert str(body["tenant_id"]) == str(admin.tenant_id)
    # Groups mirror the backend-owned closed allowlist, in declared order, excluding the
    # additional_fields catch-all: importers fail closed on unmapped columns, so it can never
    # hold a selectable field and would only render as a permanently-empty campaign scope choice.
    assert [g["group_id"] for g in body["groups"]] == [
        g.group_id for g in GROUP_DEFINITIONS if g.group_id != DEFAULT_ATOMIC_GROUP_ID
    ]
    assert DEFAULT_ATOMIC_GROUP_ID not in [g["group_id"] for g in body["groups"]]
    assert [g["order"] for g in body["groups"]] == sorted(g["order"] for g in body["groups"])
    # Review kinds mirror the authoritative supported set; group ids are exactly the scope inputs.
    assert body["review_kinds"] == list(SUPPORTED_REVIEW_KINDS)
    assert "metadata_field" in body["review_kinds"]


@pytest.mark.anyio
async def test_scope_catalog_super_admin_ok(settings: Settings, admin: AdminIdentity) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await admin_get(client, admin, scope_catalog_path(admin.tenant_id))
    assert r.status_code == 200
    assert r.json()["groups"], "super admin should receive the non-empty scope catalog"
