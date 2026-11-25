from __future__ import annotations

import math
import uuid
from contextlib import AsyncExitStack

import pytest

from review_platform.common.json import digest_json
from review_platform.db.session import Database
from review_platform.review.models import Campaign, ReviewSubject, ReviewUnit, SourceSnapshot
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, login, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


def summary_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/allocation-summary"


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


def _seed_draft_campaign_with_cases(
    database: Database,
    admin: AdminIdentity,
    *,
    key: str,
    case_count: int,
    reviewer_ids: list[uuid.UUID],
    minimum_reviews_per_case: int,
) -> uuid.UUID:
    """Build a ``draft`` campaign with real review units directly at the ORM layer.

    There is no public API path that produces a non-``published`` campaign with real review
    units: ``create_campaign`` makes an empty draft, and both import paths (synthetic/real) always
    create a ``published`` campaign, whose ``policy_json``/reviewer selection the ``campaigns``
    table trigger then freezes. Seeding a draft directly is the only way to exercise the
    allocation-math endpoint's feasible/plan branches against real cases in a test.
    """

    with database.session() as session, session.begin():
        campaign = Campaign(
            tenant_id=admin.tenant_id,
            key=key,
            name=f"Draft {key}",
            status="draft",
            policy_version="test-v1",
            policy_json={
                "selected_reviewer_ids": [str(rid) for rid in reviewer_ids],
                "minimum_reviews_per_case": minimum_reviews_per_case,
            },
            manifest_digest=digest_json({"test": key}),
            created_by=admin.user_id,
        )
        session.add(campaign)
        session.flush()
        for i in range(case_count):
            # One ReviewSubject per SourceSnapshot (uq_subject_snapshot), so each case needs its
            # own snapshot row.
            snapshot = SourceSnapshot(
                tenant_id=admin.tenant_id,
                contract_version="v0001",
                source_mode="synthetic",
                source_version="test",
                external_item_key=f"{key}-snapshot-{i}",
                input_digest=digest_json({"snapshot": key, "i": i}),
            )
            session.add(snapshot)
            session.flush()
            subject = ReviewSubject(
                tenant_id=admin.tenant_id,
                source_snapshot_id=snapshot.id,
                subject_kind="case",
                external_subject_id=f"CAS-{key}-{i:03d}",
                display_title=f"Case {i}",
                primary_source_ref=f"{key}-{i}",
                # Both real importers always set this -- it's the real case identity used to
                # de-dup one case's several field/relation ReviewSubject rows into one case (see
                # campaign_cases.py/campaign_admin.py); omitting it would collapse every case in
                # this fixture into a single NULL group.
                attributes_json={"snapshot_local_case_external_id": f"CAS-{key}-{i:03d}"},
            )
            session.add(subject)
            session.flush()
            unit = ReviewUnit(
                tenant_id=admin.tenant_id,
                campaign_id=campaign.id,
                review_subject_id=subject.id,
                review_kind="citations",
                question="Review the citations candidate pair.",
                safe_field_label="Citations",
                required_reviews=minimum_reviews_per_case,
                input_digest=digest_json({"unit": key, "i": i}),
            )
            session.add(unit)
        return campaign.id


@pytest.mark.anyio
async def test_allocation_summary_forbidden_for_reviewer(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="alloc-forbidden@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="alloc-forbidden")
        await authenticate(client, reviewer)
        r = await client.get(summary_path(admin.tenant_id, imported["campaign_id"]))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_allocation_summary_infeasible_with_no_review_units(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database, settings, admin, email="alloc-mgr-empty@example.test", role="campaign_manager"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        csrf = await authenticate(client, manager)
        draft = await _create_draft(client, csrf, admin, key="alloc-infeasible-empty")
        r = await client.get(summary_path(admin.tenant_id, draft["campaign_id"]))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feasible"] is False
    assert body["infeasible_reason"] == "no_review_units"
    assert body["assignment_plan"] == []


@pytest.mark.anyio
async def test_allocation_summary_infeasible_with_no_selected_reviewers(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="alloc-infeasible-no-reviewers")
        _, csrf_token = await login(client, admin.email, admin.password)
        r = await client.get(summary_path(admin.tenant_id, imported["campaign_id"]))
    assert r.status_code == 200, r.text
    assert r.json()["infeasible_reason"] == "no_selected_reviewers"


@pytest.mark.anyio
async def test_allocation_summary_infeasible_with_single_reviewer(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="alloc-single@example.test", role="reviewer"
    )
    campaign_id = _seed_draft_campaign_with_cases(
        database,
        admin,
        key="alloc-single-reviewer",
        case_count=5,
        reviewer_ids=[reviewer.user_id],
        minimum_reviews_per_case=2,
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await login(client, admin.email, admin.password)
        r = await client.get(summary_path(admin.tenant_id, str(campaign_id)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["feasible"] is False
    assert body["infeasible_reason"] == "insufficient_reviewers"
    assert body["selected_reviewers"] == 1


@pytest.mark.anyio
async def test_allocation_summary_feasible_plan_covers_every_case_with_distinct_reviewers(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer_one = add_review_user(
        database, settings, admin, email="alloc-plan-one@example.test", role="reviewer"
    )
    reviewer_two = add_review_user(
        database, settings, admin, email="alloc-plan-two@example.test", role="reviewer"
    )
    campaign_id = _seed_draft_campaign_with_cases(
        database,
        admin,
        key="alloc-plan",
        case_count=7,
        reviewer_ids=[reviewer_one.user_id, reviewer_two.user_id],
        minimum_reviews_per_case=2,
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await login(client, admin.email, admin.password)
        r = await client.get(summary_path(admin.tenant_id, str(campaign_id)))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["selected_reviewers"] == 2
    assert body["reviews_per_case"] == 2
    assert body["selected_cases"] == 7
    assert body["total_assignments"] == 14
    assert body["estimated_assignments_per_reviewer"] == math.ceil(14 / 2)
    assert body["feasible"] is True
    assert body["infeasible_reason"] is None
    assert len(body["assignment_plan"]) == 7
    for entry in body["assignment_plan"]:
        assert len(entry["reviewer_ids"]) == 2
        assert len(set(entry["reviewer_ids"])) == 2


@pytest.mark.anyio
async def test_allocation_summary_can_skip_plan_without_changing_counts(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewers = [
        add_review_user(
            database,
            settings,
            admin,
            email=f"alloc-counts-{index}@example.test",
            role="reviewer",
        )
        for index in range(2)
    ]
    campaign_id = _seed_draft_campaign_with_cases(
        database,
        admin,
        key="alloc-counts-only",
        case_count=7,
        reviewer_ids=[reviewer.user_id for reviewer in reviewers],
        minimum_reviews_per_case=2,
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await login(client, admin.email, admin.password)
        response = await client.get(
            f"{summary_path(admin.tenant_id, str(campaign_id))}?include_plan=false"
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected_cases"] == 7
    assert body["review_units"] == 7
    assert body["total_assignments"] == 14
    assert body["total_unit_assignments"] == 14
    assert body["assignment_plan"] == []
