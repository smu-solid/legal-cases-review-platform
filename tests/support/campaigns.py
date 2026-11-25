from __future__ import annotations

import uuid

from sqlalchemy import text

from review_platform.db.models import RoleGrant, TenantMembership, User
from review_platform.db.session import Database
from review_platform.security import hash_password
from review_platform.settings import Settings
from tests.support.clients import login, mutation_headers
from tests.support.identities import TEST_PASSWORD, AdminIdentity, ReviewIdentity


def expire_assignment_lease(database: Database, tenant_id: uuid.UUID, assignment_id: str) -> None:
    """Force an assignment's lease into the past, as a real lapse would leave it."""

    with database.session() as session, session.begin():
        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        session.execute(
            text(
                "UPDATE review_platform.assignments SET lease_expires_at = claimed_at "
                "WHERE tenant_id = :tenant_id AND id = :assignment_id"
            ),
            {"tenant_id": str(tenant_id), "assignment_id": str(assignment_id)},
        )


def release_assignment(database: Database, tenant_id: uuid.UUID, assignment_id: str) -> None:
    """Leave the row an incremental rebalance leaves behind when it moves a unit away.

    ``allocation/incremental_publish.py`` flips the previous holder's row to ``released`` rather
    than deleting it, so the movement stays auditable. Tests use this to reproduce the state a
    rebalanced reviewer is actually left in without running a whole allocation cycle.
    """

    with database.session() as session, session.begin():
        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        session.execute(
            text(
                "UPDATE review_platform.assignments SET status = 'released' "
                "WHERE tenant_id = :tenant_id AND id = :assignment_id"
            ),
            {"tenant_id": str(tenant_id), "assignment_id": str(assignment_id)},
        )


def close_campaign(database: Database, tenant_id: uuid.UUID, key: str) -> None:
    """Close campaign."""

    with database.session() as session, session.begin():
        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(tenant_id)},
        )
        session.execute(
            text(
                "UPDATE review_platform.campaigns SET status = 'closed' "
                "WHERE tenant_id = :tenant_id AND key = :key"
            ),
            {"tenant_id": str(tenant_id), "key": key},
        )


async def import_campaign(
    client,
    admin: AdminIdentity,
    *,
    key: str = "synthetic-review",
    review_kinds: list[str] | None = None,
    reviews_per_case: int | None = None,
) -> dict[str, object]:
    """Import the v0001 synthetic fixture as a campaign.

    The fixture carries two review kinds (``metadata_field`` plus a ``citation_link`` for the
    ``citation_neutral`` target). Pass ``review_kinds`` when a test is about something other than
    kind coverage -- e.g. subject *ranking* -- and wants a single-kind campaign to assert against.
    A campaign imported without it declares no scope, which means "every field", so all of the
    fixture's units are eligible for allocation.
    """

    response, csrf_token = await login(client, admin.email, admin.password)
    assert response.status_code == 200
    payload: dict[str, object] = {
        "fixture_version": "v0001",
        "campaign_key": key,
        "campaign_name": "Synthetic Review",
    }
    if review_kinds is not None:
        payload["review_scope"] = {"review_kinds": review_kinds}
    if reviews_per_case is not None:
        payload["reviews_per_case"] = reviews_per_case
    imported = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/review/import-synthetic",
        json=payload,
        headers={**mutation_headers(csrf_token), "Idempotency-Key": f"import-{key}-0001"},
    )
    assert imported.status_code == 201, imported.text
    return dict(imported.json())


def add_review_user(
    database: Database,
    settings: Settings,
    admin: AdminIdentity,
    *,
    email: str,
    role: str,
) -> ReviewIdentity:
    with database.session() as session, session.begin():
        user = User(
            email_normalized=email,
            display_name=email.split("@", maxsplit=1)[0],
            password_hash=hash_password(TEST_PASSWORD, settings),
            status="active",
            authorization_epoch=1,
        )
        session.add(user)
        session.flush()
        membership = TenantMembership(
            tenant_id=admin.tenant_id,
            user_id=user.id,
            status="active",
        )
        session.add(membership)
        session.flush()
        session.add(
            RoleGrant(
                membership_id=membership.id,
                role_code=role,
                granted_by=admin.user_id,
            )
        )
    return ReviewIdentity(user_id=user.id, email=email, password=TEST_PASSWORD)


async def claim_field(
    client,
    csrf_token: str,
    tenant_id: str,
    campaign_id: str,
    field_label: str,
    *,
    idem: str,
) -> str:
    queue = await client.get(
        f"/api/v1/tenants/{tenant_id}/review/queue",
        params={"campaign_id": campaign_id},
    )
    assert queue.status_code == 200, queue.text
    item = next(i for i in queue.json()["items"] if i["safe_field_label"] == field_label)
    claim = await client.post(
        f"/api/v1/tenants/{tenant_id}/review/claim",
        json={"review_unit_id": item["review_unit_id"]},
        headers={**mutation_headers(csrf_token), "Idempotency-Key": idem},
    )
    assert claim.status_code == 201, claim.text
    return str(claim.json()["assignment_id"])
