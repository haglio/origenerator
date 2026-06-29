from PyQt6.QtWidgets import QFrame, QVBoxLayout, QGridLayout, QLabel, QWidget
from PyQt6.QtGui import QPixmap
from PyQt6.QtCore import Qt, QPoint, pyqtSignal


class FolderTile(QFrame):
    """A folder shown in the main view: a thumbnail collage plus name + count.

    Clicking drills into the folder; right-clicking asks for a context menu.
    Both signals carry the folder's stable key so the view can act on it.
    """

    clicked = pyqtSignal(str)
    context_requested = pyqtSignal(str, QPoint)

    def __init__(self, key, text, preview_paths, count, starred=False, parent=None):
        super().__init__(parent)
        self._key = key
        self.setObjectName("folderTile")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(180, 200)
        self.setStyleSheet(
            "#folderTile { border: 1px solid #3f3f3f; border-radius: 4px; }"
            "#folderTile:hover { border-color: #6f6f6f; }"
        )
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(
            lambda pos: self.context_requested.emit(self._key, self.mapToGlobal(pos))
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)
        layout.addWidget(self._build_collage(preview_paths))

        caption = QLabel(("★ " if starred else "") + text)
        caption.setWordWrap(True)
        caption.setMaximumHeight(30)
        layout.addWidget(caption)

        count_label = QLabel(f"{count} item{'s' if count != 1 else ''}")
        count_label.setStyleSheet("color: #9a9a9a; font-size: 10px;")
        layout.addWidget(count_label)

    @staticmethod
    def _build_collage(preview_paths) -> QWidget:
        collage = QWidget()
        grid = QGridLayout(collage)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(2)
        previews = list(preview_paths)[:4]
        if not previews:
            placeholder = QLabel("empty")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            placeholder.setStyleSheet("color: #6a6a6a; background: #2a2a2a; border-radius: 2px;")
            placeholder.setFixedSize(166, 144)
            grid.addWidget(placeholder, 0, 0)
            return collage
        for idx in range(4):
            cell = QLabel()
            cell.setFixedSize(82, 71)
            cell.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cell.setStyleSheet("background: #2a2a2a; border-radius: 2px;")
            if idx < len(previews):
                pm = QPixmap(str(previews[idx]))
                if not pm.isNull():
                    cell.setPixmap(pm.scaled(
                        82, 71,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    ))
            grid.addWidget(cell, idx // 2, idx % 2)
        return collage

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._key)
