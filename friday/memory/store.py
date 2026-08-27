from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from friday.db.pool import Session, session
from friday.memory.names import alias_token, name_from_hit, name_subject
from friday.memory.types import AuditEntry, DocumentInfo, EventLog, Memory, Note, Reminder, SearchHit, TaskItem
from friday.rag.chunk import chunk_text
from friday.rag.embed import cosine_similarity, embed_text, tokenize
from friday.rag.extract import MAX_BYTES, extract_text, is_blocked


_SEARCH_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "do",
        "you",
        "know",
        "what",
        "whats",
        "is",
        "are",
        "can",
        "could",
        "please",
        "friday",
        "tell",
        "me",
        "about",
        "did",
        "have",
        "who",
        "am",
        "i",
        "to",
        "of",
        "in",
        "on",
        "for",
        "and",
    }
)


def _normalize_token(token: str) -> str:
    return alias_token(token)


_GENERIC_SEARCH_TOKENS = _SEARCH_STOPWORDS | {
    "my",
    "name",
    "names",
    "favorite",
    "favourite",
}


def _distinctive_tokens(query: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in tokenize(query)
        if _normalize_token(token) not in _GENERIC_SEARCH_TOKENS and len(token) > 1
    }


def _content_has_token(token: str, content_tokens: set[str], lowered: str) -> bool:
    if token in content_tokens or token in lowered:
        return True
    if token + "s" in content_tokens:
        return True
    return False


def _lexical_score(query: str, content: str) -> float:
    lowered = content.lower()
    content_tokens = {_normalize_token(token) for token in tokenize(content)}
    distinctive = _distinctive_tokens(query)
    if distinctive and not all(
        _content_has_token(token, content_tokens, lowered) for token in distinctive
    ):
        return 0.0
    query_tokens = {
        _normalize_token(token)
        for token in tokenize(query)
        if token not in _SEARCH_STOPWORDS and len(token) > 1
    }
    if not query_tokens:
        return 0.0
    return len(query_tokens & content_tokens) / len(query_tokens)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _relevance_score(query: str, content: str, query_vec: list[float]) -> float:
    distinctive = _distinctive_tokens(query)
    lowered = content.lower()
    content_tokens = {_normalize_token(token) for token in tokenize(content)}
    if distinctive and not all(
        _content_has_token(token, content_tokens, lowered) for token in distinctive
    ):
        return 0.0
    query_subject = name_subject(query)
    if query_subject is not None and name_from_hit(content, query_subject) is None:
        return 0.0
    return max(
        cosine_similarity(query_vec, embed_text(content)),
        _lexical_score(query, content),
    )


def connect(db_path: Path) -> Session:
    """Open a single-writer session for ``db_path``.

    Use as ``with connect(path) as connection:``. The write lock is held for
    the whole block, so a transaction cannot interleave with another thread.
    """
    return session(db_path)


def path_is_allowed(path: Path, allow_paths: tuple[Path, ...]) -> bool:
    resolved = path.resolve()
    for root in allow_paths:
        try:
            resolved.relative_to(root.expanduser().resolve())
            return True
        except ValueError:
            continue
    return False


class MemoryStore:
    """SQLite facts, conversation rows, episodic task runs, and document chunks."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        with connect(self.db_path):
            pass
        self._conversation_id: int | None = None

    def remember(self, content: str, *, kind: str = "fact", source: str = "user") -> Memory:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Nothing to remember.")
        now = _utc_now()
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO memories (kind, content, source, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (kind, cleaned, source, now, now),
            )
            memory_id = int(cursor.lastrowid)
        return self.get_memory(memory_id)

    def get_memory(self, memory_id: int) -> Memory:
        with connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id = ?", (memory_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"No memory {memory_id}")
        return _memory_from_row(row)

    def list_memories(self, limit: int = 50) -> list[Memory]:
        with connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM memories ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_memory_from_row(row) for row in rows]

    def forget(
        self,
        *,
        memory_id: int | None = None,
        text: str | None = None,
    ) -> list[Memory]:
        removed: list[Memory] = []
        with connect(self.db_path) as connection:
            if memory_id is not None:
                row = connection.execute(
                    "SELECT * FROM memories WHERE id = ?", (memory_id,)
                ).fetchone()
                if row is not None:
                    removed.append(_memory_from_row(row))
                    connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            needle = (text or "").strip()
            if needle:
                rows = connection.execute(
                    "SELECT * FROM memories WHERE instr(lower(content), lower(?)) > 0",
                    (needle,),
                ).fetchall()
                ids = [int(row["id"]) for row in rows]
                removed.extend(_memory_from_row(row) for row in rows)
                if ids:
                    connection.executemany(
                        "DELETE FROM memories WHERE id = ?",
                        [(item,) for item in ids],
                    )
        # De-duplicate if both id and text matched the same row.
        unique: dict[int, Memory] = {item.id: item for item in removed}
        return list(unique.values())

    def record_task(
        self,
        *,
        task_id: str,
        request: str,
        intent: str,
        status: str,
        observation: str | None,
    ) -> None:
        with connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO task_runs (
                    task_id, request, intent, status, observation, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_id, request, intent, status, observation, _utc_now()),
            )

    def record_audit(
        self,
        *,
        event: str,
        task_id: str | None = None,
        tool: str | None = None,
        agent: str | None = None,
        risk_level: str | None = None,
        ok: bool | None = None,
        input_hash: str | None = None,
        observation: str | None = None,
        error: str | None = None,
    ) -> None:
        with connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO audit_logs (
                    created_at, event, task_id, tool, agent, risk_level,
                    ok, input_hash, observation, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_now(),
                    str(event or "tool_call"),
                    str(task_id or ""),
                    str(tool or ""),
                    str(agent or ""),
                    str(risk_level or ""),
                    None if ok is None else int(bool(ok)),
                    str(input_hash or ""),
                    str(observation or "")[:500],
                    str(error or "")[:300],
                ),
            )

    def list_audit(self, limit: int = 20) -> list[AuditEntry]:
        capped = max(1, min(int(limit), 50))
        with connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, event, task_id, tool, agent, risk_level,
                       ok, input_hash, observation, error
                FROM audit_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (capped,),
            ).fetchall()
        return [_audit_from_row(row) for row in rows]

    def record_event(
        self,
        *,
        event: str,
        task_id: str = "",
        intent: str = "",
        tool: str = "",
        tools: str = "",
        status: str = "",
        observation: str = "",
        error: str = "",
        duration_ms: int | None = None,
        request: str = "",
    ) -> None:
        with connect(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO event_logs (
                    created_at, event, task_id, intent, tool, tools,
                    status, observation, error, duration_ms, request
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _utc_now(),
                    str(event or "event"),
                    str(task_id or ""),
                    str(intent or ""),
                    str(tool or ""),
                    str(tools or ""),
                    str(status or ""),
                    str(observation or "")[:200],
                    str(error or "")[:300],
                    duration_ms,
                    str(request or "")[:120],
                ),
            )

    def list_events(self, limit: int = 40) -> list[EventLog]:
        capped = max(1, min(int(limit), 80))
        with connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT id, created_at, event, task_id, intent, tool, tools,
                       status, observation, error, duration_ms, request
                FROM event_logs
                ORDER BY id DESC
                LIMIT ?
                """,
                (capped,),
            ).fetchall()
        return [_event_from_row(row) for row in rows]

    def record_turn(self, role: str, content: str) -> None:
        cleaned = content.strip()
        if not cleaned:
            return
        with connect(self.db_path) as connection:
            conversation_id = self._ensure_conversation(connection)
            connection.execute(
                """
                INSERT INTO messages (conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, role, cleaned, _utc_now()),
            )

    def recent_messages(self, limit: int = 20) -> list[tuple[str, str]]:
        with connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT role, content FROM messages
                ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [(str(row["role"]), str(row["content"])) for row in reversed(rows)]

    def ingest_file(self, path: Path, allow_paths: tuple[Path, ...]) -> DocumentInfo:
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"I couldn't find {path}")
        if is_blocked(resolved):
            raise PermissionError("That file type is blocked.")
        if not path_is_allowed(resolved, allow_paths):
            raise PermissionError("That path is outside the allowed folders.")
        size = resolved.stat().st_size
        if size > MAX_BYTES:
            raise ValueError("That file is too large to ingest.")
        text = extract_text(resolved)
        chunks = chunk_text(text)
        if not chunks:
            raise ValueError("I didn't find any text to index in that file.")

        stored_path = str(resolved)
        title = resolved.name
        now = _utc_now()
        with connect(self.db_path) as connection:
            existing = connection.execute(
                "SELECT id FROM documents WHERE path = ?", (stored_path,)
            ).fetchone()
            if existing:
                document_id = int(existing["id"])
                connection.execute(
                    "DELETE FROM document_chunks WHERE document_id = ?",
                    (document_id,),
                )
                connection.execute(
                    """
                    UPDATE documents
                    SET title = ?, mime = ?, bytes = ?, ingested_at = ?
                    WHERE id = ?
                    """,
                    (title, resolved.suffix.lower(), size, now, document_id),
                )
            else:
                cursor = connection.execute(
                    """
                    INSERT INTO documents (path, title, mime, bytes, ingested_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (stored_path, title, resolved.suffix.lower(), size, now),
                )
                document_id = int(cursor.lastrowid)
            rows = [
                (
                    document_id,
                    index,
                    chunk,
                    json.dumps(embed_text(chunk)),
                )
                for index, chunk in enumerate(chunks)
            ]
            connection.executemany(
                """
                INSERT INTO document_chunks (
                    document_id, chunk_index, text, embedding
                ) VALUES (?, ?, ?, ?)
                """,
                rows,
            )
        return DocumentInfo(
            id=document_id,
            path=stored_path,
            title=title,
            bytes=size,
            ingested_at=now,
            chunks=len(chunks),
        )

    def list_documents(self, limit: int = 50) -> list[DocumentInfo]:
        with connect(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT d.*, COUNT(c.id) AS chunks
                FROM documents d
                LEFT JOIN document_chunks c ON c.document_id = d.id
                GROUP BY d.id
                ORDER BY d.id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [_document_from_row(row) for row in rows]

    def add_note(self, content: str) -> Note:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Nothing to note.")
        now = _utc_now()
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                "INSERT INTO notes (content, created_at) VALUES (?, ?)",
                (cleaned, now),
            )
            note_id = int(cursor.lastrowid)
        return self.get_note(note_id)

    def get_note(self, note_id: int) -> Note:
        with connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"No note {note_id}")
        return _note_from_row(row)

    def list_notes(self, limit: int = 30) -> list[Note]:
        with connect(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM notes ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_note_from_row(row) for row in rows]

    def delete_note(self, note_id: int) -> bool:
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM notes WHERE id = ?", (note_id,)
            )
            return cursor.rowcount > 0

    def add_reminder(self, content: str, *, due_at: str | None = None) -> Reminder:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Nothing to remind.")
        now = _utc_now()
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT INTO reminders (content, due_at, status, created_at)
                VALUES (?, ?, 'open', ?)
                """,
                (cleaned, due_at, now),
            )
            reminder_id = int(cursor.lastrowid)
        return self.get_reminder(reminder_id)

    def get_reminder(self, reminder_id: int) -> Reminder:
        with connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM reminders WHERE id = ?", (reminder_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"No reminder {reminder_id}")
        return _reminder_from_row(row)

    def list_reminders(self, *, include_done: bool = False, limit: int = 30) -> list[Reminder]:
        with connect(self.db_path) as connection:
            if include_done:
                rows = connection.execute(
                    "SELECT * FROM reminders ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM reminders
                    WHERE status = 'open'
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [_reminder_from_row(row) for row in rows]

    def due_reminders(self, *, now: datetime | None = None) -> list[Reminder]:
        current = now or datetime.now().astimezone()
        due: list[Reminder] = []
        for item in self.list_reminders(include_done=False, limit=50):
            if not item.due_at:
                continue
            try:
                when = datetime.fromisoformat(item.due_at)
            except ValueError:
                continue
            if when.tzinfo is None:
                when = when.replace(tzinfo=current.tzinfo)
            if when <= current:
                due.append(item)
        return due

    def complete_reminder(self, reminder_id: int) -> bool:
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE reminders SET status = 'done' WHERE id = ? AND status = 'open'",
                (reminder_id,),
            )
            return cursor.rowcount > 0

    def delete_reminder(self, reminder_id: int) -> bool:
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM reminders WHERE id = ?", (reminder_id,)
            )
            return cursor.rowcount > 0

    def add_task(self, content: str) -> TaskItem:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Nothing to add as a task.")
        now = _utc_now()
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                "INSERT INTO tasks (content, status, created_at) VALUES (?, 'open', ?)",
                (cleaned, now),
            )
            task_id = int(cursor.lastrowid)
        return self.get_task(task_id)

    def get_task(self, task_id: int) -> TaskItem:
        with connect(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
        if row is None:
            raise KeyError(f"No task {task_id}")
        return _task_from_row(row)

    def list_tasks(self, *, include_done: bool = False, limit: int = 30) -> list[TaskItem]:
        with connect(self.db_path) as connection:
            if include_done:
                rows = connection.execute(
                    "SELECT * FROM tasks ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = connection.execute(
                    """
                    SELECT * FROM tasks
                    WHERE status = 'open'
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return [_task_from_row(row) for row in rows]

    def complete_task(self, needle: str) -> TaskItem | None:
        text = needle.strip().lower()
        if not text:
            return None
        if text.isdigit():
            task_id = int(text)
            with connect(self.db_path) as connection:
                cursor = connection.execute(
                    "UPDATE tasks SET status = 'done' WHERE id = ? AND status = 'open'",
                    (task_id,),
                )
                if cursor.rowcount <= 0:
                    return None
            return self.get_task(task_id)
        open_tasks = self.list_tasks(include_done=False, limit=50)
        match = next(
            (item for item in open_tasks if text in item.content.lower()),
            None,
        )
        if match is None:
            return None
        with connect(self.db_path) as connection:
            connection.execute(
                "UPDATE tasks SET status = 'done' WHERE id = ? AND status = 'open'",
                (match.id,),
            )
        return self.get_task(match.id)

    def delete_document(self, document_id: int) -> bool:
        with connect(self.db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM documents WHERE id = ?", (document_id,)
            )
            return cursor.rowcount > 0

    def search(self, query: str, limit: int = 5) -> list[SearchHit]:
        needle = query.strip()
        if not needle:
            return []
        query_vec = embed_text(needle)
        hits: list[SearchHit] = []
        with connect(self.db_path) as connection:
            for row in connection.execute("SELECT id, content FROM memories"):
                content = str(row["content"])
                score = _relevance_score(needle, content, query_vec)
                hits.append(
                    SearchHit(
                        text=content,
                        score=score,
                        source="memory",
                        title="memory",
                        memory_id=int(row["id"]),
                    )
                )
            chunk_rows = connection.execute(
                """
                SELECT c.text, c.embedding, d.id AS document_id, d.path, d.title
                FROM document_chunks c
                JOIN documents d ON d.id = c.document_id
                """
            ).fetchall()
        for row in chunk_rows:
            text = str(row["text"])
            score = _relevance_score(needle, text, query_vec)
            hits.append(
                SearchHit(
                    text=str(row["text"]),
                    score=score,
                    source=str(row["path"]),
                    title=str(row["title"]),
                    document_id=int(row["document_id"]),
                )
            )
        hits.sort(key=lambda item: item.score, reverse=True)
        return [hit for hit in hits if hit.score > 0.08][:limit]

    def _ensure_conversation(self, connection: sqlite3.Connection) -> int:
        if self._conversation_id is not None:
            return self._conversation_id
        cursor = connection.execute(
            "INSERT INTO conversations (started_at) VALUES (?)",
            (_utc_now(),),
        )
        self._conversation_id = int(cursor.lastrowid)
        return self._conversation_id


def _memory_from_row(row: sqlite3.Row) -> Memory:
    return Memory(
        id=int(row["id"]),
        kind=str(row["kind"]),
        content=str(row["content"]),
        source=str(row["source"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _document_from_row(row: sqlite3.Row) -> DocumentInfo:
    chunks = row["chunks"] if "chunks" in row.keys() else 0
    return DocumentInfo(
        id=int(row["id"]),
        path=str(row["path"]),
        title=str(row["title"]),
        bytes=int(row["bytes"] or 0),
        ingested_at=str(row["ingested_at"]),
        chunks=int(chunks or 0),
    )


def _note_from_row(row: sqlite3.Row) -> Note:
    return Note(
        id=int(row["id"]),
        content=str(row["content"]),
        created_at=str(row["created_at"]),
    )


def _reminder_from_row(row: sqlite3.Row) -> Reminder:
    due = row["due_at"]
    return Reminder(
        id=int(row["id"]),
        content=str(row["content"]),
        due_at=str(due) if due else None,
        status=str(row["status"]),
        created_at=str(row["created_at"]),
    )


def _task_from_row(row: sqlite3.Row) -> TaskItem:
    return TaskItem(
        id=int(row["id"]),
        content=str(row["content"]),
        status=str(row["status"]),
        created_at=str(row["created_at"]),
    )


def _audit_from_row(row: sqlite3.Row) -> AuditEntry:
    ok_raw = row["ok"]
    return AuditEntry(
        id=int(row["id"]),
        created_at=str(row["created_at"]),
        event=str(row["event"] or ""),
        task_id=str(row["task_id"] or ""),
        tool=str(row["tool"] or ""),
        agent=str(row["agent"] or ""),
        risk_level=str(row["risk_level"] or ""),
        ok=bool(ok_raw) if ok_raw is not None else False,
        input_hash=str(row["input_hash"] or ""),
        observation=str(row["observation"] or ""),
        error=str(row["error"] or ""),
    )


def _event_from_row(row: sqlite3.Row) -> EventLog:
    duration = row["duration_ms"]
    return EventLog(
        id=int(row["id"]),
        created_at=str(row["created_at"]),
        event=str(row["event"] or ""),
        task_id=str(row["task_id"] or ""),
        intent=str(row["intent"] or ""),
        tool=str(row["tool"] or ""),
        tools=str(row["tools"] or ""),
        status=str(row["status"] or ""),
        observation=str(row["observation"] or ""),
        error=str(row["error"] or ""),
        duration_ms=int(duration) if duration is not None else None,
        request=str(row["request"] or ""),
    )
