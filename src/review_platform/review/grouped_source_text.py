"""Render full source text or evidence snippets with bounded navigation anchors."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from review_platform.common.text_coordinates import utf16_length
from review_platform.review.grouped_items import _PreparedRow
from review_platform.review.grouping import (
    display_field_label,
)
from review_platform.review.models import EvidenceWindow
from review_platform.review.schemas import (
    AnchorUnavailableReason,
    SourceAnchor,
    SourceRender,
)
from review_platform.review.source_safety import (
    MAX_SOURCE_RENDER_ANCHORS,
    MAX_SOURCE_RENDER_CHARS,
    clamp_snippet,
    fit_block,
    truncate_to,
)


def unanchored_reason(evidence: Sequence[EvidenceWindow]) -> AnchorUnavailableReason:
    """Why no window of a unit could be highlighted, told apart honestly.

    When every window with a recorded anchor status says ``other_document``, the evidence is real
    and intact -- it lives in another document of the family -- so the reviewer must not be told
    the anchor is unresolved. Only a genuinely unresolved anchor keeps that word.
    """
    statuses = {item.anchor_status for item in evidence if item.anchor_status is not None}
    if (
        statuses
        and statuses <= {"other_document", "expected_unanchored"}
        and "other_document" in statuses
    ):
        return "other_document"
    return "anchor_unresolved"


class GroupedSourceTextMixin:
    @staticmethod
    def _build_source_render_from_full_text(
        prepared: list[_PreparedRow],
        source_snapshot_id: uuid.UUID,
        plain_text: str,
        effective_offsets: dict[uuid.UUID, tuple[int, int]] | None = None,
    ) -> tuple[
        SourceRender,
        dict[uuid.UUID, str],
        dict[uuid.UUID, AnchorUnavailableReason],
        dict[str, str],
    ]:
        """Render the case's full document text, anchored by each unit's own evidence offsets.

        Prefer a valid stored evidence offset. For old reported-citation windows, a verified
        display-only header offset can supply an anchor when no stored offset is usable. An
        unresolved offset is distinguished from one beyond the truncation boundary, so the
        reviewer-facing notice stays accurate.
        """

        truncated = len(plain_text) > MAX_SOURCE_RENDER_CHARS
        content = truncate_to(plain_text, MAX_SOURCE_RENDER_CHARS)
        content_len = utf16_length(content)

        anchors: list[SourceAnchor] = []
        item_anchor_by_unit: dict[uuid.UUID, str] = {}
        anchor_unavailable_by_unit: dict[uuid.UUID, AnchorUnavailableReason] = {}
        group_anchor_by_id: dict[str, str] = {}
        omitted_anchor_count = 0

        for group, _assignment, unit, _unit_subject, evidence in prepared:
            if not evidence:
                anchor_unavailable_by_unit[unit.id] = "no_evidence"
                continue
            if len(anchors) >= MAX_SOURCE_RENDER_ANCHORS:
                anchor_unavailable_by_unit[unit.id] = "anchor_budget_exhausted"
                omitted_anchor_count += 1
                continue
            window = next(
                (
                    item
                    for item in evidence
                    if item.char_start is not None
                    and item.char_end is not None
                    and 0 <= item.char_start < item.char_end <= content_len
                ),
                None,
            )
            if window is None and effective_offsets:
                window = next(
                    (
                        item
                        for item in evidence
                        if item.id in effective_offsets
                        and effective_offsets[item.id][1] <= content_len
                    ),
                    None,
                )
            if window is None:
                offset_beyond_boundary = truncated and any(
                    item.char_start is not None
                    or (effective_offsets and item.id in effective_offsets)
                    for item in evidence
                )
                anchor_unavailable_by_unit[unit.id] = (
                    "source_truncated" if offset_beyond_boundary else unanchored_reason(evidence)
                )
                if offset_beyond_boundary:
                    omitted_anchor_count += 1
                continue
            start, end = (
                (window.char_start, window.char_end)
                if window.char_start is not None and window.char_end is not None
                else (effective_offsets or {})[window.id]
            )
            if group.group_id not in group_anchor_by_id:
                group_anchor_id = f"group:{group.group_id}"
                anchors.append(
                    SourceAnchor(
                        anchor_id=group_anchor_id,
                        group_id=group.group_id,
                        char_start=start,
                        char_end=start,
                        scroll_hint="start",
                        label=group.group_label,
                    )
                )
                group_anchor_by_id[group.group_id] = group_anchor_id
            item_anchor_id = f"unit:{unit.id}"
            anchors.append(
                SourceAnchor(
                    anchor_id=item_anchor_id,
                    review_unit_id=unit.id,
                    group_id=group.group_id,
                    item_id=str(unit.id),
                    char_start=start,
                    char_end=end,
                    scroll_hint="center",
                    label=display_field_label(unit.field_name, unit.safe_field_label),
                )
            )
            item_anchor_by_unit[unit.id] = item_anchor_id

        source_render = SourceRender(
            source_snapshot_id=source_snapshot_id,
            render_mode="safe_text",
            content=content,
            anchors=anchors,
            truncated=truncated,
            omitted_anchor_count=omitted_anchor_count,
        )
        return source_render, item_anchor_by_unit, anchor_unavailable_by_unit, group_anchor_by_id

    @staticmethod
    def _build_source_render_from_snippets(
        prepared: list[_PreparedRow], source_snapshot_id: uuid.UUID
    ) -> tuple[
        SourceRender,
        dict[uuid.UUID, str],
        dict[uuid.UUID, AnchorUnavailableReason],
        dict[str, str],
    ]:
        """Fallback render for a case with no source-render artifact (synthetic fixtures).

        Assembles a safe-text render from evidence snippets and anchor offsets INTO it, since no
        full document text exists to render or anchor against. The stored evidence offsets address
        an absent original document under a specific text view and must not be reused here; an item
        with no evidence yields no anchor. Snippets and the
        assembled body are bounded (source_safety): once the character or anchor budget is reached,
        later units render no anchor — the same fallback used for no-evidence items — so the
        response stays bounded and every anchor still addresses live content.
        """

        separator = "\n\n"
        content_parts: list[str] = []
        anchors: list[SourceAnchor] = []
        item_anchor_by_unit: dict[uuid.UUID, str] = {}
        anchor_unavailable_by_unit: dict[uuid.UUID, AnchorUnavailableReason] = {}
        group_anchor_by_id: dict[str, str] = {}
        cursor = 0
        browser_cursor = 0
        truncated = False
        omitted_anchor_count = 0
        for index, (group, _assignment, unit, _unit_subject, evidence) in enumerate(prepared):
            truncated = truncated or any(
                len(item.snippet) > len(clamp_snippet(item.snippet)) for item in evidence
            )
            snippets = [clamp_snippet(item.snippet) for item in evidence]
            if not snippets:
                anchor_unavailable_by_unit[unit.id] = "no_evidence"
                continue
            if len(anchors) >= MAX_SOURCE_RENDER_ANCHORS:
                anchor_unavailable_by_unit[unit.id] = "anchor_budget_exhausted"
                omitted_anchor_count += 1
                remaining = prepared[index + 1 :]
                for (
                    _group,
                    _assignment,
                    remaining_unit,
                    _remaining_subject,
                    remaining_evidence,
                ) in remaining:
                    if remaining_evidence:
                        anchor_unavailable_by_unit[remaining_unit.id] = "anchor_budget_exhausted"
                        omitted_anchor_count += 1
                    else:
                        anchor_unavailable_by_unit[remaining_unit.id] = "no_evidence"
                break
            prefix = separator if content_parts else ""
            block, budget_exhausted = fit_block(separator.join(snippets), cursor + len(prefix))
            if not block:
                truncated = True
                anchor_unavailable_by_unit[unit.id] = "source_truncated"
                omitted_anchor_count += 1
                remaining = prepared[index + 1 :]
                for (
                    _group,
                    _assignment,
                    remaining_unit,
                    _remaining_subject,
                    remaining_evidence,
                ) in remaining:
                    if remaining_evidence:
                        anchor_unavailable_by_unit[remaining_unit.id] = "source_truncated"
                        omitted_anchor_count += 1
                    else:
                        anchor_unavailable_by_unit[remaining_unit.id] = "no_evidence"
                break
            if prefix:
                content_parts.append(prefix)
                cursor += len(prefix)
                browser_cursor += utf16_length(prefix)
            block_start = browser_cursor
            content_parts.append(block)
            cursor += len(block)
            browser_cursor += utf16_length(block)
            if group.group_id not in group_anchor_by_id:
                group_anchor_id = f"group:{group.group_id}"
                anchors.append(
                    SourceAnchor(
                        anchor_id=group_anchor_id,
                        group_id=group.group_id,
                        char_start=block_start,
                        char_end=block_start,
                        scroll_hint="start",
                        label=group.group_label,
                    )
                )
                group_anchor_by_id[group.group_id] = group_anchor_id
            item_anchor_id = f"unit:{unit.id}"
            anchors.append(
                SourceAnchor(
                    anchor_id=item_anchor_id,
                    review_unit_id=unit.id,
                    group_id=group.group_id,
                    item_id=str(unit.id),
                    char_start=block_start,
                    char_end=browser_cursor,
                    scroll_hint="center",
                    label=display_field_label(unit.field_name, unit.safe_field_label),
                )
            )
            item_anchor_by_unit[unit.id] = item_anchor_id
            if budget_exhausted:
                truncated = True
                remaining = prepared[index + 1 :]
                for (
                    _group,
                    _assignment,
                    remaining_unit,
                    _remaining_subject,
                    remaining_evidence,
                ) in remaining:
                    if remaining_evidence:
                        anchor_unavailable_by_unit[remaining_unit.id] = "source_truncated"
                        omitted_anchor_count += 1
                    else:
                        anchor_unavailable_by_unit[remaining_unit.id] = "no_evidence"
                break
        source_render = SourceRender(
            source_snapshot_id=source_snapshot_id,
            render_mode="safe_text",
            content="".join(content_parts),
            anchors=anchors,
            truncated=truncated,
            omitted_anchor_count=omitted_anchor_count,
        )
        return source_render, item_anchor_by_unit, anchor_unavailable_by_unit, group_anchor_by_id
