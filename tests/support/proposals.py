"""Author-only proposal lifecycle exercised through the production HTTP routes and PostgreSQL."""

import uuid
from contextlib import AsyncExitStack
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select

from review_platform.auth.service import now_utc
from review_platform.review.models import Assignment, Campaign, ReviewUnit
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.import_cases import _cited_case_relation, _real_case, _service


@pytest.fixture
async def proposal_workspace(database, settings, admin, tmp_path, request):
    required = getattr(request, "param", 2)
    reviewers = [
        add_review_user(
            database, settings, admin, email=f"proposal-{n}@example.test", role="reviewer"
        )
        for n in range(required)
    ]
    importer, sha = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha)
    case.relations.extend(
        [
            _cited_case_relation(),
            replace(
                _cited_case_relation(),
                review_kind="statute_reference",
                family="rel_statutes",
                relation_external_id="STAT-1",
                display_label="Statute reference",
                value={"to_statute_ext": "Test Act", "section_cited": "3"},
            ),
        ]
    )
    assignments = [[] for _ in reviewers]
    with database.session() as session, session.begin():
        result = importer.import_cases(
            session,
            tenant_id=admin.tenant_id,
            created_by=admin.user_id,
            campaign_key="proposals-test",
            campaign_name="Proposals",
            source_system="sample_a",
            cases=[case],
            minimum_reviews_per_case=required,
        )
        campaign = session.get(Campaign, result.campaign_id)
        campaign.status = "published"
        units = list(
            session.scalars(select(ReviewUnit).where(ReviewUnit.campaign_id == campaign.id))
        )
        for n, reviewer in enumerate(reviewers):
            for unit in units:
                assignment = Assignment(
                    tenant_id=admin.tenant_id,
                    review_unit_id=unit.id,
                    reviewer_id=reviewer.user_id,
                    lease_expires_at=now_utc() + timedelta(days=1),
                )
                session.add(assignment)
                session.flush()
                assignments[n].append(str(assignment.id))
        campaign_id = str(campaign.id)
    async with AsyncExitStack() as stack:
        clients = await open_clients(stack, settings, required)
        tokens = [await authenticate(c, r) for c, r in zip(clients, reviewers, strict=True)]
        bases = [
            f"/api/v1/tenants/{admin.tenant_id}/review/assignments/{a[0]}" for a in assignments
        ]
        yield clients, tokens, bases, assignments, campaign_id


def headers(token, version=1, key=None):
    return {
        **mutation_headers(token),
        "If-Match": f'"{version}"',
        "Idempotency-Key": key or str(uuid.uuid4()),
    }


def valid_body(bundle, group="cited_cases"):
    return {
        "group_id": group,
        "value": "  [2024] SGCA 7  ",
        "note": "My note",
        "provenance": [
            {
                "source_snapshot_id": bundle["source_render"]["source_snapshot_id"],
                "source_version": bundle["proposal_source_version"],
                "char_start": 0,
                "char_end": 5,
            }
        ],
    }
