"""Shared HTTP workflow scenario support."""

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select

from review_platform.review.models import Adjudication
from tests.support.campaigns import add_review_user
from tests.support.clients import authenticate, open_clients
from tests.support.proposals import headers, proposal_workspace, valid_body


@pytest.fixture
async def adjudication_proposals(proposal_workspace, database, settings, admin, request):
    reviewers, tokens, bases, assignments, campaign = proposal_workspace
    adjudicators = [
        add_review_user(
            database, settings, admin, email=f"adj-proposal-{n}@example.test", role="adjudicator"
        )
        for n in range(2)
    ]
    bundle = (await reviewers[0].get(bases[0] + "/grouped-bundle")).json()
    for n, reviewer in enumerate(reviewers):
        body = valid_body(bundle)
        body["value"] = "Same citation"
        count = (2 if n == 0 else 0) if getattr(request, "param", None) == "single_author" else 1
        for proposal_number in range(count):
            proposal_id = uuid.uuid4()
            if proposal_number:
                # Distinct citations in one passage remain valid ambiguous proposals.
                body["value"] = "Another citation"
                checked = await reviewer.post(
                    bases[n] + f"/proposals/{proposal_id}/duplicate-check",
                    json=body,
                    headers=headers(tokens[n]),
                )
                body["duplicate_acknowledgement"] = {
                    "fingerprint": checked.json()["fingerprint"],
                    "reason": "The passage contains two different citations",
                }
            response = await reviewer.put(
                bases[n] + f"/proposals/{proposal_id}/submitted",
                json=body,
                headers=headers(tokens[n]),
            )
            assert response.status_code == 200, response.text
        for aid in assignments[n]:
            response = await reviewer.post(
                bases[n].rsplit("/", 1)[0] + f"/{aid}/answer/submit",
                json={"value_correct": True, "provenance_correct": True},
                headers=headers(tokens[n]),
            )
            assert response.status_code == 201, response.text
    with database.session() as session:
        anchor = session.scalar(select(Adjudication.id))
    path = f"/api/v1/tenants/{admin.tenant_id}/review/adjudications/{anchor}"
    async with AsyncExitStack() as stack:
        clients = await open_clients(stack, settings, 2)
        csrf = [await authenticate(c, u) for c, u in zip(clients, adjudicators, strict=True)]
        # Field reviews alone must not reveal additions.
        hidden = await clients[0].get(path + "/proposal-items")
        assert hidden.status_code == 200, hidden.text
        assert hidden.json()["items"] == []
        for n, reviewer in enumerate(reviewers):
            response = await reviewer.post(bases[n] + "/case-submit", headers=headers(tokens[n]))
            assert response.status_code == 201, response.text
            if n < len(reviewers) - 1:
                hidden = (await clients[0].get(path + "/proposal-items")).json()
                assert not hidden["ready"] and not hidden["items"]
        yield clients, csrf, path, reviewers, tokens, bases


__all__ = ["proposal_workspace"]
