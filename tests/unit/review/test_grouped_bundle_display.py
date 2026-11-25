from __future__ import annotations

import uuid

import pytest

from review_platform.review.case_display import case_display
from review_platform.review.models import Candidate, ReviewSubject, ReviewUnit
from review_platform.review.relation_display import extracted_value, is_title_field


def _candidate(value: object) -> Candidate:
    return Candidate(label="A", source_kind="deterministic", verdict="supported", value_json=value)


def test_cited_case_relation_shows_external_citation_not_raw_json() -> None:
    value = {"to_case_ext": "[2020] SGHC 100", "to_case_id_int": 4821}
    display, raw = extracted_value(_candidate(value), fallback="fallback", review_kind="cited_case")
    assert display == "[2020] SGHC 100"
    assert raw == value


def test_cited_case_relation_degrades_to_unknown_id_when_no_external_citation() -> None:
    value = {"to_case_ext": None, "to_case_id_int": 4821}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="cited_case"
    )
    assert display == "Unknown cited case #4821"


def test_cited_case_relation_falls_back_to_caller_fallback_when_nothing_usable() -> None:
    value = {"to_case_ext": None, "to_case_id_int": None}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="cited_case"
    )
    assert display == "fallback"


def test_statute_relation_composes_act_and_section() -> None:
    value = {"to_statute_ext": "Companies Act", "section_cited": "216", "to_statute_id_int": 12}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="statute_reference"
    )
    assert display == "Companies Act · s 216"


def test_statute_relation_omits_missing_section() -> None:
    value = {"to_statute_ext": "Civil Law Act", "section_cited": None, "to_statute_id_int": 12}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="statute_reference"
    )
    assert display == "Civil Law Act"


def test_appeal_relation_shows_associated_citation() -> None:
    value = {"associated_citation": "[2021] SGCA 5", "higher_case_id": 99}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="appeal_relation"
    )
    assert display == "[2021] SGCA 5"


def test_metadata_field_value_is_unaffected_by_relation_formatting() -> None:
    display, raw = extracted_value(_candidate("Plain text value"), fallback="fallback")
    assert display == "Plain text value"
    assert raw == "Plain text value"


def test_cited_case_relation_prefers_resolved_case_citation_and_title() -> None:
    value = {
        "to_case_ext": None,
        "to_case_id_int": "CAS-001010",
        "resolved_citation_neutral": "[2013] SGCA 42",
        "resolved_title": "Sembcorp Marine Ltd v PPL Holdings Pte Ltd",
        "resolved_citation_reporter": "[2013] 4 rep 193",
    }
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="cited_case"
    )
    assert display == (
        "[2013] SGCA 42 · Sembcorp Marine Ltd v PPL Holdings Pte Ltd · [2013] 4 rep 193"
    )


def test_cited_case_relation_omits_missing_resolved_parts() -> None:
    value = {"to_case_id_int": "CAS-1", "resolved_citation_neutral": "[2013] SGCA 42"}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="cited_case"
    )
    assert display == "[2013] SGCA 42"


def test_appeal_relation_read_from_higher_end_degrades_to_lower_case_id() -> None:
    # The appellate case's appeal unit carries lower_case_id, not higher_case_id.
    value = {"associated_citation": None, "lower_case_id": "CAS-000042"}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="appeal_relation"
    )
    assert display == "Unknown appeal #CAS-000042"


def test_appeal_relation_prefers_resolved_counterpart_case() -> None:
    value = {
        "associated_citation": "[2019] SGCA 1",
        "lower_case_id": "CAS-000042",
        "resolved_citation_neutral": "[2016] SGHC 210",
        "resolved_title": "Lim v Tan",
    }
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="appeal_relation"
    )
    assert display == "[2016] SGHC 210 · Lim v Tan"


def test_statute_relation_does_not_double_an_existing_section_marker() -> None:
    value = {"to_statute_ext": "Companies Act (Cap 50)", "section_cited": "ss 344 (5) , 344A"}
    display, _raw = extracted_value(
        _candidate(value), fallback="fallback", review_kind="statute_reference"
    )
    assert display == "Companies Act (Cap 50) · ss 344 (5) , 344A"


@pytest.mark.parametrize(
    ("field_name", "label", "expected"),
    [
        ("cases.title_raw", "Case title", True),
        ("cases.title_raw", "Renamed title label", True),
        ("cases.subject", "Subject matter", False),
        ("cases.subject", "Title raw", False),
        (None, "Title raw", True),
        (None, "Subject", False),
        (None, "Subject matter", False),
    ],
)
def test_title_detection_distinguishes_title_from_subject(
    field_name: str | None, label: str, expected: bool
) -> None:
    assert is_title_field(field_name, label) is expected


@pytest.mark.parametrize("subject_first", [True, False])
def test_case_heading_uses_title_regardless_of_subject_order(subject_first: bool) -> None:
    title_row = (
        ReviewUnit(id=uuid.uuid4(), field_name="cases.title_raw", safe_field_label="Case title"),
        ReviewSubject(display_title="Example Trading v Sample Services"),
    )
    subject_row = (
        ReviewUnit(id=uuid.uuid4(), field_name="cases.subject", safe_field_label="Subject matter"),
        ReviewSubject(display_title="Contract and delivery"),
    )
    rows = [subject_row, title_row] if subject_first else [title_row, subject_row]
    heading = case_display(rows, candidates_by_unit={})
    assert heading.case_title == "Example Trading v Sample Services"


pytestmark = pytest.mark.no_db
