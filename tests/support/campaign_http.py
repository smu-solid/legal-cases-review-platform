"""Shared HTTP workflow scenario support."""

from __future__ import annotations

import uuid

from tests.support.clients import mutation_headers
from tests.support.identities import AdminIdentity


def complete_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}/complete"


def campaign_path(tenant_id: uuid.UUID | str, campaign_id: str) -> str:
    return f"/api/v1/admin/tenants/{tenant_id}/review/campaigns/{campaign_id}"


async def _create_draft(client, csrf_token: str, admin: AdminIdentity, *, key: str) -> dict:
    created = await client.post(
        f"/api/v1/admin/tenants/{admin.tenant_id}/review/campaigns",
        json={"campaign_key": key, "campaign_name": "Draft Campaign"},
        headers=mutation_headers(csrf_token),
    )
    assert created.status_code == 201, created.text
    return dict(created.json())
