"""
Thin wrapper around Ultralytics YOLOv8 that performs detection + tracking
in a single call, restricted to the classes relevant to surveillance.
"""
import os
from ultralytics import YOLO
import config


class YOLODetector:
    def __init__(self, weights_path=None, confidence=None, iou=None):
        self.weights_path = weights_path or config.MODEL_WEIGHTS
        self.confidence = confidence or config.DEFAULT_CONFIDENCE
        self.iou = iou or config.DEFAULT_IOU
        bundled = os.path.join(config.BASE_DIR, "yolov8n.pt")
        if os.path.isfile(self.weights_path):
            weights = self.weights_path
        elif os.path.isfile(bundled):
            weights = bundled
        else:
            weights = "yolov8n.pt"  # auto-download as a last resort
        self.model = YOLO(weights)
        self.class_names = self.model.names

    def track(self, frame):
        """
        Run detection + ByteTrack tracking on a single BGR frame.
        Returns a list of dicts: {track_id, class_id, class_name, conf, box, centroid}
        """
        results = self.model.track(
            frame,
            persist=True,
            conf=self.confidence,
            iou=self.iou,
            tracker=config.TRACKER_CONFIG,
            classes=list(config.MONITORED_CLASSES.keys()),
            verbose=False,
        )
        detections = []
        if not results:
            return detections

        result = results[0]
        if result.boxes is None or result.boxes.id is None:
            return detections

        boxes = result.boxes.xyxy.cpu().numpy()
        ids = result.boxes.id.cpu().numpy().astype(int)
        confs = result.boxes.conf.cpu().numpy()
        cls_ids = result.boxes.cls.cpu().numpy().astype(int)

        for box, track_id, conf, cls_id in zip(boxes, ids, confs, cls_ids):
            x1, y1, x2, y2 = box
            cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
            detections.append({
                "track_id": int(track_id),
                "class_id": int(cls_id),
                "class_name": self.class_names.get(int(cls_id), str(cls_id)),
                "conf": float(conf),
                "box": (float(x1), float(y1), float(x2), float(y2)),
                "centroid": (float(cx), float(cy)),
            })
        return detections
