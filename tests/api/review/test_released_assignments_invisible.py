"""A released assignment is history: the reviewer must never see it, and it must never block them.

Three reviewer-facing paths were reading those rows -- the campaign counts, the case queue, and
the grouped bundle -- and ``case-submit`` was demanding that they be ``submitted`` before it would
record the case, which no reviewer can ever make happen. Field submit on such a row answers
``409 released_assignment``; before that code existed it answered ``assignment_not_editable``,
which the workspace reads as "already submitted" and paints the field green."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import text

from review_platform.db.session import Database
from review_platform.review.models import ReviewUnit
from review_platform.settings import Settings
from tests.support.campaigns import (
    add_review_user,
    claim_field,
    import_campaign,
    release_assignment,
)
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


def _insert_second_field_on_same_case(
    database: Database,
    tenant_id: uuid.UUID,
    campaign_id: uuid.UUID,
    *,
    anchor_assignment_id: str,
    field_label: str,
) -> None:
    """Add one more review unit to the case an existing assignment already belongs to."""

    with database.session() as session, session.begin():
        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        subject_id = session.execute(
            text(
                "SELECT ru.review_subject_id FROM review_platform.assignments a "
                "JOIN review_platform.review_units ru ON ru.id = a.review_unit_id "
                "WHERE a.id = :assignment_id"
            ),
            {"assignment_id": anchor_assignment_id},
        ).scalar_one()
        session.add(
            ReviewUnit(
                tenant_id=tenant_id,
                campaign_id=campaign_id,
                review_subject_id=subject_id,
                review_kind="metadata_field",
                question=f"Confirm {field_label}",
                safe_field_label=field_label,
                input_digest="test-digest",
            )
        )


async def _claim_two_distinct_cases(client, csrf_token: str, tenant_id: str, campaign_id: str):
    """Claim one review unit from each of two different cases, returning both assignment ids."""

    queue = await client.get(
        f"/api/v1/tenants/{tenant_id}/review/queue", params={"campaign_id": campaign_id}
    )
    assert queue.status_code == 200, queue.text
    unit_ids = [item["review_unit_id"] for item in queue.json()["items"]][:2]
    assert len(unit_ids) == 2
    assignment_ids = []
    for index, unit_id in enumerate(unit_ids):
        claim = await client.post(
            f"/api/v1/tenants/{tenant_id}/review/claim",
            json={"review_unit_id": unit_id},
            headers={
                **mutation_headers(csrf_token),
                "Idempotency-Key": f"released-distinct-claim-{index}-0001",
            },
        )
        assert claim.status_code == 201, claim.text
        assignment_ids.append(str(claim.json()["assignment_id"]))
    return assignment_ids[0], assignment_ids[1]


@pytest.mark.anyio
async def test_a_case_left_with_only_released_rows_disappears_from_the_reviewer(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """The five phantom cases: every row on them was moved away, so the case is not the
    reviewer's work at all and must not be counted, listed, or openable."""

    reviewer = add_review_user(
        database, settings, admin, email="released-phantom@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="released-phantom")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        kept, moved_away = await _claim_two_distinct_cases(
            reviewer_client, csrf, tenant_id, campaign_id
        )
        release_assignment(database, admin.tenant_id, moved_away)

        campaigns = await reviewer_client.get(f"/api/v1/tenants/{tenant_id}/review/campaigns")
        summary = next(
            item for item in campaigns.json()["campaigns"] if item["campaign_id"] == campaign_id
        )
        counted = (
            summary["not_started_count"] + summary["in_progress_count"] + summary["completed_count"]
        )
        assert counted == 1, summary

        cases = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/campaigns/{campaign_id}/cases"
        )
        assert [item["anchor_assignment_id"] for item in cases.json()["items"]] == [kept]

        opened = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{moved_away}/grouped-bundle"
        )
        assert opened.status_code == 404, opened.text

        submit = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{moved_away}/case-submit",
            headers={**mutation_headers(csrf), "Idempotency-Key": "rel-phantom-case-0001"},
        )
        assert submit.status_code == 404, submit.text


@pytest.mark.anyio
async def test_a_released_field_does_not_block_submitting_the_rest_of_its_case(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """The 422 loop: one field of a case moved away, the reviewer submitted every field she still
    holds, and ``case-submit`` refused forever because the moved row is not ``submitted``."""

    reviewer = add_review_user(
        database, settings, admin, email="released-blocker@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="released-blocker")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        kept = await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Citation Neutral", idem="blk-keep-0001"
        )
        _insert_second_field_on_same_case(
            database,
            admin.tenant_id,
            uuid.UUID(campaign_id),
            anchor_assignment_id=kept,
            field_label="Moved Away Field",
        )
        moved_away = await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Moved Away Field", idem="blk-move-0001"
        )
        release_assignment(database, admin.tenant_id, moved_away)

        bundle = (
            await reviewer_client.get(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{kept}/grouped-bundle"
            )
        ).json()
        # The moved-away field is gone from the workspace, so the reviewer is never asked for it.
        assert bundle["progress"]["total_items"] == 1
        assert all(
            item["assignment_id"] != moved_away
            for group in bundle["field_groups"]
            for item in group["items"]
        )

        answer = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{kept}/answer/submit",
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(csrf),
                "Idempotency-Key": "blk-answer-0001",
                "If-Match": f'"{bundle["lock_version"]}"',
            },
        )
        assert answer.status_code == 201, answer.text

        case_submit = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{kept}/case-submit",
            headers={**mutation_headers(csrf), "Idempotency-Key": "blk-case-0001"},
        )
        assert case_submit.status_code == 201, case_submit.text


@pytest.mark.anyio
async def test_writing_to_a_released_assignment_says_so_instead_of_looking_submitted(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """``assignment_not_editable`` is the workspace's "already submitted" signal, so a released
    row answering with it made a field the reviewer never touched render as done."""

    reviewer = add_review_user(
        database, settings, admin, email="released-code@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="released-code")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        assignment_id = await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Citation Neutral", idem="code-0001"
        )
        bundle = (
            await reviewer_client.get(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
            )
        ).json()
        release_assignment(database, admin.tenant_id, assignment_id)

        for path, payload in (
            ("answer/submit", {"value_correct": True, "provenance_correct": True}),
            ("answer/draft", {"value_correct": True, "provenance_correct": True}),
        ):
            method = reviewer_client.post if path.endswith("submit") else reviewer_client.put
            response = await method(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/{path}",
                json={**payload, "evidence_ids": []},
                headers={
                    **mutation_headers(csrf),
                    "Idempotency-Key": f"code-{path.replace('/', '-')}-0001",
                    "If-Match": f'"{bundle["lock_version"]}"',
                },
            )
            assert response.status_code == 409, response.text
            assert response.json()["code"] == "released_assignment", response.text


@pytest.mark.anyio
async def test_a_released_unit_can_be_claimed_again_while_its_slot_is_free(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """Release used to be terminal: the reviewer's own released row refused the re-claim and hid
    the unit from her pool, so work moved away from her could never come back even when nobody
    else took it."""

    reviewer = add_review_user(
        database, settings, admin, email="released-reclaim@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin, key="released-reclaim")
        campaign_id = str(imported["campaign_id"])
        csrf = await authenticate(reviewer_client, reviewer)

        assignment_id = await claim_field(
            reviewer_client, csrf, tenant_id, campaign_id, "Citation Neutral", idem="reclaim-0001"
        )
        unit_id = (
            await reviewer_client.get(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
            )
        ).json()["field_groups"][0]["items"][0]["review_unit_id"]
        release_assignment(database, admin.tenant_id, assignment_id)

        reclaim = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/claim",
            json={"review_unit_id": unit_id},
            headers={**mutation_headers(csrf), "Idempotency-Key": "reclaim-0002"},
        )
        assert reclaim.status_code == 201, reclaim.text
        # Reused in place -- the schema allows only one row per (unit, reviewer).
        assert str(reclaim.json()["assignment_id"]) == assignment_id

        reopened = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        assert reopened.status_code == 200, reopened.text
