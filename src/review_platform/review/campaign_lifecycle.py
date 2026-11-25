"""Campaign detail and guarded edits to campaign scope and policy."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.review.campaign_availability import lock_pool_claims
from review_platform.review.campaign_case_filters import (
    verify_case_filter,
    verify_case_id_selection,
)
from review_platform.review.campaign_closure import ReviewCampaignClosureMixin
from review_platform.review.campaign_materialization import backfill_widened_scope
from review_platform.review.campaign_queries import (
    _campaign_detail_response,
    _load_campaign,
    _load_campaign_for_update,
    _minimum_reviews_per_case,
)
from review_platform.review.case_pool import (
    get_or_create_pool_campaign,
)
from review_platform.review.models import Campaign
from review_platform.review.schemas import (
    CampaignCaseFilter,
    CampaignDetailResponse,
    CampaignEditRequest,
    CampaignReviewScopeInput,
)

_LOCKED_STATUSES = frozenset({"closed"})


class ReviewCampaignLifecycleMixin(ReviewCampaignClosureMixin):
    def get_campaign(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
    ) -> CampaignDetailResponse:
        """Read-only campaign detail (name, status, scope, policy, selected reviewers).

        No side effects: unlike ``edit_campaign``, this never locks the row, writes an audit
        event, or requires ``confirm``. The UI's campaign-detail page uses this to render current
        state; only an actual field change goes through ``edit_campaign``.
        """

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign(session, tenant_id, campaign_id)
        return _campaign_detail_response(session, campaign)

    def edit_campaign(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign_id: uuid.UUID,
        body: CampaignEditRequest,
        request_id: str,
    ) -> CampaignDetailResponse:
        """Edit a draft/planned/published campaign's name, scope, or minimum-reviews policy.

        Closed campaigns are hard-blocked. Changing the source or case selector requires
        ``confirm=true``. The database continues to freeze identity and publication fields that
        are not part of this editor after publication.
        """

        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        self._set_tenant_scope(session, tenant_id)
        campaign = _load_campaign_for_update(session, tenant_id, campaign_id)
        if campaign.status in _LOCKED_STATUSES:
            raise APIError(
                409,
                "campaign_not_editable",
                "Campaign not editable",
                "Closed campaigns cannot be edited.",
            )
        if (
            campaign.status == "published"
            and body.reviews_per_case is not None
            and body.reviews_per_case != _minimum_reviews_per_case(campaign)
        ):
            raise APIError(
                409,
                "campaign_review_count_frozen",
                "Review count is frozen",
                "The number of reviews per case cannot change after publication.",
            )
        policy = dict(campaign.policy_json)
        current_scope = campaign.review_scope_json or {}
        source_changed = body.review_scope is not None and list(
            body.review_scope.source_families
        ) != list(current_scope.get("source_families") or [])
        selector_fields = {
            "case_filter",
            "case_id_selection",
            "case_id_selection_file_name",
        }
        selector_supplied = bool(body.model_fields_set & selector_fields)
        selector_changed = False
        if selector_supplied:
            next_filter = (body.case_filter or CampaignCaseFilter()).model_dump(mode="json")
            next_selection = (
                body.case_id_selection.model_dump(mode="json")
                if body.case_id_selection is not None
                else None
            )
            selector_changed = (
                next_filter
                != (policy.get("case_filter") or CampaignCaseFilter().model_dump(mode="json"))
                or next_selection != policy.get("case_id_selection")
                or body.case_id_selection_file_name != policy.get("case_id_selection_file_name")
            )
        if (source_changed or selector_changed) and not body.confirm:
            raise APIError(
                409,
                "campaign_edit_requires_confirmation",
                "Confirmation required",
                "Changing a campaign source or case selector requires confirm=true.",
            )
        if body.campaign_name is not None:
            campaign.name = body.campaign_name
        if body.review_scope is not None:
            self._apply_review_scope(
                session,
                tenant_id=tenant_id,
                principal=principal,
                campaign=campaign,
                review_scope=body.review_scope,
            )
        if body.reviews_per_case is not None:
            policy["minimum_reviews_per_case"] = body.reviews_per_case
        if body.case_id_selection is not None:
            if body.applied_case_id_token is None:
                raise APIError(
                    409,
                    "case_ids_not_applied",
                    "Upload case IDs first",
                    "Upload and check the case-ID file before saving campaign changes.",
                )
            scope = campaign.review_scope_json or {}
            verify_case_id_selection(
                session,
                tenant_id=tenant_id,
                source_families=list(scope.get("source_families") or []),
                case_id_selection=body.case_id_selection,
                applied_case_id_token=body.applied_case_id_token,
                receipt_key=self.campaign_filter_receipt_key,
            )
            policy["case_filter"] = CampaignCaseFilter().model_dump(mode="json")
            policy["case_id_selection"] = body.case_id_selection.model_dump(mode="json")
            policy["case_id_selection_file_name"] = body.case_id_selection_file_name
        elif "case_filter" in body.model_fields_set:
            next_case_filter = body.case_filter or CampaignCaseFilter()
            if next_case_filter.all:
                if body.applied_filter_token is None:
                    raise APIError(
                        409,
                        "case_filter_not_applied",
                        "Apply filters first",
                        "Apply the case filter before saving campaign changes.",
                    )
                scope = campaign.review_scope_json or {}
                verify_case_filter(
                    session,
                    tenant_id=tenant_id,
                    source_families=list(scope.get("source_families") or []),
                    case_filter=next_case_filter,
                    applied_filter_token=body.applied_filter_token,
                    database=self.campaign_filter_database,
                    receipt_key=self.campaign_filter_receipt_key,
                )
            policy["case_filter"] = next_case_filter.model_dump(mode="json")
            policy["case_id_selection"] = None
            policy["case_id_selection_file_name"] = None
        campaign.policy_json = policy
        campaign.lock_version += 1
        session.flush()
        append_audit_event(
            session,
            actor_user_id=principal.user.id,
            actor_type="user",
            event_type="admin.campaign_edited",
            object_type="campaign",
            object_id=str(campaign.id),
            request_id=request_id,
            payload={
                "tenant_id": str(tenant_id),
                "case_filter": (
                    body.case_filter.model_dump(mode="json")
                    if body.case_filter is not None
                    else None
                ),
                "case_id_selection_count": (
                    len(body.case_id_selection.case_ids)
                    if body.case_id_selection is not None
                    else None
                ),
            },
            key=self.audit_key,
        )
        return _campaign_detail_response(session, campaign)

    def _apply_review_scope(
        self,
        session: Session,
        *,
        tenant_id: uuid.UUID,
        principal: Principal,
        campaign: Campaign,
        review_scope: CampaignReviewScopeInput,
    ) -> None:
        """Persist a new field scope, materializing any newly added groups for existing cases.

        Widening the scope must not leave the campaign with two different per-case field
        coverages     (original cases on the old groups, later-loaded cases on the wider
        set), so the added groups     are pulled from the pool for the cases the
        campaign already holds. Field scope stays     disjoint across campaigns: if
        another campaign already owns one of those case/group pairs,     the whole edit
        is rejected rather than silently widening coverage we cannot deliver.

        Narrowing (or leaving the groups unchanged) touches no units -- units already
        materialized     for a dropped group stay put; returning them to the pool would
        be a separate, destructive     decision the admin has not asked for here."""

        previous = campaign.review_scope_json or {}
        previous_groups = set(previous.get("group_ids") or [])
        new_groups = set(review_scope.group_ids or [])
        # An empty scope means "no narrowing" everywhere else in the platform, so it is already the
        # widest possible scope -- moving away from it can only narrow, never add groups.
        added = sorted(new_groups - previous_groups) if previous_groups and new_groups else []

        if added:
            pool_campaign = get_or_create_pool_campaign(
                session, tenant_id=tenant_id, created_by=principal.user.id
            )
            lock_pool_claims(session, tenant_id=tenant_id)
            _units_moved, conflicts = backfill_widened_scope(
                session,
                tenant_id=tenant_id,
                pool_campaign=pool_campaign,
                target_campaign=campaign,
                added_group_ids=added,
                required_reviews=_minimum_reviews_per_case(campaign),
            )
            if conflicts:
                shown = "; ".join(
                    f"{c.case_id}/{c.group_id} is held by campaign '{c.campaign_key}'"
                    for c in conflicts[:5]
                )
                more = "" if len(conflicts) <= 5 else f" (and {len(conflicts) - 5} more)"
                raise APIError(
                    409,
                    "campaign_scope_conflict",
                    "Field scope conflict",
                    "Cannot widen this campaign's field scope: another campaign already holds "
                    f"these fields for cases in this campaign -- {shown}{more}. Field scope is "
                    "disjoint across campaigns; release the other campaign first.",
                )

        campaign.review_scope_json = review_scope.model_dump(mode="json")
