"""Transactional email delivery for account lifecycle messages.

This package owns the email-sending boundary only: an :class:`EmailSender` protocol, the
environment-selected sender implementations (dev console/file outbox and a production
SMTP provider), and the simple text/HTML account templates. It performs no persistence and
holds no auth state; callers render a template and hand the resulting message to the sender.
"""

from __future__ import annotations

from review_platform.email.factory import build_email_sender
from review_platform.email.message import (
    EmailConfigurationError,
    EmailDeliveryError,
    EmailMessage,
    EmailSender,
)

__all__ = [
    "EmailConfigurationError",
    "EmailDeliveryError",
    "EmailMessage",
    "EmailSender",
    "build_email_sender",
]
