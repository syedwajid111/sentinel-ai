"""
Runs the full detect -> track -> evaluate -> alert pipeline in a background
thread, so the Streamlit UI thread never blocks on frame capture or inference.
The UI reads the latest annotated frame + stats via get_state().
"""
import threading
import time
from typing import Optional

import cv2

import config
from detection.detector import YOLODetector
from detection.tracker import TrackHistory
from detection.behavior_rules import BehaviorEngine
from utils.video_utils import preprocess_frame, draw_overlays
from utils.alert_manager import AlertManager


class VideoProcessor:
    def __init__(self, source=0, zones=None, confidence=None, iou=None, loop=False):
        self.source = source
        self.is_file = isinstance(source, str)
        self.loop = loop and self.is_file
        self.detector = YOLODetector(confidence=confidence, iou=iou)
        self.history = TrackHistory()
        self.engine = BehaviorEngine(zones=zones)
        self.alert_manager = AlertManager()

        self._cap = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._running = False

        self.latest_frame = None
        self.latest_alerts = []
        self.latest_incidents = []
        self._pending_alerts = []
        self.stats = {"fps": 0.0, "people_count": 0, "object_count": 0, "total_alerts": 0}

    def set_zones(self, zones):
        self.engine.set_zones(zones)

    def is_running(self):
        return self._running

    def start(self):
        if self._running:
            return
        self._cap = cv2.VideoCapture(self.source)
        if not self._cap.isOpened():
            raise RuntimeError(f"Could not open video source: {self.source}")
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        if self._cap is not None:
            self._cap.release()
            self._cap = None

    def get_state(self):
        with self._lock:
            frame = None if self.latest_frame is None else self.latest_frame.copy()
            return frame, list(self.latest_alerts), dict(self.stats)

    def pop_alerts(self):
        """Alerts raised since the last call, each returned exactly once (for the live UI)."""
        with self._lock:
            out, self._pending_alerts = self._pending_alerts, []
            return out

    def pop_incidents(self):
        """Incidents raised by the Incident Agent since the last call (for live UI toasts)."""
        with self._lock:
            out, self.latest_incidents = self.latest_incidents, []
            return out

    def _loop(self):
        prev_t = time.time()
        total_alerts = 0
        # Play video files at their real speed (otherwise a fast server finishes a clip in seconds)
        src_fps = self._cap.get(cv2.CAP_PROP_FPS) if self.is_file else 0
        frame_interval = 1.0 / src_fps if src_fps and src_fps > 1 else 0.0
        while self._running:
            t_start = time.time()
            ok, frame = self._cap.read()
            if not ok:
                if self.loop:
                    self._cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ok, frame = self._cap.read()
                if not ok:
                    self._running = False
                    break

            frame = preprocess_frame(frame, config.FRAME_WIDTH, config.FRAME_HEIGHT, config.APPLY_DENOISE)
            detections = self.detector.track(frame)
            seen_ids = self.history.update(detections)
            self.history.purge_stale(seen_ids)
            alerts = self.engine.evaluate(detections, self.history)

            for alert in alerts:
                self.alert_manager.handle(alert, frame)
            total_alerts += len(alerts)
            new_incidents, self.alert_manager.new_incidents = self.alert_manager.new_incidents, []

            annotated = draw_overlays(frame, detections, self.engine.zones, alerts)

            now = time.time()
            fps = 1.0 / max(now - prev_t, 1e-6)
            prev_t = now

            with self._lock:
                self.latest_frame = annotated
                self.latest_alerts = alerts
                self.latest_incidents.extend(new_incidents)
                self._pending_alerts.extend(alerts)
                self.stats = {
                    "fps": round(fps, 1),
                    "people_count": sum(1 for d in detections if d["class_id"] == config.PERSON_CLASS_ID),
                    "object_count": sum(1 for d in detections if d["class_id"] in config.VALUABLE_OBJECT_CLASS_IDS),
                    "total_alerts": total_alerts,
                }

            spare = frame_interval - (time.time() - t_start)
            if spare > 0:
                time.sleep(spare)
