"""Explicit synthetic adapter over versioned local contract fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from review_platform.common.errors import APIError
from review_platform.common.json import digest_json
from review_platform.dataset.contract import (
    CONTRACT_VERSION,
    SnapshotBatch,
    SnapshotEnvelope,
    SnapshotManifest,
)

SUPPORTED_FIXTURES = frozenset({"v0001"})
DECLARED_JSON_FILES = frozenset(
    {"review_items.json", "expected_scenarios.json", "agreement_metrics.json"}
)


def _contains_forbidden_key(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"source_path", "filesystem_path"} or _contains_forbidden_key(child)
            for key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(child) for child in value)
    return False


class FixtureDatasetReader:
    """Fixturedatasetreader."""

    def __init__(self, fixture_root: Path) -> None:
        self.fixture_root = fixture_root

    def load(self, fixture_version: str) -> SnapshotBatch:
        if fixture_version not in SUPPORTED_FIXTURES:
            raise APIError(
                422,
                "fixture_version_unsupported",
                "Unsupported fixture version",
                "The synthetic fixture version is not supported.",
            )
        version_root = self.fixture_root / fixture_version
        try:
            manifest_raw = json.loads((version_root / "manifest.json").read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise APIError(
                503,
                "synthetic_fixture_unavailable",
                "Synthetic fixture unavailable",
                "The approved synthetic contract could not be loaded.",
            ) from exc
        if _contains_forbidden_key(manifest_raw):
            raise APIError(
                422,
                "synthetic_fixture_forbidden_field",
                "Invalid synthetic fixture",
                "The synthetic contract contains a forbidden field.",
            )
        try:
            manifest = SnapshotManifest.model_validate(manifest_raw)
        except ValidationError as exc:
            raise APIError(
                422,
                "synthetic_fixture_invalid",
                "Invalid synthetic fixture",
                "The synthetic contract failed validation.",
            ) from exc
        declared_paths = [item.path for item in manifest.files]
        if len(declared_paths) != len(set(declared_paths)) or set(declared_paths) != set(
            DECLARED_JSON_FILES
        ):
            raise APIError(
                422,
                "synthetic_fixture_contract_mismatch",
                "Invalid synthetic fixture",
                "The synthetic manifest must declare the complete approved fixture set.",
            )
        try:
            declared_files = {
                path: json.loads((version_root / path).read_text())
                for path in sorted(DECLARED_JSON_FILES)
            }
            envelope_raw = declared_files["review_items.json"]
        except (OSError, json.JSONDecodeError) as exc:
            raise APIError(
                503,
                "synthetic_fixture_unavailable",
                "Synthetic fixture unavailable",
                "The complete approved synthetic contract could not be loaded.",
            ) from exc
        if _contains_forbidden_key(declared_files):
            raise APIError(
                422,
                "synthetic_fixture_forbidden_field",
                "Invalid synthetic fixture",
                "The synthetic contract contains a forbidden field.",
            )
        try:
            envelope = SnapshotEnvelope.model_validate(envelope_raw)
        except ValidationError as exc:
            raise APIError(
                422,
                "synthetic_fixture_invalid",
                "Invalid synthetic fixture",
                "The synthetic contract failed validation.",
            ) from exc
        if (
            manifest.contract_version != CONTRACT_VERSION
            or envelope.contract_version != CONTRACT_VERSION
            or manifest.fixture_set != envelope.fixture_set
            or manifest.tenant_key != envelope.tenant_key
            or manifest.source_mode != "synthetic"
            or manifest.contains_real_data
            or not manifest.security_assertions.url_hosts_are_reserved_invalid
            or manifest.security_assertions.contains_source_path
        ):
            raise APIError(
                422,
                "synthetic_fixture_contract_mismatch",
                "Invalid synthetic fixture",
                "The synthetic contract metadata is inconsistent.",
            )
        return SnapshotBatch(
            manifest=manifest,
            envelope=envelope,
            manifest_digest=digest_json({"manifest": manifest_raw, "files": declared_files}),
        )
