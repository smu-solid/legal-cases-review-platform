from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest

from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, login, open_clients
from tests.support.identities import AdminIdentity


def cases_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"


@pytest.mark.anyio
async def test_campaign_cases_forbidden_for_reviewer(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="cases-forbidden@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="cases-forbidden")
        await authenticate(client, reviewer)
        r = await client.get(cases_path(admin.tenant_id, imported["campaign_id"]))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_campaign_cases_lists_every_case_exactly_once(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="cases-mgr@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="cases-listing")
        campaign_id = imported["campaign_id"]

        await authenticate(client, manager)
        r = await client.get(cases_path(admin.tenant_id, campaign_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["campaign_id"] == campaign_id
    assert body["schema_version"] == "campaign-case-progress/v1"
    assert len(body["items"]) > 0
    case_ids = [item["case_id"] for item in body["items"]]
    assert len(case_ids) == len(set(case_ids))
    for item in body["items"]:
        assert item["unit_count"] > 0
        assert item["review_kinds"] == sorted(item["review_kinds"])
        # field_group_labels is the display-safe equivalent of the raw review_kinds tokens --
        # every case has at least one, and none is a raw token like "metadata_field".
        assert len(item["field_group_labels"]) > 0
        assert "metadata_field" not in item["field_group_labels"]
        if "metadata_field" in item["review_kinds"]:
            atomic_labels = {
                "Case metadata",
                "Citations",
                "Court, date & coram",
                "Parties, lawyers & firms",
                "Additional fields",
            }
            assert atomic_labels.intersection(item["field_group_labels"])


@pytest.mark.anyio
async def test_campaign_cases_paginates_with_stable_cursor(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="cases-paginate")
        campaign_id = imported["campaign_id"]
        await login(client, admin.email, admin.password)

        full = await client.get(cases_path(admin.tenant_id, campaign_id))
        assert full.status_code == 200, full.text
        all_ids = [item["case_id"] for item in full.json()["items"]]
        assert len(all_ids) >= 2, "fixture must have at least 2 cases to exercise pagination"

        collected: list[str] = []
        cursor: str | None = None
        for _ in range(len(all_ids) + 1):
            params = {"limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            page = await client.get(cases_path(admin.tenant_id, campaign_id), params=params)
            assert page.status_code == 200, page.text
            body = page.json()
            assert len(body["items"]) == 1
            collected.append(body["items"][0]["case_id"])
            if not body["has_more"]:
                assert body["next_cursor"] is None
                break
            cursor = body["next_cursor"]
            assert cursor is not None

    assert collected == all_ids
