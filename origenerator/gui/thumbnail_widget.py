from pathlib import Path

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, pyqtSignal


class ThumbnailWidget(QWidget):
    clicked = pyqtSignal(str)  # prompt_id

    def __init__(self, prompt_id: str, thumb_path: str | None, label_text: str, parent=None):
        super().__init__(parent)
        self.prompt_id = prompt_id
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(180, 200)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)

        self._image_label = QLabel()
        self._image_label.setFixedSize(172, 160)
        self._image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._image_label.setStyleSheet("border: 1px solid #3f3f3f; border-radius: 3px;")

        if thumb_path and Path(thumb_path).exists():
            pm = QPixmap(str(thumb_path))
            self._image_label.setPixmap(
                pm.scaled(172, 160, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
        else:
            self._image_label.setText("No preview")

        self._text_label = QLabel(label_text)
        self._text_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._text_label.setWordWrap(True)
        self._text_label.setMaximumHeight(30)

        layout.addWidget(self._image_label)
        layout.addWidget(self._text_label)

    def mousePressEvent(self, event):
        self.clicked.emit(self.prompt_id)
