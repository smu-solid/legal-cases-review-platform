"""Family reconciliation against the real review database.

Proves the operational family-identity contract on actual rows: legacy member-keyed pool units are
ADOPTED by their family key (never duplicated as a second assignable case), a family with assigned
work under a member key is DEFERRED whole with a manifest, member addition updates units in place
under the stable family key, member retargeting accounts for both families, generation replacement
applies only to unassigned pool inputs, and reruns are idempotent. Submitted/assigned work is
preserved byte-for-byte — never re-keyed or deleted.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from review_platform.dataset.types import (
    InputCandidate,
    InputCase,
    InputEvidence,
    InputField,
    MemberValue,
)
from review_platform.db.models import RoleGrant, TenantMembership, User
from review_platform.review.artifact_store import FilesystemArtifactStore
from review_platform.review.dataset_import import DatasetImportError, DatasetImportService
from review_platform.review.models import (
    AnnotationRevision,
    Assignment,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from tests.support.documents import FileDocuments
from tests.support.identities import AdminIdentity

_SAMPLE_A_FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "fixtures"
    / "documents"
    / "sample_a_synthetic.html"
)


def _candidate(value: str) -> InputCandidate:
    return InputCandidate(
        source_kind="deterministic",
        verdict="supported",
        value=value,
        rationale="r",
        supporting_quote=None,
    )


def _evidence(sha: str) -> InputEvidence:
    return InputEvidence(
        kind="quote",
        snippet="first judgment paragraph BODYONE",
        char_start=10,
        char_end=20,
        line_start=None,
        line_end=None,
        source_hash=sha,
    )


def _field(name: str, value: str, sha: str, members: list[MemberValue]) -> InputField:
    return InputField(
        field_name=name,
        display_value=value,
        value_candidate=_candidate(value),
        model_candidate=None,
        evidence=[_evidence(sha)],
        member_values=tuple(members),
        cross_source_disagreement=len({m.value for m in members}) > 1,
    )


def _observation_case(external_id: str, sha: str, value: str = "Tan J") -> InputCase:
    """A PRE-GROUPING import shape: raw observation id as the case identity (legacy keys)."""
    return InputCase(
        external_id=external_id,
        source_system="sample_a",
        source_document_id=f"SRC-{external_id[-3:]}",
        sha256=sha,
        title="AA v BB",
        fields=[_field("cases.coram", value, sha, [])],
    )


def _family_case(
    family_id: str,
    sha: str,
    members: list[tuple[str, str, str]],  # (case id, source system, value)
) -> InputCase:
    member_values = [
        MemberValue(
            case_external_id=case_id,
            source_system=source,
            value=value,
            source_document_id=f"SRC-{case_id[-3:]}",
            sha256=sha if case_id == family_id else f"other-{case_id}",
            evidence=({"snippet": f"snippet {value}", "source_hash": sha, "kind": "quote"},),
        )
        for case_id, source, value in members
    ]
    return InputCase(
        external_id=family_id,
        source_system="sample_a",
        source_document_id=f"SRC-{family_id[-3:]}",
        sha256=sha,
        title="AA v BB",
        fields=[_field("cases.coram", members[0][2], sha, member_values)],
        family_id=family_id,
        member_external_ids=tuple(case_id for case_id, _s, _v in members),
        member_source_systems=tuple(source for _c, source, _v in members),
    )


def _service(root: Path, store_root: Path) -> tuple[DatasetImportService, str]:
    root.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    raw = _SAMPLE_A_FIXTURE.read_bytes()
    (root / "case.html").write_bytes(raw)
    sha256 = hashlib.sha256(raw).hexdigest()
    service = DatasetImportService(
        resolver=FileDocuments([root]),
        store=FilesystemArtifactStore(root=store_root),
        audit_key="k" * 32,
    )
    return service, sha256


def _import(
    service: DatasetImportService,
    db_session: Session,
    admin: AdminIdentity,
    cases: list[InputCase],
    *,
    refresh: bool = False,
    campaign_status: str = "pool",
):
    """Import into a POOL campaign by default: these are pool-reconciliation tests, and the
    destructive adoption path is deliberately scoped to pool generations."""
    return service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="family-recon",
        campaign_name="Family reconciliation",
        source_system="sample_a",
        cases=cases,
        refresh_existing=refresh,
        campaign_status=campaign_status,
    )


def _unit_keys(db_session: Session, admin: AdminIdentity) -> set[str]:
    rows = db_session.scalars(
        select(ReviewSubject.attributes_json["logical_external_item_key"].astext).where(
            ReviewSubject.tenant_id == admin.tenant_id
        )
    )
    return {key for key in rows if key}


def _reviewer(db_session: Session, admin: AdminIdentity) -> uuid.UUID:
    user = User(
        email_normalized=f"reviewer-{uuid.uuid4().hex[:8]}@example.test",
        display_name="R",
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


def _assign(db_session: Session, admin: AdminIdentity, unit_id: uuid.UUID) -> None:
    db_session.add(
        Assignment(
            tenant_id=admin.tenant_id,
            review_unit_id=unit_id,
            reviewer_id=_reviewer(db_session, admin),
            lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    db_session.flush()


def test_legacy_pointer_unit_is_adopted_not_duplicated(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Legacy root+pointer pool → ONE assignable family unit; the pointer key is reconciled."""
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    # The legacy pool: the ROOT and the POINTER were imported as separate raw observations.
    _import(service, db_session, admin, [_observation_case("CAS-000001", sha)])
    _import(service, db_session, admin, [_observation_case("CAS-000002", sha)])
    assert _unit_keys(db_session, admin) == {"CAS-000001:cases.coram", "CAS-000002:cases.coram"}

    family = _family_case(
        "CAS-000001",
        sha,
        [("CAS-000001", "sample_a", "Tan J"), ("CAS-000002", "sample_b", "Tan J")],
    )
    result = _import(service, db_session, admin, [family], refresh=True)

    keys = _unit_keys(db_session, admin)
    assert keys == {"CAS-000001:cases.coram"}, "exactly one assignable family unit remains"
    assert db_session.scalar(select(func.count()).select_from(ReviewUnit)) == 1
    assert {r["old_key"] for r in result.reconciled_legacy_keys} <= {
        "CAS-000001:cases.coram",
        "CAS-000002:cases.coram",
    }
    # The persisted subject carries both source-labelled member values (the display contract).
    subject = db_session.scalars(
        select(ReviewSubject).where(ReviewSubject.tenant_id == admin.tenant_id)
    ).one()
    stored = subject.attributes_json["member_values"]
    assert {entry["source_system"] for entry in stored} == {"sample_a", "sample_b"}
    assert subject.attributes_json["cross_source_disagreement"] is False


def test_assigned_member_keyed_unit_defers_the_whole_family(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Protected legacy work defers the family whole; no root-keyed unit appears beside it."""
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    _import(service, db_session, admin, [_observation_case("CAS-000002", sha)])
    unit_id = db_session.scalars(select(ReviewUnit.id)).one()
    _assign(db_session, admin, unit_id)

    family = _family_case(
        "CAS-000001",
        sha,
        [("CAS-000001", "sample_a", "Tan J"), ("CAS-000002", "sample_b", "Tan J")],
    )
    result = _import(service, db_session, admin, [family], refresh=True)

    assert "CAS-000001" in result.deferred_families
    manifest = result.deferred_families["CAS-000001"]
    assert manifest["blocking_unit_keys"] == ["CAS-000002:cases.coram"]
    assert set(manifest["member_external_ids"]) == {"CAS-000001", "CAS-000002"}
    # The assigned legacy unit is untouched and no family-keyed sibling was created.
    assert _unit_keys(db_session, admin) == {"CAS-000002:cases.coram"}
    assert db_session.scalar(select(func.count()).select_from(Assignment)) == 1


def test_member_addition_updates_in_place_and_rerun_is_idempotent(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    one_member = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    first = _import(service, db_session, admin, [one_member])
    assert first.imported_units == 1

    # A second source observation joins the family later: same family key, updated unit.
    two_members = _family_case(
        "CAS-000001",
        sha,
        [("CAS-000001", "sample_a", "Tan J"), ("CAS-000002", "sample_b", "Tan, Lee JJ")],
    )
    second = _import(service, db_session, admin, [two_members], refresh=True)
    assert second.imported_units == 1  # replaced in place, not duplicated
    assert _unit_keys(db_session, admin) == {"CAS-000001:cases.coram"}
    subject = db_session.scalars(
        select(ReviewSubject).where(ReviewSubject.tenant_id == admin.tenant_id)
    ).one()
    assert subject.attributes_json["cross_source_disagreement"] is True
    assert len(subject.attributes_json["member_values"]) == 2

    third = _import(service, db_session, admin, [two_members], refresh=True)
    assert third.imported_units == 0, "unchanged rerun writes nothing"
    assert db_session.scalar(select(func.count()).select_from(ReviewUnit)) == 1


def test_member_retargeting_accounts_for_both_families(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A member moving families: the old family drops it; the new family adopts its legacy key."""
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    _import(service, db_session, admin, [_observation_case("CAS-000003", sha)])
    assert _unit_keys(db_session, admin) == {"CAS-000003:cases.coram"}

    # CAS-000003 is retargeted INTO family CAS-000001 (it was a mis-attached observation).
    new_family = _family_case(
        "CAS-000001",
        sha,
        [("CAS-000001", "sample_a", "Tan J"), ("CAS-000003", "sample_b", "Tan J")],
    )
    result = _import(service, db_session, admin, [new_family], refresh=True)
    assert result.deferred_families == {}
    assert _unit_keys(db_session, admin) == {"CAS-000001:cases.coram"}
    assert any(r["old_key"] == "CAS-000003:cases.coram" for r in result.reconciled_legacy_keys)


def test_submitted_family_units_are_never_rekeyed_or_deleted(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """Generation replacement applies to unassigned pool inputs only; held work defers whole."""
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    family = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    _import(service, db_session, admin, [family])
    unit_id = db_session.scalars(select(ReviewUnit.id)).one()
    _assign(db_session, admin, unit_id)
    snapshot_id = db_session.scalars(select(SourceSnapshot.id)).one()

    changed = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan, Lee JJ")])
    with pytest.raises(DatasetImportError, match="has an assignment"):
        _import(service, db_session, admin, [changed], refresh=True)
    # The held unit's generation is intact: same snapshot, same key, assignment alive. The refusal
    # happens BEFORE any deletion, so no rollback is needed to keep the state consistent.
    assert db_session.scalars(select(SourceSnapshot.id)).one() == snapshot_id
    assert db_session.scalar(select(func.count()).select_from(Assignment)) == 1


def _submit(db_session: Session, admin: AdminIdentity, unit_id: uuid.UUID) -> uuid.UUID:
    """A REAL submitted review: submitted assignment plus a submitted annotation revision."""
    reviewer_id = _reviewer(db_session, admin)
    assignment = Assignment(
        tenant_id=admin.tenant_id,
        review_unit_id=unit_id,
        reviewer_id=reviewer_id,
        lease_expires_at=datetime.now(UTC) + timedelta(hours=1),
        status="submitted",
        submitted_at=datetime.now(UTC),
    )
    db_session.add(assignment)
    db_session.flush()
    revision = AnnotationRevision(
        tenant_id=admin.tenant_id,
        assignment_id=assignment.id,
        revision_no=1,
        state="submitted",
        outcome="candidate_a_preferred",
        assessments_json=[
            {"candidate_label": "A", "assessment": "correct"},
            {"candidate_label": "B", "assessment": "not_assessable"},
        ],
        evidence_ids_json=[],
        client_request_id=f"req-{uuid.uuid4().hex[:10]}",
        author_id=reviewer_id,
    )
    db_session.add(revision)
    db_session.flush()
    return revision.id


def test_unchanged_root_still_retires_a_stale_legacy_sibling(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """N3: an unchanged family-keyed generation must not leave a legacy duplicate assignable.

    The root generation is KEPT (same unit id survives, nothing rewritten); only the unassigned
    legacy sibling is retired, and the adoption is manifested.
    """
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    family = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    _import(service, db_session, admin, [family])
    root_unit_id = db_session.scalars(select(ReviewUnit.id)).one()
    # A stale pre-grouping sibling for the SAME logical unit arrives under its member key.
    _import(service, db_session, admin, [_observation_case("CAS-000002", sha)])
    assert _unit_keys(db_session, admin) == {"CAS-000001:cases.coram", "CAS-000002:cases.coram"}

    # Refresh with the IDENTICAL family input (digest unchanged) plus the sibling member listed.
    same_family = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    same_family = InputCase(
        **{
            **same_family.__dict__,
            "member_external_ids": ("CAS-000001", "CAS-000002"),
            "member_source_systems": ("sample_a", "sample_a"),
        }
    )
    result = _import(service, db_session, admin, [same_family], refresh=True)

    assert result.imported_units == 0, "the unchanged root generation is kept, not rewritten"
    surviving = db_session.scalars(select(ReviewUnit.id)).all()
    assert surviving == [root_unit_id], "exact survivor: the original root unit id"
    assert _unit_keys(db_session, admin) == {"CAS-000001:cases.coram"}
    assert {r["old_key"] for r in result.reconciled_legacy_keys} == {"CAS-000002:cases.coram"}


def test_retargeting_between_two_grouped_families_with_submitted_work_defers_both_sides(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """N4: a TRUE retargeting scenario — two GROUPED families, the old one holding SUBMITTED work.

    Moving a member from grouped family A (submitted work) into grouped family B must defer B
    (historical membership identifies the protected old-family work) and must not create duplicate
    assignable work; A's submission, revision and unit survive byte-for-byte.
    """
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    family_a = _family_case(
        "CAS-000001",
        sha,
        [("CAS-000001", "sample_a", "Tan J"), ("CAS-000003", "sample_b", "Tan J")],
    )
    _import(service, db_session, admin, [family_a])
    a_unit_id = db_session.scalars(select(ReviewUnit.id)).one()
    revision_id = _submit(db_session, admin, a_unit_id)

    # The member CAS-000003 is retargeted into grouped family B while A holds submitted work.
    family_b = _family_case(
        "CAS-000002",
        sha,
        [("CAS-000002", "sample_a", "Lee J"), ("CAS-000003", "sample_b", "Lee J")],
    )
    result = _import(service, db_session, admin, [family_b], refresh=True)

    assert "CAS-000002" in result.deferred_families, (
        "the receiving family defers over A's held work"
    )
    blocking = result.deferred_families["CAS-000002"]["blocking_unit_keys"]
    assert blocking == ["CAS-000001:cases.coram"]
    # Nothing was created for B; A's unit, submitted assignment and revision are intact.
    assert db_session.scalars(select(ReviewUnit.id)).all() == [a_unit_id]
    assert db_session.scalar(select(func.count()).select_from(Assignment)) == 1
    assert db_session.get(AnnotationRevision, revision_id) is not None
    assert (
        db_session.scalar(select(Assignment.status).where(Assignment.review_unit_id == a_unit_id))
        == "submitted"
    )


def test_family_keyed_submitted_work_with_membership_change_defers(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """N4: root-keyed protected work is guarded too — a membership transition on a held
    family-keyed unit defers the family instead of raising mid-run or rewriting the submission."""
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    family = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    _import(service, db_session, admin, [family])
    unit_id = db_session.scalars(select(ReviewUnit.id)).one()
    _submit(db_session, admin, unit_id)

    grown = _family_case(
        "CAS-000001",
        sha,
        [("CAS-000001", "sample_a", "Tan J"), ("CAS-000002", "sample_b", "Tan, Lee JJ")],
    )
    result = _import(service, db_session, admin, [grown], refresh=True)
    assert "CAS-000001" in result.deferred_families
    assert result.deferred_families["CAS-000001"]["blocking_unit_keys"] == [
        "CAS-000001:cases.coram"
    ]
    # The held generation is untouched: same unit, submitted assignment intact, no new units.
    assert db_session.scalars(select(ReviewUnit.id)).all() == [unit_id]
    assert db_session.scalar(select(func.count()).select_from(Assignment)) == 1


def test_multi_field_family_units_and_ordinary_then_refresh_import(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """N4 fixtures: multi-field families import one unit per field, ordinary import is idempotent,
    and a refresh replaces exactly the changed field's generation."""
    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    base = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    two_fields = InputCase(
        **{
            **base.__dict__,
            "fields": [
                _field("cases.coram", "Tan J", sha, list(base.fields[0].member_values)),
                _field("cases.citation_neutral", "[2020] SGHC 1", sha, []),
            ],
        }
    )
    first = _import(service, db_session, admin, [two_fields])
    assert first.imported_units == 2
    again = _import(service, db_session, admin, [two_fields])
    assert again.imported_units == 0, "ordinary (non-refresh) import stays idempotent"

    changed = InputCase(
        **{
            **two_fields.__dict__,
            "fields": [
                _field("cases.coram", "Tan, Lee JJ", sha, []),
                _field("cases.citation_neutral", "[2020] SGHC 1", sha, []),
            ],
        }
    )
    refreshed = _import(service, db_session, admin, [changed], refresh=True)
    assert refreshed.imported_units == 1, "only the changed field's generation is replaced"
    assert _unit_keys(db_session, admin) == {
        "CAS-000001:cases.coram",
        "CAS-000001:cases.citation_neutral",
    }


def test_refresh_creates_a_field_whose_logical_key_did_not_exist(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A field that becomes non-null AFTER the first import gains its own unit on refresh."""

    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    base = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    first = _import(service, db_session, admin, [base])
    assert first.imported_units == 1
    assert _unit_keys(db_session, admin) == {"CAS-000001:cases.coram"}
    coram_before = db_session.scalar(
        select(SourceSnapshot.input_digest).where(
            SourceSnapshot.external_item_key == "CAS-000001:cases.coram"
        )
    )
    units_before = db_session.scalar(select(func.count()).select_from(ReviewUnit))

    grown = InputCase(
        **{
            **base.__dict__,
            "fields": [
                base.fields[0],
                _field("cases.suit_num", "Suit 123 of 2016", sha, []),
            ],
        }
    )
    refreshed = _import(service, db_session, admin, [grown], refresh=True)

    assert refreshed.imported_units == 1, "exactly the newly non-null field is imported"
    assert _unit_keys(db_session, admin) == {
        "CAS-000001:cases.coram",
        "CAS-000001:cases.suit_num",
    }
    assert db_session.scalar(select(func.count()).select_from(ReviewUnit)) == units_before + 1
    # The field that did not change keeps its original generation untouched.
    assert (
        db_session.scalar(
            select(SourceSnapshot.input_digest).where(
                SourceSnapshot.external_item_key == "CAS-000001:cases.coram"
            )
        )
        == coram_before
    )

    # An independent second refresh of the same input imports nothing and changes no key.
    keys_after = _unit_keys(db_session, admin)
    units_after = db_session.scalar(select(func.count()).select_from(ReviewUnit))
    again = _import(service, db_session, admin, [grown], refresh=True)
    assert again.imported_units == 0
    assert _unit_keys(db_session, admin) == keys_after
    assert db_session.scalar(select(func.count()).select_from(ReviewUnit)) == units_after


def test_refresh_creates_a_newly_non_null_field_on_a_multi_member_family(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """The same creation path under the family key when the value arrives from a pointer member.

    The unit stays family-keyed: a member observation never earns its own second assignable case.
    """

    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    members = [("CAS-000001", "sample_a", "Tan J"), ("CAS-000002", "sample_b", "Tan J")]
    base = _family_case("CAS-000001", sha, members)
    _import(service, db_session, admin, [base])
    assert _unit_keys(db_session, admin) == {"CAS-000001:cases.coram"}

    member_value = MemberValue(
        case_external_id="CAS-000002",
        source_system="sample_b",
        value="Originating Summons",
        source_document_id="SRC-002",
        sha256=f"other-{'CAS-000002'}",
        evidence=({"snippet": "snippet OS", "source_hash": sha, "kind": "quote"},),
    )
    grown = InputCase(
        **{
            **base.__dict__,
            "fields": [
                base.fields[0],
                _field("cases.proceedings_type", "Originating Summons", sha, [member_value]),
            ],
        }
    )
    refreshed = _import(service, db_session, admin, [grown], refresh=True)

    assert refreshed.imported_units == 1
    assert _unit_keys(db_session, admin) == {
        "CAS-000001:cases.coram",
        "CAS-000001:cases.proceedings_type",
    }
    assert not [key for key in _unit_keys(db_session, admin) if key.startswith("CAS-000002:")]


def test_importer_accepts_a_field_its_reader_supplied_without_evidence(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """The importer imposes no evidence requirement of its own; the gate is the reader's."""

    service, sha = _service(tmp_path / "raw", tmp_path / "store")
    base = _family_case("CAS-000001", sha, [("CAS-000001", "sample_a", "Tan J")])
    evidenceless = InputField(
        field_name="cases.proceedings_type",
        display_value="Originating Summons",
        value_candidate=_candidate("Originating Summons"),
        model_candidate=None,
        evidence=[],
    )
    case = InputCase(**{**base.__dict__, "fields": [base.fields[0], evidenceless]})

    result = _import(service, db_session, admin, [case])

    assert result.imported_units == 2
    assert "CAS-000001:cases.proceedings_type" in _unit_keys(db_session, admin)
