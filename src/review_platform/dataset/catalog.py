"""Read-only SQLite dataset metadata used by campaign selection."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class DatasetCatalog:
    def __init__(self, path: Path | str | None) -> None:
        self.path = Path(path) if path else None

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        if self.path is None or not self.path.is_file():
            from review_platform.common.errors import APIError

            raise APIError(
                503,
                "dataset_unavailable",
                "Dataset unavailable",
                "The case dataset is not available.",
            )
        connection = sqlite3.connect(self.path.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        try:
            yield connection
        finally:
            connection.close()

    def cases(self) -> list[dict[str, str]]:
        with self.connection() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version != 1:
                raise ValueError("unsupported dataset schema version")
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT collection AS source_system, external_id, document_sha256 AS sha256, "
                    "subject, judgment_date FROM cases ORDER BY collection, external_id"
                )
            ]
