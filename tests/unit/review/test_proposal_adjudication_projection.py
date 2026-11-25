"""Private target presentation retains proposal identities and distinct reviewer counts."""

import uuid
from datetime import UTC, datetime

import pytest

from review_platform.common.errors import APIError
from review_platform.db.models import User
from review_platform.review.models.proposal_adjudication import ProposalAdjudicationItem
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.proposal_adjudication_read import project_proposal_item
from review_platform.review.proposal_adjudication_store import editable_item

pytestmark = pytest.mark.no_db


def test_multiple_proposals_from_one_author_keep_exact_ids_and_numbering():
    author = uuid.uuid4()
    tenant = uuid.uuid4()
    campaign = uuid.uuid4()
    time = datetime(2026, 9, 15, tzinfo=UTC)
    proposals = [
        ReviewerAddedProposal(
            id=uuid.UUID(int=n),
            tenant_id=tenant,
            campaign_id=campaign,
            reviewer_id=author,
            case_id="case",
            group_id="cited_cases",
            value_schema="cited_case_text/v1",
            original_value=f"Original {n}",
            value=f"Value {n}",
            note=f"Note {n}",
            provenance_json=[
                {
                    "source_snapshot_id": str(uuid.UUID(int=9)),
                    "source_version": "a" * 64,
                    "char_start": 0,
                    "char_end": 5,
                }
            ],
            state="submitted",
            lock_version=2,
            created_at=time,
            submitted_at=time,
        )
        for n in (2, 1)
    ]
    item = ProposalAdjudicationItem(
        id=uuid.uuid4(),
        group_id="cited_cases",
        origin="automatic",
        state="pending",
        proposal_ids_json=[str(p.id) for p in proposals],
        lock_version=1,
    )
    view = project_proposal_item(
        item,
        {str(p.id): p for p in proposals},
        {
            author: User(id=author, display_name="Reviewer A", email_normalized="a@example.test"),
        },
    )
    assert view.reviewer_count == 1
    assert view.different_values
    assert view.matching_reasons == ["complete_provenance"]
    assert [(p.id.int, p.proposal_number) for p in view.proposals] == [(1, 1), (2, 2)]
    assert view.proposals[1].note == "Note 2"
    assert view.proposals[1].original_value == "Original 2"


@pytest.mark.parametrize(
    "state,version,code",
    [
        ("submitted", 1, "proposal_adjudication_locked"),
        ("superseded", 1, "adjudication_membership_changed"),
        ("pending", 2, "precondition_failed"),
    ],
)
def test_editable_target_rejects_submitted_replaced_and_stale_items(state, version, code):
    item = ProposalAdjudicationItem(id=uuid.uuid4(), state=state, lock_version=1)
    with pytest.raises(APIError) as error:
        editable_item([item], item.id, version)
    assert error.value.code == code
