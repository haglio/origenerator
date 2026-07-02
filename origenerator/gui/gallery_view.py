import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QPushButton, QToolButton, QTreeWidgetItem, QSplitter,
    QMenu, QInputDialog, QAbstractItemView, QMessageBox, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, QTimer, QPoint, QSize, pyqtSignal

from origenerator import evolver_export, gallery, timing
from origenerator.gui import icons
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import (
    COMFYUI_OUTPUT_DIR, EVOLVER_INBOX_DIR, EVOLVER_SOURCE, STATE_DIR, THUMB_DIR,
)
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import merge_denormalized
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.folder_tree import FolderTree, BRANCH_ICON_ROLE
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.metadata_panel import MetadataPanel
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.gui.inflight_card import InFlightCard, InFlightItem
from origenerator.navigation import NavigationHistory
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_GROUP_ROLE = Qt.ItemDataRole.UserRole  # the gallery group a tree node represents
_TILE_SPACING = 8  # gap between tiles in the flowing main view
_POLL_INTERVAL_MS = 1500
_PREVIEW_COUNT = 4
_RECENTS_KEY = "__recents__"  # synthetic tree node listing recently generated items
_RECENTS_LABEL = "Recents"  # its row label; a clock is drawn in the caret column
_RECENTS_LIMIT = 50  # most recent generations the shelf lists at once
_STARRED_KEY = "__starred__"  # synthetic tree node collecting every starred folder
_STARRED_LABEL = "Starred"  # its row label; the star is drawn in the caret column
_STARRED_TITLE = "★ " + _STARRED_LABEL  # the browser-pane heading for the shelf
_ANIMATED_STRIP_LIMIT = 8  # most animation previews shown for one image at once
_PANE_MARGINS = (8, 8, 8, 8)  # breathing room inside each of the three panes


def _is_deletable_folder(group) -> bool:
    """Whether a folder may be deleted: anything nested inside a workflow.

    Model, LoRA, source-image, and settings folders live within a workflow folder
    and are fair game; a whole workflow or media folder is off-limits, so a
    workflow's entire history can never be wiped in one action.
    """
    return isinstance(
        group,
        (gallery.ModelGroup, gallery.LoraGroup, gallery.SourceImageGroup, gallery.SettingsGroup),
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
                 claimed_ids=None, generate_inflight=None):
        super().__init__(parent)
        self._db = db
        self._client = client
        # In-flight ids some other view already tracks (a Generate tab owns its own
        # jobs), so re-roll reconnection doesn't also adopt them. Queried live.
        self._claimed_ids = claimed_ids or (lambda: set())
        # In-flight InFlightItems from the Generate tabs, so the Recents shelf can
        # show every queued/running generation app-wide, not just this gallery's
        # re-rolls. Queried live each render/poll.
        self._generate_inflight = generate_inflight or (lambda: [])
        # The re-roll controller owns the live jobs and their DB lifecycle; the
        # view reacts to its signals with the redraws they call for.
        self._reroll = RerollController(db, client)
        self._reroll.changed.connect(self._rerender_current_leaf)
        self._reroll.preview.connect(self._on_reroll_preview)
        self._reroll.finished.connect(self._on_reroll_finished)
        self._reroll.failed.connect(self._on_reroll_failed)
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
        self._recents_item: QTreeWidgetItem | None = None  # the "Recents" shelf row
        self._recent_rows: list[dict] = []  # recently generated rows, newest first
        self._inflight_cards: dict[str, InFlightCard] = {}  # live in-flight cards, by job key
        self._inflight_by_key: dict[str, InFlightItem] = {}  # their items, for click routing
        self._inflight_signature: tuple = ()  # the in-flight set now drawn on the shelf
        self._starred_item: QTreeWidgetItem | None = None  # the "★ Starred" shelf row
        self._starred_groups: list = []  # folders the shelf collects, in tree order
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
        self._strip_pid: str | None = None  # generation whose animations the strip shows
        self._build_ui()
        self._sync_undo_button()
        self._sync_nav_buttons()
        self._sync_delete_button()
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

        # TOC pane: folder tree (media -> workflow -> model -> LoRA -> [source image]
        # -> settings; a LoRA-less workflow collapses the LoRA level to one
        # "(no LoRA)" folder, and the source-image level shows only for
        # image-conditioned workflows). Folders start collapsed and only expand on
        # the disclosure arrow; double-click renames.
        self._tree = FolderTree(_GROUP_ROLE)  # it offers star/delete on leaf rows itself
        self._tree.setHeaderHidden(True)
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_tree_context_menu)
        self._tree.currentItemChanged.connect(self._on_folder_selected)
        self._tree.itemDoubleClicked.connect(self._begin_inline_rename)
        self._tree.itemChanged.connect(self._commit_inline_rename)
        self._tree.star_clicked.connect(self._toggle_star)          # hover-row action
        self._tree.delete_clicked.connect(self._delete_folder_by_key)
        toc = QWidget()
        toc_box = QVBoxLayout(toc)
        toc_box.setContentsMargins(*_PANE_MARGINS)
        toc_box.addWidget(self._tree)
        self._panes.addWidget(toc)

        # Browser pane: a header (folder title, then a back/forward/undo toolbar)
        # over the flowing contents. Double-clicking the title renames the folder.
        browser = QWidget()
        browser_box = QVBoxLayout(browser)
        browser_box.setContentsMargins(*_PANE_MARGINS)
        header = QHBoxLayout()
        self._title = EditableHeader()
        self._title.edit_requested.connect(self._begin_title_rename)
        self._title.edited.connect(self._commit_title_rename)
        header.addWidget(self._title, 1)
        # A compact, grouped toolbar: browse back/forward, undo, delete — icon-only.
        self._back_btn = self._tool_button(icons.back_icon(), "Back", self._go_back)
        self._forward_btn = self._tool_button(icons.forward_icon(), "Forward", self._go_forward)
        self._undo_btn = self._tool_button(icons.undo_icon(), "Undo", self._undo)
        self._delete_btn = self._tool_button(icons.delete_icon(), "Delete", self._delete_selection)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)
        for button in (self._back_btn, self._forward_btn, self._undo_btn, self._delete_btn):
            toolbar.addWidget(button)
        header.addLayout(toolbar)
        header.setAlignment(toolbar, Qt.AlignmentFlag.AlignTop)
        browser_box.addLayout(header)
        # Shown only while a Recents item is previewed: that item's generation lives
        # in a folder other than the shelf on screen, so this jumps the browser to
        # it. Left-aligned at its natural width, and it collapses away when hidden.
        self._containing_folder_btn = QPushButton("Go to containing folder")
        self._containing_folder_btn.clicked.connect(self._go_to_containing_folder)
        self._containing_folder_btn.hide()
        folder_row = QHBoxLayout()
        folder_row.setContentsMargins(0, 0, 0, 0)
        folder_row.addWidget(self._containing_folder_btn)
        folder_row.addStretch(1)
        browser_box.addLayout(folder_row)
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
        info_box.setContentsMargins(*_PANE_MARGINS)
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
        # For an image, the videos it was animated into — click one to open it.
        self._animated_strip = AnimatedVideoStrip()
        self._animated_strip.video_activated.connect(self._on_source_link)
        info_box.addWidget(self._animated_strip)
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
        # Video-only: copy the selected clip into Evolver's inbox for sorting and
        # upscaling. Hidden entirely for images (Evolver is a video pipeline)
        # rather than shown disabled, so it's absent when it can't apply.
        self._evolver_btn = QPushButton("Send to Evolver")
        self._evolver_btn.setToolTip(
            "Copy this video into Evolver's inbox for sorting and upscaling."
        )
        self._evolver_btn.clicked.connect(self._on_send_to_evolver)
        self._evolver_btn.hide()
        info_box.addWidget(self._evolver_btn)
        self._panes.addWidget(info)

        # The TOC pane holds its width; the browser and info panes both grow with
        # the window (the browser faster), so the info pane stays comfortably wide
        # instead of a thin strip on a large screen. Long metadata values wrap
        # rather than scroll sideways, so these floors only need to keep the panes
        # readable — kept low enough that the window can still tile into a monitor
        # third or a portrait-monitor half.
        toc.setMinimumWidth(120)
        browser.setMinimumWidth(210)
        info.setMinimumWidth(300)
        self._panes.setStretchFactor(0, 0)
        self._panes.setStretchFactor(1, 3)
        self._panes.setStretchFactor(2, 2)
        self._panes.setSizes([220, 560, 440])

        layout.addWidget(self._panes)

    def _tool_button(self, icon, tooltip: str, handler) -> QToolButton:
        """A compact, icon-only toolbar button for the browser-pane header."""
        btn = QToolButton()
        btn.setObjectName("iconButton")
        btn.setIcon(icon)
        btn.setIconSize(QSize(16, 16))
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
        elif self._showing_recents():
            # No DB change, but in-flight cards still need their live frames pushed
            # and a re-render when a locally-queued Generate tab appears/vanishes
            # (it carries no DB row to move the fingerprint).
            self._refresh_inflight()

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
        tree_model = gallery.build_gallery_tree(rows, meta)
        self._starred_groups = gallery.starred_folders(tree_model)
        self._recent_rows = gallery.recent_generations(rows, _RECENTS_LIMIT)
        self._populate_tree(tree_model, expanded)
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
                self._strip_pid = None
                self._animated_strip.show_videos([])  # nothing selected: no animations
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
        self._recents_item = None
        self._starred_item = None
        root = self._tree.invisibleRootItem()
        # Synthetic shelves lead the tree: Recents (in-flight work plus recently
        # finished items) whenever there is anything to show — so a first-ever
        # generation is visible while it runs, before any folder exists — then
        # Starred (bookmarked folders) once folders do. Each is reachable in one
        # click however the tree is scrolled, and draws its marker in the caret
        # column so its label lines up with the media folders below.
        if tree_model or self._inflight_items():
            self._recents_item = self._add_shelf(
                root, _RECENTS_LABEL, _RECENTS_KEY, icons.clock_icon(), "Recently generated"
            )
        if tree_model:
            self._starred_item = self._add_shelf(
                root, _STARRED_LABEL, _STARRED_KEY, icons.star_icon(filled=True),
                "Your starred folders"
            )
        for media in tree_model:
            self._add_node(media, root)
        # Folders default to collapsed; only restore folders the user had open.
        for key in expanded_keys:
            item = self._item_by_key.get(key)
            if item is not None:
                item.setExpanded(True)
        self._tree.blockSignals(False)

    def _add_shelf(self, root, label, key, icon, tooltip) -> QTreeWidgetItem:
        """Add a synthetic shelf row (Recents/Starred) leading the tree, its marker
        drawn in the caret column so its label aligns with the media folders below."""
        item = QTreeWidgetItem([label])
        item.setData(0, BRANCH_ICON_ROLE, icon)  # marker in the caret column
        item.setToolTip(0, tooltip)
        root.addChild(item)
        self._item_by_key[key] = item
        return item

    def _add_node(self, group, parent_item) -> QTreeWidgetItem:
        # Starred state shows as the row's star icon (the delegate reads it from
        # the group), so the label itself carries no ★ prefix.
        item = QTreeWidgetItem([group.label])
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)  # for inline rename
        item.setData(0, _GROUP_ROLE, group)
        # A workflow/model/LoRA row wears a lettered chip naming its recipe level,
        # so its place in the hierarchy reads at a glance rather than by counting
        # indentation; the level joins the tooltip too. Media roots and settings
        # leaves get neither (folder_level returns None).
        level = gallery.folder_level(group)
        if level is not None:
            item.setIcon(0, icons.level_badge_icon(level))
            item.setToolTip(0, f"{group.label} · {icons.LEVEL_LABELS[level]}")
        else:
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
        """The folder to land on with no saved target: the first real media folder;
        failing that (only in-flight work so far, no finished folders), the Recents
        shelf, so a first generation stays visible while it runs."""
        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            item = root.child(i)
            if item is not self._recents_item and item is not self._starred_item:
                return item
        return self._recents_item

    def _expanded_keys(self) -> set[str]:
        return {
            key for key, item in self._item_by_key.items() if item.isExpanded()
        }

    def _selected_folder_key(self) -> str | None:
        item = self._tree.currentItem()
        if item is None:
            return None
        if item is self._recents_item:
            return _RECENTS_KEY  # so a rebuild keeps the shelf selected
        if item is self._starred_item:
            return _STARRED_KEY  # so a rebuild keeps the shelf selected
        group = item.data(0, _GROUP_ROLE)
        return group.key if group else None

    def _on_folder_selected(self, current, _previous):
        if current is None:
            self._title.set_display("")
            self._avg_label.setText("")
            self._show_widget(QWidget())
            self._visible_ids = []
            self._visible_keys = []
            self._sync_delete_button()
            return
        if current is self._recents_item:
            self._show_recents_overview()
            return
        if current is self._starred_item:
            self._show_starred_overview()
            return
        group = current.data(0, _GROUP_ROLE)
        self._title.set_display(self._breadcrumb(current))
        self._update_folder_average(group)
        if isinstance(group, gallery.SettingsGroup):
            self._show_thumbnails(group)
        else:
            self._show_folder_tiles(gallery.child_groups(group))
        self._select_first_item(group)
        self._sync_delete_button()

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

    def _add_folder_tile(self, flow, group, *, starred, context=""):
        """Build one folder tile, wire its click/context signals, and track it."""
        tile = FolderTile(
            group.key, group.label, self._preview_paths(group),
            len(gallery.rows_under(group)), starred=starred, context=context,
            level=gallery.folder_level(group),
        )
        tile.clicked.connect(self._drill_into)
        tile.context_requested.connect(self._folder_context_menu)
        flow.addWidget(tile)
        self._visible_keys.append(group.key)

    def _show_folder_tiles(self, groups):
        container, flow = self._new_tile_pane()
        for group in groups:
            self._add_folder_tile(flow, group, starred=group.starred)
        self._show_widget(container)

    # --- the Recents shelf: in-flight work, then recently finished items ----

    def _show_recents_overview(self):
        """Render the Recents shelf: a card for every in-flight generation (queued
        or running, from a Generate tab or a gallery re-roll) atop the recently
        finished items. Clicking an in-flight card reveals where its job runs; a
        finished one previews in the info pane, right here on the shelf, the way a
        thumbnail does inside a folder — and a "Go to containing folder" button
        then offers the jump to its folder. Opens with the info pane cleared, so
        it shows nothing until an item is picked."""
        self._title.set_display(_RECENTS_LABEL)
        self._avg_label.setText("")
        self._clear_metadata()
        self._render_recents()
        self._sync_delete_button()

    def _render_recents(self):
        """Draw the shelf: in-flight cards first (the newest, still-cooking work),
        then the finished thumbnails; a hint when there is neither."""
        container, flow = self._new_tile_pane()
        self._inflight_cards = {}
        self._inflight_by_key = {}
        items = self._inflight_items()
        self._inflight_signature = _inflight_signature(items)
        for item in items:
            card = InFlightCard(item)
            card.clicked.connect(self._on_inflight_clicked)
            flow.addWidget(card)
            self._inflight_cards[item.key] = card
            self._inflight_by_key[item.key] = item
        for row in self._recent_rows:
            tw = ThumbnailWidget(
                row["prompt_id"], row.get("thumbnail_path"), self._thumbnail_caption(row),
                media_type=gallery.media_type_of_row(row),  # a corner badge: image or video
                movie_path=self._animated_preview(row),     # videos loop; images stay still
            )
            tw.clicked.connect(self._thumbnail_clicked)  # preview it here, on the shelf
            tw.double_clicked.connect(self._open_in_containing_folder)  # or open its folder
            flow.addWidget(tw)
            self._visible_ids.append(row["prompt_id"])
            self._thumb_widgets[row["prompt_id"]] = tw
        # An empty shelf teaches how to fill it rather than showing a blank pane.
        self._show_widget(container if (items or self._recent_rows) else self._empty_state(
            "No recent generations yet.\n\nItems you make — from a Generate tab or a "
            "gallery re-roll — collect here, newest first."
        ))

    def _showing_recents(self) -> bool:
        return (self._recents_item is not None
                and self._tree.currentItem() is self._recents_item)

    def _refresh_inflight(self):
        """Between rebuilds, keep the in-flight cards live: push each job's latest
        frame into its card, and re-render only when the *set* of in-flight jobs
        changes — one ends, or a Generate tab is queued behind another with no DB
        row to move the fingerprint."""
        items = self._inflight_items()
        if _inflight_signature(items) != self._inflight_signature:
            self._render_recents()
            return
        for item in items:
            self._inflight_by_key[item.key] = item  # keep the reveal current
            card = self._inflight_cards.get(item.key)
            if card is not None:
                card.update_item(item)

    def _inflight_items(self) -> list:
        """Every queued/running generation as a card model, running ones first.

        The database's running/pending rows are the source of truth for what's in
        flight — a Generate tab's job or a gallery re-roll — so a card shows even
        when no live job object is tracking a row (after a restart that hasn't
        re-adopted it, say). Live frames and tab-routing are grafted on from the
        tracking objects when present: a Generate tab's own job carries them, and
        a re-roll's frame comes from its :class:`GenerationJob`. A Generate tab
        still waiting its turn in the local queue has no row yet, so those are
        added straight from the provider.
        """
        generate = {it.key: it for it in self._generate_inflight()}
        reroll_by_pid = {job.prompt_id: (key, job)
                         for key, job in self._reroll_jobs.items()}
        image_index = None  # built lazily, only to place an untracked row's folder
        items, seen = [], set()
        for row in self._db.list_generations():
            if row.get("status") not in ("running", "pending"):
                continue
            pid = row["prompt_id"]
            seen.add(pid)
            if pid in generate:
                items.append(generate[pid])  # a Generate tab's job: its own frame + reveal
                continue
            tracked = reroll_by_pid.get(pid)
            if tracked is not None:
                folder_key, frame = tracked[0], tracked[1].last_preview
            else:  # a running row no live job holds — still show it, keyed to its folder
                if image_index is None:
                    image_index = gallery.build_image_config_index(self._image_rows)
                folder_key, frame = gallery.settings_folder_key(row, image_index), None
            items.append(InFlightItem(
                key=pid,
                caption=gallery.config_tab_title(
                    row.get("workflow_name") or "", gallery.parse_params(row.get("params_json"))
                ),
                status="running" if row.get("status") == "running" else "queued",
                frame=frame,
                reveal=lambda k=folder_key: self._reveal_reroll(k),
                media_type=gallery.media_type_of_row(row),  # image/video corner badge
            ))
        # A Generate tab queued behind another carries no DB row yet — add it too.
        for pid, item in generate.items():
            if pid not in seen:
                items.append(item)
        items.sort(key=lambda it: it.status != "running")  # stable: running first
        return items

    def _reveal_reroll(self, key: str):
        """Open the folder a re-roll runs in and select its live tile."""
        item = self._item_by_key.get(key)
        if item is not None:
            self._tree.setCurrentItem(item)  # shows the folder and its re-roll tile
            self._select_reroll(key)

    def _on_inflight_clicked(self, key: str):
        item = self._inflight_by_key.get(key)
        if item is not None:
            item.reveal()

    def _go_to_containing_folder(self):
        """The 'Go to containing folder' button's action: open the previewed Recents
        item in its own folder, selected."""
        if self._selected is not None:
            self._open_in_containing_folder(self._selected["prompt_id"])

    def _open_in_containing_folder(self, prompt_id: str):
        """Jump the browser pane to ``prompt_id``'s own folder and land on the item
        itself — its tile picked and highlighted, as if you'd navigated in and
        clicked it, not just auto-previewing the folder's first item. Shared by the
        button and a double-click on a Recents tile."""
        self._on_source_link(prompt_id)  # open the folder, previewing the item
        # The navigation renders the folder's tiles; now pick this one so it reads
        # as the selected item rather than an unhighlighted preview.
        self._apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)

    def _sync_containing_folder_button(self):
        """Offer "Go to containing folder" only while the Recents shelf is showing
        a previewed item: that's the one view whose info pane holds a generation
        from a folder other than the one on screen."""
        self._containing_folder_btn.setVisible(
            self._showing_recents() and self._selected is not None
        )

    # --- the Starred shelf: every bookmarked folder, gathered in one place ---

    def _show_starred_overview(self):
        """Render the Starred shelf: one tile per bookmarked folder, each captioned
        with its breadcrumb so identically-named folders stay tellable apart. Like
        a branch folder it lists sub-folders rather than a single generation, so the
        info pane clears instead of previewing one folder's first item."""
        self._title.set_display(_STARRED_TITLE)
        self._avg_label.setText("")
        self._clear_metadata()
        self._show_starred_tiles(self._starred_groups)
        self._sync_delete_button()

    def _show_starred_tiles(self, groups):
        container, flow = self._new_tile_pane()
        for group in groups:
            item = self._item_by_key.get(group.key)
            context = self._breadcrumb(item.parent()) if item and item.parent() else ""
            self._add_folder_tile(flow, group, starred=False, context=context)
        # An empty shelf teaches how to fill it rather than showing a blank pane.
        self._show_widget(container if groups else self._empty_state(
            "No starred folders yet.\n\nHover a folder in the list and click its "
            "star, or right-click a folder and choose Star, to collect it here."
        ))

    @staticmethod
    def _empty_state(text: str) -> QWidget:
        """A centered hint filling an otherwise-blank shelf pane (Recents/Starred)."""
        label = QLabel(text)
        label.setObjectName("estimateLabel")
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        label.setContentsMargins(16, 24, 16, 16)
        return label

    @staticmethod
    def _thumbnail_caption(row) -> str:
        """A thumbnail's caption: its seed, else a snippet of its prompt."""
        seed = row.get("seed")
        if seed is not None:
            return f"seed {seed}"
        return (row.get("positive_prompt") or "")[:40] or "(no prompt)"

    def _show_thumbnails(self, group):
        container, flow = self._new_tile_pane()
        # The re-roll tile leads the flow so it sits beside the newest item
        # (thumbnails are sorted newest-first).
        if self._can_reroll(group):
            self._add_reroll_tile(flow, group)
        for row in group.rows:
            tw = ThumbnailWidget(
                row["prompt_id"], row.get("thumbnail_path"), self._thumbnail_caption(row),
                movie_path=self._animated_preview(row),  # videos loop; images stay still
            )
            tw.clicked.connect(self._thumbnail_clicked)
            tw.double_clicked.connect(self._thumbnail_double_clicked)
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

    @property
    def _reroll_jobs(self) -> dict:
        """The live re-roll jobs, keyed by settings-folder key. Owned by the
        controller; surfaced here for the Recents shelf and the info pane."""
        return self._reroll.jobs

    def _add_reroll_tile(self, flow, group):
        tile = RerollTile(self._reroll.job_for(group.key))
        tile.set_selected(group.key == self._selected_reroll_key)
        tile.add_requested.connect(lambda k=group.key: self._start_reroll(k))
        tile.cancel_requested.connect(lambda k=group.key: self._cancel_reroll(k))
        tile.selected.connect(lambda k=group.key: self._select_reroll(k))
        flow.addWidget(tile)
        self._reroll_tile = tile

    def _start_reroll(self, key: str):
        """Start a fresh variation for the folder ``key`` names and select it, so
        its live preview fills the info pane at once.

        Skips a folder already re-rolling (or a missing client) without stealing
        the info pane — the same guard the controller enforces before launching.
        """
        if self._client is None or key in self._reroll_jobs:
            return  # no client, or this folder already has one running
        item = self._item_by_key.get(key)
        group = item.data(0, _GROUP_ROLE) if item else None
        self._reroll.start(key, group, self._image_rows)
        self._select_reroll(key)  # a no-op if the launch above failed to register

    # --- re-roll as the info-pane source ----------------------------------

    def _select_reroll(self, key: str):
        """Make a running re-roll's tile the selected item and mirror its live
        frames into the info pane.

        The tile stands for an in-flight job with no saved file yet, so its
        preview comes from the job's streamed frames rather than
        :meth:`_render_preview`'s on-disk lookup.
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
        self._update_evolver_button(None)  # a running re-roll isn't a saved video
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
        """Rebind live jobs to any re-rolls left running by a previous session, so
        each shows live progress and records its completion again. Called once at
        startup, after the Generate tabs have claimed their own jobs."""
        self._reroll.reconnect_running(self._claimed_ids())

    def _cancel_reroll(self, key: str):
        self._reroll.cancel(key)
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()

    def _abandon_reroll_preview(self, key: str):
        """Empty the info pane if it was mirroring a re-roll that has ended with no
        result to show (cancelled or failed)."""
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()
            self._clear_metadata()

    def _on_reroll_finished(self, key: str):
        """A re-roll saved its result (finalized by the controller): drop it as the
        info-pane source and rebuild so it shows as a normal thumbnail."""
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()  # refresh re-selects it as a finished thumbnail
        self.refresh()

    def _on_reroll_failed(self, key: str):
        """A re-roll failed (recorded by the controller): release the info pane if
        it was showing this one, and redraw the folder without its tile."""
        self._abandon_reroll_preview(key)
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

    def _thumbnail_double_clicked(self, prompt_id: str):
        """Open a thumbnail as a Generate tab — the same "reuse parameters"
        gesture as picking it and clicking the button. Inert for a workflow the
        app can't rebuild, matching the button's greyed-out state."""
        self._on_thumbnail_clicked(prompt_id)  # make it the selected generation
        self._on_reuse()

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
        self._sync_delete_button()

    def _clear_selection(self):
        self._selected_ids = set()
        self._selection_anchor = None
        self._thumb_widgets = {}
        self._sync_delete_button()

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
        focus = self._actions.undo()  # a restored generation to return to, if any
        self._clear_selection()
        self.refresh()
        # After undoing a delete, go back to the folder it emptied (now restored),
        # rather than leaving the user on the parent we'd navigated to.
        if focus and focus in self._leaf_by_id:
            self._show_generation(focus)
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
        name = item.text(0)  # no ★ prefix to strip — the star is a row icon now
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

    def _delete_folder_by_key(self, key: str):
        """Delete the folder a hover-row trash click names."""
        item = self._item_by_key.get(key)
        group = item.data(0, _GROUP_ROLE) if item else None
        if group is not None:
            self._delete_folder(group)

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
        # Resolve the preview once and share it: both the player and the
        # Send-to-Evolver button key off the same on-disk file.
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        self._update_evolver_button(preview)
        self._render_preview(preview)
        self._meta_title.setText(
            f"{row['workflow_name']} ({row['workflow_version']})"
        )
        self._estimate_label.setText(
            f"Typical time: {timing.estimate_label(self._db.recent_durations(row['workflow_name']))}"
        )
        source_id = gallery.find_source_image_id(row, self._image_rows)
        self._meta_panel.show_row(row, source_id)
        self._update_animated_strip(row)
        self._sync_containing_folder_button()  # a Recents preview offers the jump
        # Every view of a generation — a thumbnail click, a folder's auto-selected
        # first item, a followed link — is a browsing step, unless a rebuild or
        # Back/Forward is re-selecting (those move within history, not onto it).
        if not self._suppress_history:
            self._record_visit(prompt_id)

    def _update_animated_strip(self, row: dict):
        """Show the videos an image was animated into. Rebuilt only when the
        selection changes, so a poll's re-selection doesn't restart the previews
        every tick."""
        if row["prompt_id"] == self._strip_pid:
            return
        self._strip_pid = row["prompt_id"]
        self._animated_strip.show_videos(self._animated_items(row))

    def _animated_items(self, row: dict) -> list[tuple]:
        """(prompt_id, looping-preview path, still path) for each video this image
        was animated into — empty for anything but an image with animations."""
        if gallery.media_type_of_row(row) != "image":
            return []
        videos = gallery.videos_from_source_image(row, self._video_rows())
        if len(videos) > _ANIMATED_STRIP_LIMIT:
            logger.info("Image %s has %d animations; showing the first %d",
                        row["prompt_id"], len(videos), _ANIMATED_STRIP_LIMIT)
        return [
            (v["prompt_id"], self._animated_preview(v), v.get("thumbnail_path"))
            for v in videos[:_ANIMATED_STRIP_LIMIT]
        ]

    def _video_rows(self) -> list[dict]:
        return [r for r in self._db.list_generations() if gallery.media_type_of_row(r) == "video"]

    def _animated_preview(self, row: dict) -> str | None:
        """The looping-WebP preview for a video ``row`` — ``None`` for an image or a
        video whose file is gone or unreadable, so the tile shows its still instead.
        The same resolver feeds the grid tiles, the Recents shelf, and the
        'Animated in' strip, with the app's output and thumbnail directories."""
        return gallery.animated_preview_path(row, COMFYUI_OUTPUT_DIR, THUMB_DIR)

    def _render_preview(self, preview):
        """Play/show the already-resolved ``(path, media_type)``, or clear when
        ``None`` (nothing displayable resolved for the selection)."""
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

    def _sync_delete_button(self):
        """Enable Delete when there's a target — picked thumbnails, else the
        current deletable folder — and say which in its tooltip."""
        count = len(self._selected_ids)
        folder = self._current_deletable_folder()
        if count:
            self._delete_btn.setEnabled(True)
            self._delete_btn.setToolTip(f"Delete {count} item{'s' if count != 1 else ''}")
        elif folder is not None:
            self._delete_btn.setEnabled(True)
            self._delete_btn.setToolTip(f"Delete folder “{folder.label}”")
        else:
            self._delete_btn.setEnabled(False)
            self._delete_btn.setToolTip("Nothing to delete")

    def _clear_metadata(self):
        self._selected = None
        self._reuse_btn.setEnabled(False)
        self._reuse_wrap.setToolTip("")
        self._update_evolver_button(None)
        self._meta_title.setText("Select a generation")
        self._estimate_label.clear()
        self._meta_panel.clear()
        self._preview.clear()
        self._sync_containing_folder_button()  # nothing selected: no jump to offer

    def _update_evolver_button(self, preview):
        """Reflect the selection on the Send-to-Evolver button.

        Shown only when the selection is a video with a file on disk; Evolver is
        a video pipeline, so for an image or a missing file the button is hidden
        rather than shown disabled. A video already sent shows a persistent,
        disabled "Sent ✓" so the gallery remembers the handoff across selections
        and sessions (the flag is read from the row, which the DB persists).

        ``preview`` is the selection's resolved ``(path, media_type)``, or
        ``None`` when nothing displayable is selected.
        """
        is_video = preview is not None and preview[1] == "video"
        self._evolver_btn.setVisible(is_video)
        if not is_video:
            return
        already_sent = bool(self._selected and self._selected.get("evolver_exported_at"))
        self._evolver_btn.setText("Sent to Evolver ✓" if already_sent else "Send to Evolver")
        self._evolver_btn.setEnabled(not already_sent)

    def _exportable_video_path(self) -> Path | None:
        """The on-disk video file backing the current selection, or ``None`` when
        the selection isn't a video (or its file is missing) and can't be sent.
        Resolved fresh at send time, so a file deleted since selection is caught."""
        if not self._selected:
            return None
        preview = gallery.resolve_preview(self._selected, COMFYUI_OUTPUT_DIR)
        if preview is None or preview[1] != "video":
            return None
        return preview[0]

    def _on_send_to_evolver(self):
        """Copy the selected video into Evolver's inbox and remember the send.

        Re-checks the persisted flag (not just the button's disabled state) so
        the handoff can't be repeated, mirroring how _on_reuse re-gates. The copy
        lands in another app's inbox with no other visible result here, so a
        failure must surface loudly; success is remembered on the button.
        """
        if not self._selected or self._selected.get("evolver_exported_at"):
            return
        path = self._exportable_video_path()
        if path is None:
            return
        try:
            evolver_export.export_video(path, EVOLVER_INBOX_DIR / EVOLVER_SOURCE)
        except Exception as e:
            logger.exception("Failed to send %s to Evolver", path)
            QMessageBox.warning(
                self, "Send to Evolver failed",
                f"Could not send this video to Evolver:\n\n{e}",
            )
            return
        prompt_id = self._selected["prompt_id"]
        self._db.mark_evolver_exported(prompt_id)
        # Re-read so the row (and thus the button) reflects the persisted send.
        self._selected = self._db.get_generation(prompt_id) or self._selected
        self._update_evolver_button((path, "video"))

    def _on_reuse(self):
        # Gate on reusability here, not just via the button's enabled state, so
        # the double-click path is inert for a workflow the app can't rebuild.
        if not self._selected or not _is_reusable_workflow(
            self._selected.get("workflow_name")
        ):
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


def _inflight_signature(items) -> tuple:
    """The identity of the in-flight set — its job keys — so a frame-only change
    refreshes cards in place while an added or removed job forces a re-render."""
    return tuple(sorted(it.key for it in items))
