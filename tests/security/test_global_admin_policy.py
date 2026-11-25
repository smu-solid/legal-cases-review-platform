from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from review_platform.auth import grant_policy
from review_platform.auth.principal import Principal
from review_platform.common.errors import APIError
from review_platform.dataset.fixture_reader import FixtureDatasetReader
from review_platform.db.models import GlobalRoleGrant, User
from review_platform.review.allocation.service_base import AllocationServiceBase
from review_platform.review.base import ReviewServiceBase
from tests.support.identities import AdminIdentity


@pytest.mark.parametrize("surface", ["review", "allocation"])
@pytest.mark.parametrize(
    ("grant_state", "allowed"),
    [
        ("missing", False),
        ("durable", True),
        ("active", True),
        ("expires_now", False),
        ("expired", False),
        ("revoked", False),
    ],
)
def test_global_admin_access_requires_a_live_grant_for_the_actor(
    db_session: Session,
    admin: AdminIdentity,
    monkeypatch: pytest.MonkeyPatch,
    surface: str,
    grant_state: str,
    allowed: bool,
) -> None:
    current = datetime.now(UTC)
    monkeypatch.setattr(grant_policy, "now_utc", lambda: current)
    user = User(
        email_normalized="grant-policy@example.test",
        display_name="Grant policy test",
        status="active",
    )
    db_session.add(user)
    db_session.flush()
    if grant_state != "missing":
        expires_at = {
            "durable": None,
            "active": current + timedelta(minutes=5),
            "expires_now": current,
            "expired": current - timedelta(seconds=1),
            "revoked": None,
        }[grant_state]
        db_session.add(
            GlobalRoleGrant(
                user_id=user.id,
                granted_by=admin.user_id,
                reason="Shared authorization regression test",
                expires_at=expires_at,
                revoked_at=current if grant_state == "revoked" else None,
            )
        )
        db_session.flush()
    principal = Principal(user=user, server_session=None)
    global_grant_queries: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _executemany):
        if "global_role_grants" in statement:
            global_grant_queries.append(statement)

    def authorize() -> None:
        if surface == "review":
            ReviewServiceBase(
                FixtureDatasetReader(Path("fixtures/dataset_contracts")),
                audit_key="test-audit-key",
                synthetic_enabled=True,
            )._require_role(
                db_session,
                principal,
                admin.tenant_id,
                "campaign_manager",
                allow_global_admin=True,
            )
        elif surface == "allocation":
            AllocationServiceBase("test-audit-key")._require_campaign_manager(
                db_session, principal, admin.tenant_id
            )

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        if allowed:
            authorize()
        else:
            with pytest.raises(APIError) as caught:
                authorize()
            assert caught.value.status == 403
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(global_grant_queries) == 1
