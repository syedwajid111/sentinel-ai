"""
Tools the Sentinel AI Agent can call.

Each tool is a plain Python function over the surveillance database. The LLM never
touches the database directly: it decides WHICH tool to call with WHICH arguments,
we run it, and hand the result back. That is what makes this an agent rather than a
chatbot — its answers are grounded in the real event log, not made up.
"""
import json
import time
from collections import Counter

import config

RULES = ["zone_intrusion", "loitering", "running", "object_removed"]
SEVERITIES = ["info", "warning", "critical"]


def _fmt_ts(ts):
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


def _since(hours):
    try:
        hours = float(hours)
    except (TypeError, ValueError):
        hours = 24
    hours = max(0.05, min(hours, 24 * 30))
    return time.time() - hours * 3600, hours


def _slim_event(e):
    return {
        "id": e["id"], "time": _fmt_ts(e["timestamp"]), "type": e["rule"], "severity": e["severity"],
        "zone": e.get("zone") or None, "track_id": e["track_id"], "message": e["message"],
        "has_snapshot": bool(e.get("snapshot_path")),
    }


class SurveillanceTools:
    def __init__(self, db):
        self.db = db

    # ---------------------------------------------------------------- tools
    def get_security_overview(self, hours=24):
        since, hours = _since(hours)
        events = self.db.fetch_events(limit=5000, since=since)
        incidents = self.db.fetch_incidents(limit=500, since=since)
        by_type = Counter(e["rule"] for e in events)
        by_sev = Counter(e["severity"] for e in events)
        by_zone = Counter(e["zone"] for e in events if e.get("zone"))
        by_hour = Counter(time.strftime("%H:00", time.localtime(e["timestamp"])) for e in events)
        risk = max((i["risk_score"] for i in incidents), default=0)
        return {
            "period_hours": hours,
            "total_events": len(events),
            "events_by_type": dict(by_type),
            "events_by_severity": dict(by_sev),
            "events_by_zone": dict(by_zone),
            "busiest_hour": by_hour.most_common(1)[0][0] if by_hour else None,
            "incidents_raised": len(incidents),
            "highest_incident_risk": risk,
            "first_event": _fmt_ts(min(e["timestamp"] for e in events)) if events else None,
            "last_event": _fmt_ts(max(e["timestamp"] for e in events)) if events else None,
        }

    def search_events(self, event_type=None, severity=None, zone=None, hours=24, limit=20):
        since, _ = _since(hours)
        event_type = event_type if event_type in RULES else None
        severity = severity if severity in SEVERITIES else None
        try:
            limit = max(1, min(int(limit), 50))
        except (TypeError, ValueError):
            limit = 20
        events = self.db.fetch_events(limit=500, rule=event_type, severity=severity, since=since)
        if zone:
            events = [e for e in events if (e.get("zone") or "").lower() == str(zone).lower()]
        return {"count": len(events), "events": [_slim_event(e) for e in events[:limit]]}

    def get_incidents(self, hours=24, min_risk=0):
        since, _ = _since(hours)
        try:
            min_risk = int(min_risk)
        except (TypeError, ValueError):
            min_risk = 0
        rows = [i for i in self.db.fetch_incidents(limit=200, since=since) if i["risk_score"] >= min_risk]
        return {
            "count": len(rows),
            "incidents": [{
                "id": i["id"], "time": _fmt_ts(i["timestamp"]), "title": i["title"],
                "pattern": i["pattern"], "risk_score": i["risk_score"], "severity": i["severity"],
                "zone": i["zone"] or None, "linked_event_ids": i["event_ids"],
                "reasoning": i["reasoning"], "action_taken": i["action_taken"],
            } for i in rows[:30]],
        }

    def get_track_timeline(self, track_id):
        try:
            track_id = int(track_id)
        except (TypeError, ValueError):
            return {"error": "track_id must be a number"}
        events = [e for e in self.db.fetch_events(limit=5000) if e["track_id"] == track_id]
        events.sort(key=lambda e: e["timestamp"])
        return {"track_id": track_id, "count": len(events), "timeline": [_slim_event(e) for e in events[:40]]}

    def get_zone_risk_ranking(self, hours=24):
        since, _ = _since(hours)
        weights = {"info": 1, "warning": 3, "critical": 6}
        scores, counts = Counter(), Counter()
        for e in self.db.fetch_events(limit=5000, since=since):
            z = e.get("zone") or "outside zones"
            scores[z] += weights.get(e["severity"], 1)
            counts[z] += 1
        for i in self.db.fetch_incidents(limit=500, since=since):
            scores[i["zone"] or "outside zones"] += i["risk_score"] // 10
        return {"ranking": [{"zone": z, "risk_points": s, "events": counts[z]} for z, s in scores.most_common()]}

    def get_system_configuration(self):
        return {
            "detector": "YOLOv8n (COCO), classes: " + ", ".join(config.MONITORED_CLASSES.values()),
            "tracker": "ByteTrack",
            "confidence_threshold": config.DEFAULT_CONFIDENCE,
            "loiter_seconds": config.LOITER_SECONDS,
            "running_speed_px_per_sec": config.RUN_SPEED_PX_PER_SEC,
            "object_missing_frames": config.OBJECT_MISSING_FRAMES,
            "alert_cooldown_seconds": config.ALERT_COOLDOWN_SECONDS,
            "incident_link_window_seconds": config.INCIDENT_LINK_SECONDS,
        }

    # ---------------------------------------------------------------- dispatch
    def execute(self, name, arguments):
        fn = getattr(self, name, None)
        if fn is None or name.startswith("_") or name == "execute":
            return {"error": f"unknown tool '{name}'"}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
        try:
            return fn(**(arguments or {}))
        except TypeError as exc:
            return {"error": f"bad arguments for {name}: {exc}"}


def _tool(name, description, properties=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {}, "required": required or []},
    }}


_HOURS = {"type": "number", "description": "How many hours back to look (default 24)."}

TOOL_SCHEMAS = [
    _tool("get_security_overview",
          "Totals and breakdowns of all alerts in a time period (by type, severity, zone, busiest hour) plus "
          "how many incidents the incident agent raised. Use first for any 'how was today / summary' question.",
          {"hours": _HOURS}),
    _tool("search_events",
          "List individual low-level alerts, filtered by type, severity, zone and time.",
          {"event_type": {"type": "string", "enum": RULES},
           "severity": {"type": "string", "enum": SEVERITIES},
           "zone": {"type": "string", "description": "Exact zone name"},
           "hours": _HOURS,
           "limit": {"type": "integer", "description": "Max rows to return (1-50)"}}),
    _tool("get_incidents",
          "High-level incidents (e.g. probable theft) that the autonomous incident agent raised by linking "
          "several alerts, with risk score, reasoning and action taken.",
          {"hours": _HOURS, "min_risk": {"type": "integer", "description": "Only incidents with risk >= this"}}),
    _tool("get_track_timeline",
          "Everything one tracked person/object (by track id, e.g. 'Person #3') did, in time order.",
          {"track_id": {"type": "integer"}}, ["track_id"]),
    _tool("get_zone_risk_ranking",
          "Ranks zones by weighted risk (critical alerts and incidents count more).", {"hours": _HOURS}),
    _tool("get_system_configuration",
          "Detection model, tracker and the thresholds the behavior rules use. Use for 'how does it work' questions."),
]
