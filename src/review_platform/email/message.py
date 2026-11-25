"""Email message contract, sender protocol, and typed failure modes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


class EmailConfigurationError(RuntimeError):
    """Raised at composition time when a required email configuration is missing.

    Selecting a sender must fail closed rather than silently degrading: production must never
    fall back to a console/file outbox, and an explicitly requested provider must never run
    with incomplete credentials.
    """


class EmailDeliveryError(RuntimeError):
    """Raised when a configured sender cannot deliver a message at send time."""


@dataclass(frozen=True)
class EmailMessage:
    """A rendered transactional email with both plain-text and HTML alternatives.

    ``to_address`` is the recipient; ``subject``/``text_body``/``html_body`` are already
    rendered and escaped by the template layer. The message intentionally carries no headers,
    attachments, or external asset references.
    """

    to_address: str
    subject: str
    text_body: str
    html_body: str


@runtime_checkable
class EmailSender(Protocol):
    """Delivers a rendered :class:`EmailMessage`.

    Implementations must not log message bodies or any secret link/token material; only
    non-sensitive envelope metadata (recipient, subject) may be logged.
    """

    def send(self, message: EmailMessage) -> None: ...
