"""Reviewer removal/swap through incremental preview+publish (reproduces and pins the fix for
the "remove R1 + add R2 -> Publish 0 assignments, R1 still sees the campaign" bug).

Covers:
  - a removed reviewer with no work ends the swap-publish with zero live assignments and loses
    campaign queue visibility (`ReviewQueueMixin._reviewer_campaign_ids`);
  - the remove guard and the incremental planner are scoped per-reviewer -- a third reviewer's
    in-progress work never blocks the removal and is never touched by the swap;
  - the publish response reports the swap (`moved_assignment_count`, `revoked_reviewer_ids`).
"""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select

from review_platform.db.session import Database
from review_platform.review.models import Assignment
from review_platform.settings import Settings
from tests.support.admin_stats import workload_path
from tests.support.allocation_incremental import (
    base_alloc_path,
    incr_policy,
    setup_campaign_with_published_run,
)
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, login, mutation_headers, open_clients
from tests.support.identities import AdminIdentity

# Matches the admin UI's actual default incremental movement policy
# (apps/web/src/routes/admin/CampaignDetailPage.tsx) -- claimed/unclaimed work is movable so a
# roster swap can actually take effect, drafts never move.
UI_DEFAULT_MOVEMENT_POLICY = {
    "allow_rebalance_unclaimed": True,
    "allow_rebalance_claimed": True,
    "allow_rebalance_draft": False,
}


def reviewers_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/reviewers"


def campaigns_path(tenant_id: uuid.UUID | str) -> str:
    return f"/api/v1/tenants/{tenant_id}/review/campaigns"


def queue_path(tenant_id: uuid.UUID | str) -> str:
    return f"/api/v1/tenants/{tenant_id}/review/queue"


@pytest.mark.anyio
async def test_removed_reviewer_loses_access_third_reviewer_untouched(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="swap-manager@example.test", role="campaign_manager"
    )
    r1 = add_review_user(database, settings, admin, email="swap-r1@example.test", role="reviewer")
    r3 = add_review_user(database, settings, admin, email="swap-r3@example.test", role="reviewer")
    r2 = add_review_user(database, settings, admin, email="swap-r2@example.test", role="reviewer")

    async with AsyncExitStack() as stack:
        admin_client, manager_client, r1_client, r2_client, r3_client = await open_clients(
            stack, settings, 5
        )
        manager_csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(manager_csrf)

        campaign_id, base_run_id = await setup_campaign_with_published_run(
            admin_client,
            manager_client,
            admin,
            manager,
            [r1, r3],
            campaign_key="swap-remove-r1",
            mutation_hdrs=headers,
        )
        # setup_campaign_with_published_run only feeds reviewer_ids to the allocation body -- it
        # never curates the roster through the actual add/remove endpoints, so policy_json's
        # selected_reviewer_ids is still empty (open-roster). Curate it explicitly here so the
        # rest of this test exercises the real admin checkbox flow the roster swap builds on.
        _, setup_csrf = await login(admin_client, admin.email, admin.password)
        for reviewer in (r1, r3):
            curated = await admin_client.post(
                reviewers_path(admin.tenant_id, campaign_id),
                json={"reviewer_id": str(reviewer.user_id)},
                headers=mutation_headers(setup_csrf),
            )
            assert curated.status_code == 200, curated.text

        # r3 does real, in-progress work -- this must never block removing r1, and must never be
        # touched by the swap (per-reviewer gating, not campaign-wide). The initial publish
        # already claimed this field's assignment directly to r3, so fetch it from their own
        # "assigned" queue instead of claim_field (which expects an unclaimed pool item).
        r3_csrf = await authenticate(r3_client, r3)
        r3_assigned = await r3_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "assignment_status": "assigned"},
        )
        assert r3_assigned.status_code == 200, r3_assigned.text
        r3_items = r3_assigned.json()["items"]
        assert r3_items, r3_assigned.text
        r3_item = r3_items[0]
        submitted_assignment_id = r3_item["assignment_id"]
        bundle = (
            await r3_client.get(
                f"/api/v1/tenants/{admin.tenant_id}/review/assignments/"
                f"{submitted_assignment_id}/grouped-bundle"
            )
        ).json()
        submit = await r3_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/"
            f"{submitted_assignment_id}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(r3_csrf),
                "Idempotency-Key": "swap-r3-submit",
                "If-Match": f'"{bundle["lock_version"]}"',
            },
        )
        assert submit.status_code == 201, submit.text

        # --- Roster swap: add r2, remove r1 (r1 has no work; r3's work must not block it) ---
        _, admin_csrf = await login(admin_client, admin.email, admin.password)
        reviewers_url = reviewers_path(admin.tenant_id, campaign_id)
        added = await admin_client.post(
            reviewers_url,
            json={"reviewer_id": str(r2.user_id)},
            headers=mutation_headers(admin_csrf),
        )
        assert added.status_code == 200, added.text
        removed = await admin_client.delete(
            f"{reviewers_url}/{r1.user_id}", headers=mutation_headers(admin_csrf)
        )
        assert removed.status_code == 200, removed.text
        assert set(removed.json()["selected_reviewer_ids"]) == {str(r3.user_id), str(r2.user_id)}

        # --- Incremental preview + publish with the current roster ---
        runs = base_alloc_path(admin.tenant_id, campaign_id)
        body = incr_policy(
            [str(r3.user_id), str(r2.user_id)],
            base_run_id,
            min_reviews_per_subject=2,
            movement_policy=UI_DEFAULT_MOVEMENT_POLICY,
        )
        persisted = await manager_client.post(
            f"{runs}/incremental",
            json=body,
            headers={**headers, "Idempotency-Key": "swap-persist-001"},
        )
        assert persisted.status_code == 201, persisted.text
        incr_run_id = str(persisted.json()["run_id"])

        published = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "swap-publish-001"},
        )
        assert published.status_code == 201, published.text
        pub_body = published.json()
        # The core bug: this used to report 0 moved and never released r1.
        assert pub_body["moved_assignment_count"] > 0, pub_body
        assert pub_body["revoked_reviewer_ids"] == [str(r1.user_id)], pub_body

        # --- r1 lost campaign visibility; r2 gained it; r3 (untouched) keeps it ---
        await authenticate(r1_client, r1)
        r1_campaigns = await r1_client.get(campaigns_path(admin.tenant_id))
        assert r1_campaigns.status_code == 200
        assert "swap-remove-r1" not in {
            item["campaign_key"] for item in r1_campaigns.json()["campaigns"]
        }
        r1_queue = await r1_client.get(
            queue_path(admin.tenant_id), params={"campaign_id": campaign_id}
        )
        assert r1_queue.status_code == 200
        assert r1_queue.json()["items"] == []

        await authenticate(r2_client, r2)
        r2_campaigns = await r2_client.get(campaigns_path(admin.tenant_id))
        assert "swap-remove-r1" in {
            item["campaign_key"] for item in r2_campaigns.json()["campaigns"]
        }

        r3_campaigns_again = await r3_client.get(campaigns_path(admin.tenant_id))
        assert "swap-remove-r1" in {
            item["campaign_key"] for item in r3_campaigns_again.json()["campaigns"]
        }

        # --- Admin-facing workload confirms the same picture ---
        _, admin_csrf2 = await login(admin_client, admin.email, admin.password)
        workload = await admin_client.get(
            workload_path(admin.tenant_id),
            params={"campaign_id": campaign_id},
            headers=mutation_headers(admin_csrf2),
        )
        assert workload.status_code == 200, workload.text
        by_reviewer = {item["reviewer_id"]: item for item in workload.json()["items"]}
        r1_row = by_reviewer.get(str(r1.user_id))
        assert r1_row is None or (r1_row["claimed_count"] == 0 and r1_row["submitted_count"] == 0)
        assert by_reviewer[str(r2.user_id)]["claimed_count"] > 0
        assert by_reviewer[str(r3.user_id)]["submitted_count"] == 1

    # --- r3's submitted work is byte-for-byte unchanged ---
    with database.session() as session:
        assignment = session.scalar(
            select(Assignment).where(Assignment.id == uuid.UUID(submitted_assignment_id))
        )
        assert assignment is not None
        assert assignment.status == "submitted"
        assert assignment.reviewer_id == r3.user_id


@pytest.mark.anyio
async def test_idle_reviewer_removed_and_new_reviewer_added_while_other_reviewer_has_work(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Per-reviewer gating: a working reviewer must never block editing/removing a *different*,
    idle reviewer or adding a new one -- only the reviewer actually being removed must be
    work-free. Two initial reviewers only (matches the exact acceptance scenario), and the
    guard direction is checked both ways: removing the idle one succeeds, removing the working
    one is still blocked.
    """
    r_work = add_review_user(
        database, settings, admin, email="gate-r-work@example.test", role="reviewer"
    )
    r_idle = add_review_user(
        database, settings, admin, email="gate-r-idle@example.test", role="reviewer"
    )
    r_new = add_review_user(
        database, settings, admin, email="gate-r-new@example.test", role="reviewer"
    )
    manager = add_review_user(
        database, settings, admin, email="gate-manager@example.test", role="campaign_manager"
    )

    async with AsyncExitStack() as stack:
        admin_client, manager_client, work_client, idle_client, new_client = await open_clients(
            stack, settings, 5
        )
        manager_csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(manager_csrf)

        campaign_id, base_run_id = await setup_campaign_with_published_run(
            admin_client,
            manager_client,
            admin,
            manager,
            [r_work, r_idle],
            campaign_key="gate-two-reviewers",
            mutation_hdrs=headers,
        )
        _, setup_csrf = await login(admin_client, admin.email, admin.password)
        reviewers_url = reviewers_path(admin.tenant_id, campaign_id)
        for reviewer in (r_work, r_idle):
            curated = await admin_client.post(
                reviewers_url,
                json={"reviewer_id": str(reviewer.user_id)},
                headers=mutation_headers(setup_csrf),
            )
            assert curated.status_code == 200, curated.text

        # r_work does real work; r_idle never touches anything.
        work_csrf = await authenticate(work_client, r_work)
        assigned = await work_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "assignment_status": "assigned"},
        )
        work_item = assigned.json()["items"][0]
        bundle = (
            await work_client.get(
                f"/api/v1/tenants/{admin.tenant_id}/review/assignments/"
                f"{work_item['assignment_id']}/grouped-bundle"
            )
        ).json()
        submit = await work_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/"
            f"{work_item['assignment_id']}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(work_csrf),
                "Idempotency-Key": "gate-work-submit",
                "If-Match": f'"{bundle["lock_version"]}"',
            },
        )
        assert submit.status_code == 201, submit.text

        _, admin_csrf = await login(admin_client, admin.email, admin.password)

        # Adding a brand-new reviewer is never blocked by someone else's work.
        added = await admin_client.post(
            reviewers_url,
            json={"reviewer_id": str(r_new.user_id)},
            headers=mutation_headers(admin_csrf),
        )
        assert added.status_code == 200, added.text

        # Removing the *idle* reviewer succeeds even though r_work has started work.
        removed_idle = await admin_client.delete(
            f"{reviewers_url}/{r_idle.user_id}", headers=mutation_headers(admin_csrf)
        )
        assert removed_idle.status_code == 200, removed_idle.text
        assert set(removed_idle.json()["selected_reviewer_ids"]) == {
            str(r_work.user_id),
            str(r_new.user_id),
        }

        # The guard still fires in the other direction: removing the reviewer who actually has
        # work is blocked.
        removed_work = await admin_client.delete(
            f"{reviewers_url}/{r_work.user_id}", headers=mutation_headers(admin_csrf)
        )
        assert removed_work.status_code == 422, removed_work.text
        assert removed_work.json()["code"] == "campaign_reviewer_work_exists"

        # Incremental publish actually revokes r_idle's access and gives r_new coverage.
        runs = base_alloc_path(admin.tenant_id, campaign_id)
        body = incr_policy(
            [str(r_work.user_id), str(r_new.user_id)],
            base_run_id,
            min_reviews_per_subject=2,
            movement_policy=UI_DEFAULT_MOVEMENT_POLICY,
        )
        persisted = await manager_client.post(
            f"{runs}/incremental",
            json=body,
            headers={**headers, "Idempotency-Key": "gate-persist-001"},
        )
        assert persisted.status_code == 201, persisted.text
        published = await manager_client.post(
            f"{runs}/{persisted.json()['run_id']}/publish-incremental",
            headers={**headers, "Idempotency-Key": "gate-publish-001"},
        )
        assert published.status_code == 201, published.text
        assert published.json()["revoked_reviewer_ids"] == [str(r_idle.user_id)]

        await authenticate(idle_client, r_idle)
        idle_campaigns = await idle_client.get(campaigns_path(admin.tenant_id))
        assert "gate-two-reviewers" not in {
            item["campaign_key"] for item in idle_campaigns.json()["campaigns"]
        }

        await authenticate(new_client, r_new)
        new_campaigns = await new_client.get(campaigns_path(admin.tenant_id))
        assert "gate-two-reviewers" in {
            item["campaign_key"] for item in new_campaigns.json()["campaigns"]
        }

    # r_work's submitted work is untouched by any of the above.
    with database.session() as session:
        assignment = session.scalar(
            select(Assignment).where(Assignment.id == uuid.UUID(work_item["assignment_id"]))
        )
        assert assignment is not None
        assert assignment.status == "submitted"
        assert assignment.reviewer_id == r_work.user_id
