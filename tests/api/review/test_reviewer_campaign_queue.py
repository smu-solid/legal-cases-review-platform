"""Test reviewer campaign queue."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select, text

from review_platform.db.session import Database
from review_platform.review.models import (
    Campaign,
    Candidate,
    EvidenceWindow,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.settings import Settings
from tests.support.campaigns import (
    add_review_user,
    claim_field,
    expire_assignment_lease,
    import_campaign,
)
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


def _insert_roster_only_campaign(
    database: Database, tenant_id: uuid.UUID, created_by: uuid.UUID, *, key: str, reviewer_id: str
) -> None:
    """A published campaign with a curated roster and no review units yet -- enough to test
    campaign-visibility scoping without going through the publish-immutability trigger (which only
    fires on UPDATE/DELETE, not on this direct INSERT)."""

    with database.session() as session, session.begin():
        session.add(
            Campaign(
                tenant_id=tenant_id,
                key=key,
                name="Roster-only campaign",
                status="published",
                policy_json={"selected_reviewer_ids": [reviewer_id]},
                manifest_digest="test-manifest-digest",
                created_by=created_by,
            )
        )


@pytest.mark.anyio
async def test_campaign_queue_restricts_to_curated_roster(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    on_roster = add_review_user(
        database, settings, admin, email="campq-on-roster@example.test", role="reviewer"
    )
    off_roster = add_review_user(
        database, settings, admin, email="campq-off-roster@example.test", role="reviewer"
    )
    _insert_roster_only_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="campq-roster-only",
        reviewer_id=str(on_roster.user_id),
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        on_client, off_client = await open_clients(stack, settings, 2)
        await authenticate(on_client, on_roster)
        await authenticate(off_client, off_roster)

        on_campaigns = await on_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
        assert on_campaigns.status_code == 200
        assert "campq-roster-only" in {
            item["campaign_key"] for item in on_campaigns.json()["campaigns"]
        }

        off_campaigns = await off_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
        assert off_campaigns.status_code == 200
        assert "campq-roster-only" not in {
            item["campaign_key"] for item in off_campaigns.json()["campaigns"]
        }


@pytest.mark.anyio
async def test_campaign_queue_is_keyset_paginated(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="campq-paginate@example.test", role="reviewer"
    )
    for index in range(3):
        _insert_roster_only_campaign(
            database,
            admin.tenant_id,
            admin.user_id,
            key=f"campq-page-{index}",
            reviewer_id=str(reviewer.user_id),
        )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await authenticate(client, reviewer)

        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while True:
            query = "?limit=2" + (f"&cursor={cursor}" if cursor else "")
            page = await client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns{query}")
            assert page.status_code == 200, page.text
            body = page.json()
            assert len(body["campaigns"]) <= 2
            seen.extend(item["campaign_key"] for item in body["campaigns"])
            pages += 1
            if not body["has_more"]:
                assert body["next_cursor"] is None
                break
            assert body["next_cursor"] is not None
            cursor = body["next_cursor"]
            assert pages < 5  # guard against a non-terminating cursor

    # Every roster campaign appears once, across more than one page (limit 2, three campaigns).
    assert pages >= 2
    for index in range(3):
        assert seen.count(f"campq-page-{index}") == 1


@pytest.mark.anyio
async def test_campaign_queue_counts_reflect_reviewer_own_progress(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="campq-counts@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="campq-counts")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        campaigns = await reviewer_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
        assert campaigns.status_code == 200
        before = next(
            item for item in campaigns.json()["campaigns"] if item["campaign_id"] == campaign_id
        )
        assert before["campaign_key"] == "campq-counts"
        assert before["not_started_count"] == 0
        assert before["in_progress_count"] == 0
        assert before["completed_count"] == 0
        assert "case_metadata" in before["selected_group_ids"]
        assert "court_and_hearing" in before["selected_group_ids"]

        await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Citation Neutral", idem="campq-cnt-0001"
        )

        after = await reviewer_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
        after_summary = next(
            item for item in after.json()["campaigns"] if item["campaign_id"] == campaign_id
        )
        assert after_summary["not_started_count"] == 1
        assert after_summary["in_progress_count"] == 0
        assert after_summary["completed_count"] == 0


@pytest.mark.anyio
async def test_campaign_queue_counts_are_case_granular_not_field_granular(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """A case with two claimed fields is one "in_progress" case, not two -- and it only becomes
    "completed" once the reviewer explicitly submits the case, not merely both fields."""

    reviewer = add_review_user(
        database, settings, admin, email="campq-case-granular@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="campq-case-granular")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        before = next(
            item
            for item in (
                await reviewer_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
            ).json()["campaigns"]
            if item["campaign_id"] == campaign_id
        )

        _insert_case_field_unit(
            database,
            admin.tenant_id,
            uuid.UUID(campaign_id),
            case_id="CASE000000000001",
            field_label="Custom Case Field",
            field_value="A synthetic case subject",
            external_item_key="test:campq-case-granular:subject",
        )
        citation_assignment_id = await claim_field(
            reviewer_client,
            csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="campq-cg-claim-citation-0001",
        )
        await claim_field(
            reviewer_client,
            csrf,
            tenant_id,
            campaign_id,
            "Custom Case Field",
            idem="campq-cg-claim-subject-0001",
        )

        after_both_claimed = next(
            item
            for item in (
                await reviewer_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
            ).json()["campaigns"]
            if item["campaign_id"] == campaign_id
        )
        # Two assigned fields of the same case count as one not-started case until the reviewer
        # actually saves or submits an answer; allocation alone is not review progress.
        assert after_both_claimed["in_progress_count"] == before["in_progress_count"]
        assert after_both_claimed["not_started_count"] == before["not_started_count"] + 1
        assert after_both_claimed["completed_count"] == 0

        await _submit_claimed_field(reviewer_client, csrf, tenant_id, citation_assignment_id)

        cases = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        case_item = cases.json()["items"][0]
        assert case_item["fields_submitted"] == 1
        assert case_item["status"] == "in_progress"

        # Find the still-unsubmitted field's own assignment via the flat "assigned" queue.
        assigned = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "assignment_status": "assigned"},
        )
        remaining = next(
            item for item in assigned.json()["items"] if item["case_id"] == "CASE000000000001"
        )
        await _submit_claimed_field(reviewer_client, csrf, tenant_id, remaining["assignment_id"])

        # Both fields submitted, but still not "completed" at the campaign level -- no case-submit
        # confirmation has happened yet.
        after_all_fields_submitted = next(
            item
            for item in (
                await reviewer_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
            ).json()["campaigns"]
            if item["campaign_id"] == campaign_id
        )
        assert after_all_fields_submitted["in_progress_count"] == 1
        assert after_all_fields_submitted["completed_count"] == 0

        await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{citation_assignment_id}/case-submit",
            headers={**mutation_headers(csrf), "Idempotency-Key": "campq-cg-case-submit-0001"},
        )

        after_case_submit = next(
            item
            for item in (
                await reviewer_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
            ).json()["campaigns"]
            if item["campaign_id"] == campaign_id
        )
        assert after_case_submit["in_progress_count"] == 0
        assert after_case_submit["completed_count"] == 1


def _insert_case_field_unit(
    database: Database,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    case_id: str,
    field_label: str,
    field_value: str,
    external_item_key: str,
) -> None:
    """Insert a second field/subject/unit of an already-imported case into a campaign.

    The synthetic v0001 fixture is one field per case (see ``campaign_conflicts`` module
    docstring),     so it alone cannot exercise multi-field-per-case grouping; this mirrors
    what a real multi-field     case import (``real_import._persist_unit``) produces: its
    own snapshot/subject/unit/candidate,     sharing the case's
    ``snapshot_local_case_external_id`` with the fixture-imported field."""

    with database.session() as session, session.begin():
        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        snapshot = SourceSnapshot(
            tenant_id=tenant_id,
            contract_version="test-fixture/v1",
            source_version="test-fixture",
            external_item_key=external_item_key,
            input_digest="test-digest",
        )
        session.add(snapshot)
        session.flush()
        subject = ReviewSubject(
            tenant_id=tenant_id,
            source_snapshot_id=snapshot.id,
            subject_kind="case",
            external_subject_id=f"subject_{external_item_key}",
            display_title=field_value,
            display_subtitle=field_label,
            primary_source_ref=f"source_{external_item_key}",
            attributes_json={"snapshot_local_case_external_id": case_id},
        )
        session.add(subject)
        session.flush()
        unit = ReviewUnit(
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            review_subject_id=subject.id,
            review_kind="metadata_field",
            question=f"Confirm {field_label}",
            safe_field_label=field_label,
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
                value_json=field_value,
                rationale="test fixture",
            )
        )
        session.add(
            EvidenceWindow(
                tenant_id=tenant_id,
                review_unit_id=unit.id,
                ordinal=0,
                kind="quote",
                snippet=field_value,
                source_sha256="0" * 64,
            )
        )


@pytest.mark.anyio
async def test_grouped_bundle_aggregates_multiple_fields_of_the_same_case(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="campq-grouping@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="campq-grouping")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        citation_assignment_id = await claim_field(
            reviewer_client,
            csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="campq-grp-claim-citation-0001",
        )
        # A second field of the *same* case (fixture case CASE000000000001, the citation unit's
        # case) that the synthetic fixture alone does not carry -- exercises real multi-field
        # per-case grouping the same way a real-import case with several fields would.
        _insert_case_field_unit(
            database,
            admin.tenant_id,
            uuid.UUID(campaign_id),
            case_id="CASE000000000001",
            field_label="Custom Case Field",
            field_value="A synthetic case subject",
            external_item_key="test:campq-grouping:subject",
        )
        subject_assignment_id = await claim_field(
            reviewer_client,
            csrf,
            tenant_id,
            campaign_id,
            "Custom Case Field",
            idem="campq-grp-claim-subject-0001",
        )

        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{citation_assignment_id}/grouped-bundle"
        )
        assert grouped.status_code == 200, grouped.text
        body = grouped.json()

        # Both claimed fields of the same case appear together, each in its own allowlisted group.
        item_ids_by_group = {
            group["group_id"]: {item["assignment_id"] for item in group["items"]}
            for group in body["field_groups"]
        }
        assert item_ids_by_group.get("case_metadata") == {citation_assignment_id}
        assert item_ids_by_group.get("additional_fields") == {subject_assignment_id}
        assert body["progress"]["total_items"] == 2

        # Real per-field extracted values, not one shared subject's display title.
        citation_item = next(
            item
            for group in body["field_groups"]
            for item in group["items"]
            if item["assignment_id"] == citation_assignment_id
        )
        subject_item = next(
            item
            for group in body["field_groups"]
            for item in group["items"]
            if item["assignment_id"] == subject_assignment_id
        )
        assert citation_item["extracted_value_display"] != subject_item["extracted_value_display"]
        assert citation_item["extracted_value_raw"] == citation_item["extracted_value_display"]

        # The same case viewed from the other claimed unit's assignment yields the identical group.
        other_view = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{subject_assignment_id}/grouped-bundle"
        )
        assert other_view.json()["progress"]["total_items"] == 2


@pytest.mark.anyio
async def test_case_queue_groups_multiple_claimed_fields_into_one_case(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """Test case queue groups multiple claimed fields into one case."""

    reviewer = add_review_user(
        database, settings, admin, email="casequeue-grouping@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="casequeue-grouping")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        citation_assignment_id = await claim_field(
            reviewer_client,
            csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="casequeue-grp-claim-citation-0001",
        )
        _insert_case_field_unit(
            database,
            admin.tenant_id,
            uuid.UUID(campaign_id),
            case_id="CASE000000000001",
            field_label="Custom Case Field",
            field_value="A synthetic case subject",
            external_item_key="test:casequeue-grouping:subject",
        )
        subject_assignment_id = await claim_field(
            reviewer_client,
            csrf,
            tenant_id,
            campaign_id,
            "Custom Case Field",
            idem="casequeue-grp-claim-subject-0001",
        )

        cases = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        assert cases.status_code == 200, cases.text
        body = cases.json()
        assert body["campaign_id"] == campaign_id
        assert len(body["items"]) == 1
        case_item = body["items"][0]
        assert case_item["case_id"] == "CASE000000000001"
        assert case_item["fields_assigned"] == 2
        assert case_item["fields_submitted"] == 0
        assert case_item["status"] == "not_started"
        assert case_item["neutral_citation_display"] == "[2024] SGCA 1"
        # Opening the case anchors on any one of its assignments -- the grouped bundle re-derives
        # the full case from there.
        assert case_item["anchor_assignment_id"] in {citation_assignment_id, subject_assignment_id}

        opened = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/"
            f"{case_item['anchor_assignment_id']}/grouped-bundle"
        )
        assert opened.status_code == 200
        assert opened.json()["progress"]["total_items"] == 2


@pytest.mark.anyio
async def test_case_queue_status_reflects_submission_progress(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="casequeue-status@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="casequeue-status")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        assignment_id = await claim_field(
            reviewer_client,
            csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="casequeue-status-claim-0001",
        )

        before_submit = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        item = before_submit.json()["items"][0]
        assert item["status"] == "not_started"

        bundle = (
            await reviewer_client.get(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
            )
        ).json()
        lock = bundle["lock_version"]
        await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(csrf),
                "Idempotency-Key": "casequeue-status-submit-0001",
                "If-Match": f'"{lock}"',
            },
        )

        # Every owned field is now submitted, but the case itself is not "completed" until the
        # reviewer explicitly confirms via case-submit -- it must not be derived from field state
        # alone (see CaseSubmission's docstring).
        after_field_submit = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        after_item = after_field_submit.json()["items"][0]
        assert after_item["fields_submitted"] == 1
        assert after_item["status"] == "in_progress"

        case_submit = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/case-submit",
            headers={**mutation_headers(csrf), "Idempotency-Key": "casequeue-status-case-0001"},
        )
        assert case_submit.status_code == 201, case_submit.text

        after_case_submit = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        assert after_case_submit.json()["items"][0]["status"] == "completed"


@pytest.mark.anyio
async def test_case_queue_empty_for_campaign_the_reviewer_cannot_see(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    on_roster = add_review_user(
        database, settings, admin, email="casequeue-off-roster@example.test", role="reviewer"
    )
    other_reviewer = add_review_user(
        database, settings, admin, email="casequeue-owner@example.test", role="reviewer"
    )
    _insert_roster_only_campaign(
        database,
        admin.tenant_id,
        admin.user_id,
        key="casequeue-roster-only",
        reviewer_id=str(other_reviewer.user_id),
    )
    tenant_id = str(admin.tenant_id)
    with database.session() as session:
        campaign_id = str(
            session.scalar(
                select(Campaign.id).where(
                    Campaign.tenant_id == admin.tenant_id, Campaign.key == "casequeue-roster-only"
                )
            )
        )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await authenticate(client, on_roster)
        cases = await client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        assert cases.status_code == 200
        assert cases.json()["items"] == []


@pytest.mark.anyio
async def test_flat_queue_items_carry_the_same_case_id_for_the_same_case(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """Test flat queue items carry the same case id for the same case."""

    reviewer = add_review_user(
        database, settings, admin, email="casequeue-flat-case-id@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="casequeue-flat-case-id")
        campaign_id = str(imported["campaign_id"])
        _insert_case_field_unit(
            database,
            admin.tenant_id,
            uuid.UUID(campaign_id),
            case_id="CASE000000000001",
            field_label="Custom Case Field",
            field_value="A synthetic case subject",
            external_item_key="test:casequeue-flat-case-id:subject",
        )
        await authenticate(reviewer_client, reviewer)

        queue = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/queue",
            params={"campaign_id": campaign_id, "assignment_status": "available"},
        )
        assert queue.status_code == 200, queue.text
        items_by_label = {item["safe_field_label"]: item for item in queue.json()["items"]}
        # The synthetic fixture's own citation field and the second field just inserted above both
        # belong to fixture case CASE000000000001 -- same case_id, distinct review_unit_id.
        assert items_by_label["Citation Neutral"]["case_id"] == "CASE000000000001"
        assert items_by_label["Custom Case Field"]["case_id"] == "CASE000000000001"
        assert (
            items_by_label["Citation Neutral"]["review_unit_id"]
            != items_by_label["Custom Case Field"]["review_unit_id"]
        )


async def _submit_claimed_field(
    client, csrf_token: str, tenant_id: str, assignment_id: str
) -> None:
    bundle = await client.get(
        f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
    )
    assert bundle.status_code == 200, bundle.text
    lock_version = bundle.json()["lock_version"]
    submit = await client.post(
        f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/submit",
        json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
        headers={
            **mutation_headers(csrf_token),
            "Idempotency-Key": f"submit-{assignment_id}",
            "If-Match": f'"{lock_version}"',
        },
    )
    assert submit.status_code == 201, submit.text


@pytest.mark.anyio
async def test_answer_endpoints_self_heal_an_expired_lease(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """The grouped workspace's draft/submit recover a lapsed lease while the slot is untaken."""

    reviewer = add_review_user(
        database, settings, admin, email="lease-heal-answers@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="lease-heal-answers")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        assignment_id = await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Citation Neutral", idem="lh-claim-0001"
        )
        bundle = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        lock_version = bundle.json()["lock_version"]
        answer = {"value_correct": True, "provenance_correct": True, "evidence_ids": []}

        expire_assignment_lease(database, admin.tenant_id, assignment_id)
        drafted = await reviewer_client.put(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/draft",
            json=answer,
            headers={
                **mutation_headers(csrf),
                "Idempotency-Key": "lh-draft-0001",
                "If-Match": f'"{lock_version}"',
            },
        )
        assert drafted.status_code == 200, drafted.text

        expire_assignment_lease(database, admin.tenant_id, assignment_id)
        submitted = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/submit",
            json=answer,
            headers={
                **mutation_headers(csrf),
                "Idempotency-Key": "lh-submit-0001",
                "If-Match": f'"{drafted.json()["lock_version"]}"',
            },
        )
        assert submitted.status_code == 201, submitted.text


@pytest.mark.anyio
async def test_case_submit_succeeds_once_every_owned_field_is_submitted(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="casesubmit-happy@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="casesubmit-happy")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        assignment_id = await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Citation Neutral", idem="cs-claim-0001"
        )
        await _submit_claimed_field(reviewer_client, csrf, tenant_id, assignment_id)

        case_submit = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/case-submit",
            headers={**mutation_headers(csrf), "Idempotency-Key": "cs-submit-0001"},
        )
        assert case_submit.status_code == 201, case_submit.text
        body = case_submit.json()
        assert body["case_id"] == "CASE000000000001"
        assert body["campaign_id"] == campaign_id
        assert body["replayed"] is False

        cases = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        assert cases.json()["items"][0]["status"] == "completed"

        # Resubmitting the same case is a no-op replay, not a new row/error.
        replay = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/case-submit",
            headers={**mutation_headers(csrf), "Idempotency-Key": "cs-submit-0002"},
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["replayed"] is True
        assert replay.json()["submitted_at"] == body["submitted_at"]


@pytest.mark.anyio
async def test_case_submit_rejects_when_a_field_is_still_unanswered(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="casesubmit-incomplete@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="casesubmit-incomplete")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        _insert_case_field_unit(
            database,
            admin.tenant_id,
            uuid.UUID(campaign_id),
            case_id="CASE000000000001",
            field_label="Custom Case Field",
            field_value="A synthetic case subject",
            external_item_key="test:casesubmit-incomplete:subject",
        )
        assignment_id = await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Citation Neutral", idem="cs-claim-0002"
        )
        await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Custom Case Field", idem="cs-claim-0003"
        )
        # Only the citation field is submitted; the second field is still unanswered.
        await _submit_claimed_field(reviewer_client, csrf, tenant_id, assignment_id)

        case_submit = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/case-submit",
            headers={**mutation_headers(csrf), "Idempotency-Key": "cs-submit-0003"},
        )
        assert case_submit.status_code == 422, case_submit.text
        assert case_submit.json()["code"] == "case_not_fully_submitted"
