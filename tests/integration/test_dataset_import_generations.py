from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.review.dataset_import import DatasetImportService
from review_platform.review.models import (
    ReviewUnit,
    SourceRenderArtifact,
)
from tests.support.documents import FileDocuments
from tests.support.identities import AdminIdentity
from tests.support.import_cases import (
    _SAMPLE_A_FIXTURE,
    _cited_case_relation,
    _counting_service,
    _CountingStore,
    _real_case,
    _run,
)


def test_shared_case_artifact_is_uploaded_once_per_run(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test shared case artifact is uploaded once per run."""

    raw_root = tmp_path / "raw"
    raw_root.mkdir(parents=True)
    raw = _SAMPLE_A_FIXTURE.read_bytes()
    (raw_root / "case.html").write_bytes(raw)
    sha256 = hashlib.sha256(raw).hexdigest()
    store = _CountingStore(root=tmp_path / "store")
    service = DatasetImportService(
        resolver=FileDocuments([raw_root]), store=store, audit_key="k" * 32
    )
    case = _real_case(sha256)
    case.relations.append(_cited_case_relation())  # two units, one rendered document

    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-artifact-dedupe",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    assert result.imported_units == 2  # type: ignore[attr-defined]
    assert len(store.writes) == 1
    assert db_session.scalar(select(func.count()).select_from(SourceRenderArtifact)) == 2
    # A fresh service (new run) re-imports nothing and therefore uploads nothing new either.
    rerun_store = _CountingStore(root=tmp_path / "store")
    rerun = DatasetImportService(
        resolver=FileDocuments([raw_root]), store=rerun_store, audit_key="k" * 32
    )
    again = rerun.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-artifact-dedupe",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    assert again.imported_units == 0  # type: ignore[attr-defined]
    assert rerun_store.writes == []


def test_unchanged_case_is_not_read_or_rendered_again(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test unchanged case is not read or rendered again."""

    service, sha256, resolver = _counting_service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)

    first = _run(service, db_session, admin, case, key="real-sample_a-skip")
    assert first.imported_units > 0  # type: ignore[attr-defined]
    assert resolver.reads == 1
    assert first.rendered_cases == 1  # type: ignore[attr-defined]
    assert first.skipped_unchanged_cases == 0  # type: ignore[attr-defined]

    again = _run(service, db_session, admin, case, key="real-sample_a-skip")
    assert again.imported_units == 0  # type: ignore[attr-defined]
    assert again.skipped_unchanged_cases == 1  # type: ignore[attr-defined]
    assert again.rendered_cases == 0  # type: ignore[attr-defined]
    assert again.source_render_seconds == 0.0  # type: ignore[attr-defined]
    # The whole point: no second read of the raw source.
    assert resolver.reads == 1


def test_refresh_of_a_changed_case_still_reads_and_rewrites(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Laziness must not turn into skipping real work: a changed digest still renders and
    writes."""

    service, sha256, resolver = _counting_service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    _run(service, db_session, admin, case, key="real-sample_a-changed")
    assert resolver.reads == 1

    changed = replace(case, fields=[replace(case.fields[0], display_value="CHANGED VALUE")])
    result = _run(
        service, db_session, admin, changed, key="real-sample_a-changed", refresh_existing=True
    )
    assert result.imported_units > 0  # type: ignore[attr-defined]
    assert result.rendered_cases == 1  # type: ignore[attr-defined]
    assert result.skipped_unchanged_cases == 0  # type: ignore[attr-defined]
    assert resolver.reads == 2


def test_source_lost_before_the_write_leaves_no_partial_unit(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """The source is forced before the first mutation, so losing it fails the case cleanly."""

    raw_root = tmp_path / "raw"
    service, sha256, resolver = _counting_service(raw_root, tmp_path / "store")
    case = _real_case(sha256)
    _run(service, db_session, admin, case, key="real-sample_a-lost")
    before = db_session.scalar(select(func.count()).select_from(ReviewUnit))

    # The file changes under the run, so read_html's integrity re-check returns None at write time.
    (raw_root / "case.html").write_bytes(b"<html>different bytes entirely</html>")
    changed = replace(case, fields=[replace(case.fields[0], display_value="CHANGED VALUE")])
    result = _run(
        service, db_session, admin, changed, key="real-sample_a-lost", refresh_existing=True
    )

    assert result.unresolved_source_cases == 1  # type: ignore[attr-defined]
    assert result.unresolved_case_ids == ["CAS-TEST-1"]  # type: ignore[attr-defined]
    assert result.imported_units == 0  # type: ignore[attr-defined]
    # Nothing was half-replaced: the prior generation is intact.
    assert db_session.scalar(select(func.count()).select_from(ReviewUnit)) == before
