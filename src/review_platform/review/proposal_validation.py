"""Validate marked provenance against the exact authorized browser text representation."""

from __future__ import annotations

import hashlib
import uuid

from review_platform.common.errors import APIError
from review_platform.review.models.proposals import ReviewerAddedProposal
from review_platform.review.schemas.grouped_bundle import ReviewerGroupingBundle
from review_platform.review.schemas.proposals import ProposalInput


def source_version(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_proposal(
    body: ProposalInput,
    *,
    submitted: bool,
    content: str,
    snapshot_id: uuid.UUID,
    verified_snapshot_ids: set[uuid.UUID] | None = None,
) -> None:
    if submitted and (not body.value.strip() or not body.provenance):
        raise APIError(
            422,
            "proposal_incomplete",
            "Incomplete addition",
            "A nonblank value and marked supporting provenance are required.",
        )
    version = source_version(content)
    # DOM Range offsets use UTF-16 code units. Reject ranges splitting surrogate pairs as well
    # as out-of-bounds, blank, duplicate, stale-version, or foreign-document selections.
    encoded = content.encode("utf-16-le")
    seen: set[tuple[uuid.UUID, int, int]] = set()
    for span in body.provenance:
        valid = (
            span.source_snapshot_id in (verified_snapshot_ids or {snapshot_id})
            and span.source_version == version
            and span.char_end * 2 <= len(encoded)
            and (span.source_snapshot_id, span.char_start, span.char_end) not in seen
        )
        try:
            selected = encoded[span.char_start * 2 : span.char_end * 2].decode("utf-16-le")
            valid = valid and bool(selected.strip())
        except UnicodeDecodeError:
            valid = False
        if not valid:
            raise APIError(
                422,
                "proposal_provenance_invalid",
                "Invalid marked provenance",
                "Mark supporting text in the current source document and version.",
            )
        seen.add((span.source_snapshot_id, span.char_start, span.char_end))


def validate_proposal_write(
    bundle: ReviewerGroupingBundle,
    proposal: ReviewerAddedProposal | None,
    body: ProposalInput,
    state: str,
    expected_version: int,
) -> None:
    group = next((g for g in bundle.field_groups if g.group_id == body.group_id), None)
    if bundle.case_submitted:
        raise APIError(409, "case_submitted", "Case submitted", "Your case is read-only.")
    if group is None or group.add_item_label is None:
        raise APIError(
            403,
            "proposal_group_ineligible",
            "Group unavailable",
            "Additions require an eligible group assigned to you in this campaign.",
        )
    if proposal is not None and proposal.group_id != body.group_id:
        raise APIError(
            409, "proposal_scope_immutable", "Invalid group", "An item cannot move groups."
        )
    if proposal is not None and proposal.state != "draft":
        raise APIError(409, "proposal_locked", "Item read-only", "This item cannot be changed.")
    actual_version = proposal.lock_version if proposal is not None else 1
    if actual_version != expected_version:
        raise APIError(412, "precondition_failed", "Stale version", "Refresh before saving again.")
    if state != "removed":
        validate_proposal(
            body,
            submitted=state == "submitted",
            content=bundle.source_render.content,
            snapshot_id=bundle.source_render.source_snapshot_id,
            verified_snapshot_ids=set(bundle.proposal_source_snapshot_ids),
        )
