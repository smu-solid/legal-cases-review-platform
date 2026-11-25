"""Transactional import of case datasets and document evidence."""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from review_platform.dataset.documents import DocumentResolver
from review_platform.dataset.types import InputCase, InputEvidence
from review_platform.review.artifact_store import ArtifactStore
from review_platform.review.campaign_allocation_math import resolve_minimum_reviews_per_case
from review_platform.review.import_campaign import (
    _check_case_field_conflicts as _operation_check_case_field_conflicts,
)
from review_platform.review.import_campaign import (
    _get_or_create_campaign as _operation_get_or_create_campaign,
)
from review_platform.review.import_family_reconciliation import (
    _delete_removed_pool_units as _operation_delete_removed_pool_units,
)
from review_platform.review.import_family_reconciliation import (
    _family_protected_legacy_units as _operation_family_protected_legacy_units,
)
from review_platform.review.import_family_reconciliation import (
    _incoming_logical_keys as _operation_incoming_logical_keys,
)
from review_platform.review.import_family_reconciliation import (
    _legacy_member_ids as _operation_legacy_member_ids,
)
from review_platform.review.import_family_reconciliation import (
    _retire_unassigned_pool_copies as _operation_retire_unassigned_pool_copies,
)
from review_platform.review.import_generations import (
    _delete_superseded_generation as _operation_delete_superseded_generation,
)
from review_platform.review.import_items import _import_field as _operation_import_field
from review_platform.review.import_items import _import_relation as _operation_import_relation
from review_platform.review.import_persistence import _add_candidates as _operation_add_candidates
from review_platform.review.import_persistence import _persist_unit as _operation_persist_unit
from review_platform.review.import_persistence import _write_artifact as _operation_write_artifact
from review_platform.review.import_source import ANCHOR_ANCHORED as ANCHOR_ANCHORED
from review_platform.review.import_source import ANCHOR_EXPECTED as ANCHOR_EXPECTED
from review_platform.review.import_source import ANCHOR_OTHER_DOCUMENT as ANCHOR_OTHER_DOCUMENT
from review_platform.review.import_source import ANCHOR_UNEXPECTED as ANCHOR_UNEXPECTED
from review_platform.review.import_source import DatasetImportError as DatasetImportError
from review_platform.review.import_source import DatasetImportResult as DatasetImportResult
from review_platform.review.import_source import _CaseSource as _CaseSource
from review_platform.review.import_source import _plain_text as _plain_text
from review_platform.review.import_source import _SourceUnavailableError as _SourceUnavailableError
from review_platform.review.import_source import classify_anchor as classify_anchor
from review_platform.review.import_source import field_render_evidence as field_render_evidence
from review_platform.review.import_source import (
    relation_render_evidence as relation_render_evidence,
)
from review_platform.review.models import Campaign, EvidenceWindow


class DatasetImportService:
    """Writes review rows for real cases; renders sources resolved by content hash."""

    def __init__(self, *, resolver: DocumentResolver, store: ArtifactStore, audit_key: str) -> None:
        self._resolver = resolver
        self._store = store
        self._audit_key = audit_key
        self._uploaded_digests: set[str] = set()

    def import_cases(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        created_by: uuid.UUID,
        campaign_key: str,
        campaign_name: str,
        source_system: str,
        cases: list[InputCase],
        review_scope: dict[str, list[str]] | None = None,
        minimum_reviews_per_case: int | None = None,
        progress: Callable[[], None] | None = None,
        campaign_status: str = "draft",
        refresh_existing: bool = False,
    ) -> DatasetImportResult:
        self._set_tenant_scope(session, tenant_id)
        campaign = self._get_or_create_campaign(
            session,
            tenant_id=tenant_id,
            created_by=created_by,
            key=campaign_key,
            name=campaign_name,
            source_system=source_system,
            cases=cases,
            review_scope=review_scope,
            minimum_reviews_per_case=minimum_reviews_per_case,
            campaign_status=campaign_status,
        )
        if campaign.status != "pool":
            # The pool campaign is never itself in conflict: a case/field already claimed by an
            # active real campaign simply never entered (or already left) the pool, so a preload
            # re-run must skip it silently via SourceSnapshot idempotency below, not raise --
            # otherwise topping up the pool with new cases would fail closed on every already
            # -claimed case from a prior preload run.
            self._check_case_field_conflicts(
                session, tenant_id=tenant_id, campaign=campaign, cases=cases
            )
        # The campaign's own persisted value governs every unit written this call -- not the
        # (possibly different) incoming parameter -- so a re-import into an existing campaign
        # never mixes required_reviews within one campaign, mirroring how review_scope is applied.
        required_reviews = resolve_minimum_reviews_per_case(
            campaign.policy_json.get("minimum_reviews_per_case")
        )
        result = DatasetImportResult(campaign.id, 0, 0, 0, 0, 0)
        for case in cases:
            # Resolution is an in-memory index lookup, so the unresolved accounting stays eager and
            # exact. Only the file read and render below are deferred.
            if self._resolver.resolve(case.sha256) is None:
                result.unresolved_source_cases += 1
                result.unresolved_case_ids.append(case.external_id)
                if progress is not None:
                    progress()
                continue
            source = _CaseSource(resolver=self._resolver, source_system=source_system, case=case)
            try:
                imported_here = self._import_case_units(
                    session,
                    tenant_id=tenant_id,
                    campaign=campaign,
                    case=case,
                    source=source,
                    result=result,
                    required_reviews=required_reviews,
                    refresh_existing=refresh_existing,
                )
            except _SourceUnavailableError:
                # The file changed or vanished between resolution and the write that needed it.
                # ``require`` is called before any mutation of a unit, so nothing was half-written.
                result.unresolved_source_cases += 1
                result.unresolved_case_ids.append(case.external_id)
                if progress is not None:
                    progress()
                continue
            if source.was_read:
                result.rendered_cases += 1
                result.source_render_seconds += source.seconds
            else:
                result.skipped_unchanged_cases += 1
            if imported_here:
                result.imported_cases += 1
                result.imported_units += imported_here
            if progress is not None:
                progress()
        return result

    def _import_case_units(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign: Campaign,
        case: InputCase,
        source: _CaseSource,
        result: DatasetImportResult,
        required_reviews: int,
        refresh_existing: bool,
    ) -> int:
        """Write one case's in-scope field and relation units; return how many were written."""

        blocking = self._family_protected_legacy_units(
            session, tenant_id=tenant_id, case=case, campaign=campaign
        )
        if blocking:
            # Family-wide guard: a member identity holds assigned/submitted work under a NON-family
            # key. Re-keying it would orphan or duplicate that work, so the whole family is
            # deferred and manifested; no fresh family-keyed unit is created beside it.
            entry: dict[str, object] = {
                "reason": "protected work prevents family reconciliation",
                "blocking_unit_keys": sorted(blocking),
                "member_external_ids": list(case.member_external_ids) or [case.external_id],
            }
            if refresh_existing:
                # C7: a family blocked by protected historical work must not leave duplicate
                # legacy copies assignable in the POOL. Only UNASSIGNED pool copies are removed,
                # only in this pool campaign, and every removed unit id is manifested.
                entry["pool_copies_retired"] = self._retire_unassigned_pool_copies(
                    session, tenant_id=tenant_id, campaign=campaign, case=case
                )
            result.deferred_families[case.family_id or case.external_id] = entry
            return 0
        if refresh_existing:
            self._delete_removed_pool_units(
                session, tenant_id=tenant_id, campaign=campaign, case=case, source=source
            )
        imported_here = 0
        result.relation_duplicates_grouped += sum(
            len(relation.contributing) - 1 for relation in case.relations if relation.contributing
        )
        for field in case.fields:
            if self._import_field(
                session,
                tenant_id=tenant_id,
                campaign=campaign,
                case=case,
                field=field,
                source=source,
                result=result,
                required_reviews=required_reviews,
                refresh_existing=refresh_existing,
            ):
                imported_here += 1
        for relation in case.relations:
            if self._import_relation(
                session,
                tenant_id=tenant_id,
                campaign=campaign,
                case=case,
                relation=relation,
                source=source,
                result=result,
                required_reviews=required_reviews,
                refresh_existing=refresh_existing,
            ):
                imported_here += 1
        return imported_here

    _check_case_field_conflicts = staticmethod(_operation_check_case_field_conflicts)

    _legacy_member_ids = staticmethod(_operation_legacy_member_ids)

    _incoming_logical_keys = _operation_incoming_logical_keys

    _family_protected_legacy_units = _operation_family_protected_legacy_units

    _import_field = _operation_import_field

    _import_relation = _operation_import_relation

    _persist_unit = _operation_persist_unit

    _delete_superseded_generation = staticmethod(_operation_delete_superseded_generation)

    _retire_unassigned_pool_copies = _operation_retire_unassigned_pool_copies

    _delete_removed_pool_units = _operation_delete_removed_pool_units

    _write_artifact = _operation_write_artifact

    _add_candidates = staticmethod(_operation_add_candidates)

    @staticmethod
    def _add_evidence(
        session: Session,
        *,
        tenant_id: uuid.UUID,
        unit_id: uuid.UUID,
        evidence: list[InputEvidence],
        plain_text: str,
        render_sha256: str = "",
        field_name: str | None = None,
        source_system: str | None = None,
    ) -> tuple[int, int]:
        """Persist evidence windows; return (unresolved_body_quotes, expected_unanchored)."""

        unresolved = 0
        expected = 0
        for ordinal, window in enumerate(evidence):
            status, char_start, char_end = classify_anchor(
                window,
                plain_text,
                render_sha256,
                field_name=field_name,
                source_system=source_system,
            )
            if status == ANCHOR_UNEXPECTED:
                unresolved += 1
            elif status == ANCHOR_EXPECTED:
                expected += 1
            session.add(
                EvidenceWindow(
                    tenant_id=tenant_id,
                    review_unit_id=unit_id,
                    ordinal=ordinal,
                    kind=window.kind,
                    snippet=window.snippet[:20_000],
                    line_start=window.line_start,
                    line_end=window.line_end,
                    char_start=char_start,
                    char_end=char_end,
                    source_sha256=window.source_hash,
                    provenance_external_id=window.provenance_external_id,
                    body_grounded=window.body_grounded,
                    source_region=window.source_region,
                    anchor_status=status,
                )
            )
        return unresolved, expected

    _get_or_create_campaign = staticmethod(_operation_get_or_create_campaign)

    @staticmethod
    def _set_tenant_scope(session: Session, tenant_id: uuid.UUID) -> None:
        from sqlalchemy import text

        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
