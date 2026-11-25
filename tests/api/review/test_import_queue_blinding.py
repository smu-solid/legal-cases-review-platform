from __future__ import annotations

from contextlib import AsyncExitStack

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError

from review_platform.db.session import Database
from review_platform.review.models import (
    AnnotationRevision,
    Campaign,
    Candidate,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.settings import Settings
from tests.support.annotations import preferred_annotation
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_synthetic_import_queue_bundle_idempotency_and_blinding(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database,
        settings,
        admin,
        email="reviewer-one@example.test",
        role="reviewer",
    )
    peer = add_review_user(
        database,
        settings,
        admin,
        email="reviewer-peer@example.test",
        role="reviewer",
    )
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client, peer_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(admin_client, admin)
        assert imported["imported_units"] == 5
        assert imported["blocked_units"] == 1
        replay = await admin_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "synthetic-review",
                "campaign_name": "Synthetic Review",
            },
            headers={
                **mutation_headers(admin_client.cookies["__Host-review_csrf"]),
                "Idempotency-Key": "import-synthetic-review-0001",
            },
        )
        assert replay.status_code == 201
        assert replay.json()["replayed"] is True
        conflicting_replay = await admin_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "synthetic-review",
                "campaign_name": "A different request",
            },
            headers={
                **mutation_headers(admin_client.cookies["__Host-review_csrf"]),
                "Idempotency-Key": "import-synthetic-review-0001",
            },
        )
        assert conflicting_replay.status_code == 409
        assert conflicting_replay.json()["code"] == "idempotency_conflict"
        campaign_replay = await admin_client.post(
            f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
            json={
                "fixture_version": "v0001",
                "campaign_key": "synthetic-review",
                "campaign_name": "Synthetic Review",
            },
            headers={
                **mutation_headers(admin_client.cookies["__Host-review_csrf"]),
                "Idempotency-Key": "import-synthetic-replay-0002",
            },
        )
        assert campaign_replay.status_code == 201
        assert campaign_replay.json()["replayed"] is True

        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        await authenticate(peer_client, peer)
        queue = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/queue",
            params={
                "subject_kind": "case",
                "review_kind": "metadata_field",
                "campaign_id": imported["campaign_id"],
            },
        )
        assert queue.status_code == 200
        assert len(queue.json()["items"]) == 4
        subject_item = next(
            item for item in queue.json()["items"] if item["safe_field_label"] == "Subject"
        )
        claim = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"review_unit_id": subject_item["review_unit_id"]},
            headers={**mutation_headers(reviewer_csrf), "Idempotency-Key": "claim-subject-0001"},
        )
        assert claim.status_code == 201
        assignment_id = claim.json()["assignment_id"]
        claim_replay = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"review_unit_id": subject_item["review_unit_id"]},
            headers={**mutation_headers(reviewer_csrf), "Idempotency-Key": "claim-subject-0001"},
        )
        assert claim_replay.status_code == 201
        assert claim_replay.json()["assignment_id"] == assignment_id
        assert claim_replay.json()["replayed"] is True
        assignments = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments"
        )
        assert assignments.status_code == 200
        assert [item["assignment_id"] for item in assignments.json()] == [assignment_id]

        bundle = await reviewer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        assert bundle.status_code == 200
        assert bundle.json()["schema_version"] == "assignment-bundle/v1"
        assert bundle.json()["review_subject"]["subject_kind"] == "case"
        assert (
            "<script>alert('fixture')</script>" in bundle.json()["evidence_windows"][0]["snippet"]
        )
        assert bundle.headers["cache-control"] == "no-store"
        serialized = bundle.text
        for forbidden in (
            "validator_name",
            "validator_kind",
            "synthetic_model",
            "CASE000",
            "source_path",
            "reviewer-peer@example.test",
        ):
            assert forbidden not in serialized
        assert [item["label"] for item in bundle.json()["candidates"]] == ["A", "B"]

        peer_read = await peer_client.get(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        assert peer_read.status_code == 404

        invalid = preferred_annotation(bundle.json())
        invalid["outcome"] = "unsupported_or_not_locatable"
        invalid["assessments"] = [
            {"candidate_id": item["id"], "assessment": "not_assessable"}
            for item in bundle.json()["candidates"]
        ]
        rejected = await reviewer_client.put(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/draft",
            json=invalid,
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "draft-subject-bad-0001",
                "If-Match": claim.headers["etag"],
            },
        )
        assert rejected.status_code == 422
        assert rejected.json()["code"] == "comment_required"
        invalid_etag = await reviewer_client.put(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/draft",
            json=preferred_annotation(bundle.json()),
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "draft-subject-etag-0001",
                "If-Match": "1",
            },
        )
        assert invalid_etag.status_code == 422
        assert invalid_etag.json()["code"] == "if_match_invalid"
        invalid["comment"] = "The source does not identify a subject."
        saved = await reviewer_client.put(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/draft",
            json=invalid,
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "draft-subject-good-0001",
                "If-Match": claim.headers["etag"],
            },
        )
        assert saved.status_code == 200
        assert saved.json()["state"] == "draft"
        saved_replay = await reviewer_client.put(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/draft",
            json=invalid,
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "draft-subject-good-0001",
                "If-Match": claim.headers["etag"],
            },
        )
        assert saved_replay.status_code == 200
        assert saved_replay.json()["replayed"] is True
        stale = await reviewer_client.put(
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{assignment_id}/draft",
            json=invalid,
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "draft-subject-stale-0001",
                "If-Match": claim.headers["etag"],
            },
        )
        assert stale.status_code == 412

    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReviewUnit)) == 5
        assert session.scalar(select(func.count()).select_from(Candidate)) == 10
        assert set(session.scalars(select(Candidate.source_kind))) == {"deterministic", "model"}
        snapshot = session.scalar(select(SourceSnapshot).limit(1))
        assert snapshot is not None
        assert len(snapshot.external_item_key) == 64
        int(snapshot.external_item_key, 16)
        subject = session.scalar(select(ReviewSubject).limit(1))
        assert subject is not None
        assert subject.attributes_json["reference_semantics"] == (
            "snapshot-local-soft-no-cross-database-fk"
        )
        assert subject.attributes_json["snapshot_local_target_external_id"].startswith("CASE")
        assert len(subject.attributes_json["source_sha256"]) == 64
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                text(
                    "UPDATE review_platform.source_snapshots "
                    "SET source_version='tampered' WHERE id=:id"
                ),
                {"id": snapshot.id},
            )
        campaign = session.scalar(select(Campaign).limit(1))
        assert campaign is not None
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                text("UPDATE review_platform.campaigns SET manifest_digest=:digest WHERE id=:id"),
                {"digest": "0" * 64, "id": campaign.id},
            )
        unit = session.scalar(select(ReviewUnit).limit(1))
        assert unit is not None
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                text("UPDATE review_platform.review_units SET question='tampered' WHERE id=:id"),
                {"id": unit.id},
            )
        revision = session.scalar(select(AnnotationRevision).limit(1))
        assert revision is not None
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                text("DELETE FROM review_platform.annotation_revisions WHERE id=:id"),
                {"id": revision.id},
            )
