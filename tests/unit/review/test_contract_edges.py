from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from review_platform.common.errors import APIError
from review_platform.dataset.contract import EvidenceInput, SnapshotEnvelope
from review_platform.dataset.fixture_reader import FixtureDatasetReader
from review_platform.review.schemas import AnnotationInput
from review_platform.review.state_machine import validate_annotation
from review_platform.settings import Settings

FIXTURE_ROOT = Path("fixtures/dataset_contracts")


def _envelope() -> dict[str, Any]:
    return json.loads((FIXTURE_ROOT / "v0001/review_items.json").read_text())


def _expect_api_error(code: str, function: Any) -> None:
    with pytest.raises(APIError) as caught:
        function()
    assert caught.value.code == code


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value["items"][0]["source_document"].update(
                source_url="https://example.com/source"
            ),
            "reserved .invalid host",
        ),
        (
            lambda value: value["items"][0]["evidence"][0].update(line_start=10, line_end=9),
            "line offsets must be ordered",
        ),
        (
            lambda value: value["items"][0]["evidence"][0].update(char_start=10, char_end=9),
            "character offsets must be ordered",
        ),
        (
            lambda value: value["items"][0]["validator_candidates"][0].update(display_label="B"),
            "candidate labels must be exactly A and B",
        ),
        (
            lambda value: value["items"][0]["evidence"].append(
                dict(value["items"][0]["evidence"][0])
            ),
            "evidence ordinals must be unique",
        ),
        (
            lambda value: value["items"][0]["evidence"][0].update(kind="future_kind"),
            "Input should be",
        ),
    ],
)
def test_snapshot_contract_rejects_unsafe_or_ambiguous_values(mutation: Any, message: str) -> None:
    value = _envelope()
    mutation(value)
    with pytest.raises(ValidationError, match=message):
        SnapshotEnvelope.model_validate(value)


def test_evidence_accepts_absent_offsets() -> None:
    evidence = _envelope()["items"][0]["evidence"][0]
    evidence.update(line_start=None, line_end=None, char_start=None, char_end=None)
    assert EvidenceInput.model_validate(evidence).line_start is None


def _copy_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "fixtures"
    shutil.copytree(FIXTURE_ROOT / "v0001", root / "v0001")
    return root


def _rewrite(path: Path, update: Any) -> None:
    value = json.loads(path.read_text())
    update(value)
    path.write_text(json.dumps(value))


def test_fake_adapter_rejects_unsupported_and_unavailable_fixtures(tmp_path: Path) -> None:
    adapter = FixtureDatasetReader(tmp_path)
    _expect_api_error("fixture_version_unsupported", lambda: adapter.load("v9999"))

    missing = tmp_path / "v0001"
    missing.mkdir()
    _expect_api_error("synthetic_fixture_unavailable", lambda: adapter.load("v0001"))
    (missing / "manifest.json").write_text("{")
    (missing / "review_items.json").write_text("{}")
    _expect_api_error("synthetic_fixture_unavailable", lambda: adapter.load("v0001"))


def test_fake_adapter_rejects_forbidden_invalid_and_mismatched_contracts(
    tmp_path: Path,
) -> None:
    forbidden_manifest_root = _copy_fixture(tmp_path / "forbidden-manifest")
    _rewrite(
        forbidden_manifest_root / "v0001/manifest.json",
        lambda value: value.update(source_path="/private/source"),
    )
    _expect_api_error(
        "synthetic_fixture_forbidden_field",
        lambda: FixtureDatasetReader(forbidden_manifest_root).load("v0001"),
    )

    invalid_manifest_root = _copy_fixture(tmp_path / "invalid-manifest")
    _rewrite(
        invalid_manifest_root / "v0001/manifest.json",
        lambda value: value.update(source_mode="dataset"),
    )
    _expect_api_error(
        "synthetic_fixture_invalid",
        lambda: FixtureDatasetReader(invalid_manifest_root).load("v0001"),
    )

    forbidden_root = _copy_fixture(tmp_path / "forbidden")
    _rewrite(
        forbidden_root / "v0001/review_items.json",
        lambda value: value["items"][0]["evidence"].append(
            {"nested": [{"source_path": "/private/source"}]}
        ),
    )
    _expect_api_error(
        "synthetic_fixture_forbidden_field",
        lambda: FixtureDatasetReader(forbidden_root).load("v0001"),
    )

    invalid_root = _copy_fixture(tmp_path / "invalid")
    _rewrite(
        invalid_root / "v0001/review_items.json",
        lambda value: value.update(contract_version=3),
    )
    _expect_api_error(
        "synthetic_fixture_invalid", lambda: FixtureDatasetReader(invalid_root).load("v0001")
    )

    mismatch_root = _copy_fixture(tmp_path / "mismatch")
    _rewrite(
        mismatch_root / "v0001/manifest.json",
        lambda value: value.update(contains_real_data=True),
    )
    _expect_api_error(
        "synthetic_fixture_contract_mismatch",
        lambda: FixtureDatasetReader(mismatch_root).load("v0001"),
    )

    incomplete_root = _copy_fixture(tmp_path / "incomplete")
    _rewrite(
        incomplete_root / "v0001/manifest.json",
        lambda value: value["files"].pop(),
    )
    _expect_api_error(
        "synthetic_fixture_contract_mismatch",
        lambda: FixtureDatasetReader(incomplete_root).load("v0001"),
    )

    missing_declared_root = _copy_fixture(tmp_path / "missing-declared")
    (missing_declared_root / "v0001/agreement_metrics.json").unlink()
    _expect_api_error(
        "synthetic_fixture_unavailable",
        lambda: FixtureDatasetReader(missing_declared_root).load("v0001"),
    )


def test_fake_adapter_digest_binds_every_declared_fixture_file(tmp_path: Path) -> None:
    baseline_root = _copy_fixture(tmp_path / "baseline")
    changed_root = _copy_fixture(tmp_path / "changed")
    baseline = FixtureDatasetReader(baseline_root).load("v0001")
    _rewrite(
        changed_root / "v0001/agreement_metrics.json",
        lambda value: value.update(contract_review_marker="changed"),
    )
    changed = FixtureDatasetReader(changed_root).load("v0001")
    assert changed.manifest_digest != baseline.manifest_digest

    forbidden_root = _copy_fixture(tmp_path / "declared-forbidden")
    _rewrite(
        forbidden_root / "v0001/expected_scenarios.json",
        lambda value: value.update(source_path="/private/source"),
    )
    _expect_api_error(
        "synthetic_fixture_forbidden_field",
        lambda: FixtureDatasetReader(forbidden_root).load("v0001"),
    )


def _annotation(
    candidate_ids: list[uuid.UUID],
    *,
    outcome: str = "candidate_a_preferred",
    assessments: list[dict[str, object]] | None = None,
    evidence_ids: list[uuid.UUID] | None = None,
) -> AnnotationInput:
    return AnnotationInput.model_validate(
        {
            "outcome": outcome,
            "assessments": assessments
            or [
                {"candidate_id": candidate_ids[0], "assessment": "correct"},
                {"candidate_id": candidate_ids[1], "assessment": "incorrect"},
            ],
            "evidence_ids": evidence_ids or [],
            "comment": "Required context" if outcome == "both_wrong" else None,
        }
    )


def test_annotation_validation_rejects_membership_and_consistency_errors() -> None:
    candidate_ids = [uuid.uuid4(), uuid.uuid4()]
    candidates = dict(zip(candidate_ids, ["A", "B"], strict=True))
    evidence_id = uuid.uuid4()

    duplicate = [
        {"candidate_id": candidate_ids[0], "assessment": "correct"},
        {"candidate_id": candidate_ids[0], "assessment": "incorrect"},
    ]
    _expect_api_error(
        "candidate_assessments_invalid",
        lambda: validate_annotation(
            _annotation(candidate_ids, assessments=duplicate),
            candidates_by_id=candidates,
            allowed_evidence_ids={evidence_id},
        ),
    )

    foreign_candidate = uuid.uuid4()
    wrong_set = [
        {"candidate_id": candidate_ids[0], "assessment": "correct"},
        {"candidate_id": foreign_candidate, "assessment": "incorrect"},
    ]
    _expect_api_error(
        "candidate_assessments_invalid",
        lambda: validate_annotation(
            _annotation(candidate_ids, assessments=wrong_set),
            candidates_by_id=candidates,
            allowed_evidence_ids={evidence_id},
        ),
    )

    _expect_api_error(
        "evidence_references_invalid",
        lambda: validate_annotation(
            _annotation(candidate_ids, evidence_ids=[evidence_id, evidence_id]),
            candidates_by_id=candidates,
            allowed_evidence_ids={evidence_id},
        ),
    )
    _expect_api_error(
        "evidence_references_invalid",
        lambda: validate_annotation(
            _annotation(candidate_ids, evidence_ids=[uuid.uuid4()]),
            candidates_by_id=candidates,
            allowed_evidence_ids={evidence_id},
        ),
    )

    inconsistent = [
        {"candidate_id": candidate_ids[0], "assessment": "incorrect"},
        {"candidate_id": candidate_ids[1], "assessment": "correct"},
    ]
    _expect_api_error(
        "candidate_assessments_inconsistent",
        lambda: validate_annotation(
            _annotation(candidate_ids, assessments=inconsistent),
            candidates_by_id=candidates,
            allowed_evidence_ids={evidence_id},
        ),
    )


def test_production_settings_forbid_synthetic_imports() -> None:
    with pytest.raises(ValidationError, match="synthetic imports are forbidden"):
        Settings(environment="production", synthetic_import_enabled=True)


pytestmark = pytest.mark.no_db
