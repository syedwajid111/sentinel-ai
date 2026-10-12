"""
Behavior rule engine: turns raw tracked detections + motion history into
security-relevant alerts (zone intrusion, loitering, running, object removal).

This is a heuristic, rule-based layer on top of YOLO detection + tracking —
it does NOT claim to recognize "theft" as a visual class, since no object
detector can do that. It flags patterns that correlate with theft/robbery
risk so a human can review the snapshot and decide.
"""
import time
from dataclasses import dataclass, field
from typing import List, Dict, Tuple

import cv2
import numpy as np

import config


@dataclass
class Alert:
    track_id: int
    rule: str
    message: str
    zone: str = ""
    severity: str = "warning"     # "info" | "warning" | "critical"
    timestamp: float = field(default_factory=time.time)


class BehaviorEngine:
    def __init__(self, zones: Dict[str, List[Tuple[int, int]]] = None):
        self.zones = zones or {}
        self._last_alert_time: Dict[Tuple[int, str], float] = {}
        self._object_last_seen_frame: Dict[int, int] = {}
        self._object_meta: Dict[int, dict] = {}
        self._frame_count = 0

    def set_zones(self, zones):
        self.zones = zones or {}

    def _cooldown_ok(self, track_id, rule):
        key = (track_id, rule)
        last = self._last_alert_time.get(key, 0)
        if time.time() - last >= config.ALERT_COOLDOWN_SECONDS:
            self._last_alert_time[key] = time.time()
            return True
        return False

    def _point_in_zone(self, point, polygon):
        if len(polygon) < 3:
            return False
        contour = np.array(polygon, dtype=np.int32)
        return cv2.pointPolygonTest(contour, point, False) >= 0

    def evaluate(self, detections: list, history) -> List[Alert]:
        self._frame_count += 1
        alerts: List[Alert] = []

        people = [d for d in detections if d["class_id"] == config.PERSON_CLASS_ID]
        objects = [d for d in detections if d["class_id"] in config.VALUABLE_OBJECT_CLASS_IDS]

        alerts += self._check_zone_and_loitering(people, history)
        alerts += self._check_running(people, history)
        alerts += self._check_object_removal(objects, people)
        return alerts

    # ---- Rule 1 & 2: restricted-zone intrusion + loitering ----
    def _check_zone_and_loitering(self, people, history) -> List[Alert]:
        alerts = []
        for person in people:
            tid = person["track_id"]
            cx, cy = person["centroid"]
            for zone_name, polygon in self.zones.items():
                inside = self._point_in_zone((cx, cy), polygon)
                if inside:
                    history.mark_zone_entry(tid, zone_name)
                    dwell = history.dwell_time(tid, zone_name)

                    if self._cooldown_ok(tid, f"zone:{zone_name}"):
                        alerts.append(Alert(
                            track_id=tid, rule="zone_intrusion", zone=zone_name,
                            message=f"Person #{tid} entered restricted zone '{zone_name}'",
                            severity="warning",
                        ))

                    if dwell >= config.LOITER_SECONDS and self._cooldown_ok(tid, f"loiter:{zone_name}"):
                        alerts.append(Alert(
                            track_id=tid, rule="loitering", zone=zone_name,
                            message=f"Person #{tid} has been loitering in '{zone_name}' for {dwell:.0f}s",
                            severity="critical",
                        ))
                else:
                    history.clear_zone_entry(tid, zone_name)
        return alerts

    # ---- Rule 3: running / sudden fast movement ----
    def _check_running(self, people, history) -> List[Alert]:
        alerts = []
        for person in people:
            tid = person["track_id"]
            speed = history.speed_px_per_sec(tid)
            if speed >= config.RUN_SPEED_PX_PER_SEC and self._cooldown_ok(tid, "running"):
                alerts.append(Alert(
                    track_id=tid, rule="running",
                    message=f"Person #{tid} moving at high speed ({speed:.0f}px/s) — possible fleeing",
                    severity="critical",
                ))
        return alerts

    # ---- Rule 4: object removal (an item that was stable, then vanished) ----
    def _check_object_removal(self, objects, people) -> List[Alert]:
        alerts = []

        for obj in objects:
            tid = obj["track_id"]
            meta = self._object_meta.setdefault(tid, {"frames_seen": 0, "class_name": obj["class_name"]})
            meta["frames_seen"] += 1
            meta["centroid"] = obj["centroid"]
            meta["class_name"] = obj["class_name"]
            self._object_last_seen_frame[tid] = self._frame_count

        for tid, last_frame in list(self._object_last_seen_frame.items()):
            meta = self._object_meta.get(tid)
            if not meta or meta["frames_seen"] < config.OBJECT_MIN_PRESENCE_FRAMES:
                continue
            gap = self._frame_count - last_frame
            if gap >= config.OBJECT_MISSING_FRAMES:  # fire exactly once, at the threshold
                near_person = self._person_was_nearby(meta["centroid"], people)
                if self._cooldown_ok(tid, "object_removed"):
                    severity = "warning" if near_person else "critical"
                    note = "a person was nearby" if near_person else "no person was nearby"
                    alerts.append(Alert(
                        track_id=tid, rule="object_removed",
                        message=(f"{meta['class_name'].capitalize()} #{tid} disappeared from view "
                                  f"({note}) — possible removal"),
                        severity=severity,
                    ))

        # Housekeeping: drop very old entries so dicts don't grow unbounded
        for tid in list(self._object_last_seen_frame):
            if self._frame_count - self._object_last_seen_frame[tid] > config.OBJECT_MISSING_FRAMES * 5:
                self._object_last_seen_frame.pop(tid, None)
                self._object_meta.pop(tid, None)

        return alerts

    def _person_was_nearby(self, centroid, people):
        cx, cy = centroid
        for p in people:
            px, py = p["centroid"]
            if ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 <= config.PERSON_PROXIMITY_PX:
                return True
        return False
