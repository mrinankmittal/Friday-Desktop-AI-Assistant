CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY,
    created_at TEXT NOT NULL,
    event TEXT NOT NULL,
    task_id TEXT,
    tool TEXT,
    agent TEXT,
    risk_level TEXT,
    ok INTEGER,
    input_hash TEXT,
    observation TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created
    ON audit_logs(created_at);
