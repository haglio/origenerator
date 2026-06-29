import json

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator import gallery
from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.db import Database
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.thumbnail_widget import ThumbnailWidget

_ROWS_ROLE = Qt.ItemDataRole.UserRole  # rows represented by a folder node
_GRID_COLUMNS = 4


class GalleryView(QWidget):
    reuse_requested = pyqtSignal(str, dict)  # workflow_name, params dict

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._selected: dict | None = None
        self._image_rows: list[dict] = []
        self._leaf_by_id: dict[str, QTreeWidgetItem] = {}
        self._source_image_id: str | None = None
        self._visible_ids: list[str] = []
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(8)

        # Far left: folder tree (media -> workflow -> settings)
        left = QVBoxLayout()
        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        left.addWidget(self._refresh_btn)
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.currentItemChanged.connect(self._on_folder_selected)
        left.addWidget(self._tree, 1)
        layout.addLayout(left, 2)

        # Middle: thumbnail grid for the selected folder
        self._grid_scroll = QScrollArea()
        self._grid_scroll.setWidgetResizable(True)
        self._show_rows([])
        layout.addWidget(self._grid_scroll, 5)

        # Right: preview + metadata sidebar
        right = QVBoxLayout()
        self._meta_title = QLabel("Select a generation")
        self._meta_title.setWordWrap(True)
        right.addWidget(self._meta_title)
        self._source_link = QLabel()
        self._source_link.setWordWrap(True)
        self._source_link.setTextFormat(Qt.TextFormat.RichText)
        self._source_link.setOpenExternalLinks(False)
        self._source_link.linkActivated.connect(self._on_source_link)
        self._source_link.hide()
        right.addWidget(self._source_link)
        self._preview = PreviewWidget()
        right.addWidget(self._preview, 3)
        self._meta_text = QPlainTextEdit()
        self._meta_text.setReadOnly(True)
        right.addWidget(self._meta_text, 2)
        self._reuse_btn = QPushButton("Reuse Parameters")
        self._reuse_btn.clicked.connect(self._on_reuse)
        self._reuse_btn.setEnabled(False)
        right.addWidget(self._reuse_btn)
        layout.addLayout(right, 3)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def refresh(self):
        rows = self._db.list_generations()
        self._image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
        self._populate_tree(gallery.build_gallery_tree(rows))
        self._clear_metadata()
        first_leaf = self._first_leaf()
        if first_leaf is not None:
            self._tree.setCurrentItem(first_leaf)
        else:
            self._show_rows([])

    # --- folder tree -------------------------------------------------------

    def _populate_tree(self, tree_model: list[gallery.MediaGroup]):
        self._tree.clear()
        self._leaf_by_id = {}
        for media in tree_model:
            media_rows = _flatten(media)
            media_item = self._make_node(media.label, media_rows)
            for wf in media.workflow_groups:
                wf_rows = [r for sg in wf.settings_groups for r in sg.rows]
                wf_item = self._make_node(wf.label, wf_rows)
                for sg in wf.settings_groups:
                    sg_item = self._make_node(sg.label, sg.rows)
                    for row in sg.rows:
                        self._leaf_by_id[row["prompt_id"]] = sg_item
                    wf_item.addChild(sg_item)
                media_item.addChild(wf_item)
            self._tree.addTopLevelItem(media_item)
        self._tree.expandAll()

    @staticmethod
    def _make_node(label: str, rows: list[dict]) -> QTreeWidgetItem:
        item = QTreeWidgetItem([label])
        item.setData(0, _ROWS_ROLE, rows)
        item.setToolTip(0, f"{len(rows)} item{'s' if len(rows) != 1 else ''}")
        return item

    def _first_leaf(self) -> QTreeWidgetItem | None:
        for i in range(self._tree.topLevelItemCount()):
            media = self._tree.topLevelItem(i)
            for j in range(media.childCount()):
                wf = media.child(j)
                if wf.childCount():
                    return wf.child(0)
        return None

    def _on_folder_selected(self, current, _previous):
        rows = current.data(0, _ROWS_ROLE) if current is not None else None
        self._show_rows(rows or [])

    # --- thumbnail grid ----------------------------------------------------

    def _show_rows(self, rows: list[dict]):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._visible_ids = []
        for idx, row in enumerate(rows):
            seed = row.get("seed")
            label = f"seed {seed}" if seed is not None else (
                (row.get("positive_prompt") or "")[:40] or "(no prompt)"
            )
            tw = ThumbnailWidget(row["prompt_id"], row.get("thumbnail_path"), label)
            tw.clicked.connect(self._on_thumbnail_clicked)
            grid.addWidget(tw, idx // _GRID_COLUMNS, idx % _GRID_COLUMNS)
            self._visible_ids.append(row["prompt_id"])
        self._grid_scroll.setWidget(container)  # replaces & deletes the old grid

    def visible_prompt_ids(self) -> list[str]:
        return list(self._visible_ids)

    # --- metadata sidebar --------------------------------------------------

    def _on_thumbnail_clicked(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        self._selected = row
        self._reuse_btn.setEnabled(True)
        self._show_preview(row)
        self._meta_title.setText(
            f"{row['workflow_name']} ({row['workflow_version']})"
        )
        self._update_source_link(row)
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

    def _update_source_link(self, row: dict):
        self._source_image_id = gallery.find_source_image_id(row, self._image_rows)
        if not self._source_image_id:
            self._source_link.hide()
            self._source_link.clear()
            return
        src = self._db.get_generation(self._source_image_id)
        files = gallery.row_output_files(src) if src else []
        name = files[0]["filename"] if files else "source image"
        self._source_link.setText(
            f'Input image: <a href="{self._source_image_id}">{name}</a>'
        )
        self._source_link.show()

    def _show_preview(self, row: dict):
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            self._preview.clear()
        else:
            self._preview.show_media(*preview)

    def current_source_image_id(self) -> str | None:
        return self._source_image_id

    def _on_source_link(self, prompt_id: str):
        leaf = self._leaf_by_id.get(prompt_id)
        if leaf is not None:
            self._tree.setCurrentItem(leaf)  # repopulates the grid
        self._on_thumbnail_clicked(prompt_id)

    def _clear_metadata(self):
        self._selected = None
        self._reuse_btn.setEnabled(False)
        self._meta_title.setText("Select a generation")
        self._meta_text.clear()
        self._source_link.hide()
        self._source_link.clear()
        self._source_image_id = None
        self._preview.clear()

    def _on_reuse(self):
        if not self._selected:
            return
        params_json = self._selected.get("params_json")
        if not params_json:
            return
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


def _flatten(media: gallery.MediaGroup) -> list[dict]:
    return [
        row
        for wf in media.workflow_groups
        for sg in wf.settings_groups
        for row in sg.rows
    ]
