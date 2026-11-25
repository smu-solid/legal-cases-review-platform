"""Concrete email senders: dev console/file outbox and a production SMTP provider.

The console and file senders are development-only conveniences that render the full message —
including the copyable action link — so a developer can complete invite/reset flows locally.
:func:`review_platform.email.factory.build_email_sender` forbids them in production. Only the
SMTP sender is permitted in production, and it logs envelope metadata alone.
"""

from __future__ import annotations

import logging
import smtplib
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from email.message import EmailMessage as MimeEmail
from pathlib import Path
from typing import Protocol

from review_platform.email.message import EmailDeliveryError, EmailMessage

logger = logging.getLogger("review_platform")


def _log_dispatch(mode: str, message: EmailMessage) -> None:
    """Record a delivery without ever emitting the body or any link/token material."""

    logger.info(
        "email.dispatched mode=%s to=%s subject=%s",
        mode,
        message.to_address,
        message.subject,
    )


class ConsoleEmailSender:
    """Writes the full rendered message to the application logger (development only)."""

    def send(self, message: EmailMessage) -> None:
        logger.info(
            "email.outbox.console\nTo: %s\nSubject: %s\n\n%s",
            message.to_address,
            message.subject,
            message.text_body,
        )


class FileOutboxEmailSender:
    """Writes each rendered message to a file under a local directory (development only)."""

    def __init__(self, outbox_dir: Path) -> None:
        self._outbox_dir = outbox_dir

    def send(self, message: EmailMessage) -> None:
        self._outbox_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
        path = self._outbox_dir / f"{stamp}-{uuid.uuid4().hex}.eml"
        path.write_text(
            f"To: {message.to_address}\n"
            f"Subject: {message.subject}\n\n"
            f"{message.text_body}\n\n"
            f"----- HTML -----\n{message.html_body}\n",
            encoding="utf-8",
        )
        _log_dispatch("file", message)


class SmtpClient(Protocol):
    """The subset of :class:`smtplib.SMTP` used by :class:`SmtpEmailSender`."""

    def starttls(self) -> object: ...
    def login(self, user: str, password: str) -> object: ...
    def send_message(self, msg: MimeEmail) -> object: ...


SmtpConnect = Callable[[], AbstractContextManager[SmtpClient]]


class SmtpEmailSender:
    """Delivers mail through an SMTP provider using credentials from resolved settings.

    The SMTP connection is created through an injected ``connect`` factory so the delivery
    logic is testable without a live server; it defaults to a STARTTLS ``smtplib.SMTP``
    session. Credentials are never logged.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        from_address: str,
        use_tls: bool = True,
        connect: SmtpConnect | None = None,
    ) -> None:
        self._username = username
        self._password = password
        self._from_address = from_address
        self._use_tls = use_tls
        self._connect: SmtpConnect = connect or (lambda: smtplib.SMTP(host, port))

    def send(self, message: EmailMessage) -> None:
        mime = MimeEmail()
        mime["Subject"] = message.subject
        mime["From"] = self._from_address
        mime["To"] = message.to_address
        mime.set_content(message.text_body)
        mime.add_alternative(message.html_body, subtype="html")
        try:
            with self._connect() as client:
                if self._use_tls:
                    client.starttls()
                client.login(self._username, self._password)
                client.send_message(mime)
        except OSError as exc:  # network/SMTP transport failures
            raise EmailDeliveryError("email provider delivery failed") from exc
        _log_dispatch("smtp", message)
