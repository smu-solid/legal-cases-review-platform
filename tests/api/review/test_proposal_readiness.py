"""N distinct case confirmations gate additions; field readiness remains independent."""

import uuid

import pytest
from sqlalchemy import select

from review_platform.review.models import Adjudication, Campaign, ReviewSubject
from review_platform.review.proposal_readiness import (
    adjudicable_case_proposals,
    case_proposals_ready,
)
from tests.support.proposals import headers, proposal_workspace, valid_body

__all__ = ["proposal_workspace"]


@pytest.mark.anyio
@pytest.mark.parametrize("proposal_workspace", [2, 3], indirect=True)
async def test_additions_wait_for_required_distinct_case_submissions(proposal_workspace, database):
    clients, tokens, bases, assignments, campaign_id = proposal_workspace
    bundle = (await clients[0].get(bases[0] + "/grouped-bundle")).json()
    body = valid_body(bundle)
    pid = uuid.uuid4()
    response = await clients[0].put(
        bases[0] + f"/proposals/{pid}/submitted", json=body, headers=headers(tokens[0])
    )
    assert response.status_code == 200, response.text
    for n, client in enumerate(clients):
        for assignment_id in assignments[n]:
            path = bases[n].rsplit("/", 1)[0] + f"/{assignment_id}/answer/submit"
            response = await client.post(
                path,
                json={"value_correct": True, "provenance_correct": True},
                headers=headers(tokens[n]),
            )
            assert response.status_code == 201, response.text
    with database.session() as session:
        assert len(list(session.scalars(select(Adjudication)))) == len(assignments[0])
        campaign = session.get(Campaign, uuid.UUID(campaign_id))
        subject = session.get(ReviewSubject, uuid.UUID(bundle["case_header"]["subject_id"]))
        case_id = subject.attributes_json["snapshot_local_case_external_id"]
        assert not case_proposals_ready(session, campaign=campaign, case_id=case_id)
        assert adjudicable_case_proposals(session, campaign=campaign, case_id=case_id) == []
    for n, client in enumerate(clients):
        for _ in range(2):
            response = await client.post(bases[n] + "/case-submit", headers=headers(tokens[n]))
            assert response.status_code == 201, response.text
        with database.session() as session:
            campaign = session.get(Campaign, uuid.UUID(campaign_id))
            ready = n == len(clients) - 1
            assert case_proposals_ready(session, campaign=campaign, case_id=case_id) == ready
            proposals = adjudicable_case_proposals(session, campaign=campaign, case_id=case_id)
            assert [p.id for p in proposals] == ([pid] if ready else [])
