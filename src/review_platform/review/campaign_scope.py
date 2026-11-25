"""Campaign review-scope catalog: the backend-owned allowlist a campaign scope may select from."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from review_platform.auth.service import Principal
from review_platform.review.base import ReviewServiceBase
from review_platform.review.grouping import (
    DEFAULT_ATOMIC_GROUP_ID,
    GROUP_DEFINITIONS,
    SUPPORTED_REVIEW_KINDS,
)
from review_platform.review.schemas import CampaignScopeCatalogResponse, CampaignScopeGroup


class ReviewCampaignScopeMixin(ReviewServiceBase):
    def campaign_scope_catalog(
        self, session: Session, *, tenant_id: uuid.UUID, principal: Principal
    ) -> CampaignScopeCatalogResponse:
        """Return the backend-owned catalog of selectable scope field groups and review kinds.

        Static, closed allowlist so the UI can render campaign scope selection without inferring
        groups or kinds from the database. campaign_manager only; no tenant data is read.
        """
        self._require_role(
            session, principal, tenant_id, "campaign_manager", allow_global_admin=True
        )
        # Exclude the additional_fields catch-all from the selectable scope catalog: importers
        # fail closed on unmapped columns (require_atomic_group), so no real-imported field can
        # ever land there -- offering it as campaign scope would be a permanently-empty choice.
        # It still exists as classify_unit's internal default group; only this catalog omits it.
        groups = [
            CampaignScopeGroup(
                group_id=group.group_id,
                group_label=group.group_label,
                group_kind=group.group_kind,
                order=group.order,
                description=group.description,
            )
            for group in GROUP_DEFINITIONS
            if group.group_id != DEFAULT_ATOMIC_GROUP_ID
        ]
        return CampaignScopeCatalogResponse(
            tenant_id=tenant_id, groups=groups, review_kinds=list(SUPPORTED_REVIEW_KINDS)
        )
