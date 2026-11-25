from __future__ import annotations

import pytest

from review_platform.review.grouping import (
    DEFAULT_ATOMIC_GROUP_ID,
    GROUP_BY_ID,
    UnknownReviewFieldError,
    classify_unit,
    display_field_label,
    field_token,
    require_atomic_group,
)


def test_classify_unit_covers_every_branch() -> None:
    # Explicit field-token mappings (atomic).
    assert classify_unit("metadata_field", "Subject").group_id == "case_metadata"
    assert classify_unit("metadata_field", "Court Id").group_id == "court_and_hearing"
    assert classify_unit("metadata_field", "Lawyers Pf").group_id == "parties_and_representation"
    # Citation link review-kind (a synthetic-fixture-only kind) routes into case_metadata, same as
    # every other citation field -- there is no dedicated "citations" group (see grouping.py).
    citations = classify_unit("citation_link", "Citation Neutral")
    assert citations.group_id == "case_metadata" and citations.group_kind == "atomic"
    # Non-atomic relation review-kinds.
    cited = classify_unit("cited_case", "Cited Case 17")
    assert cited.group_id == "cited_cases" and cited.group_kind == "non_atomic"
    assert classify_unit("statute_reference", "x").group_id == "statutes_cited"
    assert classify_unit("appeal_relation", "x").group_id == "appeal_relations"
    # Unknown atomic field falls through to the documented default, never raises.
    fallback = classify_unit("metadata_field", "Some Unmapped Thing")
    assert fallback.group_id == DEFAULT_ATOMIC_GROUP_ID and fallback.group_kind == "atomic"
    assert field_token("Citation Neutral") == "citation_neutral"


def test_classify_unit_prefers_stable_field_name_over_display_label() -> None:
    # Grouping keys off the stable field_name, so a renamed display label cannot regroup the field.
    renamed = classify_unit("metadata_field", "Totally Renamed Label", "cases.citation_neutral")
    assert renamed.group_id == "case_metadata"
    # Without a field_name, the legacy display-label token is the fallback.
    assert classify_unit("metadata_field", "Citation Neutral").group_id == "case_metadata"


def test_neutral_and_reported_citation_are_case_metadata_not_a_dedicated_citations_group() -> None:
    """Test neutral and reported citation are case metadata not a dedicated citations group."""

    assert (
        classify_unit("metadata_field", "Neutral Citation", "cases.citation_neutral").group_id
        == "case_metadata"
    )
    assert (
        classify_unit("metadata_field", "Reported Citation", "cases.citation_reporter").group_id
        == "case_metadata"
    )
    assert require_atomic_group("cases.citation_neutral").group_id == "case_metadata"
    assert require_atomic_group("cases.citation_reporter").group_id == "case_metadata"
    assert "citations" not in GROUP_BY_ID


def test_suit_num_is_case_metadata_not_the_additional_fields_catch_all() -> None:
    # suit_num used to fall through to additional_fields; it is now case-identity metadata.
    assert classify_unit("metadata_field", "Suit Num", "cases.suit_num").group_id == "case_metadata"
    assert require_atomic_group("cases.suit_num").group_id == "case_metadata"


def test_require_atomic_group_rejects_an_unmapped_column() -> None:
    with pytest.raises(UnknownReviewFieldError):
        require_atomic_group("cases.some_new_unmapped_column")


def test_display_field_label_maps_real_columns_but_leaves_others_untouched() -> None:
    # Real-imported unit: the raw column name is replaced by a reviewer-friendly label.
    assert display_field_label("cases.title_raw", "Title Raw") == "Case title"
    assert display_field_label("cases.j_date", "J Date") == "Judgment date"
    # No field_name (relation unit, synthetic fixture, or legacy row): stored label is kept as-is.
    assert display_field_label(None, "Cited case · [2018] SGHC 1") == "Cited case · [2018] SGHC 1"
    # Unmapped column falls back to the stored label rather than guessing.
    assert display_field_label("cases.brand_new_column", "Brand New Column") == "Brand New Column"


pytestmark = pytest.mark.no_db
