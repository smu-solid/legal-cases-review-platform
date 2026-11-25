"""Hard removal preserves submitted work and releases otherwise untouched campaigns."""

import uuid

import pytest
from sqlalchemy import select

from review_platform.review.models import IdempotencyRecord
from review_platform.review.models.proposals import ReviewerAddedProposal
from tests.support.clients import authenticate, mutation_headers
from tests.support.proposals import headers, proposal_workspace, valid_body

__all__ = ["proposal_workspace"]


@pytest.mark.anyio
@pytest.mark.parametrize("group", ["cited_cases", "statutes_cited"])
@pytest.mark.parametrize("saved", [False, True])
async def test_remove_deletes_row_and_draft_cache_and_unblocks_campaign(
    proposal_workspace, database, admin, client, group, saved
):
    clients, tokens, bases, _, campaign_id = proposal_workspace
    reviewer, token, base = clients[0], tokens[0], bases[0]
    bundle = (await reviewer.get(base + "/grouped-bundle")).json()
    body = valid_body(bundle, group)
    pid = uuid.uuid4()
    path = base + f"/proposals/{pid}"
    draft_headers = headers(token)
    admin_token = await authenticate(client, admin)
    delete_path = (
        f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns/{campaign_id}?confirm=true"
    )
    if saved:
        assert (
            await reviewer.put(path + "/draft", json=body, headers=draft_headers)
        ).status_code == 200
        blocked = await client.delete(delete_path, headers=mutation_headers(admin_token))
        assert (
            blocked.status_code == 422 and blocked.json()["code"] == "campaign_delete_work_exists"
        )
        # A peer cannot remove another reviewer's draft.
        denied = await clients[1].put(
            bases[1] + f"/proposals/{pid}/removed", json=body, headers=headers(tokens[1], 2)
        )
        assert denied.status_code == 404
        stale = await reviewer.put(path + "/removed", json=body, headers=headers(token))
        assert stale.status_code == 412
    removed = await reviewer.put(
        path + "/removed", json=body, headers=headers(token, 2 if saved else 1)
    )
    assert removed.status_code == 200, removed.text
    again = await reviewer.put(
        path + "/removed", json=body, headers=headers(token, 2 if saved else 1)
    )
    assert again.json() == removed.json()
    with database.session() as session:
        assert session.get(ReviewerAddedProposal, pid) is None
        records = session.scalars(
            select(IdempotencyRecord).where(
                IdempotencyRecord.operation.like(f"review.proposal.{pid}.%")
            )
        ).all()
        assert len(records) == 1
        assert records[0].response_json["value"] == ""
        assert records[0].response_json["provenance"] == []
    replay = await reviewer.put(path + "/draft", json=body, headers=draft_headers)
    assert replay.status_code == 409  # A delayed save cannot resurrect the deleted proposal.
    reloaded = (await reviewer.get(base + "/grouped-bundle")).json()
    assert not reloaded["reviewer_additions"]
    queue = await reviewer.get(base.split("/assignments/")[0] + f"/campaigns/{campaign_id}/cases")
    assert queue.json()["items"][0]["status"] == "not_started"
    deleted = await client.delete(delete_path, headers=mutation_headers(admin_token))
    assert deleted.status_code == 200, deleted.text


@pytest.mark.anyio
@pytest.mark.parametrize("group", ["cited_cases", "statutes_cited"])
async def test_submitted_additions_cannot_be_removed(proposal_workspace, database, group):
    clients, tokens, bases, *_ = proposal_workspace
    reviewer, token, base = clients[0], tokens[0], bases[0]
    body = valid_body((await reviewer.get(base + "/grouped-bundle")).json(), group)
    pid = uuid.uuid4()
    path = base + f"/proposals/{pid}"
    submitted = await reviewer.put(path + "/submitted", json=body, headers=headers(token))
    assert submitted.status_code == 200, submitted.text
    removed = await reviewer.put(path + "/removed", json=body, headers=headers(token, 2))
    assert removed.status_code == 409
    with database.session() as session:
        assert session.get(ReviewerAddedProposal, pid).state == "submitted"


@pytest.mark.anyio
async def test_legacy_removed_proposal_does_not_block_campaign_delete(
    proposal_workspace, database, admin, client
):
    clients, tokens, bases, _, campaign_id = proposal_workspace
    body = valid_body((await clients[0].get(bases[0] + "/grouped-bundle")).json())
    pid = uuid.uuid4()
    saved = await clients[0].put(
        bases[0] + f"/proposals/{pid}/draft", json=body, headers=headers(tokens[0])
    )
    assert saved.status_code == 200
    with database.session() as session, session.begin():
        session.get(ReviewerAddedProposal, pid).state = "removed"
    token = await authenticate(client, admin)
    deleted = await client.delete(
        f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns/{campaign_id}?confirm=true",
        headers=mutation_headers(token),
    )
    assert deleted.status_code == 200, deleted.text
    with database.session() as session:
        assert session.get(ReviewerAddedProposal, pid) is None
