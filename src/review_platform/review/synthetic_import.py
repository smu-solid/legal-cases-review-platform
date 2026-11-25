"""Synthetic fixture import: builds campaigns, review units, candidates, and evidence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.dataset.contract import SnapshotBatch, SnapshotItem, opaque_content_key
from review_platform.db.models import Tenant
from review_platform.review import synthetic_items as _synthetic_items
from review_platform.review.base import SUPPORTED_VERDICTS, ReviewServiceBase
from review_platform.review.campaign_allocation_math import resolve_minimum_reviews_per_case
from review_platform.review.grouping import scope_matches
from review_platform.review.models import (
    Campaign,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.review.schemas import (
    CampaignReviewScopeInput,
    SyntheticImportRequest,
    SyntheticImportResponse,
)


class ReviewImportMixin(ReviewServiceBase):
    @staticmethod
    def _item_publishable(item: SnapshotItem) -> bool:
        kinds = [candidate.validator_kind for candidate in item.validator_candidates]
        verdicts = [candidate.normalized_verdict for candidate in item.validator_candidates]
        return kinds == ["deterministic", "model"] and all(
            verdict in SUPPORTED_VERDICTS for verdict in verdicts
        )

    _review_kind = staticmethod(_synthetic_items._review_kind)

    @staticmethod
    def _scope_payload(body: SyntheticImportRequest) -> dict[str, list[str]] | None:
        if body.review_scope is None:
            return None
        payload = body.review_scope.model_dump(mode="json")
        if (
            not payload["group_ids"]
            and not payload["review_kinds"]
            and not payload["source_families"]
        ):
            return None
        return payload

    @staticmethod
    def _item_in_scope(item: SnapshotItem, scope: dict[str, list[str]] | None) -> bool:
        return scope_matches(
            ReviewImportMixin._review_kind(item),
            item.target.field,
            scope,
            source_system=item.source_document.source_system,
        )

    @staticmethod
    def _scope_response(scope: dict[str, object] | None) -> CampaignReviewScopeInput | None:
        if scope is None:
            return None
        return CampaignReviewScopeInput.model_validate(scope)

    def import_synthetic(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        body: SyntheticImportRequest,
        idempotency_key: str,
        request_id: str,
        # Default "published" matches the UI's "Load cases from database" button (the admin
        # dashboard, api/review/campaign_admin.py) -- data imported that way is meant to be
        # immediately reviewable. dev_seed.py (the `make seed-smoke` CLI) passes "draft" instead,
        # since a CLI-seeded campaign should go through the normal draft -> select reviewers ->
        # preview -> publish flow, matching campaign_admin.create_campaign.
        initial_status: str = "published",
    ) -> SyntheticImportResponse:
        if not self.synthetic_enabled:
            raise APIError(
                403,
                "synthetic_import_disabled",
                "Synthetic import disabled",
                "Synthetic fixture import is disabled in this environment.",
            )
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        request_digest = self._request_digest(body.model_dump(mode="json"))
        operation = "review.import_synthetic"
        record = self._idempotent_response(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
        )
        if record is not None:
            response = SyntheticImportResponse.model_validate(record.response_json)
            return response.model_copy(update={"replayed": True})
        review_scope = self._scope_payload(body)
        batch = self.reader.load(body.fixture_version)
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        if batch.manifest.tenant_key != tenant.key:
            raise APIError(
                422,
                "synthetic_tenant_mismatch",
                "Synthetic tenant mismatch",
                "The fixture is bound to a different synthetic tenant.",
            )
        campaign = session.scalar(
            select(Campaign).where(
                Campaign.tenant_id == tenant_id, Campaign.key == body.campaign_key
            )
        )
        if campaign is not None:
            if campaign.manifest_digest != batch.manifest_digest:
                raise APIError(
                    409,
                    "campaign_import_conflict",
                    "Campaign import conflict",
                    "The campaign key already refers to a different manifest.",
                )
            response = self._top_up_synthetic_campaign(
                session, tenant_id=tenant_id, campaign=campaign, batch=batch, body=body
            )
            self._store_idempotency(
                session,
                tenant_id=tenant_id,
                user_id=principal.user.id,
                operation=operation,
                key=idempotency_key,
                request_digest=request_digest,
                response=response.model_dump(mode="json"),
            )
            if not response.replayed:
                append_audit_event(
                    session,
                    actor_user_id=principal.user.id,
                    actor_type="user",
                    event_type="review.synthetic_imported",
                    object_type="campaign",
                    object_id=str(campaign.id),
                    request_id=request_id,
                    payload={
                        "manifest_digest": batch.manifest_digest,
                        "imported_units": response.imported_units,
                        "blocked_units": response.blocked_units,
                        "top_up": True,
                    },
                    key=self.audit_key,
                )
            return response
        blocked_units = sum(not self._item_publishable(item) for item in batch.envelope.items)
        scoped_items: list[SnapshotItem] = []
        for item in batch.envelope.items:
            if body.case_count is not None and len(scoped_items) >= body.case_count:
                break
            if not self._item_publishable(item):
                continue
            if not self._item_in_scope(item, review_scope):
                continue
            scoped_items.append(item)
        self._check_case_field_conflicts(session, tenant_id=tenant_id, items=scoped_items)
        minimum_reviews_per_case = resolve_minimum_reviews_per_case(body.reviews_per_case)
        campaign = Campaign(
            tenant_id=tenant_id,
            key=body.campaign_key,
            name=body.campaign_name,
            status=initial_status,
            policy_version="synthetic-v1",
            policy_json={
                "minimum_reviews_per_case": minimum_reviews_per_case,
                "blocked_units": blocked_units,
            },
            review_scope_json=review_scope,
            manifest_digest=batch.manifest_digest,
            created_by=principal.user.id,
        )
        session.add(campaign)
        session.flush()
        imported_units = 0
        for item in scoped_items:
            self._import_item(
                session,
                tenant_id=tenant_id,
                campaign=campaign,
                item=item,
                required_reviews=minimum_reviews_per_case,
            )
            imported_units += 1
        response = SyntheticImportResponse(
            campaign_id=campaign.id,
            fixture_version=body.fixture_version,
            manifest_digest=batch.manifest_digest,
            imported_units=imported_units,
            blocked_units=blocked_units,
            review_scope=body.review_scope,
            reviews_per_case=minimum_reviews_per_case,
            replayed=False,
        )
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="review.synthetic_imported",
            object_type="campaign",
            object_id=str(campaign.id),
            request_id=request_id,
            payload={
                "manifest_digest": batch.manifest_digest,
                "imported_units": imported_units,
                "blocked_units": blocked_units,
            },
            key=self.audit_key,
        )
        self._store_idempotency(
            session,
            tenant_id=tenant_id,
            user_id=principal.user.id,
            operation=operation,
            key=idempotency_key,
            request_digest=request_digest,
            response=response.model_dump(mode="json"),
        )
        return response

    def _top_up_synthetic_campaign(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        campaign: Campaign,
        batch: SnapshotBatch,
        body: SyntheticImportRequest,
    ) -> SyntheticImportResponse:
        """Import any not-yet-present in-scope items into an already-imported campaign.

        A same-manifest re-import used to just replay the campaign's existing counts
        unchanged --     there was no way to add more cases to a campaign first created
        with a smaller     ``case_count`` (or an admin-authored empty draft) without a
        fresh campaign key. Scope     filtering uses the campaign's own persisted
        ``review_scope_json``, not ``body.review_scope``     -- scope is a durable
        campaign property set at creation/edit time, not a per-import-call     override.
        ``case_count`` here means the same thing it means for a brand-new campaign: the
        desired total number of imported cases, not an additional import count."""

        existing_keys = set(
            session.scalars(
                select(SourceSnapshot.external_item_key)
                .select_from(ReviewUnit)
                .join(
                    ReviewSubject,
                    (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
                    & (ReviewSubject.id == ReviewUnit.review_subject_id),
                )
                .join(
                    SourceSnapshot,
                    (SourceSnapshot.tenant_id == ReviewSubject.tenant_id)
                    & (SourceSnapshot.id == ReviewSubject.source_snapshot_id),
                )
                .where(ReviewUnit.tenant_id == tenant_id, ReviewUnit.campaign_id == campaign.id)
            )
        )
        imported_before = len(existing_keys)
        minimum_reviews_per_case = resolve_minimum_reviews_per_case(
            campaign.policy_json.get("minimum_reviews_per_case")
        )
        new_items: list[SnapshotItem] = []
        for item in batch.envelope.items:
            if body.case_count is not None and imported_before + len(new_items) >= body.case_count:
                break
            if not self._item_publishable(item):
                continue
            if opaque_content_key(item) in existing_keys:
                continue
            if not self._item_in_scope(item, campaign.review_scope_json):
                continue
            new_items.append(item)
        if new_items:
            self._check_case_field_conflicts(
                session,
                tenant_id=tenant_id,
                items=new_items,
                exclude_campaign_id=campaign.id,
            )
            for item in new_items:
                self._import_item(
                    session,
                    tenant_id=tenant_id,
                    campaign=campaign,
                    item=item,
                    required_reviews=minimum_reviews_per_case,
                )
        return SyntheticImportResponse(
            campaign_id=campaign.id,
            fixture_version=body.fixture_version,
            manifest_digest=batch.manifest_digest,
            imported_units=imported_before + len(new_items),
            blocked_units=int(campaign.policy_json["blocked_units"]),
            review_scope=self._scope_response(campaign.review_scope_json),
            reviews_per_case=minimum_reviews_per_case,
            replayed=not new_items,
        )

    _check_case_field_conflicts = staticmethod(_synthetic_items._check_case_field_conflicts)

    _import_item = _synthetic_items._import_item
