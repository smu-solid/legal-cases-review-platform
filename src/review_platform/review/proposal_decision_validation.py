"""Resolve explicit proposal decisions to a value and validated supporting source ranges."""

from __future__ import annotations

import uuid

from review_platform.common.errors import APIError
from review_platform.review.proposal_validation import source_version, validate_proposal
from review_platform.review.schemas import (
    AdjudicationCaseWorkspace,
    AdjudicationWorkspaceItem,
    PseudonymousGroupedSubmission,
)
from review_platform.review.schemas.proposal_adjudication import (
    AdjudicationProposal,
    ProposalDecision,
    ProposalDecisionItem,
)
from review_platform.review.schemas.proposals import ProposalInput, ProposalSpan


def resolve_proposal_decision(
    decision: ProposalDecision,
    item: ProposalDecisionItem,
    workspace: AdjudicationCaseWorkspace,
    *,
    submit: bool,
    verified_snapshot_ids: set[uuid.UUID] | None = None,
) -> tuple[str | None, list[ProposalSpan]]:
    field, proposal, submission = _preferred_members(decision, item, workspace, submit)
    needs_note = bool(decision.corrected_value.strip()) or decision.outcome in {
        "all_wrong",
        "unsupported_or_not_locatable",
        "exceptional_skip",
    }
    if submit and needs_note and not decision.comment.strip():
        raise APIError(
            422, "comment_required", "Note required", "Explain this decision or correction."
        )
    value = decision.corrected_value.strip() or None
    spans = list(decision.provenance)
    rejected = decision.outcome in {"unsupported_or_not_locatable", "exceptional_skip"} or (
        decision.outcome == "all_wrong" and value is None
    )
    if submit and rejected and value:
        raise APIError(
            422,
            "conflicting_final_value",
            "Choose a value decision",
            "Clear the corrected value to reject this item, or choose a value decision.",
        )
    if not value and not rejected:
        if proposal:
            value, inherited = proposal.value, proposal.provenance
        elif submission and field:
            value, inherited = _submission_value_and_spans(submission, field, workspace)
        else:
            value = item.proposals[0].value if item.proposals else None
            inherited = [s for p in item.proposals for s in p.provenance]
        if not spans:
            spans = list(
                {
                    (s.source_snapshot_id, s.source_version, s.char_start, s.char_end): s
                    for s in inherited
                }.values()
            )
    # Validate even draft-supplied spans, but incomplete drafts remain permitted.
    validate_proposal(
        ProposalInput(
            group_id=item.group_id, value=value or "", note=decision.comment, provenance=spans
        ),
        submitted=submit and not rejected,
        content=workspace.source_render.content,
        snapshot_id=workspace.source_render.source_snapshot_id,
        verified_snapshot_ids=verified_snapshot_ids,
    )
    return (None, []) if rejected else (value, spans)


def _preferred_members(
    decision: ProposalDecision,
    item: ProposalDecisionItem,
    workspace: AdjudicationCaseWorkspace,
    submit: bool,
) -> tuple[
    AdjudicationWorkspaceItem | None,
    AdjudicationProposal | None,
    PseudonymousGroupedSubmission | None,
]:
    field = next(
        (
            i
            for g in workspace.field_groups
            for i in g.items
            if i.adjudication_id == item.extracted_adjudication_id
        ),
        None,
    )
    proposal = next((p for p in item.proposals if p.id == decision.preferred_proposal_id), None)
    submission = next(
        (
            s
            for s in (field.submissions if field else [])
            if s.submission_id == decision.preferred_submission_id
        ),
        None,
    )
    invalid = (
        (decision.preferred_proposal_id is not None and proposal is None)
        or (decision.preferred_submission_id is not None and submission is None)
        or (
            decision.preferred_proposal_id is not None
            and decision.preferred_submission_id is not None
        )
        or (
            decision.outcome != "reviewer_preferred"
            and (proposal is not None or submission is not None)
        )
    )
    if invalid or (
        submit and decision.outcome == "reviewer_preferred" and not proposal and not submission
    ):
        raise APIError(
            422,
            "proposal_preference_invalid",
            "Choose a specific proposal",
            "Select a proposal or original submission belonging to this item.",
        )
    return field, proposal, submission


def _submission_value_and_spans(
    submission: PseudonymousGroupedSubmission,
    field: AdjudicationWorkspaceItem,
    workspace: AdjudicationCaseWorkspace,
) -> tuple[str | None, list[ProposalSpan]]:
    value = (
        submission.corrected_value_display
        if not submission.value_correct
        else field.extracted_value_display
    )
    raw = submission.corrected_provenance_spans
    inherited = [
        ProposalSpan(
            source_snapshot_id=workspace.source_render.source_snapshot_id,
            source_version=source_version(workspace.source_render.content),
            char_start=s.char_start,
            char_end=s.char_end,
        )
        for s in raw
    ]
    if not inherited:
        inherited = [
            ProposalSpan(
                source_snapshot_id=workspace.source_render.source_snapshot_id,
                source_version=source_version(workspace.source_render.content),
                char_start=a.char_start,
                char_end=a.char_end,
            )
            for a in workspace.source_render.anchors
            if a.anchor_id == field.source_anchor_id
            and a.char_start is not None
            and a.char_end is not None
        ]
    return value, inherited
