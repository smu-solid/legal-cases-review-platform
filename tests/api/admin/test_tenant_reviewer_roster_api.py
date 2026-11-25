from __future__ import annotations

import uuid
from contextlib import AsyncExitStack

import pytest
from sqlalchemy import select

from review_platform.db.models import RoleGrant, Tenant, TenantMembership, User
from review_platform.db.session import Database
from review_platform.security import hash_password
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.identities import TEST_PASSWORD, AdminIdentity


def roster_path(tenant_id: uuid.UUID | str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/reviewers"


def add_role(database: Database, user_id: uuid.UUID, role: str) -> None:
    with database.session() as session, session.begin():
        membership_id = session.scalar(
            select(TenantMembership.id).where(TenantMembership.user_id == user_id)
        )
        assert membership_id is not None
        session.add(RoleGrant(membership_id=membership_id, role_code=role, granted_by=user_id))


def add_other_tenant_reviewer(
    database: Database, settings: Settings, admin: AdminIdentity
) -> tuple[uuid.UUID, uuid.UUID]:
    with database.session() as session, session.begin():
        tenant = Tenant(key="other-roster-tenant", name="Other Roster Tenant")
        session.add(tenant)
        session.flush()
        user = User(
            email_normalized="other-roster-reviewer@example.test",
            display_name="Other Roster Reviewer",
            password_hash=hash_password(TEST_PASSWORD, settings),
            status="active",
            authorization_epoch=1,
        )
        session.add(user)
        session.flush()
        membership = TenantMembership(tenant_id=tenant.id, user_id=user.id, status="active")
        session.add(membership)
        session.flush()
        session.add(
            RoleGrant(membership_id=membership.id, role_code="reviewer", granted_by=admin.user_id)
        )
        return tenant.id, user.id


def add_pending_reviewer(
    database: Database, admin: AdminIdentity, *, email: str, display_name: str
) -> uuid.UUID:
    """Invite-only reviewer that has never logged in: pending user + pending membership + reviewer
    grant, no password, no activation timestamp, no session. Mirrors
    ``provision_reviewer_roster_entry`` so the roster surfaces a ``pending`` lifecycle row."""

    with database.session() as session, session.begin():
        user = User(email_normalized=email, display_name=display_name, status="pending")
        session.add(user)
        session.flush()
        membership = TenantMembership(tenant_id=admin.tenant_id, user_id=user.id, status="pending")
        session.add(membership)
        session.flush()
        session.add(
            RoleGrant(membership_id=membership.id, role_code="reviewer", granted_by=admin.user_id)
        )
        return user.id


@pytest.mark.anyio
async def test_roster_surfaces_activity_and_workload(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    """The roster enriches each reviewer with lifecycle status, first/last activity, and
    per-reviewer assignment workload. An active reviewer who logs in and claims a unit reports a
    last-seen time and claimed workload; an invited (never-logged-in) reviewer stays ``pending``
    with null activity and zero workload."""

    tenant_admin = add_review_user(
        database, settings, admin, email="enrich-admin@example.test", role="user_admin"
    )
    reviewer = add_review_user(
        database, settings, admin, email="enrich-active@example.test", role="reviewer"
    )
    pending_id = add_pending_reviewer(
        database, admin, email="enrich-pending@example.test", display_name="Pending Reviewer"
    )

    async with AsyncExitStack() as stack:
        admin_client, admin_read_client, reviewer_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(admin_client, admin, key="roster-enrich")
        campaign_id = str(imported["campaign_id"])

        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        claim = await reviewer_client.post(
            f"/api/v1/tenants/{admin.tenant_id}/review/claim",
            json={"campaign_id": campaign_id},
            headers={**mutation_headers(reviewer_csrf), "Idempotency-Key": "roster-enrich-claim-1"},
        )
        assert claim.status_code == 201, claim.text

        await authenticate(admin_read_client, tenant_admin)
        response = await admin_read_client.get(roster_path(admin.tenant_id), params={"limit": "50"})

    assert response.status_code == 200, response.text
    items = {item["user_id"]: item for item in response.json()["items"]}

    active = items[str(reviewer.user_id)]
    assert active["roster_status"] == "active"
    assert active["eligible"] is True
    assert active["last_seen_at"] is not None
    assert active["total_assignments"] == 1
    assert active["claimed_count"] == 1
    assert active["submitted_count"] == 0
    assert active["released_count"] == 0

    pending = items[str(pending_id)]
    assert pending["roster_status"] == "pending"
    assert pending["eligible"] is False
    assert pending["first_seen_at"] is None
    assert pending["last_seen_at"] is None
    assert pending["total_assignments"] == 0
    assert pending["claimed_count"] == 0
    assert pending["submitted_count"] == 0
    assert pending["released_count"] == 0


@pytest.mark.anyio
async def test_tenant_reviewer_roster_rbac_isolation_and_sanitization(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    tenant_admin = add_review_user(
        database, settings, admin, email="roster-admin@example.test", role="user_admin"
    )
    reviewer = add_review_user(
        database, settings, admin, email="roster-reviewer-a@example.test", role="reviewer"
    )
    hybrid = add_review_user(
        database, settings, admin, email="roster-reviewer-b@example.test", role="reviewer"
    )
    add_role(database, hybrid.user_id, "campaign_manager")
    adjudicator = add_review_user(
        database, settings, admin, email="roster-adjudicator@example.test", role="adjudicator"
    )
    other_tenant_id, other_user_id = add_other_tenant_reviewer(database, settings, admin)

    async with AsyncExitStack() as stack:
        admin_client, tenant_admin_client, reviewer_client, anon_client = await open_clients(
            stack, settings, 4
        )
        tenant_admin_csrf = await authenticate(tenant_admin_client, tenant_admin)
        reviewer_csrf = await authenticate(reviewer_client, reviewer)

        unauth = await anon_client.get(roster_path(admin.tenant_id))
        assert unauth.status_code == 401

        forbidden = await reviewer_client.get(roster_path(admin.tenant_id))
        assert forbidden.status_code == 403
        assert forbidden.json()["code"] == "forbidden"

        missing_or_cross = await tenant_admin_client.get(roster_path(other_tenant_id))
        assert missing_or_cross.status_code == 403
        assert missing_or_cross.json()["code"] == "forbidden"

        first = await tenant_admin_client.get(roster_path(admin.tenant_id), params={"limit": "1"})
        assert first.status_code == 200, first.text
        body = first.json()
        assert body["has_more"] is True
        assert body["next_cursor"]
        assert len(body["items"]) == 1

        second = await tenant_admin_client.get(
            roster_path(admin.tenant_id), params={"limit": "10", "cursor": body["next_cursor"]}
        )
        assert second.status_code == 200, second.text
        all_items = body["items"] + second.json()["items"]

        returned_user_ids = {item["user_id"] for item in all_items}
        assert str(reviewer.user_id) in returned_user_ids
        assert str(hybrid.user_id) in returned_user_ids
        assert str(adjudicator.user_id) not in returned_user_ids
        assert str(other_user_id) not in returned_user_ids
        assert all(item["eligible"] is True for item in all_items)
        assert all("reviewer" in item["roles"] for item in all_items)
        assert any("campaign_manager" in item["roles"] for item in all_items)

        response_text = first.text + second.text
        for forbidden_text in (
            "@example.test",
            "password",
            "token",
            "email",
            "validator",
            "peer",
            str(other_user_id),
        ):
            assert forbidden_text not in response_text

        invalid = await tenant_admin_client.get(
            roster_path(admin.tenant_id), params={"cursor": "not-a-cursor"}
        )
        assert invalid.status_code == 422
        assert invalid.json()["code"] == "cursor_invalid"

        # Keep the authenticated sessions live so the test exercises ordinary read auth, not CSRF.
        assert tenant_admin_csrf
        assert reviewer_csrf


@pytest.mark.anyio
async def test_super_admin_can_read_roster_without_broad_admin_suite(
    settings: Settings, database: Database, admin: AdminIdentity
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="roster-super-reader@example.test", role="reviewer"
    )
    async with AsyncExitStack() as stack:
        (client,) = await open_clients(stack, settings, 1)
        await authenticate(client, admin)
        response = await client.get(roster_path(admin.tenant_id))

    assert response.status_code == 200
    body = response.json()
    assert [item["user_id"] for item in body["items"]] == [str(reviewer.user_id)]
    assert "global_roles" not in response.text
