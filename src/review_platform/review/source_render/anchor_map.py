"""Snippet-search anchor map: locate evidence snippets in the rendered text.

Matching tolerates the character-level differences that survive rendering without changing meaning:
runs of whitespace are matched flexibly, and typographic variants (curly vs straight quotes,
en/em dash vs hyphen) are matched as equivalence classes. Offsets always address the *original*
``rendered_text`` (the served render) because the tolerant pattern is applied to that text directly
-- no normalised copy is searched -- so a hit's char_start/char_end stay valid for the UI."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

# Typographic equivalence classes: a snippet character in any of these folds to the whole class so
# the render's normalised form still matches. Only meaning-preserving variants are folded.
_APOSTROPHE = "'‘’‛ʼ´`"  # ' ' ' ‛ ʼ ´ `
_DOUBLE_QUOTE = '"“”„‟«»'  # " " " „ ‟ « »
_DASH = "-‐‑‒–—―−"  # - ‐ ‑ ‒ – — ― −
_EQUIVALENCE_CLASSES = (_APOSTROPHE, _DOUBLE_QUOTE, _DASH)


@dataclass(frozen=True)
class AnchorHit:
    """One snippet-search result against the rendered plain text."""

    snippet: str
    found: bool
    char_start: int | None = None
    char_end: int | None = None


def _char_pattern(char: str) -> str:
    """Regex for a single snippet character: an equivalence class, or the escaped literal."""

    for members in _EQUIVALENCE_CLASSES:
        if char in members:
            return f"[{re.escape(members)}]"
    return re.escape(char)


def _flexible_pattern(snippet: str, *, loose_whitespace: bool = False) -> re.Pattern[str] | None:
    r"""Build a whitespace- and typography-flexible regex from a snippet, or ``None`` if empty.

    With ``loose_whitespace`` the separator between two alphanumerics becomes optional
    (``\s*``) when at least one of them is a digit -- the fallback for renders that
    insert or drop a space around a number at an inline-element boundary (``s 32`` vs
    ``s32``, ``No 600`` vs ``No600``). Whitespace between two letters stays required in
    every mode, so distinct words never merge. The loose form is only tried after the
    exact pattern fails.

    Whitespace is required (``\s+``) between two alphanumeric characters, so distinct words
    never merge, but optional (``\s*``) whenever either neighbour is punctuation --
    whether that whitespace was present in the snippet or not. That lets a provenance
    snippet that wrapped across a source line break -- e.g. ``s 5(1)(\na\n)`` -- still
    match the render's collapsed ``s 5(1)(a)``, and also lets punctuation glued to the
    snippet's text (e.g. ``2016;``) match a render that inserted a space before it (e.g.
    ``2016 ;`` -- info-table cells commonly space their ``;``-separated values that
    way), without loosening genuine word boundaries.

    Two whitespace quantifiers are never emitted back to back (``\s*\s*`` is ``\s*``,
    ``\s+\s*`` is ``\s+`` -- the same language), and every whitespace quantifier is
    possessive: whitespace never overlaps the character that follows it (no equivalence
    class contains whitespace), so giving it back can never produce a match, and
    refusing to try keeps a long near-match from backtracking exponentially. The set of
    strings a pattern matches is unchanged by either rule."""

    non_space = [char for char in snippet if not char.isspace()]
    if not non_space:
        return None

    parts: list[str] = []
    previous: str | None = None
    index = 0
    length = len(snippet)
    while index < length:
        char = snippet[index]
        if char.isspace():
            run_end = index
            while run_end < length and snippet[run_end].isspace():
                run_end += 1
            next_char = snippet[run_end] if run_end < length else None
            if previous is not None and next_char is not None:
                strict = previous.isalnum() and next_char.isalnum()
                if strict and loose_whitespace and not (previous.isalpha() and next_char.isalpha()):
                    strict = False
                _append_whitespace(parts, required=strict)
            index = run_end
            continue
        if previous is not None and (
            not previous.isalnum()
            or not char.isalnum()
            or (loose_whitespace and not (previous.isalpha() and char.isalpha()))
        ):
            # Directly adjacent in the snippet (no whitespace to collapse) but punctuation on
            # either side -- allow an optional space here too, matching the tolerance already
            # given to whitespace-separated tokens above.
            _append_whitespace(parts, required=False)
        parts.append(_char_pattern(char))
        previous = char
        index += 1
    return re.compile("".join(parts))


_WS_OPTIONAL = r"\s*+"
_WS_REQUIRED = r"\s++"


def _append_whitespace(parts: list[str], *, required: bool) -> None:
    """Append one possessive whitespace quantifier, merging with an adjacent one (same
    language)."""

    if parts and parts[-1] in (_WS_OPTIONAL, _WS_REQUIRED):
        if required and parts[-1] == _WS_OPTIONAL:
            parts[-1] = _WS_REQUIRED
        return
    parts.append(_WS_REQUIRED if required else _WS_OPTIONAL)


def _search(snippet: str, rendered_text: str) -> re.Match[str] | None:
    """Exact tolerant pattern first; then the two evidenced fallbacks, in order.

    The audit of the production imports found two residual matcher gaps behind
    ``folded_contains``-positive misses: whitespace around a number that the render inserted or
    dropped at an inline-element boundary, and letter case. Each fallback is tried only after the
    stricter form fails, so an exact hit is never displaced, and every match still addresses the
    served text.
    """

    exact = _flexible_pattern(snippet)
    if exact is None:
        return None
    if (match := exact.search(rendered_text)) is not None:
        return match
    loose = _flexible_pattern(snippet, loose_whitespace=True)
    if loose is not None and (match := loose.search(rendered_text)) is not None:
        return match
    if loose is not None:
        return re.compile(loose.pattern, re.IGNORECASE).search(rendered_text)
    return None


def build_anchor_map(rendered_text: str, snippets: list[str]) -> list[AnchorHit]:
    """Locate each snippet in ``rendered_text`` and return offsets into that text.

    Offsets address ``rendered_text`` (the served render), never the original document. A snippet
    that cannot be located (it spans omitted content, or is absent) is returned as ``found=False``
    with no offsets, mirroring the API's anchor-unavailable fallback.
    """

    hits: list[AnchorHit] = []
    for snippet in snippets:
        match = _search(snippet, rendered_text)
        if match is None:
            hits.append(AnchorHit(snippet=snippet, found=False))
        else:
            hits.append(
                AnchorHit(
                    snippet=snippet,
                    found=True,
                    char_start=match.start(),
                    char_end=match.end(),
                )
            )
    return hits


def _canonical_char(char: str) -> str:
    """Fold a typographic-variant character to its canonical ASCII form; else return it."""

    if char in _APOSTROPHE:
        return "'"
    if char in _DOUBLE_QUOTE:
        return '"'
    if char in _DASH:
        return "-"
    return char


def _fold(text: str) -> str:
    """Fold text for containment: NFKC, canonical quotes/dashes, casefold, collapse whitespace.

    Punctuation is *kept* (only whitespace and typographic variants are normalised), so a verbatim
    body quote that merely wrapped across a line break folds equal to the render, while a
    synthesised field value -- ``;``-joined coram, bracketed catchwords, an ISO date -- does not
    fold equal to the differently-punctuated source and is correctly treated as not-a-body-quote.
    Whitespace is dropped except between two letters, where it folds to one space: the matcher
    never merges distinct words, so a render that ran two words together must not count as
    containing the snippet (it would be reported as an unexplained miss forever).
    """

    normalised = unicodedata.normalize("NFKC", text).casefold()
    out: list[str] = []
    pending_space = False
    for char in normalised:
        if char.isspace():
            pending_space = True
            continue
        canonical = _canonical_char(char)
        if pending_space and out and out[-1].isalpha() and canonical.isalpha():
            out.append(" ")
        pending_space = False
        out.append(canonical)
    return "".join(out)


def folded_contains(rendered_text: str, snippet: str) -> bool:
    """Whether ``snippet`` is a verbatim span of ``rendered_text`` modulo whitespace/typography.

    Used to tell an *unexpected* anchor miss (the snippet is genuinely in the rendered body but the
    tolerant pattern still failed -- a residual matcher gap worth surfacing) from an *expected* one
    (the snippet is not a body quote: its provenance is grounded in a region the render omits, such
    as a reference table, or it is a normalised/synthesised field value with no verbatim source
    form).
    """

    folded_snippet = _fold(snippet)
    return bool(folded_snippet) and folded_snippet in _fold(rendered_text)
