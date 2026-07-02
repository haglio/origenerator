import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QPushButton, QTreeWidget, QTreeWidgetItem, QSplitter,
    QMenu, QInputDialog, QAbstractItemView, QMessageBox, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, QTimer, QPoint, pyqtSignal

from origenerator import gallery, timing
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import COMFYUI_OUTPUT_DIR, STATE_DIR
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import merge_denormalized, prepared_params
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.generation_job import (
    GenerationJob, insert_generation_row, mark_generation_completed,
)
from origenerator.gui.metadata_panel import MetadataPanel
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.navigation import NavigationHistory
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents
_TILE_SPACING = 8  # gap between tiles in the flowing main view
_POLL_INTERVAL_MS = 1500
_PREVIEW_COUNT = 4
_STAR_PREFIX = "★ "  # marks a starred folder in the tree label


def _is_deletable_folder(group) -> bool:
    """Whether a folder may be deleted: anything nested inside a workflow.

    Model, LoRA, and settings folders live within a workflow folder and are fair
    game; a whole workflow or media folder is off-limits, so a workflow's entire
    history can never be wiped in one action.
    """
    return isinstance(
        group, (gallery.ModelGroup, gallery.LoraGroup, gallery.SettingsGroup)
    )


def _is_reusable_workflow(workflow_name) -> bool:
    """Whether the app can rebuild this workflow from its template.

    The single gate for both Reuse Parameters and the gallery re-roll, so the
    re-roll '+' appears exactly where Reuse works (a re-roll is just Reuse with
    a random seed).
    """
    return (workflow_name or "") in WORKFLOW_REGISTRY


class GalleryView(QWidget):
    reuse_requested = pyqtSignal(str, dict)   # workflow_name, params dict

    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryActions | None = None,
                 claimed_ids=None):
        super().__init__(parent)
        self._db = db
        self._client = client
        # In-flight ids some other view already tracks (a Generate tab owns its own
        # jobs), so re-roll reconnection doesn't also adopt them. Queried live.
        self._claimed_ids = claimed_ids or (lambda: set())
        self._reroll_jobs: dict[str, GenerationJob] = {}  # settings-folder key -> job
        # The folder whose running re-roll currently drives the info pane (its
        # tile is the selected item), that tile, and the last frame shown — so
        # live frames mirror from the browser-pane thumbnail into the full-size
        # preview, and the frame outlives both the rebuild each stage completion
        # triggers and an i2v's image->video job swap.
        self._selected_reroll_key: str | None = None
        self._reroll_tile: RerollTile | None = None
        self._last_reroll_frame: bytes | None = None
        self._actions = actions or GalleryActions(
            db, COMFYUI_OUTPUT_DIR, Trash(STATE_DIR / "trash")
        )
        self._selected: dict | None = None
        self._image_rows: list[dict] = []
        self._item_by_key: dict[str, QTreeWidgetItem] = {}
        self._leaf_by_id: dict[str, QTreeWidgetItem] = {}
        self._visible_ids: list[str] = []
        self._visible_keys: list[str] = []
        self._selected_ids: set[str] = set()
        self._selection_anchor: str | None = None
        self._thumb_widgets: dict[str, ThumbnailWidget] = {}
        self._fingerprint = None
        self._pending_key: str | None = None  # a folder to open once the tree exists
        self._pending_selection: str | None = None  # a generation to highlight once shown
        self._editing_key: str | None = None  # folder being renamed inline
        self._history = NavigationHistory()  # back/forward across viewed generations
        self._suppress_history = False  # true while a rebuild or Back/Forward re-selects
        self._build_ui()
        self._sync_undo_button()
        self._sync_nav_buttons()
        # Catch Delete/Ctrl+Z application-wide while the Gallery tab is showing.
        # Neither keyPressEvent nor a shortcut delivered the key in the running
        # app — a clicked thumbnail's key press never reached the view through
        # the scroll area — so intercept it before delivery, independent of which
        # widget holds focus. Auto-removed when this view is destroyed.
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress and self._gallery_owns_keys():
            # Delete removes the selection. Insert does too: some keyboards send
            # Insert where Delete is expected, and the gallery has no other use
            # for it (diagnosed from a real Delete press arriving as Key_Insert).
            if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Insert):
                self._delete_selection()
                return True
            if (event.key() == Qt.Key.Key_Z
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                self._undo()
                return True
        return super().eventFilter(obj, event)

    def _gallery_owns_keys(self) -> bool:
        """True when a gallery key (Delete/Undo) should act, not pass through.

        Only while the Gallery tab is on screen, no dialog/menu is up, and the
        focus isn't in a text field (so renaming and any editor keep their keys).
        """
        if not self.isVisible():
            return False
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return False
        focus = QApplication.focusWidget()
        return not isinstance(
            focus, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)
        )

    def _build_ui(self):
        layout = QHBoxLayout(self)

        # The three panes live in a splitter, so the divider between each doubles
        # as a drag handle: the TOC pane (folder tree), the browser pane (a
        # folder's contents), and the info pane (preview + metadata).
        self._panes = QSplitter(Qt.Orientation.Horizontal)
        self._panes.setChildrenCollapsible(False)  # a pane can't be dragged shut
        self._panes.setHandleWidth(6)

        # TOC pane: folder tree (media -> workflow -> model -> [LoRA] -> settings;
        # the LoRA level shows only for workflows that use one). Folders start
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
        self._panes.addWidget(self._tree)

        # Browser pane: a header (back/forward, folder title, Undo) over the
        # flowing contents. Double-clicking the title renames the folder in place.
        browser = QWidget()
        browser_box = QVBoxLayout(browser)
        browser_box.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        self._back_btn = self._nav_button("←", "Back", self._go_back)
        header.addWidget(self._back_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._forward_btn = self._nav_button("→", "Forward", self._go_forward)
        header.addWidget(self._forward_btn, 0, Qt.AlignmentFlag.AlignTop)
        self._title = EditableHeader()
        self._title.edit_requested.connect(self._begin_title_rename)
        self._title.edited.connect(self._commit_title_rename)
        header.addWidget(self._title, 1)
        self._undo_btn = QPushButton("Undo")
        self._undo_btn.clicked.connect(self._undo)
        header.addWidget(self._undo_btn, 0, Qt.AlignmentFlag.AlignTop)
        browser_box.addLayout(header)
        self._avg_label = QLabel("")
        self._avg_label.setObjectName("estimateLabel")
        self._avg_label.setWordWrap(True)
        browser_box.addWidget(self._avg_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        browser_box.addWidget(self._scroll, 1)
        self._panes.addWidget(browser)

        # Info pane: preview + metadata sidebar
        info = QWidget()
        info_box = QVBoxLayout(info)
        info_box.setContentsMargins(0, 0, 0, 0)
        self._meta_title = QLabel("Select a generation")
        self._meta_title.setWordWrap(True)
        info_box.addWidget(self._meta_title)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        self._estimate_label.setWordWrap(True)
        info_box.addWidget(self._estimate_label)
        self._preview = PreviewWidget()
        info_box.addWidget(self._preview, 3)
        self._meta_panel = MetadataPanel()
        # An i2v's input_image value links to the image it came from; follow it.
        self._meta_panel.link_activated.connect(self._on_source_link)
        info_box.addWidget(self._meta_panel, 2)
        self._reuse_btn = QPushButton("Reuse Parameters")
        self._reuse_btn.clicked.connect(self._on_reuse)
        self._reuse_btn.setEnabled(False)
        # A disabled QPushButton receives no hover events, so its own tooltip
        # never shows; carry the "ask Claude" hint on an enabled wrapper instead.
        self._reuse_wrap = QWidget()
        reuse_box = QVBoxLayout(self._reuse_wrap)
        reuse_box.setContentsMargins(0, 0, 0, 0)
        reuse_box.addWidget(self._reuse_btn)
        info_box.addWidget(self._reuse_wrap)
        self._panes.addWidget(info)

        # The TOC pane holds its width; the browser and info panes both grow with
        # the window (the browser faster), so the info pane stays comfortably wide
        # instead of a thin strip on a large screen. Long metadata values wrap
        # rather than scroll sideways, so these floors are only for readability.
        self._tree.setMinimumWidth(150)
        browser.setMinimumWidth(240)
        info.setMinimumWidth(340)
        self._panes.setStretchFactor(0, 0)
        self._panes.setStretchFactor(1, 3)
        self._panes.setStretchFactor(2, 2)
        self._panes.setSizes([220, 560, 440])

        layout.addWidget(self._panes)

    def _nav_button(self, label: str, tooltip: str, handler) -> QPushButton:
        # Size to the label: the stylesheet's 16px side padding alone is wider
        # than a hardcoded 32px, which clipped the arrow to a blank button.
        btn = QPushButton(label)
        btn.setToolTip(tooltip)
        btn.clicked.connect(handler)
        return btn

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
        # Backstop for a missed completion frame: finish any re-roll ComfyUI has
        # already completed so it lands here without a restart. Reconcile fires
        # each job's own finished/failed handler, which persists and refreshes.
        for job in list(self._reroll_jobs.values()):
            job.reconcile()
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
        # A running re-roll drives the info pane from live frames, not a saved row,
        # so capture it to restore afterward rather than let the folder's default
        # selection replace it. This matters because every re-roll (and each i2v
        # stage) triggers a rebuild the moment its running row lands.
        reroll_key, reroll_frame = self._selected_reroll_key, self._last_reroll_frame
        self._pending_key = None
        self._pending_selection = None
        self._image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
        self._populate_tree(gallery.build_gallery_tree(rows, meta), expanded)
        self._clear_metadata()
        target = self._item_by_key.get(selected_key) or self._default_item()
        # A rebuild restores the prior view; that re-selection isn't a navigation,
        # so keep it off the history (a poll would otherwise pile up duplicates).
        self._suppress_history = True
        try:
            if target is not None:
                self._tree.setCurrentItem(target)  # shows the folder's thumbnails
                self._reselect_generation(selected_gen)
            else:
                self._title.set_display("")
                self._avg_label.setText("")
                self._show_widget(QWidget())
            self._restore_reroll_selection(reroll_key, reroll_frame)
        finally:
            self._suppress_history = False
        # Seed history once with wherever the gallery first lands, so Back works
        # even if the user's very first move is following a link.
        if self._selected and self._history.current() is None:
            self._record_visit(self._selected["prompt_id"])

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

    def _new_tile_pane(self) -> tuple[QWidget, FlowLayout]:
        """A fresh container whose tiles flow to fill the pane's width."""
        container = QWidget()
        flow = FlowLayout(container, spacing=_TILE_SPACING)
        self._clear_selection()
        self._reroll_tile = None  # re-created below only when this folder re-rolls
        self._visible_ids = []
        self._visible_keys = []
        return container, flow

    def _show_folder_tiles(self, groups):
        container, flow = self._new_tile_pane()
        for group in groups:
            tile = FolderTile(
                group.key,
                group.label,
                self._preview_paths(group),
                len(gallery.rows_under(group)),
                group.starred,
            )
            tile.clicked.connect(self._drill_into)
            tile.context_requested.connect(self._folder_context_menu)
            flow.addWidget(tile)
            self._visible_keys.append(group.key)
        self._show_widget(container)

    def _show_thumbnails(self, group):
        container, flow = self._new_tile_pane()
        # The re-roll tile leads the flow so it sits beside the newest item
        # (thumbnails are sorted newest-first).
        if self._can_reroll(group):
            self._add_reroll_tile(flow, group)
        for row in group.rows:
            seed = row.get("seed")
            label = f"seed {seed}" if seed is not None else (
                (row.get("positive_prompt") or "")[:40] or "(no prompt)"
            )
            tw = ThumbnailWidget(row["prompt_id"], row.get("thumbnail_path"), label)
            tw.clicked.connect(self._thumbnail_clicked)
            tw.context_requested.connect(self._thumbnail_context_menu)
            flow.addWidget(tw)
            self._visible_ids.append(row["prompt_id"])
            self._thumb_widgets[row["prompt_id"]] = tw
        self._show_widget(container)

    # --- re-roll: a new variation of a folder's settings, here in the gallery

    def _can_reroll(self, group) -> bool:
        """True when this folder's settings can be re-run as a new variation.

        Mirrors the Reuse Parameters gate — any folder whose workflow the app
        knows how to build, imported or not — since a re-roll is exactly Reuse +
        a random seed + Generate (with missing params filled from the workflow's
        defaults, just as the Generate tab does).
        """
        if self._client is None or not group.rows:
            return False
        return _is_reusable_workflow(group.rows[0].get("workflow_name"))

    def _add_reroll_tile(self, flow, group):
        tile = RerollTile(self._reroll_jobs.get(group.key))
        tile.set_selected(group.key == self._selected_reroll_key)
        tile.add_requested.connect(lambda k=group.key: self._start_reroll(k))
        tile.cancel_requested.connect(lambda k=group.key: self._cancel_reroll(k))
        tile.selected.connect(lambda k=group.key: self._select_reroll(k))
        flow.addWidget(tile)
        self._reroll_tile = tile

    def _start_reroll(self, key: str):
        if self._client is None or key in self._reroll_jobs:
            return  # no client, or this folder already has one running
        item = self._item_by_key.get(key)
        group = item.data(0, _GROUP_ROLE) if item else None
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        row = group.rows[0]
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None:
            return
        params = prepared_params(row, workflow)
        # An i2v whose input image is itself a re-buildable generation re-rolls
        # that image first (fresh start frame), then runs the video on it; any
        # other row just re-rolls its one workflow with the same input, as before.
        source = self._reroll_source_image(row)
        if source is None:
            self._launch_reroll(key, workflow, params, self._on_reroll_finished)
            return
        source_row, image_workflow = source
        image_params = prepared_params(source_row, image_workflow)
        self._launch_reroll(
            key, image_workflow, image_params,
            lambda k, job, files, thumb, dur: self._on_image_reroll_finished(
                k, job, files, thumb, dur, workflow, params
            ),
        )

    def _reroll_source_image(self, row: dict):
        """The image generation ``row``'s input image came from, paired with its
        workflow, when the app can rebuild it — so an i2v re-roll can regenerate a
        fresh start frame first. ``None`` when there's no reusable source image."""
        source_id = gallery.find_source_image_id(row, self._image_rows)
        if source_id is None:
            return None
        source = self._db.get_generation(source_id)
        workflow = WORKFLOW_REGISTRY.get(source.get("workflow_name") or "") if source else None
        return (source, workflow) if workflow is not None else None

    def _launch_reroll(self, key, workflow, params, on_finished):
        """Build, register and submit one re-roll job, wiring its completion to
        ``on_finished(key, job, files, thumb_path, duration)``.

        A running row is recorded before the job is submitted so an app restart
        mid-generation can find it and reconnect, exactly as the Generate tab does.
        """
        try:
            job = GenerationJob(self._client, workflow, params)
        except Exception as e:
            logger.warning("Could not build a re-roll for %s: %s", key, e)
            return
        self._register_reroll_job(key, job, on_finished)
        insert_generation_row(self._db, job)
        try:
            job.start()
            self._db.update_generation(job.prompt_id, status="running")
        except Exception as e:
            logger.warning("Re-roll submission failed for %s: %s", key, e)
            self._db.update_generation(job.prompt_id, status="error", error_message=str(e))
            self._reroll_jobs.pop(key, None)
        self._rerender_current_leaf()

    def _register_reroll_job(self, key, job, on_finished):
        """Track a re-roll job for a folder and wire its completion and failure."""
        self._reroll_jobs[key] = job
        job.finished.connect(
            lambda files, thumb, dur, k=key, j=job: on_finished(k, j, files, thumb, dur)
        )
        job.failed.connect(lambda msg, k=key: self._on_reroll_failed(k, msg))
        job.preview.connect(lambda data, k=key: self._on_reroll_preview(k, data))

    # --- re-roll as the info-pane source ----------------------------------

    def _select_reroll(self, key: str):
        """Make a running re-roll's tile the selected item and mirror its live
        frames into the info pane.

        The tile stands for an in-flight job with no saved file yet, so its
        preview comes from the job's streamed frames rather than
        :meth:`_show_preview`'s on-disk lookup.
        """
        job = self._reroll_jobs.get(key)
        if job is None:
            return
        self._last_reroll_frame = job.last_preview
        self._enter_reroll_selection(key)

    def _restore_reroll_selection(self, key: str | None, frame: bytes | None):
        """After a rebuild, re-assert a still-running re-roll as the info-pane
        source, keeping the frame it was showing (an i2v's image frame while the
        video stage warms up) rather than the fresh video job's empty preview.
        A no-op unless that re-roll is still running in the folder now on screen.
        """
        if key is None or key not in self._reroll_jobs or self._selected_folder_key() != key:
            return
        self._last_reroll_frame = frame
        self._enter_reroll_selection(key)

    def _enter_reroll_selection(self, key: str):
        """Point the info pane at re-roll ``key`` and show its last frame — or a
        'waiting' note, never the idle 'select a generation' placeholder."""
        self._selected_reroll_key = key
        self._selected = None
        self._clear_thumbnail_selection()
        if self._reroll_tile is not None:
            self._reroll_tile.set_selected(True)
        self._reuse_btn.setEnabled(False)
        self._reuse_wrap.setToolTip("")
        self._meta_title.setText("Generating a new variation…")
        self._estimate_label.clear()
        self._meta_panel.clear()
        if self._last_reroll_frame:
            self._preview.show_frame(self._last_reroll_frame)
        else:
            self._preview.show_message("Waiting for preview…")

    def _on_reroll_preview(self, key: str, data: bytes):
        """Mirror a re-roll's live frame into the info pane while it's selected,
        remembering it so it survives the rebuild each stage completion triggers."""
        if key == self._selected_reroll_key:
            self._last_reroll_frame = data
            self._preview.show_frame(data)

    def _clear_thumbnail_selection(self):
        """Drop the thumbnail multi-selection and its highlights while keeping the
        on-screen tiles (unlike a rebuild), so picking the re-roll deselects them."""
        self._selected_ids = set()
        self._selection_anchor = None
        self._refresh_selection_highlights()

    def _clear_reroll_selection(self):
        """Stop treating a running re-roll as the info-pane source — a real
        generation is taking over the pane, or the re-roll has ended."""
        self._selected_reroll_key = None
        self._last_reroll_frame = None
        if self._reroll_tile is not None:
            self._reroll_tile.set_selected(False)

    def reconnect_running_rerolls(self):
        """Rebind live jobs to any re-rolls left running by a previous session.

        Each still-in-flight row this app doesn't already own (a Generate tab owns
        its own jobs) is picked back up so its completion is recorded and its tile
        shows live progress again — even for a folder the user hasn't opened yet.
        Called once at startup, after the Generate tabs have claimed their jobs.
        """
        if self._client is None:
            return
        claimed = self._claimed_ids()
        for row in self._db.list_generations():
            if row.get("status") in ("running", "pending") and row["prompt_id"] not in claimed:
                self._reconnect_reroll(row)
        self._rerender_current_leaf()

    def _reconnect_reroll(self, row: dict):
        key = gallery.settings_folder_key(row)
        if key in self._reroll_jobs:
            return  # a job for this folder is already tracked
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None:
            return
        params = gallery.parse_params(row.get("params_json"))
        try:
            job = GenerationJob.reconnect(self._client, workflow, params, row["prompt_id"])
        except Exception as e:
            logger.warning("Could not reconnect re-roll for %s: %s", key, e)
            return
        self._register_reroll_job(key, job, self._on_reroll_finished)

    def _cancel_reroll(self, key: str):
        job = self._reroll_jobs.pop(key, None)
        if job is not None:
            job.cancel()
            self._db.delete_generation(job.prompt_id)  # drop the abandoned running row
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()

    def _abandon_reroll_preview(self, key: str):
        """Empty the info pane if it was mirroring a re-roll that has ended with no
        result to show (cancelled or failed)."""
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()
            self._clear_metadata()

    def _on_image_reroll_finished(self, key, image_job, files, thumb_path, duration,
                                  video_workflow, video_params):
        """First stage of a chained i2v re-roll: finalize the fresh image, then run
        the video on it, pointing its input at the just-saved output."""
        self._reroll_jobs.pop(key, None)
        mark_generation_completed(self._db, image_job.prompt_id, files, thumb_path, duration)
        input_ref = gallery.output_file_reference(files)
        if input_ref is not None:
            video_params = {**video_params, "input_image": input_ref}
        self._launch_reroll(key, video_workflow, video_params, self._on_reroll_finished)

    def _on_reroll_finished(self, key, job, files, thumb_path, duration):
        self._reroll_jobs.pop(key, None)
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()  # refresh re-selects it as a finished thumbnail
        mark_generation_completed(self._db, job.prompt_id, files, thumb_path, duration)
        self.refresh()  # the finished generation now shows as a normal thumbnail

    def _on_reroll_failed(self, key, message):
        job = self._reroll_jobs.pop(key, None)
        if job is not None:
            self._db.update_generation(job.prompt_id, status="error", error_message=message)
        self._abandon_reroll_preview(key)
        logger.warning("Re-roll failed for %s: %s", key, message)
        self._rerender_current_leaf()

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
        self._on_thumbnail_clicked(prompt_id)  # records the visit itself

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

    def _thumbnail_context_menu(self, prompt_id: str, global_pos):
        """Right-click menu for a thumbnail: delete the picked item(s).

        Right-clicking a tile that isn't part of the current selection first
        selects just it, so the menu always acts on something visible.
        """
        if prompt_id not in self._selected_ids:
            self._apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
            self._on_thumbnail_clicked(prompt_id)
        count = len(self._selected_ids)
        menu = QMenu(self)
        delete_action = menu.addAction(f"Delete {count} item{'s' if count != 1 else ''}")
        if menu.exec(global_pos) is delete_action:
            self._delete_selection()

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
        # Land on the parent folder after the rebuild rather than jumping to the
        # top of the tree, so the view stays where the user was working.
        item = self._item_by_key.get(group.key)
        parent = item.parent() if item is not None else None
        if parent is not None:
            self._tree.setCurrentItem(parent)
        self._delete_rows(rows)

    def _delete_rows(self, rows):
        if not rows:
            return
        deleted_ids = {r["prompt_id"] for r in rows}
        if self._selected and self._selected.get("prompt_id") in deleted_ids:
            self._preview.clear()  # release any file handle before the files move
        try:
            self._actions.delete_rows(rows)
        except Exception as e:
            # A delete that throws (a locked file, a vanished path) must not fail
            # silently — show what went wrong rather than appearing to do nothing.
            logger.exception("Failed to delete %d generation(s)", len(rows))
            QMessageBox.warning(
                self, "Delete failed",
                f"Could not delete the selected item(s):\n\n{e}",
            )
            return
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
        self._clear_reroll_selection()  # a saved generation takes over the info pane
        self._selected = row
        reusable = _is_reusable_workflow(row.get("workflow_name"))
        self._reuse_btn.setEnabled(reusable)
        self._reuse_wrap.setToolTip(
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
        source_id = gallery.find_source_image_id(row, self._image_rows)
        self._meta_panel.show_row(row, source_id)
        # Every view of a generation — a thumbnail click, a folder's auto-selected
        # first item, a followed link — is a browsing step, unless a rebuild or
        # Back/Forward is re-selecting (those move within history, not onto it).
        if not self._suppress_history:
            self._record_visit(prompt_id)

    def _show_preview(self, row: dict):
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            self._preview.clear()
        else:
            self._preview.show_media(*preview)

    def _on_source_link(self, prompt_id: str):
        self._show_generation(prompt_id)
        self._record_visit(prompt_id)

    # --- back/forward navigation ------------------------------------------

    def _show_generation(self, prompt_id: str):
        """Select a generation and its folder without recording — the move
        Back/Forward and a link both make. Switching folders auto-selects the
        folder's first item on the way; suppressing keeps that off the history,
        and a recording caller (a link) adds the real target itself afterward."""
        self._suppress_history = True
        try:
            leaf = self._leaf_by_id.get(prompt_id)
            if leaf is not None:
                self._tree.setCurrentItem(leaf)  # shows that folder's thumbnails
            self._on_thumbnail_clicked(prompt_id)
        finally:
            self._suppress_history = False

    def _record_visit(self, prompt_id: str):
        self._history.visit(prompt_id)
        self._sync_nav_buttons()

    def _go_back(self):
        prompt_id = self._history.back()
        if prompt_id is not None:
            self._show_generation(prompt_id)
        self._sync_nav_buttons()

    def _go_forward(self):
        prompt_id = self._history.forward()
        if prompt_id is not None:
            self._show_generation(prompt_id)
        self._sync_nav_buttons()

    def _sync_nav_buttons(self):
        self._back_btn.setEnabled(self._history.can_go_back())
        self._forward_btn.setEnabled(self._history.can_go_forward())

    def _clear_metadata(self):
        self._selected = None
        self._reuse_btn.setEnabled(False)
        self._reuse_wrap.setToolTip("")
        self._meta_title.setText("Select a generation")
        self._estimate_label.clear()
        self._meta_panel.clear()
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
