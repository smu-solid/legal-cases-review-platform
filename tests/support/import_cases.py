"""Shared scenario builders for retained workflow tests."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from review_platform.dataset.types import (
    InputCandidate,
    InputCase,
    InputEvidence,
    InputField,
    InputRelation,
)
from review_platform.db.models import RoleGrant, TenantMembership, User
from review_platform.review.artifact_store import FilesystemArtifactStore
from review_platform.review.dataset_import import DatasetImportService
from tests.support.documents import FileDocuments
from tests.support.identities import AdminIdentity

_SAMPLE_A_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "documents"
    / "sample_a_synthetic.html"
)


_PRESENT_SNIPPET = "first judgment paragraph BODYONE"


_OMITTED_SNIPPET = "Held omitted headnote prose SECRETHEADNOTE"


def _candidate(kind: str, value: str) -> InputCandidate:
    return InputCandidate(
        source_kind=kind, verdict="supported", value=value, rationale="r", supporting_quote=None
    )


_DOCUMENT_SHA = {"value": "0" * 64}


def _evidence(snippet: str) -> InputEvidence:
    return InputEvidence(
        kind="quote",
        snippet=snippet,
        char_start=10,
        char_end=20,
        line_start=None,
        line_end=None,
        source_hash=_DOCUMENT_SHA["value"],
    )


def _real_case(sha256: str) -> InputCase:
    return InputCase(
        external_id="CAS-TEST-1",
        source_system="sample_a",
        source_document_id="SRC-TEST-1",
        sha256=sha256,
        title="AA v BB",
        fields=[
            InputField(
                field_name="cases.citation_neutral",
                display_value="[2018] SGHCF 99",
                value_candidate=_candidate("deterministic", "[2018] SGHCF 99"),
                model_candidate=_candidate("model", "[2018] SGHCF 99"),
                evidence=[_evidence(_PRESENT_SNIPPET), _evidence(_OMITTED_SNIPPET)],
            )
        ],
    )


def _cited_case_relation() -> InputRelation:
    return InputRelation(
        review_kind="cited_case",
        family="rel_citations",
        relation_external_id="REL-CIT-1",
        display_label="Cited case",
        display_value="[2011] SGCA 9",
        value={"to_case_id_int": 42, "to_case_ext": "[2011] SGCA 9"},
        evidence=[_evidence(_PRESENT_SNIPPET)],
    )


def _service(root: Path, store_root: Path) -> tuple[DatasetImportService, str]:
    root.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    raw = _SAMPLE_A_FIXTURE.read_bytes()
    (root / "case.html").write_bytes(raw)
    sha256 = hashlib.sha256(raw).hexdigest()
    _DOCUMENT_SHA["value"] = sha256
    service = DatasetImportService(
        resolver=FileDocuments([root]),
        store=FilesystemArtifactStore(root=store_root),
        audit_key="k" * 32,
    )
    return service, sha256


def _import(
    db_session: Session, admin: AdminIdentity, tmp_path: Path, *, key: str = "real-sample_a"
) -> object:
    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    return service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key=key,
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[_real_case(sha256)],
    )


class _CountingStore:
    """Countingstore."""

    def __init__(self, root: Path) -> None:
        self._inner = FilesystemArtifactStore(root=root)
        self.writes: list[str] = []

    def read_body(self, object_key: str) -> bytes:
        return self._inner.read_body(object_key)

    def read_anchor_map(self, object_key: str) -> bytes:
        return self._inner.read_anchor_map(object_key)

    def write_artifact(self, object_key: str, *, body: bytes, anchor_map: bytes) -> None:
        self.writes.append(object_key)
        self._inner.write_artifact(object_key, body=body, anchor_map=anchor_map)


def _reviewer(db_session: Session, admin: AdminIdentity, *, suffix: str) -> uuid.UUID:
    """Provision a bare active reviewer in ``admin``'s tenant (no password/session needed)."""

    user = User(
        email_normalized=f"multi-reviewer-{suffix}@example.test",
        display_name=f"Multi Reviewer {suffix}",
        status="active",
        authorization_epoch=1,
    )
    db_session.add(user)
    db_session.flush()
    membership = TenantMembership(tenant_id=admin.tenant_id, user_id=user.id, status="active")
    db_session.add(membership)
    db_session.flush()
    db_session.add(
        RoleGrant(membership_id=membership.id, role_code="reviewer", granted_by=admin.user_id)
    )
    db_session.flush()
    return user.id


_SAMPLE_B_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "documents"
    / "sample_b_synthetic.html"
)


def _sample_b_case(sha256: str) -> InputCase:
    # No evidence: this test asserts the shared-campaign wiring, not provenance anchoring (covered
    # above), so it stays independent of the Sample B fixture's body text.
    return InputCase(
        external_id="CAS-ELIT-1",
        source_system="sample_b",
        source_document_id="SRC-ELIT-1",
        sha256=sha256,
        title="CC v DD",
        fields=[
            InputField(
                field_name="cases.citation_neutral",
                display_value="[2020] SGHC 1",
                value_candidate=_candidate("deterministic", "[2020] SGHC 1"),
                model_candidate=None,
                evidence=[],
            )
        ],
    )


def _import_source(
    db_session: Session,
    admin: AdminIdentity,
    tmp_path: Path,
    *,
    fixture: Path,
    source_system: str,
    build_case: object,
    key: str,
) -> object:
    """Import one source's single case into ``key``, resolving its fixture by content hash."""

    raw_root = tmp_path / f"raw-{source_system}"
    store_root = tmp_path / "store"
    raw_root.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    raw = fixture.read_bytes()
    (raw_root / "case.html").write_bytes(raw)
    sha256 = hashlib.sha256(raw).hexdigest()
    service = DatasetImportService(
        resolver=FileDocuments([raw_root]),
        store=FilesystemArtifactStore(root=store_root),
        audit_key="k" * 32,
    )
    return service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key=key,
        campaign_name="Local Pilot",
        source_system=source_system,
        cases=[build_case(sha256)],  # type: ignore[operator]
    )


class _CountingResolver(FileDocuments):
    """Counts raw-source reads, which is the cost this optimisation exists to avoid."""

    def __init__(self, roots: list[Path]) -> None:
        super().__init__(roots)
        self.reads = 0

    def read_html(self, sha256: str) -> str | None:
        self.reads += 1
        return super().read_html(sha256)


def _counting_service(
    root: Path, store_root: Path
) -> tuple[DatasetImportService, str, _CountingResolver]:
    root.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    raw = _SAMPLE_A_FIXTURE.read_bytes()
    (root / "case.html").write_bytes(raw)
    resolver = _CountingResolver([root])
    service = DatasetImportService(
        resolver=resolver,
        store=FilesystemArtifactStore(root=store_root),
        audit_key="k" * 32,
    )
    return service, hashlib.sha256(raw).hexdigest(), resolver


def _run(
    service: DatasetImportService,
    db_session: Session,
    admin: AdminIdentity,
    case: object,
    *,
    key: str,
    refresh_existing: bool = False,
) -> object:
    return service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key=key,
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
        refresh_existing=refresh_existing,
        campaign_status="pool",
    )
