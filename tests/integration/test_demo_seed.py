from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import func, select

from review_platform.dataset.generate import generate
from review_platform.db.models import TenantMembership, User
from review_platform.db.session import Database
from review_platform.dev_seed import seed
from review_platform.review.models import Campaign, ReviewUnit
from review_platform.security import verify_password
from review_platform.settings import Settings


def test_demo_seed_is_repeatable_and_preserves_passwords_and_dataset(
    settings: Settings, database: Database, tmp_path: Path
) -> None:
    dataset = tmp_path / "input.sqlite"
    generate(dataset, count=4)
    before = hashlib.sha256(dataset.read_bytes()).digest()
    config = settings.model_copy(
        update={
            "dataset_path": dataset,
            "source_render_artifact_root": tmp_path / "artifacts",
            "source_render_storage_mode": "filesystem",
        }
    )
    first = seed(config, password="First-demo-password")
    with database.session() as session:
        units = session.scalar(select(func.count()).select_from(ReviewUnit))
        assert units and units > 4
        hashes = dict(session.execute(select(User.email_normalized, User.password_hash)).all())
        assert len(hashes) == 4
    assert seed(config, password="Different-demo-password") == first
    with database.session() as session:
        assert session.scalar(select(func.count()).select_from(ReviewUnit)) == units
        assert session.scalar(select(func.count()).select_from(Campaign)) == 1
        assert session.scalar(select(func.count()).select_from(TenantMembership)) == 4
        for user in session.scalars(select(User)):
            assert user.password_hash == hashes[user.email_normalized]
            assert verify_password(user.password_hash, "First-demo-password")
    assert hashlib.sha256(dataset.read_bytes()).digest() == before
    assert list((tmp_path / "artifacts").rglob("body.html"))


@pytest.mark.no_db
def test_demo_seed_refuses_production_before_connecting() -> None:
    settings = Settings(_env_file=None).model_copy(update={"environment": "production"})
    with pytest.raises(ValueError, match="disabled in production"):
        seed(settings, password="Unused-demo-password")
