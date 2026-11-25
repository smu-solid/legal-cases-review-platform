from __future__ import annotations

import asyncio
import uuid
from contextlib import AsyncExitStack

import httpx
import pytest
from sqlalchemy import func, select

from review_platform.db.models import AuditEvent, RoleGrant, TenantMembership
from review_platform.db.session import Database
from review_platform.review.models import (
    AdjudicationDecision,
)
from review_platform.settings import Settings
from tests.support.annotations import alternate_annotation, preferred_annotation
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_claim_update_races_and_pseudonymous_adjudication(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    identities = [
        add_review_user(
            database,
            settings,
            admin,
            email=f"race-reviewer-{index}@example.test",
            role="reviewer",
        )
        for index in range(1, 4)
    ]
    adjudicator = add_review_user(
        database,
        settings,
        admin,
        email="adjudicator@example.test",
        role="adjudicator",
    )
    other_adjudicator = add_review_user(
        database,
        settings,
        admin,
        email="other-adjudicator@example.test",
        role="adjudicator",
    )
    async with AsyncExitStack() as stack:
        clients = await open_clients(stack, settings, 7)
        await import_campaign(clients[0], admin, key="race")
        reviewer_clients = clients[1:4]
        reviewer_csrf = [
            await authenticate(client, identity)
            for client, identity in zip(reviewer_clients, identities, strict=True)
        ]
        adjudicator_client = clients[4]
        adjudicator_csrf = await authenticate(adjudicator_client, adjudicator)
        duplicate_client = clients[5]
        duplicate_csrf = await authenticate(duplicate_client, identities[0])
        other_adjudicator_client = clients[6]
        other_adjudicator_csrf = await authenticate(other_adjudicator_client, other_adjudicator)
        admin_csrf = await authenticate(clients[0], admin)

        idempotent_queue = await reviewer_clients[0].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"review_kind": "metadata_field"},
        )
        idempotent_unit = idempotent_queue.json()["items"][0]["review_unit_id"]

        async def same_key_claim(client: httpx.AsyncClient, csrf_token: str) -> httpx.Response:
            return await client.post(
                f"/api/v1/tenants/{admin.tenant_id}/review/claim",
                json={"review_unit_id": idempotent_unit},
                headers={
                    **mutation_headers(csrf_token),
                    "Idempotency-Key": "concurrent-same-key-0001",
                },
            )

        same_key_wave = await asyncio.gather(
            same_key_claim(reviewer_clients[0], reviewer_csrf[0]),
            same_key_claim(duplicate_client, duplicate_csrf),
        )
        assert [response.status_code for response in same_key_wave] == [201, 201]
        assert len({response.json()["assignment_id"] for response in same_key_wave}) == 1
        assert sorted(response.json()["replayed"] for response in same_key_wave) == [False, True]
        queue = await reviewer_clients[0].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={"review_kind": "citation_link"},
        )
        unit_id = queue.json()["items"][0]["review_unit_id"]

        async def race_claim(index: int, key: str) -> httpx.Response:
            return await reviewer_clients[index].post(
                f"/api/v1/tenants/{admin.tenant_id}/review/claim",
                json={"review_unit_id": unit_id},
                headers={
                    **mutation_headers(reviewer_csrf[index]),
                    "Idempotency-Key": key,
                },
            )

        first_wave = await asyncio.gather(
            race_claim(0, "race-claim-one-0001"), race_claim(1, "race-claim-two-0001")
        )
        assert [response.status_code for response in first_wave] == [201, 201]
        assert first_wave[0].json()["assignment_id"] != first_wave[1].json()["assignment_id"]
        winner = 0
        loser = 1
        claims = {0: first_wave[0], 1: first_wave[1]}
        third = await race_claim(2, "race-claim-third-0001")
        assert third.status_code == 409

        assignment_id = claims[winner].json()["assignment_id"]
        bundle = await reviewer_clients[winner].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        annotation = preferred_annotation(bundle.json())

        async def race_draft(key: str) -> httpx.Response:
            return await reviewer_clients[winner].put(
                f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/draft",
                json=annotation,
                headers={
                    **mutation_headers(reviewer_csrf[winner]),
                    "Idempotency-Key": key,
                    "If-Match": claims[winner].headers["etag"],
                },
            )

        draft_wave = await asyncio.gather(
            race_draft("race-draft-one-0001"), race_draft("race-draft-two-0001")
        )
        assert sorted(response.status_code for response in draft_wave) == [200, 412]
        saved = next(response for response in draft_wave if response.status_code == 200)
        submitted_one = await reviewer_clients[winner].post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/submit",
            json=annotation,
            headers={
                **mutation_headers(reviewer_csrf[winner]),
                "Idempotency-Key": "race-submit-one-0001",
                "If-Match": saved.headers["etag"],
            },
        )
        assert submitted_one.status_code == 201
        resubmitted = await reviewer_clients[winner].post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/submit",
            json=annotation,
            headers={
                **mutation_headers(reviewer_csrf[winner]),
                "Idempotency-Key": "race-resubmit-one-0002",
                "If-Match": submitted_one.headers["etag"],
            },
        )
        assert resubmitted.status_code == 409
        assert resubmitted.json()["code"] == "assignment_not_editable"

        loser_assignment = claims[loser].json()["assignment_id"]
        loser_bundle = await reviewer_clients[loser].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{loser_assignment}/bundle"
        )
        submitted_two = await reviewer_clients[loser].post(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{loser_assignment}/submit",
            json=alternate_annotation(loser_bundle.json()),
            headers={
                **mutation_headers(reviewer_csrf[loser]),
                "Idempotency-Key": "race-submit-two-0001",
                "If-Match": claims[loser].headers["etag"],
            },
        )
        assert submitted_two.status_code == 201

        admin_submissions = await clients[0].get(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/submissions",
            params={"review_unit_id": unit_id},
        )
        assert admin_submissions.status_code == 200
        assert admin_submissions.json()["has_more"] is False
        submission_items = admin_submissions.json()["items"]
        assert {item["reviewer_id"] for item in submission_items} == {
            str(identities[winner].user_id),
            str(identities[loser].user_id),
        }
        assert {item["outcome"] for item in submission_items} == {
            "candidate_a_preferred",
            "candidate_b_preferred",
        }
        first_submission_page = await clients[0].get(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/submissions",
            params={"review_unit_id": unit_id, "limit": 1},
        )
        assert first_submission_page.status_code == 200
        assert len(first_submission_page.json()["items"]) == 1
        assert first_submission_page.json()["has_more"] is True
        assert first_submission_page.json()["next_cursor"] is not None
        second_submission_page = await clients[0].get(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/submissions",
            params={
                "review_unit_id": unit_id,
                "limit": 1,
                "cursor": first_submission_page.json()["next_cursor"],
            },
        )
        assert second_submission_page.status_code == 200
        assert second_submission_page.json()["has_more"] is False
        paged_reviewers = {
            first_submission_page.json()["items"][0]["reviewer_id"],
            second_submission_page.json()["items"][0]["reviewer_id"],
        }
        assert paged_reviewers == {
            str(identities[winner].user_id),
            str(identities[loser].user_id),
        }
        reviewer_admin_read = await reviewer_clients[winner].get(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/submissions",
            params={"review_unit_id": unit_id},
        )
        assert reviewer_admin_read.status_code == 403
        agreement = await clients[0].get(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/agreement-metrics",
            params={"review_kind": "citation_link"},
        )
        assert agreement.status_code == 200
        assert agreement.json()["pair_count"] == 1
        assert agreement.json()["agree_count"] == 0
        assert agreement.json()["agreement_percent"] == 0.0
        assert agreement.json()["cohen_kappa"] == 0.0
        assert agreement.json()["pabak"] == -1.0
        assert len(agreement.json()["reviewer_pairs"]) == 1
        assert agreement.json()["reviewer_pairs"][0]["pair_count"] == 1

        reviewer_adjudications = await reviewer_clients[loser].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications"
        )
        assert reviewer_adjudications.status_code == 403
        reviewer_adjudication_claim = await reviewer_clients[loser].post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/claim",
            headers={
                **mutation_headers(reviewer_csrf[loser]),
                "Idempotency-Key": "reviewer-adjudication-claim-0001",
            },
        )
        assert reviewer_adjudication_claim.status_code == 403

        super_admin_adjudications = await clients[0].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications"
        )
        assert super_admin_adjudications.status_code == 200

        empty_adjudications = await adjudicator_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications"
        )
        assert empty_adjudications.status_code == 200
        assert empty_adjudications.json()[0]["ready_for_me_count"] == 1

        with database.session() as session, session.begin():
            membership_id = session.scalar(
                select(TenantMembership.id).where(
                    TenantMembership.tenant_id == admin.tenant_id,
                    TenantMembership.user_id == identities[winner].user_id,
                )
            )
            assert membership_id is not None
            session.add(
                RoleGrant(
                    membership_id=membership_id,
                    role_code="adjudicator",
                    granted_by=admin.user_id,
                )
            )
        conflicted_claim = await reviewer_clients[winner].post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/claim",
            headers={
                **mutation_headers(reviewer_csrf[winner]),
                "Idempotency-Key": "conflicted-adjudication-0001",
            },
        )
        assert conflicted_claim.status_code == 409
        assert conflicted_claim.json()["code"] == "no_adjudication_available"

        claimed_adjudication = await adjudicator_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/claim",
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "claim-adjudication-0001",
            },
        )
        assert claimed_adjudication.status_code == 201
        claim_replay = await adjudicator_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/claim",
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "claim-adjudication-0001",
            },
        )
        assert claim_replay.status_code == 201
        assert claim_replay.json()["replayed"] is True
        adjudications = await adjudicator_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications"
        )
        assert len(adjudications.json()) == 1
        adjudication = await adjudicator_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/"
            f"{claimed_adjudication.json()['adjudication_id']}/bundle"
        )
        assert adjudication.status_code == 200
        assert [item["pseudonym"] for item in adjudication.json()["submissions"]] == [
            "Reviewer 1",
            "Reviewer 2",
        ]
        assert {item["outcome"] for item in adjudication.json()["submissions"]} == {
            "candidate_a_preferred",
            "candidate_b_preferred",
        }
        adjudication_text = adjudication.text
        for identity in identities:
            assert identity.email not in adjudication_text
            assert str(identity.user_id) not in adjudication_text
        missing_adjudication = await adjudicator_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{uuid.uuid4()}/bundle"
        )
        assert missing_adjudication.status_code == 404
        unassigned_reader = await other_adjudicator_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/"
            f"{claimed_adjudication.json()['adjudication_id']}/bundle"
        )
        assert unassigned_reader.status_code == 200
        conflicted = await reviewer_clients[winner].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/"
            f"{claimed_adjudication.json()['adjudication_id']}/bundle"
        )
        assert conflicted.status_code == 404

        adjudication_id = claimed_adjudication.json()["adjudication_id"]
        final_decision = preferred_annotation(adjudication.json())
        reviewer_submit = await reviewer_clients[loser].post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/submit",
            json=final_decision,
            headers={
                **mutation_headers(reviewer_csrf[loser]),
                "Idempotency-Key": "reviewer-adjudication-submit-0001",
            },
        )
        assert reviewer_submit.status_code == 403
        unassigned_submit = await other_adjudicator_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/submit",
            json=final_decision,
            headers={
                **mutation_headers(other_adjudicator_csrf),
                "Idempotency-Key": "unassigned-adjudication-submit-0002",
            },
        )
        assert unassigned_submit.status_code == 201
        assert unassigned_submit.json()["status"] == "submitted"
        resolved = await adjudicator_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/submit",
            json=final_decision,
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "resolve-adjudication-0001",
            },
        )
        assert resolved.status_code == 201
        assert resolved.json()["status"] == "submitted"
        assert resolved.json()["outcome"] == "candidate_a_preferred"
        assert resolved.json()["replayed"] is False
        resolve_replay = await adjudicator_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/submit",
            json=final_decision,
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "resolve-adjudication-0001",
            },
        )
        assert resolve_replay.status_code == 201
        assert resolve_replay.json()["replayed"] is True
        resolve_again = await adjudicator_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/submit",
            json=final_decision,
            headers={
                **mutation_headers(adjudicator_csrf),
                "Idempotency-Key": "resolve-adjudication-0002",
            },
        )
        assert resolve_again.status_code == 409
        assert resolve_again.json()["code"] == "adjudication_not_editable"

        admin_bundle = await clients[0].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/bundle"
        )
        assert admin_bundle.status_code == 200
        admin_resolution = await clients[0].post(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/submit",
            json=preferred_annotation(admin_bundle.json()),
            headers={
                **mutation_headers(admin_csrf),
                "Idempotency-Key": "resolve-adjudication-super-admin-0001",
            },
        )
        assert admin_resolution.status_code == 201, admin_resolution.text
        assert admin_resolution.json()["status"] == "resolved"
        resolved_bundle = await adjudicator_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{adjudication_id}/bundle"
        )
        assert resolved_bundle.status_code == 404
        resolved_queue = await adjudicator_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications"
        )
        assert resolved_queue.json() == []
        reviewer_bundle_after_resolution = await reviewer_clients[winner].get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        assert reviewer_bundle_after_resolution.status_code == 200
        reviewer_text = reviewer_bundle_after_resolution.text
        assert "Reviewer 1" not in reviewer_text
        assert "candidate_b_preferred" not in reviewer_text
        with database.session() as session, session.begin():
            decision_count = session.scalar(select(func.count()).select_from(AdjudicationDecision))
            assert decision_count == 3
            audit_event = session.scalar(
                select(AuditEvent).where(AuditEvent.event_type == "review.adjudication_resolved")
            )
            assert audit_event is not None
            assert audit_event.object_id == adjudication_id
