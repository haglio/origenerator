import json
import logging
import random
from typing import NamedTuple
from functools import partial

from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QScrollArea, QToolButton, QSplitter,
    QMenu, QInputDialog, QAbstractItemView, QMessageBox, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, QThreadPool, QTimer, QPoint, QSize, pyqtSignal

from origenerator import (
    evolver_export, gallery, prompt_edit, recipe_match, recovery, search, timing,
)
from origenerator.gui import icons
from origenerator.branch_session import is_branch_session, session_trash
from origenerator.comfyui_client import ComfyUIClient, ForeignQueue
from origenerator.config import (
    AMBIENT_AUDIO_VOICES, COMFYUI_OUTPUT_DIR, EVOLVER_INBOX_DIR, GENAU_SOURCE,
    STATE_DIR, THUMB_DIR,
    LOCAL_LLM_BASE_URL, LOCAL_LLM_MODEL, VIDEO_SCENE_MATCH_SYSTEM_PROMPT,
    VOICE_REQUEST_MATCH_SYSTEM_PROMPT,
)
from origenerator.db import Database
from origenerator.base_backfill import TARGET_KEY as BASE_RENDER_TARGET_KEY
from origenerator.base_backfill import queue_base_renders
from origenerator.experiments.background import queue_experiments
from origenerator.experiments.policy import ExperimentPolicy
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import (
    filled_params, randomize_seeds, would_reproduce_a_completed_run,
)
from origenerator.gui.ambient_audio import AmbientAudio
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.enhance_panel import EnhancePanel
from origenerator.gui.find_bar import FindBar
from origenerator.gui.inflight import EnhancingRun
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tree import FolderTree
from origenerator.gui.prompt_find import PromptFind
from origenerator.gui.combine_panel import CombinePanel
from origenerator.gui.auto_generate_controller import AutoGenerateController
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.request_worker import RevisionWorker, ReviseTask
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.prompt_edit import apply_request
from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS, in_order
from origenerator.voice.dictation import COMPLETED, RequestDictation, request_bias
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
from origenerator.gui.off_thread import run_off_thread
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.osr2_driver import Osr2Driver
from origenerator.gui.osr2_stroke_driver import Osr2StrokeDriver
from origenerator.gui.scope_search_edit import ScopeSearchEdit
from origenerator.gui.search_expander import SearchExpander
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.stroke_hud import STROKE_KEY_LEGEND, apply_stroke_key
from origenerator.gui.stroke_panel import StrokePanel
from origenerator.gui.generation_queue import GenerationQueue
from origenerator.gui.link_tip import LinkTip, link
from origenerator.gui.browser_pane import (
    BrowserPane, SEARCH_DRAW_LIMIT, SearchTile,
)
from origenerator.gui.gallery_tree import (
    GalleryTree,
    EXPERIMENTS_KEY as _EXPERIMENTS_KEY,
    EXPERIMENTS_LABEL as _EXPERIMENTS_LABEL,
    GROUP_ROLE as _GROUP_ROLE,
    RECENTS_KEY as _RECENTS_KEY,
    RECENTS_LABEL as _RECENTS_LABEL,
    REQUESTS_KEY as _REQUESTS_KEY,
    REQUESTS_LABEL as _REQUESTS_LABEL,
    STARRED_KEY as _STARRED_KEY,
    STARRED_LABEL as _STARRED_LABEL,
    TRASH_KEY as _TRASH_KEY,
    TRASH_LABEL as _TRASH_LABEL,
)
from origenerator.navigation import Location, NavigationHistory
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows import WORKFLOW_REGISTRY

ensure_shared_ui_on_path()
from shared_ui.check_box import CheckBox
from shared_ui.colors import BORDER_SUBTLE
from shared_ui.spacing import BUTTON_GAP, BUTTON_ICON, BUTTON_ROW_GAP

logger = logging.getLogger(__name__)

_POLL_INTERVAL_MS = 1500
_PANE_MARGINS = (8, 8, 8, 8)  # breathing room inside each of the three panes
# How long the search waits after the last keystroke before asking the local LLM
# to widen the query. Long enough to be a real pause rather than a gap between
# two characters — the table-widened results are already on screen throughout, so
# nothing is being waited *for*; this only decides how often the model is asked.
_SEARCH_EXPAND_DELAY_MS = 700
# How long the box waits after the last keystroke before searching at all. A
# search is cheap but not free — it scores the whole library and rebuilds the
# pane — and running one per character means the results churn under a word
# still being typed, which is unreadable however fast it is.
_SEARCH_DELAY_MS = 300
# Below this many characters nothing is searched. One or two letters match a
# large fraction of any library through sheer stemming, so an as-you-type search
# would answer the first keystroke of every query with most of the gallery.
_SEARCH_MIN_CHARS = 3
# The sort orders the results pane offers, as (label, mode) in menu order.
_SEARCH_SORTS = (("Recent", search.SORT_RECENT), ("Model / LoRA", search.SORT_RECIPE))
_TOOL_ICON_PX = BUTTON_ICON  # the family's icon size — see GalleryView._tool_button
_TOOLBAR_GROUP_GAP = 14  # the space that separates one group of the button bank from the next
# Said the same way by the button and by the settings panel it would run, because
# both go dark together the moment what's in front of you is a video.
_NO_VIDEO_ENHANCER = "Enhancement is for images — there is no video enhancer"
_ALREADY_AT_THESE_SETTINGS = (
    "Already enhanced at these settings — change one below to make another"
)
# The synthetic shelves, as back/forward history locations: each is a place the
# user can be standing, so a visit to one is recorded and restored by key rather
# than by the generation that happened to be picked there.
_SHELF_KEYS = (_RECENTS_KEY, _STARRED_KEY, _EXPERIMENTS_KEY, _REQUESTS_KEY,
               _TRASH_KEY)
# Their plain names, without the waiting-work counts their tree rows carry —
# what the search box and header call a shelf it is searching.
_SHELF_LABELS = {
    _RECENTS_KEY: _RECENTS_LABEL, _STARRED_KEY: _STARRED_LABEL,
    _EXPERIMENTS_KEY: _EXPERIMENTS_LABEL, _REQUESTS_KEY: _REQUESTS_LABEL,
    _TRASH_KEY: _TRASH_LABEL,
}


class _SearchScope(NamedTuple):
    """What a search covers: the selected row's breadcrumb and the generations it
    holds (``None`` for no restriction at all).

    The path rather than the folder's own name, everywhere it is said: a folder
    is named by a short code, so "Search 3A7F2C10…" names nothing the user can
    place, where the path they clicked down does.
    """

    path: str
    ids: set[str] | None
# What the lit Auto switch says while its loop runs in some other folder. It
# doesn't name that folder: a folder is named by a code, which tells you nothing
# about where it sits, so a name is no help in finding one. A link is.
_AUTO_ELSEWHERE_TIP = (
    "Auto-generate is running in another folder<br>"
    f"{link('auto', 'Go to it')} · click the switch to stop it"
)


def _is_reusable_workflow(workflow_name) -> bool:
    """Whether the app can rebuild this workflow from its template.

    The gate on the gallery re-roll: a re-roll re-runs a folder's own settings
    with a fresh seed, which needs a template to build the graph from.
    """
    return (workflow_name or "") in WORKFLOW_REGISTRY


def _toolbar_gap() -> QWidget:
    """The space between two groups of the button bank.

    Space alone is what separates them — a rule here used to, and in a bank that
    wraps onto a second row a rule can land at the end of one row or the start of
    the next, marking nothing. An empty widget rather than layout spacing because
    the gap comes and goes with the group behind it (see
    :meth:`GalleryView._sync_toolbar_gaps`), and a widget is the thing a flow
    layout can be told to leave out.
    """
    gap = QWidget()
    gap.setFixedSize(_TOOLBAR_GROUP_GAP, 1)
    return gap


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


# What a spoken command about the picture is asking for, in the words its "no
# picture on screen" answer names it by. A fix names its own part instead.
_VOICE_WANTS = {
    gallery.GENAU_COMMAND: "a Genau clip",
    gallery.ENHANCE_COMMAND: "an enhancement",
}


def _match_voice_command(text: str):
    """The one command an utterance is, or ``None`` — the whole spoken
    vocabulary, in the order it is tried.

    The show's own controls, then everything said about the picture on screen
    (:func:`~origenerator.gallery.voice_commands.match_command`, which owns that
    half's order). Each matcher is strict about its own shape and none can claim
    another's — a show command names the slideshow, a fix leads with "fix" — so
    the order only decides which is asked first. Everything unclaimed falls
    through to a prompt rewrite, which is why none of them may be loose.
    """
    return match_show_command(text) or gallery.match_command(text)


class GalleryView(QWidget):
    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryActions | None = None,
                 osr2_stroke: Osr2StrokeDriver | None = None,
                 ambient_audio: AmbientAudio | None = None,
                 search_expander: SearchExpander | None = None):
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
        # Guards the one reconcile that owns both drive sources: starting or
        # stopping the stroke is something it does, not something it reacts to.
        self._reconciling_osr2 = False
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
        self._auto = AutoGenerateController(self._start_auto_reroll)
        self._auto.stopped.connect(self._on_auto_stopped)
        # Auto-generate holds a mutable copy of a folder's params per active loop so
        # voice can steer the prompt mid-loop; turning Auto on is voice's "on" and
        # begins always-listening steering of the current folder.
        self._auto_working: dict = {}
        self._pending_auto_key: str | None = None  # a re-homed loop's folder to open once it exists
        # The runs the loop launched, by the id each began under. A loop is left
        # running while the user works, so what it makes is the gallery's, not any
        # tab's: no tab shows its frames or its result (see :meth:`_start_auto_reroll`).
        self._auto_origins: set[str] = set()
        # The matcher rides along so a spoken "fix teeth" or "start slideshow" is
        # executed as a command rather than steering a prompt; the dictation
        # collects "Request … over" across as many utterances as it takes. The
        # bias teaches whisper all three vocabularies, without which a quiet
        # mic's "fix <part>" — or the marker words the whole request hangs on —
        # transcribe as other words entirely.
        self._voice = VoiceSteering(
            command_matcher=_match_voice_command,
            dictation=RequestDictation(),
            transcribe_bias=(f"{gallery.command_bias()} {show_command_bias()} "
                             f"{request_bias()}"),
        )
        self._voice.error.connect(lambda msg: logger.warning("Voice steering: %s", msg))
        self._voice.heard.connect(self._on_voice_heard)
        self._voice.edited.connect(self._on_voice_edited)
        self._voice.error.connect(self._on_voice_error)
        self._voice.request.connect(self._on_spoken_request)
        # A finished request is worked out on the pool: the prompt may not
        # contain the words the speaker used ("no earrings" against a prompt
        # that says "silver ear studs"), and finding out which of its own terms
        # they meant is a call to the local LLM.
        self._revision = RevisionWorker(partial(
            apply_request,
            match=partial(prompt_edit.smart_match,
                          base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                          system_prompt=VOICE_REQUEST_MATCH_SYSTEM_PROMPT),
        ), parent=self)
        self._revision.revised.connect(self._on_request_revised)
        self._voice_target_key: str | None = None
        # The generation an open request is about, captured the moment the
        # request opens rather than when it finishes: a show holds still for the
        # sentence, but the words take seconds and the item on screen when they
        # end is not necessarily the one they were about.
        self._request_target: str | None = None
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
        self._live_ids: set[str] = set()  # the gallery's own rows, minus the trash
        # --- the gallery search (the box over the tree, the results in the middle
        # pane). The index is rebuilt with the gallery and queried on each
        # keystroke; the expander widens the query's words through the local LLM
        # once typing stops, and re-runs the search when its answer lands. Both
        # are built before _build_ui, whose box drives them.
        self._search = search.GallerySearch()
        self._search_query = ""       # what the box holds, stripped ("" = not searching)
        self._search_expansions = None  # the widening in force for that query, if any
        self._search_outcome = search.SearchOutcome((), ())
        self._search_tiles: list = []   # its hits as the pane draws them
        self._search_sort = search.SORT_RECENT
        self._search_collapsed: set[str] = set()  # recipe bands folded shut
        self._search_expander = search_expander or SearchExpander(self)
        self._search_expander.expanded.connect(self._on_search_expanded)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(_SEARCH_DELAY_MS)
        self._search_timer.timeout.connect(self._run_pending_search)
        self._search_expand_timer = QTimer(self)
        self._search_expand_timer.setSingleShot(True)
        self._search_expand_timer.setInterval(_SEARCH_EXPAND_DELAY_MS)
        self._search_expand_timer.timeout.connect(self._request_search_expansion)
        # The held deletions the Trash shelf lists, as gallery rows re-pointed at
        # their files in the trash — the rows behind everything a deleted item can
        # still do (see :meth:`_row_for`).
        self._held_rows: list[dict] = []
        self._selected_row: dict | None = None  # the saved generation on display in the info pane
        # The browser pane renders the middle column (tiles / thumbnails / shelves)
        # and owns the thumbnail multi-selection and in-flight cards.
        self._browser = BrowserPane(self)
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
        self._sync_history_buttons()
        self._sync_nav_buttons()
        self._sync_action_buttons()
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
                    # Ctrl+Shift+Z is the other direction, as everywhere else.
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        self._redo()
                    else:
                        self._undo()
                    return True
                # The OSR2 stroke keys work right here in the main window too —
                # not only in the fullscreen show — under the same guards that
                # keep them out of text fields and other windows.
                if (not event.modifiers()
                        and apply_stroke_key(self._osr2_stroke, event.key(),
                                             on_drive_toggle=self._toggle_osr2_drive)):
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
            # One switch, so one thing to turn off: untoggling stops whichever
            # source is on the device — a funscript drive or the stroke.
            self._osr2_btn.setChecked(False)
            handled = True
        elif self._osr2_stroke.active:
            self._osr2_stroke.stop()  # nothing else should own it, but say so anyway
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

        # The three panes live in splitters, so the divider between each doubles
        # as a drag handle: the TOC pane (folder tree), the browser pane (a
        # folder's contents), and the info pane (preview + metadata).
        #
        # Nested rather than flat, because the queue strip belongs to the first
        # two and not to the third: the tree and the browser sit side by side in
        # _folder_panes, the strip goes under both of them in _left_column, and
        # the info pane stands beside that whole column at full height. Its tabs
        # are where the user reads and edits a generation, and a strip cutting
        # across their foot would take that height for a queue they can already
        # see next to it.
        self._panes = QSplitter(Qt.Orientation.Horizontal)
        self._panes.setChildrenCollapsible(False)  # a pane can't be dragged shut
        self._panes.setHandleWidth(6)
        self._folder_panes = QSplitter(Qt.Orientation.Horizontal)
        self._folder_panes.setChildrenCollapsible(False)
        self._folder_panes.setHandleWidth(6)
        self._left_column = QSplitter(Qt.Orientation.Vertical)
        self._left_column.setChildrenCollapsible(False)  # the strip keeps its slot
        self._left_column.setHandleWidth(6)

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
        # The gallery search. It sits over the tree but no longer narrows it: what
        # it fills is the browser pane, with the matching generations themselves
        # (see :meth:`_run_search`), because a thumbnail is what the user
        # recognizes and a folder name — a short code — is not.
        # Matching is by meaning rather than by letters, so "two women" reaches
        # "a pair of dolls" and "two tall ladies" alike; a model name, a LoRA
        # name and a seed are searchable too. Its counterpart is the find strip below
        # the info pane, which searches *inside* the open tab's prompts.
        self._search_edit = ScopeSearchEdit()
        # Its placeholder names the scope — the whole path down to the selected
        # folder — and is kept current with the tree selection
        # (_sync_search_placeholder); this is only what it says before the first
        # selection lands.
        self._search_edit.set_scope(gallery.ALL_LABEL)
        self._search_edit.setToolTip(
            "Search every generation by what it is of — matching related words, "
            "not just the ones you typed — or by model, LoRA, seed, or a name "
            "you gave one of the folders holding it. The results "
            f"fill the middle pane; nothing is searched under {_SEARCH_MIN_CHARS} "
            "characters."
        )
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._on_search_changed)
        toc_box.addWidget(self._search_edit)
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
        # Switching lanes re-asks which acts are answerable: an act with plenty of
        # long-form video behind it may have no loop at all.
        self._combine.intent_changed.connect(self._on_combine_intent_changed)
        self._combine.setVisible(self._client is not None)
        toc_box.addWidget(self._combine)
        self._folder_panes.addWidget(toc)

        # Browser pane: a header (the folder's path, then a back/forward/undo
        # toolbar under it) over the flowing contents. Double-clicking the path
        # renames the folder it ends at.
        browser = QWidget()
        browser_box = QVBoxLayout(browser)
        browser_box.setContentsMargins(*_PANE_MARGINS)
        self._title = EditableHeader()
        self._title.edit_requested.connect(self._begin_title_rename)
        self._title.edited.connect(self._commit_title_rename)
        browser_box.addWidget(self._title)
        # The button bank, in five groups a space apart (see the assembly at
        # the end of this block): where you are, what you did, what to do with
        # what's in front of you, and what the app is doing on its own. Grouping
        # is what makes an icon-only bank readable — a button's neighbors say as
        # much about it as its glyph does.
        self._back_btn = self._tool_button(icons.back_icon(), "Back", self._go_back)
        self._forward_btn = self._tool_button(icons.forward_icon(), "Forward", self._go_forward)
        self._undo_btn = self._tool_button(icons.undo_icon(), "Undo", self._undo)
        self._redo_btn = self._tool_button(icons.redo_icon(), "Redo", self._redo)
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
        # Never hidden: a loop runs until it is stopped, and a switch that went
        # away with its folder left one running with nothing on screen to say so
        # (see _sync_auto_button). It greys instead when there is nothing to do.
        # While the loop is somewhere else, its tip is one you can click into —
        # naming that folder is no use when a name is a code with no branch
        # attached to it, so the tip offers to take the user there instead.
        self._auto_tip = LinkTip(self._auto_btn)
        self._auto_tip.link_activated.connect(self._go_to_looping_folder)
        # Star, enhance, delete: the three things you can do to what is in front
        # of you, each aimed the same way — the picked thumbnails, else the
        # folder on screen. Colored, and grouped, because they are one set: gold
        # for keep, green for make-better, red for take-away.
        self._star_btn = self._tool_button(
            icons.star_icon(filled=True), "Star", self._star_selection
        )
        self._enhance_btn = self._tool_button(
            icons.enhance_icon(), "Enhance", self._enhance_selection
        )
        # Turn the folders picked in the tree into a folder of their own. Shown
        # only while several are picked — that selection IS the folder, unsaved.
        self._group_btn = self._tool_button(
            icons.custom_folder_icon(),
            "Group the selected folders into a folder of your own",
            self._group_selection,
        )
        self._group_btn.hide()
        self._delete_btn = self._tool_button(icons.delete_icon(), "Delete", self._delete_selection)
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
            "Listen: spoken slideshow commands, orders over a show (“enhance”, "
            "“fix hands”, “genau it”), and prompt steering while a folder is "
            "auto-generating",
            self._on_mic_toggle, checkable=True,
        )
        self._mic_btn.setStyleSheet(
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        # One switch for the device, wearing the waveform: on means Origenerator
        # is driving the OSR2, and the app picks the source — the funscript of
        # whatever scripted video is in front (the generate tab's, or one playing
        # in a slideshow), and a self-generated genau stroke whenever there is no
        # script to follow. It used to be two buttons, which asked the user to
        # answer a question the app can answer for itself, and let both sources
        # be armed at once. Always visible (it's app-wide), lit when on.
        self._osr2_btn = self._tool_button(
            icons.stroke_icon(),
            "Drive the OSR2 — the funscript of the video in front, or a "
            f"self-generated stroke when there is none ({STROKE_KEY_LEGEND}; "
            "Esc to stop)",
            self._on_osr2_toggle, checkable=True,
        )
        self._osr2_btn.setStyleSheet(
            "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
        )
        # The bank takes the pane's whole width, under the path rather than
        # beside it, and wraps onto as many rows as that width needs. Beside the
        # path it had to share a narrow pane with a folder name, and what a
        # horizontal layout does when it runs out of room is squeeze every button
        # until the glyphs are unreadable — a row of smudges. Wrapped, a button
        # is always its own size; the bank just gets taller.
        self._toolbar_host = QWidget()
        policy = self._toolbar_host.sizePolicy()
        policy.setHeightForWidth(True)  # so the column above gives it the rows it asks for
        self._toolbar_host.setSizePolicy(policy)
        # The family's own gap along a row, and its wider one between wrapped
        # rows -- at the single small gap this used, a bank that wrapped had its
        # two rows all but touching.
        toolbar = FlowLayout(self._toolbar_host, spacing=BUTTON_GAP,
                             row_spacing=BUTTON_ROW_GAP)
        self._toolbar_groups = []
        for buttons in (
            (self._back_btn, self._forward_btn),                    # where you are
            (self._undo_btn, self._redo_btn),                       # what you did
            (self._group_btn,),                                     # …to the picked folders
            (self._star_btn, self._enhance_btn, self._delete_btn),  # …to what's in front
            (self._slideshow_btn, self._auto_btn,                   # what the app is doing
             self._mic_btn, self._audio_btn, self._osr2_btn),
        ):
            gap = _toolbar_gap()
            toolbar.addWidget(gap)
            for button in buttons:
                toolbar.addWidget(button)
            self._toolbar_groups.append((gap, buttons))
        self._sync_toolbar_gaps()
        browser_box.addWidget(self._toolbar_host)
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
        # The search results' own controls, riding under the header like the
        # Recents filter and appearing only while a query is running: how many
        # items answered it, and the order they are laid out in. Recency is one
        # question ("the one I made recently"); model + LoRA is the other ("which
        # recipe was that"), and picking it cuts the results into a labelled band
        # per combination rather than interleaving them.
        self._search_count = QLabel("")
        self._search_count.setObjectName("estimateLabel")
        # No-wheel: it rides directly over the scrolling results, and a wheel
        # notch that lands on it must scroll them rather than re-sort them.
        self._search_sort_box = NoWheelComboBox()
        for label, mode in _SEARCH_SORTS:
            self._search_sort_box.addItem(label, mode)
        self._search_sort_box.setToolTip(
            "Order the results: newest first, or banded under a heading per "
            "model + LoRA combination — click a heading to fold its band away"
        )
        self._search_sort_box.currentIndexChanged.connect(self._on_search_sort_changed)
        self._search_bar = QWidget()
        search_row = QHBoxLayout(self._search_bar)
        search_row.setContentsMargins(0, 0, 0, 0)
        search_row.addWidget(self._search_count)
        search_row.addStretch(1)
        search_row.addWidget(QLabel("Sort:"))
        search_row.addWidget(self._search_sort_box)
        self._search_bar.hide()  # shown only while a search is running
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
        browser_box.addWidget(self._search_bar)
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
        self._folder_panes.addWidget(browser)

        # A strip under those two lists every generation in flight — the app hands
        # ComfyUI one at a time, so a batch of Generates is a queue — reachable
        # from any folder or config tab. Fed on every rebuild and poll; a row
        # dragged to a new place asks the controller to re-line the queue. Its top
        # edge is this column's splitter handle, so a long queue can be dragged
        # open at the cost of the folder listing above it.
        self._queue = GenerationQueue()
        self._queue.reorder_requested.connect(self._reroll.reorder)
        self._queue.clear_queue_requested.connect(self._clear_foreign_queue)
        self._left_column.addWidget(self._folder_panes)
        self._left_column.addWidget(self._queue)
        self._panes.addWidget(self._left_column)

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
        # No floor of its own on the info pane: the config tab inside it reports
        # what its settings need (GenerateConfigPanel.minimumSizeHint), and an
        # explicit minimum here would replace that number rather than join it —
        # pinning the pane narrower than its contents and putting a horizontal
        # scroll bar back under the form.
        self._folder_panes.setStretchFactor(0, 0)  # the TOC pane holds its width
        self._folder_panes.setStretchFactor(1, 1)  # the browser takes the growth
        self._folder_panes.setSizes([220, 560])
        # The strip opens at its own height and stays there: all the growth goes
        # to the folders above it, so a taller window is more gallery rather than
        # more queue.
        self._left_column.setStretchFactor(0, 1)
        self._left_column.setStretchFactor(1, 0)
        self._left_column.setSizes([600, self._queue.minimumHeight()])
        self._panes.setStretchFactor(0, 3)
        self._panes.setStretchFactor(1, 2)
        self._panes.setSizes([780, 440])

        layout.addWidget(self._panes, 1)

    def _tool_button(self, icon, tooltip: str, handler, *, checkable=False) -> QToolButton:
        """An icon-only button for the browser-pane header's bank. A
        ``checkable`` one is a toggle whose ``handler`` receives its on/off state.

        The icon is drawn near the button's full height on purpose. At 16px it
        sat in a 24px button carrying a glyph that used a third of its own
        canvas — a mark covering about a ninth of the button, which reads as a
        smudge rather than as a symbol.
        """
        btn = QToolButton()
        btn.setObjectName("iconButton")
        btn.setIcon(icon)
        btn.setIconSize(QSize(_TOOL_ICON_PX, _TOOL_ICON_PX))
        btn.setToolTip(tooltip)
        btn.setCheckable(checkable)
        (btn.toggled if checkable else btn.clicked).connect(handler)
        return btn

    def _sync_toolbar_gaps(self):
        """Show the space in front of each group that has something to show, and
        hide the leading one — so a bank whose optional buttons (Group, Auto,
        Slideshow) are away never wears a stray or doubled gap, and never starts
        indented."""
        leading = True
        for gap, buttons in self._toolbar_groups:
            showing = any(not button.isHidden() for button in buttons)
            gap.setVisible(showing and not leading)
            leading = leading and not showing

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
        # Every keystroke in a tab's form moves the text an open find is marking
        # up — re-run rather than leave highlights on words that shifted.
        panel.form_edited.connect(self._refresh_find)

    # --- Drive OSR2: one switch, the app picking funscript or stroke ----------

    def _on_osr2_toggle(self, on: bool):
        self._osr2_enabled = on
        self._reconcile_osr2()

    def _toggle_osr2_drive(self):
        """Flip the one switch — what Space does, from any surface. The stroke's
        own toggle is deliberately not reachable from a key any more: with two
        sources for one device, whichever one a key started would have been
        streaming alongside whatever the switch already had going."""
        self._osr2_btn.setChecked(not self._osr2_btn.isChecked())

    def _reconcile_osr2(self):
        """Put the right thing on the device, or nothing.

        With the switch off, neither source drives. With it on, a funscript wins
        wherever there is one — a slideshow showing a scripted video, else the
        front tab's — and the self-generated stroke fills every other moment,
        which is most of them: a folder of images, a clip with no script, an
        empty tab. That is the whole of "genau mode when no funscript is going".

        Idempotent, so tab switches, browsing, completions and opening or closing
        a show all resolve without churning the device. The guard makes it
        re-entrant-safe too: starting or stopping the stroke emits
        ``active_changed``, and a listener that reconciles must not land back
        here mid-flight.
        """
        if self._reconciling_osr2:
            return
        self._reconciling_osr2 = True
        try:
            target = self._osr2_drive_source() if self._osr2_enabled else None
            if target is None:
                if self._osr2_driving is not None:
                    self._osr2_driver.stop()
                    self._osr2_driving = None
            else:
                video_path, player, actions = target
                # Same clip, new player (a show opened over it) still re-aims.
                driving = (video_path, player)
                if self._osr2_driving != driving:
                    self._osr2_driver.start(player, actions)
                    self._osr2_driving = driving
            wants_stroke = self._osr2_enabled and target is None
            if wants_stroke and not self._osr2_stroke.active:
                self._osr2_stroke.start()
            elif not wants_stroke and self._osr2_stroke.active:
                self._osr2_stroke.stop()
        finally:
            self._reconciling_osr2 = False

    def _osr2_drive_source(self):
        """The funscript target to follow, or ``None`` when there is none to
        follow — in which case the stroke is what drives (see
        :meth:`_reconcile_osr2`). An open slideshow wins when it's showing a
        scripted video, otherwise the front tab's video.

        The switch governs both surfaces alike: double-clicking a clip open used
        to take the device on its own, so a clip watched with the switch off
        drove anyway — the switch is what decides now, whichever surface the
        video is on."""
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
            pace=self._pace, stroke=self._osr2_stroke,
            # Its Space reaches the one OSR2 switch, like every other surface's.
            on_drive_toggle=self._toggle_osr2_drive, **kwargs)
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
        # However the show was asked for, it now owns the card it is drawn with: a
        # video generation would saturate that card, and a show is exactly the
        # stretch when nobody is waiting on a video. The queue holds them until it
        # closes and keeps making images.
        self._reroll.hold_videos(True)
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

    def flush_queue_to_server(self) -> int:
        """Hand ComfyUI everything the queue is still holding, as the app closes.

        The queue holds work back for the sake of whoever is watching — videos off
        the GPU while a slideshow plays, one prompt at a time so the line stays
        re-orderable — and closing the app ends every one of those reasons. ComfyUI
        outlives it and works through the rest alone; the next launch picks up
        whatever finished. Returns how many jobs went.
        """
        return self._reroll.flush_to_server()

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
            self._sync_history_buttons()
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
        """Point every config tab's discard button at the run *it* launched.

        A tab tracks its own Generates, not its settings folder: a folder can have
        several runs queued at once (two pictures of one recipe, both wanted), and
        a tab showing one of them must not claim the others. Of its own it follows
        the *oldest still alive* — the one nearest to being made, and so the one
        its button discards. A press that stopped the job queued behind the one on
        screen was the reported dead click. A chained i2v is two prompts but one
        run, so a tab follows its origin across the hand-off, and runs that have
        ended are let go here.
        Launches from outside a tab — the folder tile's "+", the auto loop — are
        claimed by the tab looking at that same folder (:meth:`_claim_launch`), so
        they light it up too.

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
                                 auto_generating=self._auto_generating(job))

    def _auto_generating(self, job) -> bool:
        """Whether ``job``'s own folder is auto-looping — so the button that throws
        the run away reads "Next seed" instead of "Cancel". Its folder, not the
        front tab's: the label has to match what pressing it actually does."""
        key = self._job_folder_key(job)
        return key is not None and self._auto.is_active(key)

    def _job_folder_key(self, job) -> str | None:
        """The settings folder a live job runs in, or ``None`` for one no longer
        tracked. Read from the controller's grouping rather than recomputed from the
        job's params, so it is the key the job was actually filed under."""
        if job is None:
            return None
        return next((k for k, jobs in self._reroll.jobs_by_folder.items()
                     if job in jobs), None)

    def _claim_launch(self, key: str):
        """Give a run launched outside any tab — the folder tile's "+", the auto
        loop — to the front config tab when that tab is showing the same folder.

        Unclaimed, such a run belonged to no tab at all, so the tab looking
        straight at it showed neither the discard button nor a filling Generate
        while the pane beside it streamed the very frames it was making. Only a
        matching folder claims it, so a tab parked on other settings is untouched.
        """
        panel = self._info_tabs.current_config_panel()
        job = self._reroll.newest_job_for(key)
        if panel is None or job is None or panel.settings_key() is None:
            return
        if self._panel_reroll_key(panel) == key:
            panel.note_launched(job.origin)
            self._reconcile_generating()  # the launch's own reconcile ran before this

    def _cancel_panel_reroll(self, panel):
        """Discard the run this tab's bar is showing — its Cancel/Next seed button.

        The oldest of the tab's own still alive, so the press acts on the thing on
        screen rather than something queued behind it.
        """
        for origin in panel.launched_runs():
            job = self._reroll.job_for_origin(origin)
            if job is not None:
                self._cancel_job(job.prompt_id)
                return

    def _would_reproduce_a_completed_run(self, workflow, params: dict) -> bool:
        """True when launching ``workflow`` with ``params`` would re-create a
        byte-identical past generation — the cue to re-roll rather than waste a slot.

        Callers pass params whose seed is already concrete (the form randomizes a
        Random seed before emitting; a combine reads the stored one), so the seed
        is taken as pinned here; a genuinely random seed would simply never match.
        """
        return would_reproduce_a_completed_run(
            self._db.list_generations(), workflow, params)

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
        # A pinned seed that would reproduce a past run draws a fresh one instead of
        # launching a copy — the press was made against a button already reading
        # "Generate with Random seed" (:meth:`GenerateConfigPanel._apply_generate_caption`),
        # so this is what it said it would do, not a question worth stopping for.
        # The tab keeps the Random seed, so its form goes on saying the same thing.
        if self._would_reproduce_a_completed_run(wf, params):
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
        expanded = self._tree_view.expanded_keys()
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
            recipe_match.available_categories(
                self._rebuildable_videos(rows), self._combine.selected_intent()
            )
        )
        tree_model = gallery.build_gallery_tree(rows, meta)
        unreviewed = self._review_queue(rows)
        held = self._held_rows = recovery.bin_items(self._bin_records())
        self._live_ids = {row["prompt_id"] for row in rows}
        self._custom_folders = gallery.build_custom_folders(
            tree_model, self._db.list_custom_folders()
        )
        # Re-index for the search box while the rows are in hand: tokenizing every
        # prompt belongs to the rebuild, so a keystroke costs only lookups. Rows
        # already indexed keep their words and take the fresh row object, since a
        # poll rewrites every row dict without touching the text in it.
        #
        # A row also carries the names the user gave the folders it sits in, so a
        # folder named to be remembered can be searched for by that name. Those
        # come from the tree and the user's own groupings, which is why the
        # indexing waits until both are built.
        #
        # The trash's held rows are indexed alongside the gallery's own, because
        # standing on the Trash shelf and searching it has to find something —
        # a deleted row is out of ``list_generations`` and lives only in the bin.
        # They are reachable only from that shelf: every other scope is a set of
        # ids drawn from the live tree (see :meth:`_search_scope`).
        self._search.update(rows + held, gallery.named_folders_by_row(
            tree_model, meta, self._custom_folders))
        requested = gallery.requested_generations(self._db.list_requests(), rows)  # the Requests shelf
        self._browser.set_model(
            gallery.recent_generations(rows, self._recents_media_types()),
            gallery.starred_folders(tree_model),
            gallery.starred_generations(rows),
            unreviewed,
            held,
            requested,
        )
        self._tree_view.populate(tree_model, expanded,
                                 show_recents=bool(tree_model or self._browser._inflight_items()),
                                 experiment_count=len(unreviewed),
                                 trash_count=len(held),
                                 request_count=len(requested),
                                 custom_folders=self._custom_folders,
                                 folder_meta=meta)
        # The rows the old selection group pointed at are gone with the rebuild;
        # _restore_multi_selection below stands a fresh one up from multi_keys.
        self._selection_group = None
        # The gallery's own selection is dropped and re-picked below. The tabs are
        # not: a rebuild used to empty the front tab's preview outright and count on
        # that re-pick to paint it back, so a tab showing anything the gallery
        # wasn't pointed at went blank every time a generation landed — once per
        # variation of a running loop. Only what has actually gone (a deleted or
        # trashed item) is taken off a tab now.
        self._selected_row = None
        self._info_tabs.drop_previews_of_gone_rows(self._live_ids)
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
        # Seed history once with wherever the gallery first lands, so Back works
        # even if the user's very first move leaves it.
        if self._history.current() is None:
            location = self._current_location()
            if location is not None:
                self._history.visit(location)
                self._sync_nav_buttons()
        # A search running through the rebuild takes the pane back off the folder
        # the restore above just re-drew, and re-runs against the new index — so a
        # generation that lands while a query is open joins its results.
        if self._search_query:
            self._run_search()
        self._update_queue()
        # Re-assert the front tab's Generate-as-progress state against the live jobs.
        # Keying off the freshly rebuilt image rows is what lets a reconnected re-roll
        # light its tab's button after a restart: at reconnect time the view's image
        # rows aren't built yet, so an i2v folder key wouldn't match then; here it does.
        self._reconcile_generating()
        # A generation landing or leaving can make an open tab's pinned seed one that
        # would reproduce it — or stop it being one — with nothing on the form having
        # moved, so every tab re-reads what its Generate would now do.
        for panel in self._info_tabs._config_panels():
            panel.refresh_generate_caption()

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
            self._search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
            self._search_edit.selectAll()
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

    # --- searching the gallery (the box over the tree) ------------------------

    def _on_search_changed(self, text: str):
        """A keystroke in the search box: line the search up, don't run it yet.

        Nothing happens under three characters — one or two letters reach a large
        fraction of any library through stemming alone, so searching them would
        answer the first keystroke of every query with most of the gallery. Past
        that the search waits out :data:`_SEARCH_DELAY_MS` of quiet, and the model
        call waits out a longer one, so a word being typed doesn't churn the pane
        it is about to fill.
        """
        query = (text or "").strip()
        self._search_timer.stop()
        self._search_expand_timer.stop()
        if len(query) < _SEARCH_MIN_CHARS:
            if self._search_query:
                self._exit_search()
            self._search_query = ""
            return
        if query != self._search_query:
            self._search_expansions = None  # last query's widening isn't this one's
        self._search_query = query
        self._search_timer.start()
        self._search_expand_timer.start()

    def _run_pending_search(self):
        """Typing has paused: run the standing query and draw it."""
        if not self._search_query:
            return
        # The cache is consulted, never asked: a query the expander has already
        # answered (re-typed, or reached again by backspacing) is smart from the
        # first draw, and one it hasn't waits for _request_search_expansion.
        self._search_expansions = self._search_expander.cached(self._search_query)
        self._run_search()

    def _search_scope(self) -> _SearchScope:
        """What the search covers: its short name, its path, and what is in it.

        The tree's selection is the scope, whatever kind of row it is. A shelf
        counts: Recents, Starred, Experiments and Trash are each a collection of
        generations, and standing on one and searching it is the obvious thing to
        try. The All row above Images and Videos is what covers the library
        entire, since every other folder narrows the answer before the query does.

        ``path`` is the row's breadcrumb — what the box, the header and the
        empty-result message all name the scope by. A shelf is a single row with
        no branch above it, so its path is just its own name.
        """
        item = self._tree.currentItem()
        shelf = self._current_shelf_key()
        if shelf is not None:
            rows = self._browser.selected_shelf_rows() or []
            return _SearchScope(_SHELF_LABELS[shelf],
                                {row["prompt_id"] for row in rows})
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if group is None:
            return _SearchScope(gallery.ALL_LABEL, self._live_ids)
        if isinstance(group, gallery.AllGroup):
            # Everything the *gallery* holds — the trash's held rows share the
            # index but belong to their shelf alone.
            return _SearchScope(group.label, self._live_ids)
        return _SearchScope(self._tree_view.breadcrumb(item),
                            {row["prompt_id"] for row in gallery.rows_under(group)})

    def _sync_search_placeholder(self):
        """Say in the empty box what a query typed there would search, so the
        scope is visible before there is a header or a result to name it.

        The whole path goes in; the box shows as much of its tail as it is wide
        enough for (:class:`ScopeSearchEdit`)."""
        self._search_edit.set_scope(self._search_scope().path)

    def _run_search(self):
        """Fill the browser pane with what the standing query matches, within the
        folder the tree has selected.

        Takes the pane over from that folder — the tree keeps its selection while
        a search runs, because the selection is the *scope*: picking another
        folder re-asks the question there rather than ending it, and clearing the
        box hands the pane straight back to wherever you had got to.
        """
        scope = self._search_scope()
        self._search_outcome = self._search.search(
            self._search_query, expansions=self._search_expansions, within=scope.ids
        )
        self._search_tiles = self._collapse_to_folders(self._search_outcome.results)
        self._title.set_display(f"Search: “{self._search_query}” in {scope.path}")
        self._title.setToolTip("")  # the header is the query now, not a folder
        self._avg_label.setText("")
        self._recents_filter_bar.hide()
        self._experiments_bar.hide()
        self._search_count.setText(self._search_count_text())
        self._search_bar.show()
        self._browser.show_search_results(
            self._search_tiles, sort_mode=self._search_sort,
            query=self._search_query, outcome=self._search_outcome,
            scope=scope.path, collapsed=self._search_collapsed,
            on_section_toggled=self._on_search_section_toggled,
        )
        self._sync_slideshow_button()   # a search's hits are playable, like a shelf's
        self._sync_auto_button()
        self._sync_enhance_button()
        self._sync_delete_button()
        # Results are what the pane is showing, so they are somewhere Back returns
        # to — including from a hit that was opened out of them.
        self._record_location()

    def _collapse_to_folders(self, results) -> list:
        """The hits as tiles: a folder wherever one answered with several items.

        Every row in a settings folder shares a prompt and settings and differs
        only by seed, so a prompt match hits all of them — and drawing eight
        near-copies of one picture buries the other places the query reached.
        The folder stands for them instead, and a folder's lone hit stays itself.
        Order is by first hit, so the newest thing found still leads.

        A folder the tree has no row for (a hit whose folder the current model
        doesn't hold) falls back to its own items rather than vanishing.
        """
        image_index = gallery.build_image_config_index(self._image_rows)
        by_folder: dict[str, list] = {}
        for result in results:
            key = gallery.settings_folder_key(result.row, image_index)
            by_folder.setdefault(key, []).append(result.row)
        tiles = []
        for key, rows in by_folder.items():
            group = self._group_for_key(key) if len(rows) > 1 else None
            if group is not None:
                tiles.append(SearchTile(row=rows[0], group=group, rows=list(rows)))
            else:
                tiles.extend(SearchTile(row=row, rows=[row]) for row in rows)
        return tiles

    def _on_search_section_toggled(self, heading: str, collapsed: bool):
        """Remember a recipe band's fold state, so a redraw — a rebuild, a landing
        generation, a widening — doesn't spring open the bands you shut."""
        if collapsed:
            self._search_collapsed.add(heading)
        else:
            self._search_collapsed.discard(heading)

    def _search_count_text(self) -> str:
        """How many the query found — and, past what the pane will draw at once,
        that it is showing a slice and what to do about it. A capped search that
        said only "2,000 results" would read as 2,000 tiles you could scroll to.

        Counted in tiles, which is what is on screen: a folder standing for its
        eight seed variants is one result to click, not eight."""
        count = len(self._search_tiles)
        text = f"{count:,} result{'s' if count != 1 else ''}"
        if count > SEARCH_DRAW_LIMIT:
            text += (f" — showing the newest {SEARCH_DRAW_LIMIT}; "
                     "add a word to narrow it")
        return text

    def _exit_search(self):
        """Put the search away and give the pane back to the selected folder."""
        self._clear_search_state()
        self._on_folder_selected(self._tree.currentItem(), None)

    def _clear_search_state(self):
        """Forget the running query, its results and its bar — the state half of
        leaving a search, with nothing drawn. Split out because a Back onto a stop
        that had no search must clear the same state without redrawing the pane
        twice: :meth:`_restore_location` fills it itself."""
        self._search_query = ""
        self._search_expansions = None
        self._search_outcome = search.SearchOutcome((), ())
        self._search_tiles = []
        self._search_timer.stop()
        self._search_expand_timer.stop()
        self._search_bar.hide()

    def _leave_search(self, *_args):
        """Clear the box, if a search is running — what navigating away means.

        This is for gestures that go *to* a result: opening a hit's folder, or
        following a link out of one. Picking a folder in the tree is not one of
        them — that re-scopes the search (see :meth:`_on_folder_selected`).

        Takes and ignores whatever the caller passes, so it can be wired straight
        to those gestures. Clearing the box is what actually ends the search: its
        ``textChanged`` runs :meth:`_exit_search`, so there is one path out
        rather than two.

        Off the history, because the folder the box hands the pane back to is a
        step on the way rather than anywhere the user went: the caller records the
        result it is opening. Recorded, it would sit between the results and that
        result, and Back out of a hit would land on a folder instead of on the
        hits it came from.
        """
        if not self._search_query:
            return
        self._suppress_history = True
        try:
            self._search_edit.clear()
        finally:
            self._suppress_history = False

    def _on_search_sort_changed(self, _index=0):
        """Re-lay the results in the newly picked order (a no-op off a search)."""
        self._search_sort = self._search_sort_box.currentData() or search.SORT_RECENT
        if self._search_query:
            self._run_search()

    def _request_search_expansion(self):
        """Typing has stopped: ask the local LLM to widen this query's words.

        Nothing is awaited — :meth:`_on_search_expanded` re-runs the search if and
        when an answer lands, and the table-widened results the user is already
        looking at stand if one never does.
        """
        if self._search_query:
            self._search_expander.request(self._search_query)

    def _on_search_expanded(self, query: str, expansions):
        """A widened vocabulary came back: re-run the search on it.

        Only for the query still in the box — a slow answer can land after the
        user has typed on, and widening results for a query they are no longer
        running would put items on screen they cannot account for. An empty
        answer (the endpoint down, or nothing to add) changes nothing, so it
        doesn't redraw the pane out from under them either.
        """
        if expansions and query == self._search_query:
            self._search_expansions = expansions
            self._run_search()

    def search_sort(self) -> str:
        """The results order in force, for the session state to remember."""
        return self._search_sort

    def set_search_sort(self, mode: str | None):
        """Restore the remembered results order (ignoring anything unrecognized,
        so a state file from a version that offered a different one still opens)."""
        index = self._search_sort_box.findData(mode)
        if index >= 0:
            self._search_sort_box.setCurrentIndex(index)  # its signal sets the mode

    def _showing_search(self) -> bool:
        return self._browser.showing_search()

    def _on_folder_selected(self, current, _previous):
        if self._selection_group is not None:
            return  # a multi-selection owns the panes; the current row is one of many
        self._sync_search_placeholder()  # the box says what it would search now
        # A folder picked while a search is running is a new *scope*, not an exit:
        # the same question, asked of somewhere else. Suppressed during a rebuild's
        # restore, where the tree is re-selecting itself and _rebuild re-runs the
        # search once at the end rather than once per step of the restore.
        if self._search_query and not self._suppress_history:
            self._run_search()
            return
        self._sync_auto_button()  # the auto toggle fits only a re-rollable leaf
        self._sync_slideshow_button()  # the slideshow fits any folder holding media
        self._sync_enhance_button()  # enhance-all fits a folder with plain images
        self._sync_group_button()      # grouping fits only a multi-selection
        # The image/video filter belongs to the Recents shelf alone; the
        # experimenter's switch to the Experiments shelf alone.
        self._recents_filter_bar.setVisible(current is self._recents_item)
        self._experiments_bar.setVisible(current is self._experiments_item)
        if current is None:
            self._title.set_display("")
            self._title.setToolTip("")
            self._avg_label.setText("")
            self._browser.show_empty()
            self._sync_action_buttons()
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
        if current is self._requests_item:
            self._browser.show_requests_overview()
            return
        if current is self._trash_item:
            self._browser.show_trash_overview()
            return
        group = current.data(0, _GROUP_ROLE)
        self._note_folder_visit(group.key if group is not None else None)
        if group is not None:
            # A folder is somewhere the user went, so Back can return to it — and
            # so leaving a shelf for one is a step Back can undo at all.
            self._record_location()
        self._title.set_display(self._tree_view.breadcrumb(current))
        # The path ends in a code, so what the folder holds — the prompt its
        # generations ran, and the settings that set it apart from its siblings —
        # is read by hovering the path, as it is by hovering the row itself.
        self._title.setToolTip(gallery.folder_detail(group) if group else "")
        self._update_folder_average(group)
        self._show_group_contents(group)
        self._sync_action_buttons()

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
        self._title.setToolTip("")  # a count of folders, with no one folder behind it
        self._update_folder_average(group)
        self._browser.show_custom_folder(group)
        self._sync_auto_button()  # greyed here, but still lit if a loop runs elsewhere
        self._sync_slideshow_button()
        self._sync_group_button()
        self._sync_action_buttons()

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
        self._sync_toolbar_gaps()

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
        self._sync_history_buttons()
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
        self._sync_history_buttons()

    def _remove_from_custom_folder(self, group, member_key: str):
        """Drop one gathered folder out of the custom folder on screen."""
        member = self._group_for_key(member_key)
        identity = self._member_identity(member) if member is not None else (member_key, None, None)
        self._actions.remove_from_custom_folder(
            group.folder_id, member_key, level=identity[1], ref_prompt_id=identity[2]
        )
        self.refresh()
        self._sync_history_buttons()

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
    def _requests_item(self):
        return self._tree_view.requests_item

    @property
    def _trash_item(self):
        return self._tree_view.trash_item

    def _selected_folder_key(self) -> str | None:
        """The selected folder's key (or a shelf's), from the tree renderer."""
        return self._tree_view.selected_folder_key()

    def _current_group(self):
        """The folder on screen, or ``None`` (a shelf, a search, or an empty
        selection).

        While several folders are picked that's the unsaved folder they make, so
        everything reading this — the slideshow, the title, the average, the delete
        button — sees one folder whether or not it has been saved yet.

        A running search is ``None`` for the same reason a shelf is: the tree
        still has a row selected, but that folder is not what the pane is showing,
        and every reader of this would otherwise offer its action — auto-generate,
        Enhance All, delete-the-folder — against something off screen."""
        if self._selection_group is not None:
            return self._selection_group
        if self._showing_search():
            return None
        item = self._tree.currentItem()
        return item.data(0, _GROUP_ROLE) if item else None

    def _add_reroll_tile(self, flow, group):
        job = self._reroll.job_for(group.key)
        tile = RerollTile(job,
                          auto_generating=self._auto.is_active(group.key),
                          typical_seconds=self._typical_run_seconds(job))
        tile.set_selected(group.key == self._selected_reroll_key)
        tile.add_requested.connect(lambda k=group.key: self._start_reroll(k))
        tile.cancel_requested.connect(lambda k=group.key: self._cancel_reroll(k))
        tile.selected.connect(lambda k=group.key: self._select_reroll(k))
        flow.addWidget(tile)
        self._reroll_tile = tile

    def _typical_run_seconds(self, job) -> float | None:
        """What a whole run of ``job``'s workflow usually takes — the prior the
        tile's countdown opens on, before the run has a pace of its own worth
        reading. ``None`` for an idle tile, or a workflow with no history yet."""
        if job is None:
            return None
        return timing.estimate_seconds(self._db.recent_durations(job.workflow.name))

    def _start_auto_reroll(self, key: str) -> bool:
        """The loop's own launch: the variation the tile's "+" would start, except
        that nothing about it reaches a config tab.

        A loop is left running while the user works, so what it is making is not
        what they are looking at. Its frames used to fill the info pane — that is,
        the preview of whichever tab was open, over the picture the user had put
        there — and its results landed in a tab too. Both belong to the folder's
        own live tile in the middle column, which streams the run whether or not
        the pane is pointed at it.
        """
        return self._start_reroll(key, from_auto=True)

    def _start_reroll(self, key: str, *, from_auto: bool = False) -> bool:
        """Start a fresh variation for the folder ``key`` names and select it, so
        its live preview fills the info pane at once. Returns whether a variation
        is now running for the folder — the auto-generate loop's cue that a launch
        took hold, and its cue to stop when one can't.

        The tile's "+" and the auto loop both come through here, and neither
        pressed a tab's Generate, so the run is offered to the tab showing that
        folder (:meth:`_claim_launch`) — otherwise it would run with no tab
        showing its progress or offering to discard it.

        ``from_auto`` is the loop's launch (:meth:`_start_auto_reroll`), which takes
        the info pane only where the user already had it on this folder's loop —
        watching one variation is watching the next. Otherwise the pane keeps
        whatever the user put there.

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
        self._claim_launch(key)  # the tab on this folder shows it, and can discard it
        if from_auto:
            self._note_auto_launch(key)  # its result is the loop's, not a tab's
        if not from_auto or self._selected_reroll_key == key:
            self._select_reroll(key)  # a no-op if the launch above failed to register
        return self._reroll.has(key)

    def _note_auto_launch(self, key: str):
        """Remember that the loop, not a tab, asked for the run just launched — so
        no tab shows its result when it lands (:meth:`_on_reroll_finished`).

        Recorded by the id the run began under, the same name a tab knows its own
        runs by, and pruned to what is still in flight as it goes: only a live run
        can still finish, so a cancelled variation leaves nothing behind.
        """
        job = self._reroll.newest_job_for(key)
        if job is None:
            return  # the launch didn't take
        self._auto_origins = {origin for origin in self._auto_origins
                              if self._reroll.job_for_origin(origin) is not None}
        self._auto_origins.add(job.origin)

    def _toggle_auto(self, checked: bool):
        """Start or stop auto-generating fresh variations.

        Switching it on runs the open folder; switching it off stops the loop
        wherever it is running, since the lit switch means one is running rather
        than that this folder is the one running it (see :meth:`_sync_auto_button`).
        Cleanup runs in :meth:`_on_auto_stopped` either way.

        It no longer touches the microphone. A running loop is what gives voice a
        prompt to steer, so an open mic starts steering when one begins — but the
        mic itself is the button's, and only the button's.
        """
        key = self._selected_folder_key()
        if not checked:
            self._auto.stop_all()
        elif key is not None:
            self._begin_auto(key)
        self._sync_auto_button()  # reflect the real state — a start may not take
        self._sync_discard_buttons()  # Cancel ⇄ Next seed, on all three surfaces

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
        if key == self._selected_reroll_key and key not in self._reroll_jobs:
            # The pane was following this loop between variations; there is no next
            # one to wait for now.
            self._clear_reroll_selection()
        if key == self._voice_target_key:
            self._voice_target_key = None
            self._pending_auto_key = None
            self._sync_voice()
        self._sync_auto_button()
        self._sync_discard_buttons()  # the in-flight run's button is a Cancel again

    def _sync_discard_buttons(self):
        """Re-label every button that throws a run away — the folder's live tile, the
        bottom strip's rows, each config tab's — after a loop started or ended.

        Nothing else repaints them at that moment: switching Auto on over a folder
        that is already generating launches nothing, so there is no re-roll change
        to ride, and the label would keep promising a stop that the press no longer
        performs (or offering a next seed after the loop is off).
        """
        self._rerender_current_leaf()
        self._update_queue()
        self._reconcile_generating()

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
            self._say_of_voice(f"🎤 heard: “{text}”")

    def _on_voice_edited(self, _new_prompt: str):
        self._say_of_voice("🎤 ✓ prompt updated")

    def _on_voice_error(self, message: str):
        self._say_of_voice(f"🎤 {message}")

    def _say_of_voice(self, message: str):
        """Put what voice heard or hit in front of whoever is listening.

        Both places, because they are different screens: this pane's caption for
        someone working in the window, and the show's own corner for someone
        watching a slideshow — who can see nothing of this window at all, and
        for whom a mic that heard nothing and one that heard the wrong words
        look exactly alike.
        """
        self._show_voice_status(message, transient=True)
        if self._slideshow is not None:
            self._slideshow.note_request(message)

    def _sync_auto_button(self):
        """Keep the auto-generate toggle on screen wherever the user is, lit
        whenever a loop is running — in this folder or any other.

        A loop is a standing instruction to spend the whole machine on one recipe,
        so the one thing the toolbar must never do is let one run out of sight. A
        switch that disappeared with the folder it belonged to did exactly that:
        nothing on screen said a loop was running, and finding the folder it was
        running in meant hunting the tree for it.

        So it is always there, and lit means "a loop is running" rather than "this
        folder's loop is running" — clicking it off stops whichever folder has it,
        from wherever the user happens to be. Greyed only when there is genuinely
        nothing to do: this folder can't be looped and none is running.

        While the loop is running somewhere else, its tip is a clickable one that
        offers to go there (:attr:`_auto_tip`), and the plain tooltip stands down
        so only one of them appears.
        """
        group = self._current_group()
        available = isinstance(group, gallery.SettingsGroup) and self._can_reroll(group)
        looping = self._auto.active_key()
        elsewhere = looping is not None and looping != self._selected_folder_key()
        self._auto_btn.setEnabled(available or looping is not None)
        self._auto_btn.setToolTip("" if elsewhere else self._auto_tooltip(available, looping))
        self._auto_tip.set_html(_AUTO_ELSEWHERE_TIP if elsewhere else "")
        self._auto_btn.blockSignals(True)
        self._auto_btn.setChecked(looping is not None)
        self._auto_btn.blockSignals(False)
        self._sync_toolbar_gaps()

    def _auto_tooltip(self, available: bool, looping: str | None) -> str:
        """What the toggle says it will do, for every case but the loop being
        elsewhere — that one is the clickable tip's to say."""
        if looping is not None:
            return "Auto-generate is running in this folder — click to stop it (Esc too)"
        return (
            "Auto-generate: repeatedly generate variations of this folder "
            "until toggled off (Esc stops it too)"
            if available else
            "Auto-generate: open a settings folder to generate variations of it"
        )

    def _go_to_looping_folder(self, _href: str):
        """Follow the tip's link to whichever folder is looping right now.

        Read at the click rather than baked into the link, so a loop that has
        since moved or ended takes the user to where it actually is, or nowhere.
        """
        key = self._auto.active_key()
        if key is not None:
            self._navigate_to_reroll(key)

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
        self._sync_toolbar_gaps()

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
        if self._showing_search():
            return "these results"
        return {_RECENTS_KEY: _RECENTS_LABEL, _STARRED_KEY: _STARRED_LABEL,
                _EXPERIMENTS_KEY: _EXPERIMENTS_LABEL,
                _REQUESTS_KEY: _REQUESTS_LABEL,
                _TRASH_KEY: _TRASH_LABEL}.get(
            self._current_shelf_key(), "this folder"
        )

    # --- standalone enhance: the bank button, the selection action, the queue ---

    def _sync_enhance_button(self):
        """Aim Enhance the way Delete is aimed: the picked thumbnails if any are
        picked, else every image in this folder still waiting for one. It stays
        in the bank either way, disabled when there is nothing to enhance —
        a button that comes and goes is one the user has to go looking for.

        Picked items are enhanced whether or not they already have been (that is
        what picking them says); a whole folder is only its not-yet-enhanced
        images, so the button doesn't quietly re-run the ones that are done.
        """
        if self._browser.selected_ids:
            ids = self._enhanceable_selection()
            self._enhance_btn.setEnabled(bool(ids))
            if ids:
                self._enhance_btn.setToolTip(
                    f"Enhance {len(ids)} item{'s' if len(ids) != 1 else ''} "
                    "(upscale + low-denoise re-sample)"
                )
            else:
                self._enhance_btn.setToolTip(
                    _NO_VIDEO_ENHANCER if self._selection_is_all_video()
                    else _ALREADY_AT_THESE_SETTINGS
                )
            return
        group = self._current_group()
        awaiting = (
            gallery.rows_awaiting_enhancement(group.rows, self._db.list_generations())
            if isinstance(group, gallery.SettingsGroup) else []
        )
        self._enhance_btn.setEnabled(bool(awaiting))
        self._enhance_btn.setToolTip(
            f"Enhance {len(awaiting)} not-yet-enhanced image"
            f"{'s' if len(awaiting) != 1 else ''} in this folder "
            "(upscale + low-denoise re-sample)"
            if awaiting else "Nothing here to enhance"
        )

    def _enhanceable_selection(self) -> list[str]:
        """The picked thumbnails this button would actually run on.

        Two things are dropped. Videos, because there is no video enhancer — the
        workflow behind all of this refines a still — and they are picked from
        the same flow and look no different picked, so a picked clip is nothing
        to run rather than a run that fails.

        And an image that already holds a version made at exactly the settings
        on the panel: running it again would spend a generation arriving at the
        picture that is already there. Judged against what the run would *use*
        (:func:`~origenerator.gallery.enhance.level_matching_settings`), so a
        source-matched model resolves to this image's own checkpoint before the
        comparison rather than the panel's raw value. Change any knob and the
        button comes back, which is what makes it read as "you have this one"
        rather than as "no".
        """
        ids = []
        for prompt_id in self.selected_prompt_ids():
            row = self._db.get_generation(prompt_id)
            if row is None or not gallery.is_enhanceable_row(row):
                continue
            if gallery.level_matching_settings(row, self._enhance_settings) is None:
                ids.append(prompt_id)
        return ids

    def _selection_is_all_video(self) -> bool:
        """Whether every picked thumbnail is a video — which is why Enhance is
        dark, as opposed to its images being enhanced at these settings already."""
        rows = [row for pid in self.selected_prompt_ids()
                if (row := self._db.get_generation(pid)) is not None]
        return bool(rows) and all(
            gallery.media_type_of_row(row) == "video" for row in rows
        )

    def _enhance_selection(self):
        """The bank button's action: enhance the picked thumbnails, or every
        member image of this folder that isn't enhanced yet."""
        if self._browser.selected_ids:
            ids = self._enhanceable_selection()
            if ids:
                self.enhance_items(ids)
                self._sync_enhance_button()
            return
        self._enhance_all()

    def _sync_enhance_panel(self):
        """Gray the Enhance settings out where nothing they say could ever run.

        The panel is app-wide and follows you rather than the folder, which is
        why it shows on the shelves as readily as on a settings folder — but a
        video is the one place with no enhancement to configure at all, and live
        knobs there advertise an action that isn't on offer. A mixed folder
        keeps them: the images in it are still enhanceable.
        """
        self._enhance_panel.set_applicable(
            not self._showing_only_videos(), _NO_VIDEO_ENHANCER
        )

    def _showing_only_videos(self) -> bool:
        """Whether everything in front of us is video — the picked thumbnails if
        any are picked, else the folder on screen. Nothing in front (a shelf with
        no pick) is not "only videos": there is simply nothing to say."""
        rows = [row for pid in self.selected_prompt_ids()
                if (row := self._row_for(pid)) is not None]
        if not rows and not self._browser.selected_ids:
            group = self._current_group()
            rows = gallery.rows_under(group) if group is not None else []
        return bool(rows) and all(
            gallery.media_type_of_row(row) == "video" for row in rows
        )

    def _sync_star_button(self):
        """Aim Star like Delete and Enhance: the picked thumbnails, else the
        folder on screen. It toggles, so the tooltip says which way it will go —
        a set already starred all over unstars.

        Disabled where a star means nothing: a shelf, or a deleted item in the
        bin, which has no folder to be bookmarked in."""
        pids = self.selected_prompt_ids() if self._browser.selected_ids else []
        if pids and not self._browser.showing_trash():
            starring = not self._all_starred(pids)
            self._star_btn.setEnabled(True)
            self._star_btn.setToolTip(
                f"{'Star' if starring else 'Unstar'} {len(pids)} "
                f"item{'s' if len(pids) != 1 else ''}"
            )
            return
        group = None if pids else self._starrable_folder()
        self._star_btn.setEnabled(group is not None)
        self._star_btn.setToolTip(
            f"{'Unstar' if group.starred else 'Star'} folder “{group.label}”"
            if group is not None else "Nothing here to star"
        )

    def _starrable_folder(self):
        """The folder on screen if a star can be set on it, else ``None``.

        A shelf has no group at all, and a multi-selection's folder isn't one
        yet — it has no row to hang a star on until it's saved, which is what
        the Group button beside this one is for."""
        if self._selection_group is not None:
            return None
        return self._current_group()

    def _all_starred(self, prompt_ids) -> bool:
        rows = [self._db.get_generation(pid) for pid in prompt_ids]
        return all(row and row.get("starred") for row in rows)

    def _star_selection(self):
        """The bank button's action: bookmark the picked thumbnails, or the
        folder on screen — and un-bookmark them when they already are, so the one
        button is the whole of the toggle."""
        if self._browser.selected_ids and not self._browser.showing_trash():
            pids = self.selected_prompt_ids()
            self.set_items_starred(pids, not self._all_starred(pids))
            return
        group = self._starrable_folder()
        if group is not None:
            self._toggle_star(group.key)

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
        # Whether a picked image already holds this exact version is what the
        # button is answering, so turning a knob is what brings it back.
        self._sync_enhance_button()

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
        self._sync_enhance_button()

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

        The same ask as a spoken "enhance" over the same picture, so the same
        decision makes it (:meth:`_enhance_it`); a hold has no corner line to
        fill, so its answer is dropped. The decision is on this side rather than
        in the slideshow because it is this side that holds the levels — and a
        video has none to receive."""
        return self._enhance_it(prompt_id)[0] is not None

    # --- spoken commands: "enhance" over a show, "start slideshow" for one ---

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
        """One recognized utterance: a show command, or an order about the
        picture on screen."""
        if isinstance(matched, ShowCommand):
            self._run_show_command(matched)
        else:
            self._on_picture_command(matched)

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

    def _on_picture_command(self, command):
        """A spoken command about the picture on screen: a targeted "fix <part>",
        "enhance" for the better version of it, or "genau it" to animate it as a
        Genau clip.

        Answered out of the show's own note — the speaker is looking at it, not
        at this pane. Said with no show up there is no "on screen" to act on, and
        the utterance has already been claimed as a command by the time it gets
        here, so the caption says so rather than letting it vanish."""
        show = self._slideshow
        if show is None:
            wants = _VOICE_WANTS.get(command) or f"a {command.name} fix"
            self._show_voice_status(
                f"🎤 {wants} needs a picture on screen", transient=True)
            return
        target = show.voice_target()
        if command == gallery.GENAU_COMMAND:
            prompt_id, message = self._genau_it(target)
        elif command == gallery.ENHANCE_COMMAND:
            prompt_id, message = self._enhance_it(target)
        else:
            prompt_id, message = self._fix_part(target, command)
        show.note_voice_run(prompt_id, message)

    def _enhance_it(self, prompt_id: str | None) -> tuple[str | None, str]:
        """Enhance the picture on screen: the id it launched on (``None`` when it
        didn't) and the line the speaking surface should say.

        Only an image that has received no enhancement gets one, the same gate a
        fullscreen hold's Down uses — spoken over a show, this is a gesture made
        with no view of the Enhance panel, and an image already carrying an
        enhancement someone chose must not be re-derived at whatever the knobs
        happen to say now. Re-enhancing stays a deliberate act made in front of
        the settings it will use (the thumbnail menu, the ``+ Enhance`` card).
        """
        row = self._db.get_generation(prompt_id) if prompt_id else None
        if row is None or not gallery.is_enhanceable_row(row):
            return None, "🎤 only a finished image can be enhanced"
        if gallery.is_enhanced_row(row):
            return None, "🎤 this one is enhanced already"
        params = gallery.enhance_params_for(row, self._enhance_settings)
        if params is None:
            return None, "🎤 this one has no file to enhance"
        return self._launch_spoken_enhance(row, params, "enhance", "enhancing…")

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
        return self._launch_spoken_enhance(row, params, f"{part.name} fix",
                                           f"fixing {part.name}…")

    def _launch_spoken_enhance(self, row: dict, params: dict, what: str,
                               doing: str) -> tuple[str | None, str]:
        """The tail both spoken enhancements share: refuse one already cooking,
        else launch and say so.

        A targeted fix and a plain "enhance" differ in what they refuse and in
        what they run; from here on they are one act. ``what`` names the run in
        a refusal ("teeth fix", "enhance"), ``doing`` is what the surface says
        while it runs.
        """
        if self.enhancing_run(row) is not None:
            return None, "🎤 an enhance of this image is already running"
        logger.info("Voice %s on %s at %s", what, row.get("prompt_id"),
                    gallery.describe_enhance_params(params))
        if not self._launch_enhance(row, params):
            return None, f"🎤 couldn't launch the {what} — see the log"
        return row["prompt_id"], f"🎤 {doing}"

    # --- spoken requests: "Request … over" over whatever is on screen ---------

    def _on_spoken_request(self, spoken):
        """One step of a spoken request, from the mic's dictation.

        While it is still being said the show holds and the corner says so;
        finished, it queues a revision of the item it was opened over. The
        target is taken at the opening step and kept, because a request is about
        the picture that prompted it, not whatever is up when the words run out.
        """
        show = self._slideshow
        if self._request_target is None:
            # Taken at the first step of the request, whichever step that is —
            # "Request, no hat, over" is a whole one in a single breath.
            self._request_target = self._voice_request_target(show)
        if spoken.listening:
            self._hold_for_request(show, spoken)
            return
        target = self._request_target
        self._request_target = None
        self._hold_for_request(show, spoken)
        if spoken.state != COMPLETED:  # given up on — the terminator never came
            self._answer_request(show, "🎤 request dropped — never heard “over”")
            return
        self._begin_request(target, spoken)

    def _voice_request_target(self, show) -> str | None:
        """What a request just opened is about: the slide filling the screen
        when a show is up, else the generation picked in the gallery."""
        if show is not None:
            return show.voice_target()
        return self.selected_generation()

    def _hold_for_request(self, show, spoken):
        """Hold (or release) the show while the sentence is being said, and say
        so — in the show's own corner when one is up, since that is where the
        speaker is looking, and in this pane's voice caption otherwise."""
        note = f"🎤 Request: {spoken.text}…" if spoken.listening else ""
        if show is not None:
            show.hold_for_request(spoken.listening, note)
        elif spoken.listening:
            self._show_voice_status(note or "🎤 Request…", transient=False)

    def _answer_request(self, show, message: str):
        """Say what the request did, where the speaker is looking."""
        if show is not None:
            show.note_request(message)
        else:
            self._show_voice_status(message, transient=True)

    def _begin_request(self, prompt_id: str | None, spoken):
        """Start working out what a finished request changes.

        The working-out goes to the pool because it may have to ask the local
        LLM which of the prompt's own terms the speaker meant, and a second of
        network wait on this thread is a second of frozen slideshow — at the one
        moment the app must not stutter. Whatever can be answered without that
        (nothing on screen, a recipe this app can't rebuild) is answered here,
        so a request that was never going to run doesn't wait on a model.
        """
        row = self._db.get_generation(prompt_id) if prompt_id else None
        show = self._slideshow
        if row is None:
            self._answer_request(show, "🎤 nothing on screen to request a change to")
            return
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None or self._client is None:
            self._answer_request(
                show, "🎤 this one can't be re-made, so there's nothing to revise")
            return
        params = filled_params(row, workflow)
        self._answer_request(show, f"🎤 working out “{spoken.text}”…")
        QThreadPool.globalInstance().start(ReviseTask(
            self._revision, (row, workflow, params, spoken),
            params.get("positive_prompt", ""), params.get("negative_prompt", ""),
            spoken.text,
        ))

    def _on_request_revised(self, context, revision):
        """The revision came back from the pool: queue it, and say what it did.

        The show is looked up now rather than remembered, so an answer that took
        a couple of seconds still lands wherever the speaker is looking.
        """
        row, workflow, params, spoken = context
        show = self._slideshow
        if revision is None:
            self._answer_request(show, f"🎤 didn't catch what to change in “{spoken.text}”")
            return
        if not revision.changed:
            self._answer_request(show, f"🎤 “{revision.term}” is already how you asked for it")
            return
        self._answer_request(show, self._queue_request(row, workflow, params,
                                                          spoken, revision))

    def _queue_request(self, row, workflow, params, spoken, revision) -> str:
        """Launch the revised generation and record the request behind it;
        return the line to say about it.

        The revision is the target's own recipe with its prompt pair edited and
        *the same seed* — "the same picture but without X" means the picture, so
        the one thing deliberately not re-rolled is the seed that draws it.
        """
        params = {**params, "positive_prompt": revision.positive,
                  "negative_prompt": revision.negative}
        key = self._folder_key_for(row.get("workflow_name") or "", params)
        if not self._reroll.start_prepared(key, workflow, params):
            return "🎤 couldn't queue the request — see the log"
        job = self._reroll.newest_job_for(key)
        logger.info("Request %r on %s: %s", spoken.heard, row.get("prompt_id"),
                    revision.describe())
        self._db.record_request(
            prompt_id=job.prompt_id, source_prompt_id=row["prompt_id"],
            heard=spoken.heard, term=revision.term, polarity=revision.polarity,
            action=revision.action, old_positive=revision.old_positive,
            old_negative=revision.old_negative, new_positive=revision.positive,
            new_negative=revision.negative,
        )
        self.refresh()  # the shelf shows the request the moment it is spoken
        return f"🎤 {revision.describe()} — generating"

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

    def enhancing_run(self, row: dict) -> EnhancingRun | None:
        """The standalone enhance being made of this image right now, or ``None``.

        The browser pane's tiles ask as they are built, so a folder generating
        with the Auto switch on reads honestly: the base render is out, on
        screen, and something better is on the way. Without it the folder looks
        like it is turning out plain images and ignoring the switch.

        Every live job is searched, not each folder's leading one: a batch of
        enhances goes out whole and its members share a settings key, so all but
        the first would read as not-cooking off the folder-facing view."""
        for key, job in self._enhance_jobs():
            if gallery.enhance_targets_row(job.params.get("input_image"), row):
                return self._enhancing_run(key, job)
        return None

    def _enhance_jobs(self) -> list:
        """Every standalone enhance in flight, as ``(folder key, job)``.

        The key comes along because the frames are held per folder
        (:attr:`_enhance_frames`), and a job on its own can't say which slot is
        its own."""
        return [(key, job)
                for key, jobs in self._reroll.jobs_by_folder.items()
                for job in jobs
                if job.workflow.name == gallery.ENHANCE_WORKFLOW]

    def _enhancing_run(self, key: str, job) -> EnhancingRun:
        """One enhance in flight, as the tile of the image it improves sees it.

        The frame goes only to a job actually rendering, for the reason
        :meth:`_pending_enhancement_for` spells out: a batch shares one folder
        and so one frame slot, and lending it to the ones queued behind would
        show each of those tiles a picture of a different image."""
        rendering = job.state == "running"
        return EnhancingRun(
            status="running" if rendering else "queued",
            frame=self._enhance_frames.get(key) if rendering else None,
            progress=job.last_progress,
            started_at=job.started_at,
            typical_seconds=self._typical_run_seconds(job),
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
        self._sync_history_buttons()
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
        self._sync_enhance_button()  # an image with no enhancement left awaits one

    def _reconcile_pending_enhancements(self):
        """Show the enhancement being made wherever the image it improves is.

        The info pane's version list leads with a live row while one is cooking,
        the tab's own preview streams the same frames, and the image's tile in
        the middle column streams them under its "Enhancing…" scrim — the same
        in-flight treatment work gets everywhere else in the app. The jobs are
        the gallery's, so the match is made here: every running standalone
        enhance against every tab's displayed row. Cheap enough to re-run on
        each frame; the panel updates its row in place.

        Every job of every folder, for the same reason :meth:`enhancing_run`
        reads them all: a batch of enhances shares one settings key, and a tab
        showing the third image of it must find its own run rather than the
        first.
        """
        running = self._enhance_jobs()
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
            prompt_id: self._enhancing_run(key, job)
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
        a different image. Queued, the tile says so instead — and "queued" covers
        both waits the same way, whether the job is still in this app's line or
        already sitting on ComfyUI, since neither has a frame to show."""
        for key, job in running:
            if gallery.enhance_targets_row(job.params.get("input_image"), row):
                rendering = job.state == "running"
                frame = self._enhance_frames.get(key) if rendering else None
                return ("running" if rendering else "queued", frame,
                        gallery.describe_enhance_params(job.params))
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
        """The show was dismissed (however): let it go, with the hold it put on
        videos, and hand the OSR2 back to whatever the toggle was driving. The mic
        is untouched — it answers to its own button, and "start slideshow" has to
        still be heard now there is no show to hear it over."""
        self._slideshow = None
        self._reroll.hold_videos(False)
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
            self._sync_history_buttons()
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

    def _generate_combination(self, image_id: str, video_id: str, send: bool = False):
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

        No lane reaches here: the lane chose which recipe ``video_id`` names, and
        from that point a Genau clip is made exactly like any other video. ``send``
        is the one thing that still rides along — a spoken "genau it" wants its
        clip handed on the moment it exists. The re-draw-the-frame answer to the
        reproduce dialog is the one path it can't reach: that launches the frame
        first and the clip second, under an id this never sees, so such a clip
        waits for the Send-to-Genau button like any other.
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
        prompt_id = self._reroll.start_prepared(key, workflow, params)
        if prompt_id:
            self._mark_for_sending(prompt_id, send)
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

    def _resolve_category(self, image_id: str, category: str, intent: str, then):
        """Find the recipe that fits ``category`` for the dropped image, then call
        ``then(video_id)`` with a rebuildable video's ``prompt_id`` — or ``None``.

        The local LLM picks the recipe whose starting scene matches this image's
        situation (:func:`recipe_match.smart_recipe`); if it's unreachable or finds no
        fit, it falls back to the act's most-used recipe
        (:func:`recipe_match.best_recipe`). ``None`` comes with a hint on screen, so a
        click never silently does nothing.

        Under ``GENAU`` both tiers see only the looping clips, so the hint names that
        narrower pool: the act may have plenty of long-form video and still nothing
        that could be made into a loop.

        The match runs off the UI thread and answers through ``then``, because asking
        the model is an HTTP round trip to something that thinks for several seconds
        — 4 to 9 of them, measured here. Inline, the window froze for exactly that
        long, worst of all on the spoken command, where the window is the picture
        being looked at. Everything the model needs is gathered first, so the pool
        thread touches neither the database nor a widget.
        """
        image_row = self._db.get_generation(image_id)
        if image_row is None:
            return
        image_prompts = {r.get("prompt_id"): r.get("positive_prompt") or "" for r in self._image_rows}
        candidates = [{**row, "start_scene": self._start_scene(row, image_prompts)}
                      for row in self._category_candidates()]
        scene = image_row.get("positive_prompt") or ""

        def match():
            return recipe_match.smart_recipe(
                category, scene, candidates,
                base_url=LOCAL_LLM_BASE_URL, model=LOCAL_LLM_MODEL,
                system_prompt=VIDEO_SCENE_MATCH_SYSTEM_PROMPT, intent=intent,
            ) or recipe_match.best_recipe(category, candidates, intent)

        def resolved(video_id):
            logger.info("combine: category=%s intent=%s image=%s -> recipe from %s",
                        category, intent, image_id, video_id)
            if video_id is None:
                self._say_no_recipe(category, intent)
            then(video_id)

        self._run_off_thread(match, resolved)

    def _run_off_thread(self, work, done):
        """Run one slow call away from the UI and hand its result back here.

        A seam as much as a call: the suite replaces this with a straight-through
        version, so a test can launch and inspect in one breath rather than
        pumping an event loop for every combine.
        """
        run_off_thread(work, done)

    def _say_no_recipe(self, category: str, intent: str):
        """Say the act has nothing to build a recipe from — in the corner of the
        fullscreen surface being spoken to when one is up, and in a dialog
        otherwise. A dialog thrown over a picture someone is looking at is the one
        place this must never appear."""
        what = ("looping “%s” clip" % category if intent == recipe_match.GENAU
                else "“%s” video" % category)
        if self._slideshow is not None:
            self._slideshow.note_voice_run(
                None, f"🎤 no past {what} to base a recipe on yet")
            return
        QMessageBox.information(
            self, "No recipe yet",
            f"No past {what} to base a recipe on yet — make one first, "
            "or drop a specific video instead.",
        )

    def _curated_combination(self, image_id: str, category: str,
                             intent: str = recipe_match.PLAYERS):
        """The ``(workflow, params)`` for ``category``'s overlay-curated ``intent``
        recipe on the dropped image — the pinned setup that outranks mining (see
        :func:`recipe_match.curated_recipe`), its seeds freshly rolled.

        ``None`` sends the caller on to mining: the act has no curated entry, the
        entry names an unknown or non-image-conditioned workflow, or the image
        row is gone or has no output file to seed from.
        """
        spec = recipe_match.curated_recipe(category, intent)
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

    def _generate_curated(self, image_id: str, category: str, intent: str,
                          send: bool) -> bool:
        """Launch ``category``'s curated ``intent`` recipe on the dropped image;
        ``False`` when the act has no usable curated entry, so the caller falls back
        to mining. No reproduce warning: the seeds are fresh every launch."""
        built = self._curated_combination(image_id, category, intent)
        if built is None:
            return False
        workflow, params = built
        logger.info("combine: category=%s intent=%s image=%s -> curated recipe",
                    category, intent, image_id)
        key = gallery.settings_folder_key(
            {"workflow_name": workflow.name, "workflow_version": workflow.version,
             "params_json": json.dumps(params)},
            gallery.build_image_config_index(self._image_rows),
        )
        prompt_id = self._reroll.start_prepared(key, workflow, params)
        if prompt_id:
            self._mark_for_sending(prompt_id, send)
            self._reveal_combination(key)
        return True

    def _mark_for_sending(self, prompt_id: str, send: bool):
        """Stamp a just-launched run to hand its clip on the moment it exists.

        Only a spoken "genau it" asks for this. Pressing Generate leaves the clip
        in the gallery for Send-to-Genau, because someone at the keyboard can look
        at it first; someone talking to a fullscreen picture cannot.
        """
        if send:
            self._db.mark_genau_requested(prompt_id)

    def _generate_category(self, image_id: str, category: str,
                           intent: str = recipe_match.PLAYERS, send: bool = False):
        """Run the recipe that fits ``category`` on the dropped image: the
        overlay's curated recipe when one is pinned for the act, else the mined
        exemplar handed off to the shared combine launch. ``intent`` chooses which
        lane both tiers answer from; ``send`` hands the finished clip to Genau
        without a second ask."""
        if self._generate_curated(image_id, category, intent, send):
            return
        self._resolve_category(
            image_id, category, intent,
            lambda video_id: video_id is not None
            and self._generate_combination(image_id, video_id, send),
        )

    def _open_category(self, image_id: str, category: str,
                       intent: str = recipe_match.PLAYERS):
        """Open the recipe that fits ``category`` as an editable generate tab — the
        Open-in-generator counterpart to :meth:`_generate_category`, honoring the
        same curated-over-mined order and the same lane.

        A run started from that tab is an ordinary Generate, so a Genau recipe opened
        this way is not auto-sent; the tab's own Send-to-Genau does it once the clip
        is there.
        """
        built = self._curated_combination(image_id, category, intent)
        if built is not None:
            workflow, params = built
            self._info_tabs.open_config(workflow.name, params)
            return
        self._resolve_category(
            image_id, category, intent,
            lambda video_id: video_id is not None
            and self._open_combination(image_id, video_id),
        )

    def _on_combine_intent_changed(self, _intent: str):
        """Re-grey the act list for the lane just chosen."""
        self._combine.set_available_categories(
            recipe_match.available_categories(
                self._rebuildable_videos(self._db.list_generations()),
                self._combine.selected_intent(),
            )
        )

    def _send_to_genau_if_requested(self, row: dict | None):
        """Hand a just-finished clip to the Genau lane, if that is what it was for.

        The last step of a spoken "genau it": the run was stamped at launch
        (:meth:`_mark_for_sending`), so nothing here has to remember it. Only a
        video with a file on disk that hasn't already gone is sent, and a failure
        is logged rather than shown — the clip is safe in the gallery either way,
        and Send-to-Genau is still there to retry with.
        """
        if not row or not row.get("genau_requested_at") or row.get("genau_exported_at"):
            return
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None or preview[1] != "video":
            return
        try:
            evolver_export.export_video(preview[0], EVOLVER_INBOX_DIR / GENAU_SOURCE)
        except Exception as e:
            logger.warning("Automatic send to Genau failed for %s: %s",
                           row.get("prompt_id"), e)
            return
        self._db.mark_genau_exported(row["prompt_id"])
        logger.info("genau: sent %s down the Genau lane", preview[0].name)

    def _genau_it(self, image_id: str | None) -> tuple[str | None, str]:
        """Animate an image as a Genau clip: the act read off its own prompt.

        Returns the id it launched on (``None`` when it didn't) and the line the
        speaking surface should say — the same shape as :meth:`_fix_part`, because
        the speaker is looking at the picture, not at this pane.

        Nothing is picked and nothing is dropped: the act comes from the image's
        prompt (:func:`recipe_match.category_for_prompt`), and from there this is
        the Genau lane's ordinary category path. An unreadable prompt or an act
        with no loop recipe behind it says so rather than animating the wrong
        thing. The run is stamped so its finished clip hands itself on without
        being asked again — the whole point of saying it out loud is that the
        picture is wanted moving *now*, and a second press to release it would be
        one the speaker isn't near a keyboard to make.
        """
        row = self._db.get_generation(image_id) if image_id else None
        if row is None or gallery.media_type_of_row(row) != "image":
            return None, "🎤 only a picture can become a Genau clip"
        category = recipe_match.category_for_prompt(row.get("positive_prompt") or "")
        if category is None:
            return None, "🎤 this prompt doesn't say what's happening — no act to animate"
        available = recipe_match.available_categories(
            self._rebuildable_videos(self._db.list_generations()), recipe_match.GENAU,
        )
        if category not in available:
            return None, f"🎤 no looping “{category}” clip to base a recipe on yet"
        logger.info("genau it: image=%s -> category=%s", image_id, category)
        self._generate_category(image_id, category, recipe_match.GENAU, send=True)
        return image_id, f"🎤 animating as a “{category}” loop"

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
        """The live tile's button: drop the variation it leads with.

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
        """Throw away one named run — a queue row's button, and a config tab's.

        A folder can hold several runs at once, so the one to drop is named rather
        than inferred from its folder; the redraw afterwards is the same. An auto
        loop in that folder takes it as a discarded seed and launches the next —
        after the drop, and a no-op while another of the folder's runs is still
        alive (:meth:`_start_reroll`), so the loop never doubles up.
        """
        key = self._job_folder_key(self._reroll.job_for_prompt(prompt_id))
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

    def _on_reroll_finished(self, key: str, prompt_id: str, origin: str = ""):
        """A re-roll saved its result (finalized by the controller): drop it as the
        info-pane source, rebuild so it shows as a normal thumbnail, and load it into
        the tab that launched it so a Generate ends on its finished output, not the
        placeholder."""
        # Which tab that is, read now: the rebuild below reconciles the finish, and
        # a tab lets go of its runs as they end. A launch no tab made — the folder
        # tile's "+" — has no owner unless a tab on that very folder claimed it, and
        # a variation the loop made has none at all: it is not what the user is
        # working on, so it never takes a tab's preview over.
        run = origin or prompt_id
        launcher = (None if run in self._auto_origins
                    else self._info_tabs.panel_that_launched(run))
        self._auto_origins.discard(run)
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
        self._send_to_genau_if_requested(finished_row)
        was_mirrored = key == self._selected_reroll_key  # the pane held its live frames
        # Let go of it — unless a loop is running here and the pane was pointed at
        # it, where the key stands for the loop rather than for this one variation:
        # someone watching it churn is watching what it does next, so the selection
        # waits for the variation after this one (see :meth:`_start_reroll`).
        if was_mirrored and not self._auto.is_active(key):
            self._clear_reroll_selection()  # refresh re-selects it as a finished thumbnail
        self.refresh()
        self._feed_slideshow_finished(finished_row)  # a show of its folder gains it
        self._show_reroll_result_in_tab(finished_row, launcher)
        if was_mirrored:
            self._show_mirrored_result(finished_row, launcher)
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
        self._sync_enhance_button()  # a landed enhance may retire the button
        self._reconcile_pending_enhancements()  # the live tile gives way to the level

    def _show_reroll_result_in_tab(self, finished_row: dict | None, launcher):
        """After a re-roll finishes, load its result into the tab that launched it
        — and into no other, ``launcher`` being ``None`` when no tab did.

        The finished row is handed over directly rather than resolved through the
        folder the job was keyed under: a re-roll of an old-generation folder
        lands its result in the current generation's folder (the settings key
        folds the workflow version in), so the job's key can name a folder whose
        newest row is not this result. Loading it leaves the tab showing the
        finished image/video and its footer — the completed end-state of a
        Generate — instead of the live-frame placeholder it held while running."""
        if launcher is not None and finished_row is not None \
                and gallery.produced_output(finished_row):
            launcher.show_completed_result(finished_row, self._image_rows)

    def _show_mirrored_result(self, finished_row: dict | None, launcher):
        """The run the info pane was mirroring has landed: put its picture where its
        live frames were, in the tab in front.

        The frames were streaming there whoever launched the run (see
        :meth:`InfoPaneTabs.show_reroll_frame`), so without this a pane watching a
        loop — or a fullscreen show opened over those frames — would sit on the
        last partial frame of a run that has finished. Only the preview changes:
        the tab holds no more of a run it didn't ask for. Skipped when the tab in
        front is the one that launched it, which has just been given the whole
        end-state instead.
        """
        if finished_row is None or not gallery.produced_output(finished_row):
            return
        if launcher is not None and launcher is self._info_tabs.current_config_panel():
            return
        self._info_tabs.show_reroll_result(finished_row)

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
        question :meth:`enhancing_run` asks, over every live job of every folder
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
        self._sync_history_buttons()

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
        self._sync_history_buttons()

    def _redo(self):
        """Re-apply what Undo took back. There is nothing to navigate to — a redo
        takes something away rather than restoring it — so this only rebuilds."""
        if not self._actions.can_redo():
            return
        self._info_tabs.clear_current_preview()
        self._actions.redo()
        self._browser.clear_selection()
        self.refresh()
        self._sync_history_buttons()

    def _sync_history_buttons(self):
        """Undo and Redo: enabled when there's a step that way, each saying in
        its tooltip which step that is."""
        undo_label = self._actions.undo_label()
        self._undo_btn.setEnabled(self._actions.can_undo())
        self._undo_btn.setToolTip(
            f"Undo: {undo_label}" if undo_label else "Nothing to undo"
        )
        redo_label = self._actions.redo_label()
        self._redo_btn.setEnabled(self._actions.can_redo())
        self._redo_btn.setToolTip(
            f"Redo: {redo_label}" if redo_label else "Nothing to redo"
        )

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
        # No rename for a folder named after what it holds — a model, a LoRA, a
        # workflow, a media root (see :func:`gallery.is_renamable`).
        rename_action = menu.addAction("Rename…") if gallery.is_renamable(group) else None
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
        if rename_action is not None and chosen == rename_action:
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
        self._sync_history_buttons()

    def _begin_inline_rename(self, item, _column):
        """Double-clicking a tree folder edits its name in place — a folder named
        after what it holds (see :func:`gallery.is_renamable`) has no name of its
        own to edit, and its row carries no editable flag either."""
        group = item.data(0, _GROUP_ROLE)
        if group is None or not gallery.is_renamable(group):
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
        self._sync_history_buttons()
        # Rebuild after the editor has fully closed to avoid deleting it mid-edit.
        QTimer.singleShot(0, self.refresh)

    def _begin_title_rename(self):
        """Double-clicking the title bar edits the selected folder's name — but not
        while several are picked, where the title is a count of them and the rename
        would land on whichever one happened to be current, and not over a search,
        where the title is the query and there is no folder behind it to rename.

        Only the folder's own name is edited, not the path on show: the editor is
        the size of that name, at the head of the path (see
        :meth:`EditableHeader.begin_edit`)."""
        if self._selection_group is not None or self._showing_search():
            return
        item = self._tree.currentItem()
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if group is not None and gallery.is_renamable(group):
            self._title.begin_edit(group.label)

    def _commit_title_rename(self, name: str):
        key = self._tree_view.selected_folder_key()
        if key is None:
            return
        self._actions.rename_folder(key, name.strip() or None)
        self._sync_history_buttons()
        # Rebuild on the next turn of the event loop rather than here. What
        # usually ends this edit is a click somewhere else in the window, and
        # "somewhere else" is most often a thumbnail — so refreshing inside the
        # editor's own focus-out deletes the browser pane that Qt is still
        # delivering that click to, and the app goes down with an access
        # violation. The tree's inline rename defers for the same reason.
        QTimer.singleShot(0, self.refresh)

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

    def _request_for(self, prompt_id: str) -> dict | None:
        """The spoken request that made this generation, with the item it was
        asked about resolved onto it — or ``None`` when nothing asked for it.

        Read off the shelf's own listing rather than the database, so the tab's
        link and the shelf's card can never disagree about what a request was
        about.
        """
        return next((item for item in self._request_items()
                     if item["prompt_id"] == prompt_id), None)

    def _request_items(self) -> list[dict]:
        """Every spoken request paired with what it made, newest first."""
        return gallery.requested_generations(self._db.list_requests(),
                                             self._db.list_generations())

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
            self._info_tabs.load_selection(row, self._image_rows,
                                           self._request_for(prompt_id))
        else:
            self._info_tabs.show_selection_preview(
                gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR), prompt_id
            )
        # Each generation looked at is its own browsing step, wherever it was
        # looked at: in a folder, on a shelf, or among a search's hits. The view it
        # was picked in goes on the stack with it, so Back returns to the item AND
        # to the pane it was one of — not to some other folder that also holds it.
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
        the folder's items the link meant is visible rather than guessed at.

        Following a link is a decision to go somewhere, so it puts a running
        search away first — this is the gesture a search result's double-click
        makes, and the folder it opens has to be what ends up on screen."""
        self._leave_search()
        self._show_generation(prompt_id)
        self._record_location(prompt_id)
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

    def _current_location(self) -> Location | None:
        """What the middle pane is showing right now, as a history stop: the tree
        row it is drawn from, any query running over it, and the item picked in it
        (``None`` with nothing open at all).

        Only for seeding history at startup, where there is no gesture to ask.
        Every stop after that is recorded by the gesture that made it, which knows
        which item it picked — see :meth:`_record_location`.
        """
        view = self._selected_folder_key()
        if view is None:
            return None
        item = self._selected["prompt_id"] if self._selected else None
        if item is not None and item not in self._browser.visible_prompt_ids():
            item = None  # left behind by the pane this one replaced
        return Location(view, self._search_query, item)

    def _record_location(self, item: str | None = None):
        """Record what the middle pane now shows: the folder or shelf the tree has
        selected, the query running over it, and ``item`` if the gesture picked one.

        Skipped while a rebuild or Back/Forward is what put it there — those move
        within history rather than onto it. Everything the pane can show is
        recorded the same way, so Back returns to the view the user was actually
        looking at, whatever kind of view it was.
        """
        if self._suppress_history:
            return
        view = self._selected_folder_key()
        if view is None:
            return  # nothing open: no view to come back to
        location = Location(view, self._search_query, item)
        current = self._history.current()
        if self._redrawing_the_same_search(location, current):
            # A search results pane redraws for reasons that are not navigations —
            # a sort, a widening landing, a generation finishing under a poll — and
            # a stop per redraw would fill history with the pane already on screen.
            if current.query == location.query:
                return
            # A query being narrowed is that same pane re-asked rather than another
            # one opened, so each pause overwrites its stop instead of adding one.
            self._history.replace(location)
        else:
            self._history.visit(location)
        self._sync_nav_buttons()

    @staticmethod
    def _redrawing_the_same_search(location: Location, current: Location | None) -> bool:
        """Whether ``location`` is the search stop at ``current`` being drawn again
        rather than somewhere new: the same folder, a query over it either way, and
        no item picked (picking a hit is a step within the results, not a redraw of
        them)."""
        return bool(location.query and location.item is None
                    and current is not None and current.query
                    and current.view == location.view)

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

    def _restore_location(self, location: Location):
        """Re-show a stop as it stood — its folder or shelf, the query that was
        running over it, and the item that was picked in it — without recording the
        move (which walks history rather than adding to it).

        A stop whose row the tree no longer has (a folder emptied by a delete)
        falls back to showing its item wherever it now lives, rather than leaving
        the press doing nothing at all.
        """
        self._suppress_history = True
        try:
            self._restore_query(location.query)
            row = self._item_by_key.get(location.view)
            if row is None:
                if location.item is not None:
                    self._show_generation(location.item)
                return
            if self._tree.currentItem() is row:
                # Already standing on that row, so setting it fires nothing — and
                # the pane still holds the search results, or the tile highlight,
                # this stop was recorded without. Draw it again by hand.
                self._on_folder_selected(row, None)
            else:
                self._tree.setCurrentItem(row)  # whose signal draws it
            if location.query:
                self._run_search()  # which takes the pane back off the folder again
            if location.item is not None:
                self._reveal_in_pane(location.item)
            else:
                # Nothing was picked at this stop, so nothing is picked on landing:
                # a folder still showing the item Back just left would look like the
                # press had done nothing at all.
                self._clear_metadata()
        finally:
            self._suppress_history = False

    def _restore_query(self, query: str):
        """Put the search box back to what it held at a history stop.

        Set without its typing signals: those debounce and re-run, which would
        answer a restore with a search a beat later, over whatever the restore had
        by then moved on to. The expander's cache is consulted so a query that was
        widened comes back widened, and one it never answered comes back anyway.
        """
        self._search_edit.blockSignals(True)
        try:
            self._search_edit.setText(query)
        finally:
            self._search_edit.blockSignals(False)
        self._clear_search_state()
        self._search_query = query
        if query:
            self._search_expansions = self._search_expander.cached(query)

    def _reveal_in_pane(self, prompt_id: str):
        """Land on an item the pane is already showing: its tile picked and
        scrolled to, its preview back in the info pane. Silent if the pane has no
        tile for it — a Recents page not drawn yet, a row since deleted — which
        leaves the view itself restored rather than jumping somewhere else."""
        if prompt_id in self._browser.visible_prompt_ids():
            self._browser.reveal_tile(prompt_id)
            self._on_thumbnail_clicked(prompt_id)

    def _sync_nav_buttons(self):
        self._back_btn.setEnabled(self._history.can_go_back())
        self._forward_btn.setEnabled(self._history.can_go_forward())

    def _sync_action_buttons(self):
        """Re-aim the act-on-this trio together.

        Star, Enhance and Delete all follow the same target — the picked
        thumbnails, else the folder on screen — so the events that move that
        target re-read all three at once rather than each on its own."""
        self._sync_star_button()
        self._sync_enhance_button()
        self._sync_enhance_panel()
        self._sync_delete_button()
        self._sync_toolbar_gaps()

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
