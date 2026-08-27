"""Wrap integration secrets. Windows uses DPAPI; tests can inject a protector."""

from __future__ import annotations

import base64
import json
import logging
import sys
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("friday.security")

_MARKER = "_friday_protected"
ProtectFn = Callable[[bytes], bytes]
UnprotectFn = Callable[[bytes], bytes]


def wrap_secrets(
    payload: dict[str, Any],
    *,
    protect: ProtectFn | None = None,
) -> dict[str, Any]:
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    blob = (protect or _protect)(raw)
    return {_MARKER: True, "payload": base64.b64encode(blob).decode("ascii")}


def unwrap_secrets(
    envelope: dict[str, Any],
    *,
    unprotect: UnprotectFn | None = None,
) -> dict[str, Any]:
    if not isinstance(envelope, dict):
        return {}
    if not envelope.get(_MARKER):
        return envelope
    encoded = str(envelope.get("payload") or "")
    if not encoded:
        return {}
    try:
        blob = base64.b64decode(encoded.encode("ascii"))
        raw = (unprotect or _unprotect)(blob)
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError, OSError):
        logger.exception("unable to unwrap secrets")
        return {}
    return payload if isinstance(payload, dict) else {}


class SecretBox:
    def __init__(
        self,
        *,
        protect: ProtectFn | None = None,
        unprotect: UnprotectFn | None = None,
    ) -> None:
        self.protect = protect or _protect
        self.unprotect = unprotect or _unprotect

    def dump(self, payload: dict[str, Any]) -> dict[str, Any]:
        return wrap_secrets(payload, protect=self.protect)

    def load(self, envelope: dict[str, Any]) -> dict[str, Any]:
        return unwrap_secrets(envelope, unprotect=self.unprotect)


def _protect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    try:
        return _dpapi_protect(data)
    except Exception:
        logger.exception("DPAPI protect failed; storing wrapped envelope")
        return data


def _unprotect(data: bytes) -> bytes:
    if sys.platform != "win32":
        return data
    try:
        return _dpapi_unprotect(data)
    except Exception:
        logger.exception("DPAPI unprotect failed")
        return data


def _dpapi_protect(data: bytes) -> bytes:
    import win32crypt

    return win32crypt.CryptProtectData(data, "FridaySecrets")


def _dpapi_unprotect(data: bytes) -> bytes:
    import win32crypt

    _description, raw = win32crypt.CryptUnprotectData(data)
    return raw
