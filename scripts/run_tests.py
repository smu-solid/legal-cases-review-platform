"""Run tests only against the explicitly isolated disposable database."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from review_platform.db.test_safety import validate_test_database


def main() -> None:
    url = os.environ.get(
        "REVIEW_TEST_DATABASE_URL",
        "postgresql+psycopg://review_oss_test:disposable-test-password@127.0.0.1:57433/review_oss_test",
    )
    validate_test_database(url, expected_url=url)
    env = {
        **os.environ,
        "REVIEW_DATABASE_URL": url,
        "REVIEW_MIGRATION_DATABASE_URL": url,
        "REVIEW_TEST_DATABASE_URL": url,
        "REVIEW_ENVIRONMENT": "test",
    }
    raise SystemExit(subprocess.call([sys.executable, "-m", "pytest", *sys.argv[1:]], env=env))


if __name__ == "__main__":
    main()
