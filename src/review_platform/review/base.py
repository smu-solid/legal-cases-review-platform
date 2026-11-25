"""Shared base for the review workflow service: RBAC, idempotency, scope, and adjudication advance.

The review operation mixins (import, queue, claim, bundles, submissions, admin, adjudication)
compose over this base, which owns the helpers they share.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from review_platform.auth.grant_policy import has_global_admin
from review_platform.auth.service import Principal, now_utc
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.dataset.catalog import DatasetCatalog
from review_platform.dataset.contract import SnapshotReader
from review_platform.db.models import GlobalRoleGrant, RoleGrant, TenantMembership, User
from review_platform.review.idempotency import IdempotencyMixin
from review_platform.review.models import (
    Adjudication,
    AdjudicationDecision,
    AdjudicationParticipation,
    Assignment,
    ReviewUnit,
)

LEASE_SECONDS = 900
SUPPORTED_VERDICTS = frozenset(
    {"supported", "partially_supported", "unsupported", "not_enough_context"}
)


class ReviewServiceBase(IdempotencyMixin):
    def __init__(
        self,
        reader: SnapshotReader,
        audit_key: str,
        *,
        synthetic_enabled: bool,
        campaign_filter_database: DatasetCatalog | None = None,
    ) -> None:
        self.reader = reader
        self.audit_key = audit_key
        self.synthetic_enabled = synthetic_enabled
        self.campaign_filter_database = campaign_filter_database or DatasetCatalog(None)
        # Domain separation prevents campaign receipts from being accepted as audit signatures.
        # This deliberately avoids another deployment secret for the first version while retaining
        # a cryptographically independent derived key.
        self.campaign_filter_receipt_key = hashlib.sha256(
            f"campaign-case-filter/v1:{audit_key}".encode()
        ).hexdigest()

    @staticmethod
    def _slot_active_clause(now: datetime) -> ColumnElement[bool]:
        """Assignments that still occupy a review-unit slot at ``now``.

        A submitted assignment always occupies its slot; a claimed assignment occupies it only
        while its lease is live. A claimed assignment whose lease has expired releases its slot so
        another reviewer can reclaim the freed capacity. The expired holder may still recover in
        place -- draft/submit/renew re-extend a lapsed lease via
        ``_expired_lease_slot_available`` -- but only while the freed capacity remains untaken;
        once another reviewer fills the unit's last slot the expired holder is blocked for good.
        An assignment a manager returned for revision keeps its slot reserved for that reviewer's
        correction, so the freed capacity cannot be reclaimed and a reopen never over-allocates a
        unit beyond ``required_reviews``.
        """

        return or_(
            Assignment.status.in_(("submitted", "revision_requested")),
            and_(Assignment.status == "claimed", Assignment.lease_expires_at > now),
        )

    def _expired_lease_slot_available(
        self, session: Session, assignment: Assignment, now: datetime
    ) -> bool:
        """Whether an expired claimed lease can be re-extended without over-allocating its unit."""

        required_reviews = session.scalar(
            select(ReviewUnit.required_reviews).where(
                ReviewUnit.tenant_id == assignment.tenant_id,
                ReviewUnit.id == assignment.review_unit_id,
            )
        )
        if required_reviews is None:  # pragma: no cover - composite FK invariant
            return False
        active_count = (
            session.scalar(
                select(func.count())
                .select_from(Assignment)
                .where(
                    Assignment.tenant_id == assignment.tenant_id,
                    Assignment.review_unit_id == assignment.review_unit_id,
                    Assignment.id != assignment.id,
                    self._slot_active_clause(now),
                )
            )
            or 0
        )
        return active_count < required_reviews

    def _require_role(
        self,
        session: Session,
        principal: Principal,
        tenant_id: uuid.UUID,
        role: str,
        *,
        allow_global_admin: bool = False,
    ) -> None:
        if allow_global_admin and has_global_admin(session, principal.user.id):
            return
        allowed = session.scalar(
            select(func.count())
            .select_from(TenantMembership)
            .join(RoleGrant, RoleGrant.membership_id == TenantMembership.id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.user_id == principal.user.id,
                TenantMembership.status == "active",
                RoleGrant.role_code == role,
                RoleGrant.revoked_at.is_(None),
            )
        )
        if not allowed:
            raise APIError(403, "forbidden", "Forbidden", "The action is not permitted.")

    def _reconcile_inactive_adjudicators(
        self, session: Session, *, tenant_id: uuid.UUID, request_id: str
    ) -> None:
        """Waive snapshotted participants whose adjudication authority is no longer active."""

        pending = session.execute(
            select(AdjudicationParticipation, User)
            .join(User, User.id == AdjudicationParticipation.adjudicator_id)
            .where(
                AdjudicationParticipation.tenant_id == tenant_id,
                AdjudicationParticipation.status == "pending",
            )
            .with_for_update(of=AdjudicationParticipation)
        ).all()
        changed_adjudications: set[uuid.UUID] = set()
        current = now_utc()
        for participation, user in pending:
            tenant_role = session.scalar(
                select(func.count())
                .select_from(TenantMembership)
                .join(RoleGrant, RoleGrant.membership_id == TenantMembership.id)
                .where(
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.user_id == user.id,
                    TenantMembership.status == "active",
                    RoleGrant.role_code == "adjudicator",
                    RoleGrant.revoked_at.is_(None),
                )
            )
            still_global = session.scalar(
                select(func.count())
                .select_from(GlobalRoleGrant)
                .where(
                    GlobalRoleGrant.user_id == user.id,
                    GlobalRoleGrant.role_code == "super_admin",
                    GlobalRoleGrant.revoked_at.is_(None),
                    or_(GlobalRoleGrant.expires_at.is_(None), GlobalRoleGrant.expires_at > current),
                )
            )
            if user.status == "active" and ((tenant_role or 0) > 0 or (still_global or 0) > 0):
                continue
            participation.status = "waived"
            participation.waived_at = current
            changed_adjudications.add(participation.adjudication_id)
            append_audit_event(
                session,
                actor_user_id=None,
                actor_type="system",
                event_type="review.adjudication_participation_waived",
                object_type="adjudication_participation",
                object_id=str(participation.id),
                request_id=request_id,
                payload={
                    "tenant_id": str(tenant_id),
                    "adjudication_id": str(participation.adjudication_id),
                    "review_unit_id": str(
                        session.scalar(
                            select(Adjudication.review_unit_id).where(
                                Adjudication.tenant_id == tenant_id,
                                Adjudication.id == participation.adjudication_id,
                            )
                        )
                    ),
                    "adjudicator_id": str(participation.adjudicator_id),
                    "transition": "pending_to_waived",
                },
                key=self.audit_key,
            )
        for adjudication_id in changed_adjudications:
            self._resolve_shared_adjudication_if_complete(
                session, tenant_id=tenant_id, adjudication_id=adjudication_id
            )

    @staticmethod
    def _resolve_shared_adjudication_if_complete(
        session: Session, *, tenant_id: uuid.UUID, adjudication_id: uuid.UUID
    ) -> bool:
        pending_count = (
            session.scalar(
                select(func.count())
                .select_from(AdjudicationParticipation)
                .where(
                    AdjudicationParticipation.tenant_id == tenant_id,
                    AdjudicationParticipation.adjudication_id == adjudication_id,
                    AdjudicationParticipation.status == "pending",
                )
            )
            or 0
        )
        decision_count = (
            session.scalar(
                select(func.count())
                .select_from(AdjudicationDecision)
                .where(
                    AdjudicationDecision.tenant_id == tenant_id,
                    AdjudicationDecision.adjudication_id == adjudication_id,
                )
            )
            or 0
        )
        if pending_count or not decision_count:
            return False
        adjudication = session.scalar(
            select(Adjudication).where(
                Adjudication.tenant_id == tenant_id,
                Adjudication.id == adjudication_id,
            )
        )
        if adjudication is None:
            return False
        unit = session.scalar(
            select(ReviewUnit).where(
                ReviewUnit.tenant_id == tenant_id,
                ReviewUnit.id == adjudication.review_unit_id,
            )
        )
        adjudication.status = "resolved"
        if unit is not None and unit.status != "resolved":
            unit.status = "resolved"
            unit.lock_version += 1
        return True

    @staticmethod
    def _request_digest(value: Any) -> str:
        return digest_json(value)

    def _own_assignment_for_update(
        self,
        session: Session,
        tenant_id: uuid.UUID,
        assignment_id: uuid.UUID,
        principal: Principal,
    ) -> Assignment:
        """Row-lock the caller's own assignment, raising 404 when it is not theirs or absent."""

        assignment = session.scalar(
            select(Assignment)
            .where(
                Assignment.tenant_id == tenant_id,
                Assignment.id == assignment_id,
                Assignment.reviewer_id == principal.user.id,
            )
            .with_for_update()
        )
        if assignment is None:
            raise APIError(404, "not_found", "Not found", "The resource was not found.")
        return assignment

    def _advance_to_adjudication(
        self, session: Session, assignment: Assignment, *, request_id: str
    ) -> None:
        self.advance_to_adjudication(
            session, assignment, request_id=request_id, audit_key=self.audit_key
        )

    @staticmethod
    def advance_to_adjudication(
        session: Session, assignment: Assignment, *, request_id: str, audit_key: str
    ) -> None:
        """Use the normal completion workflow for submitted or restored reviewer answers."""
        unit = session.scalar(
            select(ReviewUnit)
            .where(
                ReviewUnit.tenant_id == assignment.tenant_id,
                ReviewUnit.id == assignment.review_unit_id,
            )
            .with_for_update()
        )
        if unit is None:  # pragma: no cover - composite FK invariant
            raise RuntimeError("assignment review unit disappeared")
        submitted_count = session.scalar(
            select(func.count())
            .select_from(Assignment)
            .where(
                Assignment.tenant_id == assignment.tenant_id,
                Assignment.review_unit_id == assignment.review_unit_id,
                Assignment.status == "submitted",
            )
        )
        if (submitted_count or 0) < unit.required_reviews:
            return
        adjudication = session.scalar(
            select(Adjudication).where(
                Adjudication.tenant_id == assignment.tenant_id,
                Adjudication.review_unit_id == assignment.review_unit_id,
            )
        )
        if adjudication is None:  # pragma: no branch - submissions transition only once
            adjudication = Adjudication(
                tenant_id=assignment.tenant_id,
                review_unit_id=assignment.review_unit_id,
            )
            session.add(adjudication)
            session.flush()
            current = now_utc()
            tenant_adjudicators = (
                select(TenantMembership.user_id)
                .join(RoleGrant, RoleGrant.membership_id == TenantMembership.id)
                .join(User, User.id == TenantMembership.user_id)
                .where(
                    TenantMembership.tenant_id == assignment.tenant_id,
                    TenantMembership.status == "active",
                    User.status == "active",
                    RoleGrant.role_code == "adjudicator",
                    RoleGrant.revoked_at.is_(None),
                )
            )
            global_admins = (
                select(GlobalRoleGrant.user_id)
                .join(User, User.id == GlobalRoleGrant.user_id)
                .where(
                    User.status == "active",
                    GlobalRoleGrant.role_code == "super_admin",
                    GlobalRoleGrant.revoked_at.is_(None),
                    or_(GlobalRoleGrant.expires_at.is_(None), GlobalRoleGrant.expires_at > current),
                )
            )
            reviewer_ids = select(Assignment.reviewer_id).where(
                Assignment.tenant_id == assignment.tenant_id,
                Assignment.review_unit_id == assignment.review_unit_id,
            )
            eligible_ids = set(session.scalars(tenant_adjudicators.union(global_admins)))
            conflicted_ids = set(session.scalars(reviewer_ids))
            participants = []
            for adjudicator_id in eligible_ids - conflicted_ids:
                participation = AdjudicationParticipation(
                    tenant_id=assignment.tenant_id,
                    adjudication_id=adjudication.id,
                    adjudicator_id=adjudicator_id,
                    assigned_at=current,
                )
                session.add(participation)
                participants.append(participation)
            session.flush()
            if not participants:
                append_audit_event(
                    session,
                    actor_user_id=assignment.reviewer_id,
                    actor_type="user",
                    event_type="review.adjudication_no_eligible_participants",
                    object_type="adjudication",
                    object_id=str(adjudication.id),
                    request_id=request_id,
                    payload={
                        "review_unit_id": str(assignment.review_unit_id),
                        "transition": "ready_without_participants",
                    },
                    key=audit_key,
                )
            for participation in participants:
                append_audit_event(
                    session,
                    actor_user_id=assignment.reviewer_id,
                    actor_type="user",
                    event_type="review.adjudication_participant_snapshotted",
                    object_type="adjudication_participation",
                    object_id=str(participation.id),
                    request_id=request_id,
                    payload={
                        "adjudication_id": str(adjudication.id),
                        "review_unit_id": str(assignment.review_unit_id),
                        "adjudicator_id": str(participation.adjudicator_id),
                        "transition": "snapshotted_pending",
                    },
                    key=audit_key,
                )
        unit.status = "in_adjudication"
        unit.lock_version += 1
