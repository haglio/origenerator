from PyQt6.QtWidgets import QWidget, QVBoxLayout, QScrollArea
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR, THUMB_DIR
from origenerator.db import Database
from origenerator.gui.thumbnail_widget import ThumbnailWidget


class ThumbnailStrip(QWidget):
    """A vertical, scrollable list of thumbnails for a set of generations.

    A resizable pane inside a generate subtab, showing that tab's own history;
    clicking a thumbnail re-emits its prompt_id via ``thumbnail_activated`` so
    the container can decide whether to reuse the active subtab or open a new one.
    Hovering a thumbnail highlights every other one sharing its settings — a
    preview of the folder a click would carry into a new tab.
    """

    thumbnail_activated = pyqtSignal(str)  # prompt_id

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._widgets: list[ThumbnailWidget] = []
        self._sig_by_id: dict[str, str] = {}  # prompt_id -> settings signature
        # A slim floor — a thumbnail plus the scrollbar — so a config tab's
        # preview-over-form column keeps most of the width and the whole window
        # can still tile into a monitor third or a portrait half. The splitter
        # sizes the pane from here up.
        self.setMinimumWidth(120)

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
        self._widgets = []
        self._sig_by_id = {}
        for prompt_id in prompt_ids:
            row = self._db.get_generation(prompt_id)
            if not row:
                continue
            tw = ThumbnailWidget(
                prompt_id,
                row.get("thumbnail_path"),
                self._label_for(row),
                movie_path=gallery.animated_preview_path(
                    row, COMFYUI_OUTPUT_DIR, THUMB_DIR
                ),  # a video row loops its preview; an image stays a still
                enhanced=gallery.is_enhanced_row(row),  # the yellow-plus corner badge
            )
            tw.clicked.connect(self.thumbnail_activated)
            tw.hovered.connect(self._highlight_matching)
            tw.unhovered.connect(self._clear_highlight)
            self._sig_by_id[prompt_id] = gallery.settings_signature(
                row.get("workflow_name"), row.get("params_json"),
                workflow_version=row.get("workflow_version"),
            )
            self._widgets.append(tw)
            self._list.addWidget(tw)

    def _highlight_matching(self, prompt_id: str):
        """Highlight every thumbnail in the same settings folder as the hovered one."""
        target = self._sig_by_id.get(prompt_id)
        for widget in self._widgets:
            widget.set_highlighted(self._sig_by_id.get(widget.prompt_id) == target)

    def _clear_highlight(self, _prompt_id: str):
        for widget in self._widgets:
            widget.set_highlighted(False)

    @staticmethod
    def _label_for(row: dict) -> str:
        wf_name = row.get("workflow_name", "?")
        prompt_preview = (row.get("positive_prompt") or "")[:40]
        return f"{wf_name}\n{prompt_preview}"
