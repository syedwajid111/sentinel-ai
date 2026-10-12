"""
Autonomous Incident Agent  (perceive -> reason -> act)

The behavior engine produces *low-level* events one at a time (a person entered a
zone, an object vanished, someone ran). On their own these are noisy. This agent
runs automatically after every new event and looks at the recent event stream as a
whole. When several events line up into a known threat pattern it:

    1. raises a higher-level INCIDENT with a risk score (0-100),
    2. records WHY it decided that (reasoning, which events it linked),
    3. takes an action (escalate / notify) without a human asking it to.

It is deterministic and needs no internet, so it keeps working even if the LLM
assistant (agent/sentinel_agent.py) is offline. The LLM assistant then reads these
incidents through its tools to explain and report on them.
"""
import time
from dataclasses import dataclass, field
from typing import List

import config
from utils.logger import get_logger

logger = get_logger(__name__)

SUSPICIOUS_PRESENCE = {"loitering", "zone_intrusion"}


@dataclass
class Incident:
    pattern: str
    title: str
    risk_score: int
    severity: str
    zone: str
    event_ids: List[int]
    reasoning: str
    action_taken: str = ""
    timestamp: float = field(default_factory=time.time)


def _risk_to_severity(score):
    if score >= 75:
        return "critical"
    if score >= 45:
        return "warning"
    return "info"


class IncidentAgent:
    """Correlates recent events into incidents. Call `observe()` after each new event."""

    def __init__(self, db, notifier=None):
        self.db = db
        self.notifier = notifier  # optional callable(incident) used for escalation (e.g. email)

    # ------------------------------------------------------------------ public
    def observe(self, now=None) -> List[Incident]:
        """Look at the recent window of events and raise any new incidents."""
        now = now or time.time()
        window = self.db.fetch_events_between(now - config.INCIDENT_LOOKBACK_SECONDS, now + 1)
        if not window:
            return []

        candidates = []
        candidates += self._theft_patterns(window)
        candidates += self._unattended_removal(window)
        candidates += self._persistent_loitering(window)
        candidates += self._zone_crowding(window)

        raised = []
        for inc in candidates:
            if self.db.incident_exists(inc.pattern, inc.event_ids):
                continue
            inc.action_taken = self._act(inc)
            self.db.insert_incident(
                pattern=inc.pattern, title=inc.title, risk_score=inc.risk_score,
                severity=inc.severity, zone=inc.zone, event_ids=inc.event_ids,
                reasoning=inc.reasoning, action_taken=inc.action_taken, timestamp=inc.timestamp,
            )
            logger.info("INCIDENT [%s risk=%d] %s", inc.severity.upper(), inc.risk_score, inc.title)
            raised.append(inc)
        return raised

    def rescan_all(self):
        """Re-run correlation over the whole event history (used after loading demo data)."""
        events = self.db.fetch_events(limit=5000)
        if not events:
            return []
        raised = []
        for ev in sorted(events, key=lambda e: e["timestamp"]):
            raised += self.observe(now=ev["timestamp"])
        return raised

    # ------------------------------------------------------------------ action
    def _act(self, inc: Incident) -> str:
        if inc.severity == "critical":
            action = "ESCALATED: flagged for immediate guard review"
            if self.notifier is not None:
                try:
                    if self.notifier(inc):
                        action += " + email notification sent"
                except Exception as exc:  # never let notification failure break monitoring
                    logger.warning("Incident notifier failed: %s", exc)
            return action
        if inc.severity == "warning":
            return "Added to watch-list for review"
        return "Logged for record"

    # ------------------------------------------------------------------ patterns
    def _theft_patterns(self, window):
        """Suspicious presence -> object removed  (-> running = flight)."""
        out = []
        win = config.INCIDENT_LINK_SECONDS
        removals = [e for e in window if e["rule"] == "object_removed"]
        for rem in removals:
            before = [e for e in window
                      if e["rule"] in SUSPICIOUS_PRESENCE and 0 <= rem["timestamp"] - e["timestamp"] <= win]
            if not before:
                continue
            after_run = [e for e in window
                         if e["rule"] == "running" and 0 <= e["timestamp"] - rem["timestamp"] <= win]
            zone = next((e["zone"] for e in reversed(before) if e.get("zone")), "")
            linked = [e["id"] for e in before[-3:]] + [rem["id"]]

            if after_run:
                linked_flight = linked + [after_run[0]["id"]]
                score = 95
                out.append(Incident(
                    pattern="theft_and_flight",
                    title=f"Probable theft followed by flight{f' near {zone}' if zone else ''}",
                    risk_score=score, severity=_risk_to_severity(score), zone=zone,
                    event_ids=linked_flight, timestamp=after_run[0]["timestamp"],
                    reasoning=(f"{len(before)} suspicious-presence event(s) were followed within {win}s by "
                               f"'{rem['message']}', and then a person was seen running "
                               f"({after_run[0]['message']}). Presence + removal + fast exit is the "
                               f"classic theft signature."),
                ))
            else:
                score = 80 if any(e["rule"] == "loitering" for e in before) else 70
                out.append(Incident(
                    pattern="theft_sequence",
                    title=f"Possible theft: item removed after suspicious presence{f' in {zone}' if zone else ''}",
                    risk_score=score, severity=_risk_to_severity(score), zone=zone,
                    event_ids=linked, timestamp=rem["timestamp"],
                    reasoning=(f"'{rem['message']}' happened {rem['timestamp'] - before[-1]['timestamp']:.0f}s after "
                               f"{before[-1]['rule'].replace('_', ' ')} ({before[-1]['message']}). Linking these "
                               f"raises the removal from a single alert to a possible theft."),
                ))
        return out

    def _unattended_removal(self, window):
        out = []
        for e in window:
            if e["rule"] == "object_removed" and e["severity"] == "critical":
                score = 60
                out.append(Incident(
                    pattern="unattended_removal",
                    title="Valuable item vanished with no person nearby",
                    risk_score=score, severity=_risk_to_severity(score), zone=e.get("zone", ""),
                    event_ids=[e["id"]], timestamp=e["timestamp"],
                    reasoning=("An object that had been stable disappeared while no person was near it. This can be "
                               "an occlusion/camera issue or a removal outside the camera's view; needs human check."),
                ))
        return out

    def _persistent_loitering(self, window):
        out = []
        by_zone = {}
        for e in window:
            if e["rule"] == "loitering":
                by_zone.setdefault(e.get("zone", ""), []).append(e)
        for zone, evs in by_zone.items():
            if len(evs) >= config.INCIDENT_LOITER_REPEAT:
                # first N events in the window -> stable key, so we raise this once, not on every new alert
                ids = [e["id"] for e in evs[:config.INCIDENT_LOITER_REPEAT]]
                score = 55 + min(20, 5 * (len(evs) - config.INCIDENT_LOITER_REPEAT))
                out.append(Incident(
                    pattern="repeated_loitering",
                    title=f"Repeated loitering in '{zone or 'unknown zone'}' (possible casing)",
                    risk_score=score, severity=_risk_to_severity(score), zone=zone,
                    event_ids=ids, timestamp=evs[-1]["timestamp"],
                    reasoning=(f"{len(evs)} loitering alerts in the same zone within "
                               f"{config.INCIDENT_LOOKBACK_SECONDS // 60} minutes. Repeated lingering at one spot "
                               f"is a common sign of someone studying the area before acting."),
                ))
        return out

    def _zone_crowding(self, window):
        out = []
        by_zone = {}
        for e in window:
            if e["rule"] == "zone_intrusion":
                by_zone.setdefault(e.get("zone", ""), []).append(e)
        for zone, evs in by_zone.items():
            people = {e["track_id"] for e in evs}
            if len(people) >= config.INCIDENT_CROWD_PEOPLE:
                first_seen = {}
                for e in evs:
                    first_seen.setdefault(e["track_id"], e)
                recent = list(first_seen.values())[:config.INCIDENT_CROWD_PEOPLE]
                score = 50
                out.append(Incident(
                    pattern="zone_crowding",
                    title=f"{len(people)} different people entered restricted zone '{zone}'",
                    risk_score=score, severity=_risk_to_severity(score), zone=zone,
                    event_ids=[e["id"] for e in recent], timestamp=evs[-1]["timestamp"],
                    reasoning=(f"{len(people)} distinct tracked people entered '{zone}' in a short period. "
                               f"Group entry to a restricted area is unusual and worth checking."),
                ))
        return out
