from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import text as sqla_text

from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.allocation_incremental import (
    FEASIBLE_POLICY,
    base_alloc_path,
    incr_policy,
    setup_campaign_with_published_run,
)
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_incremental_rbac_admin_only(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="incr-mgr-rbac@example.test", role="campaign_manager"
    )
    plain_reviewer = add_review_user(
        database, settings, admin, email="incr-plain-r@example.test", role="reviewer"
    )
    r1, r2 = [
        add_review_user(
            database, settings, admin, email=f"incr-rbac-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    async with AsyncExitStack() as stack:
        admin_client, manager_client, reviewer_client = await open_clients(stack, settings, 3)
        manager_csrf = await authenticate(manager_client, manager)
        manager_headers = mutation_headers(manager_csrf)
        campaign_id, base_run_id = await setup_campaign_with_published_run(
            admin_client,
            manager_client,
            admin,
            manager,
            [r1, r2],
            campaign_key="incr-rbac",
            mutation_hdrs=manager_headers,
        )
        runs = base_alloc_path(admin.tenant_id, campaign_id)
        preview_body = incr_policy(
            [str(r1.user_id), str(r2.user_id)], base_run_id, min_reviews_per_subject=2
        )

        reviewer_csrf = await authenticate(reviewer_client, plain_reviewer)
        forbidden = await reviewer_client.post(
            f"{runs}/incremental-preview",
            json=preview_body,
            headers=mutation_headers(reviewer_csrf),
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "forbidden"

        # Non-existent base run returns 404
        bad_body = incr_policy(
            [str(r1.user_id), str(r2.user_id)],
            str(uuid.uuid4()),
            min_reviews_per_subject=2,
        )
        not_found = await manager_client.post(
            f"{runs}/incremental-preview",
            json=bad_body,
            headers=manager_headers,
        )
        assert not_found.status_code == 404
        assert not_found.json()["code"] == "base_run_not_found"


@pytest.mark.anyio
async def test_incremental_snapshot_drift_guard(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Snapshot drift between persist and publish blocks publish."""
    manager = add_review_user(
        database, settings, admin, email="incr-drift-mgr@example.test", role="campaign_manager"
    )
    r1, r2 = [
        add_review_user(
            database, settings, admin, email=f"incr-drift-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        manager_csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(manager_csrf)
        campaign_id, base_run_id = await setup_campaign_with_published_run(
            admin_client,
            manager_client,
            admin,
            manager,
            [r1, r2],
            campaign_key="incr-drift",
            mutation_hdrs=headers,
        )
        runs = base_alloc_path(admin.tenant_id, campaign_id)
        preview_body = incr_policy(
            [str(r1.user_id), str(r2.user_id)], base_run_id, min_reviews_per_subject=2
        )
        persisted = await manager_client.post(
            f"{runs}/incremental",
            json=preview_body,
            headers={**headers, "Idempotency-Key": "incr-drift-persist"},
        )
        assert persisted.status_code == 201, persisted.text
        incr_run_id = str(persisted.json()["run_id"])

        # Corrupt the snapshot digest to simulate drift
        with database.session() as session, session.begin():
            session.execute(
                sqla_text(
                    "UPDATE review_platform.allocation_runs "
                    "SET source_snapshot_digest='drifted-incr' WHERE id=:id"
                ),
                {"id": incr_run_id},
            )

        drift_resp = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "incr-drift-publish"},
        )
        assert drift_resp.status_code == 409
        assert drift_resp.json()["code"] == "blocked_by_snapshot_drift"


@pytest.mark.anyio
async def test_incremental_publish_rejects_initial_run(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """publish-incremental endpoint rejects an initial-mode run."""
    manager = add_review_user(
        database, settings, admin, email="incr-mode-mgr@example.test", role="campaign_manager"
    )
    r1, r2 = [
        add_review_user(
            database, settings, admin, email=f"incr-mode-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        manager_csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(manager_csrf)
        campaign_id, base_run_id = await setup_campaign_with_published_run(
            admin_client,
            manager_client,
            admin,
            manager,
            [r1, r2],
            campaign_key="incr-mode-check",
            mutation_hdrs=headers,
        )
        runs = base_alloc_path(admin.tenant_id, campaign_id)

        # Persist a second INITIAL run (not incremental)
        body = dict(FEASIBLE_POLICY)
        body["reviewer_ids"] = [str(r1.user_id), str(r2.user_id)]
        second = await manager_client.post(
            runs,
            json=body,
            headers={**headers, "Idempotency-Key": "second-initial-run"},
        )
        assert second.status_code == 201, second.text
        second_run_id = str(second.json()["run_id"])

        wrong_endpoint = await manager_client.post(
            f"{runs}/{second_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "wrong-endpoint-001"},
        )
        assert wrong_endpoint.status_code == 409
        assert wrong_endpoint.json()["code"] == "not_an_incremental_run"


@pytest.mark.anyio
async def test_incremental_idempotent_publish(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="incr-idem-mgr@example.test", role="campaign_manager"
    )
    r1, r2 = [
        add_review_user(
            database, settings, admin, email=f"incr-idem-r{i}@example.test", role="reviewer"
        )
        for i in range(1, 3)
    ]
    r3 = add_review_user(
        database, settings, admin, email="incr-idem-r3@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        campaign_id, base_run_id = await setup_campaign_with_published_run(
            admin_client,
            manager_client,
            admin,
            manager,
            [r1, r2],
            campaign_key="incr-idem",
            mutation_hdrs=headers,
        )
        runs = base_alloc_path(admin.tenant_id, campaign_id)
        body = incr_policy(
            [str(r1.user_id), str(r2.user_id), str(r3.user_id)],
            base_run_id,
            min_reviews_per_subject=3,
        )
        persisted = await manager_client.post(
            f"{runs}/incremental",
            json=body,
            headers={**headers, "Idempotency-Key": "idem-persist"},
        )
        assert persisted.status_code == 201, persisted.text
        incr_run_id = str(persisted.json()["run_id"])

        pub1 = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "idem-pub-1"},
        )
        assert pub1.status_code == 201, pub1.text
        assert pub1.json()["replayed"] is False

        pub2 = await manager_client.post(
            f"{runs}/{incr_run_id}/publish-incremental",
            headers={**headers, "Idempotency-Key": "idem-pub-1"},
        )
        assert pub2.status_code == 201
        assert pub2.json()["replayed"] is True
        assert pub2.json()["run_id"] == incr_run_id
