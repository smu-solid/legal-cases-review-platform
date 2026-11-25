from __future__ import annotations

from contextlib import AsyncExitStack

import pytest

from review_platform.common.pagination import encode_cursor
from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.annotations import preferred_annotation
from tests.support.campaigns import add_review_user, expire_assignment_lease, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_assignment_lifecycle_renew_release_and_expiry(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewers = [
        add_review_user(
            database,
            settings,
            admin,
            email=f"lifecycle-reviewer-{index}@example.test",
            role="reviewer",
        )
        for index in range(1, 4)
    ]
    async with AsyncExitStack() as stack:
        admin_client, client_a, client_b, client_c = await open_clients(stack, settings, 4)
        await import_campaign(admin_client, admin, key="lifecycle")
        csrf_a = await authenticate(client_a, reviewers[0])
        csrf_b = await authenticate(client_b, reviewers[1])
        csrf_c = await authenticate(client_c, reviewers[2])
        base = f"/api/v1/tenants/{admin.tenant_id}/review"

        full = await client_a.get(f"{base}/queue", params={"limit": 100})
        unit_ids = [item["review_unit_id"] for item in full.json()["items"]]
        assert len(unit_ids) >= 3
        unit_renew, unit_release, unit_expiry = unit_ids[0], unit_ids[1], unit_ids[2]

        # --- renew extends the lease without bumping the optimistic-concurrency version ---
        claim_renew = await client_a.post(
            f"{base}/claim",
            json={"review_unit_id": unit_renew},
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-claim-renew"},
        )
        assert claim_renew.status_code == 201
        renew_id = claim_renew.json()["assignment_id"]
        claim_lock = claim_renew.json()["lock_version"]
        claim_lease = claim_renew.json()["lease_expires_at"]
        claim_etag = claim_renew.headers["etag"]

        bundle = await client_a.get(f"{base}/assignments/{renew_id}/bundle")
        assert bundle.json()["allowed_actions"] == ["save_draft", "submit", "renew", "release"]

        # A peer cannot renew or release someone else's assignment (ownership-scoped → 404).
        peer_renew = await client_b.post(
            f"{base}/assignments/{renew_id}/renew",
            headers={**mutation_headers(csrf_b), "Idempotency-Key": "lifecycle-peer-renew"},
        )
        assert peer_renew.status_code == 404
        peer_release = await client_b.post(
            f"{base}/assignments/{renew_id}/release",
            headers={**mutation_headers(csrf_b), "Idempotency-Key": "lifecycle-peer-release"},
        )
        assert peer_release.status_code == 404

        renewed = await client_a.post(
            f"{base}/assignments/{renew_id}/renew",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-renew-1"},
        )
        assert renewed.status_code == 200
        assert renewed.json()["status"] == "claimed"
        assert renewed.json()["lock_version"] == claim_lock
        assert renewed.json()["lease_expires_at"] >= claim_lease
        assert renewed.headers["etag"] == claim_etag
        renew_replay = await client_a.post(
            f"{base}/assignments/{renew_id}/renew",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-renew-1"},
        )
        assert renew_replay.status_code == 200
        assert renew_replay.json()["replayed"] is True

        # The pre-renew ETag still matches, proving renew left the draft version untouched.
        draft_bundle = await client_a.get(f"{base}/assignments/{renew_id}/bundle")
        annotation = preferred_annotation(draft_bundle.json())
        drafted = await client_a.put(
            f"{base}/assignments/{renew_id}/draft",
            json=annotation,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "lifecycle-draft-1",
                "If-Match": claim_etag,
            },
        )
        assert drafted.status_code == 200
        submitted = await client_a.post(
            f"{base}/assignments/{renew_id}/submit",
            json=annotation,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "lifecycle-submit-1",
                "If-Match": drafted.headers["etag"],
            },
        )
        assert submitted.status_code == 201
        # A submitted assignment can neither be released nor renewed.
        release_submitted = await client_a.post(
            f"{base}/assignments/{renew_id}/release",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-release-submitted"},
        )
        assert release_submitted.status_code == 409
        assert release_submitted.json()["code"] == "assignment_not_releasable"
        renew_submitted = await client_a.post(
            f"{base}/assignments/{renew_id}/renew",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-renew-submitted"},
        )
        assert renew_submitted.status_code == 409
        assert renew_submitted.json()["code"] == "assignment_not_editable"

        # --- release returns the claim to the pool and is idempotent across keys ---
        claim_release = await client_a.post(
            f"{base}/claim",
            json={"review_unit_id": unit_release},
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-claim-release"},
        )
        assert claim_release.status_code == 201
        release_id = claim_release.json()["assignment_id"]
        released = await client_a.post(
            f"{base}/assignments/{release_id}/release",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-release-1"},
        )
        assert released.status_code == 200
        assert released.json()["status"] == "released"
        release_replay = await client_a.post(
            f"{base}/assignments/{release_id}/release",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-release-1"},
        )
        assert release_replay.status_code == 200
        assert release_replay.json()["replayed"] is True
        release_noop = await client_a.post(
            f"{base}/assignments/{release_id}/release",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-release-2"},
        )
        assert release_noop.status_code == 200
        assert release_noop.json()["status"] == "released"
        released_bundle = await client_a.get(f"{base}/assignments/{release_id}/bundle")
        assert released_bundle.json()["allowed_actions"] == []
        # The freed slot is claimable by another reviewer.
        peer_claim = await client_b.post(
            f"{base}/claim",
            json={"review_unit_id": unit_release},
            headers={**mutation_headers(csrf_b), "Idempotency-Key": "lifecycle-peer-claim"},
        )
        assert peer_claim.status_code == 201

        # --- expiry frees an occupied slot for reclamation by a different reviewer ---
        claim_expiry_a = await client_a.post(
            f"{base}/claim",
            json={"review_unit_id": unit_expiry},
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-expiry-a"},
        )
        assert claim_expiry_a.status_code == 201
        expiry_a_id = claim_expiry_a.json()["assignment_id"]
        claim_expiry_b = await client_b.post(
            f"{base}/claim",
            json={"review_unit_id": unit_expiry},
            headers={**mutation_headers(csrf_b), "Idempotency-Key": "lifecycle-expiry-b"},
        )
        assert claim_expiry_b.status_code == 201
        # Both slots are full, so a third reviewer is turned away.
        full_claim = await client_c.post(
            f"{base}/claim",
            json={"review_unit_id": unit_expiry},
            headers={**mutation_headers(csrf_c), "Idempotency-Key": "lifecycle-expiry-c-full"},
        )
        assert full_claim.status_code == 409
        assert full_claim.json()["code"] == "no_review_work_available"
        # Reviewer A's lease lapses; its slot is now reclaimable.
        expire_assignment_lease(database, admin.tenant_id, expiry_a_id)
        reclaim = await client_c.post(
            f"{base}/claim",
            json={"review_unit_id": unit_expiry},
            headers={**mutation_headers(csrf_c), "Idempotency-Key": "lifecycle-expiry-c-reclaim"},
        )
        assert reclaim.status_code == 201
        # C's reclaim consumed the freed capacity, so the expired holder cannot recover: renew,
        # draft, and submit all refuse (contrast with the self-heal test below, where the slot is
        # still free), and the bundle offers no actions.
        expired_bundle = await client_a.get(f"{base}/assignments/{expiry_a_id}/bundle")
        assert expired_bundle.json()["allowed_actions"] == []
        expired_renew = await client_a.post(
            f"{base}/assignments/{expiry_a_id}/renew",
            headers={**mutation_headers(csrf_a), "Idempotency-Key": "lifecycle-expired-renew"},
        )
        assert expired_renew.status_code == 409
        assert expired_renew.json()["code"] == "assignment_lease_expired"
        expired_annotation = preferred_annotation(expired_bundle.json())
        expired_draft = await client_a.put(
            f"{base}/assignments/{expiry_a_id}/draft",
            json=expired_annotation,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "lifecycle-expired-draft",
                "If-Match": claim_expiry_a.headers["etag"],
            },
        )
        assert expired_draft.status_code == 409
        assert expired_draft.json()["code"] == "assignment_lease_expired"
        expired_submit = await client_a.post(
            f"{base}/assignments/{expiry_a_id}/submit",
            json=expired_annotation,
            headers={
                **mutation_headers(csrf_a),
                "Idempotency-Key": "lifecycle-expired-submit",
                "If-Match": claim_expiry_a.headers["etag"],
            },
        )
        assert expired_submit.status_code == 409
        assert expired_submit.json()["code"] == "assignment_lease_expired"


@pytest.mark.anyio
async def test_expired_lease_self_heals_while_capacity_remains(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    """A lapsed lease recovers in place when nobody has reclaimed the freed slot."""

    reviewer = add_review_user(
        database,
        settings,
        admin,
        email="lease-self-heal@example.test",
        role="reviewer",
    )
    async with AsyncExitStack() as stack:
        admin_client, client = await open_clients(stack, settings, 2)
        await import_campaign(admin_client, admin, key="lease-self-heal")
        csrf = await authenticate(client, reviewer)
        base = f"/api/v1/tenants/{admin.tenant_id}/review"

        queue = await client.get(f"{base}/queue", params={"limit": 1})
        unit_id = queue.json()["items"][0]["review_unit_id"]
        claim = await client.post(
            f"{base}/claim",
            json={"review_unit_id": unit_id},
            headers={**mutation_headers(csrf), "Idempotency-Key": "self-heal-claim"},
        )
        assert claim.status_code == 201
        assignment_id = claim.json()["assignment_id"]
        claim_lease = claim.json()["lease_expires_at"]

        # Renew restores the lapsed lease without bumping the optimistic-concurrency version.
        expire_assignment_lease(database, admin.tenant_id, assignment_id)
        renewed = await client.post(
            f"{base}/assignments/{assignment_id}/renew",
            headers={**mutation_headers(csrf), "Idempotency-Key": "self-heal-renew"},
        )
        assert renewed.status_code == 200
        assert renewed.json()["lease_expires_at"] >= claim_lease
        assert renewed.json()["lock_version"] == claim.json()["lock_version"]
        assert renewed.headers["etag"] == claim.headers["etag"]

        # A draft on a lapsed lease re-extends it as part of the write instead of refusing.
        expire_assignment_lease(database, admin.tenant_id, assignment_id)
        bundle = await client.get(f"{base}/assignments/{assignment_id}/bundle")
        annotation = preferred_annotation(bundle.json())
        drafted = await client.put(
            f"{base}/assignments/{assignment_id}/draft",
            json=annotation,
            headers={
                **mutation_headers(csrf),
                "Idempotency-Key": "self-heal-draft",
                "If-Match": claim.headers["etag"],
            },
        )
        assert drafted.status_code == 200

        # So does a submit -- the lapse is invisible to the reviewer while the slot is theirs.
        expire_assignment_lease(database, admin.tenant_id, assignment_id)
        submitted = await client.post(
            f"{base}/assignments/{assignment_id}/submit",
            json=annotation,
            headers={
                **mutation_headers(csrf),
                "Idempotency-Key": "self-heal-submit",
                "If-Match": drafted.headers["etag"],
            },
        )
        assert submitted.status_code == 201


@pytest.mark.anyio
async def test_review_queue_pagination_and_status_filter(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database,
        settings,
        admin,
        email="reviewer-pager@example.test",
        role="reviewer",
    )
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        await import_campaign(admin_client, admin)
        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        base = f"/api/v1/tenants/{admin.tenant_id}/review/queue"

        # The whole available pool fits in one large page with no more to fetch.
        full = await reviewer_client.get(base, params={"limit": 100})
        assert full.status_code == 200
        assert full.json()["has_more"] is False
        assert full.json()["next_cursor"] is None
        full_ids = [item["review_unit_id"] for item in full.json()["items"]]
        assert len(full_ids) >= 3

        # Paging one item at a time yields the same order with no gaps or duplicates.
        collected: list[str] = []
        cursor: str | None = None
        for _ in range(len(full_ids) + 2):
            params: dict[str, object] = {"limit": 1}
            if cursor is not None:
                params["cursor"] = cursor
            page = await reviewer_client.get(base, params=params)
            assert page.status_code == 200
            assert len(page.json()["items"]) <= 1
            collected.extend(item["review_unit_id"] for item in page.json()["items"])
            if page.json()["has_more"]:
                assert page.json()["next_cursor"] is not None
                cursor = str(page.json()["next_cursor"])
            else:
                assert page.json()["next_cursor"] is None
                break
        assert collected == full_ids

        # A malformed cursor fails closed rather than scanning from the start, whether it is
        # not decodable at all or decodes to a well-formed payload with an invalid keyset.
        bad = await reviewer_client.get(base, params={"cursor": "not-a-valid-cursor"})
        assert bad.status_code == 422
        assert bad.json()["code"] == "cursor_invalid"
        bad_keyset = await reviewer_client.get(
            base,
            params={"cursor": encode_cursor({"created_at": "not-a-timestamp", "id": "not-a-uuid"})},
        )
        assert bad_keyset.status_code == 422
        assert bad_keyset.json()["code"] == "cursor_invalid"

        # The assignment-status filter partitions claimed work from the available pool.
        target = full_ids[0]
        claim = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"review_unit_id": target},
            headers={**mutation_headers(reviewer_csrf), "Idempotency-Key": "pager-claim-0001"},
        )
        assert claim.status_code == 201
        assigned = await reviewer_client.get(base, params={"assignment_status": "assigned"})
        assert assigned.status_code == 200
        assert {item["review_unit_id"] for item in assigned.json()["items"]} == {target}
        assert all(item["assignment_status"] == "assigned" for item in assigned.json()["items"])
        assert assigned.json()["has_more"] is False
        available = await reviewer_client.get(base, params={"assignment_status": "available"})
        assert available.status_code == 200
        available_ids = {item["review_unit_id"] for item in available.json()["items"]}
        assert target not in available_ids
        assert all(item["assignment_status"] == "available" for item in available.json()["items"])
