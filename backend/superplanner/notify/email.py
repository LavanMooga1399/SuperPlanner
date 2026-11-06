"""SMTP sending (M6-DESIGN 3.3): `smtplib` with SMTP_HOST / SMTP_PORT (587) / SMTP_USER / SMTP_PASSWORD /
SMTP_FROM / SMTP_STARTTLS (true). Tests pass `Settings.smtp_send` (a callable taking the EmailMessage)."""

from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from typing import Any


def build(settings: Any, to: str, subject: str, text: str, html: str,
          attachments: list[tuple[str, bytes, str]] | None = None) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.smtp_from or "superplanner@localhost"
    msg["To"] = to
    msg["Subject"] = subject[:200]
    msg.set_content(text)
    msg.add_alternative(html, subtype="html")
    for name, data, mime in attachments or []:
        main, _, sub = mime.partition("/")
        msg.add_attachment(data, maintype=main, subtype=sub or "octet-stream", filename=name)
    return msg


def send(settings: Any, msg: EmailMessage) -> None:
    if settings.smtp_send is not None:
        settings.smtp_send(msg)
        return
    if not settings.smtp_host:
        raise RuntimeError("SMTP is not configured")
    with smtplib.SMTP(settings.smtp_host, int(settings.smtp_port), timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password or "")
        smtp.send_message(msg)
