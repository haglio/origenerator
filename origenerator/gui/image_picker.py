from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QPushButton, QLabel,
)
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtCore import Qt

from origenerator.config import COMFYUI_INPUT_DIR


class ImagePickerDialog(QDialog):
    def __init__(self, parent=None, directory: Path | None = None):
        super().__init__(parent)
        self.setWindowTitle("Select Input Image")
        self.setMinimumSize(500, 400)
        self._selected: str | None = None
        self._directory = directory or COMFYUI_INPUT_DIR

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Images in: {self._directory}"))

        self._list = QListWidget()
        self._list.setViewMode(QListWidget.ViewMode.IconMode)
        self._list.setIconSize(QPixmap(128, 128).size())
        self._list.setSpacing(8)
        self._populate()
        layout.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        ok_btn = QPushButton("Select")
        ok_btn.clicked.connect(self._on_ok)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _populate(self):
        if not self._directory.exists():
            return
        for f in sorted(self._directory.iterdir()):
            if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
                item = QListWidgetItem(f.name)
                pm = QPixmap(str(f))
                if not pm.isNull():
                    item.setIcon(QIcon(pm.scaled(
                        128, 128,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )))
                self._list.addItem(item)

    def _on_ok(self):
        current = self._list.currentItem()
        if current:
            self._selected = current.text()
            self.accept()

    def selected_image(self) -> str | None:
        return self._selected
