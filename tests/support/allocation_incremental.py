from __future__ import annotations

import uuid

from tests.support.campaigns import import_campaign
from tests.support.identities import AdminIdentity, ReviewIdentity

FEASIBLE_POLICY = {
    "subject_kind": "case",
    "review_kind": "metadata_field",
    "target_distinct_subjects": 4,
    "target_per_reviewer_workload": 3,
    "target_pairwise_overlap": 2,
    "target_global_overlap": 1,
    "rolling_window_size": 0,
    "rolling_window_stride": 0,
    "hub_priority_count": 1,
    "random_seed": "alloc-seed-incr",
    "allocation_policy_version": "reviewer-allocation/v1",
    "metric_weights": {},
}

INCREMENTAL_POLICY_BASE = {
    "subject_kind": "case",
    "review_kind": "metadata_field",
    "min_reviews_per_subject": 3,
    "movement_policy": {
        "allow_rebalance_unclaimed": True,
        "allow_rebalance_claimed": False,
        "allow_rebalance_draft": False,
    },
    "random_seed": "incr-seed-1",
    "allocation_policy_version": "reviewer-allocation/v1",
}


def base_alloc_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/campaigns/{campaign_id}/allocation-runs"


def incr_policy(reviewer_ids: list[str], base_run_id: str, **overrides: object) -> dict:
    body = dict(INCREMENTAL_POLICY_BASE)
    body["reviewer_ids"] = reviewer_ids
    body["base_run_id"] = base_run_id
    body.update(overrides)
    return body


async def setup_campaign_with_published_run(
    admin_client: object,
    manager_client: object,
    admin: AdminIdentity,
    manager: ReviewIdentity,
    reviewers: list[ReviewIdentity],
    campaign_key: str,
    mutation_hdrs: dict,
) -> tuple[str, str]:
    """Return (campaign_id, initial_run_id) after initial publish.

    Scoped to ``metadata_field`` so the campaign has one review kind: these tests are about
    reviewer movement (add/remove/rebalance), and a single-kind subject set keeps their coverage
    and revocation assertions about that, not about how many kinds the fixture happens to carry.
    """
    imported = await import_campaign(
        admin_client, admin, key=campaign_key, review_kinds=["metadata_field"]
    )
    campaign_id = str(imported["campaign_id"])
    runs = base_alloc_path(admin.tenant_id, campaign_id)

    body = dict(FEASIBLE_POLICY)
    body["reviewer_ids"] = [str(r.user_id) for r in reviewers]

    persisted = await manager_client.post(
        runs,
        json=body,
        headers={**mutation_hdrs, "Idempotency-Key": f"init-persist-{campaign_key}"},
    )
    assert persisted.status_code == 201, persisted.text
    run_id = str(persisted.json()["run_id"])

    published = await manager_client.post(
        f"{runs}/{run_id}/publish",
        headers={**mutation_hdrs, "Idempotency-Key": f"init-publish-{campaign_key}"},
    )
    assert published.status_code == 201, published.text
    return campaign_id, run_id
