"""Real import values, lazy source rendering, and evidence classification."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import Mapping, Sequence, Set
from dataclasses import asdict, dataclass
from datetime import date, datetime, time
from decimal import Decimal
from time import perf_counter
from typing import Any, Literal, cast

from review_platform.common.text_coordinates import utf16_length
from review_platform.dataset.documents import DocumentResolver
from review_platform.dataset.types import InputCase, InputEvidence, InputField, InputRelation
from review_platform.review.source_render import (
    RenderedArtifact,
    build_anchor_map,
    folded_contains,
    plain_text_from_safe_html,
    render_source_document,
)

CONTRACT_VERSION = "review-dataset-snapshot/v1"


IMPORT_JOB = "dataset-import"


@dataclass
class DatasetImportResult:
    campaign_id: uuid.UUID
    imported_units: int
    imported_cases: int
    unresolved_source_cases: int
    # A body-quote evidence snippet whose words ARE in the rendered body but that the anchor matcher
    # still failed to locate -- a residual matcher gap worth investigating. Should stay ~0.
    unresolved_anchors: int
    unanchored_expected: int
    unresolved_case_ids: list[str] = dataclasses.field(default_factory=list)
    # Cases whose every unit digest already matched, so the raw source was never read or rendered.
    # This is the win on a re-run and it is reported, not assumed: a refresh that reports zero
    # skipped cases is doing full work and the cause belongs in the run's notes.
    skipped_unchanged_cases: int = 0
    # Cases whose source WAS read and rendered. ``skipped + rendered`` accounts for every case that
    # resolved, so the two together say how much of a run was avoidable.
    rendered_cases: int = 0
    # Family reconciliation accounting. ``deferred_families`` maps a family id to the reason and
    # the protected legacy unit keys that blocked it: when ANY member identity carries assigned or
    # submitted work that cannot be safely re-keyed, the WHOLE family is deferred rather than
    # represented by a second assignable case. ``reconciled_legacy_keys`` records every
    # member-keyed pool unit adopted (replaced in place) by its family-keyed successor.
    deferred_families: dict[str, dict[str, object]] = dataclasses.field(default_factory=dict)
    reconciled_legacy_keys: list[dict[str, str]] = dataclasses.field(default_factory=list)
    # Relations asserted by more than one member observation that were grouped as one unit.
    relation_duplicates_grouped: int = 0
    # Wall-clock seconds spent reading raw HTML off the source mount and rendering it. Recorded so
    # the render/database split of the per-case cost is measured rather than inferred.
    source_render_seconds: float = 0.0


class DatasetImportError(RuntimeError):
    """A precondition for the gated real import was not met (fail closed)."""


class _SourceUnavailableError(RuntimeError):
    """The raw source vanished or changed between resolution and the write that needed it."""


def _plain_text(source_system: str, raw_html: str) -> str:
    rendered = render_source_document(source_system=source_system, raw_html=raw_html)
    from review_platform.review.source_render import plain_text_from_safe_html

    return plain_text_from_safe_html(source_system, rendered.safe_html)


def _field_label(field_name: str) -> str:
    return field_name.removeprefix("cases.").replace("_", " ").title()


def _json_safe(value: object) -> object:
    """Json safe."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Decimal | uuid.UUID):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [_json_safe(item) for item in value]
    return str(value)


class _CaseSource:
    """Reads and renders a case's raw source on first demand, then memoises it.

    Loading lazily makes that cost proportional to the units actually being replaced. The render is
    forced before the first mutation of a unit, never after, so a source that has become unreadable
    still fails that case cleanly instead of half-writing it."""

    __slots__ = ("_case", "_loaded", "_resolver", "_seconds", "_source_system")

    def __init__(self, *, resolver: DocumentResolver, source_system: str, case: InputCase) -> None:
        self._resolver = resolver
        self._source_system = source_system
        self._case = case
        self._loaded: tuple[RenderedArtifact, str] | None = None
        self._seconds = 0.0

    def require(self) -> tuple[RenderedArtifact, str]:
        """Return ``(rendered, plain_text)``, reading the source the first time it is needed."""

        if self._loaded is None:
            started = perf_counter()
            raw_html = self._resolver.read_html(self._case.sha256)
            if raw_html is None:
                raise _SourceUnavailableError(self._case.external_id)
            rendered = render_source_document(
                source_system=cast(Literal["sample_a", "sample_b"], self._source_system),
                raw_html=raw_html,
            )
            self._loaded = (
                rendered,
                plain_text_from_safe_html(self._source_system, rendered.safe_html),
            )
            self._seconds = perf_counter() - started
        return self._loaded

    @property
    def was_read(self) -> bool:
        return self._loaded is not None

    @property
    def seconds(self) -> float:
        return self._seconds


_EVIDENCE_DIGEST_FIELDS: tuple[str, ...] = (
    "kind",
    "snippet",
    "char_start",
    "char_end",
    "line_start",
    "line_end",
    "source_hash",
    "body_grounded",
    "source_region",
)


ANCHOR_ANCHORED = "anchored"


ANCHOR_EXPECTED = "expected_unanchored"


ANCHOR_UNEXPECTED = "unexpected_unresolved"


ANCHOR_OTHER_DOCUMENT = "other_document"


def _evidence_digest_payload(item: InputEvidence) -> dict[str, object]:
    data = asdict(item)
    return {key: data[key] for key in _EVIDENCE_DIGEST_FIELDS}


def is_render_evidence(
    evidence: InputEvidence, render_sha256: str, member_hashes: Set[str]
) -> bool:
    """The evidence-selection contract shared by the importer and the anchor audit.

    Anchored evidence windows belong ONLY to the render document: a snippet attributable to
    ANOTHER family member's document is never re-anchored against -- or attributed to --
    the render document (it stays visible through that member's typed value / relation
    source). Evidence with an unknown hash keeps the standing behaviour and is passed on
    to :func:`classify_anchor`, which decides whether it may be searched in the render
    at all."""

    return (
        not evidence.source_hash
        or evidence.source_hash == render_sha256
        or not any(h == evidence.source_hash and h != render_sha256 for h in member_hashes)
    )


def field_render_evidence(field: InputField, case: InputCase) -> list[InputEvidence]:
    member_hashes = {mv.sha256 for mv in field.member_values}
    return [e for e in field.evidence if is_render_evidence(e, case.sha256, member_hashes)]


def relation_render_evidence(
    relation: InputRelation, case: InputCase, contributing: Sequence[Mapping[str, Any]]
) -> list[InputEvidence]:
    member_hashes = {
        str(entry.get("source_document_sha256") or "")
        for entry in contributing
        if entry.get("source_document_sha256")
    }
    return [e for e in relation.evidence if is_render_evidence(e, case.sha256, member_hashes)]


def classify_anchor(
    evidence: InputEvidence,
    plain_text: str,
    render_sha256: str,
    *,
    field_name: str | None = None,
    source_system: str | None = None,
) -> tuple[str, int | None, int | None]:
    """Anchor verified evidence in the rendered text; keep other-document evidence unanchored."""

    if evidence.source_hash and evidence.source_hash != render_sha256:
        return ANCHOR_OTHER_DOCUMENT, None, None
    char_start, char_end = _reanchor(plain_text, evidence)
    if char_start is not None:
        return ANCHOR_ANCHORED, char_start, char_end
    if evidence.body_grounded is not None:
        return (ANCHOR_UNEXPECTED if evidence.body_grounded else ANCHOR_EXPECTED), None, None
    if folded_contains(plain_text, evidence.snippet):
        return ANCHOR_UNEXPECTED, None, None
    return ANCHOR_EXPECTED, None, None


def _reanchor(plain_text: str, evidence: InputEvidence) -> tuple[int | None, int | None]:
    """Locate the provenance snippet in the rendered text; null offsets when it is not present."""

    (hit,) = build_anchor_map(plain_text, [evidence.snippet])
    if hit.found and hit.char_start is not None and hit.char_end is not None:
        return utf16_length(plain_text[: hit.char_start]), utf16_length(plain_text[: hit.char_end])
    return None, None
