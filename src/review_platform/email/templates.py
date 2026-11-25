"""Sober text/HTML account-lifecycle email templates."""

from __future__ import annotations

from html import escape

from review_platform.email.message import EmailMessage

_FORWARD_WARNING = (
    "This message contains a private link tied to your account. Do not forward it to anyone."
)


def _expiry_sentence(expiry_hours: int) -> str:
    unit = "hour" if expiry_hours == 1 else "hours"
    return f"For your security, the link expires in {expiry_hours} {unit}."


def _support_sentence(support_contact: str | None) -> str | None:
    if not support_contact:
        return None
    return f"If you did not expect this email, contact your administrator at {support_contact}."


def _compose(
    *,
    to_address: str,
    subject: str,
    paragraphs: list[str],
    action_label: str | None = None,
    action_url: str | None = None,
) -> EmailMessage:
    """Assemble a message, escaping every interpolated value for the HTML alternative."""

    text_lines: list[str] = list(paragraphs)
    html_parts = [f"<p>{escape(paragraph)}</p>" for paragraph in paragraphs]
    if action_label and action_url:
        text_lines.append(f"{action_label}: {action_url}")
        html_parts.insert(
            1 if html_parts else 0,
            f'<p><a href="{escape(action_url, quote=True)}">{escape(action_label)}</a></p>',
        )
    text_lines.append(_FORWARD_WARNING)
    html_parts.append(f"<p>{escape(_FORWARD_WARNING)}</p>")
    html_body = (
        f"<!doctype html><html><body><h1>{escape(subject)}</h1>{''.join(html_parts)}</body></html>"
    )
    return EmailMessage(
        to_address=to_address,
        subject=subject,
        text_body="\n\n".join(text_lines) + "\n",
        html_body=html_body,
    )


def _access_help_sentence(support_contact: str | None) -> str:
    """Access help sentence."""

    contact = f" at {support_contact}" if support_contact else ""
    return (
        "Access to the site itself is granted separately by an administrator, so if you sign in "
        f"and are not let in, contact your administrator{contact}."
    )


def build_reviewer_invitation(
    *,
    to_address: str,
    display_name: str,
    tenant_name: str,
    app_url: str,
    support_contact: str | None = None,
    reminder: bool = False,
) -> EmailMessage:
    """Build reviewer invitation."""

    lead = (
        f"This is a reminder that you have been invited as a reviewer for {tenant_name} on the "
        "review platform."
        if reminder
        else f"You have been invited as a reviewer for {tenant_name} on the review platform."
    )
    paragraphs = [
        f"Hello {display_name},",
        lead,
        f"Use the private activation link below to choose a password for {to_address}.",
        _access_help_sentence(support_contact),
    ]
    subject = (
        f"Reminder: you are invited to review for {tenant_name}"
        if reminder
        else f"You are invited to review for {tenant_name}"
    )
    return _compose(
        to_address=to_address,
        subject=subject,
        paragraphs=paragraphs,
        action_label="Activate your account",
        action_url=app_url,
    )


def build_password_reset_link(
    *,
    to_address: str,
    reset_url: str,
    expiry_hours: int,
    support_contact: str | None = None,
) -> EmailMessage:
    paragraphs = [
        "A password reset was requested for your review platform account.",
        "If you requested it, use the link below to choose a new password. No one else can see "
        "or set your password.",
        _expiry_sentence(expiry_hours),
    ]
    support = _support_sentence(support_contact)
    if support:
        paragraphs.append(support)
    return _compose(
        to_address=to_address,
        subject="Reset your review platform password",
        paragraphs=paragraphs,
        action_label="Choose a new password",
        action_url=reset_url,
    )
