"""Citation uniqueness is deliberately stricter than adjudication grouping."""

import uuid

import pytest

from review_platform.common.errors import APIError
from review_platform.review.citation_duplicates import (
    CitationItem,
    check_duplicates,
    classify,
    require_no_duplicates,
)

pytestmark = pytest.mark.no_db


def item(value, start=0, end=10, **kw):
    return CitationItem(uuid.uuid4(), value, spans={("document", "version", start, end)}, **kw)


@pytest.mark.parametrize(
    "left,right,start,end,duplicate",
    [
        (" [2002]   SGCA 39 ", "[2002] sgca 39", 0, 10, True),
        ("A", "A", 30, 40, False),
        ("A", "A", 5, 15, False),
        ("A", "B", 0, 10, False),
        ("Case-A", "Case A", 0, 10, False),
        ("Guobena [2002] SGCA 39", "[2002] SGCA 39", 0, 10, False),
    ],
)
def test_only_normalized_value_and_complete_provenance_match(left, right, start, end, duplicate):
    result = classify(item(left), item(right, start, end))
    assert (result is not None) == duplicate


def test_complete_span_set_required():
    a, b = item("A"), item("A")
    b.spans.add(("document", "version", 20, 30))
    assert classify(a, b) is None
    a.spans.add(("document", "version", 20, 30))
    assert classify(a, b)[0] == "confirmed"
    a.spans = b.spans = set()
    assert classify(a, b) is None


def test_version_and_document_isolation():
    a, b = item("A"), item("A")
    b.spans = {("other", "version", 0, 10)}
    assert classify(a, b) is None
    b.spans = {("document", "other-version", 0, 10)}
    assert classify(a, b) is None


def test_identity_and_incomplete_correction_do_not_block():
    assert classify(item("Neutral", identity="case-1"), item("Reporter", identity="case-1")) is None
    assert classify(item("A"), item("A", incomplete=True)) is None


def test_self_exclusion_and_duplicate_rejection():
    a, b = item("A"), item("A")
    assert not check_duplicates(a, [a]).conflicts
    confirmed = check_duplicates(a, [b])
    with pytest.raises(APIError, match="already exist"):
        require_no_duplicates(confirmed)


@pytest.mark.parametrize("field", ["value", "provenance"])
def test_added_citation_contains_complete_normalized_existing_value(field):
    full = "Calico Printers’ Association Ltd v Barclays Bank (1931) 145 LT 51 (CA)"
    addition = item(
        full if field == "value" else "Different proposed value",
        reviewer_added=True,
        provenance_text=(full,) if field == "provenance" else (),
    )
    existing = item("  (1931)  145 lt\n51 (ca)  ", 30, 40)
    assert classify(addition, existing)[0] == "confirmed"
    assert classify(existing, addition)[0] == "confirmed"
    addition.spans = existing.spans = set()
    assert classify(addition, existing)[0] == "confirmed"


def test_substring_uses_existing_aliases_and_preserves_punctuation_and_numbers():
    existing = item("Case name · (1931) 145 LT 51 (CA)", aliases={"(1931) 145 LT 51 (CA)"})
    assert classify(item("Full name (1931) 145 LT 51 (CA)", reviewer_added=True), existing)
    assert classify(item("(1931) 145 LT", reviewer_added=True), existing)
    for value in ("(1931) 145 LT 52 (CA)", "1931 145 LT 51 CA", " "):
        assert classify(item(value, reviewer_added=True), existing) is None
    assert classify(item("A", reviewer_added=True), item(" ")) is None


def test_marked_provenance_is_read_from_verified_source_using_utf16_offsets():
    from review_platform.review.citation_inventory import proposed_item
    from review_platform.review.proposal_validation import source_version
    from review_platform.review.schemas.grouped_bundle import ReviewerGroupingBundle, SourceRender
    from review_platform.review.schemas.proposals import ProposalInput, ProposalSpan

    sid, sibling = uuid.uuid4(), uuid.uuid4()
    content = "😀 Prefix (1931) 145 LT 51 (CA) suffix"
    version = source_version(content)
    bundle = ReviewerGroupingBundle.model_construct(
        field_groups=[],
        proposal_source_snapshot_ids=[sibling],
        source_render=SourceRender(
            source_snapshot_id=sid, content=content, anchors=[], render_mode="safe_text"
        ),
    )
    span = ProposalSpan(
        source_snapshot_id=sibling, source_version=version, char_start=10, char_end=31
    )
    body = ProposalInput(group_id="cited_cases", value="Different value", provenance=[span])
    added = proposed_item(bundle, uuid.uuid4(), body)
    assert added.provenance_text == ("(1931) 145 LT 51 (CA)",)
    assert classify(added, item("(1931) 145 LT 51 (CA)"))
    for patch in (
        {"source_snapshot_id": uuid.uuid4()},
        {"source_version": "0" * 64},
        {"char_end": 9999},
        {"char_start": 0, "char_end": 1},
    ):
        body.provenance = [span.model_copy(update=patch)]
        assert proposed_item(bundle, uuid.uuid4(), body).provenance_text == ()


def test_imported_aliases_resolve_identity_without_equating_unresolved_names():
    from review_platform.review.citation_inventory import citation_inventory, proposed_item
    from review_platform.review.schemas.grouped_bundle import (
        FieldGroup,
        GroupItem,
        ItemAnswerSummary,
        ReviewerGroupingBundle,
        SourceRender,
    )
    from review_platform.review.schemas.proposals import ProposalInput

    original = GroupItem.model_construct(
        review_unit_id=uuid.uuid4(),
        extraction_state="present",
        status="draft",
        extracted_value_display="Neutral citation · Full case name · Reporter citation",
        extracted_value_raw={
            "to_case_id_int": "CASE-42",
            "resolved_citation_neutral": "Neutral citation",
            "resolved_citation_reporter": "Reporter citation",
            "resolved_title": "Full case name",
        },
        answer_summary=ItemAnswerSummary(
            state="draft",
            value_correct=False,
            provenance_correct=True,
            corrected_value_display="A different corrected case",
        ),
    )
    bundle = ReviewerGroupingBundle.model_construct(
        field_groups=[FieldGroup.model_construct(group_id="cited_cases", items=[original])],
        source_render=SourceRender.model_construct(source_snapshot_id=uuid.uuid4()),
    )
    a = proposed_item(
        bundle, uuid.uuid4(), ProposalInput(group_id="cited_cases", value="Neutral citation")
    )
    b = proposed_item(
        bundle, uuid.uuid4(), ProposalInput(group_id="cited_cases", value="Reporter citation")
    )
    assert a.identity == b.identity == "CASE-42"
    assert classify(a, b) is None
    assert classify(a, citation_inventory(bundle)[0]) is not None  # original remains checked
    unresolved = proposed_item(
        bundle, uuid.uuid4(), ProposalInput(group_id="cited_cases", value="Full case name")
    )
    assert unresolved.identity is None
    assert classify(unresolved, a) is None


def test_context_rejects_wrong_version_and_exposes_all_original_windows():
    from types import SimpleNamespace

    from review_platform.review.reviewer_provenance_context import _item_context
    from review_platform.review.schemas.grouped_bundle import (
        GroupItem,
        ItemAnswerSummary,
        ReviewerGroupingBundle,
        SourceRender,
    )
    from review_platform.review.schemas.submissions import CorrectedProvenanceSpan

    sid, eid, iid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    version = "a" * 64
    summary = ItemAnswerSummary(
        state="draft",
        value_correct=False,
        provenance_correct=False,
        corrected_value_display="Correction",
        corrected_provenance_spans=[
            CorrectedProvenanceSpan(
                evidence_window_id=eid,
                char_start=4,
                char_end=8,
                source_snapshot_id=sid,
                source_version="b" * 64,
            )
        ],
    )
    original = GroupItem.model_construct(
        review_unit_id=iid,
        answer_summary=summary,
        extracted_value_display="Original",
        source_anchor_id=None,
    )
    bundle = ReviewerGroupingBundle.model_construct(
        proposal_source_version=version,
        source_render=SourceRender(
            source_snapshot_id=sid,
            render_mode="safe_text",
            content="some evidence in the source",
            anchors=[],
        ),
    )
    windows = [
        SimpleNamespace(id=eid, anchor_status="anchored", char_start=0, char_end=3),
        SimpleNamespace(id=uuid.uuid4(), anchor_status="anchored", char_start=10, char_end=14),
        SimpleNamespace(
            id=uuid.uuid4(), anchor_status="other_document", char_start=14, char_end=18
        ),
    ]
    _item_context(
        bundle,
        original,
        "cited_cases",
        SimpleNamespace(source_snapshot_id=sid),
        windows,
        {sid},
        True,
    )
    assert len(bundle.provenance_context) == 2
    assert all(c.kind == "Extracted" and c.superseded for c in bundle.provenance_context)
