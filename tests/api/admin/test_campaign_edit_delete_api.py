from __future__ import annotations

import asyncio
import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import func, select

from review_platform.db.models import AuditEvent
from review_platform.db.session import Database
from review_platform.review.case_pool import POOL_CAMPAIGN_KEY
from review_platform.review.models import Campaign
from review_platform.settings import Settings
from tests.support.campaign_http import _create_draft, campaign_path, complete_path
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, login, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_edit_campaign_reviewer_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="edit-reviewer@example.test", role="reviewer"
    )
    manager = add_review_user(
        database, settings, admin, email="edit-mgr-setup@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        mgr_csrf = await authenticate(client, manager)
        draft = await _create_draft(client, mgr_csrf, admin, key="edit-forbidden")

        rev_csrf = await authenticate(client, reviewer)
        r = await client.patch(
            campaign_path(admin.tenant_id, draft["campaign_id"]),
            json={"campaign_name": "Nope"},
            headers=mutation_headers(rev_csrf),
        )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_get_campaign_returns_detail_without_side_effects(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="get-campaign-mgr@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="get-campaign-a")

        r = await client.get(campaign_path(admin.tenant_id, draft["campaign_id"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["campaign_id"] == draft["campaign_id"]
    assert body["campaign_key"] == "get-campaign-a"
    assert body["status"] == "draft"
    assert body["reviews_per_case"] == 2
    assert body["selected_reviewer_ids"] == []
    assert body["schema_version"] == "campaign-detail/v1"


@pytest.mark.anyio
async def test_get_campaign_reviewer_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="get-campaign-reviewer@example.test", role="reviewer"
    )
    manager = add_review_user(
        database,
        settings,
        admin,
        email="get-campaign-mgr-setup@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        mgr_csrf = await authenticate(client, manager)
        draft = await _create_draft(client, mgr_csrf, admin, key="get-campaign-forbidden")

        await authenticate(client, reviewer)
        r = await client.get(campaign_path(admin.tenant_id, draft["campaign_id"]))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_get_campaign_unknown_is_404(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="get-campaign-mgr-404@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await authenticate(client, manager)
        r = await client.get(campaign_path(admin.tenant_id, str(uuid.uuid4())))
    assert r.status_code == 404


@pytest.mark.anyio
async def test_edit_draft_campaign_updates_name_and_minimum_reviews(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="edit-mgr-a@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="edit-a")

        r = await client.patch(
            campaign_path(admin.tenant_id, draft["campaign_id"]),
            json={"campaign_name": "Renamed Pilot", "minimum_reviews_per_case": 3},
            headers=mutation_headers(csrf),
        )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["campaign_name"] == "Renamed Pilot"
    assert body["reviews_per_case"] == 3
    assert body["status"] == "draft"
    assert body["selected_reviewer_ids"] == []
    assert body["schema_version"] == "campaign-detail/v1"


@pytest.mark.anyio
async def test_edit_name_does_not_require_confirmation_when_a_reviewer_is_selected(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="edit-mgr-b@example.test", role="campaign_manager"
    )
    reviewer = add_review_user(
        database, settings, admin, email="edit-b-reviewer@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="edit-b")
        campaign_id = draft["campaign_id"]

        added = await client.post(
            campaign_path(admin.tenant_id, campaign_id) + "/reviewers",
            json={"reviewer_id": str(reviewer.user_id)},
            headers=mutation_headers(csrf),
        )
        assert added.status_code == 200, added.text

        renamed = await client.patch(
            campaign_path(admin.tenant_id, campaign_id),
            json={"campaign_name": "No confirmation needed"},
            headers=mutation_headers(csrf),
        )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["campaign_name"] == "No confirmation needed"


@pytest.mark.anyio
async def test_edit_published_campaign_confirms_only_a_source_or_selector_change(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="edit-published")
        # import_campaign already authenticated as the admin; re-login for a fresh csrf token.
        _, csrf_token = await login(client, admin.email, admin.password)

        renamed = await client.patch(
            campaign_path(admin.tenant_id, imported["campaign_id"]),
            json={"campaign_name": "Published rename"},
            headers=mutation_headers(csrf_token),
        )
        unconfirmed_source = await client.patch(
            campaign_path(admin.tenant_id, imported["campaign_id"]),
            json={
                "review_scope": {"source_families": ["sample_a"]},
            },
            headers=mutation_headers(csrf_token),
        )
        confirmed = await client.patch(
            campaign_path(admin.tenant_id, imported["campaign_id"]),
            json={
                "review_scope": {"source_families": ["sample_a"]},
                "confirm": True,
            },
            headers=mutation_headers(csrf_token),
        )
        invalid_scope = await client.patch(
            campaign_path(admin.tenant_id, imported["campaign_id"]),
            json={
                "review_scope": {"group_ids": ["not-a-review-group"]},
                "confirm": True,
            },
            headers=mutation_headers(csrf_token),
        )
    assert renamed.status_code == 200, renamed.text
    assert unconfirmed_source.status_code == 409, unconfirmed_source.text
    assert unconfirmed_source.json()["code"] == "campaign_edit_requires_confirmation"
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["campaign_name"] == "Published rename"
    assert confirmed.json()["review_scope"]["source_families"] == ["sample_a"]
    assert invalid_scope.status_code == 422, invalid_scope.text


@pytest.mark.anyio
async def test_delete_draft_campaign_requires_confirmation_then_succeeds(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="delete-mgr-a@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="delete-a")
        campaign_id = draft["campaign_id"]

        unconfirmed = await client.delete(
            campaign_path(admin.tenant_id, campaign_id), headers=mutation_headers(csrf)
        )
        assert unconfirmed.status_code == 400, unconfirmed.text
        assert unconfirmed.json()["code"] == "campaign_delete_requires_confirmation"

        confirmed = await client.delete(
            campaign_path(admin.tenant_id, campaign_id),
            params={"confirm": "true"},
            headers=mutation_headers(csrf),
        )
        repeated = await client.delete(
            campaign_path(admin.tenant_id, campaign_id),
            params={"confirm": "true"},
            headers=mutation_headers(csrf),
        )
    assert confirmed.status_code == 200, confirmed.text
    body = confirmed.json()
    assert body["status"] == "closed"
    assert body["campaign_id"] == campaign_id

    assert repeated.status_code == 200, repeated.text
    assert repeated.json()["status"] == "closed"
    assert repeated.json()["cases_returned_to_pool"] == 0
    assert repeated.json()["units_returned_to_pool"] == 0
    assert repeated.json()["already_closed"] is True


@pytest.mark.anyio
async def test_delete_allows_selected_reviewers_when_no_work_exists(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="delete-mgr-reviewers@example.test",
        role="campaign_manager",
    )
    reviewer = add_review_user(
        database, settings, admin, email="delete-selected-reviewer@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="delete-selected")
        campaign_id = draft["campaign_id"]
        reviewers_path = campaign_path(admin.tenant_id, campaign_id) + "/reviewers"

        added = await client.post(
            reviewers_path,
            json={"reviewer_id": str(reviewer.user_id)},
            headers=mutation_headers(csrf),
        )
        assert added.status_code == 200, added.text

        deleted = await client.delete(
            campaign_path(admin.tenant_id, campaign_id),
            params={"confirm": "true"},
            headers=mutation_headers(csrf),
        )
    assert deleted.status_code == 200, deleted.text
    assert deleted.json()["status"] == "closed"


@pytest.mark.anyio
async def test_concurrent_admin_deletes_are_idempotent(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    managers = [
        add_review_user(
            database,
            settings,
            admin,
            email=f"delete-concurrent-{index}@example.test",
            role="campaign_manager",
        )
        for index in range(2)
    ]
    async with AsyncExitStack() as stack:
        clients = await open_clients(stack, settings, 2)
        csrf_tokens = [
            await authenticate(client, manager)
            for client, manager in zip(clients, managers, strict=True)
        ]
        draft = await _create_draft(clients[0], csrf_tokens[0], admin, key="delete-concurrent")
        path = campaign_path(admin.tenant_id, draft["campaign_id"])

        responses = await asyncio.gather(
            *[
                client.delete(
                    path,
                    params={"confirm": "true"},
                    headers=mutation_headers(csrf),
                )
                for client, csrf in zip(clients, csrf_tokens, strict=True)
            ]
        )

    assert [response.status_code for response in responses] == [200, 200]
    assert {response.json()["status"] for response in responses} == {"closed"}


@pytest.mark.anyio
async def test_delete_published_campaign_without_started_work_succeeds(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="delete-published")
        _, csrf_token = await login(client, admin.email, admin.password)

        r = await client.delete(
            campaign_path(admin.tenant_id, imported["campaign_id"]),
            params={"confirm": "true"},
            headers=mutation_headers(csrf_token),
        )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "closed"


@pytest.mark.anyio
async def test_delete_pool_campaign_is_blocked_with_specific_code(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="delete-pool-mgr@example.test", role="campaign_manager"
    )
    # Inserted directly as a pool campaign from the start -- the ``campaigns`` table trigger
    # rejects re-keying/re-statusing an existing row's identity fields after creation (the same
    # immutability the delete flow itself relies on for a real draft), so a fresh pool-status row
    # is the only way to exercise this guard without driving the full real-import fixture
    # pipeline just to get one reserved pool campaign into place.
    with database.session() as session, session.begin():
        campaign = Campaign(
            tenant_id=admin.tenant_id,
            key=POOL_CAMPAIGN_KEY,
            name="Case Pool",
            status="pool",
            policy_version="authored-v1",
            policy_json={},
            manifest_digest="0" * 64,
            created_by=admin.user_id,
        )
        session.add(campaign)
        session.flush()
        pool_id = str(campaign.id)

    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf_token = await authenticate(client, manager)
        r = await client.delete(
            campaign_path(admin.tenant_id, pool_id),
            params={"confirm": "true"},
            headers=mutation_headers(csrf_token),
        )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "campaign_delete_pool_blocked"


@pytest.mark.anyio
async def test_delete_paused_campaign_is_blocked_with_specific_code(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="delete-paused-mgr@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf_token = await authenticate(client, manager)
        draft = await _create_draft(client, csrf_token, admin, key="delete-paused")

        with database.session() as session, session.begin():
            row = session.get(Campaign, uuid.UUID(draft["campaign_id"]))
            assert row is not None
            row.status = "paused"

        r = await client.delete(
            campaign_path(admin.tenant_id, draft["campaign_id"]),
            params={"confirm": "true"},
            headers=mutation_headers(csrf_token),
        )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "campaign_delete_invalid_status"


@pytest.mark.anyio
async def test_mark_completed_requires_published_status(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="complete-draft-mgr@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf_token = await authenticate(client, manager)
        draft = await _create_draft(client, csrf_token, admin, key="complete-draft")

        r = await client.post(
            complete_path(admin.tenant_id, draft["campaign_id"]),
            headers=mutation_headers(csrf_token),
        )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "campaign_not_completable"


@pytest.mark.anyio
async def test_mark_completed_on_published_campaign_is_idempotent_and_derives_flag(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="complete-published")
        _, csrf_token = await login(client, admin.email, admin.password)
        campaign_id = imported["campaign_id"]

        before = await client.get(campaign_path(admin.tenant_id, campaign_id))
        assert before.status_code == 200, before.text
        assert before.json()["completed"] is False

        first = await client.post(
            complete_path(admin.tenant_id, campaign_id),
            headers=mutation_headers(csrf_token),
        )
        assert first.status_code == 200, first.text
        assert first.json()["completed"] is True
        assert first.json()["status"] == "published"

        second = await client.post(
            complete_path(admin.tenant_id, campaign_id),
            headers=mutation_headers(csrf_token),
        )
        assert second.status_code == 200, second.text
        assert second.json()["completed"] is True

        # Idempotent: exactly one marker audit event exists, not two.
        with database.session() as session:
            count = session.scalar(
                select(func.count())
                .select_from(AuditEvent)
                .where(
                    AuditEvent.object_type == "campaign",
                    AuditEvent.object_id == campaign_id,
                    AuditEvent.event_type == "campaign.marked_completed",
                )
            )
        assert count == 1

        after = await client.get(campaign_path(admin.tenant_id, campaign_id))
        assert after.status_code == 200, after.text
        assert after.json()["completed"] is True
