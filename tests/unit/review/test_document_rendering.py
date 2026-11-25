import json

import pytest

from review_platform.review.source_render import (
    build_anchor_map,
    folded_contains,
    plain_text_from_safe_html,
    render_source_document,
)

pytestmark = pytest.mark.no_db


def test_sanitizes_untrusted_html_and_inerts_external_resources():
    raw = (
        "<article>"
        '<p onclick="bad()">Alpha <strong>βeta 判決</strong>'
        "</p>"
        "<script>secret()</script>"
        '<img src="https://example.invalid/x">'
        '<a href="javascript:bad()">bad</a>'
        '<a href="https://example.invalid">external</a>'
        "</article>"
    )
    artifact = render_source_document(source_system="sample_a", raw_html=raw)
    assert (
        "<script" not in artifact.safe_html
        and "onclick" not in artifact.safe_html
        and "<img" not in artifact.safe_html
    )
    assert (
        "javascript:" not in artifact.safe_html
        and "https://" not in artifact.safe_html
        and "secret()" not in artifact.safe_html
    )
    assert (
        plain_text_from_safe_html("sample_a", artifact.safe_html)
        == "Alpha βeta 判決\n\nbadexternal"
    )


def test_document_article_and_projection_share_exact_coordinates():
    artifact = render_source_document(
        source_system="sample_a",
        raw_html="<html>"
        "<body>"
        "<nav>Not the document</nav>"
        '<article data-review-document="true">'
        "<p>One <b>判決</b> text</p>"
        "<p>Two<br>words</p>"
        "</article>"
        "</body>"
        "</html>",
    )
    text = plain_text_from_safe_html("sample_a", artifact.safe_html)
    assert text == "One 判決 text\n\nTwo words"
    assert "Not the document" not in artifact.safe_html
    anchors = json.loads(artifact.anchor_map_json)["anchors"]
    assert [text[anchor["char_start"] : anchor["char_end"]] for anchor in anchors] == [
        "One 判決 text",
        "Two words",
    ]


def test_rendering_is_deterministic_and_collection_independent():
    kwargs = {"raw_html": "<p>A <em>document</em>.</p>"}
    assert render_source_document(source_system="sample_a", **kwargs) == render_source_document(
        source_system="sample_b", **kwargs
    )


def test_rejects_ambiguous_document_and_oversize_input():
    with pytest.raises(ValueError):
        render_source_document(
            source_system="sample_a",
            raw_html="<div>"
            '<article data-review-document="true">A</article>'
            '<article data-review-document="true">B</article>'
            "</div>",
        )
    with pytest.raises(ValueError):
        render_source_document(source_system="sample_a", raw_html="x" * (16 * 1024 * 1024 + 1))


@pytest.mark.parametrize(
    "text,snippet,found",
    [
        ("Alpha beta", "alpha beta", True),
        ("s 32 of the Act", "s32 of the Act", True),
        ("Alpha beta", "Alphabeta", False),
        ("citation [2020] 1", "citation [2020] 1", True),
        ("abc", "absent", False),
        ("abc", "", False),
    ],
)
def test_anchor_matching_preserves_word_boundaries(text, snippet, found):
    (hit,) = build_anchor_map(text, [snippet])
    assert hit.found == found
    if found:
        assert text[hit.char_start : hit.char_end]


def test_containment_does_not_merge_words():
    assert folded_contains("Section 32 of the Act", "section32 of the Act")
    assert not folded_contains("two words", "twowords")


def test_leading_text_and_block_anchors_survive_sanitization():
    artifact = render_source_document(
        source_system="sample_a", raw_html="Leading text<p>Second block</p>"
    )
    text = plain_text_from_safe_html("sample_a", artifact.safe_html)
    assert text == "Leading text\n\nSecond block"
    anchors = json.loads(artifact.anchor_map_json)["anchors"]
    assert [text[a["char_start"] : a["char_end"]] for a in anchors] == [
        "Leading text",
        "Second block",
    ]
