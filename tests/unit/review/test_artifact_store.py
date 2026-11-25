import hashlib
from pathlib import Path

import pytest

from review_platform.api.review.source_render_support import read_verified_artifact
from review_platform.common.errors import APIError
from review_platform.review.artifact_store import (
    ArtifactNotFoundError,
    ArtifactTooLargeError,
    FilesystemArtifactStore,
    build_artifact_store,
    read_verified_body,
)
from review_platform.settings import Settings

pytestmark = pytest.mark.no_db


def test_roundtrip_idempotency_and_collision(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path)
    store.write_artifact("key", body=b"body", anchor_map=b"{}")
    store.write_artifact("key", body=b"body", anchor_map=b"{}")
    assert store.read_body("key") == b"body" and store.read_anchor_map("key") == b"{}"
    with pytest.raises(ValueError, match="collision"):
        store.write_artifact("key", body=b"changed", anchor_map=b"{}")


@pytest.mark.parametrize("key", ["../escape", "/absolute", "a/b", "..", ""])
def test_invalid_keys_refused(tmp_path: Path, key: str) -> None:
    with pytest.raises(ArtifactNotFoundError):
        FilesystemArtifactStore(tmp_path).write_artifact(key, body=b"", anchor_map=b"")


def test_missing_oversized_and_digest_mismatch(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(tmp_path, max_bytes=5)
    with pytest.raises(ArtifactNotFoundError):
        store.read_body("missing")
    with pytest.raises(ArtifactTooLargeError):
        store.write_artifact("large", body=b"123456", anchor_map=b"{}")
    store.write_artifact("ok", body=b"123", anchor_map=b"{}")
    assert (
        read_verified_body(
            store, object_key="ok", expected_digest=hashlib.sha256(b"123").hexdigest()
        )
        == b"123"
    )
    assert read_verified_body(store, object_key="ok", expected_digest="0" * 64) is None


def test_factory_and_symlink_escape(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        source_render_storage_mode="filesystem",
        source_render_artifact_root=tmp_path,
    )
    assert isinstance(build_artifact_store(settings), FilesystemArtifactStore)
    assert build_artifact_store(Settings(_env_file=None)) is None
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ArtifactNotFoundError):
        FilesystemArtifactStore(tmp_path).read_body("escape")


def test_digest_is_verified_before_body_is_returned(tmp_path: Path) -> None:
    store = FilesystemArtifactStore(root=tmp_path)
    body = b"<p>verified</p>"
    store.write_artifact("artifact", body=body, anchor_map=b'{"anchors":[]}')
    assert (
        read_verified_artifact(
            store,
            object_key="artifact",
            kind="body",
            expected_digest=hashlib.sha256(body).hexdigest(),
        )
        == body
    )

    with pytest.raises(APIError) as exc_info:
        read_verified_artifact(
            store,
            object_key="artifact",
            kind="body",
            expected_digest="0" * 64,
        )
    assert exc_info.value.status == 500
    assert exc_info.value.code == "source_render_unavailable"
