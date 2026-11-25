"""Tenant-scoped member roster reads and invite-only reviewer provisioning for administration."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import case, func, select, text, tuple_
from sqlalchemy.orm import Session

from review_platform.auth.principal import Principal, now_utc
from review_platform.auth.reviewer_email import validate_reviewer_email
from review_platform.common.audit import append_audit_event
from review_platform.common.errors import APIError
from review_platform.common.pagination import decode_cursor, encode_cursor
from review_platform.db.models import RoleGrant, ServerSession, Tenant, TenantMembership, User
from review_platform.review.assignment_status import count_live, count_released
from review_platform.review.models import Assignment

TenantAdminCheck = Callable[[Session, Principal, uuid.UUID], None]


def provision_reviewer_roster_entry(
    session: Session,
    *,
    actor: Principal,
    tenant_id: uuid.UUID,
    email: str,
    display_name: str | None,
    request_id: str,
    require_tenant_admin: TenantAdminCheck,
    audit_key: str,
    allowed_reviewer_domains: Sequence[str] = (),
) -> dict[str, Any]:
    """Add a reviewer email to the tenant roster (invite-only, passwordless).

    Also returns ``invitation_outcome`` so the caller can decide whether an invitation email is
    needed: ``"invited"`` for a roster entry with no prior reviewer grant (first invite),
    ``"reinvited"`` for a still-pending reviewer who already held the grant (idempotent reuse, no
    duplicate rows), or ``"already_active"`` when the membership is already active and no
    notification is warranted."""

    require_tenant_admin(session, actor, tenant_id)
    tenant = session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    normalized = validate_reviewer_email(email, allowed_domains=allowed_reviewer_domains)
    user = session.scalar(select(User).where(User.email_normalized == normalized).with_for_update())
    if user is None:
        user = User(
            email_normalized=normalized,
            display_name=display_name or normalized,
            status="pending",
        )
        session.add(user)
        session.flush()
    membership = session.scalar(
        select(TenantMembership).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.user_id == user.id,
        )
    )
    if membership is None:
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            status="active" if user.status == "active" else "pending",
        )
        session.add(membership)
        session.flush()
    grant = session.scalar(
        select(RoleGrant).where(
            RoleGrant.membership_id == membership.id,
            RoleGrant.role_code == "reviewer",
        )
    )
    grant_existed_before = grant is not None
    if grant is None:
        session.add(
            RoleGrant(
                membership_id=membership.id,
                role_code="reviewer",
                granted_by=actor.user.id,
            )
        )
    elif grant.revoked_at is not None:
        grant.revoked_at = None
        grant.granted_by = actor.user.id
        grant.granted_at = now_utc()
    append_audit_event(
        session,
        actor_user_id=actor.user.id,
        actor_type="user",
        event_type="admin.reviewer_invited",
        object_type="user",
        object_id=str(user.id),
        request_id=request_id,
        payload={"tenant_id": str(tenant_id)},
        key=audit_key,
    )
    if membership.status == "active":
        invitation_outcome = "already_active"
    elif grant_existed_before:
        invitation_outcome = "reinvited"
    else:
        invitation_outcome = "invited"
    return {
        "user_id": user.id,
        "membership_id": membership.id,
        "user_status": user.status,
        "membership_status": membership.status,
        "invitation_outcome": invitation_outcome,
        "reviewer_email": normalized,
        "reviewer_display_name": user.display_name,
        "tenant_name": tenant.name,
    }


def list_tenant_reviewers_for_admin(
    session: Session,
    *,
    actor: Principal,
    tenant_id: uuid.UUID,
    limit: int,
    cursor: str | None,
    require_tenant_admin: TenantAdminCheck,
) -> dict[str, Any]:
    require_tenant_admin(session, actor, tenant_id)
    tenant = session.get(Tenant, tenant_id)
    if tenant is None or tenant.status != "active":
        raise APIError(404, "not_found", "Not found", "The resource was not found.")
    after = decode_cursor(cursor)
    # Invite-only reviewer roster: every current reviewer (non-revoked reviewer grant), regardless
    # of user/membership status, so admins see pending (invited, not yet logged in), active,
    # disabled (suspended), and ineligible reviewers. ``eligible`` is the allocation-facing truth
    # (active user + active membership) rather than a hardcoded flag.
    statement = (
        select(TenantMembership, User)
        .join(User, User.id == TenantMembership.user_id)
        .join(RoleGrant, RoleGrant.membership_id == TenantMembership.id)
        .where(
            TenantMembership.tenant_id == tenant_id,
            RoleGrant.role_code == "reviewer",
            RoleGrant.revoked_at.is_(None),
        )
        .order_by(User.display_name, TenantMembership.id)
        .limit(limit + 1)
    )
    if after is not None:
        statement = statement.where(
            tuple_(User.display_name, TenantMembership.id) > _reviewer_roster_keyset(after)
        )
    rows = session.execute(statement).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    # Enrich the page with activity (first/last seen) and per-reviewer workload counts. Both are
    # computed for exactly the page's users in one grouped query each, so the roster stays a bounded
    # read rather than an N+1 fan-out.
    user_ids = [user.id for _membership, user in page]
    last_seen = _last_seen_by_user(session, user_ids)
    workload = _workload_by_reviewer(session, tenant_id, user_ids)
    items = [
        {
            "user_id": user.id,
            "membership_id": membership.id,
            "display_name": user.display_name,
            "user_status": user.status,
            "membership_status": membership.status,
            "roles": _active_membership_roles(session, membership.id),
            "eligible": _reviewer_eligible(user.status, membership.status),
            "roster_status": _reviewer_roster_status(user.status, membership.status),
            # first seen = first verified login (activation); last seen = latest session activity.
            "first_seen_at": user.activated_at,
            "last_seen_at": last_seen.get(user.id),
            **_workload_counts(workload.get(user.id)),
        }
        for membership, user in page
    ]
    next_cursor: str | None = None
    if has_more:
        last_membership, last_user = page[-1]
        next_cursor = encode_cursor(
            {
                "display_name": last_user.display_name,
                "membership_id": str(last_membership.id),
            }
        )
    return {"items": items, "next_cursor": next_cursor, "has_more": has_more}


def _last_seen_by_user(session: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """Most recent session activity per user. ``server_sessions`` is not tenant-RLS scoped (it is a
    per-user identity table), so no tenant scope is required here."""

    if not user_ids:
        return {}
    rows = session.execute(
        select(ServerSession.user_id, func.max(ServerSession.last_seen_at))
        .where(ServerSession.user_id.in_(user_ids))
        .group_by(ServerSession.user_id)
    ).all()
    return {user_id: last_seen for user_id, last_seen in rows}


def _workload_by_reviewer(
    session: Session, tenant_id: uuid.UUID, user_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int, int, int]]:
    """Per-reviewer assignment status counts (total, submitted, claimed, released) for the tenant.

    ``assignments`` is FORCE-RLS, so the tenant scope is set before the read; the explicit
    ``tenant_id`` filter is defence in depth. ``claimed`` is the reviewer's current (in-progress)
    workload; there is no separate ``completed`` assignment state — ``submitted`` is terminal.
    """

    if not user_ids:
        return {}
    session.execute(
        text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
        {"tenant_id": str(tenant_id)},
    )
    rows = session.execute(
        select(
            Assignment.reviewer_id,
            count_live(Assignment.id),
            func.count(case((Assignment.status == "submitted", Assignment.id))),
            func.count(case((Assignment.status == "claimed", Assignment.id))),
            count_released(Assignment.id),
        )
        .where(Assignment.tenant_id == tenant_id, Assignment.reviewer_id.in_(user_ids))
        .group_by(Assignment.reviewer_id)
    ).all()
    return {
        reviewer_id: (total, submitted, claimed, released)
        for reviewer_id, total, submitted, claimed, released in rows
    }


def _workload_counts(counts: tuple[int, int, int, int] | None) -> dict[str, int]:
    total, submitted, claimed, released = counts or (0, 0, 0, 0)
    return {
        "total_assignments": total,
        "submitted_count": submitted,
        "claimed_count": claimed,
        "released_count": released,
    }


def _reviewer_eligible(user_status: str, membership_status: str) -> bool:
    """A reviewer is eligible for allocation only when both the user and the tenant membership
    are active. This mirrors the allocation engine's own active/authorized check so the
    admin roster and allocation agree on who can be assigned work."""

    return user_status == "active" and membership_status == "active"


def _reviewer_roster_status(user_status: str, membership_status: str) -> str:
    """Collapse user/membership status into the admin-facing lifecycle state. ``disabled`` and
    ``pending`` take precedence so a partially-provisioned or suspended reviewer is never shown as
    active; ``ineligible`` is the residual bucket for any other non-active combination."""

    if user_status == "suspended" or membership_status == "suspended":
        return "disabled"
    if user_status == "pending" or membership_status == "pending":
        return "pending"
    if _reviewer_eligible(user_status, membership_status):
        return "active"
    return "ineligible"


def _active_membership_roles(session: Session, membership_id: uuid.UUID) -> list[str]:
    return sorted(
        session.scalars(
            select(RoleGrant.role_code).where(
                RoleGrant.membership_id == membership_id,
                RoleGrant.revoked_at.is_(None),
            )
        )
    )


def _reviewer_roster_keyset(after: dict[str, object]) -> tuple[str, uuid.UUID]:
    try:
        display_name = str(after["display_name"])
        membership_id = uuid.UUID(str(after["membership_id"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise APIError(422, "cursor_invalid", "Invalid cursor", "The cursor is invalid.") from exc
    return display_name, membership_id
