"""Persist real review units and their artifacts in the caller-owned transaction."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from typing import TYPE_CHECKING, cast

from sqlalchemy.orm import Session

from review_platform.common.json import digest_json
from review_platform.dataset.types import InputCandidate, InputCase, InputEvidence
from review_platform.review.import_generations import _prepare_generation
from review_platform.review.import_source import (
    CONTRACT_VERSION,
    IMPORT_JOB,
    DatasetImportResult,
    _CaseSource,
    _evidence_digest_payload,
    _json_safe,
)
from review_platform.review.models import (
    Campaign,
    Candidate,
    ReviewSubject,
    ReviewUnit,
    SourceRenderArtifact,
    SourceSnapshot,
)
from review_platform.review.source_render import RenderedArtifact

if TYPE_CHECKING:
    from review_platform.review.dataset_import import DatasetImportService


def _persist_unit(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    campaign: Campaign,
    case: InputCase,
    source: _CaseSource,
    result: DatasetImportResult,
    external_item_key: str,
    review_kind: str,
    label: str,
    question: str,
    display_title: str,
    target_external_id: str,
    input_payload: dict[str, object],
    candidates: list[tuple[str, InputCandidate]],
    evidence: list[InputEvidence],
    required_reviews: int,
    extra_attributes: dict[str, object] | None = None,
    field_name: str | None = None,
    refresh_existing: bool = False,
    legacy_item_keys: list[str] | None = None,
) -> bool:
    """Write one real review unit (metadata field or relation) and its candidates/evidence.

    Shared by field and relation import so both paths produce identical snapshot/subject/unit/
    artifact structure. Idempotent on ``external_item_key``: a re-import of the same real item
    is skipped. Provenance snippets are re-anchored into the rendered text (null offsets when
    the snippet falls in trimmed/omitted material -- never dropped).
    """

    external_item_key = external_item_key[:240]
    input_digest = digest_json(
        {
            **input_payload,
            "source_document_id": case.source_document_id,
            "source_sha256": case.sha256,
            "candidates": [
                {
                    "label": candidate_label,
                    **cast(dict[str, object], _json_safe(asdict(candidate))),
                }
                for candidate_label, candidate in candidates
            ],
            "evidence": [_evidence_digest_payload(item) for item in evidence],
        }
    )
    if not _prepare_generation(
        self,
        session,
        tenant_id=tenant_id,
        campaign=campaign,
        external_item_key=external_item_key,
        legacy_item_keys=legacy_item_keys,
        input_digest=input_digest,
        refresh_existing=refresh_existing,
        source=source,
        result=result,
    ):
        return False
    rendered, plain_text = source.require()
    snapshot = SourceSnapshot(
        tenant_id=tenant_id,
        contract_version=CONTRACT_VERSION,
        source_mode="dataset",
        source_version=case.source_document_id,
        external_item_key=external_item_key,
        input_digest=input_digest,
    )
    session.add(snapshot)
    session.flush()
    attributes: dict[str, object] = {
        "field_label": label,
        "source_collection": case.source_system,
        "snapshot_local_target_external_id": target_external_id,
        "snapshot_local_source_external_id": case.source_document_id,
        "source_sha256": case.sha256,
        "reference_semantics": "snapshot-local-soft-no-cross-database-fk",
        "snapshot_local_case_external_id": case.external_id,
        "logical_external_item_key": external_item_key.split(":refresh:", 1)[0],
        # Canonical-family identity: the stable reviewer key for this judgment and every source
        # observation folded into it. For family-grouped imports ``case.external_id`` IS the family
        # id; single-observation imports fall back to the observation id (one-member family).
        "family_id": case.family_id or case.external_id,
        "family_member_external_ids": list(case.member_external_ids) or [case.external_id],
        "family_member_source_systems": list(case.member_source_systems) or [case.source_system],
    }
    if extra_attributes:
        attributes.update(extra_attributes)
    subject = ReviewSubject(
        tenant_id=tenant_id,
        source_snapshot_id=snapshot.id,
        subject_kind="case",
        external_subject_id=f"subject_{snapshot.id.hex}",
        display_title=(display_title or label)[:300],
        display_subtitle=label,
        source_version=case.source_document_id,
        primary_source_ref=f"source_{rendered.content_digest[:32]}",
        attributes_json=attributes,
    )
    session.add(subject)
    session.flush()
    self._write_artifact(
        session, tenant_id=tenant_id, snapshot=snapshot, case=case, rendered=rendered
    )
    unit = ReviewUnit(
        tenant_id=tenant_id,
        campaign_id=campaign.id,
        review_subject_id=subject.id,
        review_kind=review_kind,
        question=question,
        safe_field_label=label,
        field_name=field_name,
        required_reviews=required_reviews,
        input_digest=input_digest,
    )
    session.add(unit)
    session.flush()
    self._add_candidates(session, tenant_id=tenant_id, unit_id=unit.id, candidates=candidates)
    unresolved, expected = self._add_evidence(
        session,
        tenant_id=tenant_id,
        unit_id=unit.id,
        evidence=evidence,
        plain_text=plain_text,
        render_sha256=case.sha256,
        field_name=field_name,
        source_system=case.source_system,
    )
    result.unresolved_anchors += unresolved
    result.unanchored_expected += expected
    return True


def _write_artifact(
    self: DatasetImportService,
    session: Session,
    *,
    tenant_id: uuid.UUID,
    snapshot: SourceSnapshot,
    case: InputCase,
    rendered: RenderedArtifact,
) -> None:
    object_key = rendered.content_digest
    # One upload per distinct rendered artifact per run; the per-snapshot DB row below is
    # still written for every unit (it is the read path's lookup record, not the bytes).
    if object_key not in self._uploaded_digests:
        self._store.write_artifact(
            object_key,
            body=rendered.safe_html.encode("utf-8"),
            anchor_map=rendered.anchor_map_json.encode("utf-8"),
        )
        self._uploaded_digests.add(object_key)
    session.add(
        SourceRenderArtifact(
            tenant_id=tenant_id,
            source_snapshot_id=snapshot.id,
            subject_kind="case",
            source_system=case.source_system,
            source_kind="judgment",
            render_profile=rendered.render_profile,
            render_version=rendered.render_version,
            render_mode=rendered.render_mode,
            content_digest=rendered.content_digest,
            anchor_map_digest=rendered.anchor_map_digest,
            object_key=object_key,
            artifact_mime_type=rendered.mime_type,
            artifact_size_bytes=rendered.size_bytes,
            created_by_job=IMPORT_JOB,
        )
    )


def _add_candidates(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    unit_id: uuid.UUID,
    candidates: list[tuple[str, InputCandidate]],
) -> None:
    # A is always the extracted value the reviewer judges; B is optional LLM/admin context.
    for candidate_label, candidate in candidates:
        session.add(
            Candidate(
                tenant_id=tenant_id,
                review_unit_id=unit_id,
                label=candidate_label,
                source_kind=candidate.source_kind,
                verdict=candidate.verdict,
                value_json=_json_safe(candidate.value),
                rationale=candidate.rationale or "",
                supporting_quote=candidate.supporting_quote,
            )
        )
