from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.dataset.types import (
    InputCase,
    InputEvidence,
    InputField,
)
from review_platform.review.artifact_store import FilesystemArtifactStore
from review_platform.review.dataset_import import DatasetImportService
from review_platform.review.models import (
    Adjudication,
    AdjudicationDecision,
    Assignment,
    Candidate,
    CaseSubmission,
    EvidenceWindow,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
    SourceRenderArtifact,
)
from tests.support.documents import FileDocuments
from tests.support.identities import AdminIdentity
from tests.support.import_cases import (
    _PRESENT_SNIPPET,
    _candidate,
    _cited_case_relation,
    _evidence,
    _import,
    _real_case,
    _service,
)


def test_provenance_reanchors_present_and_flags_omitted(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    result = _import(db_session, admin, tmp_path)
    # The omitted-headnote snippet is not a body quote, so its null offset is EXPECTED (anchored by
    # value, not body offset) -- not a matcher failure. No genuine body-quote miss occurs.
    assert result.unresolved_anchors == 0  # type: ignore[attr-defined]  # no body-quote miss
    assert result.unanchored_expected == 1  # type: ignore[attr-defined]  # omitted-region snippet
    windows = db_session.scalars(select(EvidenceWindow).order_by(EvidenceWindow.ordinal)).all()
    assert len(windows) == 2
    present, omitted = windows
    assert present.char_start is not None and present.char_end is not None  # re-anchored
    assert omitted.char_start is None and omitted.char_end is None  # omitted -> null offsets
    assert omitted.snippet  # snippet preserved even when unanchored


@pytest.mark.parametrize(
    ("header_citation", "full_value"),
    [
        ("[1993] 3 rep(R) 656", "[1993] 3 rep(R) 656; [1994] 1 rep 119"),
        ("[1983–1984] rep(R) 219", "[1983-1984] rep(R) 219; [1982-1983] rep 379"),
    ],
)
def test_reported_citation_display_preserves_submitted_work(
    db_session: Session,
    admin: AdminIdentity,
    tmp_path: Path,
    header_citation: str,
    full_value: str,
) -> None:
    assert header_citation.split(" ")[0].startswith("[")
    raw = (
        '<p class="caseTitle">Example Appellant v Sample Respondent</p>'
        f"<p>{full_value}</p>"
        '<p class="Citation">[1993] SGCA 90</p>'
        '<p class="Judg-1">The appeal was dismissed.</p>'
    ).encode()
    raw_root, store_root = tmp_path / "raw", tmp_path / "store"
    raw_root.mkdir()
    store_root.mkdir()
    (raw_root / "case.html").write_bytes(raw)
    sha = hashlib.sha256(raw).hexdigest()
    case = InputCase(
        external_id="CAS-000922",
        source_system="sample_a",
        source_document_id="SRC-922",
        sha256=sha,
        title="Example Appellant v Sample Respondent",
        fields=[
            InputField(
                field_name="cases.citation_reporter",
                display_value=full_value,
                value_candidate=_candidate("deterministic", full_value),
                model_candidate=None,
                evidence=[
                    InputEvidence("quote", full_value, None, None, None, None, sha),
                    InputEvidence("quote", full_value, None, None, None, None, "b" * 64),
                ],
            )
        ],
    )
    store = FilesystemArtifactStore(store_root)
    service = DatasetImportService(
        resolver=FileDocuments([raw_root]),
        store=store,
        audit_key="k" * 32,
    )
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="citation-read-test",
        campaign_name="Citation read test",
        source_system="sample_a",
        cases=[case],
    )
    unit = db_session.scalar(
        select(ReviewUnit).where(ReviewUnit.field_name == "cases.citation_reporter")
    )
    assert unit is not None
    window = db_session.scalar(
        select(EvidenceWindow)
        .where(EvidenceWindow.review_unit_id == unit.id)
        .order_by(EvidenceWindow.ordinal)
    )
    foreign_window = db_session.scalar(
        select(EvidenceWindow).where(
            EvidenceWindow.review_unit_id == unit.id, EvidenceWindow.ordinal == 1
        )
    )
    subject = db_session.get(ReviewSubject, unit.review_subject_id)
    candidate = db_session.scalar(select(Candidate).where(Candidate.review_unit_id == unit.id))
    assert window is not None and foreign_window is not None
    assert subject is not None and candidate is not None
    assert window.char_start is not None and window.anchor_status == "anchored"
    assert foreign_window.anchor_status == "other_document"
    assert candidate.value_json == full_value and window.snippet == full_value
    unit.status = "resolved"
    assignment = Assignment(
        tenant_id=admin.tenant_id,
        review_unit_id=unit.id,
        reviewer_id=admin.user_id,
        status="submitted",
        lease_expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    db_session.add(assignment)
    db_session.flush()
    manual_span = [{"evidence_window_id": str(window.id), "char_start": 5, "char_end": 12}]
    answer = ReviewItemAnswer(
        tenant_id=admin.tenant_id,
        assignment_id=assignment.id,
        revision_no=1,
        state="submitted",
        value_correct=True,
        provenance_correct=False,
        corrected_value_json=None,
        corrected_value_display=None,
        comment="Manual provenance",
        failure_reason=None,
        evidence_ids_json=[str(window.id)],
        corrected_provenance_spans_json=manual_span,
        client_request_id="citation-answer-1",
        author_id=admin.user_id,
    )
    submission = CaseSubmission(
        tenant_id=admin.tenant_id,
        campaign_id=unit.campaign_id,
        case_id="CAS-000922",
        reviewer_id=admin.user_id,
    )
    adjudication = Adjudication(
        tenant_id=admin.tenant_id,
        review_unit_id=unit.id,
        status="resolved",
    )
    db_session.add_all((answer, submission, adjudication))
    db_session.flush()
    decision = AdjudicationDecision(
        tenant_id=admin.tenant_id,
        adjudication_id=adjudication.id,
        outcome="candidate_a_preferred",
        corrected_value_json=None,
        corrected_value_display=None,
        comment="Decision retained",
        assessments_json=[{"candidate": "A"}, {"candidate": "B"}],
        evidence_ids_json=[str(window.id)],
        corrected_provenance_spans_json=manual_span,
        client_request_id="citation-decision-1",
        decided_by=admin.user_id,
    )
    db_session.add(decision)
    db_session.flush()
    before = (
        unit.id,
        unit.status,
        unit.input_digest,
        window.id,
        candidate.value_json,
        assignment.status,
        answer.corrected_provenance_spans_json,
        submission.id,
        adjudication.status,
        decision.corrected_provenance_spans_json,
    )

    from review_platform.review.grouped_bundle import ReviewGroupedBundleMixin
    from review_platform.review.grouping import classify_unit
    from review_platform.review.projections import evidence_response

    prepared = [
        (
            classify_unit(unit.review_kind, unit.safe_field_label, unit.field_name),
            assignment,
            unit,
            subject,
            [window, foreign_window],
        )
    ]
    source, anchors, unavailable, _groups, offsets = ReviewGroupedBundleMixin._build_source_render(
        db_session,
        tenant_id=admin.tenant_id,
        prepared=prepared,
        source_snapshot_id=subject.source_snapshot_id,
        artifact_store=store,
    )
    assert not unavailable
    anchor = next(a for a in source.anchors if a.anchor_id == anchors[unit.id])
    assert source.content[anchor.char_start : anchor.char_end] == full_value
    projected = evidence_response(window, subject.attributes_json, effective_offsets=offsets)
    assert projected.anchor_status == "anchored"
    assert projected.id == window.id and projected.snippet == full_value
    assert foreign_window.id not in offsets
    assert window.id not in offsets
    db_session.flush()
    db_session.refresh(window)
    assert window.char_start is not None
    after = (
        unit.id,
        unit.status,
        unit.input_digest,
        window.id,
        candidate.value_json,
        assignment.status,
        answer.corrected_provenance_spans_json,
        submission.id,
        adjudication.status,
        decision.corrected_provenance_spans_json,
    )
    assert after == before


def test_body_grounded_relation_miss_counts_as_unresolved_not_expected(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test body grounded relation miss counts as unresolved not expected."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    relation = replace(
        _cited_case_relation(),
        evidence=[
            InputEvidence(
                kind="quote",
                snippet="this exact phrase is absent from the rendered body",
                char_start=1,
                char_end=2,
                line_start=None,
                line_end=None,
                source_hash=sha256,
                body_grounded=True,
                source_region="judgment_body",
            )
        ],
    )
    case.relations.append(relation)
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-body-grounded-miss",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    # +1 unresolved from the relation's body-grounded miss; the base case's own field evidence
    # (present + omitted snippet, see `_real_case`) still contributes its usual 1 `expected`.
    assert result.unresolved_anchors == 1  # type: ignore[attr-defined]
    assert result.unanchored_expected == 1  # type: ignore[attr-defined]


def test_reference_grounded_relation_miss_still_counts_as_expected(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test reference grounded relation miss still counts as expected."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    relation = replace(
        _cited_case_relation(),
        evidence=[
            InputEvidence(
                kind="quote",
                snippet="this exact phrase is absent from the rendered body",
                char_start=1,
                char_end=2,
                line_start=None,
                line_end=None,
                source_hash=sha256,
                body_grounded=False,
                source_region="reference_table",
            )
        ],
    )
    case.relations.append(relation)
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-reference-grounded",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    # The reference-grounded relation's miss adds a 2nd `expected` on top of the base case's own
    # field evidence (present + omitted snippet, see `_real_case`), which already contributes 1.
    assert result.unresolved_anchors == 0  # type: ignore[attr-defined]
    assert result.unanchored_expected == 2  # type: ignore[attr-defined]


def test_provenance_only_unit_has_single_value_candidate(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    case.fields[0] = InputField(
        field_name="cases.citation_neutral",
        display_value="[2018] SGHCF 99",
        value_candidate=_candidate("deterministic", "[2018] SGHCF 99"),
        model_candidate=None,  # no LLM/admin validator context available
        evidence=[_evidence(_PRESENT_SNIPPET)],
    )
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    labels = list(db_session.scalars(select(Candidate.label)).all())
    assert labels == ["A"]  # reviewer still gets the value + provenance to review


def test_no_filesystem_path_persisted(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    _import(db_session, admin, tmp_path)
    subject = db_session.scalar(select(ReviewSubject))
    assert subject is not None
    serialized = str(subject.attributes_json)
    assert (
        "/raw/" not in serialized and ".html" not in serialized and str(tmp_path) not in serialized
    )
    # The artifact object key is the opaque content digest, never a path.
    artifact = db_session.scalar(select(SourceRenderArtifact))
    assert artifact is not None and "/" not in artifact.object_key


def test_evidence_of_another_document_is_stored_unanchored_not_searched_in_the_render(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Appeal evidence located in the counterpart judgment used to "anchor" at a coincidental
    occurrence of the same citation in this judgment (2,967 attempts in the 2026-09 production
    imports). Evidence whose source hash is not the render document is never searched in the
    render: it is kept, with null offsets, as ``other_document``."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    case = _real_case(sha256)
    relation = replace(
        _cited_case_relation(),
        evidence=[
            InputEvidence(
                kind="quote",
                snippet=_PRESENT_SNIPPET,  # present in THIS render, but attributed elsewhere
                char_start=1,
                char_end=2,
                line_start=None,
                line_end=None,
                source_hash="a" * 64,
                body_grounded=True,
                source_region="judgment_body",
                provenance_external_id="PRV-OTHER",
            )
        ],
    )
    case.relations.append(relation)
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-other-document",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        cases=[case],
    )
    assert result.unresolved_anchors == 0  # type: ignore[attr-defined]
    window = db_session.scalar(
        select(EvidenceWindow).where(EvidenceWindow.provenance_external_id == "PRV-OTHER")
    )
    assert window is not None
    assert window.anchor_status == "other_document"
    assert window.char_start is None and window.char_end is None
    assert window.source_sha256 == "a" * 64 and window.body_grounded is True
    field_windows = db_session.scalars(
        select(EvidenceWindow).where(
            EvidenceWindow.anchor_status.in_(["anchored", "expected_unanchored"])
        )
    ).all()
    assert {w.anchor_status for w in field_windows} == {"anchored", "expected_unanchored"}


def test_provenance_identity_is_persisted_without_changing_the_unit_digest(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Test provenance identity is persisted without changing the unit digest."""

    service, sha256 = _service(tmp_path / "raw", tmp_path / "store")
    base = _real_case(sha256)
    with_ids = replace(
        base,
        fields=[
            replace(
                base.fields[0],
                evidence=[
                    replace(e, provenance_external_id=f"PRV-{i}")
                    for i, e in enumerate(base.fields[0].evidence)
                ],
            )
        ],
    )
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-digest",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        campaign_status="pool",
        cases=[base],
    )
    digest_before = db_session.scalar(select(ReviewUnit.input_digest))
    windows = db_session.scalars(select(EvidenceWindow).order_by(EvidenceWindow.ordinal)).all()
    assert [w.provenance_external_id for w in windows] == [None, None]
    assert [w.anchor_status for w in windows] == ["anchored", "expected_unanchored"]
    # Re-import with identities and refresh: digests match, so nothing is rewritten.
    result = service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-sample_a-digest",
        campaign_name="Real Review (sample_a)",
        source_system="sample_a",
        campaign_status="pool",
        cases=[with_ids],
        refresh_existing=True,
    )
    assert result.imported_units == 0 and result.skipped_unchanged_cases == 1
    assert db_session.scalar(select(ReviewUnit.input_digest)) == digest_before
