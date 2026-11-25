"""Template rendering and HTML-escaping guarantees."""

from __future__ import annotations

import pytest

from review_platform.email.templates import build_password_reset_link, build_reviewer_invitation

pytestmark = pytest.mark.no_db


def test_reset_link_escapes_interpolated_values() -> None:
    message = build_password_reset_link(
        to_address="reviewer@example.test",
        reset_url="https://app.test/reset-password?reset_token=abc&x=1",
        expiry_hours=24,
        support_contact="ops@example.test",
    )
    # The ampersand in the link must be escaped inside the HTML attribute.
    assert "reset_token=abc&amp;x=1" in message.html_body
    # The plain-text alternative keeps the raw, clickable link.
    assert "https://app.test/reset-password?reset_token=abc&x=1" in message.text_body
    assert "expires in 24 hours" in message.text_body
    assert "Do not forward" in message.text_body
    assert "ops@example.test" in message.text_body


def test_reset_link_singular_hour_and_optional_support() -> None:
    message = build_password_reset_link(
        to_address="reviewer@example.test",
        reset_url="https://app.test/x",
        expiry_hours=1,
    )
    assert "expires in 1 hour." in message.text_body
    assert "contact your administrator" not in message.text_body


def test_reset_link_renders_subject_text_and_html() -> None:
    message = build_password_reset_link(
        to_address="a@test",
        reset_url="https://app.test/r",
        expiry_hours=2,
        support_contact="ops@test",
    )
    assert message.subject
    assert message.text_body.strip()
    assert message.html_body.startswith("<!doctype html>")
    assert "Do not forward" in message.html_body


def test_reviewer_invitation_escapes_display_and_tenant_names() -> None:
    message = build_reviewer_invitation(
        to_address="reviewer@example.test",
        display_name="<script>alert(1)</script>",
        tenant_name="Tenant & <b>Co</b>",
        app_url="https://app.test/",
        support_contact="ops@example.test",
    )
    assert "<script>" not in message.html_body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in message.html_body
    assert "Tenant &amp; &lt;b&gt;Co&lt;/b&gt;" in message.html_body
    # The unescaped raw names remain in the plain-text alternative.
    assert "<script>alert(1)</script>" in message.text_body
    assert "Tenant & <b>Co</b>" in message.text_body


def test_reviewer_invitation_explains_private_password_activation() -> None:
    message = build_reviewer_invitation(
        to_address="reviewer@example.test",
        display_name="Reviewer One",
        tenant_name="Demo Workspace",
        app_url="https://app.test/activate?token=synthetic-token",
    )
    assert "choose a password" in message.text_body.lower()
    assert "https://app.test/activate?token=synthetic-token" in message.text_body
    assert "reviewer@example.test" in message.text_body
    assert "password_hash" not in message.text_body


def test_reviewer_invitation_reminder_variant_changes_subject_and_lead() -> None:
    first = build_reviewer_invitation(
        to_address="reviewer@example.test",
        display_name="Reviewer One",
        tenant_name="Synthetic Alpha",
        app_url="https://app.test/",
    )
    reminder = build_reviewer_invitation(
        to_address="reviewer@example.test",
        display_name="Reviewer One",
        tenant_name="Synthetic Alpha",
        app_url="https://app.test/",
        reminder=True,
    )
    assert first.subject != reminder.subject
    assert "Reminder" in reminder.subject
    assert "reminder" in reminder.text_body.lower()
    assert "reminder" not in first.text_body.lower()


def test_reviewer_invitation_optional_support_contact() -> None:
    with_support = build_reviewer_invitation(
        to_address="reviewer@example.test",
        display_name="Reviewer One",
        tenant_name="Synthetic Alpha",
        app_url="https://app.test/",
        support_contact="ops@example.test",
    )
    without_support = build_reviewer_invitation(
        to_address="reviewer@example.test",
        display_name="Reviewer One",
        tenant_name="Synthetic Alpha",
        app_url="https://app.test/",
    )
    assert "ops@example.test" in with_support.text_body
    assert "ops@example.test" not in without_support.text_body
    # Both variants still tell the reviewer to contact an administrator if access is denied.
    assert "contact your administrator" in without_support.text_body
