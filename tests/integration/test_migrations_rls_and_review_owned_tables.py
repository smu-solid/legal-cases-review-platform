from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from review_platform.bootstrap import BootstrapRefusedError, bootstrap_first_superuser
from review_platform.db.models import Tenant
from review_platform.db.session import MIGRATION_HEAD, Database, DatabaseUnavailableError
from review_platform.review.models import (
    AllocationRun,
    AllocationRunReviewer,
    AllocationRunSubject,
    Assignment,
    AssignmentPlan,
    Campaign,
    CampaignSubject,
    CaseSubmission,
    ReviewerPool,
    ReviewerPoolMember,
    ReviewSubject,
    ReviewUnit,
    SourceRenderArtifact,
    SourceSnapshot,
)
from review_platform.settings import Settings
from tests.support.identities import TEST_PASSWORD, AdminIdentity


def test_bootstrap_is_one_time(
    database: Database, settings: Settings, admin: AdminIdentity
) -> None:
    assert admin.user_id
    with pytest.raises(BootstrapRefusedError), database.session() as session, session.begin():
        bootstrap_first_superuser(
            session,
            settings=settings,
            email="second@example.test",
            display_name="Second",
            password=TEST_PASSWORD,
            tenant_key="other",
            tenant_name="Other",
        )


def test_audit_rows_reject_update_and_delete(db_session: Session, admin: AdminIdentity) -> None:
    assert admin.user_id
    event_id = db_session.scalar(text("SELECT id FROM review_platform.audit_events LIMIT 1"))
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text("UPDATE review_platform.audit_events SET event_type='tampered' WHERE id=:id"),
            {"id": event_id},
        )
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text("DELETE FROM review_platform.audit_events WHERE id=:id"), {"id": event_id}
        )


def test_published_campaign_trigger_allows_only_editor_managed_policy_keys(
    db_session: Session, admin: AdminIdentity
) -> None:
    campaign = Campaign(
        tenant_id=admin.tenant_id,
        key="published-editor-policy-guard",
        name="Published editor policy guard",
        status="published",
        policy_json={"minimum_reviews_per_case": 2, "allocation_seed": "fixed"},
        manifest_digest="e" * 64,
        created_by=admin.user_id,
    )
    db_session.add(campaign)
    db_session.flush()

    # A published campaign may be renamed while its review count remains frozen.
    db_session.execute(
        text("UPDATE review_platform.campaigns SET name=:name WHERE id=:id"),
        {"id": campaign.id, "name": "Published editor policy guard renamed"},
    )

    # Unrelated allocation policy remains frozen after publication.
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text(
                "UPDATE review_platform.campaigns "
                "SET policy_json=jsonb_set(policy_json, '{allocation_seed}', "
                "'\"tampered\"'::jsonb) WHERE id=:id"
            ),
            {"id": campaign.id},
        )


def test_review_schema_has_separate_history_and_no_catalog_objects(db_session: Session) -> None:
    revision = db_session.scalar(
        text("SELECT version_num FROM review_platform.review_platform_alembic_version")
    )
    assert revision == MIGRATION_HEAD
    assignment_plan_indexes = set(
        db_session.scalars(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname='review_platform' AND tablename='assignment_plans'"
            )
        )
    )
    assert "ix_assignment_plan_assignment" in assignment_plan_indexes
    tables = set(
        db_session.scalars(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='review_platform'"
            )
        )
    )
    assert {
        "users",
        "tenants",
        "tenant_memberships",
        "user_activation_challenges",
        "password_reset_challenges",
        "role_grants",
        "global_role_grants",
        "sessions",
        "auth_rate_limits",
        "audit_events",
        "review_platform_alembic_version",
        "campaigns",
        "source_snapshots",
        "review_subjects",
        "review_units",
        "candidates",
        "evidence_windows",
        "source_render_artifacts",
        "assignments",
        "annotation_revisions",
        "review_item_answers",
        "adjudications",
        "adjudication_decisions",
        "adjudication_drafts",
        "adjudication_participations",
        "idempotency_records",
        "reviewer_pools",
        "reviewer_pool_members",
        "campaign_subjects",
        "allocation_runs",
        "allocation_run_subjects",
        "allocation_run_reviewers",
        "assignment_plans",
        "incremental_movement_plans",
        "case_submissions",
        "reviewer_added_proposals",
        "proposal_adjudication_items",
    } <= tables
    decision_columns = set(
        db_session.scalars(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='review_platform' "
                "AND table_name='adjudication_decisions'"
            )
        )
    )
    assert "corrected_provenance_spans_json" in decision_columns
    assert not any("catalog" in table for table in tables)
    assert uuid.UUID(str(admin_id := uuid.uuid4())) == admin_id


def test_review_tables_force_tenant_rls(database: Database, admin: AdminIdentity) -> None:
    role_name = f"review_rls_probe_{uuid.uuid4().hex}"
    with database.session() as session, session.begin():
        other_tenant = Tenant(key="rls-other", name="RLS Other")
        session.add(other_tenant)
        session.flush()
        session.add_all(
            [
                Campaign(
                    tenant_id=admin.tenant_id,
                    key="rls-primary",
                    name="RLS Primary",
                    policy_json={"required_reviews": 2, "blocked_units": 0},
                    manifest_digest="1" * 64,
                    created_by=admin.user_id,
                ),
                Campaign(
                    tenant_id=other_tenant.id,
                    key="rls-other",
                    name="RLS Other",
                    policy_json={"required_reviews": 2, "blocked_units": 0},
                    manifest_digest="2" * 64,
                    created_by=admin.user_id,
                ),
            ]
        )
        session.flush()
        rls_tables = set(
            session.scalars(
                text(
                    "SELECT relname FROM pg_class "
                    "WHERE relnamespace='review_platform'::regnamespace "
                    "AND relrowsecurity AND relforcerowsecurity"
                )
            )
        )
        assert {
            "campaigns",
            "source_snapshots",
            "review_subjects",
            "review_units",
            "candidates",
            "evidence_windows",
            "source_render_artifacts",
            "assignments",
            "annotation_revisions",
            "review_item_answers",
            "adjudications",
            "adjudication_decisions",
            "adjudication_drafts",
            "adjudication_participations",
            "idempotency_records",
            "reviewer_pools",
            "reviewer_pool_members",
            "campaign_subjects",
            "allocation_runs",
            "allocation_run_subjects",
            "allocation_run_reviewers",
            "assignment_plans",
            "incremental_movement_plans",
            "case_submissions",
            "reviewer_added_proposals",
            "proposal_adjudication_items",
        } <= rls_tables
        policy_count = session.scalar(
            text(
                "SELECT count(*) FROM pg_policies "
                "WHERE schemaname='review_platform' AND policyname='tenant_isolation'"
            )
        )
        assert policy_count == len(rls_tables)
        session.execute(text(f'CREATE ROLE "{role_name}" NOLOGIN'))
        session.execute(text(f'GRANT USAGE ON SCHEMA review_platform TO "{role_name}"'))
        session.execute(text(f'GRANT SELECT ON review_platform.campaigns TO "{role_name}"'))
        session.execute(text(f'SET LOCAL ROLE "{role_name}"'))
        assert session.scalar(text("SELECT count(*) FROM review_platform.campaigns")) == 0
        session.execute(
            text("SELECT set_config('review_platform.tenant_id', :tenant_id, true)"),
            {"tenant_id": str(admin.tenant_id)},
        )
        assert session.scalar(text("SELECT count(*) FROM review_platform.campaigns")) == 1
        session.execute(text("RESET ROLE"))
        session.execute(text(f'REVOKE SELECT ON review_platform.campaigns FROM "{role_name}"'))
        session.execute(text(f'REVOKE USAGE ON SCHEMA review_platform FROM "{role_name}"'))
        session.execute(text(f'DROP ROLE "{role_name}"'))


def test_allocation_persistence_is_review_owned_and_blinded(
    db_session: Session, admin: AdminIdentity
) -> None:
    source_snapshot = SourceSnapshot(
        tenant_id=admin.tenant_id,
        contract_version="review-dataset-snapshot/v1",
        source_mode="synthetic",
        source_version="allocation-test",
        external_item_key="case-1",
        input_digest="a" * 64,
    )
    db_session.add(source_snapshot)
    db_session.flush()
    subject = ReviewSubject(
        tenant_id=admin.tenant_id,
        source_snapshot_id=source_snapshot.id,
        subject_kind="case",
        external_subject_id="opaque-case-1",
        display_title="Case 1",
        display_subtitle=None,
        source_version="allocation-test",
        primary_source_ref="snapshot-ref",
        attributes_json={"citation_count": 12},
    )
    campaign = Campaign(
        tenant_id=admin.tenant_id,
        key="allocation-schema",
        name="Allocation Schema",
        status="draft",
        subject_kind="case",
        review_kind="metadata_field",
        source_snapshot_id=source_snapshot.id,
        allocation_policy_version="reviewer-allocation/v1",
        policy_version="allocation-v1",
        policy_json={"required_reviews": 2},
        manifest_digest="b" * 64,
        created_by=admin.user_id,
    )
    db_session.add_all([subject, campaign])
    db_session.flush()
    review_unit = ReviewUnit(
        tenant_id=admin.tenant_id,
        campaign_id=campaign.id,
        review_subject_id=subject.id,
        review_kind="metadata_field",
        question="Which value is supported?",
        safe_field_label="Decision date",
        required_reviews=2,
        input_digest="c" * 64,
    )
    pool = ReviewerPool(
        tenant_id=admin.tenant_id,
        campaign_id=campaign.id,
        name="Initial pool",
        status="active",
        eligibility_policy_version="pool/v1",
        exclusions_json={},
        pool_digest="d" * 64,
        created_by=admin.user_id,
    )
    db_session.add_all([review_unit, pool])
    db_session.flush()
    db_session.add(
        ReviewerPoolMember(
            tenant_id=admin.tenant_id,
            reviewer_pool_id=pool.id,
            reviewer_id=admin.user_id,
            eligibility_status="eligible",
        )
    )
    db_session.add(
        CampaignSubject(
            tenant_id=admin.tenant_id,
            campaign_id=campaign.id,
            review_subject_id=subject.id,
            subject_kind="case",
            review_kind="metadata_field",
            eligibility_status="eligible",
            metrics_json={"incoming_citation_count": 12},
            hub_score=120,
            selection_rank=1,
        )
    )
    allocation_run = AllocationRun(
        tenant_id=admin.tenant_id,
        campaign_id=campaign.id,
        reviewer_pool_id=pool.id,
        run_key="seeded-preview",
        status="planned",
        allocation_policy_version="reviewer-allocation/v1",
        planner_version="planner/v1",
        source_snapshot_id=source_snapshot.id,
        source_snapshot_digest="e" * 64,
        pool_digest="d" * 64,
        random_seed="seed-1",
        input_parameters_json={"target_distinct_subjects": 500},
        metric_weights_json={"incoming_citation_count": 1.0},
        feasibility_status="feasible_with_warnings",
        feasibility_report_json={"warnings": ["synthetic"]},
        summary_json={"pairwise_overlap_matrix": {"hidden_from_reviewers": True}},
        created_by=admin.user_id,
    )
    db_session.add(allocation_run)
    db_session.flush()
    db_session.add_all(
        [
            AllocationRunSubject(
                tenant_id=admin.tenant_id,
                allocation_run_id=allocation_run.id,
                review_subject_id=subject.id,
                selection_layer="global_hub",
                overlap_group_key="hub",
                window_index=0,
                metrics_json={"hub_score": 120},
            ),
            AllocationRunReviewer(
                tenant_id=admin.tenant_id,
                allocation_run_id=allocation_run.id,
                reviewer_id=admin.user_id,
                planned_assignment_count=1,
                unique_assignment_count=0,
                pairwise_overlap_count=0,
                global_overlap_count=1,
                workload_json={"visible_to_reviewer": False},
            ),
            AssignmentPlan(
                tenant_id=admin.tenant_id,
                allocation_run_id=allocation_run.id,
                review_unit_id=review_unit.id,
                reviewer_id=admin.user_id,
                status="planned",
                selection_layer="global_hub",
                overlap_group_key="hub",
                window_index=0,
                plan_metadata_json={"blinded": True},
            ),
        ]
    )
    db_session.flush()

    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.add(
            AssignmentPlan(
                tenant_id=admin.tenant_id,
                allocation_run_id=allocation_run.id,
                review_unit_id=review_unit.id,
                reviewer_id=admin.user_id,
                status="planned",
                selection_layer="global_hub",
                plan_metadata_json={},
            )
        )
        db_session.flush()

    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text("DELETE FROM review_platform.campaigns WHERE id=:id"),
            {"id": campaign.id},
        )


def test_source_render_artifacts_reject_update_but_allow_retirement(
    db_session: Session, admin: AdminIdentity
) -> None:
    """The derived artifact metadata table rejects UPDATE but permits retirement by DELETE."""

    snapshot = SourceSnapshot(
        tenant_id=admin.tenant_id,
        contract_version="review-dataset-snapshot/v1",
        source_mode="synthetic",
        source_version="render-test",
        external_item_key="render-case-1",
        input_digest="a" * 64,
    )
    db_session.add(snapshot)
    db_session.flush()
    artifact = SourceRenderArtifact(
        tenant_id=admin.tenant_id,
        source_snapshot_id=snapshot.id,
        subject_kind="case",
        source_system="sample_b",
        source_kind="judgment",
        render_profile="sample_b_wrapped",
        render_version=1,
        render_mode="sanitized_html",
        content_digest="b" * 64,
        anchor_map_digest="c" * 64,
        object_key="deadbeef",
        artifact_mime_type="text/html",
        artifact_size_bytes=42,
        is_current=True,
        created_by_job="test-seed",
    )
    db_session.add(artifact)
    db_session.flush()

    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text(
                "UPDATE review_platform.source_render_artifacts SET content_digest=:d WHERE id=:id"
            ),
            {"d": "d" * 64, "id": artifact.id},
        )
    # An artifact is a derived render of an immutable
    # snapshot, not reviewer work, and it has to cascade away when a case-pool refresh retires the
    # generation it belongs to. Its content can always be re-rendered from the snapshot; what must
    # never happen -- an artifact CHANGING under a reviewer who was shown it -- is still blocked
    # by the UPDATE branch above.
    with db_session.begin_nested():
        db_session.execute(
            text("DELETE FROM review_platform.source_render_artifacts WHERE id=:id"),
            {"id": artifact.id},
        )


def test_a_unit_is_deletable_only_while_no_reviewer_holds_it(
    db_session: Session, admin: AdminIdentity
) -> None:
    """The case-pool refresh replaces a superseded generation by deleting it .

    ``protect_review_unit_input`` permits that DELETE only for an unassigned unit. This is
    the     database-level backstop for the check ``DatasetImportService`` already makes in
    Python: whatever     code path reaches a unit, one a reviewer has been served can never
    be destroyed under them."""

    snapshot = SourceSnapshot(
        tenant_id=admin.tenant_id,
        contract_version="review-dataset-snapshot/v1",
        source_mode="synthetic",
        source_version="delete-guard-test",
        external_item_key="delete-guard-case-1",
        input_digest="a" * 64,
    )
    db_session.add(snapshot)
    db_session.flush()
    subject = ReviewSubject(
        tenant_id=admin.tenant_id,
        source_snapshot_id=snapshot.id,
        subject_kind="case",
        external_subject_id="opaque-delete-guard-1",
        display_title="Case 1",
        display_subtitle=None,
        source_version="delete-guard-test",
        primary_source_ref="snapshot-ref",
        attributes_json={},
    )
    campaign = Campaign(
        tenant_id=admin.tenant_id,
        key="delete-guard",
        name="Delete Guard",
        status="draft",
        subject_kind="case",
        review_kind="metadata_field",
        source_snapshot_id=snapshot.id,
        allocation_policy_version="reviewer-allocation/v1",
        policy_version="delete-guard-v1",
        policy_json={"required_reviews": 2},
        manifest_digest="b" * 64,
        created_by=admin.user_id,
    )
    db_session.add_all([subject, campaign])
    db_session.flush()

    def _unit(label: str) -> ReviewUnit:
        unit = ReviewUnit(
            tenant_id=admin.tenant_id,
            campaign_id=campaign.id,
            review_subject_id=subject.id,
            review_kind=label,
            question="Which value is supported?",
            safe_field_label="Decision date",
            required_reviews=2,
            input_digest="c" * 64,
        )
        db_session.add(unit)
        db_session.flush()
        return unit

    held = _unit("metadata_field")
    db_session.add(
        Assignment(
            tenant_id=admin.tenant_id,
            review_unit_id=held.id,
            reviewer_id=admin.user_id,
            status="claimed",
            lease_expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        )
    )
    db_session.flush()
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text("DELETE FROM review_platform.review_units WHERE id=:id"), {"id": held.id}
        )

    free = _unit("relation_citation")
    with db_session.begin_nested():
        db_session.execute(
            text("DELETE FROM review_platform.review_units WHERE id=:id"), {"id": free.id}
        )


def test_case_submissions_are_append_only(db_session: Session, admin: AdminIdentity) -> None:
    """A reviewer's case-submit confirmation rejects UPDATE and DELETE (no "undo")."""

    campaign = Campaign(
        tenant_id=admin.tenant_id,
        key="case-submission-immutability-test",
        name="Case submission immutability test",
        status="published",
        policy_json={},
        manifest_digest="test-manifest-digest",
        created_by=admin.user_id,
    )
    db_session.add(campaign)
    db_session.flush()
    submission = CaseSubmission(
        tenant_id=admin.tenant_id,
        campaign_id=campaign.id,
        case_id="CASE000000000001",
        reviewer_id=admin.user_id,
    )
    db_session.add(submission)
    db_session.flush()

    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text("UPDATE review_platform.case_submissions SET case_id=:c WHERE id=:id"),
            {"c": "CASE000000000002", "id": submission.id},
        )
    with pytest.raises(DBAPIError), db_session.begin_nested():
        db_session.execute(
            text("DELETE FROM review_platform.case_submissions WHERE id=:id"),
            {"id": submission.id},
        )


def test_populated_database_downgrade_is_refused(admin: AdminIdentity) -> None:
    assert admin.user_id
    with pytest.raises(DBAPIError, match="refusing to downgrade"):
        command.downgrade(Config("alembic.ini"), "base")


def test_database_unavailable_and_revision_checks(database: Database) -> None:
    unavailable = Database(None)
    assert not unavailable.check()
    unavailable.dispose()
    with pytest.raises(DatabaseUnavailableError), unavailable.session():
        pass

    assert database.engine is not None
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE review_platform.review_platform_alembic_version "
                "SET version_num='wrong_revision'"
            )
        )
    assert not database.check()
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE review_platform.review_platform_alembic_version "
                "SET version_num=:version_num"
            ),
            {"version_num": MIGRATION_HEAD},
        )
    assert database.check()

    class BrokenEngine:
        def connect(self) -> object:
            raise RuntimeError("unavailable")

    unavailable.engine = BrokenEngine()  # type: ignore[assignment]
    assert not unavailable.check()


def test_empty_schema_round_trip_preserves_readiness(database: Database) -> None:
    config = Config("alembic.ini")
    try:
        command.downgrade(config, "base")
        assert not database.check()
    finally:
        command.upgrade(config, "head")
    assert database.check()


def test_initial_schema_matches_application_metadata(database: Database) -> None:
    assert database.check()
    command.check(Config("alembic.ini"))
