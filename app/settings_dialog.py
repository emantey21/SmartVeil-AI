import configparser
import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QSpinBox, QComboBox, QPushButton,
    QListWidget, QListWidgetItem, QFileDialog, QProgressBar,
    QMessageBox, QFormLayout, QGroupBox, QGridLayout,
)

from app.discovery import discover_network


class SettingsDialog(QDialog):
    def __init__(self, config_path: str, parent=None):
        super().__init__(parent)
        self.config_path = config_path
        self.config = configparser.ConfigParser()
        self.config.read(config_path)
        self._discovery_running = False

        self.setWindowTitle("Settings")
        self.resize(600, 500)
        self.setStyleSheet( "QDialog { background: #1a1a1a; color: white; }"
                           "QTabWidget::pane { background: #222; }"
                           "QTabBar::tab { background: #333; color: white; padding: 6px 16px; }"
                           "QTabBar::tab:selected { background: #555; }"
                           "QLabel { color: #ddd; }"
                           "QLineEdit, QSpinBox, QComboBox { background: #333; color: white; border: 1px solid #555; padding: 4px; }"
                           "QPushButton { background: #555; color: white; padding: 4px 12px; border-radius: 4px; }"
                           "QPushButton:hover { background: #777; }"
                           "QListWidget { background: #333; color: white; border: 1px solid #555; }"
                           "QProgressBar { background: #333; border: 1px solid #555; text-align: center; color: white; }"
                           "QProgressBar::chunk { background: #2a5; }")

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._build_general_tab()
        self._build_cameras_tab()
        self._build_discovery_tab()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.clicked.connect(self._save)
        btn_layout.addWidget(self.save_btn)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)
        layout.addLayout(btn_layout)

    def _build_general_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        form.setSpacing(8)

        settings = self.config["settings"] if "settings" in self.config else self.config["DEFAULT"]

        self.base_dir_edit = QLineEdit(settings.get("base_dir", str(Path.home() / "CCTV")))
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse_base_dir)
        h = QHBoxLayout()
        h.addWidget(self.base_dir_edit, 1)
        h.addWidget(browse_btn)
        form.addRow("Base directory:", h)

        self.segment_time_spin = QSpinBox()
        self.segment_time_spin.setRange(60, 86400)
        self.segment_time_spin.setValue(settings.getint("segment_time", 600))
        self.segment_time_spin.setSuffix(" seconds")
        form.addRow("Segment length:", self.segment_time_spin)

        self.transport_combo = QComboBox()
        self.transport_combo.addItems(["tcp", "udp"])
        self.transport_combo.setCurrentText(settings.get("rtsp_transport", "tcp"))
        form.addRow("RTSP transport:", self.transport_combo)

        self.max_fps_spin = QSpinBox()
        self.max_fps_spin.setRange(1, 60)
        self.max_fps_spin.setValue(settings.getint("max_fps", 10))
        self.max_fps_spin.setSuffix(" fps")
        form.addRow("Max FPS:", self.max_fps_spin)

        self.tabs.addTab(tab, "General")

    def _build_cameras_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.cam_list = QListWidget()
        self.cam_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        for name, url in self.config["channels"].items():
            item = QListWidgetItem(f"{name}  —  {url}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.cam_list.addItem(item)
        layout.addWidget(self.cam_list)

        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_camera)
        btn_layout.addWidget(self.add_btn)

        self.edit_btn = QPushButton("Edit")
        self.edit_btn.clicked.connect(self._edit_camera)
        btn_layout.addWidget(self.edit_btn)

        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove_camera)
        btn_layout.addWidget(self.remove_btn)

        btn_layout.addStretch()

        self.deselect_btn = QPushButton("Deselect All")
        self.deselect_btn.clicked.connect(self.cam_list.clearSelection)
        btn_layout.addWidget(self.deselect_btn)

        layout.addLayout(btn_layout)
        self.tabs.addTab(tab, "Cameras")

    def _build_discovery_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel("Scan local network for RTSP cameras.")
        info.setStyleSheet("color: #aaa;")
        layout.addWidget(info)

        net_layout = QHBoxLayout()
        net_layout.addWidget(QLabel("Subnet:"))
        self.subnet_edit = QLineEdit("192.168.8.0/24")
        net_layout.addWidget(self.subnet_edit)

        net_layout.addWidget(QLabel("Ports:"))
        self.ports_edit = QLineEdit("554, 8554, 1935")
        self.ports_edit.setToolTip("Comma-separated list of ports")
        net_layout.addWidget(self.ports_edit)

        self.scan_btn = QPushButton("Scan Network")
        self.scan_btn.clicked.connect(self._start_discovery)
        net_layout.addWidget(self.scan_btn)
        layout.addLayout(net_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.discovery_list = QListWidget()
        self.discovery_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        layout.addWidget(self.discovery_list)

        status_layout = QHBoxLayout()
        self.check_all_btn = QPushButton("Check All Status")
        self.check_all_btn.clicked.connect(self._check_all_status)
        status_layout.addWidget(self.check_all_btn)

        self.status_info = QLabel("")
        self.status_info.setStyleSheet("color: #aaa;")
        status_layout.addWidget(self.status_info, 1)
        layout.addLayout(status_layout)

        disc_btn_layout = QHBoxLayout()
        self.preview_btn = QPushButton("Preview")
        self.preview_btn.clicked.connect(self._preview_discovered)
        disc_btn_layout.addWidget(self.preview_btn)

        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.clicked.connect(self.discovery_list.selectAll)
        disc_btn_layout.addWidget(self.select_all_btn)

        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.clicked.connect(self.discovery_list.clearSelection)
        disc_btn_layout.addWidget(self.deselect_all_btn)

        disc_btn_layout.addStretch()
        layout.addLayout(disc_btn_layout)

        add_found_btn = QPushButton("Add Selected to Cameras")
        add_found_btn.clicked.connect(self._add_discovered)
        layout.addWidget(add_found_btn)

        self.tabs.addTab(tab, "Discovery")

    def _browse_base_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select base directory")
        if path:
            self.base_dir_edit.setText(path)

    def _add_camera(self):
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Add Camera", "Camera name:")
        if not ok or not name:
            return
        url, ok = QInputDialog.getText(self, "Add Camera", "RTSP URL:",
                                        text="rtsp://192.168.8.200:554/avstream/channel=1/stream=0.sdp")
        if not ok or not url:
            return
        item = QListWidgetItem(f"{name}  —  {url}")
        item.setData(Qt.ItemDataRole.UserRole, name)
        self.cam_list.addItem(item)

    def _edit_camera(self):
        item = self.cam_list.currentItem()
        if not item:
            return
        old_name = item.data(Qt.ItemDataRole.UserRole)
        text = item.text()
        from PySide6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(self, "Edit Camera", "Camera name:", text=old_name)
        if not ok or not name:
            return
        old_url = text.split("  —  ")[1] if "  —  " in text else ""
        url, ok = QInputDialog.getText(self, "Edit Camera", "RTSP URL:", text=old_url)
        if not ok or not url:
            return
        item.setText(f"{name}  —  {url}")
        item.setData(Qt.ItemDataRole.UserRole, name)

    def _remove_camera(self):
        for item in self.cam_list.selectedItems():
            self.cam_list.takeItem(self.cam_list.row(item))

    def _start_discovery(self):
        if self._discovery_running:
            return
        self._discovery_running = True
        self.scan_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.discovery_list.clear()
        subnet = self.subnet_edit.text().strip()
        ports = [int(p.strip()) for p in self.ports_edit.text().split(",") if p.strip().isdigit()]

        from app.discovery import expand_urls
        extra_paths = list(self.config["channels"].values())

        self._scan_progress = {"done": 0, "total": 1}
        self._scan_results = []

        def scan():
            try:
                def progress(done, total):
                    self._scan_progress["done"] = done
                    self._scan_progress["total"] = total
                results = discover_network(subnet=subnet, ports=ports,
                                           progress_callback=progress,
                                           extra_paths=extra_paths)
                self._scan_results = results
            except Exception as e:
                self._scan_error = str(e)
            finally:
                self._discovery_running = False

        self._scan_error = None
        threading.Thread(target=scan, daemon=True).start()

        self._scan_timer = QTimer()
        self._scan_timer.timeout.connect(self._poll_scan)
        self._scan_timer.start(100)

    def _poll_scan(self):
        self.progress_bar.setMaximum(self._scan_progress["total"])
        self.progress_bar.setValue(self._scan_progress["done"])

        if self._discovery_running:
            return

        self._scan_timer.stop()
        self.progress_bar.setVisible(False)
        self.scan_btn.setEnabled(True)

        if self._scan_error:
            QMessageBox.warning(self, "Discovery Error", self._scan_error)
            return

        for r in self._scan_results:
            for url in r["urls"]:
                from app.discovery import quality_label
                qlabel = quality_label(url)
                item = QListWidgetItem(f"🟡 [{qlabel}] {r['ip']}  —  {url}")
                item.setData(Qt.ItemDataRole.UserRole, url)
                item.setData(Qt.ItemDataRole.UserRole + 1, "unknown")
                self.discovery_list.addItem(item)

    def _check_all_status(self):
        self.check_all_btn.setEnabled(False)
        self.status_info.setText("Checking...")
        items = [self.discovery_list.item(i) for i in range(self.discovery_list.count())]

        def check():
            online = 0
            offline = 0
            for item in items:
                url = item.data(Qt.ItemDataRole.UserRole)
                status = self._probe_camera(url)
                from app.discovery import quality_label
                qlabel = quality_label(url)
                ip = url.split("://")[1].split(":")[0]
                item.setText(f"{'🟢 online' if status else '🔴 offline'}  [{qlabel}] {ip}  —  {url}")
                item.setData(Qt.ItemDataRole.UserRole + 1, "online" if status else "offline")
                if status:
                    online += 1
                else:
                    offline += 1
            self.status_info.setText(f"{online} online, {offline} offline")
            self.check_all_btn.setEnabled(True)

        threading.Thread(target=check, daemon=True).start()

    def _probe_camera(self, url: str) -> bool:
        try:
            import cv2
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2000)
            ret, frame = cap.read()
            cap.release()
            return ret
        except Exception:
            return False

    def _add_discovered(self):
        selected = self.discovery_list.selectedItems()
        if not selected:
            QMessageBox.information(self, "Add Cameras", "No cameras selected.")
            return
        existing = set()
        for i in range(self.cam_list.count()):
            existing.add(self.cam_list.item(i).data(Qt.ItemDataRole.UserRole))
        from app.discovery import quality_label
        count = 0
        for item in selected:
            url = item.data(Qt.ItemDataRole.UserRole)
            ip = url.split("://")[1].split(":")[0]
            qlabel = quality_label(url)
            base_name = f"Camera_{ip.replace('.', '_')}_{qlabel}"
            name = base_name
            suffix = 1
            while name in existing:
                suffix += 1
                name = f"{base_name}_{suffix}"
            existing.add(name)
            list_item = QListWidgetItem(f"{name}  —  {url}")
            list_item.setData(Qt.ItemDataRole.UserRole, name)
            self.cam_list.addItem(list_item)
            count += 1
        msg = f"Added {count} camera(s) to the Cameras list.\nGo to the Cameras tab to review, then click Save."
        QMessageBox.information(self, "Cameras Added", msg)

    def _preview_discovered(self):
        item = self.discovery_list.currentItem()
        if not item:
            QMessageBox.information(self, "Preview", "Select a camera to preview.")
            return
        url = item.data(Qt.ItemDataRole.UserRole)
        if not url:
            return
        status = item.data(Qt.ItemDataRole.UserRole + 1)
        if status == "offline":
            reply = QMessageBox.question(
                self, "Camera Offline",
                "This camera appears to be offline. Try preview anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        QMessageBox.information(self, "Preview", "Opening ffplay preview window...")
        import subprocess
        subprocess.Popen(["ffplay", "-rtsp_transport", "tcp", "-window_title", f"Preview",
                          "-fflags", "nobuffer", "-flags", "low_delay",
                          "-framedrop", "-strict", "experimental", url])

    def _save(self):
        if "settings" not in self.config:
            self.config["settings"] = {}
        s = self.config["settings"]
        s["base_dir"] = self.base_dir_edit.text()
        s["segment_time"] = str(self.segment_time_spin.value())
        s["rtsp_transport"] = self.transport_combo.currentText()
        s["max_fps"] = str(self.max_fps_spin.value())

        self.config["channels"] = {}
        for i in range(self.cam_list.count()):
            item = self.cam_list.item(i)
            name = item.data(Qt.ItemDataRole.UserRole)
            url = item.text().split("  —  ")[1]
            self.config["channels"][name] = url

        with open(self.config_path, "w") as f:
            self.config.write(f)

        self.accept()
