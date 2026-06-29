import json
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPlainTextEdit, QPushButton, QTreeWidget, QTreeWidgetItem,
    QMenu, QInputDialog, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal

from origenerator import gallery, timing
from origenerator.config import COMFYUI_OUTPUT_DIR
from origenerator.db import Database
from origenerator.generation_config import merge_denormalized
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.rerun_dialog import ReRunDialog
from origenerator.gui.thumbnail_widget import ThumbnailWidget

_GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents
_GRID_COLUMNS = 4
_POLL_INTERVAL_MS = 1500
_PREVIEW_COUNT = 4
_STAR_PREFIX = "★ "  # marks a starred folder in the tree label


class GalleryView(QWidget):
    reuse_requested = pyqtSignal(str, dict)   # workflow_name, params dict
    replay_requested = pyqtSignal(dict, dict)  # selected row, overrides dict

    def __init__(self, db: Database, parent=None):
        super().__init__(parent)
        self._db = db
        self._selected: dict | None = None
        self._image_rows: list[dict] = []
        self._item_by_key: dict[str, QTreeWidgetItem] = {}
        self._leaf_by_id: dict[str, QTreeWidgetItem] = {}
        self._source_image_id: str | None = None
        self._visible_ids: list[str] = []
        self._visible_keys: list[str] = []
        self._fingerprint = None
        self._pending_key: str | None = None  # a folder to open once the tree exists
        self._editing_key: str | None = None  # folder being renamed inline
        self._build_ui()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(8)

        # Far left: folder tree (media -> workflow -> settings). Folders start
        # collapsed and only expand on the disclosure arrow; double-click renames.
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.currentItemChanged.connect(self._on_folder_selected)
        self._tree.itemDoubleClicked.connect(self._begin_inline_rename)
        self._tree.itemChanged.connect(self._commit_inline_rename)
        layout.addWidget(self._tree, 2)

        # Middle: folder title over the contents (folder tiles or thumbnails).
        # Double-clicking the title renames the selected folder in place.
        middle = QVBoxLayout()
        self._title = EditableHeader()
        self._title.edit_requested.connect(self._begin_title_rename)
        self._title.edited.connect(self._commit_title_rename)
        middle.addWidget(self._title)
        self._avg_label = QLabel("")
        self._avg_label.setObjectName("estimateLabel")
        self._avg_label.setWordWrap(True)
        middle.addWidget(self._avg_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        middle.addWidget(self._scroll, 1)
        layout.addLayout(middle, 5)

        # Right: preview + metadata sidebar
        right = QVBoxLayout()
        self._meta_title = QLabel("Select a generation")
        self._meta_title.setWordWrap(True)
        right.addWidget(self._meta_title)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        self._estimate_label.setWordWrap(True)
        right.addWidget(self._estimate_label)
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
        self._rerun_btn = QPushButton("Re-run…")
        self._rerun_btn.setToolTip(
            "Re-run this generation's exact workflow with an editable "
            "prompt, seed and input image — even for unregistered workflows."
        )
        self._rerun_btn.clicked.connect(self._on_rerun)
        self._rerun_btn.setEnabled(False)
        right.addWidget(self._rerun_btn)
        layout.addLayout(right, 3)

    def showEvent(self, event):
        super().showEvent(event)
        self._poll_timer.start()
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._poll_timer.stop()  # no need to poll while the tab is hidden

    # --- data loading & live update ---------------------------------------

    def refresh(self):
        rows = self._db.list_generations()
        meta = self._db.folder_meta_map()
        self._fingerprint = _fingerprint(rows, meta)
        self._rebuild(rows, meta)

    def _poll(self):
        rows = self._db.list_generations()
        meta = self._db.folder_meta_map()
        fingerprint = _fingerprint(rows, meta)
        if fingerprint != self._fingerprint:
            self._fingerprint = fingerprint
            self._rebuild(rows, meta)

    def _rebuild(self, rows, meta):
        expanded = self._expanded_keys()
        # A pending restore target stands in until the user makes a live choice.
        selected_key = self._selected_folder_key() or self._pending_key
        self._pending_key = None
        self._image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
        self._populate_tree(gallery.build_gallery_tree(rows, meta), expanded)
        self._clear_metadata()
        target = self._item_by_key.get(selected_key) or self._default_item()
        if target is not None:
            self._tree.setCurrentItem(target)
        else:
            self._title.set_display("")
            self._avg_label.setText("")
            self._show_widget(QWidget())

    # --- folder tree -------------------------------------------------------

    def _populate_tree(self, tree_model, expanded_keys):
        self._tree.blockSignals(True)
        self._tree.clear()
        self._item_by_key = {}
        self._leaf_by_id = {}
        for media in tree_model:
            self._add_node(media, self._tree.invisibleRootItem())
        # Folders default to collapsed; only restore folders the user had open.
        for key in expanded_keys:
            item = self._item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._tree.blockSignals(False)

    def _add_node(self, group, parent_item) -> QTreeWidgetItem:
        prefix = _STAR_PREFIX if group.starred else ""
        item = QTreeWidgetItem([prefix + group.label])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        item.setData(0, _GROUP_ROLE, group)
        item.setToolTip(0, group.label)
        self._item_by_key[group.key] = item
        parent_item.addChild(item)
        for child in gallery.child_groups(group):
            self._add_node(child, item)
        if isinstance(group, gallery.SettingsGroup):
            for row in group.rows:
                self._leaf_by_id[row["prompt_id"]] = item
        return item

    def _default_item(self) -> QTreeWidgetItem | None:
        root = self._tree.invisibleRootItem()
        return root.child(0) if root.childCount() else None

    def _expanded_keys(self) -> set[str]:
        return {
            key for key, item in self._item_by_key.items() if item.isExpanded()
        }

    def _selected_folder_key(self) -> str | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        group = item.data(0, _GROUP_ROLE)
        return group.key if group else None

    def _on_folder_selected(self, current, _previous):
        if current is None:
            self._title.set_display("")
            self._avg_label.setText("")
            self._show_widget(QWidget())
            self._visible_ids = []
            self._visible_keys = []
            return
        group = current.data(0, _GROUP_ROLE)
        self._title.set_display(self._breadcrumb(current))
        self._update_folder_average(group)
        if isinstance(group, gallery.SettingsGroup):
            self._show_thumbnails(group.rows)
        else:
            self._show_folder_tiles(gallery.child_groups(group))
        self._select_first_item(group)

    def _select_first_item(self, group):
        """Immediately preview the first generation under the chosen folder."""
        rows = gallery.rows_under(group)
        if rows:
            self._on_thumbnail_clicked(rows[0]["prompt_id"])

    def _update_folder_average(self, group):
        """Show the mean generation time across every item beneath this folder."""
        durations = [
            row["duration_seconds"] for row in gallery.rows_under(group)
            if row.get("duration_seconds") is not None
        ]
        label = timing.average_label(durations)
        self._avg_label.setText(f"Average time: {label}" if label else "")

    def _breadcrumb(self, item) -> str:
        parts = []
        node = item
        while node is not None:
            group = node.data(0, _GROUP_ROLE)
            if group is not None:
                parts.append(group.label)
            node = node.parent()
        return "  ›  ".join(reversed(parts))

    # --- main view: folder tiles or thumbnails -----------------------------

    def _show_widget(self, widget: QWidget):
        self._scroll.setWidget(widget)  # replaces & deletes the previous widget

    def _show_folder_tiles(self, groups):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._visible_ids = []
        self._visible_keys = []
        for idx, group in enumerate(groups):
            tile = FolderTile(
                group.key,
                group.label,
                self._preview_paths(group),
                len(gallery.rows_under(group)),
                group.starred,
            )
            tile.clicked.connect(self._drill_into)
            tile.context_requested.connect(self._folder_context_menu)
            grid.addWidget(tile, idx // _GRID_COLUMNS, idx % _GRID_COLUMNS)
            self._visible_keys.append(group.key)
        self._show_widget(container)

    def _show_thumbnails(self, rows):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._visible_ids = []
        self._visible_keys = []
        for idx, row in enumerate(rows):
            seed = row.get("seed")
            label = f"seed {seed}" if seed is not None else (
                (row.get("positive_prompt") or "")[:40] or "(no prompt)"
            )
            tw = ThumbnailWidget(row["prompt_id"], row.get("thumbnail_path"), label)
            tw.clicked.connect(self._on_thumbnail_clicked)
            grid.addWidget(tw, idx // _GRID_COLUMNS, idx % _GRID_COLUMNS)
            self._visible_ids.append(row["prompt_id"])
        self._show_widget(container)

    @staticmethod
    def _preview_paths(group) -> list[str]:
        paths = []
        for row in gallery.rows_under(group):
            thumb = row.get("thumbnail_path")
            if thumb and Path(thumb).exists():
                paths.append(thumb)
                if len(paths) >= _PREVIEW_COUNT:
                    break
        return paths

    def _drill_into(self, key: str):
        item = self._item_by_key.get(key)
        if item is not None:
            self._tree.setCurrentItem(item)

    def visible_prompt_ids(self) -> list[str]:
        return list(self._visible_ids)

    def visible_folder_keys(self) -> list[str]:
        return list(self._visible_keys)

    # --- session persistence ----------------------------------------------

    def selected_folder(self) -> str | None:
        """The key of the folder currently in view, for saving the session.

        Falls back to a not-yet-applied restore target, so a saved folder
        survives even a session where the Gallery tab was never opened.
        """
        return self._selected_folder_key() or self._pending_key

    def select_folder(self, key: str | None):
        """Open ``key`` on the next rebuild — used to restore the last session.

        The tree is built lazily on first show, so this only records the target;
        the next refresh/poll resolves it, falling back to the default folder
        when the key no longer exists.
        """
        self._pending_key = key or None

    # --- rename & star -----------------------------------------------------

    def _on_tree_context_menu(self, pos: QPoint):
        item = self._tree.itemAt(pos)
        if item is None:
            return
        group = item.data(0, _GROUP_ROLE)
        if group is not None:
            self._folder_context_menu(group.key, self._tree.viewport().mapToGlobal(pos))

    def _folder_context_menu(self, key: str, global_pos: QPoint):
        item = self._item_by_key.get(key)
        if item is None:
            return
        group = item.data(0, _GROUP_ROLE)
        menu = QMenu(self)
        rename_action = menu.addAction("Rename…")
        star_action = menu.addAction("Unstar" if group.starred else "Star")
        chosen = menu.exec(global_pos)
        if chosen == rename_action:
            self._rename_folder(key)
        elif chosen == star_action:
            self._toggle_star(key)

    def _rename_folder(self, key: str):
        item = self._item_by_key.get(key)
        current = item.data(0, _GROUP_ROLE).label if item else ""
        text, ok = QInputDialog.getText(
            self, "Rename Folder", "Folder name (blank to reset):", text=current
        )
        if ok:
            self._apply_rename(key, text)

    def _apply_rename(self, key: str, name: str):
        self._db.rename_folder(key, name.strip() or None)
        self.refresh()

    def _begin_inline_rename(self, item, _column):
        """Double-clicking a tree folder edits its name in place."""
        group = item.data(0, _GROUP_ROLE)
        if group is None:
            return
        self._editing_key = group.key
        self._tree.editItem(item, 0)

    def _commit_inline_rename(self, item, _column):
        if self._editing_key is None:
            return
        key = self._editing_key
        self._editing_key = None
        name = item.text(0)
        if name.startswith(_STAR_PREFIX):
            name = name[len(_STAR_PREFIX):]
        self._db.rename_folder(key, name.strip() or None)
        # Rebuild after the editor has fully closed to avoid deleting it mid-edit.
        QTimer.singleShot(0, self.refresh)

    def _begin_title_rename(self):
        """Double-clicking the title bar edits the selected folder's name."""
        item = self._tree.currentItem()
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if group is not None:
            self._title.begin_edit(group.label)

    def _commit_title_rename(self, name: str):
        key = self._selected_folder_key()
        if key is not None:
            self._db.rename_folder(key, name.strip() or None)
            self.refresh()

    def _toggle_star(self, key: str):
        item = self._item_by_key.get(key)
        starred = bool(item and item.data(0, _GROUP_ROLE).starred)
        self._db.set_folder_starred(key, not starred)
        self.refresh()

    # --- metadata sidebar --------------------------------------------------

    def _on_thumbnail_clicked(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        self._selected = row
        self._reuse_btn.setEnabled(True)
        self._rerun_btn.setEnabled(_has_graph(row))
        self._show_preview(row)
        self._meta_title.setText(
            f"{row['workflow_name']} ({row['workflow_version']})"
        )
        self._estimate_label.setText(
            f"Typical time: {timing.estimate_label(self._db.recent_durations(row['workflow_name']))}"
        )
        self._update_source_link(row)
        lines = []
        lines.append(f"Status: {row['status']}")
        lines.append(f"Source: {row.get('source', 'generated')}")
        lines.append(f"Seed: {row.get('seed', 'N/A')}")
        lines.append(f"Created: {row.get('created_at', '')}")
        duration = row.get("duration_seconds")
        if duration is not None:
            lines.append(f"Duration: {timing.format_duration(duration)}")
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
            self._tree.setCurrentItem(leaf)  # shows that folder's thumbnails
        self._on_thumbnail_clicked(prompt_id)

    def _clear_metadata(self):
        self._selected = None
        self._reuse_btn.setEnabled(False)
        self._rerun_btn.setEnabled(False)
        self._meta_title.setText("Select a generation")
        self._estimate_label.clear()
        self._meta_text.clear()
        self._source_link.hide()
        self._source_link.clear()
        self._source_image_id = None
        self._preview.clear()

    def _on_reuse(self):
        if not self._selected:
            return
        params = merge_denormalized(self._selected)
        if not params:
            return
        workflow_name = self._selected.get("workflow_name", "")
        self.reuse_requested.emit(workflow_name, params)

    def _on_rerun(self):
        if not self._selected or not _has_graph(self._selected):
            return
        dialog = ReRunDialog(self._selected, self)
        if dialog.exec():
            self.replay_requested.emit(self._selected, dialog.overrides())


def _has_graph(row: dict) -> bool:
    """True if a row stored a re-runnable ComfyUI graph in workflow_json."""
    raw = row.get("workflow_json")
    if not raw:
        return False
    try:
        return bool(json.loads(raw))
    except json.JSONDecodeError:
        return False


def _fingerprint(rows, meta) -> int:
    """A cheap hash of everything the gallery renders, to detect DB changes."""
    row_sig = tuple(
        (r.get("prompt_id"), r.get("status"), r.get("thumbnail_path"),
         r.get("workflow_name"), r.get("params_json"), r.get("output_files"))
        for r in rows
    )
    meta_sig = tuple(sorted(
        (k, v.get("custom_name"), v.get("starred")) for k, v in meta.items()
    ))
    return hash((row_sig, meta_sig))
