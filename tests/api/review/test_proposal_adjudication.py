"""Real HTTP proposal membership and submission, scoped independently to each adjudicator."""

import uuid

import pytest
from sqlalchemy import select

from review_platform.review.models import Adjudication
from tests.support.adjudication import adjudication_proposals
from tests.support.proposals import headers, proposal_workspace

__all__ = ["proposal_workspace", "adjudication_proposals"]


@pytest.mark.anyio
async def test_private_membership_drafts_retries_and_submitted_locks(adjudication_proposals):
    clients, csrf, path, reviewers, _tokens, _bases = adjudication_proposals
    a, b = clients
    endpoint = path + "/proposal-items"
    initial = (await a.get(endpoint)).json()
    assert initial["ready"] and len(initial["items"]) == 1
    item = initial["items"][0]
    assert len(item["proposals"]) == 2 and item["reviewer_count"] == 2
    peer = (await b.get(endpoint)).json()["items"][0]
    assert peer["id"] != item["id"]
    assert (await reviewers[0].get(endpoint)).status_code == 403
    wrong_owner = await b.put(
        endpoint + "/" + item["id"],
        json={"expected_version": 1, "decision": {"outcome": "all_equivalent_supported"}},
        headers=headers(csrf[1]),
    )
    assert wrong_owner.status_code == 404
    saved = await a.put(
        endpoint + "/" + item["id"],
        json={"expected_version": 1, "decision": {"outcome": "all_equivalent_supported"}},
        headers=headers(csrf[0]),
    )
    assert saved.status_code == 200, saved.text
    change = {"action": "separate", "item_id": item["id"], "expected_version": 2, "confirm": True}
    key = str(uuid.uuid4())
    split = await a.post(endpoint + "/membership", json=change, headers=headers(csrf[0], key=key))
    assert split.status_code == 200, split.text
    replay = await a.post(endpoint + "/membership", json=change, headers=headers(csrf[0], key=key))
    assert replay.json() == split.json()
    assert len(split.json()["items"]) == 2
    assert all(i["draft"] is None for i in split.json()["items"])
    assert len((await b.get(endpoint)).json()["items"]) == 1
    assert len((await a.get(endpoint)).json()["items"]) == 2
    one, two = split.json()["items"]
    combined = await a.post(
        endpoint + "/membership",
        json={
            "action": "combine",
            "item_id": one["id"],
            "expected_version": 1,
            "target_item_id": two["id"],
            "target_version": 1,
            "confirm": True,
        },
        headers=headers(csrf[0]),
    )
    assert combined.status_code == 200, combined.text
    merged = combined.json()["items"][0]
    preferred = merged["proposals"][1]["id"]
    submitted = await a.put(
        endpoint + "/" + merged["id"],
        json={
            "expected_version": 1,
            "submit": True,
            "decision": {"outcome": "reviewer_preferred", "preferred_proposal_id": preferred},
        },
        headers=headers(csrf[0]),
    )
    assert submitted.status_code == 200, submitted.text
    final = submitted.json()["items"][0]
    assert final["decision"]["preferred_proposal_id"] == preferred
    assert final["final_value"] == "Same citation" and final["final_provenance"]
    locked = await a.post(
        endpoint + "/membership",
        json={
            "action": "separate",
            "item_id": merged["id"],
            "expected_version": 2,
            "confirm": True,
        },
        headers=headers(csrf[0]),
    )
    assert locked.status_code == 409
    assert (await b.get(endpoint)).json()["items"][0]["state"] == "pending"


@pytest.mark.anyio
async def test_stale_and_invalid_proposal_decisions(adjudication_proposals):
    clients, csrf, path, *_ = adjudication_proposals
    a = clients[0]
    endpoint = path + "/proposal-items"
    item = (await a.get(endpoint)).json()["items"][0]
    own = endpoint + "/" + item["id"]
    response = await a.put(
        own,
        json={"expected_version": 9, "decision": {"outcome": "all_equivalent_supported"}},
        headers=headers(csrf[0]),
    )
    assert response.status_code == 412
    for decision in (
        {"outcome": "reviewer_preferred", "preferred_proposal_id": str(uuid.uuid4())},
        {"outcome": "all_wrong", "corrected_value": "New", "comment": "Why"},
        {"outcome": "unsupported_or_not_locatable"},
        {
            "outcome": "all_wrong",
            "corrected_value": "New",
            "comment": "Why",
            "provenance": [{**item["proposals"][0]["provenance"][0], "source_version": "0" * 64}],
        },
    ):
        response = await a.put(
            own,
            json={"expected_version": 1, "submit": True, "decision": decision},
            headers=headers(csrf[0]),
        )
        assert response.status_code == 422, response.text
    assert (await a.get(endpoint)).json()["items"][0]["lock_version"] == 1


@pytest.mark.anyio
@pytest.mark.parametrize("proposal_workspace", [2, 3], indirect=True)
@pytest.mark.parametrize("adjudication_proposals", ["single_author"], indirect=True)
async def test_frozen_n_case_gate_includes_multiple_proposals_from_one_author(
    adjudication_proposals,
):
    clients, csrf, path, reviewers, *_ = adjudication_proposals
    endpoint = path + "/proposal-items"
    view = (await clients[0].get(endpoint)).json()
    assert view["required_reviews"] == len(reviewers)
    assert view["ready"] and len(view["items"]) == 1
    item = view["items"][0]
    assert item["reviewer_count"] == 1
    assert [p["proposal_number"] for p in item["proposals"]] == [1, 2]
    response = await clients[0].put(
        endpoint + "/" + item["id"],
        json={
            "expected_version": 1,
            "submit": True,
            "decision": {
                "outcome": "reviewer_preferred",
                "preferred_proposal_id": item["proposals"][1]["id"],
            },
        },
        headers=headers(csrf[0]),
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["state"] == "submitted"
    assert (await clients[1].get(endpoint)).json()["items"][0]["state"] == "pending"


@pytest.mark.anyio
async def test_provenance_survives_opening_case_from_another_field_snapshot(
    adjudication_proposals, database
):
    from review_platform.review.models import ReviewSubject, ReviewUnit

    clients, csrf, path, *_ = adjudication_proposals
    first = (await clients[0].get(path + "/proposal-items")).json()
    saved_snapshot = first["items"][0]["proposals"][0]["provenance"][0]["source_snapshot_id"]
    with database.session() as session:
        other = session.scalar(
            select(Adjudication.id)
            .join(ReviewUnit, ReviewUnit.id == Adjudication.review_unit_id)
            .join(ReviewSubject, ReviewSubject.id == ReviewUnit.review_subject_id)
            .where(ReviewSubject.source_snapshot_id != uuid.UUID(saved_snapshot))
        )
    assert other is not None, "Regression fixture needs distinct field snapshots"
    endpoint = path.rsplit("/", 1)[0] + f"/{other}/proposal-items"
    view = (await clients[0].get(endpoint)).json()
    assert view["source_snapshot_id"] != saved_snapshot
    assert saved_snapshot in view["source_snapshot_ids"]
    item = view["items"][0]
    assert all(
        span["source_version"] == view["source_version"]
        for p in item["proposals"]
        for span in p["provenance"]
    )
    response = await clients[0].put(
        endpoint + "/" + item["id"],
        json={
            "expected_version": 1,
            "submit": True,
            "decision": {
                "outcome": "reviewer_preferred",
                "preferred_proposal_id": item["proposals"][0]["id"],
            },
        },
        headers=headers(csrf[0]),
    )
    assert response.status_code == 200, response.text
    final = response.json()["items"][0]
    assert final["final_provenance"][0]["source_snapshot_id"] == saved_snapshot
