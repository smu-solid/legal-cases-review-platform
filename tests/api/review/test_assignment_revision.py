from __future__ import annotations

from contextlib import AsyncExitStack

import pytest

from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.annotations import preferred_annotation
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, login, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_manager_revision_window_and_reviewer_reopen(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer_a = add_review_user(
        database, settings, admin, email="revision-a@example.test", role="reviewer"
    )
    reviewer_b = add_review_user(
        database, settings, admin, email="revision-b@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        admin_client, client_a, client_b = await open_clients(stack, settings, 3)
        await import_campaign(admin_client, admin, key="revision")
        _, admin_csrf = await login(admin_client, admin.email, admin.password)
        csrf_a = await authenticate(client_a, reviewer_a)
        csrf_b = await authenticate(client_b, reviewer_b)
        base = f"/api/v1/tenants/{admin.tenant_id}/review"
        admin_base = f"/api/v1/admin/tenants/{admin.tenant_id}/review"

        # Reviewer A claims and submits a single review of a unit that needs two, so the unit stays
        # in_review — the only state in which a manager may return the submission for correction.
        queue = await client_a.get(f"{base}/queue", params={"limit": 100})
        unit_id = queue.json()["items"][0]["review_unit_id"]
        claim = await client_a.post(
            f"{base}/claim",
            json={"review_unit_id": unit_id},
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "revision-claim"},
        )
        assert claim.status_code == 201
        assignment_id = claim.json()["assignment_id"]
        claim_etag = claim.headers["etag"]
        bundle = await client_a.get(f"{base}/assignments/{assignment_id}/bundle")
        annotation = preferred_annotation(bundle.json())
        submitted = await client_a.post(
            f"{base}/assignments/{assignment_id}/submit",
            json=annotation,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "revision-submit",
                "If-Match": claim_etag,
            },
        )
        assert submitted.status_code == 201
        submit_etag = submitted.headers["etag"]

        revision_url = f"{admin_base}/assignments/{assignment_id}/request-revision"

        # An ordinary reviewer cannot return a submission for revision.
        forbidden = await client_b.post(
            revision_url,
            json={"reason": "fix the value"},
            headers={
                **mutation_headers(csrf_b),
                "Idempotency-Key": "revision-forbidden",
                "If-Match": submit_etag,
            },
        )
        assert forbidden.status_code == 403

        # A blank reason is rejected by the server-authoritative invariant.
        blank_reason = await admin_client.post(
            revision_url,
            json={"reason": "   "},
            headers={
                **mutation_headers(admin_csrf),
                "Idempotency-Key": "revision-blank",
                "If-Match": submit_etag,
            },
        )
        assert blank_reason.status_code == 422
        assert blank_reason.json()["code"] == "revision_reason_required"

        # A stale If-Match fails safely rather than acting on an outdated version.
        stale = await admin_client.post(
            revision_url,
            json={"reason": "fix the value"},
            headers={
                **mutation_headers(admin_csrf),
                "Idempotency-Key": "revision-stale",
                "If-Match": claim_etag,
            },
        )
        assert stale.status_code == 412

        # The manager returns the submission for correction.
        revised = await admin_client.post(
            revision_url,
            json={"reason": "please correct the extracted value"},
            headers={
                **mutation_headers(admin_csrf),
                "Idempotency-Key": "revision-request",
                "If-Match": submit_etag,
            },
        )
        assert revised.status_code == 200
        assert revised.json()["status"] == "revision_requested"
        assert revised.json()["revision_reason"] == "please correct the extracted value"
        assert revised.json()["revision_requested_at"] is not None
        revision_etag = revised.headers["etag"]
        assert revision_etag != submit_etag

        # The manager action is idempotent across replays of the same request.
        replay = await admin_client.post(
            revision_url,
            json={"reason": "please correct the extracted value"},
            headers={
                **mutation_headers(admin_csrf),
                "Idempotency-Key": "revision-request",
                "If-Match": submit_etag,
            },
        )
        assert replay.status_code == 200
        assert replay.json()["replayed"] is True

        reopen_url = f"{base}/assignments/{assignment_id}/reopen"

        # A peer cannot reopen someone else's assignment (ownership-scoped → 404).
        peer_reopen = await client_b.post(
            reopen_url,
            headers={
                **mutation_headers(csrf_b),
                "Idempotency-Key": "revision-peer-reopen",
                "If-Match": revision_etag,
            },
        )
        assert peer_reopen.status_code == 404

        # The reviewer reopens the returned assignment back to editable claimed state.
        reopened = await client_a.post(
            reopen_url,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "revision-reopen",
                "If-Match": revision_etag,
            },
        )
        assert reopened.status_code == 200
        assert reopened.json()["status"] == "claimed"
        reopen_etag = reopened.headers["etag"]

        # Reopening an assignment that is not waiting for revision is a safe conflict.
        reopen_again = await client_a.post(
            reopen_url,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "revision-reopen-again",
                "If-Match": reopen_etag,
            },
        )
        assert reopen_again.status_code == 409
        assert reopen_again.json()["code"] == "assignment_revision_not_reopenable"

        # The reviewer resubmits the correction through the existing submit path.
        resubmitted = await client_a.post(
            f"{base}/assignments/{assignment_id}/submit",
            json=annotation,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "revision-resubmit",
                "If-Match": reopen_etag,
            },
        )
        assert resubmitted.status_code == 201
        assert resubmitted.json()["state"] == "submitted"
