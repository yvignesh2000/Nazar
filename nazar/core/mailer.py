"""
Transactional email adapter for invites and magic links.
"""

from __future__ import annotations

import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


RESEND_API_URL = "https://api.resend.com/emails"


def _wrap_email(body: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111827;">
      {body}
    </div>
    """


def _send_resend_email(*, to_email: str, subject: str, html: str) -> dict:
    api_key = (os.environ.get("RESEND_API_KEY") or "").strip()
    from_email = (os.environ.get("RESEND_FROM_EMAIL") or "").strip()
    if not api_key or not from_email:
        return {"mode": "dev", "sent": False}

    payload = json.dumps(
        {
            "from": from_email,
            "to": [to_email],
            "subject": subject,
            "html": html,
        }
    ).encode("utf-8")
    request = Request(
        RESEND_API_URL,
        data=payload,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
            return {"mode": "resend", "sent": True, "provider_id": data.get("id")}
    except (HTTPError, URLError):
        return {"mode": "dev", "sent": False}


def send_magic_link_email(*, to_email: str, recipient_name: str, workspace_name: str, magic_url: str) -> dict:
    body = _wrap_email(
        f"""
        <h2 style="margin:0 0 12px;">Sign in to {workspace_name}</h2>
        <p style="line-height:1.6;">Hi {recipient_name}, use the button below to sign in to Nazar.</p>
        <p style="margin:24px 0;"><a href="{magic_url}" style="background:#635bff;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;">Sign in</a></p>
        <p style="font-size:13px;color:#6b7280;line-height:1.6;">If the button does not work, open this link directly:<br>{magic_url}</p>
      """
    )
    return _send_resend_email(to_email=to_email, subject=f"Sign in to {workspace_name}", html=body)


def send_workspace_invite_email(*, to_email: str, recipient_name: str, workspace_name: str, invite_url: str, role_label: str) -> dict:
    body = _wrap_email(
        f"""
        <h2 style="margin:0 0 12px;">You’ve been invited to {workspace_name}</h2>
        <p style="line-height:1.6;">Hi {recipient_name}, you were invited to join Nazar as <strong>{role_label}</strong>.</p>
        <p style="margin:24px 0;"><a href="{invite_url}" style="background:#635bff;color:white;padding:12px 18px;border-radius:10px;text-decoration:none;">Accept invite</a></p>
        <p style="font-size:13px;color:#6b7280;line-height:1.6;">If the button does not work, open this link directly:<br>{invite_url}</p>
      """
    )
    return _send_resend_email(to_email=to_email, subject=f"Join {workspace_name} on Nazar", html=body)
