from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
from threading import Barrier, Event

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

import review_platform.review.campaign_materialization as campaign_availability_module
from review_platform.common.errors import APIError
from review_platform.db.models import utcnow
from review_platform.db.session import Database
from review_platform.review.case_pool import (
    POOL_CAMPAIGN_KEY,
    campaign_has_started_work,
)
from review_platform.review.models import (
    Assignment,
    Campaign,
    ReviewItemAnswer,
    ReviewSubject,
    ReviewUnit,
    SourceSnapshot,
)
from review_platform.review.schemas import (
    CampaignReviewScopeInput,
    CreateCampaignRequest,
    ReviewItemAnswerInput,
)
from review_platform.settings import Settings
from tests.support.identities import AdminIdentity
from tests.support.pool import (
    _SAMPLE_B_FIXTURE,
    _case,
    _ensure_admin_is_reviewer,
    _pool_unit_count,
    _principal,
    _seed_pool,
    _service,
    _sha,
)


def test_two_sessions_cannot_double_claim_the_same_pool_case(
    database: Database,
    settings: Settings,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    """The per-tenant transaction lock spans availability and materialization."""

    del settings  # fixture documents that this is the configured disposable PostgreSQL database
    with database.session() as seed_session:
        _seed_pool(seed_session, admin, tmp_path, [_case("CAS-RACE", _sha(), groups=1)])
        seed_session.commit()

    barrier = Barrier(2)

    def claim(index: int) -> tuple[str, str | None]:
        with database.session() as session:
            service = _service(tmp_path)
            principal = _principal(session, admin)
            barrier.wait(timeout=5)
            try:
                created = service.create_campaign(
                    session,
                    tenant_id=admin.tenant_id,
                    principal=principal,
                    body=CreateCampaignRequest(
                        campaign_key=f"race-{index}",
                        campaign_name=f"Race {index}",
                        requested_case_count=1,
                    ),
                    request_id=f"req-race-{index}",
                )
                session.commit()
                return "created", str(created.campaign_id)
            except APIError as error:
                session.rollback()
                return error.code, None

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(claim, (1, 2)))

    assert sorted(code for code, _ in results) == ["campaign_no_cases_available", "created"]
    winner_id = next(campaign_id for code, campaign_id in results if code == "created")
    with database.session() as verify_session:
        owners = list(
            verify_session.scalars(
                select(ReviewUnit.campaign_id)
                .join(Campaign, Campaign.id == ReviewUnit.campaign_id)
                .where(
                    ReviewUnit.tenant_id == admin.tenant_id,
                    Campaign.key.in_({"race-1", "race-2"}),
                )
            )
        )
        assert [str(owner) for owner in owners] == [winner_id]
        assert _pool_unit_count(verify_session, admin) == 0


def test_delete_work_check_blocks_a_concurrent_draft_save(
    database: Database,
    settings: Settings,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    """A draft save cannot commit in the work-check/assignment-delete window."""

    del settings
    with database.session() as seed_session:
        _seed_pool(seed_session, admin, tmp_path, [_case("CAS-DELETE-RACE", _sha(), groups=1)])
        _ensure_admin_is_reviewer(seed_session, admin)
        service = _service(tmp_path)
        created = service.create_campaign(
            seed_session,
            tenant_id=admin.tenant_id,
            principal=_principal(seed_session, admin),
            body=CreateCampaignRequest(
                campaign_key="delete-save-race",
                campaign_name="Delete/save race",
                requested_case_count=1,
            ),
            request_id="req-delete-save-race-create",
        )
        unit_id = seed_session.scalar(
            select(ReviewUnit.id).where(ReviewUnit.campaign_id == created.campaign_id)
        )
        assignment = Assignment(
            tenant_id=admin.tenant_id,
            review_unit_id=unit_id,
            reviewer_id=admin.user_id,
            status="claimed",
            lease_expires_at=utcnow() + timedelta(hours=1),
        )
        seed_session.add(assignment)
        seed_session.flush()
        assignment_id = assignment.id
        campaign_id = created.campaign_id
        seed_session.commit()

    saver_ready = Event()
    work_checked = Event()
    save_started = Event()
    save_finished = Event()

    def delete_campaign() -> str:
        with database.session() as session:
            assert saver_ready.wait(timeout=5)
            assert not campaign_has_started_work(
                session, tenant_id=admin.tenant_id, campaign_id=campaign_id
            )
            work_checked.set()
            assert save_started.wait(timeout=5)
            # The save session is already open and inside save_item_answer. It must be waiting on
            # the assignment lock held by campaign_has_started_work, not committing a child row.
            assert not save_finished.wait(timeout=1)
            _service(tmp_path).delete_campaign(
                session,
                tenant_id=admin.tenant_id,
                principal=_principal(session, admin),
                campaign_id=campaign_id,
                confirm=True,
                request_id="req-delete-save-race-delete",
            )
            session.commit()
            return "deleted"

    def save_draft() -> str:
        with database.session() as session:
            principal = _principal(session, admin)
            saver_ready.set()
            assert work_checked.wait(timeout=5)
            save_started.set()
            try:
                _service(tmp_path).save_item_answer(
                    session,
                    tenant_id=admin.tenant_id,
                    assignment_id=assignment_id,
                    principal=principal,
                    answer=ReviewItemAnswerInput(value_correct=True, provenance_correct=True),
                    state="draft",
                    expected_version=0,
                    idempotency_key="delete-save-race-draft",
                    request_id="req-delete-save-race-draft",
                )
                session.commit()
                return "saved"
            except APIError as error:
                session.rollback()
                return error.code
            finally:
                save_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        delete_future = executor.submit(delete_campaign)
        save_future = executor.submit(save_draft)
        assert delete_future.result(timeout=10) == "deleted"
        assert save_future.result(timeout=10) == "not_found"

    with database.session() as verify_session:
        assert verify_session.get(Assignment, assignment_id) is None
        assert (
            verify_session.scalar(
                select(func.count())
                .select_from(ReviewItemAnswer)
                .where(ReviewItemAnswer.assignment_id == assignment_id)
            )
            == 0
        )


def test_materialization_uses_exact_preselected_ids_and_keeps_duplicate_sources_isolated(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    """A repeated case ID in another source must not create an independent-set cross-product."""

    duplicate_case_id = "DUPLICATE-CASE-ID"
    _seed_pool(
        db_session,
        admin,
        tmp_path,
        [_case(duplicate_case_id, _sha(), source_system="sample_a", groups=1)],
    )
    pool = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id,
            Campaign.key == POOL_CAMPAIGN_KEY,
        )
    )
    assert pool is not None
    snapshot = SourceSnapshot(
        tenant_id=admin.tenant_id,
        contract_version="test/v1",
        source_mode="dataset",
        source_version="ELI-DOC",
        external_item_key="sample_b-duplicate-case-id:citation_neutral",
        input_digest="e" * 64,
    )
    db_session.add(snapshot)
    db_session.flush()
    sample_b_subject = ReviewSubject(
        tenant_id=admin.tenant_id,
        source_snapshot_id=snapshot.id,
        subject_kind="case",
        external_subject_id=f"subject_{snapshot.id.hex}",
        display_title="Duplicate Sample B case",
        display_subtitle="Citation Neutral",
        source_version="ELI-DOC",
        primary_source_ref="source_sample_b_duplicate",
        attributes_json={
            "source_collection": "sample_b",
            "snapshot_local_case_external_id": duplicate_case_id,
            "source_sha256": _sha(_SAMPLE_B_FIXTURE),
        },
    )
    db_session.add(sample_b_subject)
    db_session.flush()
    db_session.add(
        ReviewUnit(
            tenant_id=admin.tenant_id,
            campaign_id=pool.id,
            review_subject_id=sample_b_subject.id,
            review_kind="metadata_field",
            question="Verify neutral citation",
            safe_field_label="Citation Neutral",
            field_name="cases.citation_neutral",
            required_reviews=2,
            input_digest="u" * 64,
        )
    )
    db_session.flush()
    source_col = ReviewSubject.attributes_json["source_collection"].astext
    seeded = db_session.execute(
        select(ReviewUnit.id, source_col, ReviewUnit.required_reviews, ReviewUnit.lock_version)
        .join(
            ReviewSubject,
            (ReviewSubject.tenant_id == ReviewUnit.tenant_id)
            & (ReviewSubject.id == ReviewUnit.review_subject_id),
        )
        .where(
            ReviewUnit.tenant_id == admin.tenant_id,
            ReviewUnit.campaign_id == pool.id,
        )
    ).all()
    expected_sample_a_ids = {
        unit_id for unit_id, source, _required, _lock in seeded if source == "sample_a"
    }
    expected_sample_b_ids = {
        unit_id for unit_id, source, _required, _lock in seeded if source == "sample_b"
    }
    seeded_versions = {
        unit_id: (required_reviews, lock_version)
        for unit_id, _source, required_reviews, lock_version in seeded
    }
    assert len(expected_sample_a_ids) == len(expected_sample_b_ids) == 1

    captured_updates: list[tuple[str, object]] = []

    def capture_update(
        _connection: object,
        _cursor: object,
        statement: str,
        parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        normalized = statement.lstrip().lower()
        if normalized.startswith("update ") and "review_units" in normalized:
            captured_updates.append((statement, parameters))

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", capture_update)
    try:
        response = _service(tmp_path).create_campaign(
            db_session,
            tenant_id=admin.tenant_id,
            principal=_principal(db_session, admin),
            body=CreateCampaignRequest(
                campaign_key="sample_a-duplicate-only",
                campaign_name="Sample A duplicate only",
                review_scope=CampaignReviewScopeInput(source_families=["sample_a"]),
                requested_case_count=1,
            ),
            request_id="req-paired-movement",
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_update)

    assert response.total_units == 1
    target = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id,
            Campaign.key == "sample_a-duplicate-only",
        )
    )
    assert target is not None
    moved_ids = set(
        db_session.scalars(
            select(ReviewUnit.id).where(
                ReviewUnit.tenant_id == admin.tenant_id,
                ReviewUnit.campaign_id == target.id,
            )
        )
    )
    remaining_ids = set(
        db_session.scalars(
            select(ReviewUnit.id).where(
                ReviewUnit.tenant_id == admin.tenant_id,
                ReviewUnit.campaign_id == pool.id,
            )
        )
    )
    assert moved_ids == expected_sample_a_ids
    assert remaining_ids == expected_sample_b_ids
    moved_state = db_session.execute(
        select(ReviewUnit.id, ReviewUnit.required_reviews, ReviewUnit.lock_version).where(
            ReviewUnit.id.in_(moved_ids)
        )
    ).all()
    remaining_state = db_session.execute(
        select(ReviewUnit.id, ReviewUnit.required_reviews, ReviewUnit.lock_version).where(
            ReviewUnit.id.in_(remaining_ids)
        )
    ).all()
    assert all(required_reviews == 2 for _unit_id, required_reviews, _lock in moved_state)
    assert all(
        lock_version == seeded_versions[unit_id][1] + 1
        for unit_id, _required, lock_version in moved_state
    )
    assert all(
        (required_reviews, lock_version) == seeded_versions[unit_id]
        for unit_id, required_reviews, lock_version in remaining_state
    )

    assert len(captured_updates) == 1
    statement, parameters = captured_updates[0]
    assert "unnest(" not in statement.lower()
    assert "review_units.id in" in statement.lower()
    assert isinstance(parameters, dict)
    assert expected_sample_a_ids <= set(parameters.values())
    assert len(parameters) < 100


def test_materialization_rowcount_mismatch_rolls_back_every_moved_unit(
    db_session: Session, admin: AdminIdentity, tmp_path: Path
) -> None:
    _seed_pool(db_session, admin, tmp_path, [_case("ROWCOUNT-ROLLBACK", _sha(), groups=1)])
    pool = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id,
            Campaign.key == POOL_CAMPAIGN_KEY,
        )
    )
    assert pool is not None
    selected_id = db_session.scalar(
        select(ReviewUnit.id).where(
            ReviewUnit.tenant_id == admin.tenant_id,
            ReviewUnit.campaign_id == pool.id,
        )
    )
    assert selected_id is not None
    target = Campaign(
        tenant_id=admin.tenant_id,
        key="rowcount-target",
        name="Rowcount target",
        status="draft",
        subject_kind="case",
        review_kind="metadata_field",
        policy_version="test/v1",
        policy_json={},
        manifest_digest="m" * 64,
        created_by=admin.user_id,
    )
    db_session.add(target)
    db_session.flush()

    with pytest.raises(RuntimeError, match="different number of units"), db_session.begin_nested():
        campaign_availability_module._move_selected_units(
            db_session,
            tenant_id=admin.tenant_id,
            pool_campaign_id=pool.id,
            target_campaign_id=target.id,
            required_reviews=3,
            selected_unit_ids=[selected_id, uuid.uuid4()],
        )

    db_session.expire_all()
    unit = db_session.get(ReviewUnit, selected_id)
    assert unit is not None
    assert unit.campaign_id == pool.id
    assert unit.required_reviews == 2
    assert unit.lock_version == 1


def test_second_movement_batch_failure_rolls_back_the_first_batch(
    db_session: Session,
    admin: AdminIdentity,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_pool(db_session, admin, tmp_path, [_case("SECOND-BATCH-ROLLBACK", _sha())])
    pool = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id,
            Campaign.key == POOL_CAMPAIGN_KEY,
        )
    )
    assert pool is not None
    original_ids = set(
        db_session.scalars(
            select(ReviewUnit.id).where(
                ReviewUnit.tenant_id == admin.tenant_id,
                ReviewUnit.campaign_id == pool.id,
            )
        )
    )
    assert len(original_ids) == 2
    monkeypatch.setattr(campaign_availability_module, "_MOVEMENT_BATCH_SIZE", 1)
    update_count = 0

    def fail_second_update(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        nonlocal update_count
        if statement.lstrip().lower().startswith("update ") and "review_units" in statement:
            update_count += 1
            if update_count == 2:
                raise RuntimeError("deliberate second-batch failure")

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", fail_second_update)
    try:
        with (
            pytest.raises(RuntimeError, match="deliberate second-batch failure"),
            db_session.begin_nested(),
        ):
            _service(tmp_path).create_campaign(
                db_session,
                tenant_id=admin.tenant_id,
                principal=_principal(db_session, admin),
                body=CreateCampaignRequest(
                    campaign_key="second-batch-target",
                    campaign_name="Second batch target",
                    requested_case_count=1,
                ),
                request_id="req-second-batch-failure",
            )
    finally:
        event.remove(engine, "before_cursor_execute", fail_second_update)

    db_session.expire_all()
    remaining_ids = set(
        db_session.scalars(
            select(ReviewUnit.id).where(
                ReviewUnit.tenant_id == admin.tenant_id,
                ReviewUnit.campaign_id == pool.id,
            )
        )
    )
    assert update_count == 2
    assert remaining_ids == original_ids
    assert (
        db_session.scalar(
            select(Campaign.id).where(
                Campaign.tenant_id == admin.tenant_id,
                Campaign.key == "second-batch-target",
            )
        )
        is None
    )
