"""Frame preprocessing and overlay-drawing helpers."""
import cv2
import numpy as np

SEVERITY_COLORS = {
    "info": (255, 200, 120),
    "warning": (0, 165, 255),
    "critical": (0, 0, 255),
}
CLASS_COLOR = (80, 220, 120)
ZONE_COLOR = (255, 255, 0)


def preprocess_frame(frame, width, height, denoise=True):
    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_LINEAR)
    if denoise:
        frame = cv2.GaussianBlur(frame, (3, 3), 0)
    return frame


def draw_overlays(frame, detections, zones, alerts):
    out = frame.copy()

    for name, polygon in (zones or {}).items():
        if len(polygon) >= 3:
            pts = np.array(polygon, dtype=np.int32).reshape((-1, 1, 2))
            cv2.polylines(out, [pts], isClosed=True, color=ZONE_COLOR, thickness=2)
            cv2.putText(out, name, tuple(polygon[0]), cv2.FONT_HERSHEY_SIMPLEX,
                        0.55, ZONE_COLOR, 2, cv2.LINE_AA)

    flagged_ids = {a.track_id: a.severity for a in alerts}

    for det in detections:
        x1, y1, x2, y2 = map(int, det["box"])
        tid = det["track_id"]
        severity = flagged_ids.get(tid)
        color = SEVERITY_COLORS.get(severity, CLASS_COLOR)
        thickness = 3 if severity else 2
        cv2.rectangle(out, (x1, y1), (x2, y2), color, thickness)
        label = f"{det['class_name']} #{tid} {det['conf']:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        cv2.rectangle(out, (x1, max(0, y1 - th - 8)), (x1 + tw + 6, y1), color, -1)
        cv2.putText(out, label, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (0, 0, 0), 1, cv2.LINE_AA)

    return out
