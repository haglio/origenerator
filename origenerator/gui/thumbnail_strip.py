from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.db import Database
from origenerator.gui.thumbnail_widget import ThumbnailWidget


class ThumbnailStrip(QWidget):
    """A vertical, scrollable list of thumbnails for a set of generations.

    Lives beside the generate subtabs and shows the active tab's own history;
    clicking a thumbnail re-emits its prompt_id via ``thumbnail_activated`` so
    the container can decide whether to reuse the active subtab or open a new one.
    """

    thumbnail_activated = pyqtSignal(str)  # prompt_id

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self.setFixedWidth(200)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._container = QWidget()
        self._list = QVBoxLayout(self._container)
        self._list.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._container)
        outer.addWidget(self._scroll)

        self.show_generations([])

    def show_generations(self, prompt_ids: list[str]):
        """Replace the strip with thumbnails for ``prompt_ids``, in that order."""
        while self._list.count():
            item = self._list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for prompt_id in prompt_ids:
            row = self._db.get_generation(prompt_id)
            if not row:
                continue
            tw = ThumbnailWidget(
                prompt_id,
                row.get("thumbnail_path"),
                self._label_for(row),
            )
            tw.clicked.connect(self.thumbnail_activated)
            self._list.addWidget(tw)

    @staticmethod
    def _label_for(row: dict) -> str:
        wf_name = row.get("workflow_name", "?")
        prompt_preview = (row.get("positive_prompt") or "")[:40]
        return f"{wf_name}\n{prompt_preview}"
