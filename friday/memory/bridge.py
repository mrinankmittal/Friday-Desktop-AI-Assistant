"""Eel bridges for the Settings memory inspector."""

from __future__ import annotations

import eel

from friday.memory import get_memory_store


@eel.expose
def memory_list() -> list[dict]:
    return [item.to_dict() for item in get_memory_store().list_memories()]


@eel.expose
def memory_delete(memory_id: int) -> dict:
    removed = get_memory_store().forget(memory_id=int(memory_id))
    return {"ok": bool(removed), "removed": len(removed)}


@eel.expose
def document_list() -> list[dict]:
    return [item.to_dict() for item in get_memory_store().list_documents()]


@eel.expose
def document_delete(document_id: int) -> dict:
    deleted = get_memory_store().delete_document(int(document_id))
    return {"ok": bool(deleted)}


@eel.expose
def note_list() -> list[dict]:
    return [item.to_dict() for item in get_memory_store().list_notes()]


@eel.expose
def note_delete(note_id: int) -> dict:
    deleted = get_memory_store().delete_note(int(note_id))
    return {"ok": bool(deleted)}


@eel.expose
def reminder_list() -> list[dict]:
    return [item.to_dict() for item in get_memory_store().list_reminders(include_done=True)]


@eel.expose
def reminder_delete(reminder_id: int) -> dict:
    deleted = get_memory_store().delete_reminder(int(reminder_id))
    return {"ok": bool(deleted)}


@eel.expose
def event_log_list() -> list[dict]:
    return [item.to_dict() for item in get_memory_store().list_events()]


@eel.expose
def audit_list() -> list[dict]:
    return [item.to_dict() for item in get_memory_store().list_audit()]


@eel.expose
def allow_path_list() -> list[dict]:
    from friday.security.allowlist import list_allow_paths

    return [{"path": path} for path in list_allow_paths()]


@eel.expose
def integration_list() -> list[dict]:
    from friday.integrations.store import IntegrationStore

    store = IntegrationStore(get_memory_store().db_path)
    return [item.to_dict() for item in store.list()]


@eel.expose
def integration_disconnect(provider: str) -> dict:
    from friday.integrations.store import IntegrationStore

    store = IntegrationStore(get_memory_store().db_path)
    removed = store.delete(str(provider))
    return {"ok": bool(removed)}
