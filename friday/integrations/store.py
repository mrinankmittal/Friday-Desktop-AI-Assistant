"""SQLite integration rows plus a sidecar secrets file (never in git)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from friday.memory.store import connect
from friday.security.secrets import SecretBox

PROVIDERS = ("gmail", "slack", "discord")


def canonical_provider(provider: str) -> str:
    name = provider.strip().lower()
    if name in {"email", "google", "mail"}:
        return "gmail"
    return name


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class Integration:
    provider: str
    status: str
    secret_ref: str
    label: str
    connected_at: str | None
    updated_at: str

    @property
    def connected(self) -> bool:
        return self.status == "connected"

    def to_dict(self) -> dict[str, str | None | bool]:
        return {
            "provider": self.provider,
            "status": self.status,
            "label": self.label,
            "connected": self.connected,
            "connected_at": self.connected_at,
            "updated_at": self.updated_at,
        }


class IntegrationStore:
    def __init__(
        self,
        db_path: Path,
        secrets_path: Path | None = None,
        secret_box: SecretBox | None = None,
    ) -> None:
        self.db_path = Path(db_path)
        self.secrets_path = Path(secrets_path or (self.db_path.parent / "friday.secrets.json"))
        self._box = secret_box or SecretBox()
        with connect(self.db_path):
            pass
        if not self.secrets_path.exists():
            self._write_secrets({})

    def list(self) -> list[Integration]:
        with connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT provider, status, secret_ref, label, connected_at, updated_at
                FROM integrations
                ORDER BY provider
                """
            ).fetchall()
        found = {str(row["provider"]): _from_row(row) for row in rows}
        return [
            found.get(
                name,
                Integration(
                    provider=name,
                    status="disconnected",
                    secret_ref=name,
                    label="",
                    connected_at=None,
                    updated_at="",
                ),
            )
            for name in PROVIDERS
        ]

    def get(self, provider: str) -> Integration:
        name = canonical_provider(provider)
        with connect(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT provider, status, secret_ref, label, connected_at, updated_at
                FROM integrations
                WHERE provider = ?
                """,
                (name,),
            ).fetchone()
        if row is None:
            return Integration(
                provider=name,
                status="disconnected",
                secret_ref=name,
                label="",
                connected_at=None,
                updated_at="",
            )
        return _from_row(row)

    def is_connected(self, provider: str) -> bool:
        return self.get(provider).connected and bool(self.secrets_for(provider))

    def secrets_for(self, provider: str) -> dict[str, Any]:
        blob = self._read_secrets()
        payload = blob.get(canonical_provider(provider)) or {}
        return payload if isinstance(payload, dict) else {}

    def save(self, provider: str, secrets: dict[str, Any], *, label: str = "") -> Integration:
        name = canonical_provider(provider)
        if name not in PROVIDERS:
            raise ValueError(f"Unknown integration: {provider}")
        cleaned = {key: value for key, value in secrets.items() if value}
        if not cleaned:
            raise ValueError("No credentials to store.")
        blob = self._read_secrets()
        blob[name] = cleaned
        self._write_secrets(blob)
        now = _utc_now()
        with connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO integrations (provider, status, secret_ref, label, connected_at, updated_at)
                VALUES (?, 'connected', ?, ?, ?, ?)
                ON CONFLICT(provider) DO UPDATE SET
                    status = 'connected',
                    secret_ref = excluded.secret_ref,
                    label = excluded.label,
                    connected_at = COALESCE(integrations.connected_at, excluded.connected_at),
                    updated_at = excluded.updated_at
                """,
                (name, name, label.strip(), now, now),
            )
        return self.get(name)

    def delete(self, provider: str) -> bool:
        name = canonical_provider(provider)
        blob = self._read_secrets()
        existed = name in blob
        blob.pop(name, None)
        self._write_secrets(blob)
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM integrations WHERE provider = ?",
                (name,),
            )
        return existed or cursor.rowcount > 0

    def _read_secrets(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.secrets_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(payload, dict):
            return {}
        return self._box.load(payload)

    def _write_secrets(self, payload: dict[str, Any]) -> None:
        self.secrets_path.parent.mkdir(parents=True, exist_ok=True)
        envelope = self._box.dump(payload if isinstance(payload, dict) else {})
        self.secrets_path.write_text(
            json.dumps(envelope, indent=2, sort_keys=True),
            encoding="utf-8",
        )


def _from_row(row: Any) -> Integration:
    return Integration(
        provider=str(row["provider"]),
        status=str(row["status"]),
        secret_ref=str(row["secret_ref"]),
        label=str(row["label"] or ""),
        connected_at=row["connected_at"],
        updated_at=str(row["updated_at"]),
    )
