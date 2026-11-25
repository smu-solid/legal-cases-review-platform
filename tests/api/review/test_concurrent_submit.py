"""Two independent reviewers submitting the same review unit at the same time (RF-013).

Each reviewer owns a distinct assignment, so both submits must succeed; the review unit's
row lock in the adjudication-advance step must serialize them so the unit advances to
adjudication exactly once and only a single adjudication is created.
"""

from __future__ import annotations

import asyncio
import uuid
from contextlib import AsyncExitStack

import httpx
import pytest
from sqlalchemy import func, select

from review_platform.db.session import Database
from review_platform.review.models import Adjudication, ReviewUnit
from review_platform.settings import Settings
from tests.support.annotations import alternate_annotation, preferred_annotation
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import AdminIdentity


@pytest.mark.anyio
async def test_concurrent_two_reviewer_submit_advances_adjudication_once(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer_a = add_review_user(
        database, settings, admin, email="concurrent-a@example.test", role="reviewer"
    )
    reviewer_b = add_review_user(
        database, settings, admin, email="concurrent-b@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        admin_client, client_a, client_b = await open_clients(stack, settings, 3)
        await import_campaign(admin_client, admin, key="concurrent")
        csrf_a = await authenticate(client_a, reviewer_a)
        csrf_b = await authenticate(client_b, reviewer_b)
        base = f"/api/v1/tenants/{admin.tenant_id}/review"

        # A double-review unit (required_reviews == 2): both reviewers claim distinct slots.
        queue = await client_a.get(f"{base}/queue", params={"review_kind": "citation_link"})
        unit_id = queue.json()["items"][0]["review_unit_id"]

        async def claim(client: httpx.AsyncClient, csrf: str, key: str) -> httpx.Response:
            return await client.post(
                f"{base}/claim",
                json={"review_unit_id": unit_id},
                headers={**mutation_headers(csrf), "Idempotency-Key": key},
            )

        claim_a = await claim(client_a, csrf_a, "concurrent-claim-a")
        claim_b = await claim(client_b, csrf_b, "concurrent-claim-b")
        assert claim_a.status_code == 201
        assert claim_b.status_code == 201
        assignment_a = claim_a.json()["assignment_id"]
        assignment_b = claim_b.json()["assignment_id"]
        assert assignment_a != assignment_b

        bundle_a = (await client_a.get(f"{base}/assignments/{assignment_a}/bundle")).json()
        bundle_b = (await client_b.get(f"{base}/assignments/{assignment_b}/bundle")).json()
        answer_a = preferred_annotation(bundle_a)
        answer_b = alternate_annotation(bundle_b)

        async def submit(
            client: httpx.AsyncClient,
            csrf: str,
            assignment_id: str,
            claim_response: httpx.Response,
            annotation: dict[str, object],
            key: str,
        ) -> httpx.Response:
            return await client.post(
                f"{base}/assignments/{assignment_id}/submit",
                json=annotation,
                headers={
                    **mutation_headers(csrf),
                    "Idempotency-Key": key,
                    "If-Match": claim_response.headers["etag"],
                },
            )

        # Submit both reviews at the same time; the shared unit row lock serializes the advance.
        submit_a, submit_b = await asyncio.gather(
            submit(client_a, csrf_a, assignment_a, claim_a, answer_a, "concurrent-submit-a"),
            submit(client_b, csrf_b, assignment_b, claim_b, answer_b, "concurrent-submit-b"),
        )
        assert submit_a.status_code == 201, submit_a.text
        assert submit_b.status_code == 201, submit_b.text

        # The unit advanced to adjudication exactly once, with a single adjudication row.
        with database.session() as session, session.begin():
            unit = session.get(ReviewUnit, uuid.UUID(unit_id))
            assert unit is not None
            assert unit.status == "in_adjudication"
            adjudication_count = session.scalar(
                select(func.count())
                .select_from(Adjudication)
                .where(Adjudication.review_unit_id == uuid.UUID(unit_id))
            )
            assert adjudication_count == 1
