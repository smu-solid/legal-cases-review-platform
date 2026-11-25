"""Verified document access used by dataset import."""

from typing import Protocol


class DocumentResolver(Protocol):
    def resolve(self, sha256: str) -> object | None: ...
    def read_html(self, sha256: str) -> str | None: ...
