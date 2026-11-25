"""Evidence windows name the document they were taken from, and other-document evidence is not
reported as an unresolved anchor."""

from __future__ import annotations

import uuid

import pytest

from review_platform.review.grouped_source_text import unanchored_reason
from review_platform.review.models import EvidenceWindow
from review_platform.review.projections import evidence_response, grounded_in_index
from review_platform.review.schemas import GroundedIn

PRIMARY = "a" * 64
OTHER = "b" * 64


def _window(sha: str, status: str | None, *, char_start: int | None = None) -> EvidenceWindow:
    return EvidenceWindow(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        review_unit_id=uuid.uuid4(),
        ordinal=0,
        kind="dom",
        snippet="[2016] SGHC 100",
        line_start=None,
        line_end=None,
        char_start=char_start,
        char_end=None if char_start is None else char_start + 15,
        source_sha256=sha,
        anchor_status=status,
    )


RELATION_SUBJECT = {
    "source_sha256": PRIMARY,
    "snapshot_local_case_external_id": "CAS-000002",
    "relation_sources": [
        {
            "relation_external_id": "RCA-1",
            "case_external_id": "CAS-000002",
            "source_system": "sample_a",
            "source_document_sha256": PRIMARY,
        },
        {
            "relation_external_id": "RCA-1",
            "case_external_id": "CAS-000001",
            "source_system": "sample_b",
            "source_document_sha256": OTHER,
        },
    ],
}

FIELD_SUBJECT = {
    "source_sha256": PRIMARY,
    "field_name": "citation_neutral",
    "member_values": [
        {
            "case": "CAS-000002",
            "source_system": "sample_a",
            "value": "[2019] SGCA 1",
            "source_sha256": PRIMARY,
        },
        {
            "case": "CAS-000009",
            "source_system": "sample_b",
            "value": "[2019] SGCA 1",
            "source_sha256": OTHER,
        },
    ],
}


def test_relation_evidence_names_the_member_document_it_came_from() -> None:
    response = evidence_response(_window(OTHER, "other_document"), RELATION_SUBJECT)
    assert response.anchor_status == "other_document"
    assert response.grounded_in is not None
    assert response.grounded_in.model_dump() == {
        "source_sha256": OTHER,
        "source_system": "sample_b",
        "citation": None,
    }
    assert "CAS-" not in response.model_dump_json(), (
        "internal case identifiers never reach the reviewer payload"
    )


def test_field_evidence_carries_the_member_citation_when_the_field_is_the_citation() -> None:
    response = evidence_response(_window(OTHER, "anchored", char_start=10), FIELD_SUBJECT)
    assert response.grounded_in is not None
    assert response.grounded_in.source_system == "sample_b"
    assert response.grounded_in.citation == "[2019] SGCA 1"


def test_unknown_document_is_still_named_by_hash_only_and_never_invented() -> None:
    response = evidence_response(_window("c" * 64, "anchored", char_start=3), RELATION_SUBJECT)
    assert response.grounded_in is not None
    assert response.grounded_in.model_dump() == {
        "source_sha256": "c" * 64,
        "source_system": None,
        "citation": None,
    }


def test_without_subject_attributes_the_response_is_unchanged_but_for_anchor_status() -> None:
    response = evidence_response(_window(PRIMARY, None))
    assert response.grounded_in is None and response.anchor_status is None
    assert grounded_in_index(None) == {}


def test_primary_document_resolves_from_the_subject_itself() -> None:
    index = grounded_in_index(
        {"source_sha256": PRIMARY, "snapshot_local_case_external_id": "CAS-000002"}
    )
    assert index[PRIMARY] == GroundedIn(source_sha256=PRIMARY)
    assert "CAS-000002" not in index[PRIMARY].model_dump_json()


def test_other_document_evidence_is_not_called_unresolved() -> None:
    assert unanchored_reason([_window(OTHER, "other_document")]) == "other_document"
    assert (
        unanchored_reason(
            [_window(OTHER, "other_document"), _window(PRIMARY, "expected_unanchored")]
        )
        == "other_document"
    )


def test_genuinely_unresolved_or_legacy_windows_keep_the_unresolved_reason() -> None:
    assert unanchored_reason([_window(PRIMARY, "unexpected_unresolved")]) == "anchor_unresolved"
    assert unanchored_reason([_window(PRIMARY, None)]) == "anchor_unresolved"
    assert (
        unanchored_reason(
            [_window(OTHER, "other_document"), _window(PRIMARY, "unexpected_unresolved")]
        )
        == "anchor_unresolved"
    )


pytestmark = pytest.mark.no_db
