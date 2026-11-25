"""Review-owned groups and stable field labels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, NamedTuple

GroupKind = Literal["atomic", "non_atomic"]


class GroupDefinition(NamedTuple):
    group_id: str
    group_label: str
    group_kind: GroupKind
    order: int
    description: str | None = None


GROUP_DEFINITIONS: tuple[GroupDefinition, ...] = (
    GroupDefinition("case_metadata", "Case metadata", "atomic", 1),
    GroupDefinition("court_and_hearing", "Court, date & coram", "atomic", 3),
    GroupDefinition("parties_and_representation", "Parties, lawyers & firms", "atomic", 4),
    GroupDefinition("additional_fields", "Additional fields", "atomic", 5),
    GroupDefinition("cited_cases", "Cited cases", "non_atomic", 6),
    GroupDefinition("statutes_cited", "Statutes cited", "non_atomic", 7),
    GroupDefinition("appeal_relations", "Appeal relations", "non_atomic", 8),
    GroupDefinition("related_cases", "Related cases", "non_atomic", 9),
)

GROUP_BY_ID: dict[str, GroupDefinition] = {group.group_id: group for group in GROUP_DEFINITIONS}

# Default landing group for an atomic field that matches no explicit field rule. Explicit and
# documented, not a silent broadening of an existing group.
DEFAULT_ATOMIC_GROUP_ID = "additional_fields"

# Stable source-field token -> atomic group id. A token is the source column name (the stable
# ``field_name``, e.g. ``cases.citation_neutral`` -> ``citation_neutral``), NOT the reviewer-facing
# display label -- so renaming a display label can never silently regroup a field or change a
# campaign's eligibility. ``classify_unit`` prefers the unit's ``field_name``; the display-label
# token is only a legacy fallback for rows imported before ``field_name`` was stored.
_FIELD_TOKEN_TO_GROUP: dict[str, str] = {
    "title_raw": "case_metadata",
    "subject": "case_metadata",
    "proceedings_type": "case_metadata",
    "disposition_proc": "case_metadata",
    # suit_num is a case-identity field, not a grab-bag "additional field": mapping it into
    # case_metadata keeps the additional_fields catch-all from silently meaning "suit number".
    "suit_num": "case_metadata",
    # Neutral/reported citation are case-identity facts, not a standalone "Citations" section --
    # merged into case_metadata alongside title/suit number/proceedings type.
    "citation_neutral": "case_metadata",
    "citation_reporter": "case_metadata",
    "court_id": "court_and_hearing",
    "court": "court_and_hearing",
    "j_date": "court_and_hearing",
    "decision_date": "court_and_hearing",
    "coram": "court_and_hearing",
    "coram_author": "court_and_hearing",
    "parties": "parties_and_representation",
    "lawyers_pf": "parties_and_representation",
    "firms_pf": "parties_and_representation",
    "lawyers_df": "parties_and_representation",
    "firms_df": "parties_and_representation",
}

# Review-kind -> group id. Atomic single-field review kinds and the non-atomic relation review
# kinds that future snapshots may carry. "citation_link" (a synthetic-fixture-only review_kind --
# see synthetic_import.py) routes to case_metadata, same as the field-token map below; everything
# else atomic falls through to the per-field token map.
_REVIEW_KIND_TO_GROUP: dict[str, str] = {
    "citation_link": "case_metadata",
    "cited_case": "cited_cases",
    "statute_reference": "statutes_cited",
    "appeal_relation": "appeal_relations",
    "related_case": "related_cases",
}


# Closed set of review kinds the backend recognises for campaign-scope selection: the atomic
# ``metadata_field`` default plus every explicit relation/citation kind in the map above.
# Authoritative source for the campaign scope catalog; keep in sync with the map above.
SUPPORTED_REVIEW_KINDS: tuple[str, ...] = ("metadata_field", *_REVIEW_KIND_TO_GROUP.keys())

# non_atomic group id -> review_kind, for synthesizing a group-level "missing" ReviewUnit
# (campaign_availability.materialize_from_pool) when a case has no pool unit in that relation
# group. Derived from _REVIEW_KIND_TO_GROUP, restricted to non_atomic groups (every atomic group
# synthesizes as review_kind "metadata_field" with field_name=None instead, since an atomic group
# has no single review_kind of its own).
RELATION_GROUP_TO_REVIEW_KIND: dict[str, str] = {
    group_id: review_kind
    for review_kind, group_id in _REVIEW_KIND_TO_GROUP.items()
    if group_id in GROUP_BY_ID and GROUP_BY_ID[group_id].group_kind == "non_atomic"
}

SOURCE_FAMILIES: tuple[str, ...] = ("sample_a", "sample_b")


class UnknownReviewFieldError(ValueError):
    """A source metadata column has no field-group mapping -- the closed allowlist rejects it.

    Raised at import time so a newly-added ``REVIEWABLE_COLUMNS`` entry without a
    ``_FIELD_TOKEN_TO_GROUP`` mapping fails loudly instead of silently landing in
    ``additional_fields`` and retroactively changing what an existing campaign's scope means.
    """

    def __init__(self, field_name: str) -> None:
        super().__init__(f"no field-group mapping for source field {field_name!r}")
        self.field_name = field_name


FIELD_LABELS: dict[str, str] = {
    "title_raw": "Case title",
    "subject": "Subject matter",
    "proceedings_type": "Proceedings type",
    "disposition_proc": "Disposition",
    "suit_num": "Suit number",
    "citation_neutral": "Neutral citation",
    "citation_reporter": "Reported citation",
    "court_id": "Court",
    "court": "Court",
    "j_date": "Judgment date",
    "decision_date": "Decision date",
    "coram": "Coram",
    "coram_author": "Judgment author",
    "parties": "Parties",
    "lawyers_pf": "Plaintiff's counsel",
    "firms_pf": "Plaintiff's firm",
    "lawyers_df": "Defendant's counsel",
    "firms_df": "Defendant's firm",
}


def field_token(safe_field_label: str) -> str:
    """Normalise a display field label back to a lowercase, underscored field token."""

    return "_".join(safe_field_label.split()).lower()


def display_field_label(field_name: str | None, safe_field_label: str) -> str:
    """Reviewer-facing label for an atomic unit, derived from the stable ``field_name``."""

    if not field_name:
        return safe_field_label
    return FIELD_LABELS.get(field_name_token(field_name), safe_field_label)


def field_name_token(field_name: str) -> str:
    """Normalise a stable source ``field_name`` (e.g. ``cases.citation_neutral``) to its token."""

    return field_name.split(".", 1)[-1].strip().lower()


def require_atomic_group(field_name: str) -> GroupDefinition:
    """Resolve an atomic metadata field's group by its stable ``field_name``, or fail loudly.

    Used by the importers so an unmapped source column is rejected at write time (closed
    allowlist), never absorbed silently into the ``additional_fields`` default."""

    group_id = _FIELD_TOKEN_TO_GROUP.get(field_name_token(field_name))
    if group_id is None:
        raise UnknownReviewFieldError(field_name)
    return GROUP_BY_ID[group_id]


def scope_matches(
    review_kind: str,
    safe_field_label: str,
    scope: Mapping[str, Sequence[str]] | None,
    source_system: str | None = None,
    field_name: str | None = None,
) -> bool:
    """Whether a review unit falls within an optional campaign review scope.

    ``scope`` is the ``{group_ids, review_kinds, source_families}`` payload; an empty/None scope
    means all fields. A unit is included when it matches every non-empty axis: its group
    (``classify_unit``) is in ``group_ids``, its ``review_kind`` is in ``review_kinds``, and its
    ``source_system`` is in ``source_families``. Shared by the synthetic and real importers so both
    paths apply one filter. ``source_system`` is optional only for callers that never carry a
    ``source_families``-scoped campaign (a caller that omits it while ``source_families`` is set
    fails closed, matching nothing, rather than silently ignoring the axis).
    """

    if not scope:
        return True
    group_ids = set(scope.get("group_ids") or [])
    review_kinds = set(scope.get("review_kinds") or [])
    source_families = set(scope.get("source_families") or [])
    if not group_ids and not review_kinds and not source_families:
        return True
    group = classify_unit(review_kind, safe_field_label, field_name)
    return (
        (not group_ids or group.group_id in group_ids)
        and (not review_kinds or review_kind in review_kinds)
        and (not source_families or source_system in source_families)
    )


def classify_unit(
    review_kind: str, safe_field_label: str, field_name: str | None = None
) -> GroupDefinition:
    """Return the allowlisted group a review unit belongs to.

    Resolution order: explicit relation/citation review kind, then the stable ``field_name`` token,
    then the display-label token (legacy fallback for rows imported before ``field_name`` was
    stored), then the documented ``additional_fields`` atomic default. Never raises for an unknown
    field -- display paths must always resolve a group; the loud rejection of an unmapped column is
    the importers' job via :func:`require_atomic_group`.
    """

    group_id = _REVIEW_KIND_TO_GROUP.get(review_kind)
    if group_id is None:
        token = field_name_token(field_name) if field_name else field_token(safe_field_label)
        group_id = _FIELD_TOKEN_TO_GROUP.get(token)
    if group_id is None:
        group_id = DEFAULT_ATOMIC_GROUP_ID
    return GROUP_BY_ID[group_id]


def item_kind(review_kind: str) -> str:
    return {
        "citation_link": "citation",
        "metadata_field": "case_field",
        "cited_case": "cited_case",
        "statute_reference": "statute_reference",
        "appeal_relation": "appeal_relation",
        "related_case": "related_case",
    }.get(review_kind, "case_field")
