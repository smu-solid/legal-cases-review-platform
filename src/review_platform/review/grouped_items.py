"""Build reviewer field groups and effective answer summaries."""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Literal, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.review.grouping import (
    GROUP_DEFINITIONS,
    GroupDefinition,
    display_field_label,
    item_kind,
)
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    Candidate,
    EvidenceWindow,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
)
from review_platform.review.projections import evidence_response
from review_platform.review.relation_display import (
    extracted_value,
    is_neutral_citation_field,
    is_reported_citation_field,
    is_title_field,
)
from review_platform.review.schemas import (
    AnchorUnavailableReason,
    CorrectedProvenanceSpan,
    FieldGroup,
    GroupItem,
    GroupItemStatus,
    GroupProgress,
    ItemAnswerSummary,
    MemberSourceValue,
)

# One reviewer-owned review unit of the reviewed case: its allowlisted group, the reviewer's
# assignment, the unit, its own subject (each unit has its own field-scoped subject), and the
# unit's ordered evidence windows.
_PreparedRow = tuple[GroupDefinition, Assignment, ReviewUnit, ReviewSubject, list[EvidenceWindow]]


class GroupedItemsMixin:
    @staticmethod
    def _has_annotation_draft(
        session: Session, tenant_id: uuid.UUID, assignment_id: uuid.UUID
    ) -> bool:
        return (
            session.scalar(
                select(AnnotationRevision.id)
                .where(
                    AnnotationRevision.tenant_id == tenant_id,
                    AnnotationRevision.assignment_id == assignment_id,
                    AnnotationRevision.state == "draft",
                )
                .limit(1)
            )
            is not None
        )

    def _build_group_items(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        prepared: list[_PreparedRow],
        item_anchor_by_unit: dict[uuid.UUID, str],
        anchor_unavailable_by_unit: dict[uuid.UUID, AnchorUnavailableReason],
        effective_offsets: dict[uuid.UUID, tuple[int, int]] | None = None,
        fallback_title: str,
    ) -> tuple[dict[str, list[GroupItem]], str | None, str | None, str]:
        """Build the per-group reviewer item list, the citation displays, and case title.

        ``extracted_value_display``/``extracted_value_raw`` come from the unit's own deterministic
        candidate (label ``"A"``, "the extracted value the reviewer judges" -- see
        ``real_import._add_candidates``), not the anchor subject: each field/relation has its own
        subject and its own candidate. ``case_title`` prefers the case-metadata title field's own
        extracted value when the reviewer owns it, since a per-field subject's ``display_title`` is
        not reliably the case title (real import sets it to the case title only when the *first*
        imported field/relation happens to carry one).
        """

        unit_ids = [unit.id for _group, _assignment, unit, _subject, _evidence in prepared]
        candidates_by_unit: dict[uuid.UUID, Candidate] = {
            candidate.review_unit_id: candidate
            for candidate in session.scalars(
                select(Candidate).where(
                    Candidate.tenant_id == tenant_id,
                    Candidate.review_unit_id.in_(unit_ids),
                    Candidate.label == "A",
                )
            )
        }
        items_by_group: dict[str, list[GroupItem]] = defaultdict(list)
        neutral_citation_display: str | None = None
        reported_citation_display: str | None = None
        case_title: str | None = None
        for group, assignment, unit, unit_subject, evidence in prepared:
            # Detected by field token alone, independent of which group the unit landed in -- both
            # citation fields live in case_metadata (see grouping.py), not a dedicated group, so
            # gating this on a group id would never match.
            if (
                is_neutral_citation_field(unit.field_name, unit.safe_field_label)
                and neutral_citation_display is None
            ):
                neutral_citation_display, _ = extracted_value(
                    candidates_by_unit.get(unit.id), fallback=unit_subject.display_title
                )
            elif (
                is_reported_citation_field(unit.field_name, unit.safe_field_label)
                and reported_citation_display is None
            ):
                reported_citation_display, _ = extracted_value(
                    candidates_by_unit.get(unit.id), fallback=unit_subject.display_title
                )
            if (
                group.group_id == "case_metadata"
                and case_title is None
                and is_title_field(unit.field_name, unit.safe_field_label)
            ):
                case_title = unit_subject.display_title
            latest_answer = session.scalar(
                select(ReviewItemAnswer)
                .where(
                    ReviewItemAnswer.tenant_id == tenant_id,
                    ReviewItemAnswer.assignment_id == assignment.id,
                )
                .order_by(ReviewItemAnswer.revision_no.desc())
                .limit(1)
            )
            answer_summary = (
                ItemAnswerSummary(
                    state=cast(Literal["draft", "submitted"], latest_answer.state),
                    value_correct=latest_answer.value_correct,
                    provenance_correct=latest_answer.provenance_correct,
                    corrected_value_display=latest_answer.corrected_value_display
                    or (
                        latest_answer.corrected_value_json
                        if isinstance(latest_answer.corrected_value_json, str)
                        else None
                    ),
                    comment=latest_answer.comment,
                    failure_reason=latest_answer.failure_reason,
                    corrected_provenance_spans=[
                        CorrectedProvenanceSpan.model_validate(span)
                        for span in latest_answer.corrected_provenance_spans_json
                    ],
                )
                if latest_answer is not None
                else None
            )
            if assignment.status == "submitted":
                status: GroupItemStatus = "submitted"
            elif (latest_answer is not None and latest_answer.state == "draft") or (
                self._has_annotation_draft(session, tenant_id, assignment.id)
            ):
                status = "draft"
            else:
                status = "not_started"
            candidate = candidates_by_unit.get(unit.id)
            is_missing = unit.extraction_state == "missing"
            if is_missing:
                # A missing unit carries zero Candidate rows by invariant -- render the explicit
                # "no value extracted" state rather than falling through to the subject's display
                # title (which extracted_value would otherwise use as its no-candidate fallback,
                # indistinguishable from a real extracted value).
                extracted_display, extracted_raw = "No value extracted", None
            else:
                extracted_display, extracted_raw = extracted_value(
                    candidate, fallback=unit_subject.display_title, review_kind=unit.review_kind
                )
            subject_attrs = unit_subject.attributes_json or {}
            raw_member_values = subject_attrs.get("member_values") or []
            items_by_group[group.group_id].append(
                GroupItem(
                    review_unit_id=unit.id,
                    assignment_id=assignment.id,
                    item_id=str(unit.id),
                    item_label=display_field_label(unit.field_name, unit.safe_field_label),
                    item_kind=item_kind(unit.review_kind),
                    member_values=[
                        MemberSourceValue(
                            case=str(entry.get("case") or ""),
                            source_system=str(entry.get("source_system") or ""),
                            # Preview truncation happens HERE (presentation), never in the
                            # persisted attributes or the input digest.
                            value=str(entry.get("value") or "")[:300],
                            value_truncated=len(str(entry.get("value") or "")) > 300,
                            source_document_id=entry.get("source_document_id"),
                            source_sha256=entry.get("source_sha256"),
                            evidence=list(entry.get("evidence") or []),
                        )
                        for entry in raw_member_values
                        if isinstance(entry, dict)
                    ],
                    cross_source_disagreement=bool(subject_attrs.get("cross_source_disagreement")),
                    extracted_value_display=extracted_display,
                    extracted_value_raw=extracted_raw,
                    source_anchor_id=item_anchor_by_unit.get(unit.id),
                    source_anchor_unavailable_reason=anchor_unavailable_by_unit.get(unit.id),
                    evidence_window_ids=[item.id for item in evidence],
                    evidence_windows=[
                        evidence_response(item, subject_attrs, effective_offsets=effective_offsets)
                        for item in evidence
                    ],
                    status=status,
                    answer_summary=answer_summary,
                    lock_version=assignment.lock_version,
                    extraction_state=cast(Literal["present", "missing"], unit.extraction_state),
                )
            )
        return (
            items_by_group,
            neutral_citation_display,
            reported_citation_display,
            case_title or fallback_title,
        )

    @staticmethod
    def _assemble_field_groups(
        items_by_group: dict[str, list[GroupItem]], group_anchor_by_id: dict[str, str]
    ) -> tuple[list[FieldGroup], list[GroupProgress]]:
        """Order populated groups by the allowlist and compute per-group completion counts."""

        field_groups: list[FieldGroup] = []
        group_progress: list[GroupProgress] = []
        for definition in GROUP_DEFINITIONS:
            items = items_by_group.get(definition.group_id, [])
            if not items:
                continue
            completed = sum(1 for item in items if item.status == "submitted")
            field_groups.append(
                FieldGroup(
                    group_id=definition.group_id,
                    group_label=definition.group_label,
                    group_kind=definition.group_kind,
                    description=definition.description,
                    order=definition.order,
                    item_count=len(items),
                    completed_count=completed,
                    group_anchor_id=group_anchor_by_id.get(definition.group_id),
                    items=items,
                )
            )
            group_progress.append(
                GroupProgress(
                    group_id=definition.group_id,
                    item_count=len(items),
                    completed_count=completed,
                )
            )
        return field_groups, group_progress
