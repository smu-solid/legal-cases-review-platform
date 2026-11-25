"""Run the browser-test API against the dedicated disposable database."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from review_platform.db.test_safety import validate_test_database


def main() -> None:
    url = os.environ.get(
        "REVIEW_TEST_DATABASE_URL",
        "postgresql+psycopg://review_oss_test:disposable-test-password@127.0.0.1:57433/review_oss_test",
    )
    validate_test_database(url, expected_url=url)
    with tempfile.TemporaryDirectory(prefix="review-e2e-") as directory:
        os.environ.update(
            REVIEW_ENVIRONMENT="test",
            REVIEW_DATABASE_URL=url,
            REVIEW_MIGRATION_DATABASE_URL=url,
            REVIEW_TEST_DATABASE_URL=url,
            REVIEW_ALLOWED_ORIGINS='["http://localhost:5273"]',
            REVIEW_ALLOWED_HOSTS='["localhost","127.0.0.1"]',
            REVIEW_APP_BASE_URL="http://localhost:5273",
            REVIEW_DATASET_PATH="fixtures/demo.sqlite",
            REVIEW_SOURCE_RENDER_STORAGE_MODE="filesystem",
            REVIEW_SOURCE_RENDER_ARTIFACT_ROOT=directory,
            REVIEW_EMAIL_MODE="console",
            REVIEW_SESSION_HMAC_KEY="browser-session-key-00000000000000000000",
            REVIEW_ACTIVATION_HMAC_KEY="browser-activation-key-00000000000000000",
            REVIEW_RATE_LIMIT_HMAC_KEY="browser-rate-limit-key-00000000000000000",
            REVIEW_AUDIT_HMAC_KEY="browser-audit-key-0000000000000000000000",
        )
        import uvicorn
        from alembic import command
        from alembic.config import Config
        from sqlalchemy import create_engine, text

        from review_platform.dev_seed import seed
        from review_platform.settings import Settings

        engine = create_engine(url)
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA IF EXISTS review_platform CASCADE"))
        engine.dispose()
        command.upgrade(Config("alembic.ini"), "head")
        seed(Settings(_env_file=None), password="Browser-demo-password-2026")
        uvicorn.run("review_platform.main:create_app", factory=True, host="127.0.0.1", port=8780)


if __name__ == "__main__":
    main()
