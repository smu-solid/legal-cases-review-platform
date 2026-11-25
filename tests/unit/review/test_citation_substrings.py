"""Reviewer-added citations must be compared by value regardless of their marked location."""

import uuid

import pytest

from review_platform.review.citation_duplicates import (
    CitationItem,
    _normalize_duplicate_value,
    classify,
)
from review_platform.review.citation_inventory import citation_inventory
from review_platform.review.schemas.grouped_bundle import (
    FieldGroup,
    GroupItem,
    ItemAnswerSummary,
    ReviewerGroupingBundle,
    SourceRender,
)

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize("existing_added", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("field", ["value", "provenance"])
def test_substrings_in_either_direction_ignore_marked_location(existing_added, reverse, field):
    short = "(1861) 2 J & H 139"
    long = "Dent v Turpin (1861) 2 J & H 139"
    entered, saved = (short, long) if reverse else (long, short)
    current = CitationItem(
        uuid.uuid4(),
        entered if field == "value" else "Unrelated proposed authority",
        reviewer_added=True,
        provenance_text=(entered,) if field == "provenance" else (),
        spans={("source", "version", 100, 140)},
    )
    existing = CitationItem(
        uuid.uuid4(),
        saved.upper().replace(" ", "  \n"),
        reviewer_added=existing_added,
        spans={("source", "version", 200, 220)},
    )
    assert classify(current, existing) is not None


@pytest.mark.parametrize("citation", ["[1988] 1 rep(R) 349", "[1988] rep 424"])
def test_each_parallel_report_is_checked_even_when_case_names_differ(citation):
    existing = CitationItem(
        uuid.uuid4(),
        "[1988] SGHC 37 · Tham Wing Fai Peter v Public Prosecutor · "
        "[1988] 1 rep(R) 349; [1988] rep 424",
        aliases={
            "[1988] SGHC 37",
            "Tham Wing Fai Peter v Public Prosecutor",
            "[1988] 1 rep(R) 349; [1988] rep 424",
        },
    )
    current = CitationItem(
        uuid.uuid4(), f"Peter Tham Wing Fai v PP {citation}", reviewer_added=True
    )
    assert classify(current, existing) is not None


@pytest.mark.parametrize("replacement", [None, "A different corrected authority"])
@pytest.mark.parametrize("value", ["Farina v Silverlock (1856) 43 ER 1214", "(1856) 43 ER 1214"])
def test_original_extraction_is_checked_after_no_or_correction(replacement, value):
    original = GroupItem.model_construct(
        review_unit_id=uuid.uuid4(),
        extracted_value_display="Farina v Silverlock · (1856) 43 ER 1214",
        extracted_value_raw={"to_case_ext": "(1856) 43 ER 1214"},
        status="draft",
        answer_summary=ItemAnswerSummary(
            state="draft",
            value_correct=False,
            provenance_correct=False,
            corrected_value_display=replacement,
            comment="Marked incorrect",
        ),
    )
    bundle = ReviewerGroupingBundle.model_construct(
        field_groups=[FieldGroup.model_construct(group_id="cited_cases", items=[original])],
        source_render=SourceRender.model_construct(source_snapshot_id=uuid.uuid4()),
    )
    existing = citation_inventory(bundle)[0]
    current = CitationItem(uuid.uuid4(), value, reviewer_added=True)
    assert classify(current, existing) is not None
    if replacement:
        corrected = CitationItem(uuid.uuid4(), replacement, reviewer_added=True)
        assert classify(corrected, existing) is not None


def test_blank_drafts_and_different_citations_do_not_match():
    current = CitationItem(uuid.uuid4(), "[1988] rep 425", reviewer_added=True)
    for existing in (
        CitationItem(uuid.uuid4(), "[1988] rep 424", reviewer_added=True),
        CitationItem(uuid.uuid4(), "  ", reviewer_added=True),
        CitationItem(uuid.uuid4(), ""),
    ):
        assert classify(current, existing) is None


@pytest.mark.parametrize("existing_added", [False, True])
def test_trailing_full_stop_matches_existing_value(existing_added):
    existing = CitationItem(
        uuid.uuid4(),
        "ICC Publication 254 (“URCCP”) and the exclusion clause (supra)",
        reviewer_added=existing_added,
    )
    current = CitationItem(uuid.uuid4(), "the exclusion clause (supra).", reviewer_added=True)
    assert classify(current, existing) is not None


def test_boundary_full_stops_and_commas_are_ignored_in_both_values_and_marked_text():
    existing = CitationItem(
        uuid.uuid4(), ".,Dent v Turpin (1861) 2 J & H 139,.", reviewer_added=True
    )
    entered = " . , (1861) 2 J & H 139,. "
    for field in ("value", "provenance"):
        current = CitationItem(
            uuid.uuid4(),
            entered if field == "value" else "Unrelated authority",
            reviewer_added=True,
            provenance_text=(entered,) if field == "provenance" else (),
        )
        assert classify(current, existing) is not None


@pytest.mark.parametrize("value", ["Case A", " . , . "])
def test_boundary_normalization_preserves_internal_punctuation_and_ignores_empty_text(value):
    existing = CitationItem(uuid.uuid4(), "Case-A", reviewer_added=True)
    current = CitationItem(uuid.uuid4(), value, reviewer_added=True, provenance_text=("“...”",))
    assert classify(current, existing) is None


def test_boundary_brackets_quotes_and_other_punctuation_are_preserved():
    for value in (
        "[1988] rep 424",
        "(case)",
        "{case}",
        "'case'",
        "“case.”",
        "-case-",
        "_case_",
        "/case/",
        "case;",
        "case!",
        "case?",
        "case:",
    ):
        assert _normalize_duplicate_value(value) == value
