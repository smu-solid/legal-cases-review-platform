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


@pytest.mark.anyio
async def test_proposal_lifecycle_independence_readiness_and_locks(
    proposal_workspace, database, admin
):
    clients, tokens, bases, assignments, campaign = proposal_workspace
    a, b = clients
    bundle = (await a.get(bases[0] + "/grouped-bundle")).json()
    labels = {g["group_id"]: g["add_item_label"] for g in bundle["field_groups"]}
    assert labels == {
        "case_metadata": None,
        "cited_cases": "cited case",
        "statutes_cited": "statute reference",
    }
    body = valid_body(bundle)
    pid = str(uuid.uuid4())
    url = bases[0] + f"/proposals/{pid}"
    h = headers(tokens[0], key="proposal-create-retry")
    created = await a.put(url + "/draft", json={**body, "value": "", "provenance": []}, headers=h)
    assert created.status_code == 200, created.text
    replay = await a.put(url + "/draft", json={**body, "value": "", "provenance": []}, headers=h)
    assert replay.json() == created.json()
    reloaded = (await a.get(bases[0] + "/grouped-bundle")).json()
    assert len(reloaded["reviewer_additions"]) == 1
    assert reloaded["progress"]["total_items"] == bundle["progress"]["total_items"] + 1
    assert (await b.get(bases[1] + "/grouped-bundle")).json()["reviewer_additions"] == []
    peer_bundle = (await b.get(bases[1] + "/grouped-bundle")).json()
    assert peer_bundle["progress"] == bundle["progress"]
    queue_path = bases[0].split("/assignments/")[0] + f"/campaigns/{campaign}/cases"
    own_queue = (await a.get(queue_path)).json()["items"][0]
    peer_queue = (await b.get(queue_path)).json()["items"][0]
    assert own_queue["fields_assigned"] == bundle["progress"]["total_items"] + 1
    assert peer_queue["fields_assigned"] == bundle["progress"]["total_items"]
    assert own_queue["status"] == "in_progress"

    denied = await b.put(
        bases[1] + f"/proposals/{pid}/draft", json=body, headers=headers(tokens[1], 2)
    )
    assert denied.status_code == 404
    denied_anchor = await b.put(url + "/draft", json=body, headers=headers(tokens[1], 2))
    assert denied_anchor.status_code == 404
    draft = await a.put(url + "/draft", json=body, headers=headers(tokens[0], 2))
    assert draft.status_code == 200, draft.text
    assert draft.json()["original_value"] == ""
    assert draft.json()["value"] == body["value"]
    submitted = await a.put(url + "/submitted", json=body, headers=headers(tokens[0], 3))
    assert submitted.status_code == 200, submitted.text
    assert (
        await a.put(url + "/submitted", json=body, headers=headers(tokens[0], 1))
    ).json() == submitted.json()
    assert (
        await a.put(url + "/removed", json=body, headers=headers(tokens[0], 4))
    ).status_code == 409
    from review_platform.review.models import Adjudication
    from review_platform.review.proposal_scope import eligible_proposal_query

    with database.session() as session:
        assert list(session.scalars(eligible_proposal_query())) == []
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    with database.session() as session, session.begin():
        for statement in (
            "UPDATE review_platform.reviewer_added_proposals SET value='changed' WHERE id=:id",
            "DELETE FROM review_platform.reviewer_added_proposals WHERE id=:id",
        ):
            with pytest.raises(DBAPIError), session.begin_nested():
                session.execute(text(statement), {"id": pid})
    # Ordinary field submissions remain independent; a peer need not finish the whole case.
    for n in range(2):
        for assignment in assignments[n]:
            base = bases[n].rsplit("/", 1)[0] + "/" + assignment
            result = await clients[n].post(
                base + "/answer/submit",
                json={"value_correct": True, "provenance_correct": True},
                headers=headers(tokens[n]),
            )
            assert result.status_code == 201, result.text
    with database.session() as session:
        assert len(list(session.scalars(select(Adjudication)))) == len(assignments[0])
        assert list(session.scalars(eligible_proposal_query())) == []
    unfinished_id = str(uuid.uuid4())
    unfinished = bases[0] + f"/proposals/{unfinished_id}"
    assert (
        await a.put(
            unfinished + "/draft", json={"group_id": "statutes_cited"}, headers=headers(tokens[0])
        )
    ).status_code == 200
    case_result = await a.post(bases[0] + "/case-submit", headers=headers(tokens[0]))
    assert case_result.status_code == 422, case_result.text
    assert (
        await a.put(
            unfinished + "/removed",
            json={"group_id": "statutes_cited"},
            headers=headers(tokens[0], 2),
        )
    ).status_code == 200
    case_result = await a.post(bases[0] + "/case-submit", headers=headers(tokens[0]))
    assert case_result.status_code == 201, case_result.text
    assert (await a.get(bases[0] + "/grouped-bundle")).json()["case_submitted"] is True
    assert (
        await a.put(
            bases[0] + f"/proposals/{uuid.uuid4()}/draft", json=body, headers=headers(tokens[0])
        )
    ).status_code == 409
    with database.session() as session:
        assert [str(p.id) for p in session.scalars(eligible_proposal_query())] == [pid]
    # A's case submit does not lock B, even though B's extracted fields are already submitted.
    other = await b.put(
        bases[1] + f"/proposals/{uuid.uuid4()}/draft", json=body, headers=headers(tokens[1])
    )
    assert other.status_code == 200, other.text
    assert (await b.get(bases[1] + "/grouped-bundle")).json()["case_submitted"] is False


@pytest.mark.anyio
async def test_proposal_validation_scope_and_stale_writes(proposal_workspace):
    clients, tokens, bases, _, _ = proposal_workspace
    client, token, base = clients[0], tokens[0], bases[0]
    bundle = (await client.get(base + "/grouped-bundle")).json()
    body = valid_body(bundle)
    for group in ("case_metadata", "appeal_relations", "arbitrary", "related_cases"):
        response = await client.put(
            base + f"/proposals/{uuid.uuid4()}/draft",
            json={**body, "group_id": group},
            headers=headers(token),
        )
        assert response.status_code == 403
    invalids = [{**body, "value": " \n "}, {**body, "provenance": []}]
    for patch in (
        {"source_snapshot_id": str(uuid.uuid4())},
        {"source_version": "0" * 64},
        {"char_start": -1},
        {"char_end": 99999999},
        {"char_end": 0},
        {"char_start": 5, "char_end": 5},
    ):
        invalids.append({**body, "provenance": [{**body["provenance"][0], **patch}]})
    for invalid in invalids:
        result = await client.put(
            base + f"/proposals/{uuid.uuid4()}/submitted", json=invalid, headers=headers(token)
        )
        assert result.status_code == 422, result.text
    pid = uuid.uuid4()
    url = base + f"/proposals/{pid}/draft"
    good = await client.put(url, json=body, headers=headers(token))
    assert good.status_code == 200, good.text
    stale = await client.put(url, json={**body, "note": "Changed"}, headers=headers(token))
    assert stale.status_code == 412
    saved = (await client.get(base + "/grouped-bundle")).json()["reviewer_additions"][0]
    assert saved["provenance"] == body["provenance"]
    assert saved["note"] == "My note"


@pytest.mark.anyio
async def test_campaign_assignment_and_tenant_guards(proposal_workspace, database):
    clients, tokens, bases, assignments, campaign_id = proposal_workspace
    client, token, base = clients[0], tokens[0], bases[0]
    body = valid_body((await client.get(base + "/grouped-bundle")).json())
    foreign_tenant = base.replace(base.split("/")[4], str(uuid.uuid4()))
    response = await client.put(
        foreign_tenant + f"/proposals/{uuid.uuid4()}/draft", json=body, headers=headers(token)
    )
    assert response.status_code in (403, 404)
    with database.session() as session, session.begin():
        campaign = session.get(Campaign, uuid.UUID(campaign_id))
        campaign.status = "closed"
    response = await client.put(
        base + f"/proposals/{uuid.uuid4()}/draft", json=body, headers=headers(token)
    )
    assert response.status_code == 403
    with database.session() as session, session.begin():
        assignment = session.get(Assignment, uuid.UUID(assignments[0][0]))
        assignment.status = "released"
    response = await client.put(
        base + f"/proposals/{uuid.uuid4()}/draft", json=body, headers=headers(token)
    )
    assert response.status_code == 404


@pytest.mark.anyio
async def test_create_retries_and_case_creation_race(proposal_workspace):
    import asyncio

    clients, tokens, bases, assignments, _ = proposal_workspace
    client, token, base = clients[0], tokens[0], bases[0]
    body = valid_body((await client.get(base + "/grouped-bundle")).json())
    url = base + f"/proposals/{uuid.uuid4()}/draft"
    h = headers(token, key="concurrent-proposal-create")
    results = await asyncio.gather(*[client.put(url, json=body, headers=h) for _ in range(2)])
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert results[0].json() == results[1].json()
    assert len((await client.get(base + "/grouped-bundle")).json()["reviewer_additions"]) == 1
    removed = await client.put(
        url.replace("/draft", "/removed"), json=body, headers=headers(token, 2)
    )
    assert removed.status_code == 200
    for assignment in assignments[0]:
        result = await client.post(
            base.rsplit("/", 1)[0] + f"/{assignment}/answer/submit",
            json={"value_correct": True, "provenance_correct": True},
            headers=headers(token),
        )
        assert result.status_code == 201
    created, submitted = await asyncio.gather(
        client.put(base + f"/proposals/{uuid.uuid4()}/draft", json=body, headers=headers(token)),
        client.post(base + "/case-submit", headers=headers(token)),
    )
    assert (created.status_code, submitted.status_code) in ((200, 422), (409, 201))
