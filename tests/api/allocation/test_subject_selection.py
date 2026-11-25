"""Case-selection strategies for the campaign subject pool and allocation readiness edges."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select, text

from review_platform.db.session import Database
from review_platform.review.models import ReviewSubject, ReviewUnit
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, close_campaign, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity, ReviewIdentity

FEASIBLE_POLICY = {
    "subject_kind": "case",
    "review_kind": "metadata_field",
    "target_distinct_subjects": 4,
    "target_per_reviewer_workload": 3,
    "target_pairwise_overlap": 2,
    "target_global_overlap": 1,
    "rolling_window_size": 0,
    "rolling_window_stride": 0,
    "hub_priority_count": 1,
    "random_seed": "alloc-seed-1",
    "allocation_policy_version": "reviewer-allocation/v1",
    "metric_weights": {},
}


def _preview_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/subjects/preview"


def _runs_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs"


async def _manager_and_reviewers(
    settings: Settings, database: Database, admin: AdminIdentity
) -> tuple[ReviewIdentity, list[ReviewIdentity]]:
    manager = add_review_user(
        database, settings, admin, email="selection-manager@example.test", role="campaign_manager"
    )
    reviewers = [
        add_review_user(
            database,
            settings,
            admin,
            email=f"selection-reviewer-{index}@example.test",
            role="reviewer",
        )
        for index in range(1, 3)
    ]
    return manager, reviewers


def _set_citation_metrics(database: Database, tenant_id: uuid.UUID, counts: dict[str, int]) -> None:
    """Set citation metrics."""

    with database.session() as session, session.begin():
        session.execute(text("SET session_replication_role = replica"))
        subjects = session.scalars(
            select(ReviewSubject).where(ReviewSubject.tenant_id == tenant_id)
        ).all()
        for subject in subjects:
            inbound = counts.get(subject.display_title)
            if inbound is None:
                continue
            subject.attributes_json = {
                **subject.attributes_json,
                "citation_metrics": {"inbound_count": inbound, "outbound_count": inbound * 2},
            }
        session.flush()
        session.execute(text("SET session_replication_role = origin"))


async def _preview(client, tenant_id, campaign_id, csrf, **body):
    payload = {"subject_kind": "case", "review_kind": "metadata_field", "limit": 10, **body}
    response = await client.post(
        _preview_path(tenant_id, campaign_id), json=payload, headers=mutation_headers(csrf)
    )
    return response


@pytest.mark.anyio
async def test_subject_preview_sequential_default(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, _ = await _manager_and_reviewers(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        campaign_id = str(
            (
                await import_campaign(
                    admin_client, admin, key="sel-seq", review_kinds=["metadata_field"]
                )
            )["campaign_id"]
        )
        csrf = await authenticate(manager_client, manager)

        response = await _preview(manager_client, admin.tenant_id, campaign_id, csrf)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["selection_strategy"] == "sequential"
        assert body["metrics_available"] is True
        assert body["diagnostic"] is None
        assert [sample["selection_rank"] for sample in body["samples"]] == [0, 1, 2, 3]
        assert all(sample["inbound_citation_count"] is None for sample in body["samples"])


@pytest.mark.anyio
async def test_subject_preview_random_is_deterministic_permutation(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, _ = await _manager_and_reviewers(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        campaign_id = str(
            (await import_campaign(admin_client, admin, key="sel-rnd"))["campaign_id"]
        )
        csrf = await authenticate(manager_client, manager)

        sequential = await _preview(manager_client, admin.tenant_id, campaign_id, csrf)
        sequential_ids = [s["review_subject_id"] for s in sequential.json()["samples"]]

        first = await _preview(
            manager_client,
            admin.tenant_id,
            campaign_id,
            csrf,
            selection_strategy="random",
            random_seed="shuffle-a",
        )
        second = await _preview(
            manager_client,
            admin.tenant_id,
            campaign_id,
            csrf,
            selection_strategy="random",
            random_seed="shuffle-a",
        )
        assert first.status_code == 200, first.text
        first_ids = [s["review_subject_id"] for s in first.json()["samples"]]
        second_ids = [s["review_subject_id"] for s in second.json()["samples"]]
        # Same seed is reproducible, and the pool membership is preserved (a permutation).
        assert first_ids == second_ids
        assert sorted(first_ids) == sorted(sequential_ids)
        assert first.json()["metrics_available"] is True
        assert first.json()["diagnostic"] is None


@pytest.mark.anyio
async def test_citation_hub_unavailable_without_metrics(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, _ = await _manager_and_reviewers(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        campaign_id = str(
            (
                await import_campaign(
                    admin_client, admin, key="sel-nohub", review_kinds=["metadata_field"]
                )
            )["campaign_id"]
        )
        csrf = await authenticate(manager_client, manager)

        response = await _preview(
            manager_client,
            admin.tenant_id,
            campaign_id,
            csrf,
            selection_strategy="citation_in_hub",
        )
        assert response.status_code == 200, response.text
        body = response.json()
        # Fails closed: no invented order, an explicit diagnostic instead.
        assert body["metrics_available"] is False
        assert body["diagnostic"] == "citation_metrics_unavailable"
        assert len(body["samples"]) == 4


@pytest.mark.anyio
async def test_citation_hub_ranks_by_exported_metrics(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, _ = await _manager_and_reviewers(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        campaign_id = str(
            (
                await import_campaign(
                    admin_client, admin, key="sel-hub", review_kinds=["metadata_field"]
                )
            )["campaign_id"]
        )
        csrf = await authenticate(manager_client, manager)

        sequential = await _preview(manager_client, admin.tenant_id, campaign_id, csrf)
        titles = [s["display_title"] for s in sequential.json()["samples"]]
        # Give the last sequential subject the highest inbound degree so ordering must change.
        counts = {titles[0]: 1, titles[1]: 5, titles[2]: 2, titles[3]: 9}
        _set_citation_metrics(database, admin.tenant_id, counts)

        response = await _preview(
            manager_client,
            admin.tenant_id,
            campaign_id,
            csrf,
            selection_strategy="citation_in_hub",
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["metrics_available"] is True
        assert body["diagnostic"] is None
        ranked_titles = [s["display_title"] for s in body["samples"]]
        assert ranked_titles == [titles[3], titles[1], titles[2], titles[0]]
        top = body["samples"][0]
        assert top["inbound_citation_count"] == 9
        assert top["outbound_citation_count"] == 18


@pytest.mark.anyio
async def test_subject_preview_unknown_campaign_is_404(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, _ = await _manager_and_reviewers(settings, database, admin)
    async with AsyncExitStack() as stack:
        (manager_client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(manager_client, manager)
        response = await _preview(manager_client, admin.tenant_id, str(uuid.uuid4()), csrf)
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"


@pytest.mark.anyio
async def test_allocation_run_requires_at_least_two_reviewers(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, reviewers = await _manager_and_reviewers(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        campaign_id = str(
            (await import_campaign(admin_client, admin, key="sel-one"))["campaign_id"]
        )
        csrf = await authenticate(manager_client, manager)
        body = {**FEASIBLE_POLICY, "reviewer_ids": [str(reviewers[0].user_id)]}
        response = await manager_client.post(
            f"{_runs_path(admin.tenant_id, campaign_id)}/preview",
            json=body,
            headers=mutation_headers(csrf),
        )
        # Overlap/agreement allocation is undefined for one reviewer: reject at the contract.
        assert response.status_code == 422, response.text


@pytest.mark.anyio
async def test_reviewer_serves_multiple_campaigns_without_conflict(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, reviewers = await _manager_and_reviewers(settings, database, admin)
    reviewer_ids = [str(reviewer.user_id) for reviewer in reviewers]
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        csrf = await authenticate(manager_client, manager)
        first = str((await import_campaign(admin_client, admin, key="sel-camp-a"))["campaign_id"])
        body = {**FEASIBLE_POLICY, "reviewer_ids": reviewer_ids}
        persisted_a = await manager_client.post(
            _runs_path(admin.tenant_id, first),
            json=body,
            headers={**mutation_headers(csrf), "Idempotency-Key": "multi-camp-0"},
        )
        assert persisted_a.status_code == 201, persisted_a.text
        assert persisted_a.json()["reviewer_count"] == 2
        close_campaign(database, admin.tenant_id, "sel-camp-a")

        second = str((await import_campaign(admin_client, admin, key="sel-camp-b"))["campaign_id"])
        persisted_b = await manager_client.post(
            _runs_path(admin.tenant_id, second),
            json=body,
            headers={**mutation_headers(csrf), "Idempotency-Key": "multi-camp-1"},
        )
        assert persisted_b.status_code == 201, persisted_b.text
        assert persisted_b.json()["reviewer_count"] == 2

        # Both campaigns hold planned assignments for the same two reviewers.
        with database.session() as session:
            unit_campaigns = session.scalars(
                select(ReviewUnit.campaign_id).where(ReviewUnit.tenant_id == admin.tenant_id)
            ).all()
        assert uuid.UUID(first) in unit_campaigns
        assert uuid.UUID(second) in unit_campaigns
