CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER NOT NULL,
    rule TEXT NOT NULL,
    zone TEXT,
    message TEXT NOT NULL,
    severity TEXT NOT NULL,
    timestamp REAL NOT NULL,
    snapshot_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events (timestamp);
CREATE INDEX IF NOT EXISTS idx_events_rule ON events (rule);

-- Incidents: higher-level threats inferred by the autonomous Incident Agent
-- by correlating several low-level events (e.g. loitering -> object removed -> running).
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    title TEXT NOT NULL,
    risk_score INTEGER NOT NULL,
    severity TEXT NOT NULL,
    zone TEXT,
    event_ids TEXT NOT NULL,
    reasoning TEXT NOT NULL,
    action_taken TEXT,
    timestamp REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_incidents_timestamp ON incidents (timestamp);
