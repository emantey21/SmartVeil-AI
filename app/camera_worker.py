import os
import time

import cv2
import numpy as np
from PySide6.QtCore import QThread, Signal, QMutex
from PySide6.QtGui import QImage

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


class CameraWorker(QThread):
    frame_ready = Signal(QImage, str, bool, list)
    disconnected = Signal(str)

    def __init__(self, name: str, url: str, transport: str = "tcp",
                 max_fps: int = 15):
        super().__init__()
        self.name = name
        self.url = url
        self.transport = transport
        self._max_fps = max_fps
        self._min_interval = 1.0 / max_fps
        self._running = False
        self._cap = None
        self._mutex = QMutex()
        self._latest_frame = None
        self._ai_enabled = False
        self._ai_processor = None
        self._ai_frame_skip = 0
        self._ai_counter = 0

    def run(self):
        self._running = True
        self._cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        self._cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self._cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3000)
        self._cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3000)

        if not self._cap.isOpened():
            self.disconnected.emit(self.name)
            return

        last_emit = 0.0

        while self._running and self._cap.isOpened():
            try:
                ret, frame = self._cap.read()
                if not ret:
                    self.disconnected.emit(self.name)
                    break

                self._mutex.lock()
                self._latest_frame = frame.copy()
                self._mutex.unlock()

                motion = False
                detections = []
                display = frame

                if self._ai_enabled and self._ai_processor:
                    if self._ai_counter % max(1, self._ai_frame_skip) == 0:
                        annotated, motion, detections = self._ai_processor.process(frame)
                        display = annotated

                now = time.monotonic()
                if now - last_emit >= self._min_interval:
                    rgb = cv2.cvtColor(display, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb.shape
                    buf = rgb.tobytes()
                    qimg = QImage(buf, w, h, ch * w, QImage.Format.Format_RGB888)
                    self.frame_ready.emit(qimg.copy(), self.name, motion, detections)
                    last_emit = now
                else:
                    time.sleep(0.001)
                self._ai_counter += 1
            except RuntimeError:
                self.disconnected.emit(self.name)
                break

        self._cleanup()

    def enable_ai(self, motion: bool = True, detection: bool = False):
        from app.ai_processor import AIProcessor
        self._ai_processor = AIProcessor(enable_motion=motion, enable_detection=detection)
        self._ai_enabled = True
        self._ai_frame_skip = 5
        self._ai_counter = 0

    def disable_ai(self):
        self._ai_enabled = False
        self._ai_processor = None

    def get_ai_status(self) -> bool:
        return self._ai_enabled

    def get_latest_frame(self):
        self._mutex.lock()
        frame = self._latest_frame.copy() if self._latest_frame is not None else None
        self._mutex.unlock()
        return frame

    def stop(self):
        self._running = False
        if self.isRunning():
            self.wait(3000)
        self._cleanup()

    def _cleanup(self):
        if self._cap:
            self._cap.release()
            self._cap = None
