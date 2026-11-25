from __future__ import annotations

from contextlib import AsyncExitStack

import pytest

from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.allocation_incremental import (
    base_alloc_path,
    incr_policy,
    setup_campaign_with_published_run,
)
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_incremental_preview_persist_publish_new_reviewer(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Full flow: initial publish → add 3rd reviewer → incremental run assigns coverage gaps."""
    manager = add_review_user(
        database, settings, admin, email="incr-manager@example.test", role="campaign_manager"
    )
    r1, r2 = [
        add_review_user(database, settings, admin, email=f"incr-r{i}@example.test", role="reviewer")
        for i in range(1, 3)
    ]
    r3 = add_review_user(database, settings, admin, email="incr-r3@example.test", role="reviewer")
    async with AsyncExitStack() as stack:
        admin_client, manager_client, reviewer_client = await open_clients(stack, settings, 3)
        manager_csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(manager_csrf)
        campaign_id, base_run_id = await setup_campaign_with_published_run(
            admin_client,
            manager_client,
            admin,
            manager,
            [r1, r2],
            campaign_key="source-correction-incr-add-reviewer",
            mutation_hdrs=headers,
        )

        runs = base_alloc_path(admin.tenant_id, campaign_id)

        # --- Preview incremental run ---
        preview_body = incr_policy(
            [str(r1.user_id), str(r2.user_id), str(r3.user_id)],
            base_run_id,
            min_reviews_per_subject=3,  # current coverage is 2; each subject needs 1 more
        )
        preview = await manager_client.post(
            f"{runs}/incremental-preview",
            json=preview_body,
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        data = preview.json()
        assert data["schema_version"] == "incremental-preview/v1"
        assert data["feasibility"]["status"] in {"feasible", "feasible_with_warnings"}
        assert data["new_assignment_count"] > 0
        assert str(r3.user_id) in [rid for rid in data["reviewer_pool_after"]]
        # Movement plan must not appear in reviewer-facing responses (checked below)
        assert "movement_plan" in data  # admin-only field present in preview

        # --- Persist incremental run ---
        persisted = await manager_client.post(
            f"{runs}/incremental",
            json=preview_body,
            headers={**headers, "Idempotency-Key": "incr-persist-001"},
        )
        assert persisted.status_code == 201, persisted.text
        incr_run_id = str(persisted.json()["run_id"])
        assert persisted.json()["allocation_mode"] == "incremental"
        assert persisted.json()["base_run_id"] == base_run_id
        assert persisted.json()["status"] == "planned"

        # Idempotent replay
        replay = await manager_client.post(
            f"{runs}/incremental",
            json=preview_body,
            headers={**headers, "Idempotency-Key": "incr-persist-001"},
        )
        assert replay.status_code == 201
        assert replay.json()["run_id"] == incr_run_id
        assert replay.json()["replayed"] is True

        # --- Publish incremental run ---
        published = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "incr-publish-001"},
        )
        assert published.status_code == 201, published.text
        assert published.json()["status"] == "published"
        assert published.json()["schema_version"] == "incremental-publish/v1"
        assert published.json()["new_assignment_count"] > 0

        # Idempotent publish replay
        pub_replay = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "incr-publish-001"},
        )
        assert pub_replay.status_code == 201
        assert pub_replay.json()["replayed"] is True

        # --- Reviewer queue blinding ---
        await authenticate(reviewer_client, r3)
        queue = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "review_kind": "metadata_field"},
        )
        assert queue.status_code == 200
        assert len(queue.json()["items"]) > 0
        queue_text = queue.text
        for forbidden in (
            "movement_plan",
            "movement_kind",
            "movement_reason",
            "allocation_mode",
            "incremental",
            str(r1.user_id),
            str(r2.user_id),
            "overlap_group_key",
            "selection_layer",
            "allocation_run",
        ):
            assert forbidden not in queue_text, f"Blinding violation: {forbidden!r} in queue"
