from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QImage
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QLabel, QHeaderView, QPushButton, QSlider, QWidget,
    QFileDialog, QMessageBox,
)


class RecordingBrowser(QDialog):
    def __init__(self, base_dir: str, parent=None):
        super().__init__(parent)
        self.base_dir = Path(base_dir)
        self._current_player = None

        self.setWindowTitle("Recording Browser")
        self.resize(800, 600)
        self.setStyleSheet("QDialog { background: #1a1a1a; color: white; }")

        layout = QVBoxLayout(self)

        info = QLabel(f"Base: {self.base_dir}")
        info.setStyleSheet("color: #888; padding: 4px;")
        layout.addWidget(info)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Date / File", "Size"])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.setAlternatingRowColors(True)
        self.tree.setStyleSheet(
            "QTreeWidget { background: #222; color: white; border: 1px solid #444; }"
            "QTreeWidget::item:selected { background: #444; }"
            "QTreeWidget::item:alternate { background: #2a2a2a; }"
        )
        self.tree.itemDoubleClicked.connect(self._play_selected)
        layout.addWidget(self.tree)

        btn_layout = QHBoxLayout()

        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setStyleSheet("QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; } QPushButton:hover { background: #777; }")
        self.refresh_btn.clicked.connect(self.load)
        btn_layout.addWidget(self.refresh_btn)

        self.play_btn = QPushButton("▶ Play")
        self.play_btn.setStyleSheet("QPushButton { background: #2a5; color: white; padding: 4px 16px; border-radius: 4px; } QPushButton:hover { background: #3a7; }")
        self.play_btn.clicked.connect(self._play_selected)
        btn_layout.addWidget(self.play_btn)

        self.open_folder_btn = QPushButton("📂 Open Folder")
        self.open_folder_btn.setStyleSheet("QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; } QPushButton:hover { background: #777; }")
        self.open_folder_btn.clicked.connect(self._open_selected_folder)
        btn_layout.addWidget(self.open_folder_btn)

        self.delete_btn = QPushButton("🗑 Delete")
        self.delete_btn.setStyleSheet("QPushButton { background: #a33; color: white; padding: 4px 16px; border-radius: 4px; } QPushButton:hover { background: #c55; }")
        self.delete_btn.clicked.connect(self._delete_selected)
        btn_layout.addWidget(self.delete_btn)

        btn_layout.addStretch()
        self.close_btn = QPushButton("Close")
        self.close_btn.setStyleSheet("QPushButton { background: #555; color: white; padding: 4px 16px; border-radius: 4px; } QPushButton:hover { background: #777; }")
        self.close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.load()

    def load(self):
        self.tree.clear()
        if not self.base_dir.exists():
            item = QTreeWidgetItem([f"Directory not found: {self.base_dir}"])
            self.tree.addTopLevelItem(item)
            return

        for channel_dir in sorted(self.base_dir.iterdir()):
            if not channel_dir.is_dir():
                continue
            channel_item = QTreeWidgetItem([channel_dir.name])
            channel_item.setData(0, Qt.ItemDataRole.UserRole, str(channel_dir))

            for date_dir in sorted(channel_dir.iterdir(), reverse=True):
                date_item = QTreeWidgetItem([date_dir.name])
                date_item.setData(0, Qt.ItemDataRole.UserRole, str(date_dir))

                for video in sorted(date_dir.glob("*.mp4")):
                    size = video.stat().st_size
                    size_str = self._format_size(size)
                    video_item = QTreeWidgetItem([video.name, size_str])
                    video_item.setData(0, Qt.ItemDataRole.UserRole, str(video))
                    date_item.addChild(video_item)

                if date_item.childCount() > 0:
                    channel_item.addChild(date_item)

            if channel_item.childCount() > 0:
                self.tree.addTopLevelItem(channel_item)
                channel_item.setExpanded(True)

    def _play_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or not path.endswith(".mp4"):
            return
        import subprocess
        subprocess.Popen(["ffplay", "-autoexit", "-window_title", f"Playback: {item.text(0)}", path])

    def _open_selected_folder(self):
        item = self.tree.currentItem()
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path:
            return
        p = Path(path)
        if p.is_file():
            p = p.parent
        import subprocess
        subprocess.Popen(["xdg-open", str(p)])

    def _delete_selected(self):
        item = self.tree.currentItem()
        if not item:
            return
        path = item.data(0, Qt.ItemDataRole.UserRole)
        if not path or not path.endswith(".mp4"):
            QMessageBox.information(self, "Delete", "Select a video file to delete.")
            return
        reply = QMessageBox.question(
            self, "Confirm Delete",
            f"Delete {Path(path).name}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            Path(path).unlink()
            self.load()

    def _format_size(self, bytes_: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if bytes_ < 1024:
                return f"{bytes_:.1f} {unit}"
            bytes_ /= 1024
        return f"{bytes_:.1f} TB"
