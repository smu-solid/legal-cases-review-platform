from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select

from review_platform.common.errors import APIError
from review_platform.db.session import Database
from review_platform.review.campaign_reviewers import ReviewCampaignReviewersMixin
from review_platform.review.models import Assignment, ReviewItemAnswer, ReviewUnit
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, claim_field, import_campaign
from tests.support.clients import authenticate, login, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


def reviewers_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/reviewers"


async def _create_draft(client, csrf_token: str, admin: AdminIdentity, *, key: str) -> dict:
    created = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns",
        json={"campaign_key": key, "campaign_name": "Draft Campaign"},
        headers=mutation_headers(csrf_token),
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


@pytest.mark.anyio
async def test_add_reviewer_forbidden_for_reviewer_role(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="rv-mgr-setup@example.test", role="campaign_manager"
    )
    reviewer = add_review_user(
        database, settings, admin, email="rv-forbidden@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        mgr_csrf = await authenticate(client, manager)
        draft = await _create_draft(client, mgr_csrf, admin, key="reviewers-forbidden")

        rev_csrf = await authenticate(client, reviewer)
        r = await client.post(
            reviewers_path(admin.tenant_id, draft["campaign_id"]),
            json={"reviewer_id": str(reviewer.user_id)},
            headers=mutation_headers(rev_csrf),
        )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_add_reviewer_rejects_unknown_user(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="rv-mgr-a@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="reviewers-unknown")

        r = await client.post(
            reviewers_path(admin.tenant_id, draft["campaign_id"]),
            json={"reviewer_id": str(uuid.uuid4())},
            headers=mutation_headers(csrf),
        )
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "reviewer_not_found"


@pytest.mark.anyio
async def test_add_reviewer_rejects_non_reviewer_role(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="rv-mgr-b@example.test", role="campaign_manager"
    )
    other_manager = add_review_user(
        database, settings, admin, email="rv-not-a-reviewer@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="reviewers-wrong-role")

        r = await client.post(
            reviewers_path(admin.tenant_id, draft["campaign_id"]),
            json={"reviewer_id": str(other_manager.user_id)},
            headers=mutation_headers(csrf),
        )
    assert r.status_code == 404, r.text


@pytest.mark.anyio
async def test_add_then_remove_reviewer_is_idempotent(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="rv-mgr-c@example.test", role="campaign_manager"
    )
    reviewer_one = add_review_user(
        database, settings, admin, email="rv-c-one@example.test", role="reviewer"
    )
    reviewer_two = add_review_user(
        database, settings, admin, email="rv-c-two@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="reviewers-add-remove")
        path = reviewers_path(admin.tenant_id, draft["campaign_id"])

        first = await client.post(
            path, json={"reviewer_id": str(reviewer_one.user_id)}, headers=mutation_headers(csrf)
        )
        assert first.status_code == 200, first.text
        assert first.json()["selected_reviewer_ids"] == [str(reviewer_one.user_id)]

        # Adding the same reviewer twice is a no-op, not a duplicate entry.
        again = await client.post(
            path, json={"reviewer_id": str(reviewer_one.user_id)}, headers=mutation_headers(csrf)
        )
        assert again.status_code == 200, again.text
        assert again.json()["selected_reviewer_ids"] == [str(reviewer_one.user_id)]

        second = await client.post(
            path, json={"reviewer_id": str(reviewer_two.user_id)}, headers=mutation_headers(csrf)
        )
        assert second.status_code == 200, second.text
        assert set(second.json()["selected_reviewer_ids"]) == {
            str(reviewer_one.user_id),
            str(reviewer_two.user_id),
        }

        removed = await client.delete(
            f"{path}/{reviewer_one.user_id}", headers=mutation_headers(csrf)
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["selected_reviewer_ids"] == [str(reviewer_two.user_id)]

        # Removing an already-absent reviewer is a safe no-op.
        removed_again = await client.delete(
            f"{path}/{reviewer_one.user_id}", headers=mutation_headers(csrf)
        )
    assert removed_again.status_code == 200, removed_again.text
    assert removed_again.json()["selected_reviewer_ids"] == [str(reviewer_two.user_id)]


@pytest.mark.anyio
async def test_add_reviewer_allowed_once_campaign_is_published(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="rv-published@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="reviewers-published")
        _, csrf_token = await login(client, admin.email, admin.password)

        r = await client.post(
            reviewers_path(admin.tenant_id, imported["campaign_id"]),
            json={"reviewer_id": str(reviewer.user_id)},
            headers=mutation_headers(csrf_token),
        )
    assert r.status_code == 200, r.text
    assert str(reviewer.user_id) in r.json()["selected_reviewer_ids"]


@pytest.mark.anyio
async def test_cannot_remove_last_selected_reviewer_from_campaign_with_assignments(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="rv-minimum@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(client, admin, key="reviewers-minimum")
        campaign_id = str(imported["campaign_id"])
        _, csrf_token = await login(client, admin.email, admin.password)
        path = reviewers_path(admin.tenant_id, campaign_id)
        added = await client.post(
            path,
            json={"reviewer_id": str(reviewer.user_id)},
            headers=mutation_headers(csrf_token),
        )
        assert added.status_code == 200, added.text
        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        await claim_field(
            reviewer_client,
            reviewer_csrf,
            str(admin.tenant_id),
            campaign_id,
            "Citation Neutral",
            idem="reviewers-minimum-claim",
        )

        removed = await client.delete(
            f"{path}/{reviewer.user_id}", headers=mutation_headers(csrf_token)
        )

    assert removed.status_code == 422, removed.text
    assert removed.json()["code"] == "campaign_reviewer_minimum_required"


@pytest.mark.anyio
async def test_remove_absent_reviewer_still_checks_closed_campaign_status(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="rv-closed-manager@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="reviewers-closed")
        campaign_id = draft["campaign_id"]
        deleted = await client.delete(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns/{campaign_id}?confirm=true",
            headers=mutation_headers(csrf),
        )
        assert deleted.status_code == 200, deleted.text

        removed = await client.delete(
            f"{reviewers_path(admin.tenant_id, campaign_id)}/{uuid.uuid4()}",
            headers=mutation_headers(csrf),
        )

    assert removed.status_code == 409, removed.text
    assert removed.json()["code"] == "campaign_reviewers_locked"


@pytest.mark.anyio
async def test_remove_reviewer_blocked_after_submitted_work(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="rv-work-started@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="reviewers-work-started")
        campaign_id = str(imported["campaign_id"])
        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        assignment_id = await claim_field(
            reviewer_client,
            reviewer_csrf,
            str(admin.tenant_id),
            campaign_id,
            "Citation Neutral",
            idem="reviewers-work-started-claim",
        )
        bundle = (
            await reviewer_client.get(
                f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
            )
        ).json()
        submitted = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "reviewers-work-started-submit",
                "If-Match": f'"{bundle["lock_version"]}"',
            },
        )
        assert submitted.status_code == 201, submitted.text
        with database.session() as db_session:
            assignment = db_session.scalar(
                select(Assignment).where(Assignment.id == uuid.UUID(assignment_id))
            )
            assert assignment is not None
            assert assignment.status == "submitted"
            assert assignment.reviewer_id == reviewer.user_id
            unit = db_session.scalar(
                select(ReviewUnit).where(ReviewUnit.id == assignment.review_unit_id)
            )
            assert unit is not None
            assert unit.campaign_id == uuid.UUID(campaign_id)
            assert db_session.scalar(
                select(ReviewItemAnswer.id).where(
                    ReviewItemAnswer.assignment_id == uuid.UUID(assignment_id)
                )
            )

            with pytest.raises(APIError) as blocked:
                ReviewCampaignReviewersMixin._require_reviewer_has_no_work(
                    db_session,
                    tenant_id=admin.tenant_id,
                    campaign_id=uuid.UUID(campaign_id),
                    reviewer_id=reviewer.user_id,
                )
            assert blocked.value.status == 422
            assert blocked.value.code == "campaign_reviewer_work_exists"
