"""The UI-frozen count is also immutable through published campaign API and SQL writes."""

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from tests.support.campaign_http import campaign_path
from tests.support.campaigns import import_campaign
from tests.support.clients import login, mutation_headers, open_clients


@pytest.mark.anyio
@pytest.mark.parametrize("required", [2, 3])
async def test_published_review_count_omitted_unchanged_and_changed(
    settings, database, admin, required
):
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(
            client, admin, key="frozen-count", reviews_per_case=required
        )
        _, csrf = await login(client, admin.email, admin.password)
        path = campaign_path(admin.tenant_id, imported["campaign_id"])
        for body in (
            {"campaign_name": "Renamed"},
            {"reviews_per_case": required},
            {"minimum_reviews_per_case": required},
        ):
            response = await client.patch(path, json=body, headers=mutation_headers(csrf))
            assert response.status_code == 200, response.text
            assert response.json()["reviews_per_case"] == required
        for key in ("reviews_per_case", "minimum_reviews_per_case"):
            response = await client.patch(
                path, json={key: required + 1}, headers=mutation_headers(csrf)
            )
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "campaign_review_count_frozen"
        assert (await client.get(path)).json()["reviews_per_case"] == required
    with (
        pytest.raises(DBAPIError, match="frozen after publication"),
        database.session() as session,
        session.begin(),
    ):
        session.execute(
            text(
                "UPDATE review_platform.campaigns SET policy_json = "
                "jsonb_set(policy_json, '{minimum_reviews_per_case}', CAST(:n AS jsonb)) "
                "WHERE id = :id"
            ),
            {"n": str(required + 1), "id": uuid.UUID(imported["campaign_id"])},
        )
