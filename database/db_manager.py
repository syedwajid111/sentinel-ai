"""SQLite persistence for surveillance events."""
import os
import sqlite3
import time
from contextlib import contextmanager

_SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


class DBManager:
    def __init__(self, db_path):
        self.db_path = db_path
        self._init_schema()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_schema(self):
        with open(_SCHEMA_PATH, "r") as f:
            schema = f.read()
        with self._connect() as conn:
            conn.executescript(schema)

    def insert_event(self, track_id, rule, zone, message, severity, timestamp=None, snapshot_path=""):
        timestamp = timestamp or time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO events (track_id, rule, zone, message, severity, timestamp, snapshot_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (track_id, rule, zone, message, severity, timestamp, snapshot_path),
            )

    def fetch_events(self, limit=200, rule=None, severity=None, since=None):
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        if rule:
            query += " AND rule = ?"
            params.append(rule)
        if severity:
            query += " AND severity = ?"
            params.append(severity)
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def stats_by_rule(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT rule, COUNT(*) as count FROM events GROUP BY rule ORDER BY count DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def stats_by_zone(self):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT zone, COUNT(*) as count FROM events WHERE zone != '' GROUP BY zone ORDER BY count DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    # ---------------- Incidents (written by the autonomous Incident Agent) ----------------
    def insert_incident(self, pattern, title, risk_score, severity, zone, event_ids, reasoning,
                        action_taken="", timestamp=None):
        timestamp = timestamp or time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO incidents (pattern, title, risk_score, severity, zone, event_ids, reasoning, "
                "action_taken, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pattern, title, int(risk_score), severity, zone or "",
                 ",".join(str(i) for i in event_ids), reasoning, action_taken, timestamp),
            )
            return cur.lastrowid

    def fetch_incidents(self, limit=100, since=None):
        query = "SELECT * FROM incidents WHERE 1=1"
        params = []
        if since:
            query += " AND timestamp >= ?"
            params.append(since)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(query, params).fetchall()]

    def incident_exists(self, pattern, event_ids):
        key = ",".join(str(i) for i in event_ids)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM incidents WHERE pattern = ? AND event_ids = ? LIMIT 1", (pattern, key)
            ).fetchone()
            return row is not None

    def fetch_events_between(self, start_ts, end_ts):
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp ASC",
                (start_ts, end_ts),
            ).fetchall()
            return [dict(r) for r in rows]

    def clear_all(self):
        with self._connect() as conn:
            conn.execute("DELETE FROM events")
            conn.execute("DELETE FROM incidents")

    def insert_event_returning_id(self, track_id, rule, zone, message, severity, timestamp=None, snapshot_path=""):
        timestamp = timestamp or time.time()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO events (track_id, rule, zone, message, severity, timestamp, snapshot_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (track_id, rule, zone, message, severity, timestamp, snapshot_path),
            )
            return cur.lastrowid

    def total_count(self):
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) as c FROM events").fetchone()
            return row["c"] if row else 0
