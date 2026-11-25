"""Pure bounds/truncation logic for reviewer source/evidence rendering (review.source_safety)."""

from __future__ import annotations

import pytest

from review_platform.review import source_safety
from review_platform.review.source_safety import (
    MAX_EVIDENCE_SNIPPET_CHARS,
    MAX_SOURCE_RENDER_CHARS,
    TRUNCATION_MARKER,
    clamp_snippet,
    fit_block,
    truncate_to,
)

pytestmark = pytest.mark.no_db


def test_truncate_to_keeps_short_and_exact_text_verbatim() -> None:
    assert truncate_to("hello", 10) == "hello"
    assert truncate_to("hello", 5) == "hello"


def test_truncate_to_marks_and_bounds_long_text() -> None:
    out = truncate_to("x" * 100, 40)
    assert len(out) == 40
    assert out.endswith(TRUNCATION_MARKER)
    assert out.startswith("x")


def test_truncate_to_hard_cuts_when_no_room_for_marker() -> None:
    # A limit no larger than the marker cannot carry it; long text is hard-cut and never overflows.
    text = "a" * 40
    limit = len(TRUNCATION_MARKER)
    out = truncate_to(text, limit)
    assert out == text[:limit]
    assert len(out) == limit
    assert not out.endswith(TRUNCATION_MARKER)


def test_truncate_to_non_positive_limit_is_empty() -> None:
    assert truncate_to("anything", 0) == ""
    assert truncate_to("anything", -5) == ""


def test_clamp_snippet_bounds_to_window_limit() -> None:
    clamped = clamp_snippet("y" * (MAX_EVIDENCE_SNIPPET_CHARS + 500))
    assert len(clamped) == MAX_EVIDENCE_SNIPPET_CHARS
    assert clamped.endswith(TRUNCATION_MARKER)
    # A snippet within the bound is never altered.
    assert clamp_snippet("short") == "short"


def test_clamp_snippet_does_not_strip_markup(monkeypatch) -> None:
    # Bounding only truncates; it must not escape or remove markup, since safe_text is rendered as
    # text by the client and the no-execute guarantee lives in the render-mode contract.
    monkeypatch.setattr(source_safety, "MAX_EVIDENCE_SNIPPET_CHARS", 10_000)
    payload = "<script>alert('x')</script>"
    assert clamp_snippet(payload) == payload


def test_fit_block_passes_through_within_budget() -> None:
    block, exhausted = fit_block("abc", used_chars=0)
    assert block == "abc"
    assert exhausted is False


def test_fit_block_truncates_on_overflow_and_signals_exhaustion() -> None:
    used = MAX_SOURCE_RENDER_CHARS - 30
    block, exhausted = fit_block("z" * 100, used_chars=used)
    assert exhausted is True
    assert len(block) == 30
    assert block.endswith(TRUNCATION_MARKER)


def test_fit_block_returns_empty_when_budget_already_spent() -> None:
    block, exhausted = fit_block("anything", used_chars=MAX_SOURCE_RENDER_CHARS)
    assert block == ""
    assert exhausted is True
