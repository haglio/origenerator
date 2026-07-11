import json
import logging

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QPushButton, QToolButton, QSplitter,
    QMenu, QInputDialog, QAbstractItemView, QMessageBox, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, QTimer, QPoint, QSize, pyqtSignal

from origenerator import gallery, recipe_match, timing
from origenerator.gui import icons
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import (
    COMFYUI_OUTPUT_DIR, STATE_DIR, THUMB_DIR,
    LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL, VIDEO_SCENE_MATCH_SYSTEM_PROMPT,
)
from origenerator.db import Database
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import (
    ConfigSnapshot, filled_params, find_duplicate_generation, merge_denormalized,
    randomize_seeds,
)
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.combine_panel import CombinePanel
from origenerator.gui.auto_generate_controller import AutoGenerateController
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.voice.steering import VoiceSteering
from origenerator.gui.reroll_prompt import (
    REROLL_BOTH, REROLL_IMAGE, REROLL_VIDEO, offer_reroll,
)
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.info_pane_tabs import InfoPaneTabs
from origenerator.gui.osr2_driver import Osr2Driver
from origenerator.gui.running_job_bar import RunningJobBar
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


def _is_reusable_workflow(workflow_name) -> bool:
    """Whether the app can rebuild this workflow from its template.

    The single gate for both Reuse Parameters and the gallery re-roll, so the
    re-roll '+' appears exactly where Reuse works (a re-roll is just Reuse with a
    random seed).
    """
    return (workflow_name or "") in WORKFLOW_REGISTRY


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
        # The re-roll controller owns the live jobs and their DB lifecycle; the
        # view reacts to its signals with the redraws they call for.
        self._reroll = RerollController(db, client)
        self._reroll.changed.connect(self._rerender_current_leaf)
        self._reroll.changed.connect(self._reconcile_generating)
        self._reroll.preview.connect(self._on_reroll_preview)
        self._reroll.finished.connect(self._on_reroll_finished)
        self._reroll.failed.connect(self._on_reroll_failed)
        # "Repeatedly generate in a folder" is that same re-roll on a loop: launch
        # the next variation each time one finishes, until stopped or one fails.
        self._auto = AutoGenerateController(self._start_reroll)
        self._auto.stopped.connect(self._on_auto_stopped)
        # Auto-generate holds a mutable copy of a folder's params per active loop so
        # voice can steer the prompt mid-loop; turning Auto on is voice's "on" and
        # begins always-listening steering of the current folder.
        self._auto_working: dict = {}
        self._pending_auto_key: str | None = None  # a re-homed loop's folder to open once it exists
        self._voice = VoiceSteering()
        self._voice.error.connect(lambda msg: logger.warning("Voice steering: %s", msg))
        self._voice.heard.connect(self._on_voice_heard)
        self._voice.edited.connect(self._on_voice_edited)
        self._voice.error.connect(self._on_voice_error)
        self._voice_target_key: str | None = None
        # A floating caption over the top of the gallery showing what voice heard and
        # did, so it's visible without reading the log. A free child, positioned by
        # hand; transient messages revert to the idle "Listening…" after a moment.
        self._voice_status = QLabel(self)
        self._voice_status.setObjectName("voiceStatus")
        self._voice_status.setStyleSheet(
            "#voiceStatus { color: white; background: rgba(20, 20, 20, 225);"
            " padding: 8px 16px; border-radius: 6px; }"
        )
        self._voice_status.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._voice_status.hide()
        self._voice_status_timer = QTimer(self)
        self._voice_status_timer.setSingleShot(True)
        self._voice_status_timer.timeout.connect(self._voice_status_revert)
        self._slideshow = None  # the fullscreen slideshow window while one is open
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
        self._selected_row: dict | None = None  # the saved generation on display in the info pane
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
        self._folder_history: list[str] = []  # folders the user opened, to return to after a delete
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
        if event.type() == QEvent.Type.KeyPress:
            # Esc is a panic-stop, handled from anywhere — not gated on gallery key
            # focus. The driven video usually sits in the focused info-pane tab, so
            # Esc has to reach the device (and any auto loop) from there too.
            if event.key() == Qt.Key.Key_Escape and self._handle_escape():
                return True
            if self._gallery_owns_keys():
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

    def _handle_escape(self) -> bool:
        """Esc stops the physical device and any running loop, wherever focus is: it
        turns off OSR2 driving and ends auto-generate. It yields, though, when
        another window owns the keystroke — an open dialog/popup, so Esc still closes
        a combo dropdown, or an active fullscreen preview/slideshow, which close on
        Esc themselves. Returns whether it acted."""
        if self._other_window_owns_keys():
            return False
        handled = False
        if self._osr2_enabled:
            self._osr2_btn.setChecked(False)  # untoggling stops the driver
            handled = True
        if self._auto.any_active():
            self._auto.stop_all()
            handled = True
        return handled

    def _other_window_owns_keys(self) -> bool:
        """True when a keystroke belongs to something other than the gallery: an open
        modal dialog or popup, or a separate top-level window that's active — a
        fullscreen preview or the slideshow, both of which close on Esc. The
        gallery's filter is installed on the application, so it sees those windows'
        keys first and has to hand them back."""
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return True
        active = QApplication.activeWindow()
        return active is not None and active is not self.window()

    def _gallery_owns_keys(self) -> bool:
        """True when a gallery key (Delete/Undo) should act, not pass through.

        Only while the view is on screen, nothing else owns the keystroke (no
        dialog/popup and no other active window), the focus isn't in a text field
        (so renaming and any editor keep their keys), and the focus isn't inside the
        info-pane config tabs — a config form's combos and buttons aren't text
        fields, so editing one must not let Delete wipe a thumbnail.
        """
        if not self.isVisible():
            return False
        if self._other_window_owns_keys():
            return False
        focus = QApplication.focusWidget()
        if focus is not None and self._info_tabs.isAncestorOf(focus):
            return False  # editing a config in the info pane — its keys, not ours
        return not isinstance(
            focus, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)
        )

    def _build_ui(self):
        layout = QVBoxLayout(self)

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
        # A filter over the tree: type a folder name (prompt / model / LoRA /
        # workflow) to narrow it to matching branches, or a seed to jump straight
        # to that one generation. Sits above the tree so it reads as its search box.
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Filter…")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.textChanged.connect(self._on_filter_changed)
        toc_box.addWidget(self._filter_edit)
        toc_box.addWidget(self._tree, 1)  # the tree takes the height; combine sits below
        # Combine: drop an image + an i2v video, Generate re-runs that video's recipe
        # on the image. Needs a client to generate, so it hides without one.
        self._combine = CombinePanel(
            self._combine_accepts_image, self._combine_accepts_video, self._combine_preview
        )
        self._combine.generate_requested.connect(self._generate_combination)
        self._combine.category_requested.connect(self._generate_category)
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
        self._slideshow_btn = self._tool_button(
            icons.slideshow_icon(), "Play this folder as a slideshow", self._start_slideshow
        )
        self._slideshow_btn.hide()  # shown only while a folder with media is open
        self._auto_btn = self._tool_button(
            icons.autoloop_icon(), "Auto-generate variations of this folder",
            self._toggle_auto, checkable=True,
        )
        self._auto_btn.setStyleSheet(  # a lit background while auto-generate is running
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        self._auto_btn.hide()  # shown only while a re-rollable settings folder is open
        # A single global switch: while it's on, whatever scripted video is in the
        # front tab drives the OSR2. Always visible (it's app-wide), lit when on.
        self._osr2_btn = self._tool_button(
            icons.osr2_icon(),
            "Drive the OSR2 from the video open in the generate tab (Esc to stop)",
            self._on_osr2_toggle, checkable=True,
        )
        self._osr2_btn.setStyleSheet(
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        self._delete_btn = self._tool_button(icons.delete_icon(), "Delete", self._delete_selection)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)
        for button in (self._back_btn, self._forward_btn, self._undo_btn,
                       self._slideshow_btn, self._auto_btn, self._osr2_btn, self._delete_btn):
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

        # Info pane: a tabbed workspace of identical editable generate panels
        # (form + Generate). No special or permanent tab — the first opens on
        # construction, and more fork via the "+" or a thumbnail double-click, all
        # sharing one run queue. Clicking a browser thumbnail loads that generation
        # into a tab (its output in the preview, its settings in the form, a footer
        # for its media type). Each panel's source-image link and animation clicks
        # surface here as a source link the view follows.
        self._info_tabs = InfoPaneTabs(self._client, self._db)
        # One OSR2 driver for the whole view. It follows whichever video is foreground:
        # an open fullscreen view (which drives regardless of the toggle — watching a
        # clip IS the intent to feel it), else — only while the global toggle
        # (self._osr2_btn) is on — whatever scripted video is in the front tab.
        # Switching tabs/videos or opening/closing the fullscreen view re-aims it; with
        # nothing to drive it stops. self._osr2_driving is the (video, player) currently
        # driven, so a redundant reconcile doesn't churn the device. Built before the
        # panels are wired, since wiring connects their displayed_changed and
        # fullscreen_opened here.
        self._osr2_driver = Osr2Driver(parent=self)
        self._osr2_enabled = False
        self._osr2_driving = None
        self._fullscreen_preview = None  # the open fullscreen view, top drive priority
        self._info_tabs.tab_added.connect(self._wire_config_panel)
        for panel in self._info_tabs._config_panels():
            self._wire_config_panel(panel)  # the initial tab predates the connection
        self._info_tabs.currentChanged.connect(self._on_front_tab_changed)
        # Quitting mid-drive still releases the device — park it and restore genau —
        # so a closed app doesn't leave the OSR2 held and genau silently disabled.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._osr2_driver.stop)
        # A tab's Generate is a re-roll of its settings folder: launch it in that
        # folder's own re-roll slot and navigate there, live tile and all.
        self._info_tabs.generate_requested.connect(self._on_generate_requested)
        self._panes.addWidget(self._info_tabs)
        # A thumbnail double-click reuses its parameters by forking an editable
        # config tab in this same pane (a no-op without a client — nothing to run);
        # the fork's footer links are wired via tab_added like every other tab.
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

        layout.addWidget(self._panes, 1)
        # A slim bar under the panes shows the one job currently in flight (ComfyUI
        # runs them one at a time), reachable from any folder or config tab. Hidden
        # until something runs; fed on every rebuild and poll.
        self._running_bar = RunningJobBar()
        layout.addWidget(self._running_bar)

    def _tool_button(self, icon, tooltip: str, handler, *, checkable=False) -> QToolButton:
        """A compact, icon-only toolbar button for the browser-pane header. A
        ``checkable`` one is a toggle whose ``handler`` receives its on/off state."""
        btn = QToolButton()
        btn.setObjectName("iconButton")
        btn.setIcon(icon)
        btn.setIconSize(QSize(16, 16))
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        (btn.toggled if checkable else btn.clicked).connect(handler)
        return btn

    def _wire_config_panel(self, panel):
        """Route a config tab's footer links to the gallery: its "from source
        image" link and an animation-tile click both navigate like any source link.
        Its ``displayed_changed`` re-aims the global OSR2 drive at the front video,
        its ``fullscreen_opened`` hands the drive to a video popped open fullscreen,
        and its Cancel stops the re-roll running in the tab's folder. Called for the
        initial tab and every tab forked afterward."""
        panel.source_activated.connect(self._on_source_link)
        panel.animated_activated.connect(self._on_source_link)
        panel.containing_folder_requested.connect(self._browser.open_in_containing_folder)
        panel.displayed_changed.connect(self._reconcile_osr2)
        panel.fullscreen_opened.connect(self._on_fullscreen_opened)
        panel.cancel_requested.connect(lambda p=panel: self._cancel_panel_reroll(p))

    # --- Drive OSR2: a single global toggle following the front video ----------

    def _on_osr2_toggle(self, on: bool):
        self._osr2_enabled = on
        self._reconcile_osr2()

    def _reconcile_osr2(self):
        """Point the one driver at whichever video is foreground.

        Idempotent: it (re)starts only when the driven ``(video, player)`` actually
        changes and stops when nothing should drive — so tab switches, browsing,
        completions, and opening or closing the fullscreen view all resolve to the
        right video without churning the device."""
        target = self._osr2_drive_source()
        if target is None:
            if self._osr2_driving is not None:
                self._osr2_driver.stop()
                self._osr2_driving = None
            return
        video_path, player, actions = target
        driving = (video_path, player)  # same clip, new player (fullscreen) still re-aims
        if self._osr2_driving != driving:
            self._osr2_driver.start(player, actions)
            self._osr2_driving = driving

    def _osr2_drive_source(self):
        """The drive target the device should follow, or ``None``. A fullscreen view
        wins when it's showing a scripted video (it drives regardless of the toggle);
        otherwise the front tab's video, but only while the toggle is on."""
        fullscreen = self._fullscreen_preview
        if fullscreen is not None:
            target = fullscreen.osr2_drive_target()
            if target is not None:
                return target
        panel = self._info_tabs.current_config_panel()
        if self._osr2_enabled and panel is not None:
            return panel.osr2_drive_target()
        return None

    def _on_fullscreen_opened(self, fullscreen):
        """A double-click popped a video open fullscreen. It drives the OSR2 for its
        lifetime — regardless of the global toggle — then hands the device back when it
        closes. (An image or unscripted video simply has no target, so nothing drives
        and the toggle's video, if any, keeps going.)"""
        self._fullscreen_preview = fullscreen
        fullscreen.closed.connect(lambda: self._on_fullscreen_closed(fullscreen))
        self._reconcile_osr2()

    def _on_fullscreen_closed(self, fullscreen):
        """The fullscreen view closed: drop it and re-aim at the toggle's video, or
        stop. Guarded so a superseded view's late close can't clear a newer one."""
        if self._fullscreen_preview is fullscreen:
            self._fullscreen_preview = None
            self._reconcile_osr2()

    def _on_front_tab_changed(self, _index):
        """The front config tab changed: re-aim the OSR2 drive at its video, and
        re-evaluate whether that tab's folder is generating (its Cancel button)."""
        self._reconcile_osr2()
        self._reconcile_generating()

    def osr2_enabled(self) -> bool:
        """Whether the global OSR2 toggle is on (for session persistence)."""
        return self._osr2_enabled

    def set_osr2_enabled(self, enabled):
        """Restore the global OSR2 toggle from a saved session."""
        self._osr2_btn.setChecked(bool(enabled))  # drives _on_osr2_toggle → reconcile

    def _folder_key_for(self, workflow_name: str, params: dict) -> str:
        """The settings-folder key a config lands in — the key the re-roll
        controller tracks its job under, and the tree leaf it groups into. Shared by
        the Generate launch and the front-tab generating/cancel reconcile so a tab
        matches the very job its own Generate started."""
        return gallery.settings_folder_key(
            {"workflow_name": workflow_name, "params_json": json.dumps(params)},
            gallery.build_image_config_index(self._image_rows),
        )

    def _panel_reroll_key(self, panel) -> str:
        """The settings-folder key the config in ``panel`` would run in."""
        config = panel.current_config()
        return self._folder_key_for(config.workflow_name, config.params)

    def _reconcile_generating(self):
        """Show the front config tab's Cancel button while a re-roll of its settings
        folder is in flight, so the run it launched (or any re-roll of that folder)
        can be stopped from the tab, not only the folder's tile. Idempotent — driven
        by every re-roll lifecycle change and by switching the front tab."""
        panel = self._info_tabs.current_config_panel()
        if panel is not None:
            panel.set_generating(self._panel_reroll_key(panel) in self._reroll_jobs)

    def _cancel_panel_reroll(self, panel):
        """Cancel the re-roll running in ``panel``'s settings folder — the tab's
        Cancel button, the same stop the folder's re-roll tile performs."""
        key = self._panel_reroll_key(panel)
        if key in self._reroll_jobs:
            self._cancel_reroll(key)

    def _would_reproduce_a_completed_run(self, workflow, params: dict) -> bool:
        """True when launching ``workflow`` with ``params`` would re-create a
        byte-identical past generation — the cue to warn before wasting a slot.

        Callers pass params whose seed is already concrete (the form randomizes a
        Random seed before emitting; a combine reads the stored one), so the seed
        is taken as pinned here; a genuinely random seed would simply never match.
        """
        snapshot = ConfigSnapshot(workflow.name, params, seed_is_random=False)
        return find_duplicate_generation(self._db.list_generations(), snapshot) is not None

    def _on_generate_requested(self, workflow_name: str, params: dict):
        """A tab's Generate: launch it as a re-roll of its settings folder and land
        the browser there, its live tile showing the run.

        Identical in outcome to clicking the folder's re-roll "+": the job runs in
        that folder's single re-roll slot (its :class:`RerollTile` shows the live
        frame), so an edited config's brand-new folder appears and is navigated to
        at once — the running row it inserts gives the folder a tree node
        immediately (see :func:`build_gallery_tree`). Missing form params are filled
        from the workflow's defaults, exactly as the old Generate did. A no-op
        without a client, an unknown workflow, or a folder already generating.
        """
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        if self._client is None or wf is None:
            return
        params = {**wf.default_params(), **params}  # form values win over defaults
        key = self._folder_key_for(workflow_name, params)
        # A pinned seed that would reproduce a past run gets the shared "already
        # generated" dialog rather than silently launching a copy — the guard the
        # re-roll "+" and combine paths (see :meth:`_generate_combination`) use too.
        # Declining launches nothing; accepting re-rolls the seed into a fresh
        # variation and switches the front tab to a Random seed, so the choice
        # sticks — a re-Generate (even after cancelling this one) won't re-ask.
        if self._would_reproduce_a_completed_run(wf, params):
            if offer_reroll(self, wf, can_reroll_image=False) is None:
                return  # let the user change something rather than duplicate it
            params = randomize_seeds(params, wf.seed_keys())
            panel = self._info_tabs.current_config_panel()
            if panel is not None:
                panel.use_random_seed()
        if not self._reroll.start_prepared(key, wf, params):
            return  # no client, or this folder already has a re-roll running
        self._navigate_to_reroll(key)

    def _navigate_to_reroll(self, key: str):
        """Open the folder a just-started re-roll runs in and select its live tile.

        The re-roll inserts a running row, so a rebuild gives even a brand-new
        folder a node (:func:`build_gallery_tree` includes in-flight rows); this
        rebuilds, then drills into that folder and points the info pane at the tile.
        """
        self.refresh()
        item = self._item_by_key.get(key)
        if item is not None:
            self._tree.setCurrentItem(item)
            self._select_reroll(key)

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
            # No DB change, but the in-flight cards still need each running re-roll's
            # live frame pushed in — it advances between rebuilds.
            self._browser.refresh_inflight()
        # The bottom bar is always on screen, so refresh the active job every tick —
        # its live frame and progress advance between rebuilds.
        self._update_running_bar()

    def _rebuild(self, rows, meta):
        expanded = self._tree_view.persisted_expanded_keys()
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
        # An act with no video behind it has no recipe to mine, so grey it out rather
        # than let it be picked only to answer "no recipe yet".
        self._combine.set_available_categories(
            recipe_match.available_categories(self._rebuildable_videos(rows))
        )
        tree_model = gallery.build_gallery_tree(rows, meta)
        self._browser.set_model(
            gallery.recent_generations(rows, _RECENTS_LIMIT), gallery.starred_folders(tree_model)
        )
        self._tree_view.populate(tree_model, expanded,
                                 show_recents=bool(tree_model or self._browser._inflight_items()))
        self._tree_view.reapply_filter()  # populate rebuilds un-filtered; re-narrow it
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
                self._selected_row = None  # nothing selected
            self._restore_reroll_selection(reroll_key, reroll_frame)
        finally:
            self._suppress_history = False
        # Seed history once with wherever the gallery first lands — a generation or
        # a shelf — so Back works even if the user's very first move leaves it.
        if self._history.current() is None:
            location = self._current_location()
            if location is not None:
                self._record_visit(location)
        self._update_running_bar()

    def _reselect_generation(self, prompt_id: str | None):
        """Re-highlight a generation after a rebuild, if it's still on screen."""
        if prompt_id and prompt_id in self._browser.visible_prompt_ids():
            self._on_thumbnail_clicked(prompt_id)

    def _on_filter_changed(self, text: str):
        self._tree_view.apply_filter(text)
        self._focus_seed_match()

    def _focus_seed_match(self):
        """When the filter pinned down exactly one generation by its seed, open its
        folder and select it — the one case where filtering navigates on its own,
        since a seed lives on an item, not a folder the user could click to."""
        matches = self._tree_view.seed_matches
        if sum(len(ids) for ids in matches.values()) != 1:
            return
        (key, prompt_ids), = matches.items()
        item = self._item_by_key.get(key)
        if item is not None:
            self._tree.setCurrentItem(item)  # opens the folder's thumbnails
            self._reselect_generation(prompt_ids[0])

    def _on_folder_selected(self, current, _previous):
        self._sync_auto_button()  # the auto toggle fits only a re-rollable leaf
        self._sync_slideshow_button()  # the slideshow fits any folder holding media
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
        self._note_folder_visit(group.key if group is not None else None)
        self._title.set_display(self._tree_view.breadcrumb(current))
        self._update_folder_average(group)
        if isinstance(group, gallery.SettingsGroup):
            self._browser.show_thumbnails(group)
        else:
            self._browser.show_folder_tiles(gallery.child_groups(group))
        self._sync_delete_button()

    def _note_folder_visit(self, key: str | None):
        """Record a folder the user opened, so a delete can return to the most
        recent one still standing. Skipped while a rebuild or Back/Forward is
        re-selecting (suppressed), and consecutive repeats collapse, so it stays a
        genuine visit trail rather than a poll-driven pile-up."""
        if self._suppress_history or key is None:
            return
        if not self._folder_history or self._folder_history[-1] != key:
            self._folder_history.append(key)

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
        """The saved generation on display in the info pane, or ``None`` — read
        here for navigation, delete, and the Recents "containing folder" jump. Set
        by :meth:`_on_thumbnail_clicked`, cleared when a re-roll or nothing is
        showing."""
        return self._selected_row

    @property
    def _preview(self):
        """The current config tab's preview — where a selection, a re-roll frame,
        or a running generation's frames all land. ``None`` only if every tab has
        been closed."""
        panel = self._info_tabs.current_config_panel()
        return panel._preview if panel is not None else None

    def current_params(self) -> dict | None:
        """The reusable parameters of the generation on display, or ``None`` when
        nothing reusable is shown (idle, a live re-roll, or a workflow the app
        can't rebuild)."""
        if not self._selected_row or not _is_reusable_workflow(self._selected_row.get("workflow_name")):
            return None
        return merge_denormalized(self._selected_row) or None

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

    def _current_group(self):
        """The gallery group of the selected tree item, or ``None`` (a shelf or an
        empty selection)."""
        item = self._tree.currentItem()
        return item.data(0, _GROUP_ROLE) if item else None

    def _add_reroll_tile(self, flow, group):
        tile = RerollTile(self._reroll.job_for(group.key))
        tile.set_selected(group.key == self._selected_reroll_key)
        tile.add_requested.connect(lambda k=group.key: self._start_reroll(k))
        tile.cancel_requested.connect(lambda k=group.key: self._cancel_reroll(k))
        tile.selected.connect(lambda k=group.key: self._select_reroll(k))
        flow.addWidget(tile)
        self._reroll_tile = tile

    def _start_reroll(self, key: str) -> bool:
        """Start a fresh variation for the folder ``key`` names and select it, so
        its live preview fills the info pane at once. Returns whether a variation
        is now running for the folder — the auto-generate loop's cue that a launch
        took hold, and its cue to stop when one can't.

        Skips a folder already re-rolling (or a missing client) without stealing
        the info pane — the same guard the controller enforces before launching.
        """
        if self._client is None:
            return False
        if key in self._reroll_jobs:
            return True  # one is already running for this folder
        working = self._auto_working.get(key)
        if working is not None:
            # A voice-steered auto loop launches its (possibly edited) working prompt
            # with fresh seeds. If the edit moved it to a different settings folder,
            # re-home the loop there and remember to open that folder once it exists.
            target = self._working_folder_key(working)
            if target != key:
                self._auto_working[target] = self._auto_working.pop(key)
                self._auto.rekey(key, target)
                if self._voice_target_key == key:
                    self._voice_target_key = target
                self._pending_auto_key = target
                key, working = target, self._auto_working[target]
            params = randomize_seeds(working["params"], working["workflow"].seed_keys())
            self._reroll.start_prepared(key, working["workflow"], params)
        else:
            item = self._item_by_key.get(key)
            group = item.data(0, _GROUP_ROLE) if item else None
            self._reroll.start(key, group, self._image_rows)
        self._select_reroll(key)  # a no-op if the launch above failed to register
        return self._reroll.has(key)

    def _toggle_auto(self, checked: bool):
        """Start or stop auto-generating fresh variations of the open folder. Auto
        is also voice's on/off: starting a loop begins always-listening steering."""
        key = self._selected_folder_key()
        if key is not None:
            if checked:
                self._begin_auto(key)
            else:
                self._auto.stop(key)  # cleanup + voice-off run in _on_auto_stopped
        self._sync_auto_button()  # reflect the real state — a start may not take

    def _begin_auto(self, key: str):
        """Capture the folder's settings as the loop's working params, start the
        loop, and begin voice steering of its prompt."""
        self._capture_working(key)
        self._auto.start(key)
        if self._auto.is_active(key):
            self._voice_target_key = key
            self._voice.start(
                lambda: self._working_prompts(self._voice_target_key),
                lambda new: self._steer_prompts(self._voice_target_key, new),
            )
            self._show_voice_status("🎤 Listening…", transient=False)
        else:
            self._auto_working.pop(key, None)  # the launch didn't take

    def _capture_working(self, key: str):
        group = self._current_group()
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        workflow = WORKFLOW_REGISTRY.get(group.rows[0].get("workflow_name") or "")
        if workflow is not None:
            self._auto_working[key] = {
                "workflow": workflow, "params": filled_params(group.rows[0], workflow),
                "row": group.rows[0],
            }

    def _working_prompts(self, key: str) -> dict:
        params = self._auto_working.get(key, {}).get("params", {})
        return {"positive": params.get("positive_prompt", ""),
                "negative": params.get("negative_prompt", "")}

    def _steer_prompts(self, key: str, new_prompts: dict):
        """A voice command rewrote the prompts: the loop's next launches use them."""
        working = self._auto_working.get(key)
        if working is not None:
            working["params"]["positive_prompt"] = new_prompts.get("positive", "")
            working["params"]["negative_prompt"] = new_prompts.get("negative", "")

    def _working_folder_key(self, working: dict) -> str:
        """The settings-folder key the working params now belong to — recomputed as
        voice edits the prompt, so a steered loop can re-home to the matching folder."""
        row = {**working["row"], "params_json": json.dumps(working["params"])}
        return gallery.settings_folder_key(
            row, gallery.build_image_config_index(self._image_rows))

    def _on_auto_stopped(self, key: str):
        """A folder's loop ended (toggled off, cancelled, or failed): drop its
        working params and, if it was the voice target, stop listening."""
        self._auto_working.pop(key, None)
        if key == self._voice_target_key:
            self._voice.stop()
            self._voice_target_key = None
            self._pending_auto_key = None
            self._voice_status_timer.stop()
            self._voice_status.hide()
        self._sync_auto_button()

    # --- voice feedback: a floating caption of what voice heard and did --------

    def _show_voice_status(self, text: str, *, transient: bool):
        self._voice_status.setText(text)
        self._voice_status.adjustSize()
        self._reposition_voice_status()
        self._voice_status.show()
        self._voice_status.raise_()
        if transient:
            self._voice_status_timer.start(4000)  # then revert to the idle caption
        else:
            self._voice_status_timer.stop()

    def _voice_status_revert(self):
        if self._voice_target_key is not None:  # still listening
            self._show_voice_status("🎤 Listening…", transient=False)
        else:
            self._voice_status.hide()

    def _reposition_voice_status(self):
        self._voice_status.move(max(0, (self.width() - self._voice_status.width()) // 2), 12)

    def _on_voice_heard(self, text: str):
        if any(char.isalpha() for char in text):
            self._show_voice_status(f"🎤 heard: “{text}”", transient=True)

    def _on_voice_edited(self, _new_prompt: str):
        self._show_voice_status("🎤 ✓ prompt updated", transient=True)

    def _on_voice_error(self, message: str):
        self._show_voice_status(f"🎤 {message}", transient=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._voice_status.isVisible():
            self._reposition_voice_status()

    def _sync_auto_button(self):
        """Offer the auto-generate toggle only on a re-rollable settings folder,
        and keep it checked while that folder's loop runs."""
        group = self._current_group()
        available = isinstance(group, gallery.SettingsGroup) and self._can_reroll(group)
        key = self._selected_folder_key()
        self._auto_btn.setVisible(available)
        self._auto_btn.blockSignals(True)
        self._auto_btn.setChecked(available and key is not None and self._auto.is_active(key))
        self._auto_btn.blockSignals(False)

    def _sync_slideshow_button(self):
        """Offer the slideshow only on a folder that actually holds media."""
        group = self._current_group()
        self._slideshow_btn.setVisible(group is not None and bool(gallery.rows_under(group)))

    def _start_slideshow(self):
        """Open the current folder's media in a fullscreen slideshow."""
        group = self._current_group()
        if group is None:
            return
        items = self._slideshow_items(group)
        if not items:
            return
        self._slideshow = SlideshowView(items, on_delete=self._slideshow_delete)
        logger.info("Slideshow: %d items, shuffled order[:10]=%s",
                    len(items), self._slideshow._playlist.order[:10])
        self._slideshow.showFullScreen()

    def _slideshow_items(self, group) -> list:
        """(path, media_type, prompt_id) for each generation under ``group`` with a
        resolvable preview, in gallery order — the slideshow's playlist."""
        items = []
        for row in gallery.rows_under(group):
            resolved = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
            if resolved is not None:
                items.append((resolved[0], resolved[1], row["prompt_id"]))
        return items

    def _slideshow_delete(self, prompt_id: str):
        """Trash a generation culled from the slideshow (its Up key)."""
        row = self._db.get_generation(prompt_id)
        if row is not None:
            self._actions.delete_rows([row])

    def _reroll_item_seed(self, prompt_id: str, which: str):
        """Re-roll one i2v item, randomizing a single seed (its top-left hover
        controls). ``which`` is ``"video"`` (new motion, same frame) or ``"image"``
        (a new frame, same motion). Lands in the same folder — its live tile — as
        the whole-folder re-roll does; skips a folder already re-rolling."""
        if self._client is None:
            return
        row = self._db.get_generation(prompt_id)
        if row is None:
            return
        key = gallery.settings_folder_key(row, gallery.build_image_config_index(self._image_rows))
        if key in self._reroll_jobs:
            return  # this folder already has a re-roll running
        if which == "video":
            self._reroll.reroll_video_seed(key, row)
        else:
            self._reroll.reroll_image_seed(key, row, self._image_rows)
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

    def _is_rebuildable_video_row(self, row) -> bool:
        """Whether ``row`` is a video whose i2v recipe the app can rebuild — so its
        settings can be re-run on a new image. (``is_image_conditioned`` already
        implies the workflow is registered.) The shared gate behind both the video
        drop slot and the category dropdown's candidate pool."""
        return bool(
            row and gallery.media_type_of_row(row) == "video"
            and gallery.is_image_conditioned(row.get("workflow_name") or "")
        )

    def _combine_accepts_video(self, prompt_id: str) -> bool:
        """Whether the video slot accepts a dropped generation (see
        :meth:`_is_rebuildable_video_row`)."""
        return self._is_rebuildable_video_row(self._db.get_generation(prompt_id))

    def _combine_preview(self, prompt_id: str) -> tuple[str | None, str | None]:
        """A dropped item's (thumbnail, looping-preview) paths for its slot: a video
        loops its clip, an image shows its still. Either may be ``None`` when absent."""
        row = self._db.get_generation(prompt_id)
        if row is None:
            return (None, None)
        return (row.get("thumbnail_path"), self._animated_preview(row))

    def combine_selection(self) -> list:
        """The ``[image_id, video_id]`` sitting in the combine slots, for session save."""
        return [self._combine.image_slot.current_id(), self._combine.video_slot.current_id()]

    def restore_combine_selection(self, saved) -> None:
        """Refill the combine slots from a saved ``[image_id, video_id]``, skipping an
        item that's since been deleted or no longer fits its slot."""
        if not isinstance(saved, (list, tuple)) or len(saved) != 2:
            return
        image_id, video_id = saved
        if image_id and self._combine_accepts_image(image_id):
            self._combine.image_slot.set_item(image_id)
        if video_id and self._combine_accepts_video(video_id):
            self._combine.video_slot.set_item(video_id)

    def _on_thumbnail_drag_started(self, prompt_id: str):
        """A gallery thumbnail began dragging: light the combine slot it fits, so
        the drop target is obvious from the very start of the gesture."""
        self._combine.show_drop_candidates(prompt_id)

    def _on_thumbnail_drag_ended(self):
        self._combine.clear_drop_candidates()

    def _generate_combination(self, image_id: str, video_id: str):
        """Generate a new video from a dropped image + a dropped video's recipe.

        Reuses the video's workflow, settings and seed, swapping only the input
        image to the dropped one, and lands the result in the folder for that
        (image × settings) combination. A pinned seed can reproduce an identical
        past run, so this warns first via the shared "already generated" dialog —
        which, when the dropped image is itself a re-buildable generation, offers a
        fresh video seed (same frame), a fresh image seed (re-draw the dropped
        image), or both. A no-op if either row is gone, the video isn't a
        rebuildable image-conditioned recipe, the image has no output file, or that
        folder is already generating.
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
        # The frame is re-buildable independently of the video seed, so the key —
        # which groups by the image's config, not its filename — is the same one
        # whether we re-roll the seed, the frame, or both.
        key = gallery.settings_folder_key(
            {**dict(video_row), "params_json": json.dumps(params)},
            gallery.build_image_config_index(self._image_rows),
        )
        if self._would_reproduce_a_completed_run(workflow, params):
            image_workflow = WORKFLOW_REGISTRY.get(image_row.get("workflow_name") or "")
            can_reroll_image = (
                image_workflow is not None
                and image_row.get("source", "generated") == "generated"
            )
            choice = offer_reroll(self, workflow, can_reroll_image=can_reroll_image)
            if choice is None:
                return  # let the user pick a different pair rather than duplicate
            if choice in (REROLL_VIDEO, REROLL_BOTH):
                params = randomize_seeds(params, workflow.seed_keys())
            if choice in (REROLL_IMAGE, REROLL_BOTH):
                # Re-draw the dropped image (a new frame) and run the video on it,
                # carrying whatever video seed we settled on just above.
                if self._reroll.start_reroll_from_image(
                    key, image_row, image_workflow, workflow, params
                ):
                    self._reveal_combination(key)
                return
        if self._reroll.start_prepared(key, workflow, params):
            self._reveal_combination(key)

    def _rebuildable_videos(self, rows: list[dict]) -> list[dict]:
        """The completed, rebuildable i2v videos among ``rows`` — the pool an act's
        recipe is mined from (each carries the prompt it was made from, which names
        its act)."""
        return [row for row in rows
                if row.get("status") == "completed" and self._is_rebuildable_video_row(row)]

    def _category_candidates(self) -> list:
        """The recipe pool, read fresh at generate time rather than from the last
        rebuild — the gallery may have gained a video since."""
        return self._rebuildable_videos(self._db.list_generations())

    def _start_scene(self, video_row: dict, image_prompts: dict) -> str:
        """The prompt of ``video_row``'s start frame (its input image) — where the
        situation to match lives — resolved from ``image_prompts`` (prompt_id → prompt,
        built once from the in-memory image rows, so no per-video query). Falls back to
        the video's own prompt when the start frame can't be resolved (e.g. an import)."""
        source_id = gallery.find_source_image_id(video_row, self._image_rows)
        if source_id and (image_prompts.get(source_id) or "").strip():
            return image_prompts[source_id]
        return video_row.get("positive_prompt") or ""

    def _generate_category(self, image_id: str, category: str):
        """Run the recipe that fits ``category`` on the dropped image — the category
        dropdown's counterpart to a dropped video.

        The local LLM picks the recipe whose starting scene matches this image's
        situation (:func:`recipe_match.smart_recipe`); if it's unreachable or finds no
        fit, it falls back to the act's most-used recipe
        (:func:`recipe_match.best_recipe`). Either way the chosen exemplar hands off to
        the shared combine launch. A no-op — with a hint — when the gallery holds no
        video of the act, so a click never silently does nothing.
        """
        image_row = self._db.get_generation(image_id)
        if image_row is None:
            return
        image_prompts = {r.get("prompt_id"): r.get("positive_prompt") or "" for r in self._image_rows}
        candidates = [{**row, "start_scene": self._start_scene(row, image_prompts)}
                      for row in self._category_candidates()]
        video_id = recipe_match.smart_recipe(
            category, image_row.get("positive_prompt") or "", candidates,
            base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
            system_prompt=VIDEO_SCENE_MATCH_SYSTEM_PROMPT,
        ) or recipe_match.best_recipe(category, candidates)
        logger.info("combine: category=%s image=%s -> recipe from %s",
                    category, image_id, video_id)
        if video_id is None:
            QMessageBox.information(
                self, "No recipe yet",
                f"No past “{category}” video to base a recipe on yet — make one first, "
                "or drop a specific video instead.",
            )
            return
        self._generate_combination(image_id, video_id)

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
        self._selected_row = None  # a running re-roll isn't a saved generation
        self._browser.clear_thumbnail_selection()
        if self._reroll_tile is not None:
            self._reroll_tile.set_selected(True)
        self._info_tabs.show_reroll_frame(self._last_reroll_frame)

    def _on_reroll_preview(self, key: str, data: bytes):
        """Mirror a re-roll's live frame into the info pane while it's selected,
        remembering it so it survives the rebuild each stage completion triggers."""
        if key == self._selected_reroll_key:
            self._last_reroll_frame = data
            self._info_tabs.show_reroll_frame(data)

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
        startup; a tab's Generate is itself a re-roll, so every still-running row is
        the re-roll controller's to reconnect."""
        self._reroll.reconnect_running()

    def _cancel_reroll(self, key: str):
        self._auto.stop(key)  # cancelling the in-flight job ends the loop too
        self._reroll.cancel(key)
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()  # the front tab's folder may have stopped running

    def _abandon_reroll_preview(self, key: str):
        """Empty the info pane if it was mirroring a re-roll that has ended with no
        result to show (cancelled or failed)."""
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()
            self._clear_metadata()

    def _on_reroll_finished(self, key: str):
        """A re-roll saved its result (finalized by the controller): drop it as the
        info-pane source, rebuild so it shows as a normal thumbnail, and load it into
        the front tab so a Generate ends on its finished output, not the placeholder."""
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()  # refresh re-selects it as a finished thumbnail
        self.refresh()
        self._show_reroll_result_in_tab(key)
        # A voice-steered loop that re-homed to a new-prompt folder: open it now that
        # its first generation has given the folder a node.
        if self._pending_auto_key is not None:
            item = self._item_by_key.get(self._pending_auto_key)
            if item is not None:
                self._pending_auto_key = None
                self._tree.setCurrentItem(item)
        # A combine whose brand-new folder we parked off (on Recents) now has a
        # finished row, so the rebuild above gave that folder a node: drill in.
        if key == self._pending_combine_key:
            self._pending_combine_key = None
            item = self._item_by_key.get(key)
            if item is not None:
                self._tree.setCurrentItem(item)
        self._reconcile_generating()  # the run ended: the front tab drops its Cancel
        self._auto.note_finished(key)  # if auto-looping this folder, launch the next

    def _show_reroll_result_in_tab(self, key: str):
        """After a re-roll finishes, load its result into the front config tab.

        The just-finished generation is the folder's newest row (highest id); the
        rebuild has already given the folder its node. Loading it leaves the tab
        showing the finished image/video and its footer — the completed end-state of
        a Generate — instead of the live-frame placeholder it held while running."""
        item = self._item_by_key.get(key)
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if isinstance(group, gallery.SettingsGroup) and group.rows:
            self._info_tabs.show_result_in_current_tab(group.rows[0], self._image_rows)

    def _on_reroll_failed(self, key: str):
        """A re-roll failed (recorded by the controller): release the info pane if
        it was showing this one, and redraw the folder without its tile."""
        self._auto.note_failed(key)  # end the loop rather than spin on a broken workflow
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()  # the run ended: the front tab drops its Cancel

    def _rerender_current_leaf(self):
        """Redraw the open settings folder so its re-roll tile reflects the job."""
        group = self._current_group()
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

    def _update_running_bar(self):
        """Feed the bottom bar the in-flight jobs (running first), so the active
        generation shows from anywhere — the bar hides itself when nothing runs."""
        self._running_bar.set_items(self._inflight_items())

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
        """Reopen the config tabs saved from a previous session — their
        configurations only; any still-running re-roll is reconnected separately by
        :meth:`reconnect_running_rerolls`."""
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
        # Return to the most recent folder we were in that survives this delete;
        # fall back to the deleted folder's parent (not the top of the tree) when
        # history offers no survivor, so the view stays where the user was working.
        target = self._post_delete_target(group)
        if target is not None:
            self._tree.setCurrentItem(target)
        self._delete_rows(rows)

    def _post_delete_target(self, group):
        """The tree item to select after deleting ``group``: the most recently
        visited folder that isn't inside the deleted subtree, else its parent."""
        doomed = self._keys_under(group)
        for key in reversed(self._folder_history):
            if key not in doomed and (item := self._item_by_key.get(key)) is not None:
                return item
        item = self._item_by_key.get(group.key)
        return item.parent() if item is not None else None

    def _keys_under(self, group) -> set[str]:
        """``group``'s key plus every folder key nested under it in the tree — the
        folders a delete of ``group`` removes, so a return target can avoid them."""
        item = self._item_by_key.get(group.key)
        if item is None:
            return {group.key}
        keys, stack = set(), [item]
        while stack:
            node = stack.pop()
            node_group = node.data(0, _GROUP_ROLE)
            if node_group is not None:
                keys.add(node_group.key)
            stack.extend(node.child(i) for i in range(node.childCount()))
        return keys

    def _delete_rows(self, rows):
        if not rows:
            return
        deleted_ids = {r["prompt_id"] for r in rows}
        if self._selected and self._selected.get("prompt_id") in deleted_ids:
            self._info_tabs.clear_current_preview()  # release any file handle before the files move
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
        self._info_tabs.clear_current_preview()
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

    # --- the selected generation drives a config tab -----------------------

    def _on_thumbnail_clicked(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if not row:
            return
        self._clear_reroll_selection()  # a saved generation takes over the info pane
        self._selected_row = row
        # A genuine pick loads the generation into a config tab — its output in the
        # preview, its settings in the form, a footer for its media type — reusing
        # the current tab or forking one. A suppressed re-selection (a poll/rebuild,
        # or Back/Forward) only refreshes the current tab's preview, leaving the
        # tab set and any edited form alone.
        if not self._suppress_history:
            self._info_tabs.load_selection(row, self._image_rows)
        else:
            self._info_tabs.show_selection_preview(
                gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
            )
        self._browser.sync_containing_folder_button()  # a Recents preview offers the jump
        shelf_key = self._current_shelf_key()
        if shelf_key is not None:
            # Previewing an item on a shelf is shelf state, not a navigation: it's
            # remembered so Back can restore it, but the shelf stays the one history
            # stop (stepping through each preview would bury where you came from).
            self._shelf_selection[shelf_key] = prompt_id
        else:
            # In a folder, each viewed generation — a click or a followed link —
            # is its own browsing step.
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
        Back/Forward and a link both make. Opens the target's folder, then clicks
        the generation itself; suppressing keeps that off the history, and a
        recording caller (a link) adds the real target itself afterward."""
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
        """Drop the info-pane selection: forget the shown generation and empty the
        current tab's preview."""
        self._selected_row = None
        self._info_tabs.clear_current_preview()
        self._browser.sync_containing_folder_button()  # nothing selected: no jump to offer

    def _on_reuse(self):
        """Reuse the shown generation's parameters — fork a config tab from them.

        Gated on reusability (not just a button state) so the double-click path is
        inert for a workflow the app can't rebuild."""
        params = self.current_params()
        if params:
            self.reuse_requested.emit(self._selected_row.get("workflow_name", ""), params)


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
