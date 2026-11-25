"""Shared base for the auth service: construction, HMAC key access, and role catalogue."""

from __future__ import annotations

from typing import cast

from pydantic import SecretStr

from review_platform.common.errors import APIError
from review_platform.settings import Settings

FINAL_SUPERUSER_LOCK_ID = 1_914_220_242
TENANT_ROLES = frozenset({"reviewer", "adjudicator", "campaign_manager", "user_admin", "auditor"})
ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    # These strings are advisory metadata surfaced in ``/me`` for client-side routing and control
    # visibility only; server-side authorization is enforced on ``role_code`` (see
    # ``ReviewServiceBase._require_role`` and ``RoleAdminMixin.require_*``), never on these values.
    # A reviewer holds the concrete review actions (claim, submit) the reviewer surface routes on.
    "reviewer": frozenset({"review:claim", "review:submit"}),
    "adjudicator": frozenset({"adjudication:participate"}),
    "campaign_manager": frozenset({"campaign:manage"}),
    "user_admin": frozenset({"membership:manage", "tenant_role:manage"}),
    "auditor": frozenset({"audit:read"}),
    "super_admin": frozenset({"global:admin"}),
}


def capability_flags(role_codes: set[str]) -> dict[str, bool]:
    """Project the roles a user holds (any tenant, plus global) into the ``can_*`` metadata the
    review UI reads for control visibility. These are a read projection of ``role_code`` truth, not
    a second authorization authority; the server still enforces on the roles themselves."""

    return {
        "can_administer": bool(role_codes & {"super_admin", "user_admin"}),
        "can_review": "reviewer" in role_codes,
        "can_adjudicate": bool(role_codes & {"adjudicator", "super_admin"}),
        "can_invite_reviewers": bool(role_codes & {"super_admin", "user_admin"}),
        "can_allocate": bool(role_codes & {"super_admin", "campaign_manager"}),
        "can_manage_campaigns": bool(role_codes & {"super_admin", "campaign_manager"}),
    }


def default_landing(flags: dict[str, bool]) -> str | None:
    """Highest-privilege default landing route hint for the UI, or ``None`` when the identity holds
    no actionable capability (a rostered account with no usable role)."""

    if flags["can_administer"] or flags["can_manage_campaigns"] or flags["can_allocate"]:
        return "/admin"
    if flags["can_adjudicate"]:
        return "/adjudication"
    if flags["can_review"]:
        return "/reviewer"
    return None


class AuthServiceBase:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def session_key(self) -> str:
        return cast(SecretStr, self.settings.session_hmac_key).get_secret_value()

    @property
    def activation_key(self) -> str:
        return cast(SecretStr, self.settings.activation_hmac_key).get_secret_value()

    @property
    def audit_key(self) -> str:
        return cast(SecretStr, self.settings.audit_hmac_key).get_secret_value()

    @staticmethod
    def authentication_required() -> APIError:
        return APIError(
            401,
            "authentication_required",
            "Authentication required",
            "An active session is required.",
        )
