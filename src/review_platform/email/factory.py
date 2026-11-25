"""Environment-selected construction of the active :class:`EmailSender`.

Selection fails closed. Production must use the SMTP provider with complete credentials; the
console and file outboxes are refused in production so a developer convenience can never become
production behavior. An explicitly requested ``smtp`` mode also requires complete credentials in
every environment — there is no silent fallback to an outbox.
"""

from __future__ import annotations

from review_platform.email.message import EmailConfigurationError, EmailSender
from review_platform.email.senders import (
    ConsoleEmailSender,
    FileOutboxEmailSender,
    SmtpEmailSender,
)
from review_platform.settings import Settings


def _build_smtp_sender(settings: Settings) -> SmtpEmailSender:
    if (
        not settings.email_smtp_host
        or not settings.email_smtp_username
        or settings.email_smtp_password is None
        or not settings.email_from_address
    ):
        raise EmailConfigurationError(
            "SMTP email requires REVIEW_EMAIL_SMTP_HOST, REVIEW_EMAIL_SMTP_USERNAME, "
            "REVIEW_EMAIL_SMTP_PASSWORD, and REVIEW_EMAIL_FROM_ADDRESS"
        )
    return SmtpEmailSender(
        host=settings.email_smtp_host,
        port=settings.email_smtp_port,
        username=settings.email_smtp_username,
        password=settings.email_smtp_password.get_secret_value(),
        from_address=settings.email_from_address,
        use_tls=settings.email_smtp_use_tls,
    )


def build_email_sender(settings: Settings) -> EmailSender:
    """Select the email sender for the resolved settings, failing closed on misconfiguration."""

    if settings.environment == "production":
        if settings.email_mode != "smtp":
            raise EmailConfigurationError(
                "production requires REVIEW_EMAIL_MODE=smtp; console/file outboxes are refused"
            )
        return _build_smtp_sender(settings)

    if settings.email_mode == "smtp":
        return _build_smtp_sender(settings)
    if settings.email_mode == "file":
        return FileOutboxEmailSender(settings.email_outbox_dir)
    return ConsoleEmailSender()
