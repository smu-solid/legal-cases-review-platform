"""Effective cited-case values from the existing reviewer-private grouped bundle."""

from __future__ import annotations

import uuid

from review_platform.review.citation_duplicates import CitationItem, SpanKey
from review_platform.review.proposal_matching import normalized_proposal_value as normalize
from review_platform.review.proposal_validation import source_version
from review_platform.review.schemas.citation_duplicates import ReviewerProvenanceContext
from review_platform.review.schemas.grouped_bundle import ItemAnswerSummary, ReviewerGroupingBundle
from review_platform.review.schemas.proposals import ProposalInput
from review_platform.review.schemas.submissions import ReviewItemAnswerInput


def citation_inventory(
    bundle: ReviewerGroupingBundle, group_id: str = "cited_cases"
) -> list[CitationItem]:
    items = []
    for group in bundle.field_groups:
        if group.group_id != group_id:
            continue
        for item in group.items:
            if item.extraction_state == "missing" and not item.answer_summary:
                continue
            raw = item.extracted_value_raw
            raw = raw if isinstance(raw, dict) else {}
            aliases = {
                str(raw[k])
                for k in (
                    "to_case_ext",
                    "resolved_citation_neutral",
                    "resolved_citation_reporter",
                    "resolved_title",
                )
                if raw.get(k)
            }
            summary = item.answer_summary
            changed = bool(summary and summary.value_correct is False)
            replacement = (summary.corrected_value_display or "").strip() if summary else ""
            value = replacement if changed and replacement else item.extracted_value_display
            current = CitationItem(
                item.review_unit_id,
                value,
                aliases=aliases if not changed else set(),
                identity=str(raw["to_case_id_int"])
                if raw.get("to_case_id_int") and not changed
                else None,
                incomplete=changed and not bool(replacement),
                submitted=item.status == "submitted",
                authored=changed,
                original_values={item.extracted_value_display, *aliases}
                if item.extraction_state != "missing"
                else set(),
            )
            kind = (
                "Your correction" if summary and summary.corrected_provenance_spans else "Extracted"
            )
            current.spans = _spans(bundle, item.review_unit_id, kind)
            items.append(current)
    for proposal in bundle.reviewer_additions:
        if proposal.group_id == group_id:
            current = proposed_item(bundle, proposal.id, proposal)
            current.submitted = proposal.state == "submitted"
            items.append(current)
    # Only exact aliases supplied by authoritative imported relations establish an identity.
    aliases_to_ids: dict[str, set[str]] = {}
    for current in items:
        if current.identity:
            for value in current.values():
                aliases_to_ids.setdefault(value, set()).add(current.identity)
    for current in items:
        current.possible_aliases = name_aliases(bundle, current.value)
        current.identity = current.identity or resolved_identity(bundle, current.value)
        known = aliases_to_ids.get(normalize(current.value), set())
        if not current.identity and len(known) == 1:
            current.identity = next(iter(known))
    return items


def _spans(bundle: ReviewerGroupingBundle, item_id: uuid.UUID, kind: str) -> set[SpanKey]:
    return {
        (str(s.source_snapshot_id), s.source_version, s.char_start, s.char_end)
        for s in bundle.provenance_context
        if s.item_id == item_id and s.kind == kind
    }


def proposed_item(
    bundle: ReviewerGroupingBundle, item_id: uuid.UUID, body: ProposalInput
) -> CitationItem:
    verified = set(bundle.proposal_source_snapshot_ids) | {bundle.source_render.source_snapshot_id}
    marked_text = []
    if body.provenance:
        content = bundle.source_render.content
        version = source_version(content)
        encoded = content.encode("utf-16-le")
        for span in body.provenance:
            if (
                span.source_snapshot_id in verified
                and span.source_version == version
                and 0 <= span.char_start < span.char_end <= len(encoded) // 2
            ):
                try:
                    marked_text.append(
                        encoded[span.char_start * 2 : span.char_end * 2].decode("utf-16-le")
                    )
                except UnicodeDecodeError:
                    continue
    return CitationItem(
        item_id,
        body.value,
        authored=True,
        reviewer_added=True,
        provenance_text=tuple(marked_text),
        identity=resolved_identity(bundle, body.value),
        possible_aliases=name_aliases(bundle, body.value),
        spans={
            (
                str(
                    bundle.source_render.source_snapshot_id
                    if s.source_snapshot_id in verified
                    else s.source_snapshot_id
                ),
                s.source_version,
                s.char_start,
                s.char_end,
            )
            for s in body.provenance
        },
    )


def resolved_identity(bundle: ReviewerGroupingBundle, value: str) -> str | None:
    identities = set()
    for group in bundle.field_groups:
        if group.group_id != "cited_cases":
            continue
        for item in group.items:
            raw = item.extracted_value_raw
            if not isinstance(raw, dict) or not raw.get("to_case_id_int"):
                continue
            aliases = [
                raw.get(k)
                for k in (
                    "to_case_ext",
                    "resolved_citation_neutral",
                    "resolved_citation_reporter",
                )
            ]
            if normalize(value) in {normalize(str(a)) for a in aliases if a}:
                identities.add(str(raw["to_case_id_int"]))
    return next(iter(identities)) if len(identities) == 1 else None


def apply_answer_overrides(
    bundle: ReviewerGroupingBundle, overrides: dict[uuid.UUID, ReviewItemAnswerInput]
) -> None:
    for group in bundle.field_groups:
        if group.group_id not in {"cited_cases", "statutes_cited"}:
            continue
        for item in group.items:
            answer = overrides.get(item.review_unit_id)
            if answer is None or item.status == "submitted":
                continue
            item.answer_summary = ItemAnswerSummary(
                state="draft",
                value_correct=answer.value_correct,
                provenance_correct=answer.provenance_correct,
                corrected_value_display=answer.corrected_value_display
                or (answer.corrected_value if isinstance(answer.corrected_value, str) else None),
                corrected_provenance_spans=answer.corrected_provenance_spans,
            )
            bundle.provenance_context = [
                c
                for c in bundle.provenance_context
                if c.item_id != item.review_unit_id or c.kind != "Your correction"
            ]
            for span in answer.corrected_provenance_spans:
                if (
                    span.source_version is not None
                    and span.source_snapshot_id in bundle.proposal_source_snapshot_ids
                    and span.source_version == bundle.proposal_source_version
                ):
                    bundle.provenance_context.append(
                        ReviewerProvenanceContext(
                            item_id=item.review_unit_id,
                            group_id=group.group_id,
                            value=item.answer_summary.corrected_value_display
                            or item.extracted_value_display,
                            kind="Your correction",
                            source_snapshot_id=bundle.source_render.source_snapshot_id,
                            source_version=span.source_version,
                            char_start=span.char_start,
                            char_end=span.char_end,
                        )
                    )


def name_aliases(bundle: ReviewerGroupingBundle, value: str) -> set[str]:
    matches: set[str] = set()
    for group in bundle.field_groups:
        if group.group_id != "cited_cases":
            continue
        for item in group.items:
            raw = item.extracted_value_raw
            if not isinstance(raw, dict) or not raw.get("resolved_title"):
                continue
            names = {normalize(str(raw["resolved_title"]))}
            citations = {
                normalize(str(raw[k]))
                for k in ("to_case_ext", "resolved_citation_neutral", "resolved_citation_reporter")
                if raw.get(k)
            }
            if normalize(value) in names:
                matches.update(citations)
            elif normalize(value) in citations:
                matches.update(names)
    return matches
