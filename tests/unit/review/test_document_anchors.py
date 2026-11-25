from __future__ import annotations

import pytest

from review_platform.review.source_render import build_anchor_map, folded_contains
from review_platform.review.source_render.anchor_map import _flexible_pattern

pytestmark = pytest.mark.no_db


@pytest.mark.parametrize(
    ("rendered", "snippet"),
    [
        # curly apostrophe/quote in provenance vs straight in render (and vice versa)
        ("the Magistrate's Appeals were heard", "the Magistrate’s Appeals"),
        ("he said “hello there” to us", 'said "hello there" to'),
        # en-dash / em-dash catchword separators vs hyphen
        ("Criminal Law - Statutory offences here", "Criminal Law – Statutory offences"),
        ("Contract — Frustration of purpose", "Contract - Frustration"),
        # whitespace runs (including the render collapsing a newline) stay flexible
        ("first line\n\nsecond clause follows", "first line second clause"),
    ],
)
def test_build_anchor_map_tolerates_typographic_variants(rendered: str, snippet: str) -> None:
    (hit,) = build_anchor_map(rendered, [snippet])
    assert hit.found
    assert rendered[hit.char_start : hit.char_end]  # offsets address the ORIGINAL rendered text


def test_build_anchor_map_reports_absent_snippet_as_not_found() -> None:
    (hit,) = build_anchor_map("only the body text is here", ["Legislation referred to: Penal Code"])
    assert not hit.found
    assert hit.char_start is None and hit.char_end is None


def test_build_anchor_map_matches_line_wrapped_citation() -> None:
    # A provenance snippet that wrapped across a source line break still matches the collapsed
    # render because whitespace next to punctuation is optional.
    rendered = "the court applied s 5(1)(a) of the Act in this case"
    (hit,) = build_anchor_map(rendered, ["s 5(1)(\na\n) of the Act"])
    assert hit.found
    assert rendered[hit.char_start : hit.char_end] == "s 5(1)(a) of the Act"


def test_build_anchor_map_does_not_merge_distinct_words() -> None:
    # Between two alphanumeric tokens whitespace stays required, so words never silently merge.
    (hit,) = build_anchor_map("the foobar baz", ["foo bar"])
    assert not hit.found


def test_build_anchor_map_matches_snippet_punctuation_spaced_in_render() -> None:
    # while the extracted field value has no space before the punctuation ("2016; Summonses").
    rendered = (
        "Case Number : Civil Appeals Nos 181 and 182 of 2016 ; Summonses Nos 45 and 46 of 2017"
    )
    (hit,) = build_anchor_map(
        rendered, ["Civil Appeals Nos 181 and 182 of 2016; Summonses Nos 45 and 46 of 2017"]
    )
    assert hit.found
    assert (
        rendered[hit.char_start : hit.char_end]
        == "Civil Appeals Nos 181 and 182 of 2016 ; Summonses Nos 45 and 46 of 2017"
    )


def test_folded_contains_treats_synthesised_join_as_not_a_body_quote() -> None:
    body = "coram Chao Hick Tin JA, L P Thean JA and Yong Pung How CJ heard the appeal"
    # A verbatim body phrase (modulo whitespace) -> present; a miss here would be a matcher fault.
    assert folded_contains(body, "L P Thean JA and Yong Pung How CJ") is True
    assert folded_contains(body, "Chao Hick Tin JA ; L P Thean JA ; Yong Pung How CJ") is False
    # Reference-table statute text is absent from the body -> expected null, not a matcher gap.
    assert folded_contains(body, "Penal Code (Cap 224, 1985 Rev Ed) s 34") is False


def test_folded_contains_distinguishes_body_from_omitted() -> None:
    body = "the accused was charged under section 5 of the Misuse of Drugs Act"
    # Punctuation/whitespace-normalised body phrase -> present (an unexpected matcher miss signal).
    assert folded_contains(body, "s 5(1)(\na\n)") is False  # not in this body
    assert folded_contains(body, "Misuse of Drugs Act") is True
    # A normalised field value (ISO date) or reference-only text is absent from the body -> null.
    assert folded_contains(body, "2020-11-04") is False
    assert folded_contains(body, "") is False


@pytest.mark.parametrize(
    ("rendered", "snippet"),
    [
        ("see s32 of the Act", "s 32 of the Act"),  # render dropped the alphanumeric space
        ("see s 32 of the Act", "s32 of the Act"),  # render inserted one
        ("ORIGINATING SUMMONS No 12", "Originating Summons No 12"),  # letter case
    ],
)
def test_build_anchor_map_fallbacks_for_alphanumeric_whitespace_and_case(
    rendered: str, snippet: str
) -> None:
    # Matching tolerates whitespace and letter case while preserving served-text offsets.
    (hit,) = build_anchor_map(rendered, [snippet])
    assert hit.found and hit.char_start is not None and hit.char_end is not None
    assert folded_contains(rendered[hit.char_start : hit.char_end], snippet)


def test_build_anchor_map_prefers_the_exact_match_over_a_fallback() -> None:
    rendered = "first s32 then s 32 again"
    (hit,) = build_anchor_map(rendered, ["s 32"])
    assert (hit.char_start, hit.char_end) == (15, 19)


def test_flexible_pattern_has_no_adjacent_whitespace_quantifiers_and_stays_linear() -> None:
    # A 401-character catchwords snippet against a 100k-character render never finished: the
    # pattern carried 71 back-to-back whitespace quantifiers (``\s*\s*`` around punctuation), which
    # backtrack exponentially on a long near-match. Adjacent quantifiers are merged and made
    # possessive -- the matched language is unchanged (whitespace never overlaps a following
    # character class) -- so the search completes immediately.
    import time

    snippet = "[Alpha beta — gamma de — ef-ghij — klmnop — qrstuv] " * 8
    near_miss = (
        "[Alpha beta — gamma de — ef-ghij — klmnop — qrstuv] " * 7
        + "[Alpha beta — gamma de — ef-ghij — klmnop — XXXX] "
        + "filler " * 50
    )
    pattern = _flexible_pattern(snippet)
    assert pattern is not None
    assert "\\s*+\\s" not in pattern.pattern and "\\s++\\s" not in pattern.pattern
    started = time.monotonic()
    assert pattern.search(near_miss) is None
    assert pattern.search(near_miss + snippet) is not None
    assert time.monotonic() - started < 1.0
    # the language is unchanged: the documented tolerances still hold
    assert _flexible_pattern("s 5(1)(\na\n) of; the Act").search("see s 5(1)(a) of ; the Act here")
    assert _flexible_pattern("Cr App R").search("Cr AppR") is None  # letters never merge
