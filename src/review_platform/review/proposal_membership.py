"""Atomic private combine/separate operations preserve originals and superseded membership."""

from __future__ import annotations

import uuid

from sqlalchemy import delete
from sqlalchemy.orm import Session

from review_platform.common.errors import APIError
from review_platform.review.models import AdjudicationDraft
from review_platform.review.models.proposal_adjudication import ProposalAdjudicationItem
from review_platform.review.proposal_adjudication_guards import locked_participation
from review_platform.review.proposal_adjudication_store import editable_item
from review_platform.review.schemas import AdjudicationCaseWorkspace
from review_platform.review.schemas.proposal_adjudication import ProposalMembershipChange


def change_membership(
    session: Session,
    *,
    workspace: AdjudicationCaseWorkspace,
    actor: uuid.UUID,
    items: list[ProposalAdjudicationItem],
    body: ProposalMembershipChange,
) -> list[uuid.UUID]:
    if not body.confirm:
        raise APIError(
            422,
            "membership_confirmation_required",
            "Confirmation required",
            "Confirm the membership change and clearing affected drafts.",
        )
    source = editable_item(items, body.item_id, body.expected_version)
    affected, extracted_id = _affected_items(source, items, body)
    if extracted_id:
        _invalidate_extracted(session, workspace, actor, source, extracted_id, body)
    ids = list(dict.fromkeys(pid for item in affected for pid in item.proposal_ids_json))
    if body.action == "separate" and len(ids) < 2 and not extracted_id:
        raise APIError(
            422, "nothing_to_separate", "Nothing to separate", "This item has one proposal."
        )
    for item in affected:
        item.state = "superseded"
        item.draft_json = None
        item.lock_version += 1
    session.flush()  # release the active extracted-target unique key before its replacement
    partitions = [ids] if body.action == "combine" else [[pid] for pid in ids]
    new_ids = []
    for members in partitions:
        item = ProposalAdjudicationItem(
            id=uuid.uuid4(),
            tenant_id=source.tenant_id,
            campaign_id=source.campaign_id,
            case_id=source.case_id,
            group_id=source.group_id,
            adjudicator_id=actor,
            extracted_adjudication_id=extracted_id if body.action == "combine" else None,
            proposal_ids_json=members,
            origin="combined" if body.action == "combine" else "separated",
            state="pending",
            lock_version=1,
            final_provenance_json=[],
        )
        session.add(item)
        new_ids.append(item.id)
    session.flush()
    return new_ids


def _affected_items(
    source: ProposalAdjudicationItem,
    items: list[ProposalAdjudicationItem],
    body: ProposalMembershipChange,
) -> tuple[list[ProposalAdjudicationItem], uuid.UUID | None]:
    affected = [source]
    extracted_id = source.extracted_adjudication_id
    if body.action == "combine":
        if bool(body.target_item_id) == bool(body.target_extracted_id):
            raise APIError(422, "invalid_target", "Choose one target", "Select exactly one item.")
        if body.target_item_id:
            target = editable_item(items, body.target_item_id, body.target_version or 0)
            if target.id == source.id or target.group_id != source.group_id:
                raise APIError(
                    422, "invalid_target", "Invalid target", "Choose another item in this group."
                )
            if extracted_id and target.extracted_adjudication_id:
                raise APIError(
                    422,
                    "invalid_target",
                    "Invalid target",
                    "Two extracted items cannot be combined through proposal grouping.",
                )
            extracted_id = extracted_id or target.extracted_adjudication_id
            affected.append(target)
        else:
            if extracted_id or any(
                i.state != "superseded" and i.extracted_adjudication_id == body.target_extracted_id
                for i in items
            ):
                raise APIError(
                    412,
                    "adjudication_membership_changed",
                    "Refresh required",
                    "The target membership changed. Refresh before combining.",
                )
            extracted_id = body.target_extracted_id
    elif body.target_item_id or body.target_extracted_id:
        raise APIError(
            422, "invalid_target", "Invalid target", "Separation does not take a target."
        )
    return affected, extracted_id


def _invalidate_extracted(
    session: Session,
    workspace: AdjudicationCaseWorkspace,
    actor: uuid.UUID,
    source: ProposalAdjudicationItem,
    extracted_id: uuid.UUID,
    body: ProposalMembershipChange,
) -> None:
    group = next(
        (
            g
            for g in workspace.field_groups
            if any(i.adjudication_id == extracted_id for i in g.items)
        ),
        None,
    )
    if group is None or group.group_id != source.group_id:
        raise APIError(
            403,
            "invalid_target",
            "Target unavailable",
            "Select an assigned item in this group.",
        )
    field = next(i for i in group.items if i.adjudication_id == extracted_id)
    if field.submitted_reviews < field.required_reviews:
        raise APIError(
            409,
            "reviews_incomplete",
            "Reviews incomplete",
            "Required field reviews are pending.",
        )
    participation = locked_participation(session, source.tenant_id, actor, extracted_id)
    if (
        body.target_extracted_id
        and participation.membership_version != body.target_membership_version
    ):
        raise APIError(
            412,
            "adjudication_membership_changed",
            "Refresh required",
            "The target membership changed. Refresh before combining.",
        )
    participation.membership_version += 1
    session.execute(
        delete(AdjudicationDraft).where(
            AdjudicationDraft.tenant_id == source.tenant_id,
            AdjudicationDraft.adjudication_id == extracted_id,
            AdjudicationDraft.saved_by == actor,
        )
    )
