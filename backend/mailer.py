"""
Outgoing mail for the map: the sign-up mailbox check. Same Google Workspace
mailbox setup as nabilvs.com (SMTP over SSL with an app password), configured
by DXMAP_SMTP_USER, DXMAP_SMTP_APP_PASSWORD and optionally DXMAP_SMTP_FROM.

With no SMTP configured and DXMAP_ENV != prod, a mail is written to
DXMAP_LOCAL_MAIL_DIR (if set) so a local review can read the link; in prod it
is never written to disk, only logged as skipped.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
import time
from email.message import EmailMessage

log = logging.getLogger("dxmap.mail")


def configured() -> bool:
    return bool(os.environ.get("DXMAP_SMTP_USER") and os.environ.get("DXMAP_SMTP_APP_PASSWORD"))


def can_send() -> bool:
    """True when a mail would actually go out (or be written, in local review)."""
    return configured() or bool(
        os.environ.get("DXMAP_LOCAL_MAIL_DIR") and os.environ.get("DXMAP_ENV", "prod") != "prod"
    )


def send(to: str, subject: str, text: str) -> bool:
    """Best effort: returns False (and logs, without the address' content) on any failure."""
    if not configured():
        d = os.environ.get("DXMAP_LOCAL_MAIL_DIR")
        if d and os.environ.get("DXMAP_ENV", "prod") != "prod":
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, f"{int(time.time() * 1000)}.txt"), "w", encoding="utf-8") as f:
                f.write(f"To: {to}\nSubject: {subject}\n\n{text}\n")
            return True
        log.warning("SMTP not configured: mail %r not sent", subject)
        return False
    user = os.environ["DXMAP_SMTP_USER"]
    msg = EmailMessage()
    msg["From"] = os.environ.get("DXMAP_SMTP_FROM") or user
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as s:
            s.login(user, os.environ["DXMAP_SMTP_APP_PASSWORD"])
            s.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001 - never break sign-up over a mail failure
        log.warning("mail %r failed: %s", subject, type(exc).__name__)
        return False
