from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select, text, update

from review_platform.db.session import Database
from review_platform.review.models import Assignment
from review_platform.settings import Settings
from tests.support.admin_stats import login_get, progress_path, workload_path
from tests.support.campaigns import add_review_user, claim_field, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_reviewer_workload_unauthenticated(settings: Settings, admin: AdminIdentity) -> None:
    campaign_id = str(uuid.uuid4())
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await client.get(workload_path(admin.tenant_id), params={"campaign_id": campaign_id})
    assert r.status_code == 401


@pytest.mark.anyio
async def test_reviewer_workload_reviewer_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="workload-reviewer@example.test", role="reviewer"
    )
    campaign_id = str(uuid.uuid4())
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(
            client,
            reviewer,
            workload_path(admin.tenant_id),
            params={"campaign_id": campaign_id},
        )
    assert r.status_code == 403


@pytest.mark.anyio
async def test_reviewer_workload_missing_campaign_id(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """campaign_id is required; omitting it must return 422."""
    manager = add_review_user(
        database,
        settings,
        admin,
        email="workload-no-cid@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(client, manager, workload_path(admin.tenant_id))
    assert r.status_code == 422


# ---------------------------------------------------------------------------
# campaign-progress happy-path
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reviewer_workload_empty_before_claims(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="workload-before@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        admin_client, mgr_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="workload-empty")
        campaign_id = str(imported["campaign_id"])

        await authenticate(mgr_client, manager)
        r = await mgr_client.get(
            workload_path(admin.tenant_id), params={"campaign_id": campaign_id}
        )

    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "reviewer-workload/v1"
    assert str(body["campaign_id"]) == campaign_id
    assert body["items"] == []


@pytest.mark.anyio
async def test_reviewer_workload_reflects_claims(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """After a reviewer claims a unit, their workload item appears with claimed_count=1."""
    manager = add_review_user(
        database,
        settings,
        admin,
        email="workload-claim-mgr@example.test",
        role="campaign_manager",
    )
    reviewer = add_review_user(
        database,
        settings,
        admin,
        email="workload-claim-rev@example.test",
        role="reviewer",
    )
    async with AsyncExitStack() as stack:
        admin_client, mgr_client, rev_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(admin_client, admin, key="workload-claims")
        campaign_id = str(imported["campaign_id"])

        # Reviewer claims one unit
        rev_csrf = await authenticate(rev_client, reviewer)
        claim_r = await rev_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"campaign_id": campaign_id},
            headers={**mutation_headers(rev_csrf), "Idempotency-Key": "workload-claim-001"},
        )
        assert claim_r.status_code == 201, claim_r.text

        await authenticate(mgr_client, manager)
        r = await mgr_client.get(
            workload_path(admin.tenant_id), params={"campaign_id": campaign_id}
        )

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert str(item["reviewer_id"]) == str(reviewer.user_id)
    assert item["total_assignments"] == 1
    assert item["claimed_count"] == 1
    assert item["submitted_count"] == 0
    assert item["released_count"] == 0
    # A bare claim is not "work" -- the remove-reviewer freeze must not trigger yet.
    assert item["has_work"] is False


@pytest.mark.anyio
async def test_reviewer_workload_has_work_true_after_submission(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Once a reviewer has submitted an answer, the workload item flags has_work=True so the UI
    can freeze the remove-reviewer control before the click, matching the backend removal guard.
    """
    manager = add_review_user(
        database, settings, admin, email="workload-submit-mgr@example.test", role="campaign_manager"
    )
    reviewer = add_review_user(
        database, settings, admin, email="workload-submit-rev@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        admin_client, mgr_client, rev_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(admin_client, admin, key="workload-submit")
        campaign_id = str(imported["campaign_id"])

        rev_csrf = await authenticate(rev_client, reviewer)
        assignment_id = await claim_field(
            rev_client,
            rev_csrf,
            str(admin.tenant_id),
            campaign_id,
            "Citation Neutral",
            idem="workload-submit-claim",
        )
        bundle = (
            await rev_client.get(
                f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
            )
        ).json()
        submitted = await rev_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(rev_csrf),
                "Idempotency-Key": "workload-submit-submit",
                "If-Match": f'"{bundle["lock_version"]}"',
            },
        )
        assert submitted.status_code == 201, submitted.text

        await authenticate(mgr_client, manager)
        r = await mgr_client.get(
            workload_path(admin.tenant_id), params={"campaign_id": campaign_id}
        )

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["has_work"] is True


@pytest.mark.anyio
async def test_reviewer_workload_wrong_tenant_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="workload-wrong-tenant@example.test",
        role="campaign_manager",
    )
    campaign_id = str(uuid.uuid4())
    wrong_tenant = uuid.uuid4()
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(
            client,
            manager,
            workload_path(wrong_tenant),
            params={"campaign_id": campaign_id},
        )
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Stats do not leak peer review data to ordinary reviewers
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_reviewer_cannot_reach_campaign_progress_after_claim(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Even after a reviewer has an active assignment they must not read campaign stats."""
    reviewer = add_review_user(
        database,
        settings,
        admin,
        email="blind-rev@example.test",
        role="reviewer",
    )
    async with AsyncExitStack() as stack:
        admin_client, rev_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="blind-check")
        campaign_id = str(imported["campaign_id"])

        rev_csrf = await authenticate(rev_client, reviewer)
        await rev_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"campaign_id": campaign_id},
            headers={**mutation_headers(rev_csrf), "Idempotency-Key": "blind-claim-001"},
        )

        r = await rev_client.get(progress_path(admin.tenant_id))
        rw = await rev_client.get(
            workload_path(admin.tenant_id), params={"campaign_id": campaign_id}
        )

    assert r.status_code == 403
    assert rw.status_code == 403


@pytest.mark.anyio
async def test_reviewer_workload_total_excludes_released(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """A released assignment is not part of the reviewer's workload total.

    ``released`` means an incremental rebalance moved that unit AWAY from this reviewer: the row
    survives as an audit record and is already hidden from their queue. Counting it in
    ``total_assignments`` overstated what they hold -- on staging one reviewer read 237 against a
    real 220, with the 17-row gap unexplained on screen. The released rows are still reported, in
    ``released_count``.
    """

    manager = add_review_user(
        database,
        settings,
        admin,
        email="workload-released-mgr@example.test",
        role="campaign_manager",
    )
    reviewer = add_review_user(
        database,
        settings,
        admin,
        email="workload-released-rev@example.test",
        role="reviewer",
    )
    async with AsyncExitStack() as stack:
        admin_client, mgr_client, rev_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(admin_client, admin, key="workload-released")
        campaign_id = str(imported["campaign_id"])

        rev_csrf = await authenticate(rev_client, reviewer)
        for index in range(2):
            claim_r = await rev_client.post(
                f"/api/v1/tenants/{admin.tenant_id}/review/claim",
                json={"campaign_id": campaign_id},
                headers={
                    **mutation_headers(rev_csrf),
                    "Idempotency-Key": f"workload-released-{index}",
                },
            )
            assert claim_r.status_code == 201, claim_r.text

        # Retire one of them exactly as an incremental publish would.
        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tid, true)"),
                {"tid": str(admin.tenant_id)},
            )
            released_id = session.scalar(
                select(Assignment.id)
                .where(
                    Assignment.tenant_id == admin.tenant_id,
                    Assignment.reviewer_id == reviewer.user_id,
                    Assignment.status == "claimed",
                )
                .limit(1)
            )
            assert released_id is not None
            session.execute(
                update(Assignment).where(Assignment.id == released_id).values(status="released")
            )

        await authenticate(mgr_client, manager)
        r = await mgr_client.get(
            workload_path(admin.tenant_id), params={"campaign_id": campaign_id}
        )

    assert r.status_code == 200
    item = next(i for i in r.json()["items"] if str(i["reviewer_id"]) == str(reviewer.user_id))
    # Two assignment rows exist, but only one is live.
    assert item["total_assignments"] == 1
    assert item["claimed_count"] == 1
    assert item["released_count"] == 1
