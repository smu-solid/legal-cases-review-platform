"""Grouped value/provenance adjudication bundle API."""

from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select, text

from review_platform.db.models import AuditEvent, User
from review_platform.db.session import Database
from review_platform.review.models import (
    Adjudication,
    AdjudicationDecision,
    AdjudicationDraft,
    AdjudicationParticipation,
    Candidate,
    EvidenceWindow,
    ReviewUnit,
)
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, claim_field, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity

BLINDED_TOKENS = (
    "reviewer_id",
    "rationale",
    "supporting_quote",
    "verdict",
    "candidate",
    "model_kind",
    "model_name",
    "prompt_version",
    "suggested_value",
)


@pytest.mark.anyio
async def test_grouped_adjudication_bundle_identifies_reviewers_to_adjudicators_and_stays_blinded(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer_one = add_review_user(
        database, settings, admin, email="group-adj-reviewer-one@example.test", role="reviewer"
    )
    reviewer_two = add_review_user(
        database, settings, admin, email="group-adj-reviewer-two@example.test", role="reviewer"
    )
    reviewer_three = add_review_user(
        database, settings, admin, email="group-adj-reviewer-three@example.test", role="reviewer"
    )
    adjudicator = add_review_user(
        database, settings, admin, email="group-adj@example.test", role="adjudicator"
    )
    other_adjudicator = add_review_user(
        database, settings, admin, email="group-adj-other@example.test", role="adjudicator"
    )
    tenant_id = str(admin.tenant_id)

    async with AsyncExitStack() as stack:
        clients = await open_clients(stack, settings, 6)
        (
            admin_client,
            first_client,
            second_client,
            third_client,
            adjudicator_client,
            other_client,
        ) = clients
        imported = await import_campaign(
            admin_client, admin, key="grouped-adjudication", reviews_per_case=3
        )
        campaign_id = str(imported["campaign_id"])
        with database.session() as session, session.begin():
            anchor_unit = session.scalar(
                select(ReviewUnit).where(
                    ReviewUnit.tenant_id == admin.tenant_id,
                    ReviewUnit.campaign_id == imported["campaign_id"],
                    ReviewUnit.safe_field_label == "Citation Neutral",
                )
            )
            assert anchor_unit is not None
            reported_unit = ReviewUnit(
                tenant_id=admin.tenant_id,
                campaign_id=anchor_unit.campaign_id,
                review_subject_id=anchor_unit.review_subject_id,
                review_kind="metadata_field",
                question="Confirm Reported Citation",
                safe_field_label="Reported Citation",
                field_name="cases.citation_reported",
                required_reviews=3,
                input_digest="2" * 64,
            )
            session.add(reported_unit)
            session.flush()
            for label, value in (("A", "[2024] 1 rep 1"), ("B", "[2024] 1 rep 2")):
                session.add(
                    Candidate(
                        tenant_id=admin.tenant_id,
                        review_unit_id=reported_unit.id,
                        label=label,
                        source_kind="deterministic" if label == "A" else "model",
                        verdict="supported",
                        value_json=value,
                        rationale="must remain blinded",
                    )
                )
            session.add(
                EvidenceWindow(
                    tenant_id=admin.tenant_id,
                    review_unit_id=reported_unit.id,
                    ordinal=0,
                    kind="paragraph",
                    snippet="Reported citation: [2024] 1 rep 1",
                    source_sha256="2" * 64,
                )
            )
        first_csrf = await authenticate(first_client, reviewer_one)
        second_csrf = await authenticate(second_client, reviewer_two)
        third_csrf = await authenticate(third_client, reviewer_three)
        adjudicator_csrf = await authenticate(adjudicator_client, adjudicator)
        other_csrf = await authenticate(other_client, other_adjudicator)

        first_assignment = await claim_field(
            first_client,
            first_csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="group-adj-claim-one",
        )
        second_assignment = await claim_field(
            second_client,
            second_csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="group-adj-claim-two",
        )
        third_assignment = await claim_field(
            third_client,
            third_csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="group-adj-claim-three",
        )
        reported_assignments = [
            await claim_field(
                client,
                csrf,
                tenant_id,
                campaign_id,
                "Reported Citation",
                idem=f"group-adj-reported-claim-{index}",
            )
            for index, (client, csrf) in enumerate(
                (
                    (first_client, first_csrf),
                    (second_client, second_csrf),
                    (third_client, third_csrf),
                ),
                start=1,
            )
        ]
        # This unit is inserted after the campaign allocation snapshot and uses a distinct token
        # while being claimed. Canonicalize its display metadata afterward so the queue projection
        # exercises the same reported-citation token used by real imports.
        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            reported_unit = session.scalar(
                select(ReviewUnit).where(
                    ReviewUnit.tenant_id == admin.tenant_id,
                    ReviewUnit.id == reported_unit.id,
                )
            )
            assert reported_unit is not None
            reported_unit.field_name = "cases.citation_reporter"

        async def submit_answer(
            client,
            csrf_token: str,
            assignment_id: str,
            *,
            idem: str,
            value_correct: bool,
            provenance_correct: bool,
            corrected_value_display: str | None = None,
            comment: str | None = None,
        ):
            grouped = await client.get(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
            )
            assert grouped.status_code == 200, grouped.text
            body = grouped.json()
            item = next(
                item
                for group in body["field_groups"]
                for item in group["items"]
                if item["assignment_id"] == assignment_id
            )
            payload = {
                "value_correct": value_correct,
                "provenance_correct": provenance_correct,
                "evidence_ids": item["evidence_window_ids"][:1],
            }
            if corrected_value_display is not None:
                payload["corrected_value_display"] = corrected_value_display
            if comment is not None:
                payload["comment"] = comment
            return await client.post(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/submit",
                json=payload,
                headers={
                    **mutation_headers(csrf_token),
                    "Idempotency-Key": idem,
                    "If-Match": f'"{body["lock_version"]}"',
                },
            )

        first_submit = await submit_answer(
            first_client,
            first_csrf,
            first_assignment,
            idem="group-adj-submit-one",
            value_correct=True,
            provenance_correct=True,
        )
        assert first_submit.status_code == 201, first_submit.text
        awaiting_queue = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications"
        )
        assert awaiting_queue.status_code == 200
        awaiting_case = awaiting_queue.json()[0]
        assert awaiting_case["ready_for_me_count"] == 0
        assert awaiting_case["awaiting_reviews_count"] == 1
        citation_progress = next(
            field
            for field in awaiting_case["field_progress"]
            if field["item_label"] == "Citation Neutral"
        )
        assert citation_progress == {
            "review_unit_id": citation_progress["review_unit_id"],
            "item_label": "Citation Neutral",
            "submitted_reviews": 1,
            "required_reviews": 3,
            "state": "awaiting_reviews",
        }
        assert "submissions" not in awaiting_queue.text
        campaign_queue = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudication-campaigns"
        )
        assert campaign_queue.status_code == 200, campaign_queue.text
        campaign_summary = next(
            entry
            for entry in campaign_queue.json()["campaigns"]
            if entry["campaign_id"] == campaign_id
        )
        assert campaign_summary["waiting_count"] >= 1
        case_queue = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudication-campaigns/"
            f"{campaign_id}/cases?status=waiting"
        )
        waiting_projection = next(
            entry
            for entry in case_queue.json()["items"]
            if entry["case_id"] == awaiting_case["case_id"]
        )
        assert waiting_projection["neutral_citation_display"] == "[2024] SGCA 1"
        assert waiting_projection["reported_citation_display"] == "[2024] 1 rep 1"
        assert waiting_projection["status_reason_code"] == "awaiting_future_participation"
        assert waiting_projection["progress"]["future_eligible_fields"] >= 1
        waiting_field = next(
            field
            for field in waiting_projection["field_progress"]
            if field["item_label"] == "Citation Neutral"
        )
        assert waiting_field["submitted_reviews"] == 1
        assert waiting_field["required_reviews"] == 3
        assert waiting_field["state"] == "awaiting_reviews"
        assert {
            (reviewer["display_name"], reviewer["email"])
            for reviewer in waiting_field["pending_reviewers"]
        } == {
            ("group-adj-reviewer-two", "group-adj-reviewer-two@example.test"),
            ("group-adj-reviewer-three", "group-adj-reviewer-three@example.test"),
        }
        assert (
            waiting_projection["progress"]["completed_responsibility_fields"]
            <= waiting_projection["progress"]["personal_responsibility_fields"]
        )
        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            assert (
                session.scalar(
                    select(Adjudication)
                    .join(ReviewUnit, ReviewUnit.id == Adjudication.review_unit_id)
                    .where(ReviewUnit.safe_field_label == "Citation Neutral")
                )
                is None
            )
        second_submit = await submit_answer(
            second_client,
            second_csrf,
            second_assignment,
            idem="group-adj-submit-two",
            value_correct=False,
            provenance_correct=False,
            corrected_value_display="[2024] SGCA 2",
            comment="The neutral citation should be corrected.",
        )
        assert second_submit.status_code == 201, second_submit.text

        # required_reviews is dynamic: two submissions are not enough for this 3-review campaign.
        not_ready = await adjudicator_client.post(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/claim",
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "group-adj-too-early",
            },
        )
        assert not_ready.status_code == 409, not_ready.text

        third_submit = await submit_answer(
            third_client,
            third_csrf,
            third_assignment,
            idem="group-adj-submit-three",
            value_correct=True,
            provenance_correct=False,
            comment="The value is right but the highlighted provenance is not.",
        )
        assert third_submit.status_code == 201, third_submit.text

        for index, (client, csrf, assignment_id) in enumerate(
            zip(
                (first_client, second_client, third_client),
                (first_csrf, second_csrf, third_csrf),
                reported_assignments,
                strict=True,
            ),
            start=1,
        ):
            submitted = await submit_answer(
                client,
                csrf,
                assignment_id,
                idem=f"group-adj-reported-submit-{index}",
                value_correct=True,
                provenance_correct=True,
            )
            assert submitted.status_code == 201, submitted.text

        claim = await adjudicator_client.post(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/claim",
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "group-adj-claim-adjudication",
            },
        )
        assert claim.status_code == 201, claim.text
        assert claim.json()["claimed_item_count"] == 2
        adjudication_id = claim.json()["adjudication_id"]

        queue = await adjudicator_client.get(f"/api/v1/tenants/{tenant_id}/review/adjudications")
        assert queue.status_code == 200, queue.text
        assert len(queue.json()) == 1
        assert queue.json()[0]["item_count"] == 2

        personalized_cases = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudication-campaigns/"
            f"{campaign_id}/cases?status=in_progress"
        )
        assert personalized_cases.status_code == 200, personalized_cases.text
        open_case = next(
            entry
            for entry in personalized_cases.json()["items"]
            if entry["case_id"] == queue.json()[0]["case_id"]
        )
        assert open_case["workspace_adjudication_id"] == adjudication_id
        assert open_case["progress"]["pending_fields"] == 2
        assert {field["state"] for field in open_case["field_progress"]} == {
            "ready_for_adjudication"
        }

        # An adjudicator added after the participation snapshot has no responsibility for these
        # already-created units. That case is Not required, never Waiting or Finished.
        late_adjudicator = add_review_user(
            database,
            settings,
            admin,
            email="group-adj-late@example.test",
            role="adjudicator",
        )
        (late_client,) = await open_clients(stack, settings, 1)
        await authenticate(late_client, late_adjudicator)
        late_cases = await late_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudication-campaigns/"
            f"{campaign_id}/cases?status=not_required"
        )
        assert late_cases.status_code == 200, late_cases.text
        late_case = next(
            entry
            for entry in late_cases.json()["items"]
            if entry["case_id"] == queue.json()[0]["case_id"]
        )
        assert late_case["completion_kind"] == "not_required"
        assert late_case["status"] == "not_required"
        assert late_case["progress"]["personal_responsibility_fields"] == 0
        assert late_case["progress"]["completed_responsibility_fields"] == 0
        assert late_case["workspace_adjudication_id"] is None
        assert {field["state"] for field in late_case["field_progress"]} == {"not_assigned_to_me"}
        late_campaigns = await late_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudication-campaigns"
        )
        assert late_campaigns.status_code == 200, late_campaigns.text
        late_summary = next(
            entry
            for entry in late_campaigns.json()["campaigns"]
            if entry["campaign_id"] == campaign_id
        )
        assert late_summary["finished_count"] == 0
        assert late_summary["not_required_count"] >= 1

        workspace = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/case-workspace"
        )
        assert workspace.status_code == 200, workspace.text
        assert workspace.json()["mode"] == "edit"
        assert (
            len(
                [
                    entry
                    for field_group in workspace.json()["field_groups"]
                    for entry in field_group["items"]
                ]
            )
            == 2
        )

        grouped = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/grouped-bundle"
        )
        assert grouped.status_code == 200, grouped.text
        body = grouped.json()
        assert body["schema_version"] == "adjudication-grouped-bundle/v2"
        assert body["review_subject"]["subject_kind"] == "case"
        group = body["field_groups"][0]
        assert group["group_id"] == "case_metadata"
        grouped_items = [
            entry for field_group in body["field_groups"] for entry in field_group["items"]
        ]
        assert len(grouped_items) == 2
        item = next(entry for entry in grouped_items if entry["item_kind"] == "citation")
        assert item["item_kind"] == "citation"
        assert [submission["pseudonym"] for submission in item["submissions"]] == [
            "Reviewer 1",
            "Reviewer 2",
            "Reviewer 3",
        ]
        assert [submission["reviewer"] for submission in item["submissions"]] == [
            {
                "display_name": "group-adj-reviewer-one",
                "email": "group-adj-reviewer-one@example.test",
            },
            {
                "display_name": "group-adj-reviewer-two",
                "email": "group-adj-reviewer-two@example.test",
            },
            {
                "display_name": "group-adj-reviewer-three",
                "email": "group-adj-reviewer-three@example.test",
            },
        ]
        assert item["submitted_reviews"] == item["required_reviews"] == 3
        assert item["submissions"][0]["value_correct"] is True
        assert item["submissions"][1]["value_correct"] is False
        assert item["submissions"][1]["corrected_value_display"] == "[2024] SGCA 2"
        assert len({submission["submission_id"] for submission in item["submissions"]}) == 3

        raw = grouped.text
        lowered = raw.lower()
        for token in BLINDED_TOKENS:
            assert token not in lowered, token
        for identity in (reviewer_one, reviewer_two, reviewer_three):
            assert identity.email in raw
            assert str(identity.user_id) not in raw

        legacy = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/bundle"
        )
        assert legacy.status_code == 200
        assert legacy.json()["submissions"] == []

        note_only_payload = {"comment": "Private note before selecting a verdict"}
        draft_url = (
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{item['adjudication_id']}/draft"
        )
        note_headers = {
            **mutation_headers(adjudicator_csrf),
            "Idempotency-Key": "group-adj-note-before-verdict",
        }
        note_only = await adjudicator_client.put(
            draft_url, json=note_only_payload, headers=note_headers
        )
        assert note_only.status_code == 200, note_only.text
        assert note_only.json()["decision"]["outcome"] is None
        assert note_only.json()["decision"]["comment"] == note_only_payload["comment"]
        assert note_only.json()["decision"]["reviewer_assessments"] == []
        assert note_only.json()["replayed"] is False

        replay = await adjudicator_client.put(
            draft_url, json=note_only_payload, headers=note_headers
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["replayed"] is True
        assert replay.json()["decision"] == note_only.json()["decision"]
        conflict = await adjudicator_client.put(
            draft_url, json={"comment": "Changed note"}, headers=note_headers
        )
        assert conflict.status_code == 409, conflict.text
        assert conflict.json()["code"] == "idempotency_conflict"

        for reader, expected_note in (
            (adjudicator_client, note_only_payload["comment"]),
            (other_client, None),
        ):
            for view in ("grouped-bundle", "case-workspace"):
                reloaded = await reader.get(
                    f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/{view}"
                )
                assert reloaded.status_code == 200, reloaded.text
                reloaded_item = next(
                    entry
                    for group in reloaded.json()["field_groups"]
                    for entry in group["items"]
                    if entry["adjudication_id"] == item["adjudication_id"]
                )
                if expected_note is None:
                    assert reloaded_item["draft"] is None
                    assert note_only_payload["comment"] not in reloaded.text
                else:
                    assert reloaded_item["draft"]["decision"]["comment"] == expected_note
                    assert reloaded_item["draft"]["decision"]["outcome"] is None

        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            persisted_note = session.scalar(
                select(AdjudicationDraft).where(
                    AdjudicationDraft.saved_by == adjudicator.user_id,
                    AdjudicationDraft.adjudication_id == item["adjudication_id"],
                )
            )
            assert persisted_note is not None
            assert persisted_note.decision_json["outcome"] is None
            assert persisted_note.decision_json["comment"] == note_only_payload["comment"]

        for index, payload in enumerate(
            (note_only_payload, {**note_only_payload, "outcome": None})
        ):
            invalid_final = await adjudicator_client.post(
                draft_url.removesuffix("draft") + "submit",
                json=payload,
                headers={
                    **mutation_headers(adjudicator_csrf),
                    "Idempotency-Key": f"group-adj-no-final-verdict-{index}",
                },
            )
            assert invalid_final.status_code == 422, invalid_final.text

        null_outcome = await adjudicator_client.put(
            draft_url,
            json={**note_only_payload, "outcome": None},
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "group-adj-explicit-null-draft",
            },
        )
        assert null_outcome.status_code == 200, null_outcome.text
        assert null_outcome.json()["decision"]["outcome"] is None

        draft_payload = {
            "outcome": "reviewer_preferred",
            "preferred_submission_id": item["submissions"][0]["submission_id"],
            "assessments": [],
            "reviewer_assessments": [
                {
                    "submission_id": submission["submission_id"],
                    "assessment": "correct" if index == 0 else "incorrect",
                }
                for index, submission in enumerate(item["submissions"])
            ],
            "comment": "Work in progress",
            "evidence_ids": item["evidence_window_ids"],
        }
        saved_draft = await adjudicator_client.put(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{item['adjudication_id']}/draft",
            json=draft_payload,
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "group-adj-save-draft",
            },
        )
        assert saved_draft.status_code == 200, saved_draft.text
        assert saved_draft.json()["decision"]["comment"] == "Work in progress"

        with_draft = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/grouped-bundle"
        )
        drafted_item = next(
            entry
            for field_group in with_draft.json()["field_groups"]
            for entry in field_group["items"]
            if entry["adjudication_id"] == item["adjudication_id"]
        )
        assert drafted_item["draft"]["decision"]["outcome"] == "reviewer_preferred"

        other_draft_payload = {**draft_payload, "comment": "Other private draft"}
        independent_draft = await other_client.put(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{item['adjudication_id']}/draft",
            json=other_draft_payload,
            headers={
                **mutation_headers(other_csrf),
                "Idempotency-Key": "group-adj-independent-draft",
            },
        )
        assert independent_draft.status_code == 200, independent_draft.text
        other_bundle = await other_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/grouped-bundle"
        )
        other_item = next(
            entry
            for field_group in other_bundle.json()["field_groups"]
            for entry in field_group["items"]
            if entry["adjudication_id"] == item["adjudication_id"]
        )
        assert other_item["draft"]["decision"]["comment"] == "Other private draft"
        first_workspace, second_workspace = await asyncio.gather(
            adjudicator_client.get(
                f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/case-workspace"
            ),
            other_client.get(
                f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/case-workspace"
            ),
        )
        first_workspace_item = next(
            entry
            for group in first_workspace.json()["field_groups"]
            for entry in group["items"]
            if entry["adjudication_id"] == item["adjudication_id"]
        )
        second_workspace_item = next(
            entry
            for group in second_workspace.json()["field_groups"]
            for entry in group["items"]
            if entry["adjudication_id"] == item["adjudication_id"]
        )
        assert first_workspace_item["draft"]["decision"]["comment"] == "Work in progress"
        assert second_workspace_item["draft"]["decision"]["comment"] == "Other private draft"

        source_length = len(first_workspace.json()["source_render"]["content"])
        invalid_span = await adjudicator_client.put(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{item['adjudication_id']}/draft",
            json={
                **draft_payload,
                "outcome": "all_wrong",
                "preferred_submission_id": None,
                "reviewer_assessments": [
                    {
                        "submission_id": submission["submission_id"],
                        "assessment": "incorrect",
                    }
                    for submission in item["submissions"]
                ],
                "corrected_provenance_spans": [
                    {
                        "evidence_window_id": item["evidence_window_ids"][0],
                        "char_start": 0,
                        "char_end": source_length + 1,
                    }
                ],
            },
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "group-adj-invalid-provenance-bounds",
            },
        )
        assert invalid_span.status_code == 422
        assert invalid_span.json()["code"] == "corrected_provenance_spans_invalid"

        final_payload = {
            "outcome": "reviewer_preferred",
            "preferred_submission_id": item["submissions"][0]["submission_id"],
            "assessments": [],
            "reviewer_assessments": [
                {
                    "submission_id": submission["submission_id"],
                    "assessment": "correct" if index == 0 else "incorrect",
                }
                for index, submission in enumerate(item["submissions"])
            ],
            "evidence_ids": item["evidence_window_ids"],
        }

        async def submit_duplicate() -> object:
            return await adjudicator_client.post(
                f"/api/v1/tenants/{tenant_id}/review/adjudications/"
                f"{item['adjudication_id']}/submit",
                json=final_payload,
                headers={
                    **mutation_headers(adjudicator_csrf),
                    "Idempotency-Key": "group-adj-dynamic-verdict",
                },
            )

        duplicate_wave = await asyncio.gather(submit_duplicate(), submit_duplicate())
        assert [response.status_code for response in duplicate_wave] == [201, 201]
        assert len({response.json()["decision_id"] for response in duplicate_wave}) == 1
        assert sorted(response.json()["replayed"] for response in duplicate_wave) == [False, True]
        decision = next(response for response in duplicate_wave if not response.json()["replayed"])
        assert decision.status_code == 201, decision.text
        assert decision.json()["status"] == "submitted"
        assert decision.json()["assessments"] == []
        assert len(decision.json()["reviewer_assessments"]) == 3
        assert decision.json()["preferred_submission_id"] == item["submissions"][0]["submission_id"]
        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            drafts = list(session.scalars(select(AdjudicationDraft)))
            assert len(drafts) == 1
            assert drafts[0].saved_by == other_adjudicator.user_id

            shared = session.scalar(
                select(Adjudication).where(Adjudication.id == item["adjudication_id"])
            )
            assert shared is not None and shared.status == "pending"

        first_queue = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications"
        )
        assert first_queue.status_code == 200
        first_case = first_queue.json()[0]
        assert first_case["ready_for_me_count"] == 1

        first_workspace_after_submit = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/case-workspace"
        )
        assert first_workspace_after_submit.status_code == 200
        workspace_items_after_submit = [
            entry
            for field_group in first_workspace_after_submit.json()["field_groups"]
            for entry in field_group["items"]
        ]
        assert len(workspace_items_after_submit) == 2
        submitted_workspace_item = next(
            entry
            for entry in workspace_items_after_submit
            if entry["adjudication_id"] == item["adjudication_id"]
        )
        assert submitted_workspace_item["participation_status"] == "submitted"
        assert (
            submitted_workspace_item["submitted_decision"]["decision_id"]
            == decision.json()["decision_id"]
        )
        assert (
            sum(
                entry["participation_status"] == "pending" for entry in workspace_items_after_submit
            )
            == 1
        )

        other_after_first = await other_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/grouped-bundle"
        )
        assert other_after_first.status_code == 200
        other_ready_item = next(
            entry
            for field_group in other_after_first.json()["field_groups"]
            for entry in field_group["items"]
            if entry["adjudication_id"] == item["adjudication_id"]
        )
        marked_span = {
            "evidence_window_id": item["evidence_window_ids"][0],
            "char_start": 0,
            "char_end": min(10, source_length),
            "note": None,
        }
        second_decision = await other_client.post(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{item['adjudication_id']}/submit",
            json={
                **draft_payload,
                "outcome": "all_wrong",
                "preferred_submission_id": None,
                "reviewer_assessments": [
                    {
                        "submission_id": submission["submission_id"],
                        "assessment": "incorrect",
                    }
                    for submission in item["submissions"]
                ],
                "comment": "All reviewer answers are wrong",
                "corrected_provenance_spans": [marked_span],
            },
            headers={
                **mutation_headers(other_csrf),
                "Idempotency-Key": "group-adj-second-independent-verdict",
            },
        )
        assert second_decision.status_code == 201, second_decision.text
        assert second_decision.json()["decision_id"] != decision.json()["decision_id"]
        assert second_decision.json()["corrected_provenance_spans"] == [marked_span]
        assert other_ready_item["draft"]["decision"]["comment"] == "Other private draft"
        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            decisions = list(
                session.scalars(
                    select(AdjudicationDecision).where(
                        AdjudicationDecision.adjudication_id == item["adjudication_id"]
                    )
                )
            )
            assert {row.decided_by for row in decisions} == {
                adjudicator.user_id,
                other_adjudicator.user_id,
            }

        # A snapshotted participant who becomes inactive is audibly waived and no longer blocks
        # shared completion.
        with database.session() as session, session.begin():
            admin_user = session.get(User, admin.user_id)
            assert admin_user is not None
            admin_user.status = "suspended"
        reconciled = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications"
        )
        assert reconciled.status_code == 200
        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": tenant_id},
            )
            shared = session.scalar(
                select(Adjudication).where(Adjudication.id == item["adjudication_id"])
            )
            waived = session.scalar(
                select(AdjudicationParticipation).where(
                    AdjudicationParticipation.adjudication_id == item["adjudication_id"],
                    AdjudicationParticipation.adjudicator_id == admin.user_id,
                )
            )
            assert waived is not None and waived.status == "waived"
            waiver_audit = session.scalar(
                select(AuditEvent).where(
                    AuditEvent.event_type == "review.adjudication_participation_waived",
                    AuditEvent.object_id == str(waived.id),
                )
            )
            assert shared is not None and shared.status == "resolved"
            assert waiver_audit is not None

        other_queue = await other_client.get(f"/api/v1/tenants/{tenant_id}/review/adjudications")
        assert other_queue.status_code == 200
        first_anchor = first_case["workspace_adjudication_id"]
        other_anchor = other_queue.json()[0]["workspace_adjudication_id"]
        first_reported_bundle, other_reported_bundle = await asyncio.gather(
            adjudicator_client.get(
                f"/api/v1/tenants/{tenant_id}/review/adjudications/{first_anchor}/grouped-bundle"
            ),
            other_client.get(
                f"/api/v1/tenants/{tenant_id}/review/adjudications/{other_anchor}/grouped-bundle"
            ),
        )
        assert first_reported_bundle.status_code == other_reported_bundle.status_code == 200
        first_reported = next(
            entry
            for field_group in first_reported_bundle.json()["field_groups"]
            for entry in field_group["items"]
        )
        other_reported = next(
            entry
            for field_group in other_reported_bundle.json()["field_groups"]
            for entry in field_group["items"]
        )
        assert first_reported["adjudication_id"] == other_reported["adjudication_id"]
        reported_payload = {
            "outcome": "all_equivalent_supported",
            "assessments": [],
            "reviewer_assessments": [
                {
                    "submission_id": submission["submission_id"],
                    "assessment": "correct",
                }
                for submission in first_reported["submissions"]
            ],
            "evidence_ids": first_reported["evidence_window_ids"],
        }

        async def submit_reported(client, csrf_token: str, idem: str):
            return await client.post(
                f"/api/v1/tenants/{tenant_id}/review/adjudications/"
                f"{first_reported['adjudication_id']}/submit",
                json=reported_payload,
                headers={
                    **mutation_headers(csrf_token),
                    "Idempotency-Key": idem,
                },
            )

        concurrent_results = await asyncio.gather(
            submit_reported(
                adjudicator_client,
                adjudicator_csrf,
                "group-adj-concurrent-reported-one",
            ),
            submit_reported(
                other_client,
                other_csrf,
                "group-adj-concurrent-reported-two",
            ),
        )
        assert [response.status_code for response in concurrent_results] == [201, 201]
        assert len({response.json()["decision_id"] for response in concurrent_results}) == 2
        assert {response.json()["status"] for response in concurrent_results} == {
            "submitted",
            "resolved",
        }

        finished_cases = await adjudicator_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudication-campaigns/"
            f"{campaign_id}/cases?status=finished"
        )
        assert finished_cases.status_code == 200, finished_cases.text
        finished_case = next(
            entry
            for entry in finished_cases.json()["items"]
            if entry["case_id"] == open_case["case_id"]
        )
        assert finished_case["workspace_mode"] == "read_only"
        assert finished_case["workspace_adjudication_id"] == adjudication_id
        assert {field["state"] for field in finished_case["field_progress"]} == {
            "adjudicated_by_me"
        }

        reviewer_read = await first_client.get(
            f"/api/v1/tenants/{tenant_id}/review/adjudications/{adjudication_id}/grouped-bundle"
        )
        assert reviewer_read.status_code == 403
