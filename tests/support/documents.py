"""Temporary generic documents for workflow scenarios."""

import hashlib
from pathlib import Path


class FileDocuments:
    def __init__(self, roots: list[Path]) -> None:
        self.roots = roots
        self.paths = {
            hashlib.sha256(p.read_bytes()).hexdigest(): p
            for root in roots
            for p in root.rglob("*.html")
        }

    def resolve(self, sha256: str) -> Path | None:
        return self.paths.get(sha256)

    def read_html(self, sha256: str) -> str | None:
        path = self.resolve(sha256)
        if path is None or not path.is_file():
            return None
        data = path.read_bytes()
        return data.decode() if hashlib.sha256(data).hexdigest() == sha256 else None
