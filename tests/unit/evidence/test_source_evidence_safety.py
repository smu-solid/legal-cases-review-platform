"""These exercise the live reviewer bundle endpoints. Deterministic truncation/budget arithmetic is
covered separately by ``test_source_safety``; here we prove the API honours the bounds end to end,
never caches source/evidence, keeps the safe-text render verbatim, and leaks no filesystem path,
URL, or snapshot-local identifier across either bundle."""

from __future__ import annotations

from contextlib import AsyncExitStack

import pytest

from review_platform.db.session import Database
from review_platform.review import grouped_source_text, source_safety
from review_platform.review.source_safety import TRUNCATION_MARKER
from review_platform.settings import Settings
from tests.support.campaigns import add_review_user, claim_field, import_campaign
from tests.support.clients import authenticate, open_clients
from tests.support.identities import AdminIdentity

LEAK_TOKENS = (
    "snapshot_local",
    "://",
    "/Users/",
    "/var/",
    "file:",
    "../",
    ".invalid",
    "source_url",
)


def _assert_no_path_or_url_leak(payload: str) -> None:
    lowered = payload.lower()
    for token in LEAK_TOKENS:
        assert token.lower() not in lowered, token


@pytest.mark.anyio
async def test_bundle_endpoints_are_never_cached_and_leak_no_paths(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
) -> None:
    reviewer = add_review_user(
        database, settings, admin, email="safety-cache@example.test", role="reviewer"
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
            "Citation Neutral",
            idem="safety-cache-0001",
        )

        flat = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        assert flat.status_code == 200 and grouped.status_code == 200, grouped.text

        # Source/evidence is never cached: both bundle responses are no-store.
        assert flat.headers["cache-control"] == "no-store"
        assert grouped.headers["cache-control"] == "no-store"

        # Safe-text render mode is the only mode emitted; the client renders content as text.
        assert grouped.json()["source_render"]["render_mode"] == "safe_text"

        # No raw path, URL, or snapshot-local identifier leaks through either bundle.
        _assert_no_path_or_url_leak(flat.text)
        _assert_no_path_or_url_leak(grouped.text)


@pytest.mark.anyio
async def test_large_source_is_clamped_and_bounded_with_marker(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Drive the real synthetic snippets past the limits by lowering them, rather than persisting a
    # pathological document. clamp_snippet / fit_block read these module globals at call time.
    monkeypatch.setattr(source_safety, "MAX_EVIDENCE_SNIPPET_CHARS", 24)
    monkeypatch.setattr(source_safety, "MAX_SOURCE_RENDER_CHARS", 24)

    reviewer = add_review_user(
        database, settings, admin, email="safety-bound@example.test", role="reviewer"
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
            idem="safety-bound-0001",
        )

        flat = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/bundle"
        )
        snippet = flat.json()["evidence_windows"][0]["snippet"]
        # The Subject fixture snippet is longer than 24, so it is clamped and visibly marked.
        assert len(snippet) <= 24
        assert snippet.endswith(TRUNCATION_MARKER)

        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        render = grouped.json()["source_render"]
        content = render["content"]
        # The assembled render respects the aggregate bound and stays safe-text.
        assert len(content) <= 24
        assert render["render_mode"] == "safe_text"
        assert render["truncated"] is True
        assert render["omitted_anchor_count"] >= 0
        # Every emitted anchor still addresses live content despite truncation.
        for anchor in render["anchors"]:
            start, end = anchor["char_start"], anchor["char_end"]
            assert 0 <= start <= end <= len(content)


@pytest.mark.anyio
async def test_anchor_budget_exhaustion_degrades_to_reviewable_fallback(
    settings: Settings,
    database: Database,
    admin: AdminIdentity,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With no anchor budget the render drops to empty, but the item must remain reviewable with the
    # documented anchor-unavailable fallback (source_anchor_id absent), never a broken bundle.
    monkeypatch.setattr(grouped_source_text, "MAX_SOURCE_RENDER_ANCHORS", 0)

    reviewer = add_review_user(
        database, settings, admin, email="safety-fallback@example.test", role="reviewer"
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
            "Citation Neutral",
            idem="safety-fallback-0001",
        )

        grouped = await reviewer_client.get(
            f"/api/v1/tenants/{tenant_id}/review/assignments/{assignment_id}/grouped-bundle"
        )
        assert grouped.status_code == 200, grouped.text
        body = grouped.json()
        render = body["source_render"]
        assert render["content"] == ""
        assert render["anchors"] == []
        assert render["omitted_anchor_count"] == 1
        item = body["field_groups"][0]["items"][0]
        assert item["source_anchor_id"] is None
        assert item["source_anchor_unavailable_reason"] == "anchor_budget_exhausted"
        # The item is still reviewable: it keeps its evidence reference and the bundle stays usable.
        assert item["evidence_window_ids"]
        assert body["allowed_actions"] == ["save_draft", "submit"]
