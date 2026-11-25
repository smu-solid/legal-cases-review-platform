"""Shared scenario builders for retained workflow tests."""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.auth.principal import Principal
from review_platform.dataset.types import InputCandidate, InputCase, InputEvidence, InputField
from review_platform.db.models import RoleGrant, TenantMembership, User
from review_platform.review.artifact_store import FilesystemArtifactStore
from review_platform.review.case_pool import (
    POOL_CAMPAIGN_KEY,
    POOL_CAMPAIGN_NAME,
)
from review_platform.review.dataset_import import DatasetImportService
from review_platform.review.models import (
    Campaign,
    ReviewUnit,
)
from review_platform.review.service import ReviewService
from tests.support.documents import FileDocuments
from tests.support.identities import AdminIdentity

_SAMPLE_A_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "documents"
    / "sample_a_synthetic.html"
)


_SAMPLE_B_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "documents"
    / "sample_b_synthetic.html"
)


def _candidate(value: str) -> InputCandidate:
    return InputCandidate(
        source_kind="deterministic",
        verdict="supported",
        value=value,
        rationale="r",
        supporting_quote=None,
    )


def _case(
    external_id: str,
    sha256: str,
    *,
    source_system: str = "sample_a",
    groups: int = 2,
    with_evidence: bool = False,
) -> InputCase:
    """A case with 1 or 2 atomic fields landing in the case_metadata / court_and_hearing groups."""

    fields = [
        InputField(
            field_name="cases.citation_neutral",
            display_value="[2018] SGHCF 99",
            value_candidate=_candidate("[2018] SGHCF 99"),
            model_candidate=None,
            evidence=(
                [
                    InputEvidence(
                        kind="source_text",
                        snippet="[2018] SGHCF 99",
                        char_start=0,
                        char_end=16,
                        line_start=1,
                        line_end=1,
                        source_hash=sha256,
                    )
                ]
                if with_evidence
                else []
            ),
        )
    ]
    if groups >= 2:
        fields.append(
            InputField(
                field_name="cases.coram",
                display_value="Sundaresh Menon CJ",
                value_candidate=_candidate("Sundaresh Menon CJ"),
                model_candidate=None,
                evidence=[],
            )
        )
    return InputCase(
        external_id=external_id,
        source_system=source_system,
        source_document_id=f"SRC-{external_id}",
        sha256=sha256,
        title="AA v BB",
        fields=fields,
    )


def _seed_pool(
    db_session: Session,
    admin: AdminIdentity,
    tmp_path: Path,
    cases: list[InputCase],
) -> int:
    """Preload ``cases`` directly into the tenant's pool campaign.

    Returns total ``imported_units`` across every source in ``cases`` (0 for any case/field
    whose     ``SourceSnapshot`` already exists -- see
    ``DatasetImportService._persist_unit``). Both fixtures are     always written (by
    content hash, so a sample_a + sample_b case can be seeded in one call     without one
    source's file overwriting the other's)."""

    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True, exist_ok=True)
    (raw_root / "sample_a_case.html").write_bytes(_SAMPLE_A_FIXTURE.read_bytes())
    (raw_root / "sample_b_case.html").write_bytes(_SAMPLE_B_FIXTURE.read_bytes())
    store_root = tmp_path / "store"
    store_root.mkdir(parents=True, exist_ok=True)
    service = DatasetImportService(
        resolver=FileDocuments([raw_root]),
        store=FilesystemArtifactStore(root=store_root),
        audit_key="k" * 32,
    )
    by_source: dict[str, list[InputCase]] = {}
    for case in cases:
        by_source.setdefault(case.source_system, []).append(case)
    imported_units = 0
    for source_system, source_cases in by_source.items():
        result = service.import_cases(
            db_session,
            tenant_id=admin.tenant_id,
            created_by=admin.user_id,
            campaign_key=POOL_CAMPAIGN_KEY,
            campaign_name=POOL_CAMPAIGN_NAME,
            source_system=source_system,
            cases=source_cases,
            campaign_status="pool",
        )
        imported_units += result.imported_units
    return imported_units


def _service(tmp_path: Path) -> ReviewService:
    from review_platform.dataset.fixture_reader import FixtureDatasetReader

    return ReviewService(FixtureDatasetReader(tmp_path), "k" * 32, synthetic_enabled=False)


def _principal(db_session: Session, admin: AdminIdentity) -> Principal:
    user = db_session.get(User, admin.user_id)
    assert user is not None
    return Principal(user=user)


def _ensure_admin_is_reviewer(db_session: Session, admin: AdminIdentity) -> None:
    membership_id = db_session.scalar(
        select(TenantMembership.id).where(
            TenantMembership.tenant_id == admin.tenant_id,
            TenantMembership.user_id == admin.user_id,
        )
    )
    assert membership_id is not None
    existing = db_session.scalar(
        select(RoleGrant.id).where(
            RoleGrant.membership_id == membership_id,
            RoleGrant.role_code == "reviewer",
            RoleGrant.revoked_at.is_(None),
        )
    )
    if existing is None:
        db_session.add(
            RoleGrant(
                membership_id=membership_id,
                role_code="reviewer",
                granted_by=admin.user_id,
            )
        )
        db_session.flush()


def _sha(fixture: Path = _SAMPLE_A_FIXTURE) -> str:
    return hashlib.sha256(fixture.read_bytes()).hexdigest()


def _pool_unit_count(db_session: Session, admin: AdminIdentity) -> int:
    return (
        db_session.scalar(
            select(func.count())
            .select_from(ReviewUnit)
            .join(Campaign, Campaign.id == ReviewUnit.campaign_id)
            .where(Campaign.tenant_id == admin.tenant_id, Campaign.key == POOL_CAMPAIGN_KEY)
        )
        or 0
    )
