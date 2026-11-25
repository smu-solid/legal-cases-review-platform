from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select, text

from review_platform.db.models import Tenant, TenantMembership
from review_platform.db.session import Database
from review_platform.review.models import AllocationRun, AssignmentPlan
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, claim_field, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity, ReviewIdentity

# Four eligible metadata_field subjects come from the synthetic fixture; this policy is feasible for
# two reviewers (1 global + 1 pairwise + 2 unique distinct subjects, three assignments each).
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


def base_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs"


def policy_body(reviewers: list[ReviewIdentity], **overrides: object) -> dict[str, object]:
    body: dict[str, object] = dict(FEASIBLE_POLICY)
    body["reviewer_ids"] = [str(reviewer.user_id) for reviewer in reviewers]
    body.update(overrides)
    return body


async def submit_grouped_answer(
    client,
    csrf_token: str,
    tenant_id: str,
    assignment_id: str,
    *,
    idem: str,
) -> None:
    grouped = await client.get(
        f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
    )
    assert grouped.status_code == 200, grouped.text
    lock_version = grouped.json()["lock_version"]
    submit = await client.post(
        f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/submit",
        json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
        headers={
            **mutation_headers(csrf_token),
            "Idempotency-Key": idem,
            "If-Match": f'"{lock_version}"',
        },
    )
    assert submit.status_code == 201, submit.text


async def manager_session(
    settings: Settings, database: Database, admin: AdminIdentity
) -> tuple[ReviewIdentity, list[ReviewIdentity]]:
    manager = add_review_user(
        database, settings, admin, email="campaign-manager@example.test", role="campaign_manager"
    )
    reviewers = [
        add_review_user(
            database, settings, admin, email=f"alloc-reviewer-{index}@example.test", role="reviewer"
        )
        for index in range(1, 3)
    ]
    return manager, reviewers


@pytest.mark.anyio
async def test_allocation_preview_persist_inspect_publish_blinded(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, reviewers = await manager_session(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client, reviewer_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(
            admin_client, admin, key="alloc-happy", review_kinds=["metadata_field"]
        )
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = base_path(admin.tenant_id, campaign_id)

        subjects = await manager_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/subjects/preview",
            json={"subject_kind": "case", "review_kind": "metadata_field", "limit": 10},
            headers=headers,
        )
        assert subjects.status_code == 200, subjects.text
        assert subjects.json()["eligible_subject_count"] == 4
        assert len(subjects.json()["samples"]) == 4

        preview = await manager_client.post(
            f"{runs}/preview", json=policy_body(reviewers), headers=headers
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["feasibility"]["status"] == "feasible"
        assert preview.headers["cache-control"] == "no-store"
        matrix = preview.json()["pairwise_overlap_matrix"]
        r0, r1 = str(reviewers[0].user_id), str(reviewers[1].user_id)
        assert matrix[r0][r1] == 2

        persisted = await manager_client.post(
            runs, json=policy_body(reviewers), headers={**headers, "Idempotency-Key": "persist-001"}
        )
        assert persisted.status_code == 201, persisted.text
        run_id = persisted.json()["run_id"]
        assert persisted.json()["status"] == "planned"
        assert persisted.json()["planned_assignment_count"] == 6
        replay = await manager_client.post(
            runs, json=policy_body(reviewers), headers={**headers, "Idempotency-Key": "persist-001"}
        )
        assert replay.status_code == 201
        assert replay.json()["run_id"] == run_id
        assert replay.json()["replayed"] is True

        listed = await manager_client.get(runs)
        assert listed.status_code == 200
        assert [item["run_id"] for item in listed.json()["items"]] == [run_id]
        assert listed.json()["next_cursor"] is None
        assert listed.json()["has_more"] is False
        run_matrix = await manager_client.get(f"{runs}/{run_id}/matrix")
        assert run_matrix.status_code == 200
        assert run_matrix.json()["all_reviewer_overlap_count"] == 1
        workloads = await manager_client.get(f"{runs}/{run_id}/reviewer-workloads")
        assert workloads.status_code == 200
        assert sorted(
            item["planned_assignment_count"] for item in workloads.json()["reviewer_workloads"]
        ) == [3, 3]
        coverage = await manager_client.get(f"{runs}/{run_id}/subject-coverage")
        assert coverage.status_code == 200
        assert coverage.json()["subject_coverage"]["assigned_distinct_subjects"] == 4

        published = await manager_client.post(
            f"{runs}/{run_id}/publish", headers={**headers, "Idempotency-Key": "publish-001"}
        )
        assert published.status_code == 201, published.text
        assert published.json()["created_assignment_count"] == 6
        assert published.json()["status"] == "published"
        publish_replay = await manager_client.post(
            f"{runs}/{run_id}/publish", headers={**headers, "Idempotency-Key": "publish-001"}
        )
        assert publish_replay.status_code == 201
        assert publish_replay.json()["replayed"] is True

        # The published assignments reach the reviewer through the existing blinded surface only.
        reviewer_csrf = await authenticate(reviewer_client, reviewers[0])
        queue = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "review_kind": "metadata_field"},
        )
        assert queue.status_code == 200
        assert len(queue.json()["items"]) == 3
        assert {item["assignment_status"] for item in queue.json()["items"]} == {"assigned"}
        assert all(item["assignment_id"] for item in queue.json()["items"])
        queue_text = queue.text
        for forbidden in (
            "overlap_group_key",
            "selection_layer",
            "pairwise",
            "global_hub",
            str(reviewers[1].user_id),
            "allocation_run",
        ):
            assert forbidden not in queue_text
        assigned_item = queue.json()["items"][0]
        claim_existing = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"review_unit_id": assigned_item["review_unit_id"], "campaign_id": campaign_id},
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "claim-published-existing-001",
            },
        )
        assert claim_existing.status_code == 201
        assert claim_existing.json()["assignment_id"] == assigned_item["assignment_id"]
        claim_existing_replay = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"review_unit_id": assigned_item["review_unit_id"], "campaign_id": campaign_id},
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "claim-published-existing-001",
            },
        )
        assert claim_existing_replay.status_code == 201
        assert claim_existing_replay.json()["replayed"] is True
        own = await reviewer_client.get(f"/api/v1/tenants/{admin.tenant_id}/review/assignments")
        assert own.status_code == 200
        assert len(own.json()) == 3
        for forbidden in (
            "overlap_group_key",
            "selection_layer",
            "pairwise",
            "global_hub",
            str(reviewers[1].user_id),
            "allocation_run",
        ):
            assert forbidden not in own.text

    with database.session() as session:
        plans = session.scalars(
            select(AssignmentPlan).where(AssignmentPlan.allocation_run_id == uuid.UUID(run_id))
        ).all()
        assert len(plans) == 6
        assert all(plan.status == "published" and plan.assignment_id is not None for plan in plans)


@pytest.mark.anyio
async def test_publish_from_policy_persists_and_publishes_in_one_request(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Test publish from policy persists and publishes in one request."""

    manager, reviewers = await manager_session(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="alloc-publish-from-policy")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = base_path(admin.tenant_id, campaign_id)

        published = await manager_client.post(
            f"{runs}/publish",
            json=policy_body(reviewers),
            headers={**headers, "Idempotency-Key": "publish-from-policy-001"},
        )
        assert published.status_code == 201, published.text
        assert published.json()["status"] == "published"
        assert published.json()["created_assignment_count"] == 6
        run_id = published.json()["run_id"]

        # The run this created is a normal, fully-persisted run -- reachable through the existing
        # run-inspection surface exactly as if it had gone through the separate persist step.
        fetched_run = await manager_client.get(f"{runs}/{run_id}")
        assert fetched_run.status_code == 200
        assert fetched_run.json()["status"] == "published"

        replay = await manager_client.post(
            f"{runs}/publish",
            json=policy_body(reviewers),
            headers={**headers, "Idempotency-Key": "publish-from-policy-001"},
        )
        assert replay.status_code == 201
        assert replay.json()["run_id"] == run_id
        assert replay.json()["replayed"] is True

    with database.session() as session:
        plans = session.scalars(
            select(AssignmentPlan).where(AssignmentPlan.allocation_run_id == uuid.UUID(run_id))
        ).all()
        assert len(plans) == 6
        assert all(plan.status == "published" and plan.assignment_id is not None for plan in plans)


@pytest.mark.anyio
async def test_uniform_coverage_policy_is_feasible_with_more_cases_than_reviewers(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """Test uniform coverage policy is feasible with more cases than reviewers."""

    manager = add_review_user(
        database,
        settings,
        admin,
        email="uniform-coverage-manager@example.test",
        role="campaign_manager",
    )
    reviewers = [
        add_review_user(
            database,
            settings,
            admin,
            email=f"uniform-coverage-reviewer-{index}@example.test",
            role="reviewer",
        )
        for index in range(1, 4)
    ]
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="alloc-uniform-coverage")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)
        runs = base_path(admin.tenant_id, campaign_id)

        body = policy_body(
            reviewers,
            target_pairwise_overlap=0,
            target_global_overlap=0,
            target_per_reviewer_workload=3,
            uniform_reviews_per_subject=2,
        )
        preview = await manager_client.post(f"{runs}/preview", json=body, headers=headers)
        assert preview.status_code == 200, preview.text
        assert preview.json()["feasibility"]["status"] == "feasible"
        assert preview.json()["subject_coverage"]["assigned_distinct_subjects"] == 4

        persisted = await manager_client.post(
            runs, json=body, headers={**headers, "Idempotency-Key": "uniform-persist-001"}
        )
        assert persisted.status_code == 201, persisted.text
        assert persisted.json()["planned_assignment_count"] == 8
        run_id = persisted.json()["run_id"]

        workloads = await manager_client.get(f"{runs}/{run_id}/reviewer-workloads")
        assert workloads.status_code == 200
        counts = [
            item["planned_assignment_count"] for item in workloads.json()["reviewer_workloads"]
        ]
        assert sum(counts) == 8
        assert max(counts) - min(counts) <= 1

        published = await manager_client.post(
            f"{runs}/{run_id}/publish",
            headers={**headers, "Idempotency-Key": "uniform-publish-001"},
        )
        assert published.status_code == 201, published.text
        assert published.json()["created_assignment_count"] == 8

    with database.session() as session:
        plans = session.scalars(
            select(AssignmentPlan).where(AssignmentPlan.allocation_run_id == uuid.UUID(run_id))
        ).all()
        assert len(plans) == 8
        by_subject: dict[uuid.UUID, set[uuid.UUID]] = {}
        for plan in plans:
            by_subject.setdefault(plan.review_unit_id, set()).add(plan.reviewer_id)
        assert len(by_subject) == 4
        assert all(len(reviewer_ids) == 2 for reviewer_ids in by_subject.values())


@pytest.mark.anyio
async def test_completed_or_adjudication_subjects_are_excluded_from_new_allocation_pool(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, reviewers = await manager_session(settings, database, admin)
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, manager_client, first_reviewer, second_reviewer = await open_clients(
            stack, settings, 4
        )
        imported = await import_campaign(
            admin_client, admin, key="alloc-exclusion", review_kinds=["metadata_field"]
        )
        campaign_id = str(imported["campaign_id"])
        manager_csrf = await authenticate(manager_client, manager)
        first_csrf = await authenticate(first_reviewer, reviewers[0])
        second_csrf = await authenticate(second_reviewer, reviewers[1])
        preview_path = (
            f"/api/v1/admin/tenants/{admin.tenant_id}/campaigns/{campaign_id}/subjects/preview"
        )

        before = await manager_client.post(
            preview_path,
            json={"subject_kind": "case", "review_kind": "metadata_field", "limit": 10},
            headers=mutation_headers(manager_csrf),
        )
        assert before.status_code == 200, before.text
        assert before.json()["eligible_subject_count"] == 4

        first_assignment = await claim_field(
            first_reviewer,
            first_csrf,
            tenant_id,
            campaign_id,
            "Subject",
            idem="alloc-exclusion-claim-one",
        )
        await submit_grouped_answer(
            first_reviewer,
            first_csrf,
            tenant_id,
            first_assignment,
            idem="alloc-exclusion-submit-one",
        )
        second_assignment = await claim_field(
            second_reviewer,
            second_csrf,
            tenant_id,
            campaign_id,
            "Subject",
            idem="alloc-exclusion-claim-two",
        )
        await submit_grouped_answer(
            second_reviewer,
            second_csrf,
            tenant_id,
            second_assignment,
            idem="alloc-exclusion-submit-two",
        )

        after = await manager_client.post(
            preview_path,
            json={"subject_kind": "case", "review_kind": "metadata_field", "limit": 10},
            headers=mutation_headers(manager_csrf),
        )
        assert after.status_code == 200, after.text
        assert after.json()["eligible_subject_count"] == 3
        assert "Subject" not in {item["display_title"] for item in after.json()["samples"]}


@pytest.mark.anyio
async def test_allocation_rbac_and_infeasibility(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, reviewers = await manager_session(settings, database, admin)
    plain_reviewer = add_review_user(
        database, settings, admin, email="plain-reviewer@example.test", role="reviewer"
    )
    with database.session() as session, session.begin():
        other = Tenant(key="other-alloc-tenant", name="Other Alloc Tenant")
        session.add(other)
        session.flush()
        other_tenant_id = other.id
    async with AsyncExitStack() as stack:
        admin_client, manager_client, reviewer_client, anon_client = await open_clients(
            stack, settings, 4
        )
        imported = await import_campaign(admin_client, admin, key="alloc-rbac")
        campaign_id = str(imported["campaign_id"])
        runs = base_path(admin.tenant_id, campaign_id)

        # Deny by default: an authenticated reviewer without campaign_manager is forbidden.
        reviewer_csrf = await authenticate(reviewer_client, plain_reviewer)
        forbidden = await reviewer_client.post(
            f"{runs}/preview", json=policy_body(reviewers), headers=mutation_headers(reviewer_csrf)
        )
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "forbidden"

        # Unauthenticated read is rejected before any allocation logic runs.
        unauth = await anon_client.get(runs)
        assert unauth.status_code == 401

        manager_csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(manager_csrf)

        # Cross-tenant: a manager scoped to one tenant cannot act on another tenant path.
        cross = await manager_client.post(
            base_path(other_tenant_id, str(uuid.uuid4())) + "/preview",
            json=policy_body(reviewers),
            headers=headers,
        )
        assert cross.status_code == 403

        # Infeasible arithmetic returns a structured report on preview and a 422 on persist.
        infeasible = policy_body(
            reviewers,
            target_distinct_subjects=4,
            target_per_reviewer_workload=10,
            target_pairwise_overlap=2,
            target_global_overlap=1,
        )
        preview = await manager_client.post(f"{runs}/preview", json=infeasible, headers=headers)
        assert preview.status_code == 200
        assert preview.json()["feasibility"]["status"] == "infeasible"
        assert preview.json()["feasibility"]["errors"]
        persisted = await manager_client.post(
            runs, json=infeasible, headers={**headers, "Idempotency-Key": "infeasible-001"}
        )
        assert persisted.status_code == 422
        assert persisted.json()["code"] == "allocation_infeasible"


@pytest.mark.anyio
async def test_allocation_run_list_paginates_with_stable_cursor(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, reviewers = await manager_session(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="alloc-pagination")
        campaign_id = str(imported["campaign_id"])
        runs = base_path(admin.tenant_id, campaign_id)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)

        for index in range(3):
            response = await manager_client.post(
                runs,
                json=policy_body(reviewers, random_seed=f"page-seed-{index}"),
                headers={**headers, "Idempotency-Key": f"persist-page-{index}"},
            )
            assert response.status_code == 201, response.text

        full = await manager_client.get(runs)
        assert full.status_code == 200, full.text
        expected_ids = [item["run_id"] for item in full.json()["items"]]
        assert len(expected_ids) == 3
        assert full.json()["has_more"] is False

        first = await manager_client.get(runs, params={"limit": "2"})
        assert first.status_code == 200, first.text
        first_body = first.json()
        assert [item["run_id"] for item in first_body["items"]] == expected_ids[:2]
        assert first_body["has_more"] is True
        assert first_body["next_cursor"]

        second = await manager_client.get(
            runs, params={"limit": "2", "cursor": first_body["next_cursor"]}
        )
        assert second.status_code == 200, second.text
        second_body = second.json()
        assert [item["run_id"] for item in second_body["items"]] == expected_ids[2:]
        assert second_body["has_more"] is False
        assert second_body["next_cursor"] is None

        invalid = await manager_client.get(runs, params={"cursor": "not-a-cursor"})
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "cursor_invalid"


@pytest.mark.anyio
async def test_allocation_discard_and_drift_guards(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager, reviewers = await manager_session(settings, database, admin)
    async with AsyncExitStack() as stack:
        admin_client, manager_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="alloc-guards")
        campaign_id = str(imported["campaign_id"])
        runs = base_path(admin.tenant_id, campaign_id)
        csrf = await authenticate(manager_client, manager)
        headers = mutation_headers(csrf)

        async def persist(key: str, seed: str) -> str:
            response = await manager_client.post(
                runs,
                json=policy_body(reviewers, random_seed=seed),
                headers={**headers, "Idempotency-Key": key},
            )
            assert response.status_code == 201, response.text
            return str(response.json()["run_id"])

        # Discard a planned run, then prove discarded runs cannot be published.
        discard_run = await persist("persist-discard", "seed-discard")
        discarded = await manager_client.post(
            f"{runs}/{discard_run}/discard", headers={**headers, "Idempotency-Key": "discard-001"}
        )
        assert discarded.status_code == 201
        assert discarded.json()["status"] == "discarded"
        discard_replay = await manager_client.post(
            f"{runs}/{discard_run}/discard", headers={**headers, "Idempotency-Key": "discard-001"}
        )
        assert discard_replay.json()["replayed"] is True
        publish_discarded = await manager_client.post(
            f"{runs}/{discard_run}/publish", headers={**headers, "Idempotency-Key": "publish-bad"}
        )
        assert publish_discarded.status_code == 409
        assert publish_discarded.json()["code"] == "allocation_run_not_publishable"

        # Snapshot drift: the candidate pool identity recorded at planning no longer matches.
        drift_run = await persist("persist-drift", "seed-drift")
        with database.session() as session, session.begin():
            session.execute(
                text(
                    "UPDATE review_platform.allocation_runs "
                    "SET source_snapshot_digest='drifted' WHERE id=:id"
                ),
                {"id": drift_run},
            )
        drift = await manager_client.post(
            f"{runs}/{drift_run}/publish", headers={**headers, "Idempotency-Key": "publish-drift"}
        )
        assert drift.status_code == 409
        assert drift.json()["code"] == "blocked_by_snapshot_drift"

        # Reviewer-pool drift: a planned reviewer is no longer authorized at publish time.
        pool_run = await persist("persist-pool", "seed-pool")
        with database.session() as session, session.begin():
            membership_id = session.scalar(
                select(TenantMembership.id).where(
                    TenantMembership.tenant_id == admin.tenant_id,
                    TenantMembership.user_id == reviewers[1].user_id,
                )
            )
            session.execute(
                text(
                    "UPDATE review_platform.role_grants SET revoked_at=now() "
                    "WHERE membership_id=:mid AND role_code='reviewer'"
                ),
                {"mid": membership_id},
            )
        pool = await manager_client.post(
            f"{runs}/{pool_run}/publish", headers={**headers, "Idempotency-Key": "publish-pool"}
        )
        assert pool.status_code == 409
        assert pool.json()["code"] == "blocked_by_reviewer_pool"

    with database.session() as session:
        statuses = set(
            session.scalars(
                select(AllocationRun.status).where(
                    AllocationRun.campaign_id == uuid.UUID(campaign_id)
                )
            )
        )
        assert statuses == {"planned", "discarded"}
