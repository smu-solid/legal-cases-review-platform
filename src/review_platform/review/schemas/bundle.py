"""Candidate-comparison assignment bundle schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field, JsonValue

from review_platform.review.schemas.assignment import AssignmentSummary
from review_platform.review.schemas.common import ReviewKind, ReviewModel, SubjectKind


class ReviewSubjectResponse(ReviewModel):
    id: uuid.UUID
    subject_kind: SubjectKind
    external_subject_id: str
    display_title: str
    display_subtitle: str | None
    source_snapshot_id: uuid.UUID
    source_version: str | None
    primary_source_ref: str
    attributes: dict[str, JsonValue]


class CandidateResponse(ReviewModel):
    id: uuid.UUID
    label: Literal["A", "B"]
    value: JsonValue
    verdict: str
    rationale: str
    supporting_quote: str | None


class GroundedIn(ReviewModel):
    """The document an evidence window was taken from, named so a reviewer can tell it apart.

    Additive: resolved from the review subject's own persisted member/relation observations, so it
    never reaches for a document outside this unit's family. Deliberately carries no internal case
    identifier -- reviewer blindness forbids them in reviewer payloads; the document hash, its
    source system and (for citation fields) the member's citation identify the document.
    """

    source_sha256: str
    source_system: str | None = None
    citation: str | None = None


class EvidenceWindowResponse(ReviewModel):
    id: uuid.UUID
    kind: str
    snippet: str
    line_start: int | None
    line_end: int | None
    char_start: int | None
    char_end: int | None
    source_sha256: str
    #: Where the window anchors against the unit's rendered document: ``anchored``,
    #: ``expected_unanchored``, ``unexpected_unresolved`` or ``other_document`` (the evidence lives
    #: in another document of the same family); ``None`` for windows imported before anchor
    #: identity was recorded.
    anchor_status: str | None = None
    grounded_in: GroundedIn | None = None


class CandidateAssessmentInput(ReviewModel):
    candidate_id: uuid.UUID
    assessment: Literal["correct", "incorrect", "not_assessable"]


class AnnotationInput(ReviewModel):
    outcome: Literal[
        "candidate_a_preferred",
        "candidate_b_preferred",
        "equivalent_supported",
        "both_wrong",
        "unsupported_or_not_locatable",
        "exceptional_skip",
    ]
    assessments: list[CandidateAssessmentInput] = Field(min_length=2, max_length=2)
    corrected_value: JsonValue | None = None
    corrected_value_display: str | None = Field(default=None, max_length=10_000)
    comment: str | None = Field(default=None, max_length=20_000)
    evidence_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)


class AnnotationRevisionResponse(ReviewModel):
    id: uuid.UUID
    assignment_id: uuid.UUID
    revision_no: int
    state: Literal["draft", "submitted"]
    outcome: str
    corrected_value: JsonValue | None
    corrected_value_display: str | None
    comment: str | None
    assessments: list[CandidateAssessmentInput]
    evidence_ids: list[uuid.UUID]
    created_at: datetime
    lock_version: int
    replayed: bool = False


class CommentRequirements(ReviewModel):
    required_for_outcomes: list[str]
    required_for_correction: bool = True


class RenderHints(ReviewModel):
    schema_version: Literal["render-hints/v1"] = "render-hints/v1"
    layout: Literal["candidate_comparison"] = "candidate_comparison"
    value_format: Literal["text"] = "text"


class AssignmentBundle(ReviewModel):
    assignment: AssignmentSummary
    review_subject: ReviewSubjectResponse
    review_kind: ReviewKind
    question: str
    candidates: list[CandidateResponse]
    evidence_windows: list[EvidenceWindowResponse]
    prior_self_draft: AnnotationRevisionResponse | None
    allowed_actions: list[Literal["save_draft", "submit", "renew", "release"]]
    comment_requirements: CommentRequirements
    render_hints: RenderHints
    schema_version: Literal["assignment-bundle/v1"] = "assignment-bundle/v1"
