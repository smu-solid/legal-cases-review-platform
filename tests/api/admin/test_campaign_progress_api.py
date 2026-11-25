from __future__ import annotations

import uuid
from contextlib import AsyncExitStack
from datetime import timedelta

import pytest
from sqlalchemy import select

from review_platform.db.models import utcnow
from review_platform.db.session import Database
from review_platform.review.models import (
    Assignment,
    Campaign,
    Candidate,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.settings import Settings
from tests.support.admin_stats import admin_get, login_get, progress_path
from tests.support.campaigns import add_review_user, close_campaign, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


def _insert_published_campaign_with_cases(
    database: Database,
    tenant_id: uuid.UUID,
    created_by: uuid.UUID,
    *,
    key: str,
    reviewer_ids: list[uuid.UUID],
    case_ids: list[str],
) -> uuid.UUID:
    """A published campaign with a curated roster and ``len(case_ids)`` one-field cases, baked in
    at INSERT time (never via UPDATE) so this never trips the publish-immutability trigger that
    otherwise blocks changing ``policy_json``/adding review units on an already-published campaign.
    """

    with database.session() as session, session.begin():
        campaign = Campaign(
            tenant_id=tenant_id,
            key=key,
            name="N*C progress test campaign",
            status="published",
            policy_json={"selected_reviewer_ids": [str(r) for r in reviewer_ids]},
            manifest_digest="test-manifest-digest",
            created_by=created_by,
        )
        session.add(campaign)
        session.flush()
        for case_id in case_ids:
            snapshot = SourceSnapshot(
                tenant_id=tenant_id,
                contract_version="test-fixture/v1",
                source_version="test-fixture",
                external_item_key=f"test:{key}:{case_id}",
                input_digest="test-digest",
            )
            session.add(snapshot)
            session.flush()
            subject = ReviewSubject(
                tenant_id=tenant_id,
                source_snapshot_id=snapshot.id,
                subject_kind="case",
                external_subject_id=f"subject_{case_id}",
                display_title=f"Case {case_id}",
                display_subtitle="Citation Neutral",
                primary_source_ref=f"source_{case_id}",
                attributes_json={"snapshot_local_case_external_id": case_id},
            )
            session.add(subject)
            session.flush()
            unit = ReviewUnit(
                tenant_id=tenant_id,
                campaign_id=campaign.id,
                review_subject_id=subject.id,
                review_kind="metadata_field",
                question="Confirm Citation Neutral",
                safe_field_label="Citation Neutral",
                input_digest="test-digest",
            )
            session.add(unit)
            session.flush()
            session.add(
                Candidate(
                    tenant_id=tenant_id,
                    review_unit_id=unit.id,
                    label="A",
                    source_kind="deterministic",
                    verdict="supported",
                    value_json=f"[2024] SGCA {case_id[-1]}",
                    rationale="test fixture",
                )
            )
            session.add(
                EvidenceWindow(
                    tenant_id=tenant_id,
                    review_unit_id=unit.id,
                    ordinal=0,
                    kind="quote",
                    snippet=f"[2024] SGCA {case_id[-1]}",
                    source_sha256="0" * 64,
                )
            )
        return campaign.id


def _seed_assignments(
    database: Database,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    case_id: str,
    holders: list[tuple[uuid.UUID, str]],
) -> None:
    """Put ``holders`` -- ``(reviewer_id, status)`` pairs -- on every unit of one case.

    Models what an incremental rebalance leaves behind: a ``released`` row is a unit moved AWAY
    from that reviewer, retained purely as an audit record.
    """

    with database.session() as session, session.begin():
        unit_ids = list(
            session.scalars(
                select(ReviewUnit.id)
                .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
                .where(
                    ReviewUnit.tenant_id == tenant_id,
                    ReviewUnit.campaign_id == campaign_id,
                    ReviewSubject.attributes_json["snapshot_local_case_external_id"].astext
                    == case_id,
                )
            )
        )
        assert unit_ids, f"no review units for {case_id}"
        session.add_all(
            Assignment(
                tenant_id=tenant_id,
                review_unit_id=unit_id,
                reviewer_id=reviewer_id,
                status=status,
                lease_expires_at=utcnow() + timedelta(hours=1),
            )
            for unit_id in unit_ids
            for reviewer_id, status in holders
        )


@pytest.mark.anyio
async def test_case_progress_ignores_released_assignments(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """A released row must not inflate a case's reviewer count.

    This is the shape a repaired-from-fragmentation case has on staging: two reviewers hold the
    case, and a third's rows survive as ``released`` audit records. Counting those made the
    progress cell read "0/3" in a two-reviews-per-case campaign.
    """

    manager = add_review_user(
        database, settings, admin, email="progress-rel-mgr@example.test", role="campaign_manager"
    )
    holder_one = add_review_user(
        database, settings, admin, email="progress-rel-r1@example.test", role="reviewer"
    )
    holder_two = add_review_user(
        database, settings, admin, email="progress-rel-r2@example.test", role="reviewer"
    )
    moved_off = add_review_user(
        database, settings, admin, email="progress-rel-r3@example.test", role="reviewer"
    )
    campaign_id_uuid = _insert_published_campaign_with_cases(
        database,
        admin.tenant_id,
        admin.user_id,
        key="progress-released",
        reviewer_ids=[holder_one.user_id, holder_two.user_id, moved_off.user_id],
        case_ids=["CASE000000000011"],
    )
    _seed_assignments(
        database,
        admin.tenant_id,
        campaign_id_uuid,
        "CASE000000000011",
        [
            (holder_one.user_id, "claimed"),
            (holder_two.user_id, "claimed"),
            (moved_off.user_id, "released"),
        ],
    )
    async with AsyncExitStack() as stack:
        (mgr_client,) = await open_clients(stack, settings, 1)
        await authenticate(mgr_client, manager)
        cases = await mgr_client.get(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns/{campaign_id_uuid}/cases"
        )
    assert cases.status_code == 200, cases.text
    item = next(i for i in cases.json()["items"] if i["case_id"] == "CASE000000000011")
    # Two live holders, not three. The released reviewer no longer holds this case.
    assert item["reviewers_assigned_count"] == 2
    # ... and their rows do not pad the assignment total either.
    assert item["assignment_count"] == 2
    assert item["reviewers_completed_count"] == 0


@pytest.mark.anyio
async def test_case_with_a_released_reviewer_can_still_be_fully_complete(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """``cases_fully_complete_count`` compares submissions against LIVE holders.

    While released rows counted as holders, a case a rebalance had moved work off could never be
    complete: every remaining reviewer could submit and the count would still fall short.
    """

    manager = add_review_user(
        database, settings, admin, email="progress-relc-mgr@example.test", role="campaign_manager"
    )
    holder = add_review_user(
        database, settings, admin, email="progress-relc-r1@example.test", role="reviewer"
    )
    moved_off = add_review_user(
        database, settings, admin, email="progress-relc-r2@example.test", role="reviewer"
    )
    campaign_id_uuid = _insert_published_campaign_with_cases(
        database,
        admin.tenant_id,
        admin.user_id,
        key="progress-released-complete",
        reviewer_ids=[holder.user_id, moved_off.user_id],
        case_ids=["CASE000000000012"],
    )
    campaign_id = str(campaign_id_uuid)
    _seed_assignments(
        database,
        admin.tenant_id,
        campaign_id_uuid,
        "CASE000000000012",
        [(moved_off.user_id, "released")],
    )
    async with AsyncExitStack() as stack:
        mgr_client, holder_client = await open_clients(stack, settings, 2)
        await authenticate(mgr_client, manager)
        holder_csrf = await authenticate(holder_client, holder)

        queue = await holder_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "assignment_status": "available"},
        )
        target_unit = next(
            item for item in queue.json()["items"] if item["case_id"] == "CASE000000000012"
        )
        claim = await holder_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"review_unit_id": target_unit["review_unit_id"]},
            headers={**mutation_headers(holder_csrf), "Idempotency-Key": "rel-claim"},
        )
        assert claim.status_code == 201, claim.text
        assignment_id = claim.json()["assignment_id"]
        bundle = (
            await holder_client.get(
                f"/api/v1/tenants/{admin.tenant_id}"
                f"/review/assignments/{assignment_id}/grouped-bundle"
            )
        ).json()
        await holder_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(holder_csrf),
                "Idempotency-Key": "rel-submit-field",
                "If-Match": f'"{bundle["lock_version"]}"',
            },
        )
        await holder_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/case-submit",
            headers={**mutation_headers(holder_csrf), "Idempotency-Key": "rel-case-submit"},
        )

        progress = await mgr_client.get(progress_path(admin.tenant_id))
    item = next(i for i in progress.json()["items"] if i["campaign_id"] == campaign_id)
    # The one live holder submitted the case, so the case is done -- the released row must not
    # raise the bar to two.
    assert item["case_reviewer_completions"] == 1
    assert item["cases_fully_complete_count"] == 1


@pytest.mark.anyio
async def test_campaign_progress_unauthenticated(settings: Settings, admin: AdminIdentity) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await client.get(progress_path(admin.tenant_id))
    assert r.status_code == 401


@pytest.mark.anyio
async def test_campaign_progress_reviewer_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="progress-reviewer@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(client, reviewer, progress_path(admin.tenant_id))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_campaign_progress_adjudicator_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    adj = add_review_user(
        database, settings, admin, email="progress-adj@example.test", role="adjudicator"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(client, adj, progress_path(admin.tenant_id))
    assert r.status_code == 403


@pytest.mark.anyio
async def test_campaign_progress_wrong_tenant_forbidden(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="progress-mgr-wrong@example.test",
        role="campaign_manager",
    )
    wrong_tenant = uuid.uuid4()
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        r = await login_get(client, manager, progress_path(wrong_tenant))
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# RBAC: reviewer-workload
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_campaign_progress_manager_sees_imported_campaign(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="progress-mgr@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        admin_client, mgr_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="progress-happy")
        campaign_id = str(imported["campaign_id"])

        await authenticate(mgr_client, manager)
        r = await mgr_client.get(progress_path(admin.tenant_id))

    assert r.status_code == 200
    body = r.json()
    assert body["schema_version"] == "campaign-progress-list/v1"
    assert str(body["tenant_id"]) == str(admin.tenant_id)
    items = body["items"]
    assert len(items) == 1
    item = items[0]
    assert str(item["campaign_id"]) == campaign_id
    assert item["schema_version"] == "campaign-progress/v1"
    # Synthetic v0001 imports non-zero units; all start as "pending" (no claims yet)
    assert item["total_units"] > 0
    assert item["unit_status_counts"]["pending"] == item["total_units"]
    assert item["unit_status_counts"]["in_review"] == 0
    assert item["unit_status_counts"]["in_adjudication"] == 0
    assert item["unit_status_counts"]["resolved"] == 0
    assert item["total_assignments"] == 0
    assert item["assignment_status_counts"]["claimed"] == 0
    assert item["assignment_status_counts"]["submitted"] == 0
    assert item["assignment_status_counts"]["released"] == 0
    # cases_total counts distinct subjects, which is <= total_units (a case may have several
    # fields/units); no reviewers are selected on a fresh synthetic import.
    assert 0 < item["cases_total"] <= item["total_units"]
    assert item["reviewers_total"] == 0
    assert item["cases_fully_complete_count"] == 0
    # Never manually marked completed -- derived flag must default false, matching
    # CampaignDetailResponse.completed.
    assert item["completed"] is False


@pytest.mark.anyio
async def test_campaign_progress_reflects_marked_completed(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="progress-completed-mgr@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        admin_client, mgr_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="progress-completed")
        campaign_id = str(imported["campaign_id"])

        mgr_csrf = await authenticate(mgr_client, manager)
        completed = await mgr_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns/{campaign_id}/complete",
            headers=mutation_headers(mgr_csrf),
        )
        assert completed.status_code == 200, completed.text

        r = await mgr_client.get(progress_path(admin.tenant_id))

    assert r.status_code == 200
    items = r.json()["items"]
    item = next(i for i in items if i["campaign_id"] == campaign_id)
    assert item["completed"] is True


@pytest.mark.anyio
async def test_campaign_progress_super_admin_sees_campaign(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        imported = await import_campaign(client, admin, key="progress-super")
        campaign_id = str(imported["campaign_id"])
        r = await admin_get(client, admin, progress_path(admin.tenant_id))

    assert r.status_code == 200
    ids = [item["campaign_id"] for item in r.json()["items"]]
    assert campaign_id in ids


@pytest.mark.anyio
async def test_campaign_progress_filter_by_campaign_id(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="progress-filter@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        admin_client, mgr_client = await open_clients(stack, settings, 2)
        imp_a = await import_campaign(admin_client, admin, key="progress-filter-a")
        close_campaign(database, admin.tenant_id, "progress-filter-a")
        await import_campaign(admin_client, admin, key="progress-filter-b")
        campaign_a = str(imp_a["campaign_id"])

        await authenticate(mgr_client, manager)
        r = await mgr_client.get(progress_path(admin.tenant_id), params={"campaign_id": campaign_a})

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert str(items[0]["campaign_id"]) == campaign_a


@pytest.mark.anyio
async def test_campaign_progress_case_reviewer_slots_and_completions(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """reviews_per_case * C cases is the "slots" denominator; a slot fills only once a reviewer
    explicitly submits a case, not merely because its fields are submitted. Here roster size equals
    reviews_per_case (2), so the denominator is 4 either way -- see
    test_slots_use_reviews_per_case_not_roster_size for the case that distinguishes them."""

    manager = add_review_user(
        database, settings, admin, email="progress-nc-mgr@example.test", role="campaign_manager"
    )
    reviewer_one = add_review_user(
        database, settings, admin, email="progress-nc-r1@example.test", role="reviewer"
    )
    reviewer_two = add_review_user(
        database, settings, admin, email="progress-nc-r2@example.test", role="reviewer"
    )
    campaign_id_uuid = _insert_published_campaign_with_cases(
        database,
        admin.tenant_id,
        admin.user_id,
        key="progress-nc",
        reviewer_ids=[reviewer_one.user_id, reviewer_two.user_id],
        case_ids=["CASE000000000001", "CASE000000000002"],
    )
    campaign_id = str(campaign_id_uuid)
    async with AsyncExitStack() as stack:
        mgr_client, r1_client = await open_clients(stack, settings, 2)

        await authenticate(mgr_client, manager)
        before = await mgr_client.get(progress_path(admin.tenant_id))
        before_item = next(
            item for item in before.json()["items"] if item["campaign_id"] == campaign_id
        )
        assert before_item["reviewers_total"] == 2
        assert before_item["cases_total"] == 2
        assert before_item["case_reviewer_slots_total"] == 4
        assert before_item["case_reviewer_completions"] == 0
        assert before_item["cases_fully_complete_count"] == 0

        r1_csrf = await authenticate(r1_client, reviewer_one)
        queue = await r1_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "assignment_status": "available"},
        )
        target_unit = next(
            item for item in queue.json()["items"] if item["case_id"] == "CASE000000000001"
        )
        claim = await r1_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"review_unit_id": target_unit["review_unit_id"]},
            headers={**mutation_headers(r1_csrf), "Idempotency-Key": "nc-claim"},
        )
        assert claim.status_code == 201, claim.text
        assignment_id = claim.json()["assignment_id"]
        bundle = (
            await r1_client.get(
                f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
            )
        ).json()
        await r1_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(r1_csrf),
                "Idempotency-Key": "nc-submit-field",
                "If-Match": f'"{bundle["lock_version"]}"',
            },
        )

        # All fields submitted for this case, but no explicit case-submit yet -- still 0 slots
        # filled at the campaign level.
        mid = await mgr_client.get(progress_path(admin.tenant_id))
        mid_item = next(item for item in mid.json()["items"] if item["campaign_id"] == campaign_id)
        assert mid_item["case_reviewer_completions"] == 0
        assert mid_item["cases_fully_complete_count"] == 0

        await r1_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/case-submit",
            headers={**mutation_headers(r1_csrf), "Idempotency-Key": "nc-case-submit"},
        )

        after = await mgr_client.get(progress_path(admin.tenant_id))
        after_item = next(
            item for item in after.json()["items"] if item["campaign_id"] == campaign_id
        )
        assert after_item["case_reviewer_completions"] == 1
        assert after_item["case_reviewer_slots_total"] == 4
        # CASE000000000001 is "fully complete" once every reviewer actually assigned to it (here,
        # only reviewer_one -- reviewer_two never claimed anything on it) has submitted the case;
        # CASE000000000002 was never touched by anyone, so it does not count.
        assert after_item["cases_fully_complete_count"] == 1

        cases = await mgr_client.get(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        submitted_case = next(
            item for item in cases.json()["items"] if item["case_id"] == "CASE000000000001"
        )
        # Only reviewer_one ever touched this case; reviewer_two never claimed anything on it.
        assert submitted_case["reviewers_assigned_count"] == 1
        assert submitted_case["reviewers_completed_count"] == 1
        other_case = next(
            item for item in cases.json()["items"] if item["case_id"] != "CASE000000000001"
        )
        assert other_case["reviewers_assigned_count"] == 0
        assert other_case["reviewers_completed_count"] == 0


@pytest.mark.anyio
async def test_slots_use_reviews_per_case_not_roster_size(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """The case-reviewer "slots" denominator is cases * reviews_per_case (the planned assignment
    count), NOT cases * roster size. With 3 selected reviewers but the default reviews_per_case of
    2, each case is reviewed by exactly 2 of the 3 reviewers, so 2 cases yield 4 slots -- not 6."""

    manager = add_review_user(
        database, settings, admin, email="slots-rpc-mgr@example.test", role="campaign_manager"
    )
    campaign_id_uuid = _insert_published_campaign_with_cases(
        database,
        admin.tenant_id,
        admin.user_id,
        key="slots-rpc",
        reviewer_ids=[uuid.uuid4() for _ in range(3)],
        case_ids=["CASE000000000001", "CASE000000000002"],
    )
    campaign_id = str(campaign_id_uuid)
    async with AsyncExitStack() as stack:
        (mgr_client,) = await open_clients(stack, settings, 1)
        await authenticate(mgr_client, manager)
        resp = await mgr_client.get(progress_path(admin.tenant_id))
        item = next(i for i in resp.json()["items"] if i["campaign_id"] == campaign_id)
        assert item["reviewers_total"] == 3
        assert item["cases_total"] == 2
        # cases (2) * reviews_per_case (default 2) == 4, never cases * roster (2 * 3 == 6).
        assert item["case_reviewer_slots_total"] == 4


@pytest.mark.anyio
async def test_campaign_progress_empty_when_no_campaigns(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    manager = add_review_user(
        database,
        settings,
        admin,
        email="progress-empty@example.test",
        role="campaign_manager",
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await authenticate(client, manager)
        r = await client.get(progress_path(admin.tenant_id))

    assert r.status_code == 200
    assert r.json()["items"] == []


# ---------------------------------------------------------------------------
# reviewer-workload happy-path
# ---------------------------------------------------------------------------
