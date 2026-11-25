"""Reviewer-safe display derivation for a review unit's extracted candidate value.

Split out of ``grouped_bundle.py`` (which keeps growing) and reused by ``queue.py``'s case-grouped
reviewer queue -- both need the same field-token/citation/relation-label derivation, and neither
depends on the mixin/session plumbing the rest of ``grouped_bundle.py`` carries, so this module is
plain functions and constants only, with no ``ReviewServiceBase``/session coupling.
"""

from __future__ import annotations

import json
from typing import Any

from review_platform.common.display_labels import section_display as _section_display
from review_platform.review.models import Candidate

# Field tokens whose own extracted value is the case's title (used to derive the case-level header
# title from whichever unit of the group actually carries it, rather than the anchor unit).
# Subject matter is a topic, not the case title.
TITLE_FIELD_TOKENS = frozenset({"title_raw"})

# Field tokens for the citation metadata fields, used for the case header's citation displays (both
# live in the case_metadata group; see grouping.py -- there is no dedicated "citations" group).
# Matched by field token, not review_kind, because real imports carry citation fields as ordinary
# metadata_field units -- "citation_link" is a synthetic-fixture-only review_kind (see
# synthetic_import.py) and never appears in real-imported data.
NEUTRAL_CITATION_FIELD_TOKEN = "citation_neutral"  # nosec B105 -- field token, not a credential
REPORTED_CITATION_FIELD_TOKEN = "citation_reporter"  # nosec B105 -- field token, not a credential


def _atomic_field_token(field_name: str | None, safe_field_label: str) -> str:
    """Token for title/citation detection: prefer the stable ``field_name``, else the label.

    Keeps header title/citation derivation working after a display label changes, since it keys off
    the source column rather than the renamable label (mirrors ``grouping.classify_unit``).
    """

    from review_platform.review.grouping import field_name_token, field_token

    return field_name_token(field_name) if field_name else field_token(safe_field_label)


def is_title_field(field_name: str | None, safe_field_label: str) -> bool:
    return _atomic_field_token(field_name, safe_field_label) in TITLE_FIELD_TOKENS


def is_neutral_citation_field(field_name: str | None, safe_field_label: str) -> bool:
    return _atomic_field_token(field_name, safe_field_label) == NEUTRAL_CITATION_FIELD_TOKEN


def is_reported_citation_field(field_name: str | None, safe_field_label: str) -> bool:
    return _atomic_field_token(field_name, safe_field_label) == REPORTED_CITATION_FIELD_TOKEN


_RELATION_DISPLAY_KEYS: dict[str, tuple[str, ...]] = {
    "cited_case": ("to_case_ext",),
    "statute_reference": ("to_statute_ext", "section_cited"),
    "appeal_relation": ("associated_citation",),
}
_RELATION_RESOLVED_CASE_KEYS: tuple[str, ...] = (
    "resolved_citation_neutral",
    "resolved_title",
    "resolved_citation_reporter",
)
_RELATION_PREFERRED_KEYS: dict[str, tuple[str, ...]] = {
    "cited_case": _RELATION_RESOLVED_CASE_KEYS,
    "statute_reference": (),
    "appeal_relation": _RELATION_RESOLVED_CASE_KEYS,
}
# ``appeal_relation`` is a directed edge read from both ends, so the counterpart id lives under
# ``higher_case_id`` or ``lower_case_id`` depending which end this case sits at.
_RELATION_FALLBACK_ID_KEYS: dict[str, tuple[str, ...]] = {
    "cited_case": ("to_case_id_int",),
    "statute_reference": ("to_statute_id_int",),
    "appeal_relation": ("higher_case_id", "lower_case_id"),
}
_RELATION_UNKNOWN_LABEL: dict[str, str] = {
    "cited_case": "cited case",
    "statute_reference": "statute",
    "appeal_relation": "appeal",
}


def extracted_value(
    candidate: Candidate | None, *, fallback: str, review_kind: str | None = None
) -> tuple[str, Any | None]:
    """Render a unit's deterministic candidate value as reviewer-facing display text plus raw
    JSON."""

    if candidate is None:
        return fallback, None
    value = candidate.value_json
    if value is None:
        return fallback, None
    if review_kind in _RELATION_DISPLAY_KEYS and isinstance(value, dict):
        return _relation_display(review_kind, value, fallback=fallback), value
    if isinstance(value, str):
        return value, value
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True), value
    return str(value), value


def _relation_display(review_kind: str, value: dict[str, Any], *, fallback: str) -> str:
    """Compose a reviewer-safe label for a relation's structured candidate value.

    Resolution order: the counterpart case's resolved citation/title
    (``_RELATION_PREFERRED_KEYS``), then whichever display-carrying columns are present
    (``_RELATION_DISPLAY_KEYS``), joined with " · " in column order; a statute's
    ``section_cited`` is rendered as a provision (e.g. "Companies Act (Cap 50) · s 216")
    without doubling a marker the source already carries. Degrades to "Unknown <kind>
    #<id>" when only an internal id column is present, and to the unit's own fallback
    title when nothing usable is present at all -- never surfaces a raw internal id as
    the primary label."""

    for keys in (_RELATION_PREFERRED_KEYS[review_kind], _RELATION_DISPLAY_KEYS[review_kind]):
        parts: list[str] = []
        for key in keys:
            raw = value.get(key)
            if raw is None or str(raw).strip() == "":
                continue
            text = str(raw).strip()
            parts.append(_section_display(text) if key == "section_cited" else text)
        if parts:
            return " · ".join(parts)
    for id_key in _RELATION_FALLBACK_ID_KEYS[review_kind]:
        raw_id = value.get(id_key)
        if raw_id is not None and str(raw_id).strip() != "":
            return f"Unknown {_RELATION_UNKNOWN_LABEL[review_kind]} #{raw_id}"
    return fallback
