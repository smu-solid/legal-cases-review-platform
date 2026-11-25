"""Behavioral tests for the concrete email senders."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType

import pytest

from review_platform.email.message import EmailDeliveryError, EmailMessage
from review_platform.email.senders import (
    ConsoleEmailSender,
    FileOutboxEmailSender,
    SmtpEmailSender,
)

pytestmark = pytest.mark.no_db

MESSAGE = EmailMessage(
    to_address="reviewer@example.test",
    subject="Subject line",
    text_body="text body with link https://app.test/x?invitation_token=secret-token",
    html_body="<p>html body</p>",
)


@contextmanager
def _capture(logger_name: str) -> Iterator[list[logging.LogRecord]]:
    """Capture records from a named logger regardless of pytest's global log disabling."""

    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append  # type: ignore[assignment]
    logger = logging.getLogger(logger_name)
    previous_disable = logging.root.manager.disable
    previous_level = logger.level
    previous_disabled = logger.disabled
    logging.disable(logging.NOTSET)
    logger.disabled = False
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        yield records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.disabled = previous_disabled
        logging.disable(previous_disable)


def test_console_sender_logs_body_without_raising() -> None:
    with _capture("review_platform") as records:
        ConsoleEmailSender().send(MESSAGE)
    assert any("reviewer@example.test" in record.getMessage() for record in records)


def test_file_outbox_writes_message_and_creates_directory(tmp_path: Path) -> None:
    outbox = tmp_path / "nested" / "outbox"
    FileOutboxEmailSender(outbox).send(MESSAGE)
    files = list(outbox.glob("*.eml"))
    assert len(files) == 1
    contents = files[0].read_text(encoding="utf-8")
    assert "To: reviewer@example.test" in contents
    assert "Subject: Subject line" in contents
    assert "secret-token" in contents  # dev outbox intentionally carries the copyable link


class _FakeSmtp:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __enter__(self) -> _FakeSmtp:
        self.calls.append("enter")
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.calls.append("exit")

    def starttls(self) -> object:
        self.calls.append("starttls")
        return None

    def login(self, user: str, password: str) -> object:
        self.calls.append(f"login:{user}")
        return None

    def send_message(self, msg: object) -> object:
        self.calls.append("send_message")
        return None


def test_smtp_sender_starts_tls_logs_in_and_sends() -> None:
    fake = _FakeSmtp()
    sender = SmtpEmailSender(
        host="smtp.test",
        port=587,
        username="mailer",
        password="secret",
        from_address="no-reply@review.test",
        use_tls=True,
        connect=lambda: fake,
    )
    sender.send(MESSAGE)
    assert fake.calls == ["enter", "starttls", "login:mailer", "send_message", "exit"]


def test_smtp_sender_skips_starttls_when_disabled() -> None:
    fake = _FakeSmtp()
    SmtpEmailSender(
        host="smtp.test",
        port=25,
        username="mailer",
        password="secret",
        from_address="no-reply@review.test",
        use_tls=False,
        connect=lambda: fake,
    ).send(MESSAGE)
    assert "starttls" not in fake.calls


def test_smtp_sender_wraps_transport_failure() -> None:
    def failing_connect() -> _FakeSmtp:
        raise OSError("connection refused")

    sender = SmtpEmailSender(
        host="smtp.test",
        port=587,
        username="mailer",
        password="secret",
        from_address="no-reply@review.test",
        connect=failing_connect,
    )
    with pytest.raises(EmailDeliveryError):
        sender.send(MESSAGE)
