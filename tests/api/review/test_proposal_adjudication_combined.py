"""Combined extracted/proposal targets keep private locks, versions, and progress."""

import asyncio
import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from review_platform.review.models import AdjudicationDecision
from tests.support.adjudication import adjudication_proposals, proposal_workspace
from tests.support.proposals import headers

__all__ = ["adjudication_proposals", "proposal_workspace"]


def original_decision(field):
    return {
        "outcome": "all_equivalent_supported",
        "membership_version": field["membership_version"],
        "reviewer_assessments": [
            {"submission_id": s["submission_id"], "assessment": "correct"}
            for s in field["submissions"]
        ],
        "evidence_ids": field["evidence_window_ids"],
    }


@pytest.mark.anyio
async def test_combined_extracted_identity_draft_versions_and_independence(
    adjudication_proposals, database
):
    clients, csrf, path, *_ = adjudication_proposals
    a, b = clients
    endpoint = path + "/proposal-items"
    base = (await a.get(path + "/case-workspace")).json()
    group = next(g for g in base["field_groups"] if g["group_id"] == "cited_cases")
    field = group["items"][0]
    original_path = path.rsplit("/", 1)[0] + "/" + field["adjudication_id"]
    payload = original_decision(field)
    for client, token in zip(clients, csrf, strict=True):
        saved = await client.put(original_path + "/draft", json=payload, headers=headers(token))
        assert saved.status_code == 200, saved.text
    item = (await a.get(endpoint)).json()["items"][0]
    combine = {
        "action": "combine",
        "item_id": item["id"],
        "expected_version": 1,
        "target_extracted_id": field["adjudication_id"],
        "target_membership_version": field["membership_version"],
        "confirm": True,
    }
    merged = await a.post(endpoint + "/membership", json=combine, headers=headers(csrf[0]))
    assert merged.status_code == 200, merged.text
    item = merged.json()["items"][0]
    assert item["extracted_adjudication_id"] == field["adjudication_id"]
    stale = await a.put(original_path + "/draft", json=payload, headers=headers(csrf[0]))
    assert stale.status_code == 412, stale.text
    mine = (await a.get(path + "/case-workspace")).json()
    theirs = (await b.get(path + "/case-workspace")).json()
    assert (
        mine["case"]["progress"]["total_scoped_fields"]
        == base["case"]["progress"]["total_scoped_fields"] - 1
    )
    assert theirs["case"]["progress"] == base["case"]["progress"]
    mine_field = next(
        i
        for g in mine["field_groups"]
        for i in g["items"]
        if i["adjudication_id"] == field["adjudication_id"]
    )
    peer_field = next(
        i
        for g in theirs["field_groups"]
        for i in g["items"]
        if i["adjudication_id"] == field["adjudication_id"]
    )
    assert mine_field["draft"] is None and peer_field["draft"] is not None
    # Separating restores the genuine extraction, and its membership epoch stays advanced.
    separated = await a.post(
        endpoint + "/membership",
        json={
            "action": "separate",
            "item_id": item["id"],
            "expected_version": 1,
            "confirm": True,
        },
        headers=headers(csrf[0]),
    )
    assert separated.status_code == 200, separated.text
    stale = await a.put(original_path + "/draft", json=payload, headers=headers(csrf[0]))
    assert stale.status_code == 412
    current = (await a.get(path + "/case-workspace")).json()
    current_field = next(
        i
        for g in current["field_groups"]
        for i in g["items"]
        if i["adjudication_id"] == field["adjudication_id"]
    )
    assert current_field["extracted_value_display"] == field["extracted_value_display"]
    assert current_field["membership_version"] == 2
    item = separated.json()["items"][0]
    combine.update(item_id=item["id"], target_membership_version=2)
    response = await a.post(endpoint + "/membership", json=combine, headers=headers(csrf[0]))
    assert response.status_code == 200, response.text
    item = next(i for i in response.json()["items"] if i["extracted_adjudication_id"])
    decision = {
        "expected_version": 1,
        "submit": True,
        "decision": {
            "outcome": "reviewer_preferred",
            "preferred_proposal_id": item["proposals"][0]["id"],
        },
    }
    key = str(uuid.uuid4())
    final = await a.put(
        endpoint + "/" + item["id"], json=decision, headers=headers(csrf[0], key=key)
    )
    assert final.status_code == 200, final.text
    replay = await a.put(
        endpoint + "/" + item["id"], json=decision, headers=headers(csrf[0], key=key)
    )
    assert replay.json() == final.json()
    assert (
        await a.put(original_path + "/draft", json=payload, headers=headers(csrf[0]))
    ).status_code in {409, 412}
    assert (
        await b.put(original_path + "/draft", json=payload, headers=headers(csrf[1]))
    ).status_code == 200
    with database.session() as session, session.begin():
        stored = session.scalar(
            select(AdjudicationDecision).where(
                AdjudicationDecision.adjudication_id == uuid.UUID(field["adjudication_id"])
            )
        )
        assert str(stored.preferred_proposal_id) == item["proposals"][0]["id"]
        with pytest.raises(DBAPIError), session.begin_nested():
            session.execute(
                text(
                    "UPDATE review_platform.proposal_adjudication_items "
                    "SET draft_json='{}' WHERE id=:id"
                ),
                {"id": item["id"]},
            )


@pytest.mark.anyio
async def test_concurrent_draft_writes_only_one_version_wins(adjudication_proposals):
    clients, csrf, path, *_ = adjudication_proposals
    a = clients[0]
    endpoint = path + "/proposal-items"
    item = (await a.get(endpoint)).json()["items"][0]
    results = await asyncio.gather(
        *[
            a.put(
                endpoint + "/" + item["id"],
                json={
                    "expected_version": 1,
                    "decision": {"outcome": "all_equivalent_supported", "comment": note},
                },
                headers=headers(csrf[0]),
            )
            for note in ("first", "second")
        ]
    )
    assert sorted(r.status_code for r in results) == [200, 412]
    latest = (await a.get(endpoint)).json()["items"][0]
    assert latest["lock_version"] == 2
    assert latest["draft"]["comment"] in {"first", "second"}


@pytest.mark.anyio
async def test_stale_membership_keeps_newer_draft_and_cross_tenant_is_denied(
    adjudication_proposals,
):
    clients, csrf, path, *_ = adjudication_proposals
    a = clients[0]
    endpoint = path + "/proposal-items"
    item = (await a.get(endpoint)).json()["items"][0]
    saved = await a.put(
        endpoint + "/" + item["id"],
        json={
            "expected_version": 1,
            "decision": {"outcome": "all_wrong", "comment": "Keep this draft"},
        },
        headers=headers(csrf[0]),
    )
    assert saved.status_code == 200
    response = await a.post(
        endpoint + "/membership",
        json={
            "action": "separate",
            "item_id": item["id"],
            "expected_version": 1,
            "confirm": True,
        },
        headers=headers(csrf[0]),
    )
    assert response.status_code == 412
    assert (await a.get(endpoint)).json()["items"][0]["draft"]["comment"] == "Keep this draft"
    foreign = endpoint.replace(endpoint.split("/tenants/")[1].split("/")[0], str(uuid.uuid4()))
    assert (await a.get(foreign)).status_code in {403, 404}
    assert (
        await a.put(
            foreign + "/" + item["id"],
            json={
                "expected_version": 2,
                "decision": {"outcome": "all_equivalent_supported"},
            },
            headers=headers(csrf[0]),
        )
    ).status_code in {403, 404}
