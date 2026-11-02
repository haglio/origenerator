from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.link_heading import link_heading
from origenerator.gui.looping_preview import play_in
from origenerator.gui.thumbnail_box import THUMBNAIL_BOX, fitted_in_the_box


class _VideoTile(QLabel):
    clicked = pyqtSignal(str)

    def __init__(self, prompt_id: str, parent=None):
        super().__init__(parent)
        self._prompt_id = prompt_id
        self.setFixedSize(THUMBNAIL_BOX)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._prompt_id)


def _show_heading(label, heading: str) -> None:
    label.setText(heading)
    label.setVisible(bool(heading))


class Animations(QWidget):
    video_activated = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_SMALL)
        self._heading = link_heading("")
        self.set_heading("")
        column.addWidget(self._heading)
        self._host = QWidget()
        FlowLayout(self._host, spacing=6)
        column.addWidget(self._host)
        self._column = column
        self.hide()

    def set_heading(self, heading: str) -> None:
        _show_heading(self._heading, heading)

    def show_videos(self, items: list[tuple[str, object, object]]):
        # Deleting the old host stops and frees its tiles' movies.
        self._column.removeWidget(self._host)
        self._host.deleteLater()
        self._host = QWidget()
        flow = FlowLayout(self._host, spacing=6)
        for prompt_id, movie_path, still_path in items:
            flow.addWidget(self._make_tile(prompt_id, movie_path, still_path))
        self._column.addWidget(self._host)
        self.setVisible(bool(items))

    def _make_tile(self, prompt_id, movie_path, still_path) -> _VideoTile:
        tile = _VideoTile(prompt_id)
        tile.clicked.connect(self.video_activated)
        if movie_path:
            play_in(tile, movie_path, THUMBNAIL_BOX)
        elif still_path:
            pixmap = QPixmap(str(still_path))
            if not pixmap.isNull():
                tile.setPixmap(fitted_in_the_box(pixmap))
        return tile
