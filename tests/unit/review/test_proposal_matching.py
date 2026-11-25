"""Matching boundaries independent of storage and database ordering."""

import uuid
from dataclasses import replace
from itertools import permutations

import pytest

from review_platform.review.proposal_matching import (
    ProposalMatchInput,
    automatic_proposal_groups,
    matching_reasons,
    normalized_proposal_value,
)
from review_platform.review.schemas.proposals import ProposalSpan

pytestmark = pytest.mark.no_db


def proposal(number=1, value="Example [2020] 10", ranges=((0, 5),)):
    return ProposalMatchInput(
        id=uuid.UUID(int=number),
        tenant_id=uuid.UUID(int=100),
        campaign_id=uuid.UUID(int=101),
        case_id="case-1",
        group_id="cited_cases",
        value=value,
        provenance=tuple(
            ProposalSpan(
                source_snapshot_id=uuid.UUID(int=102),
                source_version="a" * 64,
                char_start=start,
                char_end=end,
            )
            for start, end in ranges
        ),
    )


@pytest.mark.parametrize(
    ("value", "ranges", "expected"),
    [
        ("Example [2020] 10", ((0, 5),), ("normalized_value", "complete_provenance")),
        ("Example [2020] 10", ((10, 15),), ("normalized_value",)),
        ("Different", ((0, 5),), ("complete_provenance",)),
        ("Different", ((10, 15),), ()),
    ],
)
def test_four_matching_combinations(value, ranges, expected):
    assert matching_reasons(proposal(), proposal(2, value, ranges)) == expected


def test_normalization_preserves_numbers_punctuation_and_names():
    assert normalized_proposal_value(" \tEXAMPLE\n [2020]   10 ") == "example [2020] 10"
    for value in ("Example [2021] 10", "Example (2020) 10", "[2020] 10", "Example [2020] 1"):
        assert not matching_reasons(proposal(), proposal(2, value, ((20, 25),)))


def test_complete_span_sets_ignore_order_but_not_partial_overlap_or_shared_subset():
    left = proposal(ranges=((0, 5), (10, 15)))
    assert matching_reasons(left, proposal(2, "Different", ((10, 15), (0, 5)))) == (
        "complete_provenance",
    )
    for ranges in (((0, 5),), ((0, 5), (10, 16)), ((1, 5), (10, 15)), ((20, 25), (30, 35))):
        assert not matching_reasons(left, proposal(2, "Different", ranges))


@pytest.mark.parametrize("field", ["source_snapshot_id", "source_version"])
def test_source_identity_and_version_must_match(field):
    right = proposal(2, "Different")
    changed = uuid.UUID(int=999) if field == "source_snapshot_id" else "b" * 64
    right = replace(right, provenance=(right.provenance[0].model_copy(update={field: changed}),))
    assert not matching_reasons(proposal(), right)


@pytest.mark.parametrize("field", ["tenant_id", "campaign_id", "case_id", "group_id"])
def test_scope_is_never_crossed(field):
    value = (
        uuid.UUID(int=999)
        if field.endswith("_id") and field not in {"case_id", "group_id"}
        else "other"
    )
    assert not matching_reasons(proposal(), replace(proposal(2), **{field: value}))


def test_nontransitive_bridge_is_deterministic_and_never_merges_incompatible_endpoints():
    a = proposal(1, "First", ((0, 5),))
    b = proposal(2, "First", ((10, 15),))
    c = proposal(3, "Third", ((10, 15),))
    for ordering in permutations([a, b, c]):
        assert [
            [p.id.int for p in group] for group in automatic_proposal_groups(list(ordering))
        ] == [[1, 2], [3]]


def test_single_proposal_is_retained_and_blank_data_does_not_match():
    assert automatic_proposal_groups([proposal()]) == [[proposal()]]
    assert not matching_reasons(proposal(value="", ranges=()), proposal(2, " ", ()))
