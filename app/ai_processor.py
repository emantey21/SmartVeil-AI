import time
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

OBJECT_LABELS = {
    0: "person", 1: "bicycle", 2: "car", 3: "motorcycle",
    4: "airplane", 5: "bus", 6: "train", 7: "truck",
    8: "boat", 9: "traffic light", 10: "fire hydrant",
    11: "stop sign", 12: "parking meter", 13: "bench",
    14: "bird", 15: "cat", 16: "dog", 17: "horse",
    18: "sheep", 19: "cow", 20: "elephant", 21: "bear",
    22: "zebra", 23: "giraffe", 24: "backpack",
    25: "umbrella", 26: "handbag", 27: "tie",
    28: "suitcase", 29: "frisbee", 30: "skis",
    31: "snowboard", 32: "sports ball", 33: "kite",
    34: "baseball bat", 35: "baseball glove", 36: "skateboard",
    37: "surfboard", 38: "tennis racket", 39: "bottle",
    40: "wine glass", 41: "cup", 42: "fork",
    43: "knife", 44: "spoon", 45: "bowl",
    46: "banana", 47: "apple", 48: "sandwich",
    49: "orange", 50: "broccoli", 51: "carrot",
    52: "hot dog", 53: "pizza", 54: "donut",
    55: "cake", 56: "chair", 57: "couch",
    58: "potted plant", 59: "bed", 60: "dining table",
    61: "toilet", 62: "tv", 63: "laptop",
    64: "mouse", 65: "remote", 66: "keyboard",
    67: "cell phone", 68: "microwave", 69: "oven",
    70: "toaster", 71: "sink", 72: "refrigerator",
    73: "book", 74: "clock", 75: "vase",
    76: "scissors", 77: "teddy bear", 78: "hair drier",
    79: "toothbrush",
}

_yolo_model = None


def _get_yolo():
    global _yolo_model
    if _yolo_model is None:
        try:
            from ultralytics import YOLO
            _yolo_model = YOLO("yolov8n.pt")
            _yolo_model.conf = 0.15
            _yolo_model.overrides["imgsz"] = 1280
        except Exception:
            pass
    return _yolo_model


class AIProcessor:
    def __init__(self, enable_motion: bool = True, enable_detection: bool = False):
        self._enable_motion = enable_motion
        self._enable_detection = enable_detection
        self._bg_subtractor = None
        self._model = None
        self._last_motion = 0.0
        self._motion_cooldown = 1.0

        if enable_motion:
            self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
                history=500, varThreshold=36, detectShadows=False
            )

        if enable_detection:
            self._model = _get_yolo()

    def process(self, frame: np.ndarray) -> tuple:
        result = frame.copy()
        detections = []
        motion = False

        if self._enable_motion and self._bg_subtractor:
            motion, result = self._detect_motion(frame, result)

        if self._enable_detection and self._model:
            results = self._model(frame, verbose=False)
            for r in results:
                for box in r.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cls = int(box.cls[0])
                    conf = float(box.conf[0])
                    label = OBJECT_LABELS.get(cls, f"obj_{cls}")
                    detections.append((x1, y1, x2, y2, label, conf))
                    if cls == 0:
                        color = (0, 0, 255)
                    elif cls in (1, 2, 3, 5, 7):
                        color = (255, 0, 0)
                    else:
                        color = (0, 255, 0)
                    cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
                    label_text = f"{label} {conf:.0%}"
                    (tw, th), _ = cv2.getTextSize(label_text, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
                    cv2.rectangle(result, (x1, y1 - th - 4), (x1 + tw + 4, y1), color, -1)
                    cv2.putText(result, label_text, (x1 + 2, y1 - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        return result, motion, detections

    def _detect_motion(self, frame: np.ndarray, display: np.ndarray) -> tuple:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        fgmask = self._bg_subtractor.apply(blur)
        fgmask = cv2.erode(fgmask, None, iterations=1)
        fgmask = cv2.dilate(fgmask, None, iterations=2)
        contours, _ = cv2.findContours(fgmask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        motion = False
        for cnt in contours:
            if cv2.contourArea(cnt) > 300:
                motion = True
                x, y, w, h = cv2.boundingRect(cnt)
                cv2.rectangle(display, (x, y), (x + w, y + h), (0, 0, 255), 2)

        return motion, display

    def set_motion(self, enabled: bool):
        self._enable_motion = enabled
        if enabled and not self._bg_subtractor:
            self._bg_subtractor = cv2.createBackgroundSubtractorMOG2(
                history=500, varThreshold=36, detectShadows=False
            )
        elif not enabled:
            self._bg_subtractor = None

    def set_detection(self, enabled: bool):
        self._enable_detection = enabled
        if enabled and not self._model:
            self._model = _get_yolo()
