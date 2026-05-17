from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal, QMimeData, QPoint, QEvent
from PySide6.QtGui import QPixmap, QAction, QFont, QDrag
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPushButton, QHBoxLayout,
    QSizePolicy, QMenu, QInputDialog, QMessageBox,
)

DRAG_MIME = "application/x-smarthome-camera"


class CameraWidget(QWidget):
    expanded = Signal(str)
    screenshot_taken = Signal(str, str)
    rename_requested = Signal(str, str)

    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self._recording = False
        self._rec_process = None
        self._offline = False
        self._pixmap = None
        self._zoom = 1.0
        self._pan_x = 0.0
        self._pan_y = 0.0
        self._url = ""
        self._base_dir = str(Path.home() / "CCTV")
        self._worker = None
        self._drag_start = None
        self._is_panning = False
        self._rendering = False

        self.setMinimumSize(320, 240)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(2)

        self.label = QLabel(name)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("font-weight: bold; color: white; background: #333; padding: 2px; border-radius: 2px;")
        layout.addWidget(self.label)

        self.video = QLabel()
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setStyleSheet("background: #111; border: 1px solid #444;")
        self.video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.video.setMinimumSize(320, 200)
        self.video.installEventFilter(self)
        layout.addWidget(self.video, 1)

        btn_layout = QHBoxLayout()
        self.record_btn = QPushButton("REC")
        self.record_btn.setFixedHeight(28)
        self.record_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; font-weight: bold; border-radius: 4px; padding: 2px 8px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.record_btn.clicked.connect(self._toggle_recording)
        btn_layout.addWidget(self.record_btn)

        self.ss_btn = QPushButton("📷")
        self.ss_btn.setFixedSize(28, 28)
        self.ss_btn.setToolTip("Take snapshot")
        self.ss_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.ss_btn.clicked.connect(self.take_screenshot)
        btn_layout.addWidget(self.ss_btn)

        self.motion_btn = QPushButton("🔄")
        self.motion_btn.setFixedSize(28, 28)
        self.motion_btn.setToolTip("Toggle motion detection")
        self.motion_btn.setCheckable(True)
        self.motion_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
            "QPushButton:checked { background: #f80; }"
        )
        self.motion_btn.clicked.connect(self._toggle_ai_motion)
        btn_layout.addWidget(self.motion_btn)

        self.detect_btn = QPushButton("🧠")
        self.detect_btn.setFixedSize(28, 28)
        self.detect_btn.setToolTip("Toggle object detection (YOLO)")
        self.detect_btn.setCheckable(True)
        self.detect_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
            "QPushButton:checked { background: #080; }"
        )
        self.detect_btn.clicked.connect(self._toggle_ai_detection)
        btn_layout.addWidget(self.detect_btn)

        self.status_label = QLabel("●")
        self.status_label.setFixedWidth(20)
        self.status_label.setStyleSheet("color: #0f0; font-size: 18px;")
        btn_layout.addWidget(self.status_label)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def set_worker(self, worker):
        self._worker = worker

    def update_frame(self, qimage):
        if self._rendering:
            return
        self._offline = False
        self._pixmap = QPixmap.fromImage(qimage)
        self._render_frame()
        self.status_label.setStyleSheet("color: #0f0; font-size: 18px;")
        self.video.setStyleSheet("background: #111; border: 1px solid #444;")

    def _render_frame(self):
        if self._rendering or not self._pixmap:
            return
        self._rendering = True
        vw, vh = self.video.width(), self.video.height()
        if vw <= 1 or vh <= 1:
            self._rendering = False
            return

        base = self.video.size()
        target = base * self._zoom
        scaled = self._pixmap.scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        if self._zoom > 1.0:
            sw, sh = scaled.width(), scaled.height()
            max_pan_x = max(0, sw - vw)
            max_pan_y = max(0, sh - vh)
            self._pan_x = max(0, min(self._pan_x, max_pan_x))
            self._pan_y = max(0, min(self._pan_y, max_pan_y))
            cx, cy = int(self._pan_x), int(self._pan_y)
            cw, ch = min(vw, sw - cx), min(vh, sh - cy)
            if cw > 0 and ch > 0:
                scaled = scaled.copy(cx, cy, cw, ch)

        self.video.setPixmap(scaled)
        self._rendering = False

    def mark_offline(self):
        self._offline = True
        self.video.setText("OFFLINE")
        self.video.setStyleSheet("background: #300; color: #f44; border: 1px solid #644; font-size: 24px;")
        self.status_label.setStyleSheet("color: #f00; font-size: 18px;")

    def resizeEvent(self, event):
        if not self._rendering and self._pixmap and not self._offline:
            self._render_frame()
        super().resizeEvent(event)

    def _zoom_wheel(self, direction: int):
        if not self._pixmap or self._offline:
            return
        old_zoom = self._zoom
        if direction > 0:
            self._zoom = min(5.0, self._zoom + 0.3)
        else:
            self._zoom = max(1.0, self._zoom - 0.3)

        vw, vh = self.video.width(), self.video.height()
        if vw > 1 and vh > 1 and old_zoom != self._zoom and old_zoom > 1.0:
            cx = self._pan_x + vw / 2
            cy = self._pan_y + vh / 2
            ratio = self._zoom / old_zoom
            self._pan_x = cx * ratio - vw / 2
            self._pan_y = cy * ratio - vh / 2

        if self._zoom <= 1.0:
            self._pan_x = 0
            self._pan_y = 0

        self._render_frame()
        self._update_zoom_label()

    def eventFilter(self, obj, event):
        if obj is self.video and event.type() == QEvent.Type.Wheel:
            if self._pixmap and not self._offline and event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                delta = event.angleDelta().y()
                self._zoom_wheel(1 if delta > 0 else -1)
                return True
            return False
        return super().eventFilter(obj, event)

    def _update_zoom_label(self):
        if self._zoom > 1.0:
            self.label.setText(f"{self.name} [{self._zoom:.1f}x]")
        else:
            self.label.setText(self.name)

    def mouseDoubleClickEvent(self, event):
        self.expanded.emit(self.name)
        event.accept()

    def _show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background: #2a2a2a; color: white; border: 1px solid #555; }"
            "QMenu::item:selected { background: #444; }"
        )

        expand_act = QAction("Expand", self)
        expand_act.triggered.connect(lambda: self.expanded.emit(self.name))
        menu.addAction(expand_act)

        ss_act = QAction("Screenshot", self)
        ss_act.triggered.connect(self.take_screenshot)
        menu.addAction(ss_act)

        menu.addSeparator()

        rec_act = QAction("Stop Recording" if self._recording else "Start Recording", self)
        rec_act.triggered.connect(self._toggle_recording)
        menu.addAction(rec_act)

        menu.addSeparator()

        rename_act = QAction("Rename", self)
        rename_act.triggered.connect(self._rename_channel)
        menu.addAction(rename_act)

        reset_act = QAction("Reset Zoom", self)
        reset_act.triggered.connect(self._reset_zoom)
        menu.addAction(reset_act)

        menu.exec(self.mapToGlobal(pos))

    def _rename_channel(self):
        new_name, ok = QInputDialog.getText(self, "Rename Channel", "New name:", text=self.name)
        if ok and new_name and new_name != self.name:
            old_name = self.name
            self.name = new_name
            self.label.setText(new_name)
            self.rename_requested.emit(old_name, new_name)

    def take_screenshot(self):
        if self._worker:
            frame = self._worker.get_latest_frame()
            if frame is not None:
                import cv2
                ss_dir = Path.home() / "Pictures" / "SmartVeil"
                ss_dir.mkdir(parents=True, exist_ok=True)
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = str(ss_dir / f"{self.name}_{ts}.jpg")
                cv2.imwrite(path, frame)
                self.screenshot_taken.emit(self.name, path)

    def _reset_zoom(self):
        self._zoom = 1.0
        self._pan_x = 0
        self._pan_y = 0
        self._render_frame()
        self.label.setText(self.name)

    def _toggle_recording(self):
        if self._recording:
            self._stop_recording()
        else:
            self._start_recording()

    def _start_recording(self):
        from recorder import ChannelRecorder
        rec = ChannelRecorder(
            name=self.name,
            url=self._url,
            base_dir=self._base_dir,
        )
        rec.start()
        self._rec_process = rec
        self._recording = True
        self.record_btn.setText("STOP")
        self.record_btn.setStyleSheet(
            "QPushButton { background: #c00; color: white; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background: #e00; }"
        )

    def _stop_recording(self):
        if self._rec_process:
            self._rec_process.stop()
            self._rec_process = None
        self._recording = False
        self.record_btn.setText("REC")
        self.record_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; font-weight: bold; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )

    def _toggle_ai_motion(self):
        if not self._worker:
            return
        if self.motion_btn.isChecked():
            self._worker.enable_ai(motion=True, detection=self.detect_btn.isChecked())
        else:
            if not self.detect_btn.isChecked():
                self._worker.disable_ai()
            else:
                self._worker.enable_ai(motion=False, detection=True)

    def _toggle_ai_detection(self):
        if not self._worker:
            return
        if self.detect_btn.isChecked():
            self._worker.enable_ai(motion=self.motion_btn.isChecked(), detection=True)
        else:
            if not self.motion_btn.isChecked():
                self._worker.disable_ai()
            else:
                self._worker.enable_ai(motion=True, detection=False)

    def set_url(self, url: str):
        self._url = url

    def set_base_dir(self, base_dir: str):
        self._base_dir = base_dir

    def is_recording(self) -> bool:
        return self._recording

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
            if self._zoom > 1.0:
                self._is_panning = True
                self.video.setCursor(Qt.CursorShape.ClosedHandCursor)
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._is_panning and self._zoom > 1.0:
            if self._pixmap and self._drag_start:
                dx = event.position().x() - self._drag_start.x()
                dy = event.position().y() - self._drag_start.y()
                self._pan_x -= dx
                self._pan_y -= dy
                self._drag_start = event.position().toPoint()
                self._render_frame()
            return
        if self._drag_start is None:
            return
        if self._zoom <= 1.0 and (event.position().toPoint() - self._drag_start).manhattanLength() >= 10:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(DRAG_MIME, self.name.encode())
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.MoveAction)
            self._drag_start = None

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._is_panning = False
            if self._zoom > 1.0:
                self.video.setCursor(Qt.CursorShape.ArrowCursor)
            self._drag_start = None
        super().mouseReleaseEvent(event)

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, z: float):
        self._zoom = max(1.0, min(5.0, z))
        if self._zoom <= 1.0:
            self._pan_x = 0
            self._pan_y = 0
        self._update_zoom_label()
