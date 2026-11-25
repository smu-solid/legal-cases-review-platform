"""Typed case, field, relation and evidence inputs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InputCandidate:
    source_kind: str  # 'deterministic' | 'model'
    verdict: str
    value: Any
    rationale: str
    supporting_quote: str | None


@dataclass(frozen=True)
class InputEvidence:
    kind: str
    snippet: str
    char_start: int | None
    char_end: int | None
    line_start: int | None
    line_end: int | None
    source_hash: str
    body_grounded: bool | None = None
    source_region: str | None = None
    provenance_external_id: str | None = None


@dataclass(frozen=True)
class MemberValue:
    """One family member's extracted value for a field, source-labelled for the reviewer.

    New imports carry only the selected record's value. The shape also represents historical
    merged imports for safe reconciliation. Each value retains its own document identity and
    evidence; another document's snippets must never become highlights in the displayed source.
    """

    case_external_id: str
    source_system: str
    value: Any
    source_document_id: str = ""
    sha256: str = ""
    #: This member's own evidence for the field: (snippet, source_hash) pairs, display-only.
    evidence: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class InputField:
    field_name: str
    display_value: str
    value_candidate: InputCandidate  # A: the extracted case-field value (always present)
    model_candidate: InputCandidate | None  # B: optional LLM validator context (admin)
    evidence: list[InputEvidence]
    # Selected-record value; historical imports may contain multiple disagreeing observations.
    # Empty for single-observation reads (backward compatible).
    member_values: tuple[MemberValue, ...] = ()
    cross_source_disagreement: bool = False


@dataclass(frozen=True)
class InputRelation:
    """A reviewable evidence relation (cited case / statute reference / appeal) for a case.

    Mirrors the provenance-first metadata contract: a relation is reviewable only when it
    carries conformant provenance evidence, so the reviewer confirms/corrects the
    extracted relation against an anchored source snippet. ``relation_external_id`` is
    the opaque reviewer-view relation id and gives the unit a stable per-relation
    identity for idempotent import."""

    review_kind: str  # 'cited_case' | 'statute_reference' | 'appeal_relation'
    family: str  # provenance field-name family, e.g. 'rel_citations'
    relation_external_id: str
    display_label: str  # safe field label, e.g. 'Cited case'
    display_value: str
    value: dict[str, Any]
    evidence: list[InputEvidence]
    #: Family review: every member observation asserting a SEMANTICALLY EQUIVALENT relation
    #: (same kind and target), each with its own relation id, case and source. Genuinely different
    #: relationships are never collapsed; equal ones become one unit that lists every supporter.
    contributing: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True)
class InputCase:
    external_id: str
    source_system: str
    source_document_id: str
    sha256: str
    title: str | None
    fields: list[InputField] = field(default_factory=list)
    relations: list[InputRelation] = field(default_factory=list)
    # Canonical-family review identity: ``COALESCE(canonical_external_id, external_id)`` of
    # the member
    # observations. For family-grouped reads ``external_id`` IS the family id (the stable reviewer
    # identity) and ``member_external_ids`` lists every source observation folded into this case.
    family_id: str = ""
    member_external_ids: tuple[str, ...] = ()
    member_source_systems: tuple[str, ...] = ()
