CREATE TABLE IF NOT EXISTS event_logs (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    event TEXT NOT NULL,
    task_id TEXT,
    intent TEXT,
    tool TEXT,
    tools TEXT,
    status TEXT,
    observation TEXT,
    error TEXT,
    duration_ms INTEGER,
    request TEXT
);

CREATE INDEX IF NOT EXISTS idx_event_logs_created
    ON event_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_event_logs_task
    ON event_logs(task_id);
