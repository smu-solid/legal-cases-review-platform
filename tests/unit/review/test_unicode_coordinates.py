from __future__ import annotations

import json
import uuid
from types import SimpleNamespace

import pytest

from review_platform.common.text_coordinates import codepoint_range, utf16_length
from review_platform.dataset.types import InputEvidence
from review_platform.review.grouped_source_text import GroupedSourceTextMixin
from review_platform.review.grouping import classify_unit
from review_platform.review.import_source import classify_anchor
from review_platform.review.source_render import plain_text_from_safe_html, render_source_document

pytestmark = pytest.mark.no_db


def test_import_and_browser_highlights_agree_after_supplementary_characters():
    html = "<html><body>Lead 😀<p>Supported 判決 🧪 end</p>Trailing text</body></html>"
    artifact = render_source_document(source_system="sample_a", raw_html=html)
    text = plain_text_from_safe_html("sample_a", artifact.safe_html)
    snippet = "Supported 判決 🧪"
    evidence = InputEvidence("quote", snippet, None, None, None, None, "a" * 64)
    status, start, end = classify_anchor(evidence, text, "a" * 64)
    assert status == "anchored" and start is not None and end is not None
    assert start == utf16_length(text[: text.index(snippet)])
    encoded = text.encode("utf-16-le")
    assert encoded[start * 2 : end * 2].decode("utf-16-le") == snippet
    first = json.loads(artifact.anchor_map_json)["anchors"][0]
    assert encoded[first["char_start"] * 2 : first["char_end"] * 2].decode("utf-16-le") == "Lead 😀"


@pytest.mark.parametrize("span", [(-1, 2), (1, 1), (0, 10), (2, 3), (1, 2)])
def test_ranges_reject_out_of_bounds_empty_and_split_surrogate_pairs(span):
    with pytest.raises(ValueError):
        codepoint_range("A😀B", *span)


def test_valid_supplementary_range_and_leading_inline_tail_are_preserved():
    assert codepoint_range("A😀B", 1, 3) == (1, 2)
    artifact = render_source_document(source_system="sample_a", raw_html="Leading <b>😀</b> tail")
    text = plain_text_from_safe_html("sample_a", artifact.safe_html)
    assert text == "Leading 😀 tail"
    start, end = codepoint_range(text, 8, 10)
    assert text[start:end] == "😀"


def test_fallback_and_full_document_bundle_anchors_use_browser_coordinates():
    group = classify_unit("metadata_field", "Subject", "cases.subject")
    unit = SimpleNamespace(id=uuid.uuid4(), field_name="cases.subject", safe_field_label="Subject")
    evidence = SimpleNamespace(
        snippet="😀 Provenance", char_start=0, char_end=13, anchor_status="anchored"
    )
    prepared = [(group, None, unit, None, [evidence])]
    source, *_ = GroupedSourceTextMixin._build_source_render_from_snippets(prepared, uuid.uuid4())
    anchor = next(a for a in source.anchors if a.review_unit_id)
    assert anchor.char_end == utf16_length(source.content)
    source, *_ = GroupedSourceTextMixin._build_source_render_from_full_text(
        prepared, uuid.uuid4(), "😀 Provenance"
    )
    anchor = next(a for a in source.anchors if a.review_unit_id)
    assert anchor.char_end == 13
