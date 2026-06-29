import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QGridLayout, QLabel,
    QScrollArea, QPushButton, QTreeWidget, QTreeWidgetItem,
    QMenu, QInputDialog, QAbstractItemView, QFrame, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt, QTimer, QPoint, pyqtSignal
from PyQt6.QtGui import QShortcut, QKeySequence

from origenerator import gallery, timing
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import COMFYUI_OUTPUT_DIR, STATE_DIR
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import merge_denormalized, randomize_seeds
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.generation_job import GenerationJob
from origenerator.gui.metadata_panel import MetadataPanel
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents
_GRID_COLUMNS = 4
_POLL_INTERVAL_MS = 1500
_PREVIEW_COUNT = 4
_STAR_PREFIX = "★ "  # marks a starred folder in the tree label


def _is_deletable_folder(group) -> bool:
    """Whether a folder may be deleted: anything nested inside a workflow.

    Model and settings folders live within a workflow folder and are fair game;
    a whole workflow or media folder is off-limits, so a workflow's entire
    history can never be wiped in one action.
    """
    return isinstance(group, (gallery.ModelGroup, gallery.SettingsGroup))


class GalleryView(QWidget):
    reuse_requested = pyqtSignal(str, dict)   # workflow_name, params dict

    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryActions | None = None):
        super().__init__(parent)
        self._db = db
        self._client = client
        self._reroll_jobs: dict[str, GenerationJob] = {}  # settings-folder key -> job
        self._actions = actions or GalleryActions(
            db, COMFYUI_OUTPUT_DIR, Trash(STATE_DIR / "trash")
        )
        self._selected: dict | None = None
        self._image_rows: list[dict] = []
        self._item_by_key: dict[str, QTreeWidgetItem] = {}
        self._leaf_by_id: dict[str, QTreeWidgetItem] = {}
        self._source_image_id: str | None = None
        self._visible_ids: list[str] = []
        self._visible_keys: list[str] = []
        self._selected_ids: set[str] = set()
        self._selection_anchor: str | None = None
        self._thumb_widgets: dict[str, ThumbnailWidget] = {}
        self._fingerprint = None
        self._pending_key: str | None = None  # a folder to open once the tree exists
        self._pending_selection: str | None = None  # a generation to highlight once shown
        self._editing_key: str | None = None  # folder being renamed inline
        self._build_ui()
        self._install_shortcuts()
        self._sync_undo_button()

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _install_shortcuts(self):
        delete = QShortcut(QKeySequence(QKeySequence.StandardKey.Delete), self)
        delete.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        delete.activated.connect(self._delete_selection)
        undo = QShortcut(QKeySequence(QKeySequence.StandardKey.Undo), self)
        undo.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        undo.activated.connect(self._undo)

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setSpacing(8)

        # Far left: folder tree (media -> workflow -> model -> settings). Folders
        # start collapsed and only expand on the disclosure arrow; double-click renames.
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

        # Middle: a header (folder title + Undo) over the contents.
        # Double-clicking the title renames the selected folder in place.
        middle = QVBoxLayout()
        header = QHBoxLayout()
        self._title = EditableHeader()
        self._title.edit_requested.connect(self._begin_title_rename)
        self._title.edited.connect(self._commit_title_rename)
        header.addWidget(self._title, 1)
        self._undo_btn = QPushButton("Undo")
        self._undo_btn.clicked.connect(self._undo)
        header.addWidget(self._undo_btn, 0, Qt.AlignmentFlag.AlignTop)
        middle.addLayout(header)
        self._avg_label = QLabel("")
        self._avg_label.setObjectName("estimateLabel")
        self._avg_label.setWordWrap(True)
        middle.addWidget(self._avg_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        middle.addWidget(self._scroll, 1)
        layout.addLayout(middle, 5)

        # A thin divider sets the metadata sidebar apart from the main pane.
        # A plain 1px frame (not QFrame.VLine) renders the theme colour exactly;
        # VLine's etched, palette-driven line ignores a stylesheet fill.
        separator = QFrame()
        separator.setObjectName("paneSeparator")
        separator.setFixedWidth(1)
        layout.addWidget(separator)

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
        self._meta_panel = MetadataPanel()
        right.addWidget(self._meta_panel, 2)
        self._reuse_btn = QPushButton("Reuse Parameters")
        self._reuse_btn.clicked.connect(self._on_reuse)
        self._reuse_btn.setEnabled(False)
        right.addWidget(self._reuse_btn)
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
        # Pending restore targets stand in until the user makes a live choice.
        selected_key = self._selected_folder_key() or self._pending_key
        selected_gen = self.selected_generation()
        self._pending_key = None
        self._pending_selection = None
        self._image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
        self._populate_tree(gallery.build_gallery_tree(rows, meta), expanded)
        self._clear_metadata()
        target = self._item_by_key.get(selected_key) or self._default_item()
        if target is not None:
            self._tree.setCurrentItem(target)  # shows the folder's thumbnails
            self._reselect_generation(selected_gen)
        else:
            self._title.set_display("")
            self._avg_label.setText("")
            self._show_widget(QWidget())

    def _reselect_generation(self, prompt_id: str | None):
        """Re-highlight a generation after a rebuild, if it's still on screen."""
        if prompt_id and prompt_id in self._visible_ids:
            self._on_thumbnail_clicked(prompt_id)

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
            self._show_thumbnails(group)
        else:
            self._show_folder_tiles(gallery.child_groups(group))
        self._select_first_item(group)

    def _select_first_item(self, group):
        """Immediately preview the first generation under the chosen folder."""
        rows = gallery.rows_under(group)
        if rows:
            self._on_thumbnail_clicked(rows[0]["prompt_id"])

    def _update_folder_average(self, group):
        """Show the mean generation time for this folder.

        Prefers the folder's own timed items; when it has none — common for a
        single video prompt, which is rarely re-run — it falls back to the
        parent workflow's timed runs so a figure still appears at the prompt
        level the way it does at the workflow level.
        """
        durations = [
            row["duration_seconds"] for row in gallery.rows_under(group)
            if row.get("duration_seconds") is not None
        ]
        if not durations:
            workflow = _group_workflow(group)
            if workflow:
                durations = self._db.recent_durations(workflow)
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
        self._clear_selection()
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

    def _show_thumbnails(self, group):
        container = QWidget()
        grid = QGridLayout(container)
        grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._clear_selection()
        self._visible_ids = []
        self._visible_keys = []
        # The re-roll tile leads the grid so it sits beside the newest item
        # (thumbnails are sorted newest-first).
        offset = 1 if self._can_reroll(group) else 0
        if offset:
            self._add_reroll_tile(grid, group, 0)
        for idx, row in enumerate(group.rows):
            seed = row.get("seed")
            label = f"seed {seed}" if seed is not None else (
                (row.get("positive_prompt") or "")[:40] or "(no prompt)"
            )
            tw = ThumbnailWidget(row["prompt_id"], row.get("thumbnail_path"), label)
            tw.clicked.connect(self._thumbnail_clicked)
            pos = idx + offset
            grid.addWidget(tw, pos // _GRID_COLUMNS, pos % _GRID_COLUMNS)
            self._visible_ids.append(row["prompt_id"])
            self._thumb_widgets[row["prompt_id"]] = tw
        self._show_widget(container)

    # --- re-roll: a new variation of a folder's settings, here in the gallery

    def _can_reroll(self, group) -> bool:
        """True when this folder's settings can be re-run as a new variation.

        Needs a live client and a generation of ours (imports lack our full
        params) made with a workflow we still know how to build.
        """
        if self._client is None or not group.rows:
            return False
        row = group.rows[0]
        if row.get("source", "generated") != "generated":
            return False
        return WORKFLOW_REGISTRY.get(row.get("workflow_name") or "") is not None

    def _add_reroll_tile(self, grid, group, index):
        tile = RerollTile(self._reroll_jobs.get(group.key))
        tile.add_requested.connect(lambda k=group.key: self._start_reroll(k))
        tile.cancel_requested.connect(lambda k=group.key: self._cancel_reroll(k))
        grid.addWidget(tile, index // _GRID_COLUMNS, index % _GRID_COLUMNS)

    def _start_reroll(self, key: str):
        if self._client is None or key in self._reroll_jobs:
            return  # no client, or this folder already has one running
        item = self._item_by_key.get(key)
        group = item.data(0, _GROUP_ROLE) if item else None
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        workflow = WORKFLOW_REGISTRY.get(group.rows[0].get("workflow_name") or "")
        if workflow is None:
            return
        seed_keys = [pd.key for pd in workflow.param_definitions() if pd.type == "seed"]
        params = randomize_seeds(merge_denormalized(group.rows[0]), seed_keys)
        try:
            job = GenerationJob(self._client, workflow, params)
        except Exception as e:
            logger.warning("Could not build a re-roll for %s: %s", key, e)
            return
        self._reroll_jobs[key] = job
        job.finished.connect(
            lambda files, thumb, dur, k=key, j=job: self._on_reroll_finished(k, j, files, thumb, dur)
        )
        job.failed.connect(lambda msg, k=key: self._on_reroll_failed(k, msg))
        try:
            job.start()
        except Exception as e:
            logger.warning("Re-roll submission failed for %s: %s", key, e)
            self._reroll_jobs.pop(key, None)
        self._rerender_current_leaf()

    def _cancel_reroll(self, key: str):
        job = self._reroll_jobs.pop(key, None)
        if job is not None:
            job.cancel()
        self._rerender_current_leaf()

    def _on_reroll_finished(self, key, job, files, thumb_path, duration):
        self._reroll_jobs.pop(key, None)
        self._persist_generation(job, files, thumb_path, duration)
        self.refresh()  # the finished generation now shows as a normal thumbnail

    def _on_reroll_failed(self, key, message):
        self._reroll_jobs.pop(key, None)
        logger.warning("Re-roll failed for %s: %s", key, message)
        self._rerender_current_leaf()

    def _persist_generation(self, job, files, thumb_path, duration):
        workflow, params = job.workflow, job.params
        self._db.insert_generation(
            prompt_id=job.prompt_id,
            workflow_name=workflow.name,
            workflow_version=workflow.version,
            positive_prompt=params.get("positive_prompt", ""),
            negative_prompt=params.get("negative_prompt", ""),
            seed=params.get("seed"),
            params_json=json.dumps(params),
            workflow_json=json.dumps(job.payload),
        )
        fields = dict(
            status="completed",
            output_files=json.dumps(files),
            thumbnail_path=thumb_path,
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        if duration is not None:
            fields["duration_seconds"] = duration
        self._db.update_generation(job.prompt_id, **fields)

    def _rerender_current_leaf(self):
        """Redraw the open settings folder so its re-roll tile reflects the job."""
        item = self._tree.currentItem()
        group = item.data(0, _GROUP_ROLE) if item else None
        if isinstance(group, gallery.SettingsGroup):
            self._show_thumbnails(group)

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

    def selected_generation(self) -> str | None:
        """The prompt_id of the highlighted generation, for saving the session.

        Falls back to a not-yet-applied restore target, mirroring
        :meth:`selected_folder`, so it survives a session that never showed it.
        """
        if self._selected:
            return self._selected.get("prompt_id")
        return self._pending_selection

    def select_generation(self, prompt_id: str | None):
        """Re-highlight ``prompt_id`` once its folder's thumbnails are shown.

        Resolved by the next rebuild (after :meth:`select_folder` reopens the
        folder), and quietly dropped if that generation is no longer present.
        """
        self._pending_selection = prompt_id or None

    # --- selection ---------------------------------------------------------

    def _thumbnail_clicked(self, prompt_id: str):
        self._apply_selection(prompt_id, QApplication.keyboardModifiers())
        self._on_thumbnail_clicked(prompt_id)

    def _apply_selection(self, prompt_id: str, modifiers):
        """Update the multi-select set the way the held modifiers dictate.

        Ctrl toggles one tile; Shift extends a contiguous run from the anchor;
        a plain click resets to just this tile. Mirrors a typical file browser.
        """
        ctrl = bool(modifiers & Qt.KeyboardModifier.ControlModifier)
        shift = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        if ctrl:
            self._selected_ids ^= {prompt_id}
            self._selection_anchor = prompt_id
        elif shift and self._selection_anchor in self._visible_ids \
                and prompt_id in self._visible_ids:
            a = self._visible_ids.index(self._selection_anchor)
            b = self._visible_ids.index(prompt_id)
            lo, hi = sorted((a, b))
            self._selected_ids = set(self._visible_ids[lo:hi + 1])
        else:
            self._selected_ids = {prompt_id}
            self._selection_anchor = prompt_id
        self._refresh_selection_highlights()

    def _refresh_selection_highlights(self):
        for pid, widget in self._thumb_widgets.items():
            widget.set_selected(pid in self._selected_ids)

    def _clear_selection(self):
        self._selected_ids = set()
        self._selection_anchor = None
        self._thumb_widgets = {}

    def selected_prompt_ids(self) -> list[str]:
        return [pid for pid in self._visible_ids if pid in self._selected_ids]

    # --- deletion & undo ---------------------------------------------------

    def _delete_selection(self):
        """Delete picked thumbnails, or the current folder if none are picked."""
        if self._selected_ids:
            rows = [self._db.get_generation(pid) for pid in self.selected_prompt_ids()]
            self._delete_rows([r for r in rows if r])
            return
        group = self._current_deletable_folder()
        if group is not None:
            self._delete_folder(group)

    def _current_deletable_folder(self):
        """The selected tree folder if it may be deleted, else ``None``."""
        item = self._tree.currentItem()
        group = item.data(0, _GROUP_ROLE) if item else None
        return group if _is_deletable_folder(group) else None

    def _delete_folder(self, group):
        if not _is_deletable_folder(group):
            return
        rows = gallery.rows_under(group)
        if not rows:
            return
        plural = "s" if len(rows) != 1 else ""
        if not self._confirm(f"Delete “{group.label}” and its {len(rows)} item{plural}?"):
            return
        self._delete_rows(rows)

    def _delete_rows(self, rows):
        if not rows:
            return
        deleted_ids = {r["prompt_id"] for r in rows}
        if self._selected and self._selected.get("prompt_id") in deleted_ids:
            self._preview.clear()  # release any file handle before the files move
        self._actions.delete_rows(rows)
        self._clear_selection()
        self.refresh()
        self._sync_undo_button()

    def _undo(self):
        if not self._actions.can_undo():
            return
        self._preview.clear()
        self._actions.undo()
        self._clear_selection()
        self.refresh()
        self._sync_undo_button()

    def _sync_undo_button(self):
        label = self._actions.undo_label()
        self._undo_btn.setEnabled(self._actions.can_undo())
        self._undo_btn.setToolTip(f"Undo: {label}" if label else "Nothing to undo")

    def _confirm(self, text: str) -> bool:
        reply = QMessageBox.question(
            self, "Delete", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

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
        delete_action = None
        if _is_deletable_folder(group):
            menu.addSeparator()
            delete_action = menu.addAction("Delete folder…")
        chosen = menu.exec(global_pos)
        if chosen == rename_action:
            self._rename_folder(key)
        elif chosen == star_action:
            self._toggle_star(key)
        elif delete_action is not None and chosen == delete_action:
            self._delete_folder(group)

    def _rename_folder(self, key: str):
        item = self._item_by_key.get(key)
        current = item.data(0, _GROUP_ROLE).label if item else ""
        text, ok = QInputDialog.getText(
            self, "Rename Folder", "Folder name (blank to reset):", text=current
        )
        if ok:
            self._apply_rename(key, text)

    def _apply_rename(self, key: str, name: str):
        self._actions.rename_folder(key, name.strip() or None)
        self.refresh()
        self._sync_undo_button()

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
        self._actions.rename_folder(key, name.strip() or None)
        self._sync_undo_button()
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
            self._actions.rename_folder(key, name.strip() or None)
            self.refresh()
            self._sync_undo_button()

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
        reusable = row.get("workflow_name") in WORKFLOW_REGISTRY
        self._reuse_btn.setEnabled(reusable)
        self._reuse_btn.setToolTip(
            "" if reusable else
            "This workflow isn't built into the app yet — ask Claude to "
            "implement it if you want to reuse its parameters."
        )
        self._show_preview(row)
        self._meta_title.setText(
            f"{row['workflow_name']} ({row['workflow_version']})"
        )
        self._estimate_label.setText(
            f"Typical time: {timing.estimate_label(self._db.recent_durations(row['workflow_name']))}"
        )
        self._update_source_link(row)
        self._meta_panel.show_row(row)

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
        self._reuse_btn.setToolTip("")
        self._meta_title.setText("Select a generation")
        self._estimate_label.clear()
        self._meta_panel.clear()
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


def _group_workflow(group) -> str | None:
    """The single workflow a folder belongs to, or ``None`` if it spans several
    (a media-type folder) and so has no one workflow time to fall back on."""
    if isinstance(group, gallery.MediaGroup):
        return None
    if isinstance(group, gallery.WorkflowGroup):
        return group.workflow_name
    rows = gallery.rows_under(group)  # model or settings folder: ask its rows
    return rows[0]["workflow_name"] if rows else None


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
