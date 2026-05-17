import configparser
import math
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QShortcut, QPixmap
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QScrollArea, QToolBar,
    QStatusBar, QLabel, QPushButton, QSizePolicy,
    QStackedWidget, QMessageBox, QDialog, QSpinBox,
)

from app.camera_worker import CameraWorker
from app.camera_widget import CameraWidget, DRAG_MIME
from app.recording_browser import RecordingBrowser
from app.settings_dialog import SettingsDialog


class DropGridContainer(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setSpacing(4)
        self.grid_layout.setContentsMargins(8, 8, 8, 8)
        self._main_win = parent

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(DRAG_MIME):
            event.acceptProposedAction()

    def dropEvent(self, event):
        source_name = event.mimeData().data(DRAG_MIME).data().decode()
        source_widget = event.source()
        if not isinstance(source_widget, CameraWidget):
            return

        target_widget = self.childAt(event.position().toPoint())
        while target_widget and not isinstance(target_widget, CameraWidget):
            target_widget = target_widget.parentWidget()

        if not target_widget or target_widget == source_widget:
            return

        src_idx = self.grid_layout.indexOf(source_widget)
        tgt_idx = self.grid_layout.indexOf(target_widget)
        if src_idx < 0 or tgt_idx < 0:
            return

        src_pos = self.grid_layout.getItemPosition(src_idx)
        tgt_pos = self.grid_layout.getItemPosition(tgt_idx)

        self.grid_layout.removeWidget(source_widget)
        self.grid_layout.removeWidget(target_widget)

        self.grid_layout.addWidget(source_widget, *tgt_pos)
        self.grid_layout.addWidget(target_widget, *src_pos)

        event.acceptProposedAction()

        if self._main_win and hasattr(self._main_win, '_on_grid_reordered'):
            self._main_win._on_grid_reordered()


class MainWindow(QMainWindow):
    def __init__(self, config_path: str):
        super().__init__()
        self.config_path = config_path
        self.config = self._load_config()
        self.workers: dict[str, CameraWorker] = {}
        self.widgets: dict[str, CameraWidget] = {}
        self._expanded_camera: str | None = None
        self._is_fullscreen = False
        self._resizing = False
        self._paused = False

        self.setWindowTitle("SmartVeil AI")
        self.resize(1280, 800)

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()
        self._setup_shortcuts()
        QTimer.singleShot(100, self._start_cameras)

    def _load_config(self):
        config = configparser.ConfigParser()
        config.read(self.config_path)
        return config

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        self.stacked = QStackedWidget()
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.stacked)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setStyleSheet("QScrollArea { background: #1a1a1a; border: none; }")

        self.grid_container = DropGridContainer(self)
        self.grid_layout = self.grid_container.grid_layout
        self.scroll.setWidget(self.grid_container)

        grid_page = QWidget()
        grid_page_layout = QVBoxLayout(grid_page)
        grid_page_layout.setContentsMargins(0, 0, 0, 0)

        self.ctrl_bar = QWidget()
        self.ctrl_bar.setFixedHeight(40)
        self.ctrl_bar.setStyleSheet("background: #222;")
        ctrl_layout = QHBoxLayout(self.ctrl_bar)
        ctrl_layout.setContentsMargins(8, 4, 8, 4)

        self.record_all_btn = QPushButton("Record All")
        self.record_all_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.record_all_btn.clicked.connect(self._toggle_record_all)
        ctrl_layout.addWidget(self.record_all_btn)

        self.screenshot_all_btn = QPushButton("Screenshot All")
        self.screenshot_all_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.screenshot_all_btn.clicked.connect(self._screenshot_all)
        ctrl_layout.addWidget(self.screenshot_all_btn)

        self.cam_pause_btn = QPushButton("⏸ Pause")
        self.cam_pause_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.cam_pause_btn.clicked.connect(self._toggle_pause_cameras)
        ctrl_layout.addWidget(self.cam_pause_btn)

        ctrl_layout.addStretch()

        ctrl_layout.addWidget(QLabel("Cols:"))
        self.cols_spin = QSpinBox()
        self.cols_spin.setRange(1, 8)
        self.cols_spin.setValue(4)
        self.cols_spin.setFixedWidth(50)
        self.cols_spin.setStyleSheet("QSpinBox { background: #333; color: white; border: 1px solid #555; padding: 2px; }")
        ctrl_layout.addWidget(self.cols_spin)

        self.rearrange_btn = QPushButton("Rearrange")
        self.rearrange_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; padding: 4px 12px; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.rearrange_btn.clicked.connect(self._rearrange_grid_by_columns)
        ctrl_layout.addWidget(self.rearrange_btn)

        grid_page_layout.addWidget(self.ctrl_bar)
        grid_page_layout.addWidget(self.scroll, 1)

        self.stacked.addWidget(grid_page)

        self.expanded_page = QWidget()
        self.expanded_page.setStyleSheet("background: #000;")
        expanded_layout = QVBoxLayout(self.expanded_page)
        expanded_layout.setContentsMargins(0, 0, 0, 0)

        self.expanded_top_bar = QWidget()
        self.expanded_top_bar.setFixedHeight(40)
        self.expanded_top_bar.setStyleSheet("background: #222;")
        exp_top_layout = QHBoxLayout(self.expanded_top_bar)
        exp_top_layout.setContentsMargins(8, 4, 8, 4)

        self.expanded_label = QLabel("")
        self.expanded_label.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        exp_top_layout.addWidget(self.expanded_label)

        exp_top_layout.addStretch()

        self.exp_rec_btn = QPushButton("REC")
        self.exp_rec_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; font-weight: bold; padding: 4px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.exp_rec_btn.clicked.connect(self._toggle_expanded_recording)
        exp_top_layout.addWidget(self.exp_rec_btn)

        self.exp_ss_btn = QPushButton("📷 Screenshot")
        self.exp_ss_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.exp_ss_btn.clicked.connect(self._screenshot_expanded)
        exp_top_layout.addWidget(self.exp_ss_btn)

        self.exp_back_btn = QPushButton("Back to Grid")
        self.exp_back_btn.setStyleSheet(
            "QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; }"
            "QPushButton:hover { background: #777; }"
        )
        self.exp_back_btn.clicked.connect(self._show_grid)
        exp_top_layout.addWidget(self.exp_back_btn)

        expanded_layout.addWidget(self.expanded_top_bar)

        self.expanded_video = QLabel()
        self.expanded_video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.expanded_video.setStyleSheet("background: #000;")
        self.expanded_video.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.expanded_video.setMouseTracking(True)
        expanded_layout.addWidget(self.expanded_video, 1)

        self._exp_pan_start = None
        self._exp_is_panning = False
        self.expanded_video.mousePressEvent = self._exp_video_press
        self.expanded_video.mouseMoveEvent = self._exp_video_move
        self.expanded_video.mouseReleaseEvent = self._exp_video_release

        self.expanded_page.wheelEvent = self._expanded_wheel

        self.stacked.addWidget(self.expanded_page)

    def _build_toolbar(self):
        toolbar = QToolBar("Main")
        toolbar.setStyleSheet(
            "QToolBar { background: #2a2a2a; border: none; padding: 2px; spacing: 4px; }"
            "QToolButton { color: white; background: #444; padding: 4px 12px; border-radius: 4px; }"
            "QToolButton:hover { background: #666; }"
        )
        self.addToolBar(toolbar)

        act_recordings = QAction("Recordings", self)
        act_recordings.triggered.connect(self._open_recordings)
        toolbar.addAction(act_recordings)

        toolbar.addSeparator()

        act_settings = QAction("Settings", self)
        act_settings.triggered.connect(self._open_settings)
        toolbar.addAction(act_settings)

        toolbar.addSeparator()

        act_grid = QAction("Grid View", self)
        act_grid.triggered.connect(self._show_grid)
        toolbar.addAction(act_grid)

        act_refresh = QAction("Refresh", self)
        act_refresh.triggered.connect(self._restart_cameras)
        toolbar.addAction(act_refresh)

    def _build_statusbar(self):
        self.status = QStatusBar()
        self.status.setStyleSheet("QStatusBar { background: #222; color: #aaa; }")
        self.cam_count = QLabel("Cameras: 0")
        self.status.addPermanentWidget(self.cam_count)
        self.setStatusBar(self.status)

    def _setup_shortcuts(self):
        QShortcut(QKeySequence(Qt.Key.Key_F11), self, self._toggle_fullscreen)
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self._handle_escape)
        QShortcut(QKeySequence("Ctrl+R"), self, self._restart_cameras)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self._screenshot_all)

    def _start_cameras(self):
        settings = self.config["settings"]
        base_dir = settings.get("base_dir", str(Path.home() / "CCTV"))
        transport = settings.get("rtsp_transport", "tcp")
        max_fps = settings.getint("max_fps", 10)

        channels = list(self.config["channels"].items())
        cols = max(1, math.ceil(math.sqrt(len(channels))))

        self._pending_cameras = list(enumerate(channels))
        self._cam_cols = cols
        self._cam_base_dir = base_dir
        self._cam_transport = transport
        self._cam_max_fps = max_fps
        QTimer.singleShot(2000, self._start_next_camera)

        self.cam_count.setText(f"Cameras: {len(channels)}")

    def _start_next_camera(self):
        if not self._pending_cameras:
            return
        idx, (name, url) = self._pending_cameras.pop(0)

        settings = self.config["settings"]
        widget = CameraWidget(name)
        widget.set_url(url)
        widget.set_base_dir(self._cam_base_dir)
        widget.setStyleSheet(
            "CameraWidget { background: #1a1a1a; border: 1px solid #333; border-radius: 4px; }"
        )
        widget.expanded.connect(self._expand_camera)
        widget.screenshot_taken.connect(self._on_screenshot)
        widget.rename_requested.connect(self._on_rename_channel)
        self.widgets[name] = widget

        row = idx // self._cam_cols
        col = idx % self._cam_cols
        self.grid_layout.addWidget(widget, row, col)

        worker = CameraWorker(name, url, transport=self._cam_transport, max_fps=self._cam_max_fps)
        worker.frame_ready.connect(self._on_frame)
        worker.disconnected.connect(self._on_disconnect)
        worker.start()
        widget.set_worker(worker)
        self.workers[name] = worker

        QTimer.singleShot(2000, self._start_next_camera)

    def _on_frame(self, qimage, name, motion, detections):
        widget = self.widgets.get(name)
        if widget:
            widget.update_frame(qimage)
            if motion and widget.motion_btn.isChecked():
                widget.status_label.setStyleSheet("color: #f80; font-size: 18px;")
            elif motion:
                widget.status_label.setStyleSheet("color: #0f0; font-size: 18px;")
            if detections:
                labels = [d[4] for d in detections]
                widget.label.setText(f"{name} [{','.join(labels)}]")
        if name == self._expanded_camera:
            self._update_expanded_view(qimage)

    def _update_expanded_view(self, qimage):
        pixmap = QPixmap.fromImage(qimage)
        vw, vh = self.expanded_video.width(), self.expanded_video.height()
        if vw <= 1 or vh <= 1:
            return

        widget = self.widgets.get(self._expanded_camera)
        z = widget.zoom() if widget else 1.0

        target = self.expanded_video.size() * z
        scaled = pixmap.scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

        if z > 1.0 and widget:
            sw, sh = scaled.width(), scaled.height()
            max_pan_x = max(0, sw - vw)
            max_pan_y = max(0, sh - vh)
            widget._pan_x = max(0, min(widget._pan_x, max_pan_x))
            widget._pan_y = max(0, min(widget._pan_y, max_pan_y))
            scaled = scaled.copy(int(widget._pan_x), int(widget._pan_y), vw, vh)

        self.expanded_video.setPixmap(scaled)

    def _on_disconnect(self, name):
        widget = self.widgets.get(name)
        if widget:
            widget.mark_offline()

    def _expand_camera(self, name):
        self._expanded_camera = name
        self.expanded_label.setText(f"📹 {name}")
        widget = self.widgets.get(name)
        if widget:
            self.exp_rec_btn.setText("STOP" if widget.is_recording() else "REC")
            self.exp_rec_btn.setStyleSheet(
                "QPushButton { background: #c00; color: white; font-weight: bold; padding: 4px 16px; border-radius: 4px; }"
                "QPushButton:hover { background: #e00; }"
                if widget.is_recording() else
                "QPushButton { background: #555; color: white; font-weight: bold; padding: 4px 16px; border-radius: 4px; }"
                "QPushButton:hover { background: #777; }"
            )
        self.stacked.setCurrentIndex(1)
        self.status.showMessage(f"Viewing: {name}", 3000)

    def _show_grid(self):
        self._expanded_camera = None
        self.stacked.setCurrentIndex(0)
        self.status.showMessage("Grid view", 2000)

    def _rearrange_grid_by_columns(self):
        cols = self.cols_spin.value()
        channels = list(self.config["channels"].items())
        if not channels or not self.widgets:
            return

        for i in range(self.grid_layout.count()):
            item = self.grid_layout.itemAt(0)
            if item and item.widget():
                self.grid_layout.removeWidget(item.widget())

        for idx, (name, url) in enumerate(channels):
            widget = self.widgets.get(name)
            if widget:
                row = idx // cols
                col = idx % cols
                self.grid_layout.addWidget(widget, row, col)

        self.status.showMessage(f"Grid rearranged to {cols} columns", 2000)

    def _toggle_expanded_recording(self):
        if self._expanded_camera:
            widget = self.widgets.get(self._expanded_camera)
            if widget:
                widget._toggle_recording()
                self.exp_rec_btn.setText("STOP" if widget.is_recording() else "REC")

    def _screenshot_expanded(self):
        if self._expanded_camera:
            widget = self.widgets.get(self._expanded_camera)
            if widget:
                widget.take_screenshot()

    def _screenshot_all(self):
        count = 0
        for name, widget in self.widgets.items():
            widget.take_screenshot()
            count += 1
        self.status.showMessage(f"Snapshots saved for {count} cameras", 3000)

    def _on_screenshot(self, name, path):
        self.status.showMessage(f"Screenshot saved: {path}", 5000)

    def _on_rename_channel(self, old_name, new_name):
        if old_name in self.widgets:
            self.widgets[new_name] = self.widgets.pop(old_name)
        if old_name in self.workers:
            self.workers[new_name] = self.workers.pop(old_name)

        url = self.config["channels"].pop(old_name, None)
        if url:
            self.config["channels"][new_name] = url

        with open(self.config_path, "w") as f:
            self.config.write(f)

        if self._expanded_camera == old_name:
            self._expanded_camera = new_name
            self.expanded_label.setText(f"📹 {new_name}")

        self.status.showMessage(f"Renamed {old_name} → {new_name}", 3000)

    def _toggle_pause_cameras(self):
        if self._paused:
            self.cam_pause_btn.setText("⏸ Pause")
            for name in list(self.widgets.keys()):
                if name not in self.workers:
                    self._pending_cameras = [(0, (name, self.widgets[name]._url))]
                    self._start_next_camera()
            self._paused = False
            self.status.showMessage("Cameras resumed", 2000)
        else:
            for worker in list(self.workers.values()):
                worker.stop()
            self.workers.clear()
            self.cam_pause_btn.setText("▶ Resume")
            self._paused = True
            self.status.showMessage("Cameras paused", 2000)

    def _toggle_record_all(self):
        recording_any = any(w.is_recording() for w in self.widgets.values())
        if recording_any:
            self._stop_all_recordings()
        else:
            for widget in self.widgets.values():
                if not widget.is_recording():
                    widget._toggle_recording()
            self.record_all_btn.setText("Stop All")
            self.status.showMessage("Recording all channels", 3000)

    def _stop_all_recordings(self):
        for widget in self.widgets.values():
            if widget.is_recording():
                widget._stop_recording()
        self.record_all_btn.setText("Record All")
        self.status.showMessage("Stopped all recordings", 3000)
        if self._expanded_camera:
            self.exp_rec_btn.setText("REC")

    def _toggle_fullscreen(self):
        if self._is_fullscreen:
            self.showNormal()
        else:
            self.showFullScreen()
        self._is_fullscreen = not self._is_fullscreen

    def _handle_escape(self):
        if self._is_fullscreen:
            self.showNormal()
            self._is_fullscreen = False
        elif self.stacked.currentIndex() == 1:
            self._show_grid()

    def _open_recordings(self):
        settings = self.config["settings"]
        base_dir = settings.get("base_dir", str(Path.home() / "CCTV"))
        browser = RecordingBrowser(base_dir, self)
        browser.exec()

    def _on_grid_reordered(self):
        names = []
        for i in range(self.grid_layout.count()):
            w = self.grid_layout.itemAt(i).widget()
            if isinstance(w, CameraWidget):
                names.append(w.name)
        self.status.showMessage("Grid rearranged", 2000)

    def _restart_cameras(self):
        for worker in self.workers.values():
            worker.stop()
        self.workers.clear()
        self._start_cameras()
        self.status.showMessage("Cameras restarted", 3000)

    def _open_settings(self):
        old_channels = dict(self.config["channels"])
        dialog = SettingsDialog(self.config_path, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config = self._load_config()
            new_channels = dict(self.config["channels"])

            for name in list(old_channels):
                if name not in new_channels:
                    if name in self.workers:
                        self.workers[name].stop()
                        del self.workers[name]
                    if name in self.widgets:
                        w = self.widgets.pop(name)
                        self.grid_layout.removeWidget(w)
                        w.deleteLater()

            for name, url in new_channels.items():
                if name not in old_channels:
                    settings = self.config["settings"]
                    transport = settings.get("rtsp_transport", "tcp")
                    max_fps = settings.getint("max_fps", 15)
                    base_dir = settings.get("base_dir", str(Path.home() / "CCTV"))

                    widget = CameraWidget(name)
                    widget.set_url(url)
                    widget.set_base_dir(base_dir)
                    widget.setStyleSheet(
                        "CameraWidget { background: #1a1a1a; border: 1px solid #333; border-radius: 4px; }"
                    )
                    widget.expanded.connect(self._expand_camera)
                    widget.screenshot_taken.connect(self._on_screenshot)
                    widget.rename_requested.connect(self._on_rename_channel)
                    self.widgets[name] = widget

                    import math
                    ch_list = list(new_channels.keys())
                    idx = ch_list.index(name)
                    cols = max(1, math.ceil(math.sqrt(len(new_channels))))
                    self.grid_layout.addWidget(widget, idx // cols, idx % cols)

                    worker = CameraWorker(name, url, transport=transport, max_fps=max_fps)
                    worker.frame_ready.connect(self._on_frame)
                    worker.disconnected.connect(self._on_disconnect)
                    QTimer.singleShot(100, worker.start)
                    widget.set_worker(worker)
                    self.workers[name] = worker

                elif old_channels[name] != url:
                    if name in self.workers:
                        self.workers[name].stop()
                        del self.workers[name]
                    settings = self.config["settings"]
                    transport = settings.get("rtsp_transport", "tcp")
                    max_fps = settings.getint("max_fps", 15)
                    worker = CameraWorker(name, url, transport=transport, max_fps=max_fps)
                    worker.frame_ready.connect(self._on_frame)
                    worker.disconnected.connect(self._on_disconnect)
                    QTimer.singleShot(100, worker.start)
                    widget = self.widgets.get(name)
                    if widget:
                        widget.set_url(url)
                        widget.set_worker(worker)
                    self.workers[name] = worker

            self.cam_count.setText(f"Cameras: {len(new_channels)}")
            self.status.showMessage("Settings saved", 3000)

    def _exp_video_press(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._exp_pan_start = event.position().toPoint()
            widget = self.widgets.get(self._expanded_camera)
            if widget and widget.zoom() > 1.0:
                self._exp_is_panning = True

    def _exp_video_move(self, event):
        if self._exp_is_panning and self._exp_pan_start and self._expanded_camera:
            widget = self.widgets.get(self._expanded_camera)
            if widget and widget._pixmap:
                dx = event.position().x() - self._exp_pan_start.x()
                dy = event.position().y() - self._exp_pan_start.y()
                widget._pan_x -= dx
                widget._pan_y -= dy
                self._exp_pan_start = event.position().toPoint()
                self._update_expanded_view(widget._pixmap.toImage())

    def _exp_video_release(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._exp_is_panning = False
            self._exp_pan_start = None

    def _expanded_wheel(self, event):
        if self._expanded_camera:
            widget = self.widgets.get(self._expanded_camera)
            if widget and widget._pixmap:
                delta = event.angleDelta().y()
                if delta > 0:
                    widget.set_zoom(widget.zoom() + 0.3)
                else:
                    widget.set_zoom(widget.zoom() - 0.3)
                if widget.zoom() <= 1.0:
                    widget._pan_x = 0
                    widget._pan_y = 0
                self._update_expanded_view(widget._pixmap.toImage())
                self.expanded_label.setText(
                    f"📹 {self._expanded_camera} [{widget.zoom():.1f}x]"
                    if widget.zoom() > 1.0 else f"📹 {self._expanded_camera}"
                )
                self.expanded_video.setCursor(Qt.CursorShape.ArrowCursor)
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, '_resizing') and self._resizing:
            return
        self._resizing = True
        if self._expanded_camera and self.expanded_video.pixmap():
            widget = self.widgets.get(self._expanded_camera)
            if widget and widget._pixmap:
                self._update_expanded_view(widget._pixmap.toImage())
        self._resizing = False

    def closeEvent(self, event):
        for worker in self.workers.values():
            worker.stop()
        self.workers.clear()
        self._stop_all_recordings()
        event.accept()
