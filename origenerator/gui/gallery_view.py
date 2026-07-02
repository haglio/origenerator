import json
import logging

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
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.combine_panel import CombinePanel
from origenerator.gui.metadata_panel import MetadataPanel
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.reroll_prompt import offer_reroll
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.info_pane import InfoPaneController, _is_reusable_workflow
from origenerator.gui.info_pane_tabs import InfoPaneTabs
from origenerator.gui.browser_pane import BrowserPane
from origenerator.gui.gallery_tree import (
    GalleryTree,
    GROUP_ROLE as _GROUP_ROLE,
    RECENTS_KEY as _RECENTS_KEY,
    STARRED_KEY as _STARRED_KEY,
)
from origenerator.navigation import NavigationHistory
from origenerator.trash import Trash
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 1500
_RECENTS_LIMIT = 50  # most recent generations the shelf lists at once
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
                 actions: GalleryActions | None = None):
        super().__init__(parent)
        self._db = db
        self._client = client
        # The info pane's config tabs are the source of in-flight Generate work and
        # the ids the re-roll reconnection must not re-adopt; wired in _build_ui once
        # the tabs exist. Default to empty until then.
        self._claimed_ids = lambda: set()
        self._generate_inflight = lambda: []
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
        # The browser pane renders the middle column (tiles / thumbnails / shelves)
        # and owns the thumbnail multi-selection and in-flight cards.
        self._browser = BrowserPane(self)
        self._shelf_selection: dict[str, str] = {}  # last item previewed on each shelf
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

        Only while the view is on screen, no dialog/menu is up, the focus isn't in
        a text field (so renaming and any editor keep their keys), and the focus
        isn't inside the info-pane config tabs — a config form's combos and buttons
        aren't text fields, so editing one must not let Delete wipe a thumbnail.
        """
        if not self.isVisible():
            return False
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return False
        focus = QApplication.focusWidget()
        if focus is not None and self._info_tabs.isAncestorOf(focus):
            return False  # editing a config in the info pane — its keys, not ours
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
        toc_box.addWidget(self._tree, 1)  # the tree takes the height; combine sits below
        # Combine: drop an image + an i2v video, Generate re-runs that video's recipe
        # on the image. Needs a client to generate, so it hides without one.
        self._combine = CombinePanel(
            self._combine_accepts_image, self._combine_accepts_video, self._combine_preview
        )
        self._combine.generate_requested.connect(self._generate_combination)
        self._combine.setVisible(self._client is not None)
        toc_box.addWidget(self._combine)
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
        self._containing_folder_btn.clicked.connect(self._browser.go_to_containing_folder)
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
        # The info pane is a tab widget: this Inspect page is tab 0 — always
        # present, not closable — and editable config tabs (Reuse Parameters or the
        # "+") open after it, sharing one run queue.
        self._info_tabs = InfoPaneTabs(self._client, self._db, info)
        self._panes.addWidget(self._info_tabs)
        # The config tabs feed the Recents shelf its in-flight Generate cards, and
        # name the running ids the re-roll reconnection must not re-adopt.
        self._generate_inflight = self._info_tabs.in_flight_items
        self._claimed_ids = self._info_tabs.active_prompt_ids
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
        # Reuse Parameters opens an editable config tab in this same pane (a no-op
        # without a client — nothing could run it).
        self.reuse_requested.connect(self._info_tabs.open_config)

        # The TOC pane holds its width; the browser and info panes both grow with
        # the window (the browser faster), so the info pane stays comfortably wide
        # instead of a thin strip on a large screen. Long metadata values wrap
        # rather than scroll sideways, so these floors only need to keep the panes
        # readable — kept low enough that the window can still tile into a monitor
        # third or a portrait-monitor half.
        toc.setMinimumWidth(120)
        browser.setMinimumWidth(210)
        self._info_tabs.setMinimumWidth(300)
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
        elif self._browser.showing_recents():
            # No DB change, but in-flight cards still need their live frames pushed
            # and a re-render when a locally-queued Generate tab appears/vanishes
            # (it carries no DB row to move the fingerprint).
            self._browser.refresh_inflight()

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
        self._browser.set_model(
            gallery.recent_generations(rows, _RECENTS_LIMIT), gallery.starred_folders(tree_model)
        )
        self._tree_view.populate(tree_model, expanded,
                                 show_recents=bool(tree_model or self._browser._inflight_items()))
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
                self._browser.show_widget(QWidget())
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
        if prompt_id and prompt_id in self._browser.visible_prompt_ids():
            self._on_thumbnail_clicked(prompt_id)

    def _on_folder_selected(self, current, _previous):
        if current is None:
            self._title.set_display("")
            self._avg_label.setText("")
            self._browser.show_empty()
            self._sync_delete_button()
            return
        if current is self._recents_item:
            self._browser.show_recents_overview()
            return
        if current is self._starred_item:
            self._browser.show_starred_overview()
            return
        group = current.data(0, _GROUP_ROLE)
        self._title.set_display(self._tree_view.breadcrumb(current))
        self._update_folder_average(group)
        if isinstance(group, gallery.SettingsGroup):
            self._browser.show_thumbnails(group)
        else:
            self._browser.show_folder_tiles(gallery.child_groups(group))
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

    # --- the Recents shelf: in-flight work, then recently finished items ----

    # --- the Starred shelf: every bookmarked folder, gathered in one place ---

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

    def _combine_accepts_image(self, prompt_id: str) -> bool:
        """Whether the image slot accepts a dropped generation: an image with a
        file to seed an i2v from (not merely anything that produced a file — a
        video's clip would satisfy that and can't be a start frame)."""
        row = self._db.get_generation(prompt_id)
        return bool(
            row and gallery.media_type_of_row(row) == "image"
            and gallery.output_file_reference(gallery.row_output_files(row)) is not None
        )

    def _combine_accepts_video(self, prompt_id: str) -> bool:
        """Whether the video slot accepts a dropped generation: a video whose i2v
        recipe the app can rebuild — so its settings can be re-run on a new image.
        (``is_image_conditioned`` already implies the workflow is registered.)"""
        row = self._db.get_generation(prompt_id)
        return bool(
            row and gallery.media_type_of_row(row) == "video"
            and gallery.is_image_conditioned(row.get("workflow_name") or "")
        )

    def _combine_preview(self, prompt_id: str) -> tuple[str | None, str | None]:
        """A dropped item's (thumbnail, looping-preview) paths for its slot: a video
        loops its clip, an image shows its still. Either may be ``None`` when absent."""
        row = self._db.get_generation(prompt_id)
        if row is None:
            return (None, None)
        return (row.get("thumbnail_path"), self._animated_preview(row))

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
        self._browser.clear_thumbnail_selection()
        if self._reroll_tile is not None:
            self._reroll_tile.set_selected(True)
        self._info.show_generating(self._last_reroll_frame)

    def _on_reroll_preview(self, key: str, data: bytes):
        """Mirror a re-roll's live frame into the info pane while it's selected,
        remembering it so it survives the rebuild each stage completion triggers."""
        if key == self._selected_reroll_key:
            self._last_reroll_frame = data
            self._info.show_frame(data)

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
            self._browser.show_thumbnails(group)

    def visible_prompt_ids(self) -> list[str]:
        return self._browser.visible_prompt_ids()

    def visible_folder_keys(self) -> list[str]:
        return self._browser.visible_folder_keys()

    # --- browser-pane facade (the shelves/inflight the view drives into it) -

    @property
    def _inflight_cards(self) -> dict:
        return self._browser._inflight_cards

    def _showing_recents(self) -> bool:
        return self._browser.showing_recents()

    def _drill_into(self, key: str):
        self._browser._drill_into(key)

    def _thumbnail_double_clicked(self, prompt_id: str):
        self._browser._thumbnail_double_clicked(prompt_id)

    def _on_inflight_clicked(self, key: str):
        self._browser._on_inflight_clicked(key)

    def _inflight_items(self) -> list:
        return self._browser._inflight_items()

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

    def capture_config_tabs(self) -> dict:
        """Snapshot the open editable config tabs (and which is active), for the
        session. Delegates to the info pane's tab strip."""
        return self._info_tabs.capture_state()

    def restore_config_tabs(self, state):
        """Reopen the config tabs saved from a previous session, reconnecting any
        whose job is still running — done before :meth:`reconnect_running_rerolls`
        so a tab reclaims its own job before the gallery adopts the rest."""
        self._info_tabs.restore_state(state)

    # --- selection ---------------------------------------------------------

    def _thumbnail_clicked(self, prompt_id: str):
        self._browser._thumbnail_clicked(prompt_id)

    def _apply_selection(self, prompt_id: str, modifiers):
        self._browser.apply_selection(prompt_id, modifiers)

    def selected_prompt_ids(self) -> list[str]:
        return self._browser.selected_prompt_ids()

    @property
    def _thumb_widgets(self) -> dict:
        """The on-screen thumbnail widgets, owned by the browser pane."""
        return self._browser._thumb_widgets

    # --- deletion & undo ---------------------------------------------------

    def _thumbnail_context_menu(self, prompt_id: str, global_pos):
        self._browser._thumbnail_context_menu(prompt_id, global_pos)

    def _delete_selection(self):
        """Delete picked thumbnails, or the current folder if none are picked."""
        if self._browser.selected_ids:
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
        self._browser.clear_selection()
        self.refresh()
        self._sync_undo_button()

    def _undo(self):
        if not self._actions.can_undo():
            return
        self._preview.clear()
        focus = self._actions.undo()  # a restored generation to return to, if any
        self._browser.clear_selection()
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
        self._browser.sync_containing_folder_button()  # a Recents preview offers the jump
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
        if prompt_id is not None and prompt_id in self._browser.visible_prompt_ids():
            self._apply_selection(prompt_id, Qt.KeyboardModifier.NoModifier)
            self._on_thumbnail_clicked(prompt_id)

    def _sync_nav_buttons(self):
        self._back_btn.setEnabled(self._history.can_go_back())
        self._forward_btn.setEnabled(self._history.can_go_forward())

    def _sync_delete_button(self):
        """Enable Delete when there's a target — picked thumbnails, else the
        current deletable folder — and say which in its tooltip."""
        count = len(self._browser.selected_ids)
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
        self._browser.sync_containing_folder_button()  # nothing selected: no jump to offer

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
