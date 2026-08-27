CREATE TABLE IF NOT EXISTS integrations (
    provider TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'disconnected',
    secret_ref TEXT NOT NULL,
    label TEXT,
    connected_at TEXT,
    updated_at TEXT NOT NULL
);
