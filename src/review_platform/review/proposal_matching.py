"""Deterministic, pairwise matching of immutable reviewer-added proposals."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from itertools import combinations

from review_platform.review.schemas.proposals import ProposalSpan


@dataclass(frozen=True)
class ProposalMatchInput:
    id: uuid.UUID
    tenant_id: uuid.UUID
    campaign_id: uuid.UUID
    case_id: str
    group_id: str
    value: str
    provenance: tuple[ProposalSpan, ...]


def normalized_proposal_value(value: str) -> str:
    return " ".join(value.split()).casefold()


def provenance_key(proposal: ProposalMatchInput) -> frozenset[tuple[uuid.UUID, str, int, int]]:
    return frozenset(
        (span.source_snapshot_id, span.source_version, span.char_start, span.char_end)
        for span in proposal.provenance
    )


def matching_reasons(left: ProposalMatchInput, right: ProposalMatchInput) -> tuple[str, ...]:
    if (left.tenant_id, left.campaign_id, left.case_id, left.group_id) != (
        right.tenant_id,
        right.campaign_id,
        right.case_id,
        right.group_id,
    ):
        return ()
    reasons = []
    value = normalized_proposal_value(left.value)
    if value and value == normalized_proposal_value(right.value):
        reasons.append("normalized_value")
    spans = provenance_key(left)
    if spans and spans == provenance_key(right):
        reasons.append("complete_provenance")
    return tuple(reasons)


def automatic_proposal_groups(
    proposals: list[ProposalMatchInput],
) -> list[list[ProposalMatchInput]]:
    """Stable first-fit cliques: every member matches every other member.

    UUID order is deliberate: timestamps and database return order cannot change membership.
    A bridge can join the first compatible group, but cannot merge incompatible endpoints.
    """
    groups: list[list[ProposalMatchInput]] = []
    for proposal in sorted(proposals, key=lambda p: str(p.id)):
        for group in groups:
            if all(matching_reasons(proposal, member) for member in group):
                group.append(proposal)
                break
        else:
            groups.append([proposal])
    return groups


def proposal_group_reasons(proposals: list[ProposalMatchInput]) -> list[str]:
    return sorted(
        {reason for a, b in combinations(proposals, 2) for reason in matching_reasons(a, b)}
    )
