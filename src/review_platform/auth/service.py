"""Authentication, session, role, and administrator application services.

``AuthService`` composes the responsibility mixins over
:class:`review_platform.auth.base.AuthServiceBase`: session resolution/CSRF/logout
(:mod:`review_platform.auth.sessions`), role/status administration
(:mod:`review_platform.auth.roles`), and admin-triggered password reset
(:mod:`review_platform.auth.password_reset`, in support of the admin step-up-reauth-gated
actions only). Value types and constants are re-exported here so existing
``review_platform.auth.service`` imports continue to resolve.
"""

from __future__ import annotations

from review_platform.auth.accounts import AccountAccessMixin
from review_platform.auth.base import (
    FINAL_SUPERUSER_LOCK_ID,
    ROLE_CAPABILITIES,
    TENANT_ROLES,
    AuthServiceBase,
)
from review_platform.auth.password_reset import PasswordResetMixin
from review_platform.auth.principal import Principal, now_utc
from review_platform.auth.sessions import SessionMixin

__all__ = [
    "FINAL_SUPERUSER_LOCK_ID",
    "ROLE_CAPABILITIES",
    "TENANT_ROLES",
    "AuthService",
    "AuthServiceBase",
    "Principal",
    "now_utc",
]


class AuthService(SessionMixin, PasswordResetMixin, AccountAccessMixin):
    """Authentication, session, role/status, and admin-triggered password-reset service.

    ``PasswordResetMixin`` extends ``RoleAdminMixin``, so tenant-admin authorization and session
    revocation are inherited through it.
    """
