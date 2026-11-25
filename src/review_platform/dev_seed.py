"""Create demo users and import fictional SQLite cases into the eligible pool."""

from __future__ import annotations

import argparse
import os
from typing import cast

from pydantic import SecretStr
from sqlalchemy import select

from review_platform.bootstrap import bootstrap_first_superuser
from review_platform.dataset.sqlite import SQLiteDataset
from review_platform.db.models import RoleGrant, Tenant, TenantMembership, User
from review_platform.db.session import Database
from review_platform.review.artifact_store import FilesystemArtifactStore
from review_platform.review.case_pool import POOL_CAMPAIGN_KEY, POOL_CAMPAIGN_NAME
from review_platform.review.dataset_import import DatasetImportService
from review_platform.security import hash_password
from review_platform.settings import Settings


def seed(settings: Settings, *, password: str) -> dict[str, str]:
    if settings.environment == "production":
        raise ValueError("demo account creation is disabled in production")
    if not settings.database_url or not settings.source_render_artifact_root:
        raise ValueError("database and artifact root are required")
    database = Database(settings.database_url)
    try:
        with database.session() as session, session.begin():
            admin = session.scalar(
                select(User).where(User.email_normalized == "admin@example.test")
            )
            if admin is None:
                admin_id = bootstrap_first_superuser(
                    session,
                    settings=settings,
                    email="admin@example.test",
                    display_name="Demo Administrator",
                    password=password,
                    tenant_key=settings.default_tenant_key,
                    tenant_name=settings.default_tenant_name,
                )
                admin = session.get(User, admin_id)
            if admin is None:
                raise ValueError("demo administrator is missing")
            tenant = session.scalar(select(Tenant).where(Tenant.key == settings.default_tenant_key))
            if tenant is None:
                raise ValueError("demo tenant is missing")
            for email, name, role in [
                ("reviewer1@example.test", "Reviewer One", "reviewer"),
                ("reviewer2@example.test", "Reviewer Two", "reviewer"),
                ("adjudicator@example.test", "Demo Adjudicator", "adjudicator"),
            ]:
                user = session.scalar(select(User).where(User.email_normalized == email))
                if user is None:
                    user = User(
                        email_normalized=email,
                        display_name=name,
                        status="active",
                        password_hash=hash_password(password, settings),
                    )
                    session.add(user)
                    session.flush()
                    membership = TenantMembership(
                        tenant_id=tenant.id, user_id=user.id, status="active"
                    )
                    session.add(membership)
                    session.flush()
                    session.add(
                        RoleGrant(membership_id=membership.id, role_code=role, granted_by=admin.id)
                    )
            reader = SQLiteDataset(settings.dataset_path)
            importer = DatasetImportService(
                resolver=reader,
                store=FilesystemArtifactStore(settings.source_render_artifact_root),
                audit_key=cast(SecretStr, settings.audit_hmac_key).get_secret_value(),
            )
            cases = list(reader.iter_cases())
            for collection in sorted({case.source_system for case in cases}):
                importer.import_cases(
                    session,
                    tenant_id=tenant.id,
                    created_by=admin.id,
                    campaign_key=POOL_CAMPAIGN_KEY,
                    campaign_name=POOL_CAMPAIGN_NAME,
                    source_system=collection,
                    cases=[case for case in cases if case.source_system == collection],
                    campaign_status="pool",
                )
            return {"tenant_id": str(tenant.id), "case_count": str(len(cases))}
    finally:
        database.dispose()


def main() -> None:
    argparse.ArgumentParser(description=__doc__).parse_args()
    password = os.environ.get("REVIEW_DEMO_PASSWORD")
    if not password:
        raise SystemExit("Set REVIEW_DEMO_PASSWORD to a password of at least 12 characters.")
    result = seed(Settings(), password=password)
    print(f"Demo ready: {result['case_count']} cases; tenant {result['tenant_id']}")


if __name__ == "__main__":
    main()
