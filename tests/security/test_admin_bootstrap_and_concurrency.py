from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

import review_platform.bootstrap as bootstrap_module
from review_platform.auth.service import AuthService, Principal
from review_platform.bootstrap import BootstrapRefusedError, bootstrap_first_superuser
from review_platform.common.errors import APIError
from review_platform.db.models import GlobalRoleGrant, User
from review_platform.db.session import Database, DatabaseUnavailableError
from review_platform.security import hash_password
from review_platform.settings import Settings
from tests.support.identities import TEST_PASSWORD, AdminIdentity


def test_concurrent_final_superuser_changes_leave_one_durable_admin(
    database: Database,
    settings: Settings,
    admin: AdminIdentity,
) -> None:
    with database.session() as session, session.begin():
        second = User(
            email_normalized="second-admin@example.test",
            display_name="Second Admin",
            password_hash=hash_password(TEST_PASSWORD, settings),
            status="active",
            activated_at=datetime.now(UTC),
        )
        session.add(second)
        session.flush()
        session.add(
            GlobalRoleGrant(
                user_id=second.id,
                granted_by=admin.user_id,
                reason="concurrency test",
                expires_at=None,
            )
        )
        second_id = second.id

    barrier = Barrier(2)

    def suspend(actor_id: uuid.UUID, target_id: uuid.UUID) -> str:
        try:
            with database.session() as session, session.begin():
                actor = session.get(User, actor_id)
                assert actor is not None
                barrier.wait(timeout=5)
                AuthService(settings).set_user_status(
                    session,
                    actor=Principal(actor, MagicMock()),
                    target_user_id=target_id,
                    status="suspended",
                    reason="concurrent rotation",
                    request_id=f"concurrent-{actor_id}",
                )
            return "suspended"
        except APIError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = (
            pool.submit(suspend, admin.user_id, second_id),
            pool.submit(suspend, second_id, admin.user_id),
        )
        results = {future.result(timeout=10) for future in futures}
    assert results == {"suspended", "final_superuser_protected"}
    with database.session() as session:
        remaining = session.scalar(
            text(
                "SELECT count(*) FROM review_platform.users u "
                "JOIN review_platform.global_role_grants g ON g.user_id=u.id "
                "WHERE u.status='active' AND g.revoked_at IS NULL AND g.expires_at IS NULL"
            )
        )
        assert remaining == 1


def _production_settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="production",
        database_url="postgresql+psycopg://u:p@127.0.0.1:5432/review_prod",
        migration_database_url="postgresql+psycopg://u2:p@127.0.0.1:5432/review_prod",
        source_render_storage_mode="disabled",
        cookie_secure=True,
        allowed_origins=("https://prod.example",),
        session_hmac_key="k" * 32,
        activation_hmac_key="a" * 32,
        rate_limit_hmac_key="r" * 32,
        audit_hmac_key="d" * 32,
    )


def test_bootstrap_allows_two_extra_global_admins_in_production_then_refuses(
    database: Database, admin: AdminIdentity
) -> None:
    """Production's built-in default permits three standing admins; a fourth is still refused."""

    prod_settings = _production_settings()
    with database.session() as session, session.begin():
        second_id = bootstrap_first_superuser(
            session,
            settings=prod_settings,
            email="second-admin@example.test",
            display_name="Second Admin",
            password=TEST_PASSWORD,
            tenant_key="prod-second",
            tenant_name="Prod Second",
        )
    assert second_id != admin.user_id

    with database.session() as session, session.begin():
        third_id = bootstrap_first_superuser(
            session,
            settings=prod_settings,
            email="third-admin@example.test",
            display_name="Third Admin",
            password=TEST_PASSWORD,
            tenant_key="prod-third",
            tenant_name="Prod Third",
        )
    assert third_id not in (admin.user_id, second_id)

    with pytest.raises(BootstrapRefusedError), database.session() as session, session.begin():
        bootstrap_first_superuser(
            session,
            settings=prod_settings,
            email="fourth-admin@example.test",
            display_name="Fourth Admin",
            password=TEST_PASSWORD,
            tenant_key="prod-fourth",
            tenant_name="Prod Fourth",
        )


def test_max_global_admins_resolves_from_setting_when_present(
    admin: AdminIdentity,  # noqa: ARG001 - fixture ensures a DB-backed settings baseline
) -> None:
    """An explicit ``REVIEW_MAX_GLOBAL_ADMINS`` overrides the per-environment default."""

    overridden = Settings(
        _env_file=None,  # type: ignore[call-arg]
        environment="production",
        database_url="postgresql+psycopg://u:p@127.0.0.1:5432/review_prod",
        cookie_secure=True,
        allowed_origins=("https://prod.example",),
        session_hmac_key="k" * 32,
        activation_hmac_key="a" * 32,
        rate_limit_hmac_key="r" * 32,
        audit_hmac_key="d" * 32,
        max_global_admins=5,
    )
    assert bootstrap_module.max_global_admins(overridden) == 5


def test_max_global_admins_defaults_to_three_in_production_when_unset() -> None:
    """Without an override, production's built-in default is 3 (was 2)."""

    assert bootstrap_module.max_global_admins(_production_settings()) == 3


def test_max_global_admins_defaults_to_one_outside_production_when_unset(
    settings: Settings,
) -> None:
    assert bootstrap_module.max_global_admins(settings) == 1


def test_bootstrap_cli_paths(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    settings: Settings,
) -> None:
    answers = iter(["cli@example.test", "CLI Admin", "cli", "CLI Tenant"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    passwords = iter([TEST_PASSWORD, TEST_PASSWORD])
    monkeypatch.setattr(bootstrap_module.getpass, "getpass", lambda _prompt: next(passwords))
    monkeypatch.setattr(bootstrap_module, "Settings", lambda: settings)
    bootstrap_module.main()
    assert "Created first super administrator" in capsys.readouterr().out


def test_bootstrap_cli_rejects_missing_database_and_password_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_database = Settings(database_url=None)
    monkeypatch.setattr(bootstrap_module, "Settings", lambda: no_database)
    with pytest.raises(DatabaseUnavailableError):
        bootstrap_module.main()

    configured = Settings(database_url="postgresql+psycopg://unused")
    monkeypatch.setattr(bootstrap_module, "Settings", lambda: configured)
    answers = iter(["cli@example.test", "CLI Admin", "cli", "CLI Tenant"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    passwords = iter(["first password", "different password"])
    monkeypatch.setattr(bootstrap_module.getpass, "getpass", lambda _prompt: next(passwords))
    with pytest.raises(BootstrapRefusedError):
        bootstrap_module.main()
