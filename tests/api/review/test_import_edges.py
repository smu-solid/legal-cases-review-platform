from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select, text

from review_platform.db.models import Tenant
from review_platform.db.session import Database
from review_platform.review.models import (
    Assignment,
    Campaign,
)
from review_platform.settings import Settings
from tests.support.annotations import preferred_annotation
from tests.support.campaigns import add_review_user, close_campaign, import_campaign
from tests.support.clients import authenticate, login, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_review_import_and_workflow_edges(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database,
        settings,
        admin,
        email="reviewer-edges@example.test",
        role="reviewer",
    )
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        admin_response, admin_csrf = await login(admin_client, admin.email, admin.password)
        assert admin_response.status_code == 200

        forbidden = await admin_client.get(f"/api/v1/tenants/{admin.tenant_id}/review/queue")
        assert forbidden.status_code == 403

        missing_tenant = await admin_client.post(
            f"/api/v1/admin/tenants/{uuid.uuid4()}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "missing-tenant",
                "campaign_name": "Missing tenant",
            },
            headers={**mutation_headers(admin_csrf), "Idempotency-Key": "missing-tenant-0001"},
        )
        assert missing_tenant.status_code == 404

        with database.session() as session, session.begin():
            other_tenant = Tenant(key="other-synthetic-tenant", name="Other tenant")
            session.add(other_tenant)
            session.flush()
            other_tenant_id = other_tenant.id
        mismatch = await admin_client.post(
            f"/api/v1/admin/tenants/{other_tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "wrong-tenant",
                "campaign_name": "Wrong tenant",
            },
            headers={**mutation_headers(admin_csrf), "Idempotency-Key": "wrong-tenant-0001"},
        )
        assert mismatch.status_code == 422
        assert mismatch.json()["code"] == "synthetic_tenant_mismatch"

        await import_campaign(admin_client, admin, key="edges")
        # The admin UI's "Load cases from database" button hits this same route; a campaign
        # imported through it is immediately reviewable ("published"), unlike the `make
        # seed-smoke` CLI path (test_dev_seed.py), which starts as an editable draft.
        with database.session() as session:
            campaign = session.scalar(
                select(Campaign).where(
                    Campaign.tenant_id == admin.tenant_id, Campaign.key == "edges"
                )
            )
        assert campaign is not None and campaign.status == "published"
        close_campaign(database, admin.tenant_id, "edges")
        copied = await admin_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "edges-copy",
                "campaign_name": "Synthetic copy",
            },
            headers={
                **mutation_headers(admin_client.cookies["__Host-review_csrf"]),
                "Idempotency-Key": "edges-copy-0001",
            },
        )
        assert copied.status_code == 201
        assert copied.json()["imported_units"] == 5
        # Same reason as above: "edges-scoped" below re-covers case 6's court_and_hearing group
        # (a scope isolating exactly one v0001-fixture unit -- "citations" no longer does this
        # since neutral/reported citation merged into case_metadata; see grouping.py).
        close_campaign(database, admin.tenant_id, "edges-copy")

        scoped = await admin_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "edges-scoped",
                "campaign_name": "Scoped synthetic review",
                "review_scope": {"group_ids": ["court_and_hearing"], "review_kinds": []},
            },
            headers={
                **mutation_headers(admin_client.cookies["__Host-review_csrf"]),
                "Idempotency-Key": "edges-scoped-0001",
            },
        )
        assert scoped.status_code == 201, scoped.text
        assert scoped.json()["review_scope"] == {
            "group_ids": ["court_and_hearing"],
            "review_kinds": [],
            "source_families": [],
        }
        assert scoped.json()["imported_units"] == 1

        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(admin.tenant_id)},
            )
            session.add(
                Campaign(
                    tenant_id=admin.tenant_id,
                    key="edges-conflict",
                    name="Conflicting campaign",
                    policy_json={"required_reviews": 2, "blocked_units": 0},
                    manifest_digest="0" * 64,
                    created_by=admin.user_id,
                )
            )
        campaign_conflict = await admin_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "edges-conflict",
                "campaign_name": "Synthetic Review",
            },
            headers={
                **mutation_headers(admin_client.cookies["__Host-review_csrf"]),
                "Idempotency-Key": "edges-conflict-0001",
            },
        )
        assert campaign_conflict.status_code == 409
        assert campaign_conflict.json()["code"] == "campaign_import_conflict"

        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        unfiltered_queue = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue"
        )
        assert unfiltered_queue.status_code == 200
        # "edges" and "edges-copy" are closed above; only "edges-scoped" (1 unit) is a live,
        # non-pool campaign, so the no-roster fallback (queue.py's `_reviewer_campaign_ids`)
        # correctly excludes the closed campaigns' units from an unfiltered reviewer queue.
        assert len(unfiltered_queue.json()["items"]) == 1
        claimed = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={
                "subject_kind": "case",
                "review_kind": "citation_link",
                "campaign_id": copied.json()["campaign_id"],
            },
            headers={**mutation_headers(reviewer_csrf), "Idempotency-Key": "edge-claim-0001"},
        )
        assert claimed.status_code == 201
        assignment_id = claimed.json()["assignment_id"]
        bundle = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        annotation = preferred_annotation(bundle.json())

        missing_assignment = await reviewer_client.put(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{uuid.uuid4()}/draft",
            json=annotation,
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "edge-missing-0001",
                "If-Match": '"1"',
            },
        )
        assert missing_assignment.status_code == 404

        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(admin.tenant_id)},
            )
            assignment = session.get(Assignment, uuid.UUID(assignment_id))
            assert assignment is not None
            assignment.lease_expires_at = assignment.claimed_at
        # Nobody reclaimed the freed slot, so a write on the lapsed lease self-heals it in place
        # instead of 409ing (see test_assignment_lifecycle for both sides of that boundary).
        expired = await reviewer_client.put(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/draft",
            json=annotation,
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "edge-expired-0001",
                "If-Match": claimed.headers["etag"],
            },
        )
        assert expired.status_code == 200
        with database.session() as session:
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(admin.tenant_id)},
            )
            healed = session.get(Assignment, uuid.UUID(assignment_id))
            assert healed is not None
            assert healed.lease_expires_at > healed.claimed_at

        missing_adjudication = await admin_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{uuid.uuid4()}/bundle"
        )
        assert missing_adjudication.status_code == 404

        disabled_settings = settings.model_copy(update={"synthetic_import_enabled": False})
        disabled_client = (await open_clients(stack, disabled_settings, 1))[0]
        disabled_login, disabled_csrf = await login(disabled_client, admin.email, admin.password)
        assert disabled_login.status_code == 200
        disabled = await disabled_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "disabled",
                "campaign_name": "Disabled",
            },
            headers={
                **mutation_headers(disabled_csrf),
                "Idempotency-Key": "disabled-import-0001",
            },
        )
        assert disabled.status_code == 403
        assert disabled.json()["code"] == "synthetic_import_disabled"


@pytest.mark.anyio
async def test_import_synthetic_new_key_after_conflict_succeeds(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """After a manifest-conflict 409 on a re-used key, a genuinely new key still imports cleanly --

    the conflicting row leaves no server-side state that blocks or corrupts a later import.
    """
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        with database.session() as session, session.begin():
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(admin.tenant_id)},
            )
            session.add(
                Campaign(
                    tenant_id=admin.tenant_id,
                    key="conflict-then-new",
                    name="Conflicting campaign",
                    policy_json={"required_reviews": 2, "blocked_units": 0},
                    manifest_digest="0" * 64,
                    created_by=admin.user_id,
                )
            )
        conflict = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "conflict-then-new",
                "campaign_name": "Synthetic Review",
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "conflict-then-new-0001"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["code"] == "campaign_import_conflict"

        fresh = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "conflict-then-new-2",
                "campaign_name": "Synthetic Review Retry",
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "conflict-then-new-2-0001"},
        )
        assert fresh.status_code == 201, fresh.text
        assert fresh.json()["replayed"] is False


@pytest.mark.anyio
async def test_import_synthetic_rejects_unknown_review_scope_group(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "bad-scope-import",
                "campaign_name": "Bad Scope Import",
                "review_scope": {"group_ids": ["not_a_group"], "review_kinds": []},
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "bad-scope-import-0001"},
        )
        assert r.status_code == 422, r.text
        assert r.json()["code"] == "validation_failed"


@pytest.mark.anyio
async def test_import_synthetic_rejects_unknown_source_family(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "bad-source-import",
                "campaign_name": "Bad Source Import",
                "review_scope": {"source_families": ["not_a_source"]},
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "bad-source-import-0001"},
        )
        assert r.status_code == 422, r.text
        assert r.json()["code"] == "validation_failed"


@pytest.mark.anyio
async def test_import_synthetic_rejects_nonzero_reviewer_count(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "reviewer-count-import",
                "campaign_name": "Reviewer Count Import",
                "reviewer_count": 3,
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "reviewer-count-import-0001"},
        )
        assert r.status_code == 422, r.text
        assert r.json()["code"] == "validation_failed"


@pytest.mark.anyio
async def test_import_synthetic_filters_by_source_family(
    settings: Settings, admin: AdminIdentity
) -> None:
    """A ``source_families`` scope only imports units whose fixture item is from that source."""
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "sample_a-only-import",
                "campaign_name": "Sample A Only Import",
                "review_scope": {"source_families": ["sample_a"]},
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "sample_a-only-import-0001"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        # 4 sample_a items in the v0001 fixture, one of which is unpublishable (unrecognised
        # validator kind) -- see fixtures/dataset_contracts/v0001/review_items.json.
        assert body["imported_units"] == 3
        assert body["review_scope"]["source_families"] == ["sample_a"]


@pytest.mark.anyio
async def test_import_synthetic_caps_by_case_count(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "capped-import",
                "campaign_name": "Capped Import",
                "case_count": 2,
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "capped-import-0001"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["imported_units"] == 2


@pytest.mark.anyio
async def test_import_synthetic_tops_up_existing_campaign_with_new_cases(
    settings: Settings, admin: AdminIdentity
) -> None:
    """A second import against the same campaign key must add cases not yet present, not just
    replay the old count -- there was previously no way to grow an already-imported campaign
    (e.g. one first created with a small ``case_count``, or an admin-authored empty draft) without
    a fresh campaign key."""

    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        first = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "topup-import",
                "campaign_name": "Topup Import",
                "case_count": 2,
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "topup-import-0001"},
        )
        assert first.status_code == 201, first.text
        assert first.json()["imported_units"] == 2
        assert first.json()["replayed"] is False

        topped_up = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "topup-import",
                "campaign_name": "Topup Import",
                "case_count": 100,
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "topup-import-0002"},
        )
        assert topped_up.status_code == 201, topped_up.text
        assert topped_up.json()["imported_units"] == 5
        assert topped_up.json()["blocked_units"] == 1
        assert topped_up.json()["replayed"] is False

        # Nothing left to add: a further call replays the now-complete count.
        replay = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "topup-import",
                "campaign_name": "Topup Import",
                "case_count": 100,
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "topup-import-0003"},
        )
        assert replay.status_code == 201, replay.text
        assert replay.json()["imported_units"] == 5
        assert replay.json()["replayed"] is True


@pytest.mark.anyio
async def test_import_synthetic_rejects_case_field_conflict_across_active_campaigns(
    settings: Settings, admin: AdminIdentity
) -> None:
    """Test import synthetic rejects case field conflict across active campaigns."""
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        first = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "conflict-guard-first",
                "campaign_name": "Conflict Guard First",
                "review_scope": {"group_ids": ["court_and_hearing"], "review_kinds": []},
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "conflict-guard-first-0001"},
        )
        assert first.status_code == 201, first.text
        assert first.json()["imported_units"] == 1

        second = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "conflict-guard-second",
                "campaign_name": "Conflict Guard Second",
                "review_scope": {"group_ids": ["court_and_hearing"], "review_kinds": []},
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "conflict-guard-second-0001"},
        )
        assert second.status_code == 409, second.text
        assert second.json()["code"] == "campaign_case_field_conflict"
        errors = second.json()["errors"]
        assert errors and errors[0]["code"] == "case_field_conflict"

        # The rejected import left no campaign row behind for its key -- a retry under the same
        # key still conflicts (rather than hitting an unrelated manifest/duplicate-key error).
        retry = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "conflict-guard-second",
                "campaign_name": "Conflict Guard Second Retry",
                "review_scope": {"group_ids": ["court_and_hearing"], "review_kinds": []},
            },
            headers={
                **mutation_headers(csrf),
                "Idempotency-Key": "conflict-guard-second-retry-0001",
            },
        )
        assert retry.status_code == 409, retry.text
        assert retry.json()["code"] == "campaign_case_field_conflict"


@pytest.mark.anyio
async def test_import_synthetic_honors_configured_minimum_reviews_per_case(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "min-reviews-import",
                "campaign_name": "Minimum Reviews Import",
                "minimum_reviews_per_case": 3,
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "min-reviews-import-0001"},
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["reviews_per_case"] == 3

        with database.session() as session:
            session.execute(
                text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
                {"tenant_id": str(admin.tenant_id)},
            )
            required_reviews = (
                session.execute(
                    text(
                        "SELECT DISTINCT required_reviews FROM review_platform.review_units "
                        "WHERE campaign_id = :campaign_id"
                    ),
                    {"campaign_id": body["campaign_id"]},
                )
                .scalars()
                .all()
            )
        assert required_reviews == [3]


@pytest.mark.anyio
async def test_import_synthetic_defaults_minimum_reviews_per_case_to_two(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "min-reviews-default",
                "campaign_name": "Minimum Reviews Default",
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "min-reviews-default-0001"},
        )
        assert r.status_code == 201, r.text
        assert r.json()["reviews_per_case"] == 2


@pytest.mark.anyio
async def test_import_synthetic_rejects_minimum_reviews_per_case_below_two(
    settings: Settings, admin: AdminIdentity
) -> None:
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        _, csrf = await login(client, admin.email, admin.password)

        r = await client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "min-reviews-invalid",
                "campaign_name": "Minimum Reviews Invalid",
                "minimum_reviews_per_case": 1,
            },
            headers={**mutation_headers(csrf), "Idempotency-Key": "min-reviews-invalid-0001"},
        )
        assert r.status_code == 422, r.text
        assert r.json()["code"] == "validation_failed"
