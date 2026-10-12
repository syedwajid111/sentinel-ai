"""
Maintains per-track motion history (used to derive speed and dwell time
for the behavior rules) on top of the raw detections from YOLODetector.
"""
import time
from collections import defaultdict, deque


class TrackHistory:
    def __init__(self, max_history=30):
        self.max_history = max_history
        self.history = defaultdict(lambda: deque(maxlen=max_history))  # track_id -> deque[(t, cx, cy)]
        self.first_seen = {}
        self.last_seen = {}
        self.zone_entry_time = {}  # (track_id, zone_name) -> timestamp

    def update(self, detections):
        now = time.time()
        seen_ids = set()
        for det in detections:
            tid = det["track_id"]
            cx, cy = det["centroid"]
            self.history[tid].append((now, cx, cy))
            self.last_seen[tid] = now
            self.first_seen.setdefault(tid, now)
            seen_ids.add(tid)
        return seen_ids

    def speed_px_per_sec(self, track_id):
        pts = self.history.get(track_id)
        if not pts or len(pts) < 2:
            return 0.0
        (t0, x0, y0), (t1, x1, y1) = pts[0], pts[-1]
        dt = t1 - t0
        if dt <= 0:
            return 0.0
        dist = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        return dist / dt

    def presence_frames(self, track_id):
        return len(self.history.get(track_id, []))

    def mark_zone_entry(self, track_id, zone_name):
        self.zone_entry_time.setdefault((track_id, zone_name), time.time())

    def clear_zone_entry(self, track_id, zone_name):
        self.zone_entry_time.pop((track_id, zone_name), None)

    def dwell_time(self, track_id, zone_name):
        start = self.zone_entry_time.get((track_id, zone_name))
        if start is None:
            return 0.0
        return time.time() - start

    def purge_stale(self, seen_ids):
        """Extension point — kept for future cleanup of very old, inactive tracks."""
        return
