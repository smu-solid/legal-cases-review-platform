"""Private filesystem storage for immutable document artifacts."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from review_platform.settings import Settings

BODY_FILENAME = "body.html"
ANCHOR_MAP_FILENAME = "anchor_map.json"
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
_KEY_PATTERN = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")


class ArtifactNotFoundError(RuntimeError):
    pass


class ArtifactTooLargeError(RuntimeError):
    pass


class ArtifactStore(Protocol):
    def read_body(self, object_key: str) -> bytes: ...
    def read_anchor_map(self, object_key: str) -> bytes: ...
    def write_artifact(self, object_key: str, *, body: bytes, anchor_map: bytes) -> None: ...


@dataclass(frozen=True)
class FilesystemArtifactStore:
    root: Path
    max_bytes: int = MAX_ARTIFACT_BYTES

    def _resolve(self, object_key: str, filename: str) -> Path:
        if not _KEY_PATTERN.fullmatch(object_key):
            raise ArtifactNotFoundError("invalid artifact key")
        base = self.root.resolve()
        target = (base / object_key / filename).resolve()
        if target.parent.parent != base:
            raise ArtifactNotFoundError("artifact path escapes store")
        return target

    def _read(self, object_key: str, filename: str) -> bytes:
        path = self._resolve(object_key, filename)
        try:
            with path.open("rb") as handle:
                data = handle.read(self.max_bytes + 1)
        except FileNotFoundError as exc:
            raise ArtifactNotFoundError("artifact is missing") from exc
        if len(data) > self.max_bytes:
            raise ArtifactTooLargeError("artifact exceeds size limit")
        return data

    def read_body(self, object_key: str) -> bytes:
        return self._read(object_key, BODY_FILENAME)

    def read_anchor_map(self, object_key: str) -> bytes:
        return self._read(object_key, ANCHOR_MAP_FILENAME)

    def write_artifact(self, object_key: str, *, body: bytes, anchor_map: bytes) -> None:
        for filename, data in ((BODY_FILENAME, body), (ANCHOR_MAP_FILENAME, anchor_map)):
            if len(data) > self.max_bytes:
                raise ArtifactTooLargeError("artifact exceeds size limit")
            path = self._resolve(object_key, filename)
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                if path.read_bytes() != data:
                    raise ValueError("artifact content collision")
                continue
            descriptor, tmp = tempfile.mkstemp(dir=path.parent, prefix=".artifact-")
            try:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.link(tmp, path)
            except FileExistsError as exc:
                if path.read_bytes() != data:
                    raise ValueError("artifact content collision") from exc
            finally:
                Path(tmp).unlink(missing_ok=True)


def build_artifact_store(settings: Settings) -> ArtifactStore | None:
    if settings.source_render_storage_mode == "disabled":
        return None
    if settings.source_render_artifact_root is None:
        raise ValueError("artifact root is required")
    return FilesystemArtifactStore(settings.source_render_artifact_root)


def read_verified_body(
    store: ArtifactStore | None, *, object_key: str, expected_digest: str
) -> bytes | None:
    if store is None:
        return None
    try:
        data = store.read_body(object_key)
    except (ArtifactNotFoundError, ArtifactTooLargeError):
        return None
    return data if hashlib.sha256(data).hexdigest() == expected_digest else None
