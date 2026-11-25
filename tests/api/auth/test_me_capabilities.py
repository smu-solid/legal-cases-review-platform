"""`/me` capability metadata is the RBAC routing contract the UI depends on.

These tests pin the capability strings surfaced per membership so a change to
``ROLE_CAPABILITIES`` that would silently break client-side routing (as happened when the
reviewer role advertised ``review:participate`` while the reviewer surface routes on
``review:claim``/``review:submit``) fails here instead of only in the live UI.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from review_platform.db.models import RoleGrant, TenantMembership
from review_platform.db.session import Database
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user
from tests.support.clients import login
from tests.support.identities import AdminIdentity


def _membership(session_db: Database, admin: AdminIdentity, user_id: object) -> TenantMembership:
    with session_db.session() as session:
        membership = session.scalar(
            select(TenantMembership).where(
                TenantMembership.tenant_id == admin.tenant_id,
                TenantMembership.user_id == user_id,
            )
        )
    assert membership is not None
    return membership


async def _me(client: httpx.AsyncClient, tenant_id: object) -> dict[str, object]:
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 200
    body = response.json()
    membership = next(item for item in body["memberships"] if item["tenant_id"] == str(tenant_id))
    return dict(membership)


@pytest.mark.anyio
async def test_reviewer_me_exposes_claim_and_submit_capabilities(
    client: httpx.AsyncClient, admin: AdminIdentity, database: Database, settings: Settings
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="rbac-reviewer@example.test", role="reviewer"
    )
    login_response, _ = await login(client, reviewer.email, reviewer.password)
    assert login_response.status_code == 200

    membership = await _me(client, admin.tenant_id)
    assert membership["roles"] == ["reviewer"]
    # The reviewer surface (router guard + nav) gates on either capability; both must be present.
    assert set(membership["capabilities"]) == {"review:claim", "review:submit"}


@pytest.mark.anyio
async def test_reviewer_with_no_work_gets_empty_queue_not_forbidden(
    client: httpx.AsyncClient, admin: AdminIdentity, database: Database, settings: Settings
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="rbac-empty@example.test", role="reviewer"
    )
    assert (await login(client, reviewer.email, reviewer.password))[0].status_code == 200

    queue = await client.get(f"/api/v1/tenants/{admin.tenant_id}/review/queue")
    assert queue.status_code == 200
    assert queue.json()["items"] == []


@pytest.mark.anyio
async def test_multi_role_me_capabilities_are_the_union(
    client: httpx.AsyncClient, admin: AdminIdentity, database: Database, settings: Settings
) -> None:
    member = add_review_user(
        database, settings, admin, email="rbac-multi@example.test", role="reviewer"
    )
    membership = _membership(database, admin, member.user_id)
    with database.session() as session, session.begin():
        session.add(
            RoleGrant(
                membership_id=membership.id,
                role_code="adjudicator",
                granted_by=admin.user_id,
            )
        )
    assert (await login(client, member.email, member.password))[0].status_code == 200

    resolved = await _me(client, admin.tenant_id)
    assert set(resolved["roles"]) == {"reviewer", "adjudicator"}
    assert set(resolved["capabilities"]) == {
        "review:claim",
        "review:submit",
        "adjudication:participate",
    }
