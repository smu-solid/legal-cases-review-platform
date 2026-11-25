"""Reviewer grouping bundle (reviewer-grouping-bundle/v1): structure, navigation, blinding."""

from __future__ import annotations

import hashlib
import uuid
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from review_platform.dataset.types import InputCandidate, InputCase, InputEvidence, InputField
from review_platform.db.session import Database
from review_platform.review.artifact_store import FilesystemArtifactStore
from review_platform.review.dataset_import import DatasetImportService
from review_platform.review.models import Campaign
from review_platform.settings import Settings
from tests.support.annotations import preferred_annotation
from tests.support.campaigns import add_review_user, claim_field, import_campaign
from tests.support.clients import authenticate, mutation_headers, open_clients
from tests.support.documents import FileDocuments
from tests.support.identities import AdminIdentity

_SAMPLE_A_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "fixtures"
    / "documents"
    / "sample_a_synthetic.html"
)

BLINDED_TOKENS = (
    "rationale",
    "supporting_quote",
    "verdict",
    "candidate",
    "model_kind",
    "model_name",
    "prompt_version",
    "deterministic",
    "supporting",
)


@pytest.mark.anyio
async def test_grouped_bundle_structure_navigation_and_blinding(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="grouping-reviewer@example.test", role="reviewer"
    )
    peer = add_review_user(
        database, settings, admin, email="grouping-peer@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client, peer_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(admin_client, admin)
        campaign_id = str(imported["campaign_id"])

        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        await authenticate(peer_client, peer)

        assignment_id = await claim_field(
            reviewer_client,
            reviewer_csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="grp-claim-citation-0001",
        )
        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        assert grouped.status_code == 200, grouped.text
        assert grouped.headers["cache-control"] == "no-store"
        body = grouped.json()

        # Schema + reviewer-safe case header.
        assert body["schema_version"] == "reviewer-grouping-bundle/v1"
        header = body["case_header"]
        assert header["subject_kind"] == "case"
        assert header["neutral_citation_display"] == "[2024] SGCA 1"
        assert header["campaign_name"] == "Synthetic Review"
        assert header["source_system"] in ("sample_a", "sample_b")

        assert len(body["field_groups"]) == 1
        group = body["field_groups"][0]
        assert group["group_id"] == "case_metadata"
        assert group["group_kind"] == "atomic"
        assert group["item_count"] == 1 and group["completed_count"] == 0
        item = group["items"][0]
        assert item["assignment_id"] == assignment_id
        assert item["item_kind"] == "citation"
        assert item["status"] == "not_started"
        assert item["extracted_value_display"] == "[2024] SGCA 1"

        # Progress reflects own work only.
        assert body["progress"] == {
            "total_items": 1,
            "completed_items": 0,
            "remaining_items": 1,
            "group_progress": [
                {"group_id": "case_metadata", "item_count": 1, "completed_count": 0}
            ],
        }
        assert body["allowed_actions"] == ["save_draft", "submit"]

        # Source render: safe text with anchors addressing the rendered content (not the absent
        # original-document offsets). Group + item anchors resolve into bounds.
        render = body["source_render"]
        assert render["render_mode"] == "safe_text"
        content = render["content"]
        anchors = {a["anchor_id"]: a for a in render["anchors"]}
        assert group["group_anchor_id"] in anchors
        item_anchor = anchors[item["source_anchor_id"]]
        assert item_anchor["review_unit_id"] == item["review_unit_id"]
        start, end = item_anchor["char_start"], item_anchor["char_end"]
        assert 0 <= start <= end <= len(content)
        # The slice the anchor points at is the evidence text the per-assignment bundle exposes.
        plain = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        snippet = plain.json()["evidence_windows"][0]["snippet"]
        assert content[start:end] == snippet

        # Reviewer blinding: no validator candidate / model / verdict surface leaks.
        raw = grouped.text.lower()
        for token in BLINDED_TOKENS:
            assert token not in raw, token
        # No raw source path or reserved synthetic URL crosses the boundary.
        assert ".invalid" not in grouped.text
        assert "source_url" not in grouped.text

        # Peer cannot read another reviewer's grouped bundle -> neutral not-found.
        peer_view = await peer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        assert peer_view.status_code == 404

        # Submitting the underlying per-unit assignment flips the item to completed.
        annotation = preferred_annotation(plain.json())
        submit = await reviewer_client.post(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/submit",
            json=annotation,
            headers={
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": "grp-submit-citation-0001",
                "If-Match": plain.headers["etag"],
            },
        )
        assert submit.status_code == 201, submit.text
        after = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        after_body = after.json()
        assert after_body["field_groups"][0]["items"][0]["status"] == "submitted"
        assert after_body["progress"]["completed_items"] == 1
        assert after_body["progress"]["remaining_items"] == 0
        assert after_body["allowed_actions"] == []


@pytest.mark.anyio
async def test_grouped_bundle_preserves_untrusted_source_text(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="grouping-xss@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, settings, 2)
        imported = await import_campaign(admin_client, admin)
        campaign_id = str(imported["campaign_id"])
        reviewer_csrf = await authenticate(reviewer_client, reviewer)

        assignment_id = await claim_field(
            reviewer_client,
            reviewer_csrf,
            tenant_id,
            campaign_id,
            "Subject",
            idem="grp-claim-subject-0001",
        )
        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        body = grouped.json()
        group = body["field_groups"][0]
        assert group["group_id"] == "case_metadata"
        # Untrusted source text is preserved verbatim for the client to render via text nodes; the
        # API neither executes nor strips it. An evidence with no original offsets still produces an
        # anchor because the render computes its own offsets.
        content = body["source_render"]["content"]
        assert "<script>alert('fixture')</script>" in content
        item = group["items"][0]
        assert item["source_anchor_id"] is not None


@pytest.mark.anyio
async def test_value_provenance_answer_flow_and_validation(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="vp-reviewer@example.test", role="reviewer"
    )
    peer = add_review_user(database, settings, admin, email="vp-peer@example.test", role="reviewer")
    tenant_id = str(admin.tenant_id)

    def answer_url(assignment_id: str, action: str) -> str:
        return f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/answer/{action}"

    def grouped_url(assignment_id: str) -> str:
        return f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"

    async with AsyncExitStack() as stack:
        admin_client, reviewer_client, peer_client = await open_clients(stack, settings, 3)
        imported = await import_campaign(admin_client, admin)
        campaign_id = str(imported["campaign_id"])
        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        await authenticate(peer_client, peer)

        assignment_id = await claim_field(
            reviewer_client,
            reviewer_csrf,
            tenant_id,
            campaign_id,
            "Citation Neutral",
            idem="vp-claim-0001",
        )
        bundle = (await reviewer_client.get(grouped_url(assignment_id))).json()
        lock = bundle["lock_version"]
        evidence_id = bundle["field_groups"][0]["items"][0]["evidence_window_ids"][0]

        def headers(idem: str, lock_version: int) -> dict[str, str]:
            return {
                **mutation_headers(reviewer_csrf),
                "Idempotency-Key": idem,
                "If-Match": f'"{lock_version}"',
            }

        # Evidence outside the assigned snapshot is rejected.
        bad_evidence = await reviewer_client.put(
            answer_url(assignment_id, "draft"),
            json={"value_correct": True, "evidence_ids": [str(uuid.uuid4())]},
            headers=headers("vp-baddraft-0001", lock),
        )
        assert bad_evidence.status_code == 422
        assert bad_evidence.json()["code"] == "evidence_references_invalid"

        # Duplicate evidence references are rejected.
        duplicate_evidence = await reviewer_client.put(
            answer_url(assignment_id, "draft"),
            json={"value_correct": True, "evidence_ids": [evidence_id, evidence_id]},
            headers=headers("vp-dupdraft-0001", lock),
        )
        assert duplicate_evidence.status_code == 422
        assert duplicate_evidence.json()["code"] == "evidence_references_invalid"

        bad_span = await reviewer_client.put(
            answer_url(assignment_id, "draft"),
            json={
                "value_correct": True,
                "corrected_provenance_spans": [
                    {"evidence_window_id": str(uuid.uuid4()), "char_start": 0, "char_end": 5}
                ],
            },
            headers=headers("vp-badspan-0001", lock),
        )
        assert bad_span.status_code == 422
        assert bad_span.json()["code"] == "corrected_provenance_spans_invalid"

        # Partial draft: value answered, provenance still null (no button selected yet).
        draft = await reviewer_client.put(
            answer_url(assignment_id, "draft"),
            json={
                "value_correct": True,
                "evidence_ids": [evidence_id],
                "corrected_provenance_spans": [
                    {"evidence_window_id": evidence_id, "char_start": 0, "char_end": 5}
                ],
            },
            headers=headers("vp-draft-0001", lock),
        )
        assert draft.status_code == 200, draft.text
        assert draft.json()["schema_version"] == "reviewer-item-answer/v1"
        assert draft.json()["value_correct"] is True
        assert draft.json()["provenance_correct"] is None
        assert draft.json()["corrected_provenance_spans"] == [
            {"evidence_window_id": evidence_id, "char_start": 0, "char_end": 5, "note": None}
        ]
        next_lock = int(draft.json()["lock_version"])

        # A corrected span contradicts an accepted provenance: the workspace hides the marking
        # control unless provenance_correct is NO, and the server enforces the same rule.
        accepted_with_span = await reviewer_client.put(
            answer_url(assignment_id, "draft"),
            json={
                "value_correct": True,
                "provenance_correct": True,
                "evidence_ids": [evidence_id],
                "corrected_provenance_spans": [
                    {"evidence_window_id": evidence_id, "char_start": 0, "char_end": 5}
                ],
            },
            headers=headers("vp-accepted-span-0001", next_lock),
        )
        assert accepted_with_span.status_code == 422
        assert accepted_with_span.json()["code"] == "corrected_provenance_spans_invalid"

        # Grouped bundle reflects the draft answer.
        after_draft = (await reviewer_client.get(grouped_url(assignment_id))).json()
        draft_item = after_draft["field_groups"][0]["items"][0]
        assert draft_item["status"] == "draft"
        assert draft_item["answer_summary"] == {
            "state": "draft",
            "value_correct": True,
            "provenance_correct": None,
            "corrected_value_display": None,
            "comment": None,
            "failure_reason": None,
            "corrected_provenance_spans": [
                {"evidence_window_id": evidence_id, "char_start": 0, "char_end": 5, "note": None}
            ],
        }

        # Submit guards: value/provenance must be explicit; an incorrect value needs a correction.
        missing_value = await reviewer_client.post(
            answer_url(assignment_id, "submit"),
            json={"provenance_correct": True, "evidence_ids": []},
            headers=headers("vp-badsubmit-0001", next_lock),
        )
        assert missing_value.status_code == 422
        assert missing_value.json()["code"] == "value_correctness_required"
        missing_provenance = await reviewer_client.post(
            answer_url(assignment_id, "submit"),
            json={"value_correct": True, "evidence_ids": []},
            headers=headers("vp-badsubmit-0003", next_lock),
        )
        assert missing_provenance.status_code == 422
        assert missing_provenance.json()["code"] == "provenance_correctness_required"
        no_correction = await reviewer_client.post(
            answer_url(assignment_id, "submit"),
            json={"value_correct": False, "provenance_correct": False, "evidence_ids": []},
            headers=headers("vp-badsubmit-0002", next_lock),
        )
        assert no_correction.status_code == 422
        assert no_correction.json()["code"] == "correction_or_comment_required"

        # Stale optimistic-concurrency token is rejected.
        stale = await reviewer_client.post(
            answer_url(assignment_id, "submit"),
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers=headers("vp-stale-0001", 1),
        )
        assert stale.status_code == 412

        # A peer cannot answer another reviewer's assignment.
        peer_submit = await peer_client.post(
            answer_url(assignment_id, "submit"),
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": []},
            headers={
                **mutation_headers(peer_client.cookies["__Host-review_csrf"]),
                "Idempotency-Key": "vp-peer-0001",
                "If-Match": f'"{next_lock}"',
            },
        )
        assert peer_submit.status_code == 404

        # Valid submit, then idempotent replay.
        submit = await reviewer_client.post(
            answer_url(assignment_id, "submit"),
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": [evidence_id]},
            headers=headers("vp-submit-0001", next_lock),
        )
        assert submit.status_code == 201, submit.text
        assert submit.json()["state"] == "submitted"
        replay = await reviewer_client.post(
            answer_url(assignment_id, "submit"),
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": [evidence_id]},
            headers=headers("vp-submit-0001", next_lock),
        )
        assert replay.status_code == 201
        assert replay.json()["replayed"] is True

        # A double-submit that races past the client's in-flight guard sends a *new* idempotency key
        # (and, having not refreshed, a now-stale If-Match). The reviewer already submitted this
        # field, so this must resolve to idempotent success returning the latest submitted state --
        # never a user-visible 409 assignment_not_editable or 412 stale conflict.
        resubmit_new_key = await reviewer_client.post(
            answer_url(assignment_id, "submit"),
            json={"value_correct": True, "provenance_correct": True, "evidence_ids": [evidence_id]},
            headers=headers("vp-resubmit-newkey-0001", 1),
        )
        assert resubmit_new_key.status_code == 201, resubmit_new_key.text
        assert resubmit_new_key.json()["replayed"] is True
        assert resubmit_new_key.json()["state"] == "submitted"

        # Grouped bundle now shows the item completed.
        final = (await reviewer_client.get(grouped_url(assignment_id))).json()
        final_item = final["field_groups"][0]["items"][0]
        assert final_item["status"] == "submitted"
        assert final_item["answer_summary"]["state"] == "submitted"
        assert final["progress"]["completed_items"] == 1
        assert final["allowed_actions"] == []

        # An incorrect value with a correction is accepted and recorded.
        other_id = await claim_field(
            reviewer_client,
            reviewer_csrf,
            tenant_id,
            campaign_id,
            "Subject",
            idem="vp-claim-0002",
        )
        other_lock = (await reviewer_client.get(grouped_url(other_id))).json()["lock_version"]
        corrected = await reviewer_client.post(
            answer_url(other_id, "submit"),
            json={
                "value_correct": False,
                "provenance_correct": False,
                "corrected_value_display": "Corrected subject",
                "comment": "The extracted subject is wrong.",
                "evidence_ids": [],
            },
            headers=headers("vp-corrected-0001", other_lock),
        )
        assert corrected.status_code == 201, corrected.text
        assert corrected.json()["value_correct"] is False
        corrected_bundle = (await reviewer_client.get(grouped_url(other_id))).json()
        assert corrected_bundle["field_groups"][0]["items"][0]["answer_summary"] == {
            "state": "submitted",
            "value_correct": False,
            "provenance_correct": False,
            "corrected_value_display": "Corrected subject",
            "comment": "The extracted subject is wrong.",
            "failure_reason": None,
            "corrected_provenance_spans": [],
        }


@pytest.mark.anyio
async def test_grouped_bundle_derives_citation_displays_from_real_imported_fields(
    settings: Settings,
    database: Database,
    db_session: Session,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    """Real-imported citation fields carry ``review_kind="metadata_field"`` (never the
    synthetic-     fixture-only ``"citation_link"``), and a metadata_field subject's own
    ``display_title`` defaults     to the case title, not the field's value. The case
    header's neutral/reported citation displays     must therefore be derived from each
    field's own extracted candidate value, keyed by field token,     or a real campaign's
    header falls back to showing the raw subject id (see grouped_bundle.py's
    ``_NEUTRAL_CITATION_FIELD_TOKEN``/``_REPORTED_CITATION_FIELD_TOKEN``)."""

    root, store_root = tmp_path / "raw", tmp_path / "store"
    root.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    raw = _SAMPLE_A_FIXTURE.read_bytes()
    (root / "case.html").write_bytes(raw)
    sha256 = hashlib.sha256(raw).hexdigest()

    def _field(name: str, value: str) -> InputField:
        return InputField(
            field_name=name,
            display_value=value,
            value_candidate=InputCandidate(
                source_kind="deterministic",
                verdict="supported",
                value=value,
                rationale="r",
                supporting_quote=None,
            ),
            model_candidate=None,
            evidence=[
                InputEvidence(
                    kind="quote",
                    snippet="first judgment paragraph BODYONE",
                    char_start=10,
                    char_end=20,
                    line_start=None,
                    line_end=None,
                    source_hash=sha256,
                )
            ],
        )

    case = InputCase(
        external_id="CAS-CITATION-TEST-1",
        source_system="sample_a",
        source_document_id="SRC-CITATION-TEST-1",
        sha256=sha256,
        title="AA v BB",
        fields=[
            _field("cases.citation_neutral", "[2018] SGHCF 99"),
            _field("cases.citation_reporter", "[2018] 3 rep 100"),
        ],
    )
    service = DatasetImportService(
        resolver=FileDocuments([root]),
        store=FilesystemArtifactStore(root=store_root),
        audit_key="k" * 32,
    )
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-citation-test",
        campaign_name="Real Citation Test",
        source_system="sample_a",
        cases=[case],
    )
    campaign_row = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id, Campaign.key == "real-citation-test"
        )
    )
    assert campaign_row is not None
    campaign_row.status = "published"
    db_session.flush()
    db_session.commit()

    reviewer = add_review_user(
        database, settings, admin, email="real-citation-reviewer@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        (reviewer_client,) = await open_clients(stack, settings, 1)
        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        campaign_id = str(campaign_row.id)

        neutral_assignment = await claim_field(
            reviewer_client,
            reviewer_csrf,
            tenant_id,
            campaign_id,
            "Neutral citation",
            idem="real-citation-claim-0001",
        )
        reporter_assignment = await claim_field(
            reviewer_client,
            reviewer_csrf,
            tenant_id,
            campaign_id,
            "Reported citation",
            idem="real-citation-claim-0002",
        )

        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{neutral_assignment}/grouped-bundle"
        )
        assert grouped.status_code == 200, grouped.text
        header = grouped.json()["case_header"]
        # Not the raw case title ("AA v BB") and not the raw subject id -- the field's own value.
        assert header["neutral_citation_display"] == "[2018] SGHCF 99"
        assert header["reported_citation_display"] == "[2018] 3 rep 100"

        # Same citation displays, reached from the reporter-field assignment too -- each field has
        # its own ReviewSubject (subject_id/case_identifier_display legitimately differ per
        # assignment; only the derived citation displays are shared case-level facts).
        reporter_header = (
            await reviewer_client.get(
                f"/api/v1/tenants/{tenant_id}/review/assignments/{reporter_assignment}/grouped-bundle"
            )
        ).json()["case_header"]
        assert reporter_header["neutral_citation_display"] == header["neutral_citation_display"]
        assert reporter_header["reported_citation_display"] == header["reported_citation_display"]


@pytest.mark.anyio
async def test_grouped_bundle_renders_full_source_document_for_real_imports(
    settings: Settings,
    database: Database,
    db_session: Session,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    """A real-imported case's ``source_render.content`` must be the case's full document text, not
    just the claimed field's own evidence snippet -- and the field's anchor must be its own
    evidence window's import-time offsets (no fresh string search here; see grouped_bundle.py's
    ``_build_source_render_from_full_text``)."""

    root, store_root = tmp_path / "raw", tmp_path / "store"
    root.mkdir(parents=True, exist_ok=True)
    store_root.mkdir(parents=True, exist_ok=True)
    raw = _SAMPLE_A_FIXTURE.read_bytes()
    (root / "case.html").write_bytes(raw)
    sha256 = hashlib.sha256(raw).hexdigest()

    snippet = "second judgment paragraph BODYTWO"
    case = InputCase(
        external_id="CAS-FULLDOC-TEST-1",
        source_system="sample_a",
        source_document_id="SRC-FULLDOC-TEST-1",
        sha256=sha256,
        title="AA v BB",
        fields=[
            InputField(
                field_name="cases.subject",
                display_value="AA v BB",
                value_candidate=InputCandidate(
                    source_kind="deterministic",
                    verdict="supported",
                    value="AA v BB",
                    rationale="r",
                    supporting_quote=None,
                ),
                model_candidate=None,
                evidence=[
                    InputEvidence(
                        kind="quote",
                        snippet=snippet,
                        char_start=None,
                        char_end=None,
                        line_start=None,
                        line_end=None,
                        source_hash=sha256,
                    )
                ],
            )
        ],
    )
    service = DatasetImportService(
        resolver=FileDocuments([root]),
        store=FilesystemArtifactStore(root=store_root),
        audit_key="k" * 32,
    )
    service.import_cases(
        db_session,
        tenant_id=admin.tenant_id,
        created_by=admin.user_id,
        campaign_key="real-fulldoc-test",
        campaign_name="Real Full Document Test",
        source_system="sample_a",
        cases=[case],
    )
    campaign_row = db_session.scalar(
        select(Campaign).where(
            Campaign.tenant_id == admin.tenant_id, Campaign.key == "real-fulldoc-test"
        )
    )
    assert campaign_row is not None
    campaign_row.status = "published"
    db_session.flush()
    db_session.commit()

    reviewer = add_review_user(
        database, settings, admin, email="real-fulldoc-reviewer@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    # The app's own artifact store must resolve the same object store DatasetImportService
    # just wrote
    # the artifact into -- import above happened out-of-band via a directly-constructed store, not
    # through the running app.
    scoped_settings = settings.model_copy(
        update={
            "source_render_storage_mode": "filesystem",
            "source_render_artifact_root": store_root,
        }
    )
    async with AsyncExitStack() as stack:
        (reviewer_client,) = await open_clients(stack, scoped_settings, 1)
        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        campaign_id = str(campaign_row.id)

        assignment_id = await claim_field(
            reviewer_client,
            reviewer_csrf,
            tenant_id,
            campaign_id,
            "Subject matter",
            idem="real-fulldoc-claim-0001",
        )
        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        assert grouped.status_code == 200, grouped.text
        body = grouped.json()

        render = body["source_render"]
        assert render["render_mode"] == "safe_text"
        content = render["content"]
        # The full document, not just the claimed field's own evidence snippet: paragraphs the
        # claimed field's evidence never mentions must still be present.
        assert "AA v BB" in content
        assert "BODYONE" in content
        assert "BODYTWO" in content
        assert "Example Act section 3" in content
        assert content != snippet

        item = body["field_groups"][0]["items"][0]
        assert item["item_label"] == "Subject matter"
        assert item["source_anchor_id"] is not None
        assert item["source_anchor_unavailable_reason"] is None
        anchor = {a["anchor_id"]: a for a in render["anchors"]}[item["source_anchor_id"]]
        start, end = anchor["char_start"], anchor["char_end"]
        # The anchor addresses this exact rendered content -- not the passed-in (unrelated,
        # pre-render) InputEvidence.char_start/char_end -- via the evidence window's own
        # import-time re-anchor, never a fresh search here.
        assert content[start:end] == snippet
