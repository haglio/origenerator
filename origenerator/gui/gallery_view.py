import json

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QPlainTextEdit, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.config import THUMB_DIR
from origenerator.db import Database
from origenerator.gui.thumbnail_widget import ThumbnailWidget


class GalleryView(QWidget):
    reuse_requested = pyqtSignal(str, dict)  # workflow_name, params dict

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._selected: dict | None = None
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(8)

        # Left: thumbnail grid in scroll area
        left = QVBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        left.addWidget(self._refresh_btn)
        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._grid_container = QWidget()
        self._grid_layout = _FlowLayout(self._grid_container)
        self._grid_scroll.setWidget(self._grid_container)
        left.addWidget(self._grid_scroll, 1)
        layout.addLayout(left, 2)

        # Right: metadata sidebar
        right = QVBoxLayout()
        self._meta_title = QLabel("Select a generation")
        self._meta_title.setWordWrap(True)
        right.addWidget(self._meta_title)
        self._meta_text = QPlainTextEdit()
        self._meta_text.setReadOnly(True)
        right.addWidget(self._meta_text, 1)
        self._reuse_btn = QPushButton("Reuse Parameters")
        self._reuse_btn.clicked.connect(self._on_reuse)
        self._reuse_btn.setEnabled(False)
        right.addWidget(self._reuse_btn)
        layout.addLayout(right, 1)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        # Clear existing thumbnails
        while self._grid_layout.count():
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rows = self._db.list_generations()
        for row in rows:
            thumb_path = row.get("thumbnail_path")
            wf_name = row.get("workflow_name", "?")
            prompt_preview = (row.get("positive_prompt") or "")[:40]
            label = f"{wf_name}\n{prompt_preview}"
            tw = ThumbnailWidget(row["prompt_id"], thumb_path, label)
            tw.clicked.connect(self._on_thumbnail_clicked)
            self._grid_layout.addWidget(tw)

    def _on_thumbnail_clicked(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        self._selected = row
        self._reuse_btn.setEnabled(True)
        self._meta_title.setText(
            f"{row['workflow_name']} ({row['workflow_version']})"
        )
        lines = []
        lines.append(f"Status: {row['status']}")
        lines.append(f"Source: {row.get('source', 'generated')}")
        lines.append(f"Seed: {row.get('seed', 'N/A')}")
        lines.append(f"Created: {row.get('created_at', '')}")
        lines.append("")
        lines.append("--- Positive Prompt ---")
        lines.append(row.get("positive_prompt") or "(empty)")
        lines.append("")
        lines.append("--- Negative Prompt ---")
        lines.append(row.get("negative_prompt") or "(empty)")
        lines.append("")
        params = row.get("params_json")
        if params:
            lines.append("--- Parameters ---")
            try:
                d = json.loads(params)
                for k, v in d.items():
                    if k not in ("positive_prompt", "negative_prompt"):
                        lines.append(f"  {k}: {v}")
            except json.JSONDecodeError:
                lines.append(params)
        lines.append("")
        out = row.get("output_files")
        if out:
            lines.append("--- Output Files ---")
            try:
                for f in json.loads(out):
                    lines.append(f"  {f.get('subfolder', '')}/{f['filename']}")
            except (json.JSONDecodeError, KeyError):
                lines.append(out)
        self._meta_text.setPlainText("\n".join(lines))

    def _on_reuse(self):
        if not self._selected:
            return
        params_json = self._selected.get("params_json")
        if params_json:
            try:
                params = json.loads(params_json)
            except json.JSONDecodeError:
                return
            # Merge denormalized columns into params
            for key in ("positive_prompt", "negative_prompt", "seed"):
                val = self._selected.get(key)
                if val is not None and key not in params:
                    params[key] = val
            workflow_name = self._selected.get("workflow_name", "")
            self.reuse_requested.emit(workflow_name, params)


class _FlowLayout(QVBoxLayout):
    """Simple vertical layout used as placeholder; a proper flow layout
    can be added later for wrapping thumbnails in a grid."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[QHBoxLayout] = []
        self._current_row: QHBoxLayout | None = None
        self._count_in_row = 0
        self._cols = 4

    def addWidget(self, widget, *args, **kwargs):
        if self._current_row is None or self._count_in_row >= self._cols:
            self._current_row = QHBoxLayout()
            self._current_row.setAlignment(Qt.AlignmentFlag.AlignLeft)
            self._rows.append(self._current_row)
            super().addLayout(self._current_row)
            self._count_in_row = 0
        self._current_row.addWidget(widget, *args, **kwargs)
        self._count_in_row += 1
