"""Assignment-scoped source-render artifact API: authorization, blinding, sandbox, integrity."""

from __future__ import annotations

import uuid
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from sqlalchemy import select

from review_platform.db.session import Database
from review_platform.review.artifact_store import FilesystemArtifactStore
from review_platform.review.models import ReviewSubject, SourceRenderArtifact
from review_platform.review.source_render import render_source_document
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, claim_field, import_campaign
from tests.support.clients import authenticate, open_clients
from tests.support.identities import AdminIdentity

# A tiny untrusted Sample B-shaped document: one script (must be stripped), one external link
# (must go inert), one internal anchor link, and two anchorable blocks.
_RAW_HTML = (
    "<html><body>"
    '<h1 id="para-1">Judgment of the Court</h1>'
    '<p id="para-2">The appeal is dismissed.'
    ' <a href="https://evil.example/x">external</a>'
    "<script>alert('xss')</script></p>"
    '<p>See <a href="#para-1">the holding</a> above.</p>'
    "</body></html>"
)

# Tokens that must never cross the reviewer boundary in source-render payloads.
_FORBIDDEN_TOKENS = ("object_key", "storage", "source_path", "created_by_job", "evil.example")


def _storage_settings(settings: Settings, root: Path) -> Settings:
    return settings.model_copy(
        update={
            "source_render_storage_mode": "filesystem",
            "source_render_artifact_root": root,
        }
    )


def _seed_artifacts(
    database: Database, tenant_id: uuid.UUID, root: Path, *, source_system: str = "sample_b"
) -> set[str]:
    """Render the sample doc and seed one current artifact per source snapshot.

    The synthetic fixture spreads its review units across several case subjects, so every subject's
    snapshot is given an artifact; the claimed assignment then always resolves one. Returns the set
    of seeded artifact ids.
    """

    artifact = render_source_document(source_system=source_system, raw_html=_RAW_HTML)
    store = FilesystemArtifactStore(root=root)
    ids: set[str] = set()
    with database.session() as session, session.begin():
        subjects = session.scalars(
            select(ReviewSubject).where(ReviewSubject.tenant_id == tenant_id)
        ).all()
        for subject in subjects:
            object_key = uuid.uuid4().hex
            store.write_artifact(
                object_key,
                body=artifact.safe_html.encode("utf-8"),
                anchor_map=artifact.anchor_map_json.encode("utf-8"),
            )
            row = SourceRenderArtifact(
                tenant_id=tenant_id,
                source_snapshot_id=subject.source_snapshot_id,
                subject_kind=subject.subject_kind,
                source_system=source_system,
                source_kind="judgment",
                render_profile=artifact.render_profile,
                render_version=artifact.render_version,
                render_mode="sanitized_html",
                content_digest=artifact.content_digest,
                anchor_map_digest=artifact.anchor_map_digest,
                object_key=object_key,
                artifact_mime_type=artifact.mime_type,
                artifact_size_bytes=artifact.size_bytes,
                is_current=True,
                created_by_job="test-seed",
            )
            session.add(row)
            session.flush()
            ids.add(str(row.id))
    return ids


@pytest.mark.anyio
async def test_source_render_metadata_body_anchors_and_sandbox(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    scoped = _storage_settings(settings, tmp_path)
    reviewer = add_review_user(
        database, settings, admin, email="sr-reviewer@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, scoped, 2)
        imported = await import_campaign(admin_client, admin)
        campaign_id = str(imported["campaign_id"])
        artifact_ids = _seed_artifacts(database, admin.tenant_id, tmp_path)

        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        assignment_id = await claim_field(
            reviewer_client, reviewer_csrf, tenant_id, campaign_id, "Subject", idem="sr-claim-0001"
        )
        base = f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render"

        # Metadata: reviewer-safe, sanitized_html, same-origin URLs, no forbidden fields.
        meta = await reviewer_client.get(base)
        assert meta.status_code == 200, meta.text
        assert meta.headers["cache-control"] == "no-store"
        body = meta.json()
        assert body["render_artifact_id"] in artifact_ids
        assert body["render_mode"] == "sanitized_html"
        assert body["render_profile"] == "generic_document"
        assert len(body["content_digest"]) == 64
        assert body["body_url"] == f"{base}/body"
        assert body["anchor_map_url"] == f"{base}/anchors"
        for token in _FORBIDDEN_TOKENS:
            assert token not in meta.text, token

        # Body: sanitized HTML, sandbox CSP, same-origin frame, no script/external surface.
        render = await reviewer_client.get(f"{base}/body")
        assert render.status_code == 200, render.text
        assert render.headers["content-type"].startswith("text/html")
        assert render.headers["cache-control"] == "no-store"
        assert render.headers["x-content-type-options"] == "nosniff"
        assert render.headers["x-frame-options"] == "SAMEORIGIN"
        csp = render.headers["content-security-policy"]
        assert "sandbox" in csp and "style-src 'unsafe-inline'" in csp
        html = render.text
        assert "Judgment of the Court" in html
        assert "<script" not in html.lower()
        assert "alert('xss')" not in html
        assert "evil.example" not in html
        assert "https://" not in html  # external links inert; wrapper loads no off-origin asset

        # Anchors: offset-only anchor map, no snippet text or forbidden fields.
        anchors = await reviewer_client.get(f"{base}/anchors")
        assert anchors.status_code == 200, anchors.text
        anchor_body = anchors.json()
        assert anchor_body["render_artifact_id"] == body["render_artifact_id"]
        assert anchor_body["anchors"], "expected at least one anchor"
        for anchor in anchor_body["anchors"]:
            assert set(anchor) <= {"anchor_id", "char_start", "char_end", "label"}
        for token in _FORBIDDEN_TOKENS:
            assert token not in anchors.text, token


@pytest.mark.anyio
async def test_source_render_denies_peer_wrong_tenant_and_missing(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    scoped = _storage_settings(settings, tmp_path)
    reviewer = add_review_user(
        database, settings, admin, email="sr-owner@example.test", role="reviewer"
    )
    peer = add_review_user(database, settings, admin, email="sr-peer@example.test", role="reviewer")
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client, peer_client = await open_clients(stack, scoped, 3)
        imported = await import_campaign(admin_client, admin)
        campaign_id = str(imported["campaign_id"])
        _seed_artifacts(database, admin.tenant_id, tmp_path)

        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        await authenticate(peer_client, peer)
        assignment_id = await claim_field(
            reviewer_client, reviewer_csrf, tenant_id, campaign_id, "Subject", idem="sr-own-0001"
        )
        base = f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render"

        # A peer cannot read another reviewer's source render -> generic 404 on every sub-path.
        for suffix in ("", "/body", "/anchors"):
            peer_view = await peer_client.get(f"{base}{suffix}")
            assert peer_view.status_code == 404, suffix

        # A tenant where the reviewer holds no role is denied by the role gate (like every reviewer
        # route) before any assignment lookup, so it never reveals whether the assignment exists.
        other_tenant = uuid.uuid4()
        wrong = await reviewer_client.get(
            f"/api/v1/tenants/{other_tenant}/review/assignments/{assignment_id}/source-render"
        )
        assert wrong.status_code == 403

        # An unknown assignment -> 404.
        missing = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{uuid.uuid4()}/source-render"
        )
        assert missing.status_code == 404


@pytest.mark.anyio
async def test_source_render_missing_artifact_is_not_found(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
    tmp_path: Path,
) -> None:
    # Storage is configured, but no artifact row is seeded for the subject.
    scoped = _storage_settings(settings, tmp_path)
    reviewer = add_review_user(
        database, settings, admin, email="sr-noartifact@example.test", role="reviewer"
    )
    tenant_id = str(admin.tenant_id)
    async with AsyncExitStack() as stack:
        admin_client, reviewer_client = await open_clients(stack, scoped, 2)
        imported = await import_campaign(admin_client, admin)
        campaign_id = str(imported["campaign_id"])
        reviewer_csrf = await authenticate(reviewer_client, reviewer)
        assignment_id = await claim_field(
            reviewer_client, reviewer_csrf, tenant_id, campaign_id, "Subject", idem="sr-none-0001"
        )
        base = f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/source-render"
        for suffix in ("", "/body", "/anchors"):
            response = await reviewer_client.get(f"{base}{suffix}")
            assert response.status_code == 404, suffix
