from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest

from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


def campaigns_path(tenant_id: uuid.UUID | str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaigns"


@pytest.mark.anyio
async def test_create_campaign_rejects_mutation_without_origin(
    settings: Settings, admin: AdminIdentity
) -> None:
    """The browser-mutation guard rejects a cross-site/originless POST before authentication."""
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await client.post(
            campaigns_path(admin.tenant_id),
            json={"campaign_key": "authored-anon", "campaign_name": "Anon"},
        )
    assert r.status_code == 403
    assert r.json()["code"] == "csrf_failed"


@pytest.mark.anyio
async def test_create_campaign_reviewer_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="authored-reviewer@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, reviewer)
        r = await client.post(
            campaigns_path(admin.tenant_id),
            json={"campaign_key": "authored-forbidden", "campaign_name": "Forbidden"},
            headers=mutation_headers(csrf),
        )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_create_campaign_authors_draft_and_rejects_duplicate(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """A campaign_manager authors an empty draft campaign; re-using the key is a 409 conflict so an
    existing campaign is never silently rebound."""

    manager = add_review_user(
        database, settings, admin, email="authored-mgr@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)

        created = await client.post(
            campaigns_path(admin.tenant_id),
            json={"campaign_key": "authored-pilot", "campaign_name": "Authored Pilot"},
            headers=mutation_headers(csrf),
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["campaign_key"] == "authored-pilot"
        assert body["campaign_name"] == "Authored Pilot"
        assert body["status"] == "draft"
        assert body["total_units"] == 0
        assert body["schema_version"] == "campaign-authored/v1"

        duplicate = await client.post(
            campaigns_path(admin.tenant_id),
            json={"campaign_key": "authored-pilot", "campaign_name": "Authored Pilot Again"},
            headers=mutation_headers(csrf),
        )
        assert duplicate.status_code == 409, duplicate.text
        assert duplicate.json()["code"] == "campaign_key_exists"

        # A genuinely new key succeeds right after a duplicate rejection -- the 409 leaves no
        # server-side state that could block or corrupt an unrelated subsequent authoring request.
        retried = await client.post(
            campaigns_path(admin.tenant_id),
            json={"campaign_key": "authored-pilot-2", "campaign_name": "Authored Pilot Retry"},
            headers=mutation_headers(csrf),
        )
        assert retried.status_code == 201, retried.text
        assert retried.json()["campaign_key"] == "authored-pilot-2"
        assert retried.json()["campaign_id"] != body["campaign_id"]


@pytest.mark.anyio
async def test_create_campaign_with_empty_pool_returns_clear_error_without_creating_draft(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="authored-empty-pool@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        response = await client.post(
            campaigns_path(admin.tenant_id),
            json={
                "campaign_key": "empty-pool",
                "campaign_name": "Empty pool",
                "requested_case_count": "all",
            },
            headers=mutation_headers(csrf),
        )

    assert response.status_code == 422, response.text
    assert response.json()["code"] == "campaign_no_cases_available"


@pytest.mark.anyio
async def test_create_campaign_rejects_unknown_review_scope_group(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """An unknown ``review_scope.group_ids`` entry is rejected up front with a machine-readable

    ``validation_failed`` code, instead of silently matching zero review units at import time.
    """

    manager = add_review_user(
        database, settings, admin, email="authored-badscope@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)

        r = await client.post(
            campaigns_path(admin.tenant_id),
            json={
                "campaign_key": "authored-badscope",
                "campaign_name": "Authored Bad Scope",
                "review_scope": {"group_ids": ["not_a_group"], "review_kinds": []},
            },
            headers=mutation_headers(csrf),
        )
        assert r.status_code == 422, r.text
        assert r.json()["code"] == "validation_failed"


@pytest.mark.anyio
async def test_create_campaign_minimum_reviews_per_case_defaults_and_is_configurable(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="authored-minrev@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)

        default = await client.post(
            campaigns_path(admin.tenant_id),
            json={"campaign_key": "authored-minrev-default", "campaign_name": "Default"},
            headers=mutation_headers(csrf),
        )
        assert default.status_code == 201, default.text
        assert default.json()["reviews_per_case"] == 2

        configured = await client.post(
            campaigns_path(admin.tenant_id),
            json={
                "campaign_key": "authored-minrev-configured",
                "campaign_name": "Configured",
                "minimum_reviews_per_case": 5,
            },
            headers=mutation_headers(csrf),
        )
        assert configured.status_code == 201, configured.text
        assert configured.json()["reviews_per_case"] == 5

        rejected = await client.post(
            campaigns_path(admin.tenant_id),
            json={
                "campaign_key": "authored-minrev-invalid",
                "campaign_name": "Invalid",
                "minimum_reviews_per_case": 1,
            },
            headers=mutation_headers(csrf),
        )
        assert rejected.status_code == 422, rejected.text
        assert rejected.json()["code"] == "validation_failed"
