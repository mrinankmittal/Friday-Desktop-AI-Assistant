CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY,
    content TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status
    ON tasks(status, id);
