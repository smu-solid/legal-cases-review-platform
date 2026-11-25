import hashlib
import sqlite3
from pathlib import Path

import pytest

from review_platform.dataset.generate import generate
from review_platform.dataset.sqlite import SQLiteDataset
from review_platform.db.test_safety import validate_test_database

pytestmark = pytest.mark.no_db


def test_dataset_generation_is_reproducible_readonly_and_complete(tmp_path: Path):
    a = tmp_path / "a.sqlite"
    b = tmp_path / "b.sqlite"
    generate(a, count=4)
    generate(b, count=4)
    assert a.read_bytes() == b.read_bytes()
    before = hashlib.sha256(a.read_bytes()).hexdigest()
    reader = SQLiteDataset(a)
    cases = list(reader.iter_cases())
    assert len(cases) == 4 and all(c.fields and c.relations for c in cases)
    for case in cases:
        assert reader.read_html(case.sha256)
    with reader.connection() as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("DELETE FROM cases")
    assert hashlib.sha256(a.read_bytes()).hexdigest() == before
    with pytest.raises(FileExistsError):
        generate(a)


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE documents SET html='changed'",
        "UPDATE cases SET collection='changed'",
        "PRAGMA user_version=2",
    ],
)
def test_dataset_integrity_and_version_errors_fail_closed(tmp_path: Path, change: str):
    path = tmp_path / "demo.sqlite"
    generate(path, count=2)
    with sqlite3.connect(path) as connection:
        connection.execute(change)
    with pytest.raises(ValueError):
        list(SQLiteDataset(path).iter_cases())


def test_destructive_test_guard_requires_isolated_identity():
    good = "postgresql+psycopg://user:pass@127.0.0.1:57433/review_oss_test"
    validate_test_database(good, expected_url=good)
    for url in [
        "postgresql+psycopg://user:pass@127.0.0.1:55432/review_oss_test",
        "postgresql+psycopg://user:pass@127.0.0.1:57433/review_oss",
        "postgresql+psycopg://user:pass@other:57433/review_oss_test",
    ]:
        with pytest.raises(ValueError):
            validate_test_database(url, expected_url=url)
    with pytest.raises(ValueError):
        validate_test_database(good, expected_url=None)
