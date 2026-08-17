import json
import logging
import random

from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QToolButton, QSplitter,
    QMenu, QInputDialog, QAbstractItemView, QMessageBox, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, QTimer, QPoint, QSize, pyqtSignal

from origenerator import gallery, recipe_match, recovery, timing
from origenerator.gui import icons
from origenerator.branch_session import is_branch_session, session_trash
from origenerator.comfyui_client import ComfyUIClient, ForeignQueue
from origenerator.config import (
    AMBIENT_AUDIO_VOICES, COMFYUI_OUTPUT_DIR, STATE_DIR, THUMB_DIR,
    LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL, VIDEO_SCENE_MATCH_SYSTEM_PROMPT,
)
from origenerator.db import Database
from origenerator.base_backfill import TARGET_KEY as BASE_RENDER_TARGET_KEY
from origenerator.base_backfill import queue_base_renders
from origenerator.experiments.background import queue_experiments
from origenerator.experiments.policy import ExperimentPolicy
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import (
    ConfigSnapshot, filled_params, find_duplicate_generation, randomize_seeds,
)
from origenerator.gui.ambient_audio import AmbientAudio
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.enhance_panel import EnhancePanel
from origenerator.gui.find_bar import FindBar
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.prompt_find import PromptFind
from origenerator.gui.combine_panel import CombinePanel
from origenerator.gui.auto_generate_controller import AutoGenerateController
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS, in_order
from origenerator.voice.show_commands import (
    ShowCommand, match_show_command, show_command_bias,
)
from origenerator.voice.steering import VoiceSteering
from origenerator.gui.reroll_prompt import (
    REROLL_BOTH, REROLL_IMAGE, REROLL_VIDEO, offer_reroll,
)
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.inflight import queue_wait_text
from origenerator.gui.info_pane_tabs import InfoPaneTabs
from origenerator.gui.osr2_driver import Osr2Driver
from origenerator.gui.osr2_stroke_driver import Osr2StrokeDriver
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.stroke_hud import STROKE_KEY_LEGEND, apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel
from origenerator.gui.generation_queue import GenerationQueue
from origenerator.gui.browser_pane import BrowserPane
from origenerator.gui.gallery_tree import (
    GalleryTree,
    EXPERIMENTS_KEY as _EXPERIMENTS_KEY,
    EXPERIMENTS_LABEL as _EXPERIMENTS_LABEL,
    GROUP_ROLE as _GROUP_ROLE,
    RECENTS_KEY as _RECENTS_KEY,
    RECENTS_LABEL as _RECENTS_LABEL,
    STARRED_KEY as _STARRED_KEY,
    STARRED_LABEL as _STARRED_LABEL,
    TRASH_KEY as _TRASH_KEY,
    TRASH_LABEL as _TRASH_LABEL,
)
from origenerator.navigation import NavigationHistory
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows import WORKFLOW_REGISTRY

ensure_shared_ui_on_path()
from shared_ui.check_box import CheckBox
from shared_ui.colors import BORDER_SUBTLE

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 1500
_PANE_MARGINS = (8, 8, 8, 8)  # breathing room inside each of the three panes
# The synthetic shelves, as back/forward history locations: each is a place the
# user can be standing, so a visit to one is recorded and restored by key rather
# than by the generation that happened to be picked there.
_SHELF_KEYS = (_RECENTS_KEY, _STARRED_KEY, _EXPERIMENTS_KEY, _TRASH_KEY)


def _is_reusable_workflow(workflow_name) -> bool:
    """Whether the app can rebuild this workflow from its template.

    The gate on the gallery re-roll: a re-roll re-runs a folder's own settings
    with a fresh seed, which needs a template to build the graph from.
    """
    return (workflow_name or "") in WORKFLOW_REGISTRY


def _bottom_divider() -> QFrame:
    """The hairline closing the browser pane off from the panels beneath it.

    Drawn with an explicit background rather than a ``QFrame`` sunken line: the
    app's stylesheet paints every plain widget one flat color, and a frame's
    native shadow line is invisible against it.
    """
    line = QFrame()
    line.setFixedHeight(1)
    line.setStyleSheet(f"background-color: {BORDER_SUBTLE.name()};")
    return line


def _is_deletable_folder(group) -> bool:
    """Whether a folder may be deleted: anything nested inside a workflow.

    Model, LoRA, source-image, and settings folders live within a workflow folder
    and are fair game; a whole workflow or media folder is off-limits, so a
    workflow's entire history can never be wiped in one action. A custom folder is
    off-limits too, and for a stronger reason: deleting one must remove the
    grouping, never the generations it gathers, so it has its own path
    (:meth:`GalleryView._remove_custom_folder`) rather than this one.
    """
    return isinstance(
        group,
        (gallery.ModelGroup, gallery.LoraGroup, gallery.SourceImageGroup, gallery.SettingsGroup),
    )


def _match_voice_command(text: str):
    """The one command an utterance is, or ``None`` — the whole spoken
    vocabulary, in the order it is tried.

    Both matchers are strict about their own shape and neither can claim the
    other's (a show command names the slideshow, a fix leads with "fix"), so the
    order only decides which is asked first. Everything unclaimed falls through
    to a prompt rewrite, which is why neither may be loose.
    """
    return match_show_command(text) or gallery.match_fix_command(text)


class GalleryView(QWidget):
    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryActions | None = None,
                 osr2_stroke: Osr2StrokeDriver | None = None,
                 ambient_audio: AmbientAudio | None = None):
        super().__init__(parent)
        self._db = db
        self._client = client
        # The app-global audio bed behind the toolbar's audio switch: several
        # library clips at once, sound only. Injectable so tests never open a
        # real media backend. Built before _build_ui, whose switch drives it.
        self._ambient_audio = (
            ambient_audio if ambient_audio is not None else AmbientAudio(parent=self)
        )
        # The one app-global stroke driver (genau's engine, no funscript needed):
        # every surface — this window and whatever slideshow is up —
        # drives it through the shared stroke keys, and while it holds the device
        # the funscript reconcile stands down. Injectable so tests never touch
        # the broker. Built before _build_ui, which wires its window feedback.
        self._osr2_stroke = osr2_stroke if osr2_stroke is not None else Osr2StrokeDriver(parent=self)
        # How long a slide holds the screen, app-wide: Genau's console shows
        # it as clip seconds and sets it, from whichever window the console
        # is on — including this one, with nothing playing, where it is what
        # the next slideshow opens at.
        self._pace = SlideshowPace(parent=self)
        self._osr2_stroke.active_changed.connect(self._on_stroke_active_changed)
        # The re-roll controller owns the live jobs and their DB lifecycle; the
        # view reacts to its signals with the redraws they call for.
        self._reroll = RerollController(db, client)
        self._reroll.changed.connect(self._rerender_current_leaf)
        self._reroll.changed.connect(self._reconcile_generating)
        self._reroll.changed.connect(self._reconcile_pending_enhancements)
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
        # The matcher rides along so a spoken "fix teeth" or "start slideshow" is
        # executed as a command rather than steering a
        # prompt; the bias teaches whisper the command vocabulary, without
        # which a quiet mic's "fix <part>" transcribes as other words entirely.
        self._voice = VoiceSteering(
            command_matcher=_match_voice_command,
            transcribe_bias=f"{gallery.fix_command_bias()} {show_command_bias()}",
        )
        self._voice.error.connect(lambda msg: logger.warning("Voice steering: %s", msg))
        self._voice.heard.connect(self._on_voice_heard)
        self._voice.edited.connect(self._on_voice_edited)
        self._voice.error.connect(self._on_voice_error)
        self._voice_target_key: str | None = None
        # A caption showing what voice heard and did, so it's visible without reading
        # the log. It rides at the top of the left pane, taking its own room rather
        # than floating over the header buttons it used to land on; transient
        # messages revert to the idle "Listening…" after a moment.
        self._voice_status = QLabel(self)
        self._voice_status.setObjectName("voiceStatus")
        self._voice_status.setWordWrap(True)  # a long utterance grows down, not sideways
        self._voice_status.setStyleSheet(
            "#voiceStatus { color: white; background: rgba(20, 20, 20, 225);"
            " padding: 6px 10px; border-radius: 6px; }"
        )
        self._voice_status.hide()
        self._voice_status_timer = QTimer(self)
        self._voice_status_timer.setSingleShot(True)
        self._voice_status_timer.timeout.connect(self._voice_status_revert)
        # The fullscreen slideshow window while one is open — whether it was
        # started from the toolbar (a whole folder, shuffled) or by
        # double-clicking a picture (that folder in order, held at a pace of
        # nought). One slot, because it is one view.
        self._slideshow = None
        # The folder whose running re-roll currently drives the info pane (its
        # tile is the selected item), that tile, and the last frame shown — so
        # live frames mirror from the browser-pane thumbnail into the full-size
        # preview, and the frame outlives both the rebuild each stage completion
        # triggers and an i2v's image->video job swap.
        self._selected_reroll_key: str | None = None
        self._reroll_tile: RerollTile | None = None
        self._last_reroll_frame: bytes | None = None
        # The queue-wait text currently painted in the pane, so a poll repaints it
        # only when the number actually moves.
        self._shown_wait_note: str | None = None
        self._actions = actions or GalleryActions(
            db, COMFYUI_OUTPUT_DIR, session_trash(STATE_DIR / "trash"),
            release_files=self._release_held_media, thumb_dir=THUMB_DIR,
            cancel_enhancements=self._cancel_enhancements_of,
        )
        # Derives the background experiments this gallery hands ComfyUI as the
        # app closes (the Experiments shelf's switch): variations of the user's
        # own work, landing on that shelf for review at the next launch.
        self._experiment_policy = ExperimentPolicy(
            registry=WORKFLOW_REGISTRY, rng=random.Random()
        )
        self._image_rows: list[dict] = []
        # The held deletions the Trash shelf lists, as gallery rows re-pointed at
        # their files in the trash — the rows behind everything a deleted item can
        # still do (see :meth:`_row_for`).
        self._held_rows: list[dict] = []
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
        # The latest streamed frame of each running enhance, keyed by the folder
        # its job runs under, so the info pane's version list, the tab preview
        # and the image's own tile can all show the level being made. One slot
        # per folder is enough because ComfyUI renders one prompt at a time: a
        # folder's other enhances are queued behind, and a queued one is shown as
        # queued rather than lent this frame (see
        # :meth:`_pending_enhancement_for`).
        self._enhance_frames: dict[str, bytes] = {}
        # Which image each running enhance is improving, and the set of runs that
        # answer was worked out from — recomputed only when that set changes, not
        # on every frame they stream.
        self._enhancing_by_prompt: dict[str, tuple] = {}
        self._enhancing_signature: tuple = ()
        # What every enhance runs at, app-wide — the Enhance subpanel's value.
        # Restored from the session by set_enhance_settings; built before
        # _build_ui, whose panel opens on it.
        self._enhance_settings = gallery.EnhanceSettings()
        self._editing_key: str | None = None  # folder being renamed inline
        # The user's own folders, resolved against the live tree on each rebuild,
        # and the throwaway one a multi-selection stands up (None with 0 or 1 row
        # picked). Both are CustomGroups, so the pane, breadcrumb, and slideshow
        # treat them exactly as they treat a derived folder.
        self._custom_folders: list = []
        self._selection_group = None
        self._history = NavigationHistory()  # back/forward across viewed locations
        self._suppress_history = False  # true while a rebuild or Back/Forward re-selects
        self._folder_history: list[str] = []  # folders the user opened, to return to after a delete
        # What another app has on the shared ComfyUI, re-read on every poll so the
        # bottom bar can say the server is busy before a Generate goes in behind it.
        self._foreign_queue = ForeignQueue(running=[], pending=[])
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
            # Esc puts the find away — after the panic-stop above has had it, so a
            # running device still stops on the first press whatever is open.
            if (event.key() == Qt.Key.Key_Escape and self._find_bar.isVisible()
                    and not self._other_window_owns_keys()):
                self._close_find()
                return True
            # Ctrl+F opens the find from wherever focus happens to be — including
            # the prompt field it will search, and the tree's rename editor, both
            # of which the gallery otherwise hands its keys to. Searching is what
            # the chord means everywhere else and nothing in this window competes
            # for it, so it is answered before that yielding happens.
            if (event.key() == Qt.Key.Key_F
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and self.isVisible() and not self._other_window_owns_keys()):
                self._open_find()
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
                # The OSR2 stroke keys work right here in the main window too —
                # not only in the fullscreen show — under the same guards that
                # keep them out of text fields and other windows.
                if (not event.modifiers()
                        and apply_stroke_key(self._osr2_stroke, event.key())):
                    self._stroke_panel.refresh()
                    return True
        return super().eventFilter(obj, event)

    def _handle_escape(self) -> bool:
        """Esc stops the physical device and any running loop, wherever focus is: it
        turns off OSR2 driving and ends auto-generate. It yields, though, when
        another window owns the keystroke — an open dialog/popup, so Esc still closes
        a combo dropdown, or an active fullscreen slideshow, which closes on
        Esc themselves. Returns whether it acted."""
        if self._other_window_owns_keys():
            return False
        handled = False
        if self._osr2_enabled:
            self._osr2_btn.setChecked(False)  # untoggling stops the driver
            handled = True
        if self._osr2_stroke.active:
            self._osr2_stroke.stop()  # the stroke is part of the same panic-stop
            handled = True
        if self._auto.any_active():
            self._auto.stop_all()
            handled = True
        return handled

    def _other_window_owns_keys(self) -> bool:
        """True when a keystroke belongs to something other than the gallery: an open
        modal dialog or popup, or a separate top-level window that's active — a
        fullscreen slideshow, which closes on Esc itself. The
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
        # Picking several folders (Shift/Ctrl) shows them together, as the folder
        # they would make; this fires after currentItemChanged, so it has the last
        # word on what the panes show.
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self._tree.itemDoubleClicked.connect(self._begin_inline_rename)
        self._tree.itemChanged.connect(self._commit_inline_rename)
        self._tree.star_clicked.connect(self._toggle_star)          # hover-row action
        self._tree.delete_clicked.connect(self._delete_folder_by_key)
        self._tree.folders_dropped.connect(self._on_folders_dropped)
        toc = QWidget()
        toc_box = QVBoxLayout(toc)
        toc_box.setContentsMargins(*_PANE_MARGINS)
        # Voice's caption sits above everything else in this pane — the top-left
        # corner of the view, where it obscures no control while it's up.
        toc_box.addWidget(self._voice_status)
        # The find over the tree: type any of a folder's name (prompt / model /
        # LoRA / workflow) to narrow it to matching branches, a word from anywhere
        # in a generation's positive or negative prompt — past the headline the
        # folder label truncates to — or a seed to jump straight to that one
        # generation. Sits above the tree it searches. Its counterpart is the find
        # strip below the info pane, which searches *inside* the open tab's
        # prompts rather than across the gallery's folders.
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Find a folder…")
        self._filter_edit.setToolTip(
            "Find folders by name, generations by anything in their prompt, or "
            "one generation by its seed"
        )
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
        self._combine.open_requested.connect(self._open_combination)
        self._combine.open_category_requested.connect(self._open_category)
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
        # Shown wherever there's a collection of media to play — a folder, or the
        # Recents/Starred shelf — with its tooltip naming that subject.
        self._slideshow_btn.hide()
        self._auto_btn = self._tool_button(
            icons.autoloop_icon(),
            "Auto-generate: repeatedly generate variations of this folder until "
            "toggled off (Esc stops it too)",
            self._toggle_auto, checkable=True,
        )
        self._auto_btn.setStyleSheet(  # a lit background while auto-generate is running
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        self._auto_btn.hide()  # shown only while a re-rollable settings folder is open
        self._enhance_all_btn = self._tool_button(
            icons.enhance_icon(),
            "Enhance every not-yet-enhanced image in this folder "
            "(upscale + low-denoise re-sample)",
            self._enhance_all,
        )
        self._enhance_all_btn.hide()  # shown only on a folder with images awaiting it
        # Turn the folders picked in the tree into a folder of their own. Shown
        # only while several are picked — that selection IS the folder, unsaved.
        self._group_btn = self._tool_button(
            icons.custom_folder_icon(),
            "Group the selected folders into a folder of your own",
            self._group_selection,
        )
        self._group_btn.hide()
        # A single global switch: while it's on, whatever scripted video is in front
        # drives the OSR2 — in the generate tab, or one opened fullscreen over it.
        # Always visible (it's app-wide), lit when on.
        self._osr2_btn = self._tool_button(
            icons.osr2_icon(),
            "Drive the OSR2 from the video in front — the generate tab's, or one "
            "opened fullscreen (Esc to stop)",
            self._on_osr2_toggle, checkable=True,
        )
        self._osr2_btn.setStyleSheet(
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        # The other app-global switch, beside the OSR2's: while it's on, a few
        # library clips play at once with only their sound — something to work
        # over, tied to nothing on screen.
        self._audio_btn = self._tool_button(
            icons.audio_icon(),
            f"Play {AMBIENT_AUDIO_VOICES} library clips at once, sound only, "
            "shuffling endlessly",
            self._on_audio_toggle, checkable=True,
        )
        self._audio_btn.setStyleSheet(
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        # The microphone, beside the other app-global switches: on is listening,
        # off is not, and that is the whole of it. Nothing opens or closes the mic
        # on its own any more — it used to come on with the Auto loop and with a
        # fullscreen show, which meant the answer to "is it listening?" was a
        # thing to work out rather than a thing to look at.
        self._mic_btn = self._tool_button(
            icons.mic_icon(),
            "Listen: spoken slideshow commands, targeted fixes over a show, and "
            "prompt steering while a folder is auto-generating",
            self._on_mic_toggle, checkable=True,
        )
        self._mic_btn.setStyleSheet(
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        # The stroke's own switch, beside the OSR2's. Genau toggles its engine
        # from Fun Time's console; there is no console here, so the toolbar
        # carries it — and the drive readout appears with it rather than sitting
        # there dark while nothing is being sent.
        self._stroke_btn = self._tool_button(
            icons.stroke_icon(),
            "Drive the OSR2 from a self-generated stroke — no video needed "
            f"({STROKE_KEY_LEGEND})",
            self._on_stroke_toggle, checkable=True,
        )
        self._stroke_btn.setStyleSheet(
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        self._delete_btn = self._tool_button(icons.delete_icon(), "Delete", self._delete_selection)
        toolbar = QHBoxLayout()
        toolbar.setSpacing(2)
        for button in (self._back_btn, self._forward_btn, self._undo_btn,
                       self._slideshow_btn, self._auto_btn, self._enhance_all_btn,
                       self._group_btn, self._mic_btn, self._audio_btn,
                       self._osr2_btn, self._stroke_btn, self._delete_btn):
            toolbar.addWidget(button)
        header.addLayout(toolbar)
        header.setAlignment(toolbar, Qt.AlignmentFlag.AlignTop)
        browser_box.addLayout(header)
        # The Recents shelf's image/video filter: two checkboxes choosing which
        # media types it lists, both on so the shelf opens showing everything. The
        # bar rides just under the header and appears only while that shelf is open.
        self._recents_image_cb = CheckBox("Images")
        self._recents_video_cb = CheckBox("Videos")
        for checkbox in (self._recents_image_cb, self._recents_video_cb):
            checkbox.setChecked(True)
            checkbox.toggled.connect(self._on_recents_filter_changed)
        self._recents_filter_bar = QWidget()
        filter_row = QHBoxLayout(self._recents_filter_bar)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel("Show:"))
        filter_row.addWidget(self._recents_image_cb)
        filter_row.addWidget(self._recents_video_cb)
        filter_row.addStretch(1)
        self._recents_filter_bar.hide()  # shown only on the Recents shelf
        browser_box.addWidget(self._recents_filter_bar)
        # The Experiments shelf's controls: the background experimenter's on/off
        # switch and a one-line status. Rides under the header like the Recents
        # filter, and appears only while that shelf is open.
        self._experiments_cb = CheckBox("Run experiments while the app is closed")
        self._experiments_cb.toggled.connect(self._on_experiments_toggled)
        # Scheduling an absence is the live install's alone, so a branch session
        # can't reach the switch (see queue_experiments_for_absence).
        self._experiments_cb.setEnabled(not is_branch_session())
        self._experiments_status = QLabel("")
        self._experiments_status.setObjectName("estimateLabel")
        self._experiments_bar = QWidget()
        experiments_row = QHBoxLayout(self._experiments_bar)
        experiments_row.setContentsMargins(0, 0, 0, 0)
        experiments_row.addWidget(self._experiments_cb)
        experiments_row.addWidget(self._experiments_status)
        experiments_row.addStretch(1)
        self._experiments_bar.hide()  # shown only on the Experiments shelf
        self._sync_experiments_bar()
        browser_box.addWidget(self._experiments_bar)
        self._avg_label = QLabel("")
        self._avg_label.setObjectName("estimateLabel")
        self._avg_label.setWordWrap(True)
        browser_box.addWidget(self._avg_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # The Recents shelf has no end: reaching the bottom of what it has drawn
        # draws the next page. Range as well as value — see BrowserPane.grow_recents.
        self._scroll.verticalScrollBar().valueChanged.connect(self._browser.grow_recents)
        self._scroll.verticalScrollBar().rangeChanged.connect(self._browser.grow_recents)
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
        # One OSR2 driver for the whole view, under the one global toggle
        # (self._osr2_btn): while that's on it follows whichever video is foreground —
        # an open slideshow, else whatever scripted video is in the front tab —
        # and with it off nothing drives on either surface.
        # Switching tabs/videos or opening/closing a slideshow re-aims it; with
        # nothing to drive it stops. self._osr2_driving is the (video, player) currently
        # driven, so a redundant reconcile doesn't churn the device. Built before the
        # panels are wired, since wiring connects their displayed_changed here.
        self._osr2_driver = Osr2Driver(parent=self)
        self._osr2_enabled = False
        self._osr2_driving = None
        # The bottom of the center (browser) pane, shared by two panels that each
        # take their own room rather than floating over anyone's buttons: genau's
        # readout, copied, held to the left at its fixed size, and the open
        # folder's Enhance settings taking the width left beside it.
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(12)
        self._stroke_panel = StrokePanel(self._osr2_stroke, pace=self._pace)
        bottom.addWidget(self._stroke_panel, 0, Qt.AlignmentFlag.AlignTop)
        # What an enhancement runs at — the Enhance All button, a single image's
        # Enhance, and (with its box on) each image the app newly generates.
        # App-wide and always here: enhancement is whatever you are doing at the
        # moment, not a property of the folder you happen to be standing in, so
        # it shows on the shelves as readily as on a settings folder. Deliberately
        # not on the Generate form: every setting there picks the folder a run
        # lands in, and this one doesn't.
        self._enhance_panel = EnhancePanel(self._on_enhance_settings_changed)
        self._enhance_panel.show_settings(self._enhance_settings)
        bottom.addWidget(self._enhance_panel, 1, Qt.AlignmentFlag.AlignTop)
        # A hairline where the browsing stops and these two panels start. Without
        # it the Enhance knobs read as the bottom of whatever folder is on screen
        # rather than as their own thing — which they are: app-wide settings that
        # don't belong to the folder they happen to be sitting under.
        browser_box.addWidget(_bottom_divider())
        browser_box.addLayout(bottom)
        self._info_tabs.tab_added.connect(self._wire_config_panel)
        for panel in self._info_tabs._config_panels():
            self._wire_config_panel(panel)  # the initial tab predates the connection
        self._info_tabs.currentChanged.connect(self._on_front_tab_changed)
        # Quitting mid-drive still releases the device — park it and restore genau —
        # so a closed app doesn't leave the OSR2 held and genau silently disabled.
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._osr2_driver.stop)
            app.aboutToQuit.connect(self._osr2_stroke.stop)
            # Same reason the preview releases its player: a live media player at
            # Qt/Python shutdown can deadlock the real (WMF) backend.
            app.aboutToQuit.connect(self._ambient_audio.stop)
        # A tab's Generate is a re-roll of its settings folder: launch it in that
        # folder's own re-roll slot and navigate there, live tile and all.
        self._info_tabs.generate_requested.connect(self._on_generate_requested)
        # The find strip, at the foot of the info pane where the prompts it
        # searches are. Ctrl+F opens it over the front tab's prompt fields; it
        # takes no room until then, and closing it clears every mark it painted.
        self._find = PromptFind()
        self._find_bar = FindBar()
        self._find_bar.query_changed.connect(self._on_find_query)
        self._find_bar.step_requested.connect(self._on_find_step)
        self._find_bar.dismissed.connect(self._close_find)
        info_pane = QWidget()
        info_box = QVBoxLayout(info_pane)
        info_box.setContentsMargins(0, 0, 0, 0)
        info_box.addWidget(self._info_tabs, 1)
        info_box.addWidget(self._find_bar)
        self._panes.addWidget(info_pane)

        # The TOC pane holds its width; the browser and info panes both grow with
        # the window (the browser faster), so the info pane stays comfortably wide
        # instead of a thin strip on a large screen. Long metadata values wrap
        # rather than scroll sideways, so these floors only need to keep the panes
        # readable — kept low enough that the window can still tile into a monitor
        # third or a portrait-monitor half.
        toc.setMinimumWidth(120)
        browser.setMinimumWidth(210)
        self._info_tabs.setMinimumWidth(300)
        info_pane.setMinimumWidth(300)  # the pane in the splitter is the wrapper now
        self._panes.setStretchFactor(0, 0)
        self._panes.setStretchFactor(1, 3)
        self._panes.setStretchFactor(2, 2)
        self._panes.setSizes([220, 560, 440])

        layout.addWidget(self._panes, 1)
        # A strip under the panes lists every generation in flight — ComfyUI runs
        # them one at a time, so a batch of Generates is a queue — reachable from
        # any folder or config tab. Fed on every rebuild and poll; a row dragged to
        # a new place asks the controller to make ComfyUI run them in that order.
        self._queue = GenerationQueue()
        self._queue.reorder_requested.connect(self._reroll.reorder)
        self._queue.clear_queue_requested.connect(self._clear_foreign_queue)
        layout.addWidget(self._queue)

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
        Its ``displayed_changed`` re-aims the global OSR2 drive at the front video
        and re-reads whether the tab still owns a run in flight, a double-click on
        its preview opens the folder behind it as a held slideshow,
        and its Cancel stops the re-roll running in the tab's folder. Called for the
        initial tab and every tab forked afterward."""
        panel.source_activated.connect(self._on_source_link)
        panel.animated_activated.connect(self._on_source_link)
        panel.containing_folder_requested.connect(self._browser.open_in_containing_folder)
        panel.displayed_changed.connect(self._reconcile_osr2)
        # A tab that just changed which image it shows needs the live enhance
        # tile for THAT image, not the one it was showing a moment ago.
        panel.displayed_changed.connect(self._reconcile_pending_enhancements)
        # Pointing a tab at another generation drops its claim on the run it
        # launched, so its Generate button has to be re-read straight away.
        panel.displayed_changed.connect(self._reconcile_generating)
        # Its version list's "+ Enhance" row runs through the same queue the
        # folder button and the context menu use, and its Delete goes through
        # the same undo stack as every other delete in the gallery.
        panel.enhance_requested.connect(lambda pid: self.enhance_items([pid]))
        panel.levels_delete_requested.connect(self.delete_enhance_levels)
        panel.set_enhance_settings(self._enhance_settings)
        panel.set_fullscreen_factory(self._open_slideshow_on_preview)
        panel.cancel_requested.connect(lambda p=panel: self._cancel_panel_reroll(p))
        # Dragging the tab's preview out lights the combine slot it fits, like a
        # browser thumbnail (see :meth:`_on_generation_drag_started`).
        panel.preview_drag_started.connect(self._on_generation_drag_started)
        panel.preview_drag_ended.connect(self._on_generation_drag_ended)
        # Picking a different workflow builds a whole new form, so an open find
        # has to let go of the fields it was holding before they're destroyed.
        panel.form_replaced.connect(self._retarget_find)
        # A tab's title is recomputed from its prompt on every keystroke, so this
        # is also the signal that the text an open find is marking up has moved
        # under it — re-run rather than leave highlights on words that shifted.
        panel.title_changed.connect(self._refresh_find)

    # --- Drive OSR2: a single global toggle following the front video ----------

    def _on_osr2_toggle(self, on: bool):
        self._osr2_enabled = on
        self._reconcile_osr2()

    def _reconcile_osr2(self):
        """Point the one driver at whichever video is foreground.

        Idempotent: it (re)starts only when the driven ``(video, player)`` actually
        changes and stops when nothing should drive — so tab switches, browsing,
        completions, and opening or closing a slideshow all resolve to the
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
        """The drive target the device should follow, or ``None``. The auto-generate
        slideshow's stroke engine owns the device outright while it runs; else, while
        the toggle is on, an open slideshow wins when it's showing a scripted video,
        otherwise the front tab's video.

        The toggle governs both surfaces alike: double-clicking a clip open fullscreen
        used to take the device on its own, so a clip watched with the switch off drove
        anyway — the switch is what decides now, whichever surface the video is on."""
        if self._osr2_stroke.active or not self._osr2_enabled:
            return None
        if self._slideshow is not None:
            target = self._slideshow.osr2_drive_target()
            if target is not None:
                return target
        panel = self._info_tabs.current_config_panel()
        if panel is not None:
            return panel.osr2_drive_target()
        return None

    def _open_slideshow_on_preview(self, media, frame):
        """A double-click on a tab's preview: open its folder as a slideshow held
        on the very picture that was clicked.

        The pace is nought — nothing moves until an arrow does, or until the
        console's clip-seconds pair is turned up — and the order is the browser's
        rather than a shuffle, because this is the folder you were already looking
        at rather than a set to be played. That is the whole of what used to be a
        second fullscreen viewer: the arrows, the counter, the neighbor stills,
        Up and Down, are the show's own.

        ``media`` is the file the pane is showing, or ``None`` while a generation
        is still running behind it — in which case the show opens over ``frame``,
        that run's latest, and goes on following it until the pane hands over the
        file it lands as.
        """
        items, index = self._folder_media_playlist()
        if media is None:  # following a run: it has no place among the files yet
            items, index = [], 0
        elif not items:  # the shown item isn't in the folder listing: play it alone
            items, index = [(media[0], media[1], None, None)], 0
        return self._open_slideshow(items, start=index, frame=frame,
                                    image_dwell_ms=0, shuffle=in_order,
                                    folder_items=self._folder_media())

    def _open_slideshow(self, items, *, folder_items=None, **kwargs):
        """Build, wire and show a fullscreen slideshow of ``items``.

        The one place a show is made, however it was asked for, so the toolbar's
        and a double-click's differ only in the order and the pace they pass.
        ``folder_items`` is what to arm a show that opened over a running
        generation with, since that one has no items of its own yet.
        """
        self._slideshow = SlideshowView(
            items, on_delete=self._trash_generation,
            on_enhance=self._enhance_from_slideshow,
            on_star=self._star_generation,
            pace=self._pace, stroke=self._osr2_stroke, **kwargs)
        if folder_items and self._slideshow.is_live():
            # Watching something render is no reason to lose the folder it is
            # being made in: the first arrow leaves the live frames for it.
            self._slideshow.set_playlist(folder_items, 0)
        # Shift+Left/Right gets its own axis: the versions of whichever image is
        # on screen, so a level can be compared against the one below it at full
        # size rather than in a thumbnail.
        self._slideshow.set_levels(self._folder_level_playlists())
        self._slideshow.open_requested.connect(self._open_from_slideshow)
        self._slideshow.closed.connect(self._on_slideshow_closed)
        self._slideshow.media_changed.connect(self._reconcile_osr2)
        self._slideshow.showFullScreen()
        self._reconcile_osr2()
        return self._slideshow

    def _folder_level_playlists(self) -> dict:
        """Each visible image's versions, keyed by the file the folder shows it
        under — newest first, matching the strip in the info pane. Each carries
        its label, so a slideshow can say which one is on screen."""
        playlists = {}
        for pid in self._browser.visible_prompt_ids():
            row = self._row_for(pid)
            if row is None:
                continue
            levels = gallery.enhance_levels(row)
            if len(levels) < 2:
                continue  # one version is nothing to step between
            entries = [
                (gallery.output_file_path(lvl.file, COMFYUI_OUTPUT_DIR), "image", lvl.label)
                for lvl in levels
            ]
            playlists[str(entries[0][0])] = entries
        return playlists

    def _folder_media_playlist(self):
        """The visible folder's resolvable media in shown order, and the index of
        the currently-shown item — what a double-clicked picture's show plays.

        Each entry carries its generation's id alongside the media, so the show's
        Up and Down can name what to trash and what to bookmark, and its stored
        thumbnail, which is the only still a video has for the neighbor previews.

        Returns an empty list when the shown item isn't among them, so the show
        always opens on what's already on screen."""
        selected_pid = self._selected["prompt_id"] if self._selected else None
        items, index, found = [], 0, False
        for entry in self._folder_media():
            if entry[2] == selected_pid:
                index, found = len(items), True
            items.append(entry)
        return (items, index) if found else ([], 0)

    def _folder_media(self) -> list[tuple]:
        """The visible folder's resolvable media in shown order, each as
        ``(path, media_type, prompt_id, thumbnail)``. In-flight and output-less
        rows have nothing to show fullscreen, so they are left out."""
        media = []
        for pid in self._browser.visible_prompt_ids():
            row = self._row_for(pid)
            preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR) if row else None
            if preview is not None:
                media.append((preview[0], preview[1], pid, row.get("thumbnail_path")))
        return media

    # --- the app-global OSR2 stroke: reconcile hold and main-window feedback --

    def _on_stroke_toggle(self, checked: bool):
        """The toolbar switch: take the device, or park it. The stroke is
        app-global, so this only asks — every surface hears back through
        ``active_changed``, including this window's own button."""
        if checked != self._osr2_stroke.active:
            self._osr2_stroke.toggle()

    def _on_stroke_active_changed(self, active: bool):
        """The stroke took or released the device (from whichever surface — a
        key in a slideshow, or the toolbar switch here): the funscript reconcile
        stands down while it holds it, and the switch follows. The drive readout
        shows and hides itself (:class:`StrokePanel` follows the same signal)."""
        self._reconcile_osr2()
        if self._stroke_btn.isChecked() != active:
            self._stroke_btn.setChecked(active)


    def _group_for_key(self, key: str):
        item = self._item_by_key.get(key)
        return item.data(0, _GROUP_ROLE) if item is not None else None

    def _on_front_tab_changed(self, _index):
        """The front config tab changed: re-aim the OSR2 drive at its video,
        re-evaluate whether that tab's folder is generating (its Cancel button),
        and point an open find at the prompts now in front."""
        self._reconcile_osr2()
        self._reconcile_generating()
        self._retarget_find()

    def osr2_enabled(self) -> bool:
        """Whether the global OSR2 toggle is on (for session persistence)."""
        return self._osr2_enabled

    def set_osr2_enabled(self, enabled):
        """Restore the global OSR2 toggle from a saved session."""
        self._osr2_btn.setChecked(bool(enabled))  # drives _on_osr2_toggle → reconcile

    # --- the audio bed: one app-global switch, following nothing on screen ----

    def _on_audio_toggle(self, on: bool):
        """Start or silence the audio bed. Unlike the OSR2's switch it has nothing
        to re-aim: it plays under whatever the user is doing, so the toggle is the
        whole of it."""
        if on:
            self._ambient_audio.start()
        else:
            self._ambient_audio.stop()

    def audio_enabled(self) -> bool:
        """Whether the audio bed's switch is on (for session persistence)."""
        return self._audio_btn.isChecked()

    def set_audio_enabled(self, enabled):
        """Restore the audio bed's switch from a saved session."""
        self._audio_btn.setChecked(bool(enabled))  # drives _on_audio_toggle → start

    # --- background experiments: the closing batch and the shelf's controls ---

    def experiments_enabled(self) -> bool:
        """Whether the background experimenter is on (for session persistence)."""
        return self._experiments_cb.isChecked()

    def set_experiments_enabled(self, enabled):
        """Restore the background experimenter's switch from a saved session —
        off in a branch session whatever was saved, since a branch session's
        state is seeded from the live install's, switch position included."""
        self._experiments_cb.setChecked(bool(enabled) and not is_branch_session())

    def queue_experiments_for_absence(self) -> int:
        """Hand ComfyUI a batch of experiments to run while the app is closed.

        Called from the window's close, the one moment the GPU becomes nobody's:
        ComfyUI outlives the app and works through the batch alone, and the next
        launch finalizes what finished onto the Experiments shelf. A no-op with
        the switch off. Returns how many were queued.

        Only the live install schedules an absence. A branch preview shares the
        one ComfyUI, and its batch outlives it there as work no app can account
        for: the live session cancels only the experiments its own database
        records, so a preview's survive every launch, and each Generate after
        them waits behind jobs "from another app" that were the user's own
        preview. The GPU while Origenerator is closed belongs to the install
        that is actually closed.
        """
        if is_branch_session():
            logger.info("Branch session: experiments left to the live app")
            return 0
        if not self.experiments_enabled():
            return 0
        return queue_experiments(
            self._db.list_generations(), self._experiment_policy,
            self._launch_experiment,
        )

    def queue_base_renders_for_absence(self) -> int:
        """Hand ComfyUI a batch of base re-renders to run while the app is closed.

        Called from the window's close beside the experiments batch, and for the
        same reason: this is a full render per repaired image and there are a
        great many of them, so putting one in front of the user's own work would
        be the whole cost of the feature. The next launch folds what finished and
        drops what hadn't started. Returns how many were queued.

        A branch preview queues none, exactly as it queues no experiments: its
        batch would outlive it in the one shared ComfyUI as work no app can
        account for, and the repairs belong to the live library anyway.
        """
        if is_branch_session():
            logger.info("Branch session: base re-renders left to the live app")
            return 0
        return queue_base_renders(self._db.list_generations(), self._launch_base_render)

    def _launch_base_render(self, workflow, params):
        """The batch's launch adapter: submit one re-render as a normal re-roll
        job tagged ``source="base_render"``, keyed to a folder of its own so it
        can never displace the user's work under a folder they might re-roll.
        Returns its prompt_id, or ``None`` when the launch didn't take."""
        key = f"base_render/{params[BASE_RENDER_TARGET_KEY]}"
        if not self._reroll.start_prepared(key, workflow, params,
                                           source=gallery.BASE_RENDER_SOURCE):
            return None
        return self._reroll.jobs[key].prompt_id

    def _on_experiments_toggled(self, _checked: bool):
        self._sync_experiments_bar()

    def _review_queue(self, rows) -> list[dict]:
        """The experiments waiting on the user's verdict — the Experiments shelf.

        Empty in a branch session, whatever its database holds. A preview's
        database is a copy of the live one, so it inherits the live app's
        unreviewed experiments; but a verdict recorded here stays in the copy
        while the live app goes on offering the same items, and a rejection here
        deletes the files the live app's own rows still point at — which is how
        a shelf of dead "No preview" tiles was built, and rebuilt, in the live
        install. Reviewing is the live app's, as scheduling is.
        """
        return [] if is_branch_session() else gallery.unreviewed_experiments(rows)

    def _sync_experiments_bar(self):
        """Say what the switch's current position means, under the switch."""
        if is_branch_session():
            self._experiments_status.setText(
                "Off — a branch preview never queues experiments; that's the live app's")
            return
        self._experiments_status.setText(
            "On — variations run after you close the app and land here for review"
            if self.experiments_enabled() else "Off — the GPU stays all yours"
        )

    def _launch_experiment(self, proposal):
        """The batch's launch adapter: submit a proposal as a normal re-roll job
        (tagged ``source="experiment"``), keyed to the settings folder its params
        land in. Returns the launched row's prompt_id, or ``None`` when the
        launch didn't take — no client, the submit failed, or an earlier
        proposal in this batch already claimed the folder (the same recipe
        twice explores nothing)."""
        key = self._folder_key_for(proposal.workflow.name, proposal.params)
        if not self._reroll.start_prepared(key, proposal.workflow, proposal.params,
                                           source="experiment"):
            return None
        return self._reroll.job_for(key).prompt_id

    def _on_experiment_verdict(self, prompt_id: str, action_id: str):
        """A review from the Experiments shelf: "keep" admits the result to the
        gallery proper; "reject" records the down-verdict the policy learns from
        and trashes the files (undoable). Either way the item leaves the shelf."""
        if action_id == "keep":
            self._db.set_experiment_verdict(prompt_id, "up")
        else:
            row = self._db.get_generation(prompt_id)
            if row is not None:
                self._actions.reject_experiment(row)
            self._sync_undo_button()
        self.refresh()

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
        """Point every config tab's Cancel and progress fill at the run *it* launched.

        A tab tracks its own Generates, not its settings folder: a folder can have
        several runs queued at once (two pictures of one recipe, both wanted), and
        a tab showing one of them must not claim the others. Of its own it follows
        the *oldest still alive* — the one nearest to being made, and so the one
        whose progress the bar shows and whose run its Cancel stops. A press that
        stopped the job queued behind the one on screen was the reported dead
        click. A chained i2v is two prompts but one run, so a tab follows its
        origin across the hand-off, and runs that have ended are let go here.

        Idempotent — driven by every re-roll lifecycle change and by switching the
        front tab. Every tab is reconciled, not just the front one, so a run
        launched from a tab that is now behind another still shows there.
        """
        for panel in self._info_tabs._config_panels():
            live = [(origin, job) for origin in panel.launched_runs()
                    if (job := self._reroll.job_for_origin(origin)) is not None]
            panel.forget_launched({origin for origin in panel.launched_runs()
                                   if origin not in {o for o, _ in live}})
            job = live[0][1] if live else None  # the oldest still alive: nearest done
            panel.set_generating(job is not None,
                                 job.prompt_id if job is not None else None)

    def _cancel_panel_reroll(self, panel):
        """Cancel the run this tab's bar is showing — its Cancel button.

        The oldest of the tab's own still alive, so the press stops the thing on
        screen rather than something queued behind it.
        """
        for origin in panel.launched_runs():
            job = self._reroll.job_for_origin(origin)
            if job is not None:
                self._cancel_job(job.prompt_id)
                return

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

        Identical in outcome to clicking the folder's re-roll "+": the job lands in
        that folder (its :class:`RerollTile` shows the leading run's live frame), so
        an edited config's brand-new folder appears and is navigated to at once —
        the running row it inserts gives the folder a tree node immediately (see
        :func:`build_gallery_tree`). A folder already generating takes the new run
        too; ComfyUI works through them in turn and the bottom strip shows the line.
        Missing form params are filled from the workflow's defaults, exactly as the
        old Generate did. A no-op without a client or an unknown workflow.

        The launched run is noted on the tab that asked for it, so that tab's
        Cancel and progress fill follow its own Generate rather than its folder.
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
        launching = self._info_tabs.current_config_panel()
        if not self._reroll.start_prepared(key, wf, params):
            return  # no client, or the submit failed
        if launching is not None:
            launching.note_launched(self._reroll.newest_job_for(key).origin)
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
        for job in self._reroll.all_jobs:
            job.reconcile()
            # And re-read what another app has in front of a job ComfyUI hasn't
            # started, so that wait shows a number instead of an unmoving bar
            # (see GenerationJob.refresh_backlog).
            job.refresh_backlog()
        self._refresh_foreign_queue()
        # And re-read the order ComfyUI will work through its queue in, which a
        # drag in the bottom strip changes (see RerollController.reorder).
        self._reroll.refresh_queue_order()
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
        # The bottom strip is always on screen, so refresh it every tick — its
        # rows' live frames and progress advance between rebuilds.
        self._update_queue()
        self._refresh_wait_note()

    def _rebuild(self, rows, meta):
        expanded = self._tree_view.persisted_expanded_keys()
        # Pending restore targets stand in until the user makes a live choice.
        selected_key = self._tree_view.selected_folder_key() or self._pending_key
        # A live multi-selection is a folder the user is composing, so a rebuild
        # (a poll, a completed generation) must not silently collapse it back to
        # one row — the keys are re-picked once the tree is rebuilt.
        multi_keys = self._tree.selected_folder_keys()
        if len(multi_keys) < 2:
            multi_keys = []
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
        unreviewed = self._review_queue(rows)
        held = self._held_rows = recovery.bin_items(self._bin_records())
        self._custom_folders = gallery.build_custom_folders(
            tree_model, self._db.list_custom_folders()
        )
        self._browser.set_model(
            gallery.recent_generations(rows, self._recents_media_types()),
            gallery.starred_folders(tree_model),
            gallery.starred_generations(rows),
            unreviewed,
            held,
        )
        self._tree_view.populate(tree_model, expanded,
                                 show_recents=bool(tree_model or self._browser._inflight_items()),
                                 experiment_count=len(unreviewed),
                                 trash_count=len(held),
                                 custom_folders=self._custom_folders)
        self._tree_view.reapply_filter()  # populate rebuilds un-filtered; re-narrow it
        # The rows the old selection group pointed at are gone with the rebuild;
        # _restore_multi_selection below stands a fresh one up from multi_keys.
        self._selection_group = None
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
                self._browser.show_empty()
                self._selected_row = None  # nothing selected
            self._restore_multi_selection(multi_keys)
            self._restore_reroll_selection(reroll_key, reroll_frame)
        finally:
            self._suppress_history = False
        # Seed history once with wherever the gallery first lands — a generation or
        # a shelf — so Back works even if the user's very first move leaves it.
        if self._history.current() is None:
            location = self._current_location()
            if location is not None:
                self._record_visit(location)
        self._update_queue()
        # Re-assert the front tab's Generate-as-progress state against the live jobs.
        # Keying off the freshly rebuilt image rows is what lets a reconnected re-roll
        # light its tab's button after a restart: at reconnect time the view's image
        # rows aren't built yet, so an i2v folder key wouldn't match then; here it does.
        self._reconcile_generating()

    def _reselect_generation(self, prompt_id: str | None):
        """Re-highlight a generation after a rebuild, if it's still on screen."""
        if prompt_id and prompt_id in self._browser.visible_prompt_ids():
            self._on_thumbnail_clicked(prompt_id)

    # --- find in the open tab's prompts (Ctrl+F) ------------------------------

    def _open_find(self):
        """Ctrl+F: open the find strip over the front tab's prompt fields, its
        standing query re-run against them.

        With no prompts in front — the resting tab, whose form waits on a workflow
        being picked — the chord goes to the tree's own find instead: the one
        search the window still has. It never does nothing.
        """
        fields = self._prompt_fields()
        if not fields:
            self._filter_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self._filter_edit.selectAll()
            return
        self._find.set_fields(fields)
        self._find_bar.open_find()
        self._on_find_query(self._find_bar.query())

    def _prompt_fields(self) -> list:
        """The prompt inputs of the config tab in front — what a find searches."""
        panel = self._info_tabs.current_config_panel()
        return panel.prompt_fields() if panel is not None else []

    def _on_find_query(self, text: str):
        self._find.search(text)
        self._sync_find_count()

    def _on_find_step(self, delta: int):
        self._find.step(delta)
        self._sync_find_count()

    def _sync_find_count(self):
        self._find_bar.show_count(self._find.position(), self._find.count())

    def _retarget_find(self):
        """Point an open find at the front tab's prompts — after a tab switch, a
        tab closing, or a workflow swap replacing the form under it. With nothing
        left to search it puts itself away rather than sitting over an empty pane."""
        if not self._find_bar.isVisible():
            return
        fields = self._prompt_fields()
        if not fields:
            self._close_find()
            return
        self._find.set_fields(fields)
        self._on_find_query(self._find_bar.query())

    def _refresh_find(self):
        """Re-run the open find over a prompt the user has just edited, keeping
        their place in the results — highlights left over a changed prompt would
        be marking words that have moved."""
        if self._find_bar.isVisible():
            self._find.refresh()
            self._sync_find_count()

    def _close_find(self):
        """Put the find away: the strip hidden and every highlight it painted
        gone, so a closed find leaves no marks in the prompts."""
        self._find.clear()
        self._find_bar.hide()

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
        if self._selection_group is not None:
            return  # a multi-selection owns the panes; the current row is one of many
        self._sync_auto_button()  # the auto toggle fits only a re-rollable leaf
        self._sync_slideshow_button()  # the slideshow fits any folder holding media
        self._sync_enhance_all_button()  # enhance-all fits a folder with plain images
        self._sync_group_button()      # grouping fits only a multi-selection
        # The image/video filter belongs to the Recents shelf alone; the
        # experimenter's switch to the Experiments shelf alone.
        self._recents_filter_bar.setVisible(current is self._recents_item)
        self._experiments_bar.setVisible(current is self._experiments_item)
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
        if current is self._experiments_item:
            self._sync_experiments_bar()
            self._browser.show_experiments_overview()
            return
        if current is self._trash_item:
            self._browser.show_trash_overview()
            return
        group = current.data(0, _GROUP_ROLE)
        self._note_folder_visit(group.key if group is not None else None)
        if group is not None:
            # A folder is somewhere the user went, so Back can return to it — and
            # so leaving a shelf for one is a step Back can undo at all.
            self._record_location(group.key)
        self._title.set_display(self._tree_view.breadcrumb(current))
        self._update_folder_average(group)
        self._show_group_contents(group)
        self._sync_delete_button()

    def _show_group_contents(self, group):
        """Fill the browser pane with what a folder holds: its generations
        (a settings leaf), the folders it gathers (one the user composed), or its
        sub-folders (every other tier)."""
        if isinstance(group, gallery.SettingsGroup):
            self._browser.show_thumbnails(group)
        elif isinstance(group, gallery.CustomGroup):
            self._browser.show_custom_folder(group)
        else:
            self._browser.show_folder_tiles(gallery.child_groups(group))

    # --- several folders at once: the folder they would make ------------------

    def _on_tree_selection_changed(self):
        """Picking several folders shows them together — the same view a saved
        custom folder gets, since that selection is exactly an unsaved one. Falling
        back to a single row hands the panes to :meth:`_on_folder_selected`."""
        groups = self._selected_groups()
        if len(groups) > 1:
            self._selection_group = gallery.selection_group(groups)
            self._show_selection()
            return
        was_multi = self._selection_group is not None
        self._selection_group = None
        if was_multi:
            self._on_folder_selected(self._tree.currentItem(), None)
        else:
            self._sync_group_button()

    def _selected_groups(self) -> list:
        """The folders the tree currently has picked, in tree order. A custom
        folder is left out: gathering one into another would nest a grouping inside
        a grouping, which the tree has nowhere to draw."""
        return [
            group for key in self._tree.selected_folder_keys()
            if (group := self._group_for_key(key)) is not None
            and not isinstance(group, gallery.CustomGroup)
        ]

    def _show_selection(self):
        """Render the picked folders as the folder they would make: their tiles in
        the browser pane, and the toolbar offering to save the grouping."""
        group = self._selection_group
        self._recents_filter_bar.hide()
        self._experiments_bar.hide()
        self._title.set_display(group.label)
        self._update_folder_average(group)
        self._browser.show_custom_folder(group)
        self._auto_btn.hide()
        self._enhance_all_btn.hide()
        self._sync_slideshow_button()
        self._sync_group_button()
        self._sync_delete_button()

    def _restore_multi_selection(self, keys: list[str]):
        """Re-pick the folders a rebuild dropped, and re-show them together.

        The first is set as the current row, which clears whatever the rebuild's
        own restore had picked — so what comes back is exactly what was picked
        before, never that plus the folder the restore landed on."""
        items = [item for key in keys if (item := self._item_by_key.get(key)) is not None]
        if len(items) < 2:
            return
        self._tree.blockSignals(True)
        try:
            self._tree.setCurrentItem(items[0])
            for item in items[1:]:
                item.setSelected(True)
        finally:
            self._tree.blockSignals(False)
        self._on_tree_selection_changed()

    def _sync_group_button(self):
        """Offer "group these" only while several folders are picked — one folder
        is not a grouping, and the button would only ask what it meant."""
        self._group_btn.setVisible(self._selection_group is not None)

    def _group_selection(self):
        """Save the picked folders as a folder of the user's own, under a name they
        give, and open it."""
        group = self._selection_group
        if group is None:
            return
        members = gallery.child_groups(group)
        name, ok = QInputDialog.getText(
            self, "New Folder",
            f"Name for a folder holding these {len(members)} folders:",
        )
        if not ok or not name.strip():
            return
        folder_id = self._actions.create_custom_folder(
            name.strip(), [self._member_identity(m) for m in members]
        )
        self._open_custom_folder(folder_id)

    def _member_identity(self, group) -> tuple:
        """A gathered folder as ``(key, level, ref_prompt_id)`` — its key plus the
        identity the reconcile re-derives it from when a key formula moves."""
        rows = gallery.rows_under(group)
        return (group.key, gallery.group_level(group),
                rows[0]["prompt_id"] if rows else None)

    def _open_custom_folder(self, folder_id: int):
        """Rebuild so the folder has a row, then land on it — the end of every
        action that makes or fills one."""
        self._tree.clearSelection()
        self._selection_group = None
        self.refresh()
        self._sync_undo_button()
        item = self._item_by_key.get(gallery.custom_folder_key(folder_id))
        if item is not None:
            self._tree.setCurrentItem(item)

    def _on_folders_dropped(self, target_key: str, keys: list):
        """Folders dragged onto a collecting row: Starred stars them (the drag-and-
        drop way to bookmark), a custom folder gathers them."""
        groups = [g for key in keys if (g := self._group_for_key(key)) is not None]
        if target_key == _STARRED_KEY:
            for group in groups:
                self._db.set_folder_starred(group.key, True)
            self.refresh()
            return
        folder_id = gallery.custom_folder_id(target_key)
        if folder_id is None:
            return
        self._actions.add_to_custom_folder(
            folder_id, [self._member_identity(g) for g in groups]
        )
        self._open_custom_folder(folder_id)

    def _new_custom_folder(self):
        """Make an empty folder of the user's own — the tree's right-click action,
        for when the folders to fill it with are easier dragged in than picked."""
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name.strip():
            self._open_custom_folder(self._actions.create_custom_folder(name.strip(), []))

    def _remove_custom_folder(self, group):
        """Delete a folder the user made. Only the grouping goes — its gathered
        folders and their generations are untouched — so the confirmation says so
        rather than reading like the delete that trashes files."""
        count = len(gallery.child_groups(group))
        plural = "s" if count != 1 else ""
        if not self._confirm(
            f"Remove the folder “{group.label}”?\n\n"
            f"The {count} folder{plural} it holds, and their items, are kept."
        ):
            return
        self._actions.delete_custom_folder(group.folder_id)
        self._tree.clearSelection()
        self._selection_group = None
        self.refresh()
        self._sync_undo_button()

    def _remove_from_custom_folder(self, group, member_key: str):
        """Drop one gathered folder out of the custom folder on screen."""
        member = self._group_for_key(member_key)
        identity = self._member_identity(member) if member is not None else (member_key, None, None)
        self._actions.remove_from_custom_folder(
            group.folder_id, member_key, level=identity[1], ref_prompt_id=identity[2]
        )
        self.refresh()
        self._sync_undo_button()

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

        Any folder whose workflow the app knows how to build, imported or not: a
        re-roll is that folder's own settings + a random seed + Generate (with
        missing params filled from the workflow's defaults, just as the Generate
        tab does).
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
        or a running generation's frames all land. ``None`` only if the pane holds
        something that isn't a config tab, which nothing builds."""
        panel = self._info_tabs.current_config_panel()
        return panel._preview if panel is not None else None

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

    @property
    def _experiments_item(self):
        return self._tree_view.experiments_item

    @property
    def _trash_item(self):
        return self._tree_view.trash_item

    def _selected_folder_key(self) -> str | None:
        """The selected folder's key (or a shelf's), from the tree renderer."""
        return self._tree_view.selected_folder_key()

    def _current_group(self):
        """The folder on screen, or ``None`` (a shelf or an empty selection).

        While several folders are picked that's the unsaved folder they make, so
        everything reading this — the slideshow, the title, the average, the delete
        button — sees one folder whether or not it has been saved yet."""
        if self._selection_group is not None:
            return self._selection_group
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
        """Start or stop auto-generating fresh variations of the open folder.

        It no longer touches the microphone. A running loop is what gives voice a
        prompt to steer, so an open mic starts steering when one begins — but the
        mic itself is the button's, and only the button's.
        """
        key = self._selected_folder_key()
        if key is not None:
            if checked:
                self._begin_auto(key)
            else:
                self._auto.stop(key)  # cleanup + voice-off run in _on_auto_stopped
        self._sync_auto_button()  # reflect the real state — a start may not take

    def _begin_auto(self, key: str):
        """Capture the folder's settings as the loop's working params and start
        the loop, giving an open mic a prompt to steer."""
        self._capture_working(key)
        self._auto.start(key)
        if self._auto.is_active(key):
            self._voice_target_key = key
            self._sync_voice()  # steers this folder's prompt, if the mic is on
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
        """A folder's loop ended (toggled off, Esc'd, or failed — a cancelled
        variation doesn't end it): drop its working params and, if it was the one
        being steered, leave voice with nothing to steer. The mic stays as the
        button has it."""
        self._auto_working.pop(key, None)
        if key == self._voice_target_key:
            self._voice_target_key = None
            self._pending_auto_key = None
            self._sync_voice()
        self._sync_auto_button()

    # --- voice feedback: a floating caption of what voice heard and did --------

    def _show_voice_status(self, text: str, *, transient: bool):
        self._voice_status.setText(text)
        self._voice_status.show()
        if transient:
            self._voice_status_timer.start(4000)  # then revert to the idle caption
        else:
            self._voice_status_timer.stop()

    def _voice_status_revert(self):
        if self._mic_btn.isChecked():  # still listening
            self._show_voice_status("🎤 Listening…", transient=False)
        else:
            self._voice_status.hide()

    def _on_voice_heard(self, text: str):
        if any(char.isalpha() for char in text):
            self._show_voice_status(f"🎤 heard: “{text}”", transient=True)

    def _on_voice_edited(self, _new_prompt: str):
        self._show_voice_status("🎤 ✓ prompt updated", transient=True)

    def _on_voice_error(self, message: str):
        self._show_voice_status(f"🎤 {message}", transient=True)

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
        """Offer the slideshow on anything that holds media: a folder, or the
        Recents/Starred/Experiments shelf — each a collection of generations like a
        folder, just gathered rather than nested. The tooltip names what it would
        play.

        Media, not rows: a folder gets its node the moment a generation starts, so
        a folder being filled can hold nothing anyone can look at yet, and a button
        that opens an empty show is worse than no button."""
        self._slideshow_btn.setVisible(
            bool(self._slideshow_items(self._slideshow_rows()))
        )
        self._slideshow_btn.setToolTip(f"Play {self._slideshow_subject()} as a slideshow")

    def _slideshow_rows(self) -> list[dict]:
        """The generations the slideshow would play from the view on screen: the
        shelf's collection on a shelf, else everything under the selected folder."""
        rows = self._browser.shelf_rows()
        if rows is not None:
            return rows
        group = self._current_group()
        return gallery.rows_under(group) if group is not None else []

    def _slideshow_subject(self) -> str:
        """What the slideshow button would play, named for its tooltip."""
        return {_RECENTS_KEY: _RECENTS_LABEL, _STARRED_KEY: _STARRED_LABEL,
                _EXPERIMENTS_KEY: _EXPERIMENTS_LABEL,
                _TRASH_KEY: _TRASH_LABEL}.get(
            self._current_shelf_key(), "this folder"
        )

    # --- standalone enhance: the folder button, the selection action, the queue ---

    def _sync_enhance_all_button(self):
        """Offer Enhance All only on a settings folder holding finished images
        that haven't been enhanced yet — neither inline (their workflow's
        ``enhance`` toggle) nor by a standalone enhance of their output."""
        group = self._current_group()
        available = isinstance(group, gallery.SettingsGroup) and bool(
            gallery.rows_awaiting_enhancement(group.rows, self._db.list_generations())
        )
        self._enhance_all_btn.setVisible(available)

    def enhance_settings(self) -> str:
        """The app-wide enhancement settings, for the session to persist."""
        return self._enhance_settings.to_json()

    def set_enhance_settings(self, raw: str | None):
        """Restore the enhancement settings a previous session left."""
        self._enhance_settings = gallery.EnhanceSettings.parse(raw)
        self._enhance_panel.show_settings(self._enhance_settings)
        self._push_enhance_settings()

    def _push_enhance_settings(self):
        """Tell every config tab what the ``+ Enhance`` card would run at.

        The panel holds the settings and the tabs hold the images, so the card
        can only know whether it would be making a duplicate once the two meet —
        here, on every edit and every rebuild."""
        for panel in self._info_tabs._config_panels():
            panel.set_enhance_settings(self._enhance_settings)

    def _on_enhance_settings_changed(self, settings):
        """Take an edit made in the Enhance subpanel.

        Held app-wide rather than per folder: enhancement is whatever you are
        doing at the moment, not a property of where you happen to be standing,
        so switching folders never changes what the next enhance will run at.
        Written through on each edit rather than on an Apply, so an enhance
        launched a moment later uses what is on screen."""
        self._enhance_settings = settings
        self._push_enhance_settings()

    def _enhance_all(self):
        """The folder button's action: queue a standalone enhance for every
        member image that isn't enhanced yet, at the current settings, then
        retire the button."""
        group = self._current_group()
        if not isinstance(group, gallery.SettingsGroup):
            return
        self._enqueue_enhancements(
            gallery.rows_awaiting_enhancement(group.rows, self._db.list_generations())
        )
        self._sync_enhance_all_button()

    def enhance_items(self, prompt_ids: list[str]):
        """Queue a standalone enhance for each picked generation (the thumbnail
        context menu's action) — a deliberate pick, so already-enhanced images
        are re-enhanced rather than skipped, landing as a further level beside
        the ones already there."""
        rows = [self._db.get_generation(pid) for pid in prompt_ids]
        self._enqueue_enhancements([r for r in rows if r is not None])

    def _enqueue_enhancements(self, rows: list[dict]):
        """Launch a standalone enhance of each of ``rows``, at the current settings.

        All of them go to the controller at once: ComfyUI runs one prompt at a
        time and the queue strip shows the line, so a batch of enhances is a
        queue the user can watch — and cancel a row out of — rather than a
        backlog held out of sight in here. (This view did hold one, because
        enhances of a single folder's images share a settings key and the
        controller took only one job per folder; it takes them all now, so the
        buffer had nothing left to do but hide the work.)
        """
        index = gallery.build_image_config_index(self._image_rows)
        for row in rows:
            params = gallery.enhance_params_for(row, self._enhance_settings)
            if params is None:
                logger.warning("Enhance skipped for %s: no output file to enhance",
                               row.get("prompt_id"))
                continue
            self._launch_enhance(row, params, index)

    def _launch_enhance(self, row: dict, params: dict, index=None) -> bool:
        """Hand one standalone enhance to the controller, under the folder its
        settings shape — a batch shares ``index`` so it isn't rebuilt per row.

        Returns whether the run started. Unlaunchable (no client, or the
        submit was refused) is logged rather than dropped in silence: a
        request the user made and never saw run is the one failure they
        cannot diagnose from the screen.
        """
        workflow = WORKFLOW_REGISTRY[gallery.ENHANCE_WORKFLOW]
        if index is None:
            index = gallery.build_image_config_index(self._image_rows)
        key = gallery.settings_folder_key(
            {"workflow_name": workflow.name, "workflow_version": workflow.version,
             "params_json": json.dumps(params)},
            index,
        )
        prepared = randomize_seeds(params, workflow.seed_keys())
        if self._reroll.start_prepared(key, workflow, prepared):
            logger.info("Enhance launched for %s on %s at %s, under %s",
                        row.get("prompt_id"), params.get("input_image"),
                        gallery.describe_enhance_params(params), key)
            return True
        logger.warning("Enhance of %s dropped: could not launch under %s",
                       params.get("input_image"), key)
        return False

    def _enhance_from_slideshow(self, prompt_id: str) -> bool:
        """Holding a slide asked for it to be enhanced. Returns whether a run
        started — the slideshow shows its corner note only if one did.

        Only an image that has received NO enhancement gets one, the same gate
        Enhance All and the Auto switch use. A hold is a glance-speed gesture
        made with no view of the Enhance panel, so an image already carrying an
        enhancement someone chose must not be re-derived at whatever the knobs
        happen to say now: that spends a run and hangs a level nobody asked for
        beside the one they did. Re-enhancing stays a deliberate act — the
        thumbnail menu's Enhance, or the info pane's ``+ Enhance`` card, both of
        which are pressed while looking at the settings they will use.

        The decision is here rather than in the slideshow because it is this
        side that holds the levels — and a video has none to receive."""
        row = self._db.get_generation(prompt_id)
        if row is None or not gallery.is_enhanceable_row(row):
            return False
        if gallery.is_enhanced_row(row):
            return False
        if self.is_enhancing(row):
            return False
        self._enqueue_enhancements([row])
        return True

    # --- spoken commands: "fix teeth" over a show, "start slideshow" for one ---

    def _on_mic_toggle(self, _on: bool):
        """The microphone switch: the one thing that opens or closes the mic."""
        self._sync_voice()

    def _sync_voice(self):
        """Listen, or don't, exactly as the mic button says.

        Nothing else decides. The mic used to come on with the Auto loop and
        again with a fullscreen show, which made "is it listening?" a question
        with a derivation rather than an answer — and left "start slideshow"
        unhearable in the one state it is for, with no show up.

        What is listened *for* still depends on what is running: the spoken
        commands always, and the prompt steering only while a loop has a folder
        to steer. That is not a second switch, just nothing to steer.
        """
        if not self._mic_btn.isChecked():
            self._voice.stop()           # both halves, so the listener closes
            self._voice.stop_commands()
            self._voice_status_timer.stop()
            self._voice_status.hide()
            return
        self._voice.start_commands(self._on_voice_command)
        if self._voice_target_key is not None:
            self._voice.start(
                lambda: self._working_prompts(self._voice_target_key),
                lambda new: self._steer_prompts(self._voice_target_key, new),
            )
        else:
            self._voice.stop()  # no loop to steer; the commands hold the mic open
        self._show_voice_status("🎤 Listening…", transient=False)

    def _on_voice_command(self, matched):
        """One recognized utterance: a show command, or a targeted fix."""
        if isinstance(matched, ShowCommand):
            self._run_show_command(matched)
        else:
            self._on_voice_fix(matched)

    def _run_show_command(self, command: ShowCommand):
        """Get the show going, hold it, or close it.

        Pausing is a pace of nought and starting is that pace back at the
        standard number, because a show that never moves on is exactly what a
        held picture is here — there is no separate paused state to keep.

        The pace is set through the show when there is one, not only posted to
        the app-wide number: a show sitting at nought while that number already
        reads four would get no word of a change that never happened, and would
        stay frozen through the very command meant to start it.
        """
        show = self._slideshow
        if command is ShowCommand.STOP:
            if show is None:
                self._show_voice_status("🎤 no slideshow to close", transient=True)
                return
            show.close()
            self._show_voice_status("🎤 slideshow closed", transient=True)
            return
        seconds = 0 if command is ShowCommand.PAUSE else DEFAULT_IMAGE_DWELL_MS // 1000
        if show is None:
            self._pace.set_seconds(seconds)  # what the next show opens at
            if command is ShowCommand.PAUSE:
                self._show_voice_status("🎤 no slideshow to pause", transient=True)
                return
            self._start_slideshow()
            if self._slideshow is None:
                self._show_voice_status("🎤 nothing here to play", transient=True)
            return
        show.set_dwell_s(seconds)
        show.note_voice_command(
            "🎤 slideshow paused" if command is ShowCommand.PAUSE
            else f"🎤 slideshow at {seconds}s"
        )

    def _on_voice_fix(self, part):
        """A spoken "fix <part>": aim a targeted detail pass at what's on screen.

        Answered out of the show's own note — the speaker is looking at it, not
        at this pane. Said with no show up there is no "on screen" to aim at, and
        the utterance has already been claimed as a command by the time it gets
        here, so the caption says so rather than letting it vanish."""
        show = self._slideshow
        if show is None:
            self._show_voice_status(
                f"🎤 a {part.name} fix needs a picture on screen", transient=True)
            return
        prompt_id, message = self._fix_part(show.voice_fix_target(), part)
        show.note_voice_fix(prompt_id, message)

    def _fix_part(self, prompt_id: str | None, part) -> tuple[str | None, str]:
        """Launch a targeted fix if the image wants one: the id it launched on
        (``None`` when it didn't) and the line the surface should say about it.

        The run is the image's latest enhancement done again with the detail
        pass aimed at the named part (:func:`~origenerator.gallery.enhance.
        fix_part_params`) — so the answer to a bad hand on an already-enhanced
        image is the same image, same settings, hand redrawn."""
        row = self._db.get_generation(prompt_id) if prompt_id else None
        if row is None or not gallery.is_enhanceable_row(row):
            return None, f"🎤 only a finished image can get a {part.name} fix"
        params = gallery.fix_part_params(row, part, self._enhance_settings)
        if params is None:
            return None, (f"🎤 no {part.name} detector installed "
                          "(ComfyUI models/ultralytics/bbox)")
        if gallery.level_matching_params(row, params) is not None:
            return None, f"🎤 already has this {part.name} fix"
        if self.is_enhancing(row):
            return None, "🎤 an enhance of this image is already running"
        logger.info("Voice fix: %s on %s at %s", part.name, row.get("prompt_id"),
                    gallery.describe_enhance_params(params))
        if not self._launch_enhance(row, params):
            return None, f"🎤 couldn't launch the {part.name} fix — see the log"
        return row["prompt_id"], f"🎤 fixing {part.name}…"

    def _feed_slideshow_enhanced(self, row: dict | None):
        """Hand a landed enhancement to an open show, so the item becomes the
        better version there rather than the version it was made from. A show
        ignores an id it isn't holding.

        Not only while that item is the one on screen: an enhancement asked for
        from a show lands minutes later, by which time it has long paged on, so an
        upgrade it doesn't take here it never takes at all. The show also draws
        each item small as a neighbor, so it takes the new thumbnail with the file.
        """
        if row is None or self._slideshow is None:
            return
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            return
        self._slideshow.note_enhanced(row["prompt_id"], preview[0], preview[1],
                                      still=row.get("thumbnail_path"))

    def is_enhancing(self, row: dict) -> bool:
        """Whether a standalone enhance of this image is running right now.

        The browser pane's tiles ask, so a folder generating with the Auto
        switch on reads honestly: the base render is out, on screen, and
        something better is on the way. Without it the folder looks like it is
        turning out plain images and ignoring the switch.

        Every live job is searched, not each folder's leading one: a batch of
        enhances goes out whole and its members share a settings key, so all but
        the first would read as not-cooking off the folder-facing view."""
        return any(
            job.workflow.name == gallery.ENHANCE_WORKFLOW
            and gallery.enhance_targets_row(job.params.get("input_image"), row)
            for job in self._reroll.all_jobs
        )

    def delete_enhance_levels(self, prompt_id: str, filenames: list):
        """Bin some of one image's versions, from the info pane's version list.

        Undoable like every other delete here, and only ever a delete of files:
        the generation keeps its row, its folder, its star and its other
        versions. The rebuild after is what redraws the tile — a binned top
        version means a new picture and, once the last enhancement goes, no more
        green badge."""
        row = self._db.get_generation(prompt_id)
        if row is None or not self._actions.delete_enhance_levels(row, filenames):
            return
        self._sync_undo_button()
        self.refresh()
        updated = self._db.get_generation(prompt_id)
        if updated is not None:
            # Every tab showing this image, not just the front one — the delete
            # can come from a tab that isn't in front, and a stale list would
            # still be offering a version that is gone.
            for panel in self._info_tabs._config_panels():
                shown = panel.displayed_row()
                if shown is not None and shown.get("prompt_id") == prompt_id:
                    panel.show_completed_result(updated, self._image_rows)
        self._sync_enhance_all_button()  # an image with no enhancement left awaits one

    def _reconcile_pending_enhancements(self):
        """Show the enhancement being made wherever the image it improves is.

        The info pane's version list leads with a live row while one is cooking,
        the tab's own preview streams the same frames, and the image's tile in
        the middle column streams them under its "Enhancing…" scrim — the same
        in-flight treatment work gets everywhere else in the app. The jobs are
        the gallery's, so the match is made here: every running standalone
        enhance against every tab's displayed row. Cheap enough to re-run on
        each frame; the panel updates its row in place.

        Every job of every folder, for the same reason :meth:`is_enhancing` reads
        them all: a batch of enhances shares one settings key, and a tab showing
        the third image of it must find its own run rather than the first.
        """
        running = [
            (key, job)
            for key, jobs in self._reroll.jobs_by_folder.items()
            for job in jobs
            if job.workflow.name == gallery.ENHANCE_WORKFLOW
        ]
        for panel in self._info_tabs._config_panels():
            row = panel.displayed_row()
            panel.set_pending_enhancement(
                self._pending_enhancement_for(row, running) if row else None
            )
        self._reconcile_enhancing_tiles(running)

    def _reconcile_enhancing_tiles(self, running):
        """Stream each running enhance onto the tile of the image it is enhancing.

        Which image a job targets is worked out only when the set of running
        enhances changes, not on every streamed frame: the match walks every
        image row, and the frames arrive several times a second.

        A frame goes only to a job actually rendering, for the reason
        :meth:`_pending_enhancement_for` spells out — a batch shares one folder
        and so one frame slot, and lending it to the ones queued behind would
        show each of those tiles a picture of a different image.
        """
        signature = tuple(sorted(
            (key, job.params.get("input_image") or "") for key, job in running
        ))
        if signature != self._enhancing_signature:
            self._enhancing_signature = signature
            self._enhancing_by_prompt = {
                row["prompt_id"]: (key, job)
                for key, job in running
                for row in self._image_rows
                if gallery.enhance_targets_row(job.params.get("input_image"), row)
            }
        self._browser.show_enhancing({
            prompt_id: (self._enhance_frames.get(key)
                        if job.state == "running" else None)
            for prompt_id, (key, job) in self._enhancing_by_prompt.items()
        })

    def _pending_enhancement_for(self, row: dict, running) -> tuple | None:
        """``(status, frame, settings)`` of a standalone enhance running on
        ``row``'s own image, or ``None``.

        The settings ride along so the live tile can name what is being made the
        way a finished level names what made it — the panel may have moved on
        since the run was launched, so the job's own params are the only honest
        answer.

        The frame goes only to a job actually rendering. :attr:`_enhance_frames`
        holds one frame per folder, and a batch of enhances shares a folder — so
        the frame there belongs to whichever of them ComfyUI is running, and
        lending it to the ones queued behind would show each of them a picture of
        a different image. Queued, the tile says so instead."""
        for key, job in running:
            if gallery.enhance_targets_row(job.params.get("input_image"), row):
                frame = self._enhance_frames.get(key) if job.state == "running" else None
                return (job.state, frame, gallery.describe_enhance_params(job.params))
        return None

    def _auto_enhance_if_wanted(self, row: dict | None):
        """Enhance a just-finished image while the Auto box is on.

        The subpanel's standing instruction, app-wide: with it ticked the app
        turns out finished images rather than raw ones, without pressing Enhance
        All after every run. The gate is Enhance All's own —
        :func:`~origenerator.gallery.enhance.rows_awaiting_enhancement` — so a
        video, an already-enhanced image (inline or folded), and an image whose
        enhance is still cooking are all passed over. That last part is what
        stops the loop: the enhance this queues folds back onto the row it came
        from and arrives here already enhanced."""
        if row is None or not self._enhance_settings.auto:
            return
        awaiting = gallery.rows_awaiting_enhancement([row], self._db.list_generations())
        if awaiting:
            self._enqueue_enhancements(awaiting)

    def _start_slideshow(self):
        """Open what's on screen — a folder, or the Recents/Starred shelf — as a
        fullscreen slideshow, shuffled and running at the app-wide pace."""
        items = self._slideshow_items(self._slideshow_rows())
        if not items:
            return
        show = self._open_slideshow(items)
        logger.info("Slideshow of %s: %d items, shuffled order[:10]=%s",
                    self._slideshow_subject(), len(items),
                    show._playlist.order[:10])

    def _on_slideshow_closed(self):
        """The show was dismissed (however): let it go and hand the OSR2 back to
        whatever the toggle was driving. The mic is untouched — it answers to its
        own button, and "start slideshow" has to still be heard now there is no
        show to hear it over."""
        self._slideshow = None
        self._reconcile_osr2()

    def _slideshow_items(self, rows) -> list:
        """(path, media_type, prompt_id, thumbnail) for each of ``rows``, in the
        order given — the slideshow's playlist. The thumbnail is what the view
        draws for the item while it's a neighbor rather than the one on screen (a
        video has no other still).

        A row with no file is left out, whether it never got one or is still
        being made: a slide with nothing to look at is a gap between pictures,
        and one still cooking joins the running show the moment it lands (see
        :meth:`_feed_slideshow_finished`)."""
        items = []
        for row in rows:
            resolved = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
            if resolved is None:
                continue  # nothing to look at yet, or ever
            items.append((resolved[0], resolved[1], row["prompt_id"],
                          row.get("thumbnail_path")))
        return items

    def _feed_slideshow_finished(self, row: dict | None):
        """A generation landed: it joins an open slideshow if that show would be
        playing it had it opened now.

        Which is the whole point of watching a folder that is auto-generating —
        the playlist is otherwise the fixed set the show opened with, so the
        items the loop makes while it runs are exactly the ones it never reaches.
        Asked of the rows on screen rather than of a folder key remembered at
        open time, so a shelf's show and a parent folder's answer it the same way
        their tiles would.
        """
        if self._slideshow is None or row is None:
            return
        if not any(r["prompt_id"] == row["prompt_id"] for r in self._slideshow_rows()):
            return
        for item in self._slideshow_items([row]):
            self._slideshow.note_added(*item)

    def _open_from_slideshow(self, prompt_id: str):
        """Enter in a slideshow: land in the item's own folder with it selected —
        the same jump a shelf tile's double-click makes. The slideshow has already
        closed itself, so this arrives on the gallery."""
        self._slideshow = None
        self._browser.open_in_containing_folder(prompt_id)

    def _star_generation(self, prompt_id: str):
        """Bookmark a generation from a fullscreen show (its Down key) — the same
        star the gallery's own control sets."""
        self.set_items_starred([prompt_id], True)

    def _trash_generation(self, prompt_id: str):
        """Trash a generation condemned from a slideshow (its Up key) — the same
        undoable delete as anywhere else.

        An unreviewed experiment is rejected instead of deleted: the Experiments
        shelf plays as a slideshow, so Up there is the shelf's own Reject, and
        that keeps the row whose params the policy learns to steer away from.

        An item already in the bin has no row to delete, so Up does nothing over
        the Trash shelf's slideshow. Deliberate: the only delete left there is the
        permanent one, and that is not a thing to do on a keystroke — it is asked
        for from the tile, and confirmed.
        """
        row = self._db.get_generation(prompt_id)
        if row is None:
            return
        if gallery.unreviewed_experiments([row]):
            self._actions.reject_experiment(row)
            self._sync_undo_button()
        else:
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

    def _on_generation_drag_started(self, prompt_id: str):
        """A generation began dragging — from a browser thumbnail or a generate tab's
        preview: light the combine slot it fits, so the drop target is obvious from
        the very start of the gesture."""
        self._combine.show_drop_candidates(prompt_id)

    def _on_generation_drag_ended(self):
        self._combine.clear_drop_candidates()

    def _combined_params(self, image_id: str, video_id: str):
        """The ``(workflow, params, video_row, image_row)`` for re-running
        ``video_id``'s recipe on ``image_id`` — the video's workflow, settings and
        seed with only the input image swapped to the dropped one.

        ``None`` when the pair can't be combined: either row is gone, the video
        isn't a rebuildable image-conditioned recipe, or the image has no output
        file to seed from. Shared by the Generate and Open-in-generator paths.
        """
        image_row = self._db.get_generation(image_id)
        video_row = self._db.get_generation(video_id)
        if not image_row or not video_row:
            return None
        workflow_name = video_row.get("workflow_name") or ""
        workflow = WORKFLOW_REGISTRY.get(workflow_name)
        if workflow is None or not gallery.is_image_conditioned(workflow_name):
            return None  # the video must be a rebuildable, image-conditioned recipe
        params = gallery.combined_params(video_row, image_row, workflow)
        if params is None:
            return None  # the dropped image has no output file to seed from
        return workflow, params, video_row, image_row

    def _open_combination(self, image_id: str, video_id: str):
        """Open a dropped image + video's recipe as an editable generate tab instead
        of running it — the combine panel's "Open in generator" path. The tab is
        prefilled with the same combination Generate would launch, ready to tweak."""
        built = self._combined_params(image_id, video_id)
        if built is None:
            return
        workflow, params, _video_row, _image_row = built
        self._info_tabs.open_config(workflow.name, params)

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
        built = self._combined_params(image_id, video_id)
        if built is None:
            return
        workflow, params, video_row, image_row = built
        # The frame is re-buildable independently of the video seed, so the key —
        # which groups by the image's config, not its filename — is the same one
        # whether we re-roll the seed, the frame, or both. The prospective row is
        # stamped with the CURRENT workflow version (what the launched run will
        # record), not the recipe video's stored one: the settings key folds the
        # version in, and keying by an old recipe's version would park the reveal
        # on a folder the finished row never joins.
        key = gallery.settings_folder_key(
            {**dict(video_row), "params_json": json.dumps(params),
             "workflow_version": workflow.version},
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

    def _resolve_category(self, image_id: str, category: str) -> str | None:
        """The recipe (a rebuildable video's ``prompt_id``) that fits ``category`` for
        the dropped image — the category dropdown's counterpart to a dropped video.

        The local LLM picks the recipe whose starting scene matches this image's
        situation (:func:`recipe_match.smart_recipe`); if it's unreachable or finds no
        fit, it falls back to the act's most-used recipe
        (:func:`recipe_match.best_recipe`). Returns ``None`` — with a hint — when the
        gallery holds no video of the act, so a click never silently does nothing.
        """
        image_row = self._db.get_generation(image_id)
        if image_row is None:
            return None
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
        return video_id

    def _curated_combination(self, image_id: str, category: str):
        """The ``(workflow, params)`` for ``category``'s overlay-curated recipe on
        the dropped image — the pinned setup that outranks mining (see
        :func:`recipe_match.curated_recipe`), its seeds freshly rolled.

        ``None`` sends the caller on to mining: the act has no curated entry, the
        entry names an unknown or non-image-conditioned workflow, or the image
        row is gone or has no output file to seed from.
        """
        spec = recipe_match.curated_recipe(category)
        if spec is None:
            return None
        workflow = WORKFLOW_REGISTRY.get(spec.get("workflow") or "")
        if workflow is None or not gallery.is_image_conditioned(workflow.name):
            logger.warning("combine: category=%s curated workflow %r not usable",
                           category, spec.get("workflow"))
            return None
        image_row = self._db.get_generation(image_id)
        if image_row is None:
            return None
        params = gallery.curated_params(spec, image_row, workflow)
        if params is None:
            return None
        return workflow, params

    def _generate_curated(self, image_id: str, category: str) -> bool:
        """Launch ``category``'s curated recipe on the dropped image; ``False``
        when the act has no usable curated entry, so the caller falls back to
        mining. No reproduce warning: the seeds are fresh every launch."""
        built = self._curated_combination(image_id, category)
        if built is None:
            return False
        workflow, params = built
        logger.info("combine: category=%s image=%s -> curated recipe", category, image_id)
        key = gallery.settings_folder_key(
            {"workflow_name": workflow.name, "workflow_version": workflow.version,
             "params_json": json.dumps(params)},
            gallery.build_image_config_index(self._image_rows),
        )
        if self._reroll.start_prepared(key, workflow, params):
            self._reveal_combination(key)
        return True

    def _generate_category(self, image_id: str, category: str):
        """Run the recipe that fits ``category`` on the dropped image: the
        overlay's curated recipe when one is pinned for the act, else the mined
        exemplar handed off to the shared combine launch."""
        if self._generate_curated(image_id, category):
            return
        video_id = self._resolve_category(image_id, category)
        if video_id is not None:
            self._generate_combination(image_id, video_id)

    def _open_category(self, image_id: str, category: str):
        """Open the recipe that fits ``category`` as an editable generate tab — the
        Open-in-generator counterpart to :meth:`_generate_category`, honoring the
        same curated-over-mined order."""
        built = self._curated_combination(image_id, category)
        if built is not None:
            workflow, params = built
            self._info_tabs.open_config(workflow.name, params)
            return
        video_id = self._resolve_category(image_id, category)
        if video_id is not None:
            self._open_combination(image_id, video_id)

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
        self._shown_wait_note = self._wait_note(key)
        self._info_tabs.show_reroll_frame(self._last_reroll_frame, self._shown_wait_note)

    def _wait_note(self, key: str) -> str | None:
        """What re-roll ``key`` is waiting on, when another app is holding ComfyUI
        in front of it — the pane's wait text, in place of a bare 'waiting for
        preview'. Its own folder's queue isn't a wait worth naming."""
        job = self._reroll_jobs.get(key)
        return queue_wait_text(job.foreign_ahead) if job is not None else None

    def _refresh_wait_note(self):
        """Keep that wait text current between rebuilds. The count falls as the
        queue drains, and a pane frozen on a stale number is the mystery this is
        here to end. Only while the selected run has streamed no frame — once it
        has, the frame itself is the answer."""
        key = self._selected_reroll_key
        if key is None or self._last_reroll_frame is not None:
            return
        note = self._wait_note(key)
        if note != self._shown_wait_note:
            self._shown_wait_note = note
            self._info_tabs.show_reroll_frame(None, note)

    def _on_reroll_preview(self, key: str, data: bytes):
        """Mirror a re-roll's live frame into the info pane while it's selected,
        remembering it so it survives the rebuild each stage completion triggers."""
        if key == self._selected_reroll_key:
            self._last_reroll_frame = data
            self._info_tabs.show_reroll_frame(data)
        # An enhance's frames go to the version strip of whichever tab shows the
        # image being enhanced, not to the pane — an enhancement isn't a
        # generation taking the preview over.
        self._enhance_frames[key] = data
        self._reconcile_pending_enhancements()

    def _clear_reroll_selection(self):
        """Stop treating a running re-roll as the info-pane source — a real
        generation is taking over the pane, or the re-roll has ended."""
        self._selected_reroll_key = None
        self._last_reroll_frame = None
        self._shown_wait_note = None
        if self._reroll_tile is not None:
            self._reroll_tile.set_selected(False)

    def reconnect_running_rerolls(self):
        """Rebind live jobs to any re-rolls left running by a previous session, so
        each shows live progress and records its completion again. Called once at
        startup; a tab's Generate is itself a re-roll, so every still-running row is
        the re-roll controller's to reconnect."""
        self._reroll.reconnect_running()

    def _cancel_reroll(self, key: str):
        """The live tile's Cancel: drop the variation it leads with.

        An auto loop survives it and launches the next seed at once — cancel
        discards the run, only the Auto toggle stops the loop. Told *after* the
        drop, so the relaunch doesn't see the job it is replacing and no-op.
        """
        self._drop_reroll(key)
        self._auto.note_canceled(key)

    def _drop_reroll(self, key: str):
        """Cancel the re-roll leading a folder and redraw without it."""
        self._reroll.cancel(key)
        self._after_a_job_left(key)

    def _cancel_job(self, prompt_id: str):
        """Stop one named run — a queue row's Cancel, and a config tab's.

        A folder can hold several runs at once, so the one to stop is named rather
        than inferred from its folder; the redraw afterwards is the same. An auto
        loop in that folder takes it as a discarded seed and launches the next —
        after the drop, and a no-op while another of the folder's runs is still
        alive (:meth:`_start_reroll`), so the loop never doubles up.
        """
        job = self._reroll.job_for_prompt(prompt_id)
        key = next((k for k, jobs in self._reroll.jobs_by_folder.items()
                    if job in jobs), None)
        self._reroll.cancel_job(prompt_id)
        if key is not None:
            self._after_a_job_left(key)
            self._auto.note_canceled(key)

    def _after_a_job_left(self, key: str):
        """Redraw the folder a run has just been taken out of."""
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()  # a tab's run may have stopped

    def _abandon_reroll_preview(self, key: str):
        """Empty the info pane if it was mirroring a re-roll that has ended with no
        result to show (cancelled or failed)."""
        if key == self._selected_reroll_key:
            self._close_live_fullscreen()
            self._clear_reroll_selection()
            self._clear_metadata()

    def _close_live_fullscreen(self):
        """Dismiss a show that was watching a generation which ended with
        nothing to show — left up, it would sit on a stale partial frame forever."""
        show = self._slideshow
        if show is not None and show.is_live():
            show.close()

    def _on_reroll_finished(self, key: str, prompt_id: str):
        """A re-roll saved its result (finalized by the controller): drop it as the
        info-pane source, rebuild so it shows as a normal thumbnail, and load it into
        the front tab so a Generate ends on its finished output, not the placeholder."""
        finished_row = self._db.get_generation(prompt_id)
        if finished_row is not None and finished_row.get("source") == "experiment":
            # A background experiment landed: it waits on the Experiments shelf
            # for review rather than moving the user's view — no front-tab load,
            # no slideshow feed, no auto-loop or combine bookkeeping.
            self.refresh()
            return
        if finished_row is not None \
                and finished_row.get("workflow_name") == gallery.ENHANCE_WORKFLOW:
            # A standalone enhance is an upgrade, not a generation: fold its
            # output onto the image it enhanced — same row, same folder, same
            # star, now wearing the enhanced pixels and badge — and let the
            # upgraded image be what the front tab shows.
            source_id = gallery.fold_enhancement(self._db, finished_row)
            if source_id is not None:
                finished_row = self._db.get_generation(source_id)
                # A slideshow that asked for this one swaps the slide for it.
                self._feed_slideshow_enhanced(finished_row)
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()  # refresh re-selects it as a finished thumbnail
        self.refresh()
        self._feed_slideshow_finished(finished_row)  # a show of its folder gains it
        self._show_reroll_result_in_tab(finished_row)
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
        self._enhance_frames.pop(key, None)   # this run's frames are spent
        self._reconcile_generating()  # the run ended: the front tab drops its Cancel
        self._auto.note_finished(key)  # if auto-looping this folder, launch the next
        self._auto_enhance_if_wanted(finished_row)  # while the Auto switch is on
        self._sync_enhance_all_button()  # a landed enhance may retire the button
        self._reconcile_pending_enhancements()  # the live tile gives way to the level

    def _show_reroll_result_in_tab(self, finished_row: dict | None):
        """After a re-roll finishes, load its result into the front config tab.

        The finished row is handed over directly rather than resolved through the
        folder the job was keyed under: a re-roll of an old-generation folder
        lands its result in the current generation's folder (the settings key
        folds the workflow version in), so the job's key can name a folder whose
        newest row is not this result. Loading it leaves the tab showing the
        finished image/video and its footer — the completed end-state of a
        Generate — instead of the live-frame placeholder it held while running."""
        if finished_row is not None and gallery.produced_output(finished_row):
            self._info_tabs.show_result_in_current_tab(finished_row, self._image_rows)

    def _on_reroll_failed(self, key: str):
        """A re-roll failed (recorded by the controller): release the info pane if
        it was showing this one, and redraw the folder without its tile."""
        self._auto.note_failed(key)  # end the loop rather than spin on a broken workflow
        self._enhance_frames.pop(key, None)
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()  # the run ended: the front tab drops its Cancel
        self._reconcile_pending_enhancements()  # nothing is cooking for it now

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

    def _recents_media_types(self) -> set[str]:
        """The media types the Recents shelf's checkboxes currently include —
        the filter :func:`gallery.recent_generations` and the in-flight cards honor.
        Both on (the default) means every type; both off means none."""
        types = set()
        if self._recents_image_cb.isChecked():
            types.add("image")
        if self._recents_video_cb.isChecked():
            types.add("video")
        return types

    def _on_recents_filter_changed(self, _checked=False):
        """A media-type checkbox toggled: re-list the shelf under the new filter.
        Lightweight — re-derives the recent rows and redraws, with no tree rebuild."""
        self._browser.set_recent_rows(gallery.recent_generations(
            self._db.list_generations(), self._recents_media_types()
        ))
        self._sync_slideshow_button()  # a filter that empties the shelf retires it

    def _drill_into(self, key: str):
        self._browser._drill_into(key)

    def _thumbnail_double_clicked(self, prompt_id: str):
        self._browser._thumbnail_double_clicked(prompt_id)

    def _on_inflight_clicked(self, key: str):
        self._browser._on_inflight_clicked(key)

    def _inflight_items(self) -> list:
        return self._browser._inflight_items()

    def _update_queue(self):
        """Feed the bottom strip every in-flight job, in the order ComfyUI will
        work through them, plus whatever another app has on ComfyUI — so the whole
        queue shows from anywhere, and one that isn't ours is visible before
        Generate rather than after."""
        self._queue.set_items(self._inflight_items(), self._foreign_queue.total)

    def _refresh_foreign_queue(self):
        """Re-read what another app has on the shared ComfyUI.

        Read whether or not anything of ours is in flight: the point is to see a
        queue full of somebody else's work *before* pressing Generate, instead of
        learning about it from a submit that reports six jobs ahead of it out of
        nowhere. ComfyUI outlives every app that queues on it, so that backlog can
        be a branch preview's background experiments that outlived the preview.
        """
        if self._client is None:
            return
        try:
            self._foreign_queue = self._client.foreign_queue()
        except Exception as e:
            # Unreadable (server down, wedged, restarting): claim nothing rather
            # than leave a stale count on screen offering to clear a queue we
            # can no longer see.
            logger.debug("Could not read ComfyUI's queue: %s", e)
            self._foreign_queue = ForeignQueue(running=[], pending=[])

    def _clear_foreign_queue(self):
        """Wipe another app's work off ComfyUI, on the user's say-so.

        The shared server accumulates jobs no window here can account for — a
        branch preview's absence experiments outlive the preview that queued
        them, and the live app cancels only the experiments its own database
        records — so until now they could only be waited out. Only theirs go: the
        user's own queue is what they asked for, and each of those has its own ✕.
        """
        if self._client is None:
            return
        total = self._foreign_queue.total
        if not total or not self._confirm_clear_queue(total):
            return
        try:
            dropped = self._client.clear_foreign_queue()
        except Exception as e:
            logger.exception("Failed to clear ComfyUI's queue")
            QMessageBox.warning(
                self, "Could not clear the queue",
                f"ComfyUI would not drop the other app's jobs:\n\n{e}",
            )
            return
        logger.info("Dropped %d job(s) another app had queued on ComfyUI", dropped)
        self._refresh_foreign_queue()
        self._update_queue()  # the strip goes blank now rather than a poll later

    def _confirm_clear_queue(self, total: int) -> bool:
        """Ask before dropping it: the jobs are somebody's work, and one of them
        may be part-rendered. Spelled out, since the button sits beside a caption
        that is often the user's own running job."""
        reply = QMessageBox.question(
            self, "Clear ComfyUI's queue",
            f"Drop the {total} job{'' if total == 1 else 's'} another app has"
            " queued on ComfyUI?\n\nAnything you queued from here is left alone;"
            " one of theirs already running is interrupted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

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

    def set_items_starred(self, prompt_ids, starred: bool):
        """Star or unstar the given generations, then rebuild so their tiles pick
        up (or drop) the corner star — mirroring how a folder star refreshes."""
        for pid in prompt_ids:
            self._db.set_generation_starred(pid, starred)
        self.refresh()

    def _delete_selection(self):
        """Delete picked thumbnails, or the current folder if none are picked.

        On the Trash shelf the picked items are already deleted, so Delete means
        the only deletion left: ending them for good. Same button, same key, the
        one meaning it can have where it is standing — rather than a control that
        looks live and quietly does nothing.
        """
        if self._browser.showing_trash():
            self.purge_from_trash(self.selected_prompt_ids())
            return
        if self._browser.selected_ids:
            rows = [self._db.get_generation(pid) for pid in self.selected_prompt_ids()]
            self._delete_rows([r for r in rows if r])
            return
        group = self._current_deletable_folder()
        if group is not None:
            self._delete_folder(group)

    # --- the Trash shelf: restoring a delete, or ending it -------------------

    def _bin_records(self) -> list[dict]:
        """The held deletions the Trash shelf offers — every one in the live app,
        and in a preview only the ones that hold no files.

        That reduces, in a preview, to the deletes it made itself. Its database
        is a copy, so it inherits the live install's held deletions, and every
        path in those points into the live install's trash: restoring one would
        move the live app's files out from under rows it is still showing, and
        purging one would take its only copies. A preview's own delete takes no
        files at all (see :func:`~origenerator.branch_session.session_trash`), so
        it holds nothing that isn't already the copy's — putting one back only
        re-inserts the row, and ending one only forgets it. Which is what leaves
        the shelf usable for judging it, rather than a wall saying come back to
        the live app.
        """
        records = self._db.list_deletions()
        if not is_branch_session():
            return records
        return [r for r in records if not (r.get("batch") or {}).get("moves")]

    def _on_trash_action(self, prompt_id: str, action_id: str):
        """A Trash tile's hover control: restore this item, or end it now."""
        if action_id == "restore":
            self.restore_from_trash([prompt_id])
        else:
            self.purge_from_trash([prompt_id])

    def restore_from_trash(self, prompt_ids):
        """Bring deleted items back — files to where they were, rows to the
        gallery — and land on one of them in its own folder, so a restore ends
        with the thing you recovered in front of you rather than on the shelf it
        just left."""
        if not prompt_ids:
            return
        try:
            restored = self._actions.restore_deleted(prompt_ids)
        except Exception as e:
            logger.exception("Failed to restore %d deleted item(s)", len(prompt_ids))
            QMessageBox.warning(
                self, "Restore failed",
                f"Could not restore the selected item(s):\n\n{e}",
            )
            return
        self._browser.clear_selection()
        self.refresh()
        if restored and restored in self._leaf_by_id:
            self._show_generation(restored)

    def purge_from_trash(self, prompt_ids):
        """End deleted items now instead of waiting out their window. Confirmed
        first, and pointedly: this is the one action in the gallery with no undo
        and no second copy behind it."""
        if not prompt_ids:
            return
        count = len(prompt_ids)
        plural = "s" if count != 1 else ""
        if not self._confirm(
            f"Permanently delete {count} item{plural}? This cannot be undone."
        ):
            return
        try:
            self._actions.purge_deleted(prompt_ids)
        except Exception as e:
            logger.exception("Failed to permanently delete %d item(s)", count)
            QMessageBox.warning(
                self, "Delete failed",
                f"Could not permanently delete the selected item(s):\n\n{e}",
            )
            return
        self._browser.clear_selection()
        self.refresh()

    def _current_deletable_folder(self):
        """The folder on screen if it may be deleted, else ``None`` — which covers
        a multi-selection: its unsaved folder isn't deletable, so Delete stays dark
        rather than quietly wiping whichever one row happens to be current."""
        group = self._current_group()
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

    def _release_held_media(self, paths):
        """Drop every on-screen view of ``paths`` — the files a delete is about to
        move — so nothing in this app is still holding one open.

        Wired into :class:`GalleryActions` itself, so it runs for every delete
        there is: a picked tile, a whole folder, a rejected experiment, a
        slideshow's Up key. Windows won't move a file while any handle on it is
        open, and a video preview holds one for as long as it's loaded — so an
        item still showing anywhere blocks its own deletion. Panes showing
        something else keep it.
        """
        self._info_tabs.release_media(paths)
        if self._slideshow is not None:
            self._slideshow.release_media(paths)

    def _cancel_enhancements_of(self, rows):
        """Stop every standalone enhance still being made of ``rows`` — the items
        a delete is about to take.

        Wired into :class:`GalleryActions` beside the media release, so it runs
        for every delete there is: a picked tile, a whole folder, a rejected
        experiment, a slideshow's Up key. The jobs are the gallery's, so the
        match is made here — the same "is this run an enhance of this image?"
        question :meth:`is_enhancing` asks, over every live job of every folder
        (a batch of enhances shares one settings key, so all but its leader
        would be missed by the folder-facing view).

        Cancelling frees the queue — a video-length wait can sit behind an
        enhance nobody wants any more — and takes the run's transient row with
        it, so no enhanced file lands with no original to be a version of.
        """
        doomed = [row for row in rows if row]
        for job in list(self._reroll.all_jobs):
            if job.workflow.name != gallery.ENHANCE_WORKFLOW:
                continue
            source = job.params.get("input_image")
            if any(gallery.enhance_targets_row(source, row) for row in doomed):
                logger.info("Cancelling the enhance of %s: its image is being deleted",
                            source)
                self._reroll.cancel_job(job.prompt_id)

    def _delete_rows(self, rows):
        if not rows:
            return
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
        global_pos = self._tree.viewport().mapToGlobal(pos)
        item = self._tree.itemAt(pos)
        if item is None:
            self._empty_tree_context_menu(global_pos)
            return
        # Right-clicking inside a multi-selection offers what to do with the whole
        # set; right-clicking outside it is about the one row under the cursor.
        if self._selection_group is not None:
            group = item.data(0, _GROUP_ROLE)
            if group is not None and any(
                m.key == group.key for m in gallery.child_groups(self._selection_group)
            ):
                self._selection_context_menu(global_pos)
                return
        group = item.data(0, _GROUP_ROLE)
        if group is not None:
            self._folder_context_menu(group.key, global_pos)

    def _empty_tree_context_menu(self, global_pos: QPoint):
        """Below the last row there is no folder to act on, so the only thing on
        offer is starting a new folder of your own."""
        menu = QMenu(self)
        new_action = menu.addAction("New folder…")
        if menu.exec(global_pos) == new_action:
            self._new_custom_folder()

    def _selection_context_menu(self, global_pos: QPoint):
        """The picked folders as a set: save them as a folder of your own."""
        count = len(gallery.child_groups(self._selection_group))
        menu = QMenu(self)
        group_action = menu.addAction(f"Group {count} folders into a new folder…")
        if menu.exec(global_pos) == group_action:
            self._group_selection()

    def _folder_context_menu(self, key: str, global_pos: QPoint):
        item = self._item_by_key.get(key)
        if item is None:
            return
        group = item.data(0, _GROUP_ROLE)
        if isinstance(group, gallery.CustomGroup):
            self._custom_folder_context_menu(group, global_pos)
            return
        menu = QMenu(self)
        rename_action = menu.addAction("Rename…")
        star_action = menu.addAction("Unstar" if group.starred else "Star")
        # Inside a folder the user made, a member tile can also be dropped from it.
        # Right-clicking the same folder in the tree offers nothing of the sort —
        # it isn't in any grouping from there.
        open_custom = self._current_group()
        remove_action = None
        if isinstance(open_custom, gallery.CustomGroup) and open_custom.folder_id is not None \
                and any(m.key == key for m in gallery.child_groups(open_custom)):
            remove_action = menu.addAction(f"Remove from “{open_custom.label}”")
        add_menu = self._add_to_folder_menu(menu, key)
        delete_action = None
        if _is_deletable_folder(group):
            menu.addSeparator()
            delete_action = menu.addAction("Delete folder…")
        chosen = menu.exec(global_pos)
        if chosen == rename_action:
            self._rename_folder(key)
        elif chosen == star_action:
            self._toggle_star(key)
        elif remove_action is not None and chosen == remove_action:
            self._remove_from_custom_folder(open_custom, key)
        elif chosen in add_menu:
            self._on_folders_dropped(add_menu[chosen], [key])
        elif delete_action is not None and chosen == delete_action:
            self._delete_folder(group)

    def _add_to_folder_menu(self, menu: QMenu, key: str) -> dict:
        """An "Add to" sub-menu naming each of the user's folders — the menu route
        to what a drag onto its row does, for when dragging is awkward (a long tree,
        a folder scrolled out of sight). Returns ``{action: custom folder key}``,
        empty when there are no folders of the user's own yet."""
        targets = [f for f in self._custom_folders
                   if not any(m.key == key for m in gallery.child_groups(f))]
        if not targets:
            return {}
        submenu = menu.addMenu("Add to folder")
        return {submenu.addAction(folder.label): folder.key for folder in targets}

    def _custom_folder_context_menu(self, group, global_pos: QPoint):
        """A folder the user made: rename it, or remove the grouping. It has no
        star (a bookmark of a bookmark shelf collects nothing) and no delete —
        removing it must never touch the generations it gathers."""
        menu = QMenu(self)
        rename_action = menu.addAction("Rename…")
        menu.addSeparator()
        remove_action = menu.addAction("Remove folder…")
        chosen = menu.exec(global_pos)
        if chosen == rename_action:
            self._rename_folder(group.key)
        elif chosen == remove_action:
            self._remove_custom_folder(group)

    def _rename_folder(self, key: str):
        item = self._item_by_key.get(key)
        current = item.data(0, _GROUP_ROLE).label if item else ""
        # A derived folder's name is an overlay over the one its settings produce,
        # so blank resets it; a custom folder's name is all it has, so it can't.
        prompt = ("Folder name:" if gallery.is_custom_key(key)
                  else "Folder name (blank to reset):")
        text, ok = QInputDialog.getText(self, "Rename Folder", prompt, text=current)
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
        """Double-clicking the title bar edits the selected folder's name — but not
        while several are picked, where the title is a count of them and the rename
        would land on whichever one happened to be current."""
        if self._selection_group is not None:
            return
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

    def _row_for(self, prompt_id: str) -> dict | None:
        """The generation behind a tile: the gallery's own row, else a held
        deletion's.

        A deleted item's row is out of the ``generations`` table — that is what
        deleting is — but the recovery bin kept it whole, and its files are all
        still there in the trash. So a Trash tile is a generation like any other
        to look at: it previews, it plays, it opens full size, it fills a config
        tab with the settings that made it. Only the actions that would change it
        are gone (it has no folder, no star, no enhance), and those already ask
        the database directly rather than coming through here.
        """
        row = self._db.get_generation(prompt_id)
        if row:
            return row
        return next((r for r in self._held_rows if r["prompt_id"] == prompt_id), None)

    def _on_thumbnail_clicked(self, prompt_id: str):
        row = self._row_for(prompt_id)
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
                gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR), prompt_id
            )
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
        """Follow a link to another generation — a video's source image, an image's
        animation, a "Go to folder". Opens the target's folder and lands on the
        item itself: previewed, its tile picked and scrolled into view, so which of
        the folder's items the link meant is visible rather than guessed at."""
        self._show_generation(prompt_id)
        self._record_visit(prompt_id)
        # After the navigation, which renders the folder's tiles fresh.
        self._browser.reveal_tile(prompt_id)

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
        return key if key in _SHELF_KEYS else None

    def _current_location(self) -> str | None:
        """The history key for the view on screen — a shelf key on a shelf, the
        selected generation's id in a folder, else the open folder's own key
        (``None`` with nothing open at all)."""
        return self._current_shelf_key() or (
            self._selected["prompt_id"] if self._selected else self._selected_folder_key()
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
        (Recents/Starred), a folder, or a generation in its folder."""
        if location in _SHELF_KEYS:
            self._return_to_shelf(location)
        elif location in self._item_by_key:
            self._return_to_folder(location)
        else:
            self._show_generation(location)

    def _return_to_folder(self, key: str):
        """Back/Forward onto a folder: open it without recording the move (so it
        doesn't pile back onto history)."""
        self._suppress_history = True
        try:
            self._tree.setCurrentItem(self._item_by_key[key])
        finally:
            self._suppress_history = False

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
        if self._browser.showing_trash():
            # Already deleted: the button's one remaining meaning is "for good",
            # and the tooltip has to say so before it's clicked.
            self._delete_btn.setEnabled(bool(count))
            self._delete_btn.setToolTip(
                f"Permanently delete {count} item{'s' if count != 1 else ''}"
                if count else "Pick an item to delete permanently"
            )
        elif count:
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

    def pin_config_tab(self):
        """Keep the front config tab — the double-click half of the pane's
        preview-tab rule. Relayed here because the browser owns the gesture and
        the info pane owns the tabs."""
        self._info_tabs.pin_current_tab()


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
