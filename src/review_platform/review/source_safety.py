"""Payload bounds and safe truncation for reviewer-facing source/evidence rendering.

Its sole responsibility is to keep a pathological source document from producing an unbounded
response or anchors that address content the render had to drop. It bounds each snippet, bounds the
assembled render, and truncates on a deterministic character boundary with a visible marker so the
reviewer can tell the text was cut."""

from __future__ import annotations

# A single evidence window is already bounded by its DB column; clamp defensively at the same size
# so the rendered payload never exceeds the persisted bound even if the column later grows.
MAX_EVIDENCE_SNIPPET_CHARS = 20_000

# Aggregate ceiling for one assembled ``source_render.content``. Many small windows (or a unit with
# many windows) must not concatenate into an unbounded body.
MAX_SOURCE_RENDER_CHARS = 120_000

# Upper bound on anchors emitted for one render. Each owned unit contributes one or two anchors;
# this caps the navigation table for a subject with an unusually large number of owned units.
MAX_SOURCE_RENDER_ANCHORS = 2_000

# Appended where text is cut so the boundary is visible to the reviewer. Plain text on purpose: it
# is rendered through the same safe-text path as the source itself.
TRUNCATION_MARKER = "…[truncated]"


def truncate_to(text: str, limit: int) -> str:
    """Return ``text`` cut to at most ``limit`` characters, marked when anything was removed.

    The result never exceeds ``limit`` characters: when there is room the marker replaces the tail,
    and when ``limit`` is too small to hold the marker the text is hard-cut without one.
    """

    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit <= len(TRUNCATION_MARKER):
        return text[:limit]
    return text[: limit - len(TRUNCATION_MARKER)] + TRUNCATION_MARKER


def clamp_snippet(text: str) -> str:
    """Bound a single evidence snippet to the per-window render limit."""

    return truncate_to(text, MAX_EVIDENCE_SNIPPET_CHARS)


def fit_block(block: str, used_chars: int) -> tuple[str, bool]:
    """Fit one render block into the remaining aggregate budget.

    ``used_chars`` is the length of the content already assembled (including any separator that
    will precede this block). Returns the block to append — truncated when it would overflow — and
    a flag that is true once the aggregate budget is exhausted, telling the caller to stop adding.
    """

    available = MAX_SOURCE_RENDER_CHARS - used_chars
    if available <= 0:
        return "", True
    if len(block) <= available:
        return block, False
    return truncate_to(block, available), True
