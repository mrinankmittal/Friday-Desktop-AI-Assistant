"""Gmail / Slack / Discord HTTP senders. Tokens never go in SQLite."""

from __future__ import annotations

import base64
from email.mime.text import MIMEText
from typing import Any, Protocol


class HttpTransport(Protocol):
    def get(self, url: str, **kwargs: Any) -> Any: ...

    def post(self, url: str, **kwargs: Any) -> Any: ...


class RequestsTransport:
    def get(self, url: str, **kwargs: Any) -> Any:
        import requests

        return requests.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> Any:
        import requests

        return requests.post(url, **kwargs)


def send_gmail(
    *,
    access_token: str = "",
    to: str,
    subject: str,
    body: str,
    transport: HttpTransport | None = None,
    smtp_user: str = "",
    smtp_password: str = "",
) -> str:
    if smtp_user and smtp_password:
        _smtp_send(
            user=smtp_user,
            password=smtp_password,
            to=to,
            subject=subject,
            body=body,
        )
        return "Email sent."
    if not access_token:
        raise PermissionError("Gmail login expired. Say connect gmail again.")
    http = transport or RequestsTransport()
    message = MIMEText(body, _charset="utf-8")
    message["To"] = to
    message["Subject"] = subject or "Message from Friday"
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii").rstrip("=")
    response = http.post(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
        json={"raw": raw},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    _raise_for_status(response, "Gmail")
    return "Email sent."


def list_gmail(
    *,
    access_token: str,
    transport: HttpTransport | None = None,
    limit: int = 5,
) -> str:
    http = transport or RequestsTransport()
    response = http.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        params={"maxResults": max(1, min(limit, 10))},
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20,
    )
    _raise_for_status(response, "Gmail")
    payload = response.json() if hasattr(response, "json") else {}
    ids = [str(item.get("id") or "") for item in (payload.get("messages") or []) if item]
    if not ids:
        return "Your inbox has no recent messages."
    subjects: list[str] = []
    for message_id in ids[:limit]:
        detail = http.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
            params={"format": "metadata", "metadataHeaders": "Subject"},
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if getattr(detail, "status_code", 200) != 200:
            continue
        data = detail.json() if hasattr(detail, "json") else {}
        headers = (data.get("payload") or {}).get("headers") or []
        subject = next(
            (str(item.get("value") or "") for item in headers if item.get("name") == "Subject"),
            "",
        )
        subjects.append(subject or f"message {message_id[:8]}")
    spoken = "Here are recent emails. " + "; ".join(subjects)
    return spoken


def send_slack(
    *,
    access_token: str,
    channel: str,
    body: str,
    transport: HttpTransport | None = None,
) -> str:
    http = transport or RequestsTransport()
    response = http.post(
        "https://slack.com/api/chat.postMessage",
        json={"channel": channel, "text": body},
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=utf-8",
        },
        timeout=20,
    )
    _raise_for_status(response, "Slack")
    payload = response.json() if hasattr(response, "json") else {}
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("error") or "Slack send failed."))
    return "Slack message sent."


def send_discord(
    *,
    webhook_url: str,
    body: str,
    transport: HttpTransport | None = None,
) -> str:
    http = transport or RequestsTransport()
    response = http.post(
        webhook_url,
        json={"content": body},
        timeout=20,
    )
    _raise_for_status(response, "Discord")
    return "Discord message sent."


def _smtp_send(*, user: str, password: str, to: str, subject: str, body: str) -> None:
    import smtplib

    message = MIMEText(body, _charset="utf-8")
    message["From"] = user
    message["To"] = to
    message["Subject"] = subject or "Message from Friday"
    try:
        with smtplib.SMTP("smtp.gmail.com", 587, timeout=20) as smtp:
            smtp.starttls()
            smtp.login(user, password)
            smtp.sendmail(user, [to], message.as_string())
    except smtplib.SMTPAuthenticationError as error:
        raise PermissionError(
            "Gmail rejected the login. Use a 16-letter App Password from Google Account, "
            "Security, 2-step verification, App passwords — not your normal Gmail password. "
            "Then restart Friday and say connect gmail."
        ) from error
    except smtplib.SMTPException as error:
        raise RuntimeError(f"Gmail SMTP failed: {error}") from error


def _raise_for_status(response: Any, label: str) -> None:
    status = int(getattr(response, "status_code", 200) or 200)
    if status in {401, 403}:
        raise PermissionError(f"{label} login expired. Say connect {label.lower()} again.")
    if status >= 400:
        raise RuntimeError(f"{label} request failed ({status}).")
