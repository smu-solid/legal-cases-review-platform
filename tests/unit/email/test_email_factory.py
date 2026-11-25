"""Environment-driven sender selection and fail-closed configuration checks."""

from __future__ import annotations

from typing import Any

import pytest

from review_platform.email.factory import build_email_sender
from review_platform.email.message import EmailConfigurationError
from review_platform.email.senders import (
    ConsoleEmailSender,
    FileOutboxEmailSender,
    SmtpEmailSender,
)
from review_platform.settings import Settings

pytestmark = pytest.mark.no_db

# Isolate the local dotenv so a dev `.env` (e.g. `REVIEW_EMAIL_MODE=file` for the local outbox)
# cannot leak into these sender-selection assertions; the app still reads `.env` at runtime. Tests
# that pass an explicit `email_mode` are already deterministic, but they share this base so the
# whole module asserts built-in defaults rather than whatever the developer's `.env` happens to set.
_DEV_BASE: dict[str, Any] = {"_env_file": None, "environment": "development"}

_PROD_BASE: dict[str, Any] = {
    "_env_file": None,
    "environment": "production",
    "database_url": "postgresql://runtime/db",
    "migration_database_url": "postgresql://migrate/db",
    "session_hmac_key": "prod-session-key-0000000000000000000000000",
    "activation_hmac_key": "prod-activation-key-00000000000000000000000",
    "rate_limit_hmac_key": "prod-rate-key-00000000000000000000000000000",
    "audit_hmac_key": "prod-audit-key-0000000000000000000000000000",
    "allowed_origins": ("https://app.test",),
    "allowed_hosts": ("app.test",),
}

_SMTP_CONFIG: dict[str, Any] = {
    "email_mode": "smtp",
    "email_smtp_host": "smtp.test",
    "email_smtp_username": "mailer",
    "email_smtp_password": "smtp-secret",
    "email_from_address": "no-reply@app.test",
}


def test_development_defaults_to_console() -> None:
    sender = build_email_sender(Settings(**_DEV_BASE))
    assert isinstance(sender, ConsoleEmailSender)


def test_file_mode_selected_outside_production() -> None:
    sender = build_email_sender(Settings(**_DEV_BASE, email_mode="file"))
    assert isinstance(sender, FileOutboxEmailSender)


def test_smtp_mode_selected_when_fully_configured() -> None:
    sender = build_email_sender(Settings(**_DEV_BASE, **_SMTP_CONFIG))
    assert isinstance(sender, SmtpEmailSender)


def test_smtp_mode_fails_closed_when_incomplete() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(Settings(**_DEV_BASE, email_mode="smtp", email_smtp_host="smtp.test"))


def test_production_requires_smtp_mode() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(Settings(**_PROD_BASE))


def test_production_refuses_file_outbox() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(Settings(**_PROD_BASE, email_mode="file"))


def test_production_smtp_requires_complete_credentials() -> None:
    with pytest.raises(EmailConfigurationError):
        build_email_sender(Settings(**_PROD_BASE, email_mode="smtp", email_smtp_host="smtp.test"))


def test_production_smtp_selected_when_configured() -> None:
    sender = build_email_sender(Settings(**_PROD_BASE, **_SMTP_CONFIG))
    assert isinstance(sender, SmtpEmailSender)
