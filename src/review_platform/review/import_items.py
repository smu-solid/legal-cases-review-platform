"""Prepare field and relation units for the shared import writer."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy.orm import Session

from review_platform.dataset.types import InputCandidate, InputCase, InputField, InputRelation
from review_platform.review.grouping import require_atomic_group, scope_matches
from review_platform.review.import_source import (
    DatasetImportResult,
    _CaseSource,
    _field_label,
    field_render_evidence,
    relation_render_evidence,
)
from review_platform.review.models import Campaign

if TYPE_CHECKING:
    from review_platform.review.dataset_import import DatasetImportService


def _import_field(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    case: InputCase,
    field: InputField,
    source: _CaseSource,
    result: DatasetImportResult,
    required_reviews: int,
    refresh_existing: bool,
) -> bool:
    label = _field_label(field.field_name)
    # Closed allowlist: a source column with no field-group mapping is rejected loudly here
    # rather than silently absorbed into additional_fields (which would retroactively change
    # what an existing campaign's declared scope means). Grouping/scope keys off the stable
    # field_name, never the renamable display label.
    require_atomic_group(field.field_name)
    # Campaign review scope (if any) narrows which fields become review units. Real metadata
    # units are metadata_field; an out-of-scope field is skipped before any row is written.
    if not scope_matches(
        "metadata_field",
        label,
        campaign.review_scope_json,
        source_system=case.source_system,
        field_name=field.field_name,
    ):
        return False
    candidates = [("A", field.value_candidate)]
    if field.model_candidate is not None:  # B: optional LLM/admin context
        candidates.append(("B", field.model_candidate))
    return self._persist_unit(
        session,
        tenant_id=tenant_id,
        campaign=campaign,
        case=case,
        source=source,
        result=result,
        external_item_key=f"{case.external_id}:{field.field_name}",
        review_kind="metadata_field",
        label=label,
        field_name=field.field_name,
        question=f"Confirm the {label} for this case, or correct its provenance.",
        display_title=case.title or field.display_value or label,
        target_external_id=case.external_id,
        input_payload={
            "case": case.external_id,
            "field": field.field_name,
            "value": field.display_value,
            "family_id": case.family_id or case.external_id,
            # Family membership, FULL member values, member document identity and member
            # evidence are all input-digest material: a member joining/leaving, a value change
            # anywhere in the value (not just its first 300 characters), a document swap or an
            # evidence-only change is a changed input generation, never a silent "unchanged".
            "members": [
                [
                    mv.case_external_id,
                    mv.source_system,
                    str(mv.value),
                    mv.source_document_id,
                    mv.sha256,
                    list(mv.evidence),
                ]
                for mv in field.member_values
            ],
            "cross_source_disagreement": field.cross_source_disagreement,
        },
        candidates=candidates,
        # Shared evidence-selection contract (``field_render_evidence``): only evidence of the
        # render document is anchored; another member's snippet stays with that member's value.
        evidence=field_render_evidence(field, case),
        required_reviews=required_reviews,
        refresh_existing=refresh_existing,
        legacy_item_keys=[
            f"{member}:{field.field_name}" for member in self._legacy_member_ids(case)
        ],
        extra_attributes={
            # Canonical-family review, PERSISTED on the subject and served to the reviewer:
            # every member observation's value, source-labelled and carrying its OWN document
            # identity and evidence; a material disagreement is marked — surfaced for
            # adjudication, never silently resolved to one source.
            # FULL semantic values and ALL evidence entries are persisted; truncation is a
            # PRESENTATION concern (the bundle sends a preview and marks it truncated, and the
            # full value remains accessible through this subject attribute).
            "member_values": [
                {
                    "case": mv.case_external_id,
                    "source_system": mv.source_system,
                    "value": str(mv.value),
                    "source_document_id": mv.source_document_id,
                    "source_sha256": mv.sha256,
                    "evidence": [dict(e) for e in mv.evidence],
                }
                for mv in field.member_values
            ],
            "cross_source_disagreement": field.cross_source_disagreement,
        },
    )


def _import_relation(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    case: InputCase,
    relation: InputRelation,
    source: _CaseSource,
    result: DatasetImportResult,
    required_reviews: int,
    refresh_existing: bool,
) -> bool:
    # A relation unit's kind (cited_case/statute_reference/appeal_relation) drives its review
    # group; scope narrows by that kind. Relations carry a single deterministic candidate (A) --
    # the extracted relation the reviewer confirms against provenance -- and no model candidate.
    if not scope_matches(
        relation.review_kind,
        relation.display_label,
        campaign.review_scope_json,
        source_system=case.source_system,
    ):
        return False
    candidate = InputCandidate(
        source_kind="deterministic",
        verdict="supported",
        value=relation.value,
        rationale="Extracted relation grounded by document evidence.",
        supporting_quote=None,
    )
    contributing = list(relation.contributing) or [
        {
            "relation_external_id": relation.relation_external_id,
            "case_external_id": case.external_id,
            "source_system": case.source_system,
        }
    ]
    legacy_keys = [
        f"{member}:{relation.family}:{entry['relation_external_id']}"
        for member in self._legacy_member_ids(case)
        for entry in contributing
    ]
    legacy_keys += [
        f"{case.family_id or case.external_id}:{relation.family}:{entry['relation_external_id']}"
        for entry in contributing
        if entry["relation_external_id"] != relation.relation_external_id
    ]
    return self._persist_unit(
        session,
        tenant_id=tenant_id,
        campaign=campaign,
        case=case,
        source=source,
        result=result,
        external_item_key=f"{case.external_id}:{relation.family}:{relation.relation_external_id}",
        review_kind=relation.review_kind,
        label=relation.display_label,
        question=(
            f"Confirm this {relation.display_label.lower()} "
            f"({relation.display_value}) for the case, or correct its provenance."
        ),
        display_title=case.title or f"{relation.display_label}: {relation.display_value}",
        target_external_id=relation.relation_external_id,
        required_reviews=required_reviews,
        refresh_existing=refresh_existing,
        input_payload={
            "case": case.external_id,
            "relation": relation.relation_external_id,
            "kind": relation.review_kind,
            "value": relation.display_value,
            # Contributing observations are digest input: a member's relation joining or
            # leaving this semantic group is a changed input generation.
            "relation_sources": contributing,
        },
        candidates=[("A", candidate)],
        # Shared evidence-selection contract (see ``relation_render_evidence``); a pointer
        # member's relation snippet stays fully attributed inside relation_sources below.
        evidence=relation_render_evidence(relation, case, contributing),
        legacy_item_keys=legacy_keys,
        extra_attributes={
            "relation_family": relation.family,
            "relation_review_kind": relation.review_kind,
            # Every member observation asserting this same relationship: relation id, source,
            # its own document identity AND its own evidence — preserved, not collapsed.
            "relation_sources": contributing,
        },
    )
