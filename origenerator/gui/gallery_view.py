import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QPushButton, QToolButton, QSplitter,
    QMenu, QInputDialog, QAbstractItemView, QMessageBox, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, QTimer, QPoint, QSize, pyqtSignal

from origenerator import gallery, timing
from origenerator.gui import icons
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import COMFYUI_OUTPUT_DIR, STATE_DIR, THUMB_DIR
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import (
    ConfigSnapshot, find_duplicate_generation, randomize_seeds,
)
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tile import FolderTile
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.metadata_panel import MetadataPanel
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.reroll_prompt import offer_reroll
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.thumbnail_widget import ThumbnailWidget
from origenerator.gui.inflight_card import InFlightCard, InFlightItem
from origenerator.gui.info_pane import InfoPaneController, _is_reusable_workflow
from origenerator.gui.gallery_tree import (
    GalleryTree,
    GROUP_ROLE as _GROUP_ROLE,
    RECENTS_KEY as _RECENTS_KEY,
    RECENTS_LABEL as _RECENTS_LABEL,
    STARRED_KEY as _STARRED_KEY,
    STARRED_LABEL as _STARRED_LABEL,
)
from origenerator.navigation import NavigationHistory
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_TILE_SPACING = 8  # gap between tiles in the flowing main view
_POLL_INTERVAL_MS = 1500
_PREVIEW_COUNT = 4
_RECENTS_LIMIT = 50  # most recent generations the shelf lists at once
_STARRED_TITLE = "★ " + _STARRED_LABEL  # the browser-pane heading for the shelf
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
        self._image_rows: list[dict] = []
        self._recent_rows: list[dict] = []  # recently generated rows, newest first
        self._inflight_cards: dict[str, InFlightCard] = {}  # live in-flight cards, by job key
        self._inflight_by_key: dict[str, InFlightItem] = {}  # their items, for click routing
        self._inflight_signature: tuple = ()  # the in-flight set now drawn on the shelf
        self._starred_groups: list = []  # folders the shelf collects, in tree order
        self._visible_ids: list[str] = []
        self._visible_keys: list[str] = []
        self._selected_ids: set[str] = set()
        self._selection_anchor: str | None = None
        self._shelf_selection: dict[str, str] = {}  # last item previewed on each shelf
        self._thumb_widgets: dict[str, ThumbnailWidget] = {}
        self._fingerprint = None
        self._pending_key: str | None = None  # a folder to open once the tree exists
        self._pending_selection: str | None = None  # a generation to highlight once shown
        # A combine's brand-new folder doesn't exist until its job finishes; hold
        # its key so _on_reroll_finished can drill in once the tree has the folder.
        self._pending_combine_key: str | None = None
        self._editing_key: str | None = None  # folder being renamed inline
        self._history = NavigationHistory()  # back/forward across viewed locations
        self._suppress_history = False  # true while a rebuild or Back/Forward re-selects
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
        self._tree_view = GalleryTree(self._tree)  # builds it + the key/prompt→item maps
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
        info_box.addWidget(self._meta_panel, 2)
        self._animated_strip = AnimatedVideoStrip()
        info_box.addWidget(self._animated_strip)
        self._reuse_btn = QPushButton("Reuse Parameters")
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
        self._evolver_btn.hide()
        info_box.addWidget(self._evolver_btn)
        self._panes.addWidget(info)
        # The controller drives the pane's widgets from the generation on display;
        # an i2v source link or an animation click surfaces here as a source link,
        # and Reuse re-emits as this view's reuse_requested.
        self._info = InfoPaneController(
            self._db,
            preview=self._preview, meta_panel=self._meta_panel, meta_title=self._meta_title,
            estimate_label=self._estimate_label, animated_strip=self._animated_strip,
            reuse_btn=self._reuse_btn, reuse_wrap=self._reuse_wrap, evolver_btn=self._evolver_btn,
            parent=self,
        )
        self._info.link_activated.connect(self._on_source_link)
        self._info.reuse_requested.connect(self.reuse_requested)

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
        expanded = self._tree_view.expanded_keys()
        # Pending restore targets stand in until the user makes a live choice.
        selected_key = self._tree_view.selected_folder_key() or self._pending_key
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
        self._tree_view.populate(tree_model, expanded,
                                 show_recents=bool(tree_model or self._inflight_items()))
        self._clear_metadata()
        target = self._item_by_key.get(selected_key) or self._tree_view.default_item()
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
                self._info.reset_animated_strip()  # nothing selected: no animations
            self._restore_reroll_selection(reroll_key, reroll_frame)
        finally:
            self._suppress_history = False
        # Seed history once with wherever the gallery first lands — a generation or
        # a shelf — so Back works even if the user's very first move leaves it.
        if self._history.current() is None:
            location = self._current_location()
            if location is not None:
                self._record_visit(location)

    def _reselect_generation(self, prompt_id: str | None):
        """Re-highlight a generation after a rebuild, if it's still on screen."""
        if prompt_id and prompt_id in self._visible_ids:
            self._on_thumbnail_clicked(prompt_id)

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
        self._title.set_display(self._tree_view.breadcrumb(current))
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
        self._record_location(_RECENTS_KEY)  # so Back can return to the shelf

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
        self._record_location(_STARRED_KEY)  # so Back can return to the shelf

    def _show_starred_tiles(self, groups):
        container, flow = self._new_tile_pane()
        for group in groups:
            item = self._item_by_key.get(group.key)
            context = self._tree_view.breadcrumb(item.parent()) if item and item.parent() else ""
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

    @property
    def _selected(self) -> dict | None:
        """The saved generation on display in the info pane, or ``None``. Owned by
        the info-pane controller; read here for navigation, delete, and the
        Recents "containing folder" jump."""
        return self._info.current_row()

    # The folder tree's key→item / prompt→item maps and shelf rows are owned by the
    # GalleryTree renderer; surfaced here for navigation, selection, and rebuild.
    @property
    def _item_by_key(self) -> dict:
        return self._tree_view.item_by_key

    @property
    def _leaf_by_id(self) -> dict:
        return self._tree_view.leaf_by_id

    @property
    def _recents_item(self):
        return self._tree_view.recents_item

    @property
    def _starred_item(self):
        return self._tree_view.starred_item

    def _selected_folder_key(self) -> str | None:
        """The selected folder's key (or a shelf's), from the tree renderer."""
        return self._tree_view.selected_folder_key()

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

    # --- combine: a video's recipe applied to a dropped image -------------

    def _generate_combination(self, image_id: str, video_id: str):
        """Generate a new video from a dropped image + a dropped video's recipe.

        Reuses the video's workflow, settings and seed, swapping only the input
        image to the dropped one, and lands the result in the folder for that
        (image × settings) combination. A pinned seed can reproduce an identical
        past run, so this warns first via the shared "already generated" dialog,
        offering a fresh seed — exactly as the Generate tab does. A no-op if either
        row is gone, the video isn't a rebuildable image-conditioned recipe, the
        image has no output file, or that folder is already generating.
        """
        image_row = self._db.get_generation(image_id)
        video_row = self._db.get_generation(video_id)
        if not image_row or not video_row:
            return
        workflow_name = video_row.get("workflow_name") or ""
        workflow = WORKFLOW_REGISTRY.get(workflow_name)
        if workflow is None or not gallery.is_image_conditioned(workflow_name):
            return  # the video must be a rebuildable, image-conditioned recipe
        params = gallery.combined_params(video_row, image_row, workflow)
        if params is None:
            return  # the dropped image has no output file to seed from
        snapshot = ConfigSnapshot(workflow.name, params, seed_is_random=False)
        if find_duplicate_generation(self._db.list_generations(), snapshot):
            if not offer_reroll(self, workflow):
                return  # let the user pick a different pair rather than duplicate
            params = randomize_seeds(params, workflow.seed_keys())
        key = gallery.settings_folder_key(
            {**dict(video_row), "params_json": json.dumps(params)},
            gallery.build_image_config_index(self._image_rows),
        )
        if self._reroll.start_prepared(key, workflow, params):
            self._reveal_combination(key)

    def _reveal_combination(self, key: str):
        """Show a just-launched combine. If its (image × settings) folder already
        exists, open it and mirror the live tile; otherwise it's a brand-new
        combination with no folder yet, so park on Recents — where its in-flight
        card shows — and remember the key for :meth:`_on_reroll_finished` to drill
        into once the finished row gives the folder a node."""
        item = self._item_by_key.get(key)
        if item is not None:
            self._tree.setCurrentItem(item)  # existing folder: watch the live tile
            self._select_reroll(key)
        elif self._recents_item is not None:
            self._pending_combine_key = key
            self._tree.setCurrentItem(self._recents_item)

    # --- re-roll as the info-pane source ----------------------------------

    def _select_reroll(self, key: str):
        """Make a running re-roll's tile the selected item and mirror its live
        frames into the info pane.

        The tile stands for an in-flight job with no saved file yet, so its
        preview comes from the job's streamed frames rather than the info pane's
        on-disk lookup.
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
        if key is None or key not in self._reroll_jobs or self._tree_view.selected_folder_key() != key:
            return
        self._last_reroll_frame = frame
        self._enter_reroll_selection(key)

    def _enter_reroll_selection(self, key: str):
        """Point the info pane at re-roll ``key`` and show its last frame — or a
        'waiting' note, never the idle 'select a generation' placeholder."""
        self._selected_reroll_key = key
        self._clear_thumbnail_selection()
        if self._reroll_tile is not None:
            self._reroll_tile.set_selected(True)
        self._info.show_generating(self._last_reroll_frame)

    def _on_reroll_preview(self, key: str, data: bytes):
        """Mirror a re-roll's live frame into the info pane while it's selected,
        remembering it so it survives the rebuild each stage completion triggers."""
        if key == self._selected_reroll_key:
            self._last_reroll_frame = data
            self._info.show_frame(data)

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
        # A combine whose brand-new folder we parked off (on Recents) now has a
        # finished row, so the rebuild above gave that folder a node: drill in.
        if key == self._pending_combine_key:
            self._pending_combine_key = None
            item = self._item_by_key.get(key)
            if item is not None:
                self._tree.setCurrentItem(item)

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
        return self._tree_view.selected_folder_key() or self._pending_key

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
        key = self._tree_view.selected_folder_key()
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
        self._info.show_generation(row, self._image_rows)
        self._sync_containing_folder_button()  # a Recents preview offers the jump
        shelf_key = self._current_shelf_key()
        if shelf_key is not None:
            # Previewing an item on a shelf is shelf state, not a navigation: it's
            # remembered so Back can restore it, but the shelf stays the one history
            # stop (stepping through each preview would bury where you came from).
            self._shelf_selection[shelf_key] = prompt_id
        else:
            # In a folder, each viewed generation — a click, the auto-selected first
            # item, a followed link — is its own browsing step.
            self._record_location(prompt_id)

    def _animated_preview(self, row: dict) -> str | None:
        """The looping-WebP preview for a video ``row`` — ``None`` for an image or a
        video whose file is gone or unreadable, so the tile shows its still instead.
        Feeds the grid tiles and the Recents shelf (the info pane's 'Animated in'
        strip resolves the same path through :func:`gallery.animated_preview_path`)."""
        return gallery.animated_preview_path(row, COMFYUI_OUTPUT_DIR, THUMB_DIR)

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

    def _current_shelf_key(self) -> str | None:
        """The key of the shelf on screen (Recents/Starred), or ``None`` off them."""
        key = self._selected_folder_key()
        return key if key in (_RECENTS_KEY, _STARRED_KEY) else None

    def _current_location(self) -> str | None:
        """The history key for the view on screen — a shelf key on a shelf, else the
        selected generation's id (``None`` when nothing is selected)."""
        return self._current_shelf_key() or (
            self._selected["prompt_id"] if self._selected else None
        )

    def _record_location(self, location: str):
        """Record a visit to a location — a generation id or a shelf key — unless a
        rebuild or Back/Forward is re-showing it (those move within history, not
        onto it)."""
        if not self._suppress_history:
            self._record_visit(location)

    def _record_visit(self, location: str):
        self._history.visit(location)
        self._sync_nav_buttons()

    def _go_back(self):
        location = self._history.back()
        if location is not None:
            self._restore_location(location)
        self._sync_nav_buttons()

    def _go_forward(self):
        location = self._history.forward()
        if location is not None:
            self._restore_location(location)
        self._sync_nav_buttons()

    def _restore_location(self, location: str):
        """Re-show a history location without recording the move — a shelf overview
        (Recents/Starred) or a generation in its folder."""
        if location in (_RECENTS_KEY, _STARRED_KEY):
            self._return_to_shelf(location)
        else:
            self._show_generation(location)

    def _return_to_shelf(self, key: str):
        """Back/Forward onto a shelf: show it and restore the item that was selected
        there, all without recording (so the move doesn't pile back onto history)."""
        item = self._item_by_key.get(key)
        if item is None:
            return
        self._suppress_history = True
        try:
            self._tree.setCurrentItem(item)  # shows the shelf, cleared of any selection
            self._restore_shelf_selection(key)
        finally:
            self._suppress_history = False

    def _restore_shelf_selection(self, key: str):
        """Re-preview the item last selected on this shelf, if it's still listed —
        so returning to a shelf lands on it, not on a blank shelf."""
        prompt_id = self._shelf_selection.get(key)
        if prompt_id is not None and prompt_id in self._visible_ids:
            self._apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
            self._on_thumbnail_clicked(prompt_id)

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
        self._info.clear()
        self._sync_containing_folder_button()  # nothing selected: no jump to offer

    def _on_send_to_evolver(self):
        self._info._on_send_to_evolver()

    def _on_reuse(self):
        self._info._on_reuse()


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
