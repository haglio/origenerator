from __future__ import annotations

import json
import logging
import random
from typing import NamedTuple

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from origenerator import (
    gallery,
    recovery,
    search,
    timing,
)
from origenerator.base_backfill import TARGET_KEY as BASE_RENDER_TARGET_KEY
from origenerator.base_backfill import queue_base_renders
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_api import format_execution_error
from origenerator.comfyui_client import ComfyUIClient, ForeignQueue
from origenerator.config import (
    COMFYUI_OUTPUT_DIR,
    THUMB_DIR,
    TRASH_DIR,
)
from origenerator.db import Database
from origenerator.experiments.background import queue_experiments
from origenerator.experiments.policy import ExperimentPolicy
from origenerator.fun_time_mode import FunTimeSession
from origenerator.gallery_actions import GalleryActions
from origenerator.generation_config import (
    filled_params,
    randomize_seeds,
    would_reproduce_a_completed_run,
)
from origenerator.gui import corner_controls
from origenerator.gui.ambient_audio import AmbientAudio
from origenerator.gui.auto_generate_controller import AutoGenerateController
from origenerator.gui.browser_pane import (
    BrowserPane,
    BrowserScrollArea,
    PaneHost,
    TreeNavigation,
)
from origenerator.gui.combine_controller import CombineController
from origenerator.gui.deferred import defer
from origenerator.gui.editable_header import EditableHeader
from origenerator.gui.enhance_controller import EnhanceController
from origenerator.gui.find_bar import FindBar
from origenerator.gui.folder_request_tile import FolderRequestTile
from origenerator.gui.folder_tree import TREE_KEY_ROLE as _TREE_KEY_ROLE
from origenerator.gui.gallery_navigation import NavigationController
from origenerator.gui.gallery_search import GallerySearchController
from origenerator.gui.gallery_tree import (
    EXPERIMENTS_KEY as _EXPERIMENTS_KEY,
)
from origenerator.gui.gallery_tree import (
    EXPERIMENTS_LABEL as _EXPERIMENTS_LABEL,
)
from origenerator.gui.gallery_tree import (
    GROUP_ROLE as _GROUP_ROLE,
)
from origenerator.gui.gallery_tree import (
    RECENTS_KEY as _RECENTS_KEY,
)
from origenerator.gui.gallery_tree import (
    RECENTS_LABEL as _RECENTS_LABEL,
)
from origenerator.gui.gallery_tree import (
    REQUESTS_KEY as _REQUESTS_KEY,
)
from origenerator.gui.gallery_tree import (
    REQUESTS_LABEL as _REQUESTS_LABEL,
)
from origenerator.gui.gallery_tree import (
    STARRED_KEY as _STARRED_KEY,
)
from origenerator.gui.gallery_tree import (
    STARRED_LABEL as _STARRED_LABEL,
)
from origenerator.gui.gallery_tree import (
    TRASH_KEY as _TRASH_KEY,
)
from origenerator.gui.gallery_tree import (
    TRASH_LABEL as _TRASH_LABEL,
)
from origenerator.gui.gallery_tree import (
    GalleryTree,
    SideModel,
)
from origenerator.gui.generation_queue import GenerationQueue
from origenerator.gui.inflight import (
    discard_run_text,
    discard_run_tooltip,
    queue_wait_text,
    stop_loop_text,
    stop_loop_tooltip,
)
from origenerator.gui.info_pane_tabs import InfoPaneTabs
from origenerator.gui.looping_preview import set_previews_paused
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.motion_panel import MotionPanel
from origenerator.gui.off_thread import run_off_thread
from origenerator.gui.orientation import (
    LANDSCAPE as _LANDSCAPE,
)
from origenerator.gui.orientation import (
    ORIENTATION_LABELS as _ORIENTATION_LABELS,
)
from origenerator.gui.orientation import (
    ORIENTATIONS as _ORIENTATIONS,
)
from origenerator.gui.orientation import (
    base_of as _base_of,
)
from origenerator.gui.orientation import (
    filter_rows,
    oriented_key,
    requested_orientation,
    split_rows,
)
from origenerator.gui.orientation import (
    orientation_of as _orientation_of,
)
from origenerator.gui.orientation import (
    split_key as _split_shelf_key,
)
from origenerator.gui.osr2_driver import Osr2Driver
from origenerator.gui.osr2_motion_driver import Osr2MotionDriver
from origenerator.gui.prompt_find import PromptFind
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.reroll_prompt import (
    offer_reroll,
)
from origenerator.gui.reroll_tile import RerollTile
from origenerator.gui.search_expander import SearchExpander
from origenerator.gui.show_director import ShowDirector
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.gui.toolbar_bank import (
    AUTO_ELSEWHERE_TIP,
    BankActs,
    BankState,
    Button,
    ToolbarBank,
)
from origenerator.gui.voice_router import VoiceRouter
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.slideshow import in_order
from origenerator.trash import Trash
from origenerator.voice.app_commands import AppCommand
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.derived_size import resolve_input_image_path

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE
from shared_ui.spacing import (
    BUTTON_GROUP_GAP,
)
from shared_ui.tick_control import TickControl

logger = logging.getLogger(__name__)


_POLL_INTERVAL_MS = 1500
_PANE_MARGINS = (8, 8, 8, 8)  # breathing room inside each of the three panes
# How long the search waits after the last keystroke before asking the local LLM
# to widen the query. Long enough to be a real pause rather than a gap between
# two characters — the table-widened results are already on screen throughout, so
# nothing is being waited *for*; this only decides how often the model is asked.
_SEARCH_EXPAND_DELAY_MS = 700
# How long the field waits after the last keystroke before searching at all. A
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
# The synthetic shelves, as back/forward history locations: each is a place the
# user can be standing, so a visit to one is recorded and restored by key rather
# than by the generation that happened to be picked there.
_SHELF_KEYS = (_RECENTS_KEY, _STARRED_KEY, _EXPERIMENTS_KEY, _REQUESTS_KEY,
               _TRASH_KEY)
# Their plain names, without the waiting-work counts their tree rows carry —
# what the search field and header call a shelf it is searching.
_SHELF_LABELS = {
    _RECENTS_KEY: _RECENTS_LABEL, _STARRED_KEY: _STARRED_LABEL,
    _EXPERIMENTS_KEY: _EXPERIMENTS_LABEL, _REQUESTS_KEY: _REQUESTS_LABEL,
    _TRASH_KEY: _TRASH_LABEL,
}


class _Running(NamedTuple):
    """What the app is doing under its own steam — everything Esc turns off, and
    everything a second Esc turns back on.

    Not the mic, which Esc never touches, and not the work already in flight: a
    generation that is rendering lands either way. What is here is the standing
    instructions — the device, the loop, the show, the sound.
    """

    osr2: bool = False       # the device switch: a funscript, or the motion under it
    motion: bool = False     # the bare motion, running with the switch off
    auto: str | None = None  # the folder looping, if one is
    audio: bool = False      # the audio bed
    show: bool = False       # a fullscreen slideshow is up
    # ...and the pass it was playing, to take up again. A show following a
    # generation in flight has none, which is why this is asked separately from
    # whether there is a show at all.
    show_pass: tuple | None = None

    @property
    def anything(self) -> bool:
        return bool(self.osr2 or self.motion or self.auto or self.audio or self.show)


class _SearchScope(NamedTuple):
    """What a search covers: the selected row's breadcrumb and the generations it
    holds (``None`` for no restriction at all).

    The path rather than the folder's own name, everywhere it is said: a folder
    is named by a short code, so "Search 3A7F2C10…" names nothing the user can
    place, where the path they clicked down does.
    """

    path: str
    ids: set[str] | None
def _is_reusable_workflow(workflow_name) -> bool:
    """Whether the app can rebuild this workflow from its template.

    The gate on the gallery re-roll: a re-roll re-runs a folder's own settings
    with a fresh seed, which needs a template to build the graph from.
    """
    return (workflow_name or "") in WORKFLOW_REGISTRY


def _lower_divider() -> QFrame:
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


class GalleryView(QWidget):
    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryActions | None = None,
                 osr2_motion: Osr2MotionDriver | None = None,
                 ambient_audio: AmbientAudio | None = None,
                 search_expander: SearchExpander | None = None,
                 experiment_policy: ExperimentPolicy | None = None,
                 fun_time: FunTimeSession | None = None):
        super().__init__(parent)
        self._db = db
        self._client = client
        # The Fun Time session hosting this app, or None standalone.  Inside one
        # the layout goes vertical, the fullscreen surfaces land on the satellite
        # regions, and the OSR2 is Fun Time's alone (see origenerator.fun_time_mode).
        self._fun_time = fun_time
        # The app-global audio bed under the toolbar's audio switch: several
        # library clips at once, sound only. Injectable so tests never open a
        # real media backend. Built before _build_ui, whose switch drives it.
        self._ambient_audio = (
            ambient_audio if ambient_audio is not None else AmbientAudio(parent=self)
        )
        # The one app-global motion driver (genau's engine, no funscript needed):
        # every surface — this window and whatever slideshow is up —
        # drives it through the shared motion keys, and while it holds the device
        # the funscript reconcile stands down. Injectable so tests never touch
        # the broker. Built before _build_ui, which wires its window feedback.
        # None inside a Fun Time session: the OSR2 there is the main player's
        # alone, so no surface of this app may reach the device.
        if fun_time is not None:
            self._osr2_motion = None
        else:
            self._osr2_motion = osr2_motion if osr2_motion is not None else Osr2MotionDriver(parent=self)
        # How long a slide holds the screen, app-wide: Genau's console shows
        # it as clip seconds and sets it, from whichever window the console
        # is on — including this one, with nothing playing, where it is what
        # the next slideshow opens at.
        self._pace = SlideshowPace(parent=self)
        # Guards the one reconcile that owns both drive sources: starting or
        # stopping the motion is something it does, not something it reacts to.
        self._reconciling_osr2 = False
        self._build_the_queue_of_runs(db, client)
        self._actions = actions or GalleryActions(
            db, COMFYUI_OUTPUT_DIR, Trash(TRASH_DIR),
            release_files=self._release_held_media, thumb_dir=THUMB_DIR,
            cancel_enhancements=lambda rows: self._enhance.cancel_for_delete(rows),
        )
        # Derives the background experiments this gallery hands ComfyUI as the
        # app closes (the Experiments shelf's switch): variations of the user's
        # own work, landing on that shelf for review at the next launch.
        self._experiment_policy = experiment_policy or ExperimentPolicy(
            registry=WORKFLOW_REGISTRY, rng=random.Random()
        )
        self._forget_the_listing()
        self._build_the_panes(db, client, search_expander)
        # What another app has on the shared ComfyUI, re-read on every poll so the
        # lower bar can say the server is busy before a Generate goes in after it.
        self._foreign_queue = ForeignQueue(running=[], pending=[])
        # What the last Esc took off, for the next one to put back — cleared as
        # soon as it is put back, so the key goes on alternating.
        self._stopped_by_escape: _Running | None = None
        self._build_ui()
        self._voice.bind_the_bank(
            auto=self._bank.auto, audio=self._bank.audio, drive=self._bank.drive,
            mic=self._bank.mic,
            enhance=(self._bank.enhance, self._enhance.enhance_the_selection),
            actions={
                AppCommand.BACK: (self._bank.back, self._navigation.go_back),
                AppCommand.FORWARD: (self._bank.forward, self._navigation.go_forward),
                AppCommand.CULL: (self._bank.delete, self._delete_selection),
                AppCommand.STAR: (self._bank.star, self._star_selection),
                AppCommand.UNDO: (self._bank.undo, self._undo),
                AppCommand.REDO: (self._bank.redo, self._redo),
                AppCommand.GROUP: (self._bank.group, self._group_selection),
            },
        )
        self._re_aim()
        # Catch Delete/Ctrl+Z application-wide while the Gallery tab is showing.
        # Neither keyPressEvent nor a shortcut delivered the key in the running
        # app — a clicked thumbnail's key press never reached the view through
        # the scroll area — so intercept it before delivery, independent of which
        # widget holds focus. Taken off again in closeEvent, and re-armed by
        # showEvent for a view shown after one.
        self._intercept_the_rooms_keys(True)

        self._poll_inflight = False  # a tick's reads are out; don't stack more
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _build_the_queue_of_runs(self, db, client):
        """The generation queue: the controller that owns the live jobs, the loop
        that keeps one folder generating, and what each of those has to remember
        between launches.
        """
        # The re-roll controller owns the live jobs and their DB lifecycle; the
        # view reacts to its signals with the redraws they call for.
        self._reroll = RerollController(db, client)
        self._reroll.changed.connect(self._rerender_current_leaf)
        self._reroll.changed.connect(self._reconcile_generating)
        self._reroll.changed.connect(lambda: self._enhance.reconcile())
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
        # The folder whose running re-roll is the gallery's selected item (its
        # tile lit in the middle column), and that tile. Which tab shows the
        # run's frames full size is the tabs' own affair: a tab follows the
        # folder it launched into or was pointed at (see
        # :meth:`GenerateConfigPanel.watch_folder`), and the frames are routed
        # to it by folder key, never to "the tab in front".
        self._selected_reroll_key: str | None = None
        self._reroll_tile: RerollTile | None = None

    def _forget_the_listing(self):
        """Empty every slot a rebuild fills in.

        Called once at construction and never again: a rebuild replaces what is
        here rather than clearing it first, so these are the values a gallery has
        before its first refresh.
        """
        self._image_rows: list[dict] = []
        # Pictures whose spoken "genau it" is still choosing a recipe, so a
        # second one said into that wait is refused rather than queued twice
        # (:meth:`_already_genaud`). Only until the launch is a row.
        self._live_ids: set[str] = set()  # the gallery's own rows, minus the trash
        self._image_index: dict | None = None  # memo, dropped by every rebuild

    def _build_the_panes(self, db, client, search_expander):
        """The three panes' own objects, in the order they need each other: the
        search over the tree, the browser in the middle, the trail across both,
        then the shows, the combine, the enhance and the spoken words that all
        read those.

        Before ``_build_ui``, which places the widgets each of them builds.
        """
        # --- the gallery search (the field over the tree, the results in the middle
        # pane). The index is rebuilt with the gallery and queried on each
        # keystroke; the expander widens the query's words through the local LLM
        # once typing stops, and re-runs the search when its answer lands. Both
        # are built before _build_ui, whose field drives them.
        self._search = GallerySearchController(
            self, parent=self, expander=search_expander)
        # The held deletions the Trash shelf lists, as gallery rows re-pointed at
        # their files in the trash — the rows under everything a deleted item can
        # still do (see :meth:`row_for`).
        self._held_rows: list[dict] = []
        self._selected_row: dict | None = None  # the saved generation on display in the info pane
        # The browser pane renders the middle column (tiles / thumbnails / shelves)
        # and owns the thumbnail multi-selection and in-flight cards. Its signals
        # carry every gesture made on a tile; the handlers here answer them. The
        # scroll area is its canvas — built here so it can be handed over, placed
        # into the layout by _build_ui.
        self._scroll = BrowserScrollArea()
        self._browser = BrowserPane(
            self._scroll, db, self._reroll, self._auto,
            TreeNavigation(
                selected_folder_key=self.selected_folder_key,
                folder_context=self._folder_context,
                group_for_key=self.group_for_key,
            ),
            # Each answer looks itself up through self at call time, as the
            # pane's old view reads did — so a per-instance stub (tests fake
            # animated_preview this way) still lands.
            PaneHost(
                media_types=lambda: self.media_types(),
                image_rows=lambda: self._image_rows,
                animated_preview=lambda row: self.animated_preview(row),
                enhancing_run=lambda row: self._enhance.run_of(row),
                enhance_settings=lambda: self._enhance.settings,
                experiments_enabled=lambda: self.experiments_enabled(),
                add_lead_tiles=lambda flow, group: self._add_lead_tiles(flow, group),
            ),
        )
        self._browser.pane_reset.connect(self._forget_reroll_tile)
        self._browser.thumbnail_activated.connect(self._on_thumbnail_clicked)
        self._browser.tab_pin_requested.connect(self.pin_config_tab)
        self._browser.item_jump_requested.connect(self.follow_link)
        self._browser.folder_open_requested.connect(self._open_folder_tile)
        self._browser.reveal_reroll_requested.connect(self._reveal_reroll)
        self._browser.folder_menu_requested.connect(self._folder_context_menu)
        self._browser.menu_requested.connect(self.generation_menu)
        self._browser.trash_menu_requested.connect(self._trash_menu)
        self._browser.item_action_triggered.connect(self.run_item_action)
        self._browser.seed_reroll_requested.connect(self._reroll_item_seed)
        self._browser.experiment_verdict.connect(self._on_experiment_verdict)
        self._browser.trash_action_triggered.connect(self._on_trash_action)
        self._browser.cancel_requested.connect(self._cancel_job)
        self._browser.selection_changed.connect(self._re_aim)
        self._fingerprint = None
        self._pending_key: str | None = None  # a folder to open once the tree exists
        self._pending_selection: str | None = None  # a generation to highlight once shown
        # A combine's brand-new folder doesn't exist until its job finishes; hold
        # its key so _on_reroll_finished can drill in once the tree has the folder.
        self._pending_combine_key: str | None = None
        self._editing_key: str | None = None  # folder being renamed inline
        # The user's own folders, resolved against the live tree on each rebuild,
        # and the throwaway one a multi-selection stands up (None with 0 or 1 row
        # picked). Both are CustomGroups, so the pane, breadcrumb, and slideshow
        # treat them exactly as they treat a derived folder.
        self._custom_folders: list = []
        self._selection_group = None
        self._navigation = NavigationController(self, search=self._search)
        # What the trail allows right now, as it last told us: the bank is written
        # from one state, so Back and Forward read it there rather than being set
        # on their own (see :meth:`nav_state_changed`).
        self._trail = (False, False)
        # The fullscreen shows: the one in front, the two a hosting session
        # runs on its satellite regions, and everything that keeps them
        # current. Built after the browser it reads and before _build_ui,
        # whose slideshow button starts one.
        self._shows = ShowDirector(
            self, db=db, browser=self._browser, reroll=self._reroll,
            pace=self._pace, motion=self._osr2_motion, fun_time=self._fun_time)
        # Combine: a video's recipe run again on a dropped picture, and the
        # spoken "genau it" that asks for the same thing out loud
        # (:mod:`origenerator.gui.combine_controller`). It builds its own panel,
        # which _build_ui places under the tree.
        self._combine = CombineController(
            self, parent=self, db=db, reroll=self._reroll, client=client,
            info_tabs_of=lambda: self._info_tabs, shows=self._shows)
        # The standalone enhance: its settings panel, what the Enhance button
        # would run on, and the live run's appearance on every surface showing
        # the picture it improves
        # (:mod:`origenerator.gui.enhance_controller`). It builds its own panel,
        # which _build_ui seats in the footer.
        self._enhance = EnhanceController(
            self, db=db, reroll=self._reroll, browser=self._browser,
            shows=self._shows, info_tabs_of=lambda: self._info_tabs)
        # A thumbnail or a preview picked up anywhere lights the slot it fits,
        # so the drop target is obvious from the start of the gesture.
        self._browser.drag_started.connect(self._combine.drag_started)
        self._browser.drag_ended.connect(self._combine.drag_ended)
        # Everything spoken: the microphone, the caption that says what it heard,
        # and where each word lands (:mod:`origenerator.gui.voice_router`). Its
        # caption is placed by _build_ui, and the bank it presses is bound to it
        # once _build_ui has built one.
        self._voice = VoiceRouter(self, parent=self, db=db, shows=self._shows,
                                  client=client, motion=self._osr2_motion)
        self._folder_history: list[str] = []  # folders the user opened, to return to after a delete

    def _intercept_the_rooms_keys(self, intercepting: bool):
        """Take (or hand back) every key the application delivers.

        Taking it is idempotent — Qt moves a filter already on the list rather
        than adding a second copy — so ``showEvent`` can re-arm without counting.
        """
        app = QApplication.instance()
        if app is None:
            return
        if intercepting:
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)

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
                # The OSR2 motion keys work right here in the main window too —
                # not only in the fullscreen show — under the same guards that
                # keep them out of text fields and other windows.
                if (not event.modifiers()
                        and apply_motion_key(self._osr2_motion, event.key(),
                                             on_drive_toggle=self.toggle_osr2_drive)):
                    self._motion_panel.refresh()
                    return True
        return super().eventFilter(obj, event)

    def _handle_escape(self) -> bool:
        """Esc turns off everything the app is doing, wherever focus is: the OSR2
        drive (a funscript or the genau motion), the auto-generate loop, the
        fullscreen slideshow, and the audio bed. Pressed with all of it off, it
        starts the room instead: what the last press took away — the same folder
        looping, the same show on the same picture, the sound, the device — or,
        with nothing to put back, all four from a standing start. So the key is
        the one thing to reach for either way, on a freshly opened app as much
        as on a running one, the way leaving an OmniPause hands the room back.

        Everything except the microphone, which is why that switch stands on its
        own in the bank. A stop that closed the mic too would take with it the
        one way of starting anything again without reaching for the keyboard —
        and the room is usually mid-something when Esc is pressed.

        It yields when a dialog or popup owns the keystroke, so Esc still closes
        a combo dropdown, and when some other window is up. Our own slideshow is
        not that: it closes itself on Esc, but closing only the show would leave
        the loop, the device and the sound running under it, which is the
        opposite of what the key means. Returns whether it acted.
        """
        if self._other_window_owns_keys() and not self._shows.is_in_front():
            return False
        running = self._running_now()
        if running.anything:
            # Whatever is on when it is pressed, however it came to be on — so
            # something started by hand after a stop is taken away by the next
            # Esc, and is what the one after that offers back.
            self._stopped_by_escape = running
            self._stop_running(running)
            return True
        if self._escape_cancels_something():
            return False
        self._resume(self._stopped_by_escape or self._all_of_it())
        self._stopped_by_escape = None
        return True

    def _escape_cancels_something(self) -> bool:
        """Whether Esc means "not that" to something on screen: an open find, or a
        text field being typed in — a folder being renamed, a prompt being
        written. Both are keystrokes away from the key's other meaning, and
        starting the whole room up out of one that meant "cancel this" is the one
        way this could be worse than the key doing nothing at all."""
        if self._find_bar.isVisible():
            return True
        focus = QApplication.focusWidget()
        return isinstance(
            focus, (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)
        )

    def _running_now(self) -> _Running:
        """Everything the app is doing under its own steam right now."""
        show = self._shows.showing
        return _Running(
            osr2=self._osr2_enabled,
            # Space reaches the switch rather than the motion, so a motion
            # running with the switch off is one something else started — the
            # stop has always covered that case, and so does the resume.
            motion=self._osr2_motion.active and not self._osr2_enabled,
            auto=self._auto.active_key(),
            audio=self._bank.audio is not None and self._bank.audio.isChecked(),
            show=show is not None,
            show_pass=show.playing_now() if show is not None else None,
        )

    def _all_of_it(self) -> _Running:
        """Everything on, for an Esc pressed with nothing running and nothing held
        back — a freshly opened app, or a session that has not been stopped yet.

        The same four switches, aimed at whatever is in front: the folder on
        screen loops, the folder on screen plays, the sound comes up, the device
        drives. Each one is only what its own button does, so a folder that can't
        be looped or has nothing to show simply doesn't start.
        """
        # The folder's own key, side stripped: a loop belongs to the folder, and
        # both sides of the tree draw the same one.
        return _Running(osr2=True, auto=_base_of(self.selected_folder_key()),
                        audio=True, show=True)

    def _stop_running(self, running: _Running) -> None:
        """Take all of ``running`` off."""
        if running.osr2:
            # One switch, so one thing to turn off: untoggling stops whichever
            # source is on the device — a funscript drive or the motion.
            self._bank.drive.setChecked(False)
        elif running.motion:
            self._osr2_motion.stop()
        if running.auto:
            self._auto.stop_all()
        if running.show:
            self._shows.showing.close()  # the director lets it go
        if running.audio:
            if self._bank.audio is not None:
                self._bank.audio.setChecked(False)  # drives _on_audio_toggle → silence

    def _resume(self, stopped: _Running) -> None:
        """Put back what Esc took away.

        In the order that leaves each one aimed where it was: the show goes up
        before the device switch, so the one reconcile that picks a drive source
        finds the show's video in front of it exactly as it did the first time.

        A loop resumes in the folder it was running in rather than the one on
        screen — the gallery is somewhere else by now as often as not, and the
        loop was never about where the user is looking.

        A show with no pass under it opens on what is in front instead, which is
        both the standing start and the show that was following a generation in
        flight: that one has no pass to take up, and what it was watching has
        landed or gone by now.
        """
        if stopped.audio:
            if self._bank.audio is not None:
                self._bank.audio.setChecked(True)
        if stopped.show_pass is not None:
            items, index, dwell_ms = stopped.show_pass
            self._shows.open(items, start=index, image_dwell_ms=dwell_ms,
                             shuffle=in_order)
        elif stopped.show:
            self._shows.start()
        if stopped.auto:
            self._begin_auto(stopped.auto)
            self._re_aim()      # a resumed loop lights its switch again
            self._sync_discard_buttons()  # and its run offers a next seed, not a cancel
        if stopped.osr2:
            self._bank.drive.setChecked(True)
        elif stopped.motion:
            self._osr2_motion.start()

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
        """Put the three panes on screen, in the order their contents need.

        Each pane builds itself and hands back the widget it built; the two
        arrangers at the foot are the one place the hosted and standalone shapes
        differ. Sequence rather than grouping is what this preserves -- the
        motion, the sound and the device driver must exist before the widgets
        that wire them, and each pane's own comments say which.
        """
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
        #
        # Hosted by Fun Time the rect is an upright column, so the panes fold
        # into _stack instead of sitting side by side: the info pane on top, the
        # tree and browser as one row under it, and the queue across the foot of
        # all three: hosted, the queue belongs to the window rather than to the
        # folder column, so there is no _left_column at all on that side.
        self._panes = QSplitter(Qt.Orientation.Horizontal)
        self._panes.setChildrenCollapsible(False)  # a pane can't be dragged shut
        self._panes.setHandleWidth(6)
        self._folder_panes = QSplitter(Qt.Orientation.Horizontal)
        self._folder_panes.setChildrenCollapsible(False)
        self._folder_panes.setHandleWidth(6)
        self._stack = None
        if self._fun_time is not None:
            self._stack = QSplitter(Qt.Orientation.Vertical)
            self._stack.setChildrenCollapsible(False)
            self._stack.setHandleWidth(6)
        toc = self._build_toc_pane()
        # Hosted, the tree is the upright column's own left edge rather than a
        # part of the folder row, so it goes straight into the outer splitter.
        # Placed here rather than by the arrangers: it is the folder row's first
        # widget, and a splitter takes them in the order they arrive.
        (self._panes if self._stack is not None else self._folder_panes).addWidget(toc)
        browser = self._build_browser_pane()
        self._folder_panes.addWidget(browser)
        # A strip under those two lists every generation in flight — the app hands
        # ComfyUI one at a time, so a batch of Generates is a queue — reachable
        # from any folder or config tab. Fed on every rebuild and poll; a row
        # dragged to a new place asks the controller to re-line the queue. Its top
        # edge is this column's splitter handle, so a long queue can be dragged
        # open at the cost of the folder listing above it.
        self._queue = GenerationQueue()
        self._queue.reorder_requested.connect(self._reroll.reorder)
        self._queue.clear_queue_requested.connect(self.clear_foreign_queue)
        info_pane = self._build_info_pane()
        if self._stack is not None:
            self._arrange_hosted(toc, browser, info_pane)
        else:
            self._arrange_standalone(toc, browser, info_pane)
        layout.addWidget(self._stack if self._stack is not None else self._panes, 1)

    def _build_toc_pane(self):
        """The left pane: the two folder trees under the voice caption, the
        search field and the media filter, with the combine panel at their foot.
        """
        # TOC pane: folder tree (media -> workflow -> model -> LoRA -> [source image]
        # -> settings; a LoRA-less workflow collapses the LoRA level to one
        # "(no LoRA)" folder, and the source-image level shows only for
        # image-conditioned workflows). Folders start collapsed and only expand on
        # the disclosure arrow; double-click renames.
        # One tree per shape, each under a standing label and each scrolling on
        # its own: the table of contents exists twice over, and which half you
        # are in is what decides the screen a slideshow goes to.
        self._tree = SplitFolderTree(_GROUP_ROLE)  # its rows offer star/delete themselves
        self._tree_view = GalleryTree(self._tree)  # fills it + the key/prompt→item maps
        self._tree.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._tree.setExpandsOnDoubleClick(False)
        self._tree.context_menu_requested.connect(self._on_tree_context_menu)
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
        toc_column = QVBoxLayout(toc)
        toc_column.setContentsMargins(*_PANE_MARGINS)
        # Voice's caption sits above everything else in this pane — the top-left
        # corner of the view, where it obscures no control while it's up.
        toc_column.addWidget(self._voice.status)
        # The gallery search: its field over the tree, its results bar over the
        # browser pane below (:mod:`origenerator.gui.gallery_search`).
        toc_column.addWidget(self._search.field)
        # The gallery's image/video filter: two ticks saying which kinds of
        # generation the gallery is made of at all, both on so it opens showing
        # everything. It sits between the search field and the tree because it
        # prunes the tree: a gallery with videos switched off has no video folders
        # in it, and no video tiles in the pane beside them either. (It replaces a
        # pair that filtered the Recents shelf alone, which could only ever answer
        # "which of these do I want to look at" for one shelf.)
        self._image_cb = TickControl("Images")
        self._video_cb = TickControl("Videos")
        for tick in (self._image_cb, self._video_cb):
            tick.setChecked(True)
            tick.setToolTip(
                "Which kinds of generation the gallery lists — the folders below "
                "as well as the items in the pane beside them"
            )
            tick.toggled.connect(self._on_media_filter_changed)
        media_filter = QWidget()
        media_row = QHBoxLayout(media_filter)
        media_row.setContentsMargins(0, 0, 0, 0)
        media_row.addWidget(self._image_cb)
        media_row.addWidget(self._video_cb)
        media_row.addStretch(1)
        toc_column.addWidget(media_filter)
        toc_column.addWidget(self._tree, 1)  # the trees take the height; combine sits below
        toc_column.addWidget(self._combine.panel)
        return toc

    def _build_browser_pane(self):
        """The middle pane: the folder's path, the button bank under it, the
        shelf's own bars, and the flowing contents -- with the two app-wide
        panels standing at its foot, under a hairline of their own.
        """
        # Browser pane: a header (the folder's path, then a back/forward/undo
        # toolbar under it) over the flowing contents. Double-clicking the path
        # renames the folder it ends at.
        browser = QWidget()
        browser_column = QVBoxLayout(browser)
        browser_column.setContentsMargins(*_PANE_MARGINS)
        self._title = EditableHeader()
        self._title.edit_requested.connect(self._begin_title_rename)
        self._title.edited.connect(self._commit_title_rename)
        browser_column.addWidget(self._title)
        # The button bank over this pane (:mod:`origenerator.gui.toolbar_bank`).
        # It builds and lays out every button and is written from one state; what
        # each button depends on is gathered in :meth:`bank_state`.
        self._bank = ToolbarBank(
            BankActs(
                go_back=self._navigation.go_back,
                go_forward=self._navigation.go_forward,
                undo=self._undo,
                redo=self._redo,
                start_show=self._shows.start,
                toggle_auto=self._toggle_auto,
                go_to_looping_folder=self._go_to_looping_folder,
                star=self._star_selection,
                enhance=self._enhance.enhance_the_selection,
                group=self._group_selection,
                delete=self._delete_selection,
                toggle_audio=self._on_audio_toggle,
                toggle_mic=self._voice.mic_toggled,
                toggle_drive=self._on_osr2_toggle,
            ),
            hosted=self._fun_time is not None,
            device=self._osr2_motion is not None,
        )
        browser_column.addWidget(self._bank)
        # The Experiments shelf's controls: the background experimenter's on/off
        # switch and a one-line status. Rides under the header, and appears only
        # while that shelf is open.
        self._experiments_cb = TickControl("Run experiments while the app is closed")
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
        browser_column.addWidget(self._experiments_bar)
        browser_column.addWidget(self._search.bar)
        self._avg_label = QLabel("")
        self._avg_label.setObjectName("estimateLabel")
        self._avg_label.setWordWrap(True)
        browser_column.addWidget(self._avg_label)
        self._scroll.setWidgetResizable(True)
        # A click on the background between the tiles puts the selection down,
        # as it does in a file browser — and here it is also the only way back
        # to aiming Star / Enhance / Delete at the whole folder once a tile has
        # been picked.
        self._scroll.background_clicked.connect(
            self._browser.clear_thumbnail_selection)
        # The Recents shelf has no end: reaching the end of what it has drawn
        # draws the next page. Range as well as value — see BrowserPane.grow_recents.
        self._scroll.verticalScrollBar().valueChanged.connect(self._browser.grow_recents)
        self._scroll.verticalScrollBar().rangeChanged.connect(self._browser.grow_recents)
        browser_column.addWidget(self._scroll, 1)
        # The foot of the center (browser) pane, shared by two panels that each
        # take their own room rather than floating over anyone's buttons: genau's
        # readout, copied, held to the left at its fixed size, and the open
        # folder's Enhance settings taking the width left beside it.  Hosted by
        # Fun Time there is no readout — the real console is on the session's
        # main player — so the Enhance settings take the row alone.
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(BUTTON_GROUP_GAP)  # two panels, one group's gap apart
        self._motion_panel = None
        if self._osr2_motion is not None:
            self._motion_panel = MotionPanel(self._osr2_motion, pace=self._pace)
            footer.addWidget(self._motion_panel, 0, Qt.AlignmentFlag.AlignTop)
        # What an enhancement runs at — the Enhance All button, a single image's
        # Enhance, and (with its tick on) each image the app newly generates.
        # App-wide and always here: enhancement is whatever you are doing at the
        # moment, not a property of the folder you happen to be standing in, so
        # it shows on the shelves as readily as on a settings folder. Deliberately
        # not on the Generate form: every setting there picks the folder a run
        # lands in, and this one doesn't.
        footer.addWidget(self._enhance.panel, 1, Qt.AlignmentFlag.AlignTop)
        # A hairline where the browsing stops and these two panels start. Without
        # it the Enhance settings read as the foot of whatever folder is on screen
        # rather than as their own thing — which they are: app-wide settings that
        # don't belong to the folder they happen to be sitting under.
        browser_column.addWidget(_lower_divider())
        browser_column.addLayout(footer)
        return browser

    def _build_info_pane(self):
        """The right pane: the tabbed workspace of generate panels, with the
        find strip riding under it.
        """
        # Info pane: a tabbed workspace of identical editable generate panels
        # (form + Generate). No special or permanent tab — the first opens on
        # construction, and more fork via the "+" or a thumbnail double-click, all
        # sharing one run queue. Clicking a browser thumbnail loads that generation
        # into a tab (its output in the preview, its settings in the form, a footer
        # for its media type). Each panel's source-image link and animation clicks
        # surface here as a source link the view follows.
        self._info_tabs = InfoPaneTabs(self._client, self._db, fun_time=self._fun_time)
        # One OSR2 driver for the whole view, under the one global toggle
        # (self._bank.drive): while that's on it follows whichever video is foreground —
        # an open slideshow, else whatever scripted video is in the front tab —
        # and with it off nothing drives on either surface.
        # Switching tabs/videos or opening/closing a slideshow re-aims it; with
        # nothing to drive it stops. self._osr2_driving is the (video, player) currently
        # driven, so a redundant reconcile doesn't churn the device. Built before the
        # panels are wired, since wiring connects their displayed_changed here.
        # None where this app may not touch the device at all (hosted by Fun
        # Time, whose main player owns the OSR2).
        self._osr2_driver = Osr2Driver(parent=self) if self._osr2_motion is not None else None
        self._osr2_enabled = False
        self._osr2_driving = None
        self._info_tabs.tab_added.connect(self._wire_config_panel)
        for panel in self._info_tabs.config_panels():
            self._wire_config_panel(panel)  # the initial tab predates the connection
        self._info_tabs.currentChanged.connect(self._on_front_tab_changed)
        # Quitting mid-drive still releases the device — park it and restore genau —
        # so a closed app doesn't leave the OSR2 held and genau silently disabled.
        app = QApplication.instance()
        if app is not None:
            if self._osr2_driver is not None:
                app.aboutToQuit.connect(self._osr2_driver.stop)
                app.aboutToQuit.connect(self._osr2_motion.stop)
            # Same reason the preview releases its player: a live media player at
            # Qt/Python shutdown can deadlock the real (WMF) backend.
            app.aboutToQuit.connect(self._ambient_audio.stop)
        # A tab's Generate is a re-roll of its settings folder: launch it in that
        # folder's own re-roll slot and navigate there, live tile and all.
        self._info_tabs.generate_requested.connect(self._on_generate_requested)
        self._info_tabs.changes_requested.connect(self._on_changes_requested)
        # The find strip, at the foot of the info pane where the prompts it
        # searches are. Ctrl+F opens it over the front tab's prompt fields; it
        # takes no room until then, and closing it clears every mark it painted.
        self._find = PromptFind()
        self._find_bar = FindBar()
        self._find_bar.query_changed.connect(self._on_find_query)
        self._find_bar.step_requested.connect(self._on_find_step)
        self._find_bar.dismissed.connect(self._close_find)
        info_pane = QWidget()
        info_column = QVBoxLayout(info_pane)
        info_column.setContentsMargins(0, 0, 0, 0)
        info_column.addWidget(self._info_tabs, 1)
        info_column.addWidget(self._find_bar)
        return info_pane

    def _arrange_hosted(self, toc, browser, info_pane):
        """The upright arrangement a Fun Time session's rect asks for."""
        # Hosted, the queue is not the folder column's strip.  It spans the
        # whole foot of the rect (added to _stack below), so the corner
        # under the tree is the queue rather than more tree — which is where
        # a standalone window's eye finds it, and the upright fold has no
        # reason to move it.  The folder panes go straight beside the tree.
        self._panes.addWidget(self._folder_panes)

        # The upright arrangement, from the top down: the generate tabs (with
        # the find bar riding under them), then the browser beside a
        # collapsible tree, then the queue across the foot.  The generator
        # leads because it is what the user is doing — a tall rect that
        # opens on a folder listing puts the form they came to fill below
        # the fold.  The floors shrink with the column: each floor spans the
        # stack's whole width, so a side-by-side floor would only fight the
        # tree for room it no longer shares.
        self._stack.addWidget(info_pane)
        self._stack.addWidget(self._panes)
        self._stack.addWidget(self._queue)
        self._panes.setCollapsible(0, True)  # the tree may be dragged shut
        toc.setMinimumWidth(120)
        browser.setMinimumWidth(210)
        self._info_tabs.setMinimumWidth(210)
        info_pane.setMinimumWidth(210)
        self._panes.setStretchFactor(0, 0)
        self._panes.setStretchFactor(1, 1)
        self._panes.setSizes([180, 660])
        # The strip opens at its own height and stays there, as it does
        # standalone: a taller rect is more gallery and more form, not more
        # queue.  The two panes above it split the rest, the browser a
        # little ahead so the tree it sits beside has room to be read.
        self._stack.setStretchFactor(0, 2)
        self._stack.setStretchFactor(1, 3)
        self._stack.setStretchFactor(2, 0)
        self._stack.setSizes([440, 640, self._queue.minimumHeight()])


    def _arrange_standalone(self, toc, browser, info_pane):
        """The three panes side by side, as a window of its own opens them."""
        self._left_column = QSplitter(Qt.Orientation.Vertical)
        self._left_column.setChildrenCollapsible(False)  # the strip keeps its slot
        self._left_column.setHandleWidth(6)
        self._left_column.addWidget(self._folder_panes)
        self._left_column.addWidget(self._queue)
        self._panes.addWidget(self._left_column)
        self._panes.addWidget(info_pane)
        # The TOC pane holds its width; the browser and info panes both grow
        # with the window (the browser faster), so the info pane stays
        # comfortably wide instead of a thin strip on a large screen. Long
        # metadata values wrap rather than scroll sideways, so these floors
        # only need to keep the panes readable — kept low enough that the
        # window can still tile into a monitor third or a portrait-monitor
        # half.
        toc.setMinimumWidth(120)
        browser.setMinimumWidth(210)
        # No floor of its own on the info pane: the config tab inside it
        # reports what its settings need (GenerateConfigPanel.minimumSizeHint),
        # and an explicit minimum here would replace that number rather than
        # join it — pinning the pane narrower than its contents and putting a
        # horizontal scroll bar back under the form.
        self._folder_panes.setStretchFactor(0, 0)  # the TOC pane holds its width
        self._folder_panes.setStretchFactor(1, 1)  # the browser takes the growth
        self._folder_panes.setSizes([220, 560])
        # The strip opens at its own height and stays there: all the growth
        # goes to the folders above it, so a taller window is more gallery
        # rather than more queue.
        self._left_column.setStretchFactor(0, 1)
        self._left_column.setStretchFactor(1, 0)
        self._left_column.setSizes([600, self._queue.minimumHeight()])
        self._panes.setStretchFactor(0, 3)
        self._panes.setStretchFactor(1, 2)
        self._panes.setSizes([780, 440])

    def _wire_config_panel(self, panel):
        """Route a config tab's footer links to the gallery: its "from source
        image" link and an animation-tile click both navigate like any source link,
        and its preview's corner controls and right-click menu act on the shown
        generation exactly as a browser thumbnail's do.
        Its ``displayed_changed`` re-aims the global OSR2 drive at the front video
        and re-reads whether the tab still owns a run in flight, a double-click on
        its preview opens the folder under it as a held slideshow,
        and its Cancel stops the re-roll running in the tab's folder. Called for the
        initial tab and every tab forked afterward."""
        panel.source_activated.connect(self.follow_link)
        panel.animated_activated.connect(self.follow_link)
        # Its preview's corners and its right-click are the same acts, on the same
        # generation, as a browser thumbnail's — so they land in the same places.
        panel.item_action_requested.connect(self.run_item_action)
        panel.context_menu_requested.connect(
            lambda prompt_id, pos: self.generation_menu([prompt_id], pos))
        panel.displayed_changed.connect(self.reconcile_osr2)
        # A tab that just changed which image it shows needs the live enhance
        # tile for THAT image, not the one it was showing a moment ago.
        panel.displayed_changed.connect(lambda: self._enhance.reconcile())
        # Pointing a tab at another generation drops its claim on the run it
        # launched, so its Generate button has to be re-read straight away.
        panel.displayed_changed.connect(self._reconcile_generating)
        # Its version list's "+ Enhance" row runs through the same queue the
        # folder button and the context menu use, and its Delete goes through
        # the same undo stack as every other delete in the gallery.
        panel.enhance_requested.connect(lambda pid: self._enhance.enhance_items([pid]))
        panel.levels_delete_requested.connect(self.delete_enhance_levels)
        panel.set_enhance_settings(self._enhance.settings)
        panel.set_fullscreen_factory(self._shows.open_on_preview)
        panel.cancel_requested.connect(lambda p=panel: self._cancel_panel_reroll(p))
        # Dragging the tab's preview out lights the combine slot it fits, like a
        # browser thumbnail (see :meth:`CombineController.drag_started`).
        panel.preview_drag_started.connect(self._combine.drag_started)
        panel.preview_drag_ended.connect(self._combine.drag_ended)
        # Picking a different workflow builds a whole new form, so an open find
        # has to let go of the fields it was holding before they're destroyed.
        panel.form_replaced.connect(self._retarget_find)
        # Every keystroke in a tab's form moves the text an open find is marking
        # up — re-run rather than leave highlights on words that shifted.
        panel.form_edited.connect(self._refresh_find)

    # --- Drive OSR2: one switch, the app picking funscript or motion ----------

    def _on_osr2_toggle(self, on: bool):
        self._osr2_enabled = on
        self.reconcile_osr2()

    def toggle_osr2_drive(self):
        """Flip the one switch — what Space does, from any surface. The motion's
        own toggle is deliberately not reachable from a key any more: with two
        sources for one device, whichever one a key started would have been
        streaming alongside whatever the switch already had going.

        A no-op with no switch to flip: hosted by Fun Time the device belongs
        to the session's main player, so nothing here may start it."""
        if self._bank.drive is not None:
            self._bank.drive.setChecked(not self._bank.drive.isChecked())

    def reconcile_osr2(self):
        """Put the right thing on the device, or nothing.

        With the switch off, neither source drives. With it on, a funscript wins
        wherever there is one — a slideshow showing a scripted video, else the
        front tab's — and the self-generated motion fills every other moment,
        which is most of them: a folder of images, a clip with no script, an
        empty tab. That is the whole of "genau mode when no funscript is going".

        Idempotent, so tab switches, browsing, completions and opening or closing
        a show all resolve without churning the device. The guard makes it
        re-entrant-safe too: starting or stopping the motion emits
        ``active_changed``, and a listener that reconciles must not land back
        here mid-flight.
        """
        if self._osr2_driver is None:
            return  # hosted by Fun Time — the device is the main player's
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
            wants_motion = self._osr2_enabled and target is None
            if wants_motion and not self._osr2_motion.active:
                self._osr2_motion.start()
            elif not wants_motion and self._osr2_motion.active:
                self._osr2_motion.stop()
        finally:
            self._reconciling_osr2 = False

    def _osr2_drive_source(self):
        """The funscript target to follow, or ``None`` when there is none to
        follow — in which case the motion is what drives (see
        :meth:`reconcile_osr2`). An open slideshow wins when it's showing a
        scripted video, otherwise the front tab's video.

        The switch governs both surfaces alike: double-clicking a clip open used
        to take the device on its own, so a clip watched with the switch off
        drove anyway — the switch is what decides now, whichever surface the
        video is on."""
        target = self._shows.drive_target()
        if target is not None:
            return target
        panel = self._info_tabs.current_config_panel()
        if panel is not None:
            return panel.osr2_drive_target()
        return None

    def level_playlists(self) -> dict:
        """Each visible image's versions, keyed by the file the folder shows it
        under — newest first, matching the strip in the info pane. Each carries
        its label, so a slideshow can say which one is on screen."""
        playlists = {}
        for pid in self._browser.visible_prompt_ids():
            row = self.row_for(pid)
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

    def folder_media_playlist(self):
        """The visible folder's resolvable media in shown order, and the index of
        the currently-shown item — what a double-clicked picture's show plays.

        Each entry carries its generation's id alongside the media, so the show's
        Up and Down can name what to trash and what to bookmark, and its stored
        thumbnail, which is the only still a video has for the neighbor previews.

        Returns an empty list when the shown item isn't among them, so the show
        always opens on what's already on screen."""
        selected_pid = self._selected["prompt_id"] if self._selected else None
        items, index, found = [], 0, False
        for entry in self.folder_media():
            if entry[2] == selected_pid:
                index, found = len(items), True
            items.append(entry)
        return (items, index) if found else ([], 0)

    def folder_media(self) -> list[tuple]:
        """The visible folder's resolvable media in shown order, each as
        ``(path, media_type, prompt_id, thumbnail)``. In-flight and output-less
        rows have nothing to show fullscreen, so they are left out."""
        media = []
        for pid in self._browser.visible_prompt_ids():
            row = self.row_for(pid)
            preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR) if row else None
            if preview is not None:
                media.append((preview[0], preview[1], pid, row.get("thumbnail_path")))
        return media


    def group_for_key(self, key: str):
        """The folder ``key`` names, as the side it is being looked at holds it."""
        item = self._tree_item_for(key)
        return item.data(0, _GROUP_ROLE) if item is not None else None

    def _on_front_tab_changed(self, _index):
        """The front config tab changed: re-aim the OSR2 drive at its video,
        re-evaluate whether that tab's folder is generating (its Cancel button),
        and point an open find at the prompts now in front."""
        self.reconcile_osr2()
        self._reconcile_generating()
        self._retarget_find()

    def osr2_enabled(self) -> bool:
        """Whether the global OSR2 toggle is on (for session persistence)."""
        return self._osr2_enabled

    def set_osr2_enabled(self, enabled):
        """Restore the global OSR2 toggle from a saved session.  With no OSR2
        surface (hosted by Fun Time) a stale saved value has nothing to restore."""
        if self._bank.drive is not None:
            self._bank.drive.setChecked(bool(enabled))  # drives _on_osr2_toggle → reconcile

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
        return self._bank.audio is not None and self._bank.audio.isChecked()

    def set_audio_enabled(self, enabled):
        """Restore the audio bed's switch from a saved session.  With no switch
        (hosted by Fun Time, whose main player owns the room's sound) a stale
        saved value has nothing to restore."""
        if self._bank.audio is not None:
            self._bank.audio.setChecked(bool(enabled))  # drives _on_audio_toggle → start

    # --- the microphone: the one switch Esc leaves alone ---------------------

    def mic_enabled(self) -> bool:
        """Whether the mic switch is on (for session persistence).

        Hosted there is no switch — the session owns the room's microphone — so
        the answer is no.  Asked on the way out either way, and an
        AttributeError raised inside closeEvent takes the whole process down
        with it rather than surfacing anywhere.
        """
        return self._bank.mic is not None and self._bank.mic.isChecked()

    def set_mic_enabled(self, enabled):
        """Restore the mic switch from a saved session — on when the session has
        nothing to say, which is where the app opens.

        The other switches default off because each of them spends something: the
        GPU, the device, the room's sound. Listening spends nothing until it hears
        something, and it is the only way back in after Esc has stopped everything
        else — so off is a state to be chosen, not one to be arrived at.
        """
        if self._bank.mic is not None:  # hosted, the session owns the microphone
            self._bank.mic.setChecked(True if enabled is None else bool(enabled))

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
        them waits on jobs "from another app" that were the user's own
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
        """The experiments waiting on the user's verdict — the Experiments shelf."""
        return gallery.unreviewed_experiments(rows)

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
        key = self.folder_key_for(proposal.workflow.name, proposal.params)
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
            self._re_aim()
        self.refresh()

    def folder_key_for(self, workflow_name: str, params: dict,
                        workflow_version: str | None = None) -> str:
        """The settings-folder key a config lands in — the key the re-roll
        controller tracks its job under, and the tree leaf it groups into. Shared by
        the Generate launch and the front-tab generating/cancel reconcile so a tab
        matches the very job its own Generate started.

        Five call sites used to build this row dict inline, and they disagreed
        about what went in it — one left the workflow version out, two put it in,
        two spread a whole video row — so a reader could not tell which differences
        were meaningful. They are arguments now, and a caller that already holds a
        row asks :meth:`folder_key_of` instead.
        """
        row = {"workflow_name": workflow_name, "params_json": json.dumps(params)}
        if workflow_version is not None:
            row["workflow_version"] = workflow_version
        return self.folder_key_of(row)

    def folder_key_of(self, row: dict) -> str:
        """The settings-folder key a stored row lands in — the same derivation,
        for a caller holding the row rather than a config."""
        return gallery.settings_folder_key(row, self.image_config_index())

    def _panel_reroll_key(self, panel) -> str:
        """The settings-folder key the config in ``panel`` would run in."""
        config = panel.current_config()
        return self.folder_key_for(config.workflow_name, config.params)

    def _reconcile_generating(self):
        """Point every config tab's discard button at the run *it* launched.

        A tab tracks its own Generates, not its settings folder: a folder can have
        several runs queued at once (two pictures of one recipe, both wanted), and
        a tab showing one of them must not claim the others. Of its own it follows
        the *oldest still alive* — the one nearest to being made, and so the one
        its button discards. A press that stopped the job queued after the one on
        screen was the reported dead click. A chained i2v is two prompts but one
        run, so a tab follows its origin across the hand-off, and runs that have
        ended are let go here.
        Launches from outside a tab — the folder tile's "+", the auto loop — are
        claimed by the tab looking at that same folder (:meth:`_claim_launch`), so
        they light it up too.

        Idempotent — driven by every re-roll lifecycle change and by switching the
        front tab. Every tab is reconciled, not just the front one, so a run
        launched from a tab that is now under another still shows there.
        """
        for panel in self._info_tabs.config_panels():
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
        screen rather than something queued after it.
        """
        for origin in panel.launched_runs():
            job = self._reroll.job_for_origin(origin)
            if job is not None:
                self._cancel_job(job.prompt_id)
                return

    def would_reproduce_a_completed_run(self, workflow, params: dict) -> bool:
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
        too; ComfyUI works through them in turn and the lower strip shows the line.
        Missing form params are filled from the workflow's defaults, exactly as the
        old Generate did. A no-op without a client or an unknown workflow.

        The launched run is noted on the tab that asked for it, so that tab's
        Cancel and progress fill follow its own Generate rather than its folder.
        """
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        if self._client is None or wf is None:
            return
        params = {**wf.default_params(), **params}  # form values win over defaults
        key = self.folder_key_for(workflow_name, params)
        # A pinned seed that would reproduce a past run draws a fresh one instead of
        # launching a copy — the press was made against a button already reading
        # "Generate with Random seed" (:meth:`GenerateConfigPanel._apply_generate_caption`),
        # so this is what it said it would do, not a question worth stopping for.
        # The tab keeps the Random seed, so its form goes on saying the same thing.
        if self.would_reproduce_a_completed_run(wf, params):
            params = randomize_seeds(params, wf.seed_keys())
            panel = self._info_tabs.current_config_panel()
            if panel is not None:
                panel.use_random_seed()
        launching = self._info_tabs.current_config_panel()
        prompt_id = self._reroll.start_prepared(key, wf, params)
        if not prompt_id:
            return  # no client, or the submit failed
        if launching is not None:
            # A tab Combine opened stamps its run with where the recipe came
            # from, whether it was launched as opened or edited first — that mark
            # is the only thing telling the queue what act this video is of.
            category, video_id = launching.recipe_source()
            if category or video_id:
                self._db.set_recipe_source(prompt_id, category=category,
                                           video_prompt_id=video_id)
            launching.note_launched(self._reroll.newest_job_for(key).origin)
        self._navigate_to_reroll(key)

    def _navigate_to_reroll(self, key: str):
        """Open the folder a just-started re-roll runs in and select its live tile.

        The re-roll inserts a running row, so a rebuild gives even a brand-new
        folder a node (:func:`build_gallery_tree` includes in-flight rows); this
        rebuilds, then drills into that folder and points the info pane at the tile.
        """
        self.refresh()
        item = self._tree_item_for(key)
        if item is not None:
            self._tree.setCurrentItem(item)
            self._select_reroll(key)

    def showEvent(self, event):
        super().showEvent(event)
        self._poll_timer.start()
        self._intercept_the_rooms_keys(True)  # back on screen: back on the keys
        self.refresh()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._poll_timer.stop()  # no need to poll while the tab is hidden

    def closeEvent(self, event):
        """Put down everything this view arms application-wide, however it was
        let go: the poll, the filter that takes the room's keys, and the shows,
        each a window of its own that would otherwise outlive the view that
        answers for it.

        ``hideEvent`` alone is not enough for either: a widget that was never
        shown is never hidden, so ``close()`` on one left the 1.5 s poll running
        — blocking HTTP and a whole-table SELECT, on a view nobody can see —
        and left a closed gallery answering Esc from whatever window has focus,
        which is the panic-stop for the whole room.
        """
        self._poll_timer.stop()
        self._intercept_the_rooms_keys(False)
        self.close_the_shows()
        super().closeEvent(event)

    # --- data loading & live update ---------------------------------------

    def refresh(self):
        rows = self._db.list_generations()
        meta = self._db.folder_meta_map()
        self._fingerprint = _fingerprint(rows, meta)
        self._rebuild(rows, meta)
        if self._shows.regions_wanted:
            # The tree this rebuild just made is what the base state is read
            # from, and the session's OPEN_SHOWS can land before the first one
            # (its launch races this app's boot).  Filling here costs nothing
            # when both regions are already playing, and is the only thing that
            # rescues a session that opened into the mode a moment too early.
            self.fill_the_regions()

    def _poll(self):
        """One tick: fetch every blocking read away from the GUI, apply here.

        The tick used to make its HTTP calls inline — with a 2.0 s socket
        timeout inside a 1.5 s timer, so a wedged ComfyUI froze the window for
        most of every tick. The reads now run on the pool
        (:func:`_fetch_poll_facts`) and :meth:`_finish_poll` applies them back
        on this thread. A tick that fires while the last one's reads are still
        out is skipped rather than stacked, so a slow server thins the refresh
        instead of queueing freezes.
        """
        if self._poll_inflight:
            return
        self._poll_inflight = True
        jobs = self._reroll.all_jobs
        targets = [(job.prompt_id, job.state) for job in jobs]
        client = self._client
        self.off_thread(lambda: _fetch_poll_facts(client, targets),
                             lambda facts: self._finish_poll(jobs, facts))

    def _finish_poll(self, jobs, facts):
        """Apply a tick's ComfyUI answers, then send its database reads out too.

        Applying before reading is load-bearing: reconciliation can land a
        completion's row, and the listing read next must see it rather than lag
        it a tick. The listing — two whole-table SELECTs and the requests
        table, the tick's other blocking work — is read on the pool and lands
        in :meth:`_finish_poll_rebuild`.
        """
        try:
            if facts is not None:  # None only if the batched fetch itself died
                self._apply_poll_facts(jobs, facts)
        except Exception:
            self._poll_inflight = False
            raise
        db = self._db

        def read_listing():
            rows = db.list_generations()
            meta = db.folder_meta_map()
            return rows, meta, db.list_requests(), _fingerprint(rows, meta)

        self.off_thread(read_listing, self._finish_poll_rebuild)

    def _finish_poll_rebuild(self, listing):
        """The tick's last hop: fold the freshly read listing into the panes."""
        try:
            if listing is None:  # only if the read itself died
                return
            rows, meta, requests, fingerprint = listing
            if fingerprint != self._fingerprint:
                self._fingerprint = fingerprint
                self._rebuild(rows, meta)
            else:
                # No DB change, but the in-flight cards still need each running
                # re-roll's live frame pushed in — it advances between rebuilds.
                # Wherever they were drawn: the Recents shelf, or a folder with
                # a batch of them cooking in it.
                self._browser.refresh_inflight(rows=rows, requests=requests)
            # The lower strip is always on screen, so refresh it every tick —
            # its rows' live frames and progress advance between rebuilds. The
            # listing already in hand feeds it, so the strip costs the tick no
            # further table reads.
            self._update_queue(self._inflight_items(rows=rows, requests=requests))
            # And a show's corner, for the same reason and one more: a run
            # starting is not a change to any row, so nothing else here would
            # tell the show its held slide went from waiting to being made.
            self._enhance.tell_the_shows()
            self._refresh_wait_note()
        finally:
            self._poll_inflight = False

    def _apply_poll_facts(self, jobs, facts: _PollFacts):
        """Apply one tick's fetched answers, in the order the inline calls ran.

        Reconciling first is load-bearing: finishing a missed completion fires
        the job's own finished handler, which persists its row — so the rows
        this tick then reads see the completion rather than lagging it a tick.
        """
        for job in jobs:
            # Backstop for a missed completion frame: finish any re-roll
            # ComfyUI has already completed so it lands without a restart.
            job.reconcile_with(facts.histories.get(job.prompt_id))
            # And what another app has in front of a job ComfyUI hasn't
            # started, so that wait shows a number instead of an unmoving bar.
            job.take_backlog(facts.backlogs.get(job.prompt_id))
        if facts.foreign is not None:
            self._foreign_queue = facts.foreign

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
        # A running re-roll's tile is the selected item, not a saved row, so
        # capture it to restore afterward rather than let the folder's default
        # selection replace it. This matters because every re-roll (and each i2v
        # stage) triggers a rebuild the moment its running row lands.
        reroll_key = self._selected_reroll_key
        self._pending_key = None
        self._pending_selection = None
        self._image_rows = [r for r in rows if gallery.media_type_of_row(r) == "image"]
        self._image_index = None   # rebuilt on the next ask (image_config_index)
        self._combine.offer_the_acts(rows)
        # The Images/Videos ticks narrow everything the gallery shows: which
        # folders the tree grows, which items each shelf lists, and what a search
        # can turn up. The tree takes the filter itself rather than pre-filtered
        # rows, because the start-frame index under a video's source-image
        # folders has to see every image whichever way the ticks stand.
        media_types = self.media_types()
        listed = gallery.rows_of_media_types(rows, media_types)
        # Built once here off the whole library and handed to every tree below —
        # the split trees included, which are the ones that cannot build it for
        # themselves (see :func:`gallery.start_frame_index`).
        start_frames = gallery.start_frame_index(rows)
        tree_model = gallery.build_gallery_tree(rows, meta, media_types,
                                                image_index=start_frames)
        unreviewed = self._review_queue(listed)
        # The bin holds every kind, so a restore can still resolve a row of a type
        # the ticks are hiding; only what the Trash shelf lists is narrowed.
        self._held_rows = recovery.bin_items(self._bin_records())
        held = gallery.rows_of_media_types(self._held_rows, media_types)
        self._live_ids = {row["prompt_id"] for row in rows}
        self._custom_folders = gallery.build_custom_folders(
            tree_model, self._db.list_custom_folders()
        )
        # Re-index for the search field while the rows are in hand: tokenizing every
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
        # ids drawn from the live tree (see :meth:`search_scope`).
        self._search.index.update(listed + held, gallery.named_folders_by_row(
            tree_model, meta, self._custom_folders))
        requested = gallery.requested_generations(self._db.list_requests(), listed)  # the Requests shelf
        # Every side is built from the rows the media filter keeps, so switching
        # videos off empties both halves of them rather than one.
        sides, starred_by_side = self._build_sides(listed, meta, unreviewed, held,
                                                   requested, start_frames)
        self._browser.set_model(
            gallery.recent_generations(listed),
            starred_by_side,
            gallery.starred_generations(listed),
            unreviewed,
            held,
            requested,
        )
        self._tree_view.populate(sides, expanded, folder_meta=meta)
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
        # _tree_item_for rather than a bare lookup, so a restore target saved as
        # a folder key — a session from before the tree grew sides — still lands
        # on that folder instead of falling back to the default.
        target = (self._tree_item_for(selected_key) if selected_key
                  else None) or self._tree_view.default_item()
        # A rebuild restores the prior view; that re-selection isn't a navigation,
        # so keep it off the history (a poll would otherwise pile up duplicates).
        with self._navigation.off_the_record():
            if target is not None:
                self._tree.setCurrentItem(target)  # shows the folder's thumbnails
                self._reselect_generation(selected_gen)
            else:
                self._title.set_display("")
                self._avg_label.setText("")
                self._browser.show_empty()
                self._selected_row = None  # nothing selected
            self._restore_multi_selection(multi_keys)
            self._restore_reroll_selection(reroll_key)
        # Seed history once with wherever the gallery first lands, so Back works
        # even if the user's very first move leaves it.
        self._navigation.seed()
        # A search running through the rebuild takes the pane back off the folder
        # the restore above just re-drew, and re-runs against the new index — so a
        # generation that lands while a query is open joins its results.
        if self._search.query:
            self._search.run()
        self._update_queue()
        # Re-assert the front tab's Generate-as-progress state against the live jobs.
        # Keying off the freshly rebuilt image rows is what lets a reconnected re-roll
        # light its tab's button after a restart: at reconnect time the view's image
        # rows aren't built yet, so an i2v folder key wouldn't match then; here it does.
        self._reconcile_generating()
        # A generation landing or leaving can make an open tab's pinned seed one that
        # would reproduce it — or stop it being one — with nothing on the form having
        # moved, so every tab re-reads what its Generate would now do.
        for panel in self._info_tabs.config_panels():
            panel.refresh_generate_caption()

    def _build_sides(self, rows, meta, unreviewed, held, requested, start_frames):
        """The two sides of the tree, and the starred folders each one holds.

        A side is the whole table of contents over one shape's rows: its own
        media/workflow/model/LoRA/settings hierarchy, its own copies of the
        folders the user composed, and shelves whose counts are its own — a
        number covering both sides would send you to a shelf that then showed
        you nothing.  Built from a single deal of the rows, because measuring
        each row's shape is the expensive part and a rebuild runs on every poll.

        ``start_frames`` is the whole library's, not the side's: what a side
        holds decides which folders it draws, never what they are called (see
        :func:`gallery.start_frame_index`).
        """
        dealt = split_rows(rows)
        custom_records = self._db.list_custom_folders()
        request_rows = [item["row"] for item in requested]
        inflight = self._browser.inflight_orientations()
        sides, starred = [], {}
        for orientation in _ORIENTATIONS:
            model = gallery.build_gallery_tree(dealt[orientation], meta,
                                               image_index=start_frames)
            starred[orientation] = gallery.starred_folders(model)
            sides.append(SideModel(
                orientation=orientation,
                tree_model=model,
                custom_folders=gallery.build_custom_folders(model, custom_records),
                # Recents keeps a side up with no folders yet, so a first-ever
                # generation of that shape is visible while it runs.
                show_recents=bool(model) or orientation in inflight,
                experiment_count=len(filter_rows(unreviewed, orientation)),
                request_count=len(filter_rows(request_rows, orientation)),
                trash_count=len(filter_rows(held, orientation)),
            ))
        return sides, starred

    def _reselect_generation(self, prompt_id: str | None):
        """Re-select a generation after a rebuild, if it's still on screen.

        The gallery's own selection only. The tabs keep what they were showing
        across a rebuild — one happens whenever anything lands, once per
        variation of a running loop — and a tab is repainted only when the
        generation it shows changes under it or goes (see
        :meth:`InfoPaneTabs.refresh_displayed` and
        :meth:`InfoPaneTabs.drop_previews_of_gone_rows`). Painting the selection
        into whichever tab was in front is how a tab came to show a picture that
        was not its own."""
        if not prompt_id or prompt_id not in self._browser.visible_prompt_ids():
            return
        row = self.row_for(prompt_id)
        if row:
            self._select_saved_generation(row)

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
            self._search.focus_field()
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

    # --- searching the gallery (the field over the tree) ------------------------


    def image_config_index(self) -> dict:
        """The index a folder key is derived against.

        Memoized against the image rows it is built from, which change only on a
        rebuild: it was rebuilt from scratch at eight call sites, several of them
        on a click's path, and the answer is the same every time between two
        rebuilds.
        """
        if self._image_index is None:
            self._image_index = gallery.build_image_config_index(self._image_rows)
        return self._image_index

    def name_search_on_screen(self, query: str, scope: str) -> None:
        """Say in the header that a search is what the pane is showing, in place
        of the folder that was there."""
        self._title.set_display(f"Search: “{query}” in {scope}")
        self._title.setToolTip("")  # the header is the query now, not a folder
        self._avg_label.setText("")
        self._experiments_bar.hide()

    def show_search_results(self, tiles, **terms) -> None:
        self._browser.show_search_results(tiles, **terms)

    def search_results_drawn(self) -> None:
        """Results are up: the buttons that fit what the pane holds are re-read,
        and the pane is somewhere Back returns to — including from a hit opened
        out of it."""
        self._re_aim()
        self._navigation.record()

    def suppress_history(self):
        """A search leaving is a step on the way, not a stop — the history's own
        term for that (:meth:`NavigationController.off_the_record`)."""
        return self._navigation.off_the_record()

    def selected_prompt_id(self) -> str | None:
        """The generation picked in the pane, or ``None``."""
        return self._selected["prompt_id"] if self._selected else None

    def pane_holds(self, prompt_id: str) -> bool:
        return prompt_id in self._browser.visible_prompt_ids()

    def show_folder(self, key: str) -> bool:
        """Draw the folder or shelf ``key`` names, saying whether the tree had a
        row for it at all.

        ``_tree_item_for`` rather than a bare lookup: a stop recorded before the
        tree grew sides names a folder key with no side on it, and that key still
        has to find its row. Standing on the row already fires no signal, and the
        pane would go on holding the search results or the tile highlight the
        stop was recorded without, so that case is drawn by hand.
        """
        row = self._tree_item_for(key)
        if row is None:
            return False
        if self._tree.currentItem() is row:
            self._on_folder_selected(row, None)
        else:
            self._tree.setCurrentItem(row)  # whose signal draws it
        return True

    def reveal(self, prompt_id: str) -> None:
        """Pick and scroll to a tile the pane is already showing, and put the
        item back in the info pane."""
        self._browser.reveal_tile(prompt_id)
        self._on_thumbnail_clicked(prompt_id)

    def clear_selection(self) -> None:
        self._clear_metadata()

    def nav_state_changed(self, can_go_back: bool, can_go_forward: bool) -> None:
        """The trail moved: hold what it now allows, and re-aim the bank."""
        self._trail = (can_go_back, can_go_forward)
        self._re_aim()

    def hand_pane_back(self) -> None:
        """The search is over: the pane belongs to the selected folder again."""
        self._on_folder_selected(self._tree.currentItem(), None)

    def search_scope(self) -> _SearchScope:
        """What the search covers: the path it is scoped to, and what is under it.

        The tree's selection is the scope, whatever kind of row it is. A shelf
        counts: Recents, Starred, Experiments and Trash are each a collection of
        generations, and standing on one and searching it is the obvious thing to
        try. The All row over the workflow folders is what covers the library
        entire, since every other folder narrows the answer before the query does.

        ``path`` is the row's breadcrumb — what the field, the header and the
        empty-result message all name the scope by. A shelf is a single row with
        no branch above it, so its path is just its own name.
        """
        item = self._tree.currentItem()
        shelf = self._current_shelf_key()
        if shelf is not None:
            base, orientation = _split_shelf_key(shelf)
            name = _SHELF_LABELS[base]
            if orientation:
                # The same path shape a folder's breadcrumb has, since a shelf is
                # one side's now: which half of the library is being searched has
                # to read the same way wherever you are standing.
                name = f"{_ORIENTATION_LABELS[orientation]}  ›  {name}"
            rows = self._browser.selected_shelf_rows() or []
            return _SearchScope(name, {row["prompt_id"] for row in rows})
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if group is None:
            # Nothing selected, or the caret resting on a side's header row: the
            # whole gallery, since neither names a folder to narrow to. The
            # trash's held rows share the index but belong to their shelf alone.
            return _SearchScope(gallery.ALL_LABEL, self._live_ids)
        return _SearchScope(self._tree_view.breadcrumb(item),
                            {row["prompt_id"] for row in gallery.rows_under(group)})





    def search_sort(self) -> str:
        """The results order in force, for the session state to remember."""
        return self._search.sort()

    def set_search_sort(self, mode: str | None):
        """Restore the remembered results order."""
        self._search.set_sort(mode)

    def _showing_search(self) -> bool:
        return self._browser.showing_search()

    def _on_folder_selected(self, current, _previous):
        if self._selection_group is not None:
            return  # a multi-selection owns the panes; the current row is one of many
        self._search.sync_placeholder()  # the field says what it would search now
        # A folder picked while a search is running is a new *scope*, not an exit:
        # the same question, asked of somewhere else. Suppressed during a rebuild's
        # restore, where the tree is re-selecting itself and _rebuild re-runs the
        # search once at the end rather than once per step of the restore.
        if self._search.query and not self._navigation.suppressed:
            self._search.run()
            return
        self._re_aim()
        # The experimenter's switch belongs to the Experiments shelf alone, and
        # which shelf is showing is read off the key rather than off an item
        # identity — there are two of every row now, one per side.
        base, orientation = _split_shelf_key(self._tree_view.selected_folder_key())
        self._experiments_bar.setVisible(base == _EXPERIMENTS_KEY)
        if current is None:
            self._title.set_display("")
            self._title.setToolTip("")
            self._avg_label.setText("")
            self._browser.show_empty()
            self._re_aim()
            return
        if base in _SHELF_KEYS:
            self._open_shelf(base, orientation)
            return
        group = current.data(0, _GROUP_ROLE)
        # A folder's place in the tree is where the user is standing, side and
        # all, so that — not the folder's own key — is what history and the
        # return-after-delete trail record.
        here = self._tree_view.selected_folder_key()
        self._note_folder_visit(here if group is not None else None)
        if group is not None:
            # A folder is somewhere the user went, so Back can return to it — and
            # so leaving a shelf for one is a step Back can undo at all.
            self._navigation.record()
        self._title.set_display(self._tree_view.breadcrumb(current))
        # The path ends in a code, so what the folder holds — the prompt its
        # generations ran, and the settings that set it apart from its siblings —
        # is read by hovering the path, as it is by hovering the row itself.
        self._title.setToolTip(gallery.folder_detail(group) if group else "")
        self._update_folder_average(group)
        self._show_group_contents(group)
        self._re_aim()

    def _open_shelf(self, base: str, orientation: str | None):
        """Show one side's copy of a shelf: dress the header, clear the info
        pane (a shelf opens showing nothing until an item is picked), have the
        browser render it, and record the visit so Back can return to it."""
        if base == _EXPERIMENTS_KEY:
            self._sync_experiments_bar()  # what the switch's position means
        self._title.set_display(self._shelf_title(base, orientation))
        self._avg_label.setText("")   # no shelf has an average to state
        self._clear_metadata()
        self._browser.show_shelf(base, orientation)
        if base == _REQUESTS_KEY:
            self._re_aim()
        self._navigation.record()

    @staticmethod
    def _shelf_title(base: str, orientation: str | None) -> str:
        """A shelf's header: its side, then its name — the path shape a folder's
        breadcrumb has, since a shelf belongs to one side like everything else.
        Favorites keeps the star its tree row wears."""
        label = _SHELF_LABELS[base]
        if base == _STARRED_KEY:
            label = "★ " + label
        if orientation is None:
            return label
        return f"{_ORIENTATION_LABELS[orientation]}  ›  {label}"

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

    def _open_folder_tile(self, key: str):
        """A folder tile was clicked: select its tree row, which draws the folder.
        Clicking one is a decision to go there, so it puts a running search away
        first — a search's results are folder tiles too, and this is how they
        open; without it the field would still be full while the pane shows the
        folder it drilled into."""
        item = self._tree_item_for(key)
        if item is not None:
            self._search.leave()
            self._tree.setCurrentItem(item)

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
            self._re_aim()

    def _selected_groups(self) -> list:
        """The folders the tree currently has picked, in tree order. A custom
        folder is left out: gathering one into another would nest a grouping inside
        a grouping, which the tree has nowhere to draw."""
        return [
            group for key in self._tree.selected_folder_keys()
            if (group := self.group_for_key(key)) is not None
            and not isinstance(group, gallery.CustomGroup)
        ]

    def _show_selection(self):
        """Render the picked folders as the folder they would make: their tiles in
        the browser pane, and the toolbar offering to save the grouping."""
        group = self._selection_group
        self._experiments_bar.hide()
        self._title.set_display(group.label)
        self._title.setToolTip("")  # a count of folders, with no one folder under it
        self._update_folder_average(group)
        self._browser.show_custom_folder(group)
        self._re_aim()

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

    def _group_selection(self):
        """Save the picked folders as a folder of the user's own, under a name they
        give, and open it."""
        group = self._selection_group
        if group is None:
            return
        folders = gallery.child_groups(group)
        name, ok = QInputDialog.getText(
            self, "New Folder",
            f"Name for a folder holding these {len(folders)} folders:",
        )
        if not ok or not name.strip():
            return
        folder_id = self._actions.create_custom_folder(
            name.strip(), [self._item_identity(f) for f in folders]
        )
        self._open_custom_folder(folder_id)

    def _item_identity(self, group) -> tuple:
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
        self._re_aim()
        item = self._tree_item_for(gallery.custom_folder_key(folder_id))
        if item is not None:
            self._tree.setCurrentItem(item)

    def _on_folders_dropped(self, target_key: str, keys: list):
        """Folders dragged onto a collecting row: Starred stars them (the drag-and-
        drop way to bookmark), a custom folder gathers them."""
        groups = [g for key in keys if (g := self.group_for_key(key)) is not None]
        if target_key == _STARRED_KEY:
            for group in groups:
                self._db.set_folder_starred(group.key, True)
            self.refresh()
            return
        folder_id = gallery.custom_folder_id(target_key)
        if folder_id is None:
            return
        self._actions.add_to_custom_folder(
            folder_id, [self._item_identity(g) for g in groups]
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
        self._re_aim()

    def _remove_from_custom_folder(self, group, item_key: str):
        """Drop one gathered folder out of the custom folder on screen."""
        item = self.group_for_key(item_key)
        identity = self._item_identity(item) if item is not None else (item_key, None, None)
        self._actions.remove_from_custom_folder(
            group.folder_id, item_key, level=identity[1], ref_prompt_id=identity[2]
        )
        self.refresh()
        self._re_aim()

    def _note_folder_visit(self, key: str | None):
        """Record a folder the user opened, so a delete can return to the most
        recent one still standing. Skipped while a rebuild or Back/Forward is
        re-selecting (suppressed), and consecutive repeats collapse, so it stays a
        genuine visit trail rather than a poll-driven pile-up."""
        if self._navigation.suppressed or key is None:
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

    # The folder tree's key→item and prompt→item maps are owned by the GalleryTree
    # renderer; surfaced here for navigation, selection, and rebuild. A shelf's row
    # is reached separately, through _shelf_item.
    @property
    def _item_by_key(self) -> dict:
        return self._tree_view.item_by_key

    @property
    def _leaf_by_id(self) -> dict:
        return self._tree_view.leaf_by_id

    def selected_folder_key(self) -> str | None:
        """The selected row's tree key (or a shelf's), from the tree renderer."""
        return self._tree_view.selected_folder_key()

    def side_in_view(self) -> str:
        """Which of the two sides the tree is standing on.

        Every row lives under one, so this is only ever a fallback: nothing
        selected at all (a fresh window, a rebuild that found no target) reads
        as Landscape, the roomier side and the one an unmeasurable item files
        under everywhere else.
        """
        return _orientation_of(self.selected_folder_key()) or _LANDSCAPE

    def _tree_item_for(self, key: str):
        """The tree row for ``key`` — a tree key resolves to its own row, and a
        folder's own key to the copy of it on the side being browsed.

        A folder key names a folder, not a place: a re-roll, a combine, a folder
        tile and a delete's return target all hold one, and each side draws its
        own row for it. Staying on the side already open is the answer that
        doesn't teleport the user across the tree; a folder only the other side
        holds is followed there rather than dropped.

        A key that already names a side is answered by that side alone. Falling
        back across the split would hand a portrait region a landscape library
        the moment the portrait one happened to be empty, which is the whole of
        what the split exists to prevent.
        """
        item = self._item_by_key.get(key)
        if item is not None or _orientation_of(key):
            return item
        drawn = self._tree_view.keys_for_folder(key)
        if not drawn:
            return None
        here = oriented_key(key, self.side_in_view())
        return self._item_by_key[here if here in drawn else drawn[0]]

    def _shelf_item(self, shelf_key: str, orientation: str | None = None):
        """One side's copy of a shelf row — the side being browsed by default."""
        return self._tree_view.shelf_item(shelf_key, orientation or self.side_in_view())

    def _folder_context(self, key: str) -> str:
        """Where folder ``key`` lives: the breadcrumb of its parent, or "" at the
        top of the tree. The caption a tile drawn far from the tree wears
        (see :class:`~origenerator.gui.browser_pane.TreeNavigation`)."""
        item = self._tree_item_for(key)
        if item is None or item.parent() is None:
            return ""
        return self._tree_view.breadcrumb(item.parent())

    def current_group(self):
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

    def _add_lead_tiles(self, flow, group):
        """Lead a settings folder's grid with the view's own tiles — the live
        re-roll tile and, beside it, its mirror (the same seeds again, said
        differently) — when the folder supports each. The pane grants the spot
        (:attr:`~origenerator.gui.browser_pane.PaneHost.add_lead_tiles`)."""
        if self._can_reroll(group):
            self._add_reroll_tile(flow, group)
        if self._can_request_changes(group):
            self._add_folder_request_tile(flow, group)

    def _forget_reroll_tile(self):
        """The pane is dropping what it holds, the re-roll tile with it — it is
        re-created only when a re-rolling folder is next rendered."""
        self._reroll_tile = None

    def _add_reroll_tile(self, flow, group):
        job = self._reroll.job_for(group.key)
        tile = RerollTile(job,
                          auto_generating=self._auto.is_active(group.key),
                          typical_seconds=self.typical_run_seconds(job),
                          source_picture=self._job_source_picture(job),
                          recipe_picture=self._job_recipe_picture(job))
        tile.set_selected(group.key == self._selected_reroll_key)
        tile.add_requested.connect(lambda k=group.key: self._start_reroll(k))
        tile.cancel_requested.connect(lambda k=group.key: self._cancel_reroll(k))
        tile.context_requested.connect(
            lambda pos, k=group.key: self._reroll_tile_menu(k, pos))
        tile.selected.connect(lambda k=group.key: self._select_reroll(k))
        flow.addWidget(tile)
        self._reroll_tile = tile

    def _reroll_tile_menu(self, key: str, global_pos):
        """Right-click a folder's live tile: throw away the run it is showing.

        The same act as the button on its face, on the gesture the rest of the
        grid answers — a right-click that worked on every other card and died on
        this one read as a tile that wasn't listening. The wording is the
        button's (:func:`inflight.discard_run_text`), so both say the same thing
        about the same press.

        With one more entry the button has no room for: while the folder is
        looping, that press is "Next seed" and nothing on the tile stops
        anything, so the menu carries the real stop too
        (:func:`inflight.stop_loop_text`). The loop is ended first — a discard
        while it is still on is the cue for the next seed.
        """
        menu = QMenu(self)
        auto = self._auto.is_active(key)
        discard = menu.addAction(discard_run_text(auto))
        discard.setToolTip(discard_run_tooltip(auto))
        stop = None
        if auto:
            stop = menu.addAction(stop_loop_text())
            stop.setToolTip(stop_loop_tooltip())
        chosen = menu.exec(global_pos)
        if chosen is discard:
            self._cancel_reroll(key)
        elif stop is not None and chosen is stop:
            self._auto.stop(key)
            self._cancel_reroll(key)

    # --- the folder-wide request: same seeds, changed words ----------------

    def _can_request_changes(self, group) -> bool:
        """True when this folder can be run again with its prompt rewritten.

        Everything a re-roll needs, plus at least one image to rewrite: the
        request reproduces the folder seed for seed, so a folder holding nothing
        finished yet has nothing to reproduce.
        """
        return self._can_reroll(group) and bool(self._folder_request_rows(group))

    @staticmethod
    def _folder_request_rows(group) -> list[dict]:
        """The generations a request over ``group`` would re-run: the ones that
        actually produced an image.

        A failed or in-flight row is a seed with nothing to compare against — the
        point of the request is this image said differently, so a row with no
        image is not part of it. Anything but a settings leaf holds no rows of
        its own to re-run, so it comes back empty rather than raising.
        """
        if not isinstance(group, gallery.SettingsGroup):
            return []
        return [row for row in group.rows if gallery.produced_output(row)]

    def _add_folder_request_tile(self, flow, group):
        tile = FolderRequestTile()
        tile.clicked.connect(lambda g=group: self._open_folder_request(g))
        flow.addWidget(tile)

    def _open_folder_request(self, group):
        """Open this folder's prompt in a tab, ready to be rewritten.

        Nothing is launched: the card is the start of an edit made by hand, which
        is the whole reason it is typed rather than spoken. The tab carries the
        folder's settings, its prompts marked against themselves, and its images
        tiled in the preview — see
        :meth:`GenerateConfigPanel.open_folder_request`.
        """
        rows = self._folder_request_rows(group)
        workflow = WORKFLOW_REGISTRY.get(rows[0].get("workflow_name") or "") if rows else None
        if workflow is None or self._client is None:
            return
        # One entry per run the press will make, thumbnail or not, so the count
        # in the hover is the number of images and not of readable files.
        pictures = [row.get("thumbnail_path") for row in rows]
        self._clear_reroll_selection()  # the tab is about the folder, not a live run
        self._info_tabs.open_folder_request(group.key, group.label, workflow.name,
                                      filled_params(rows[0], workflow), pictures)

    def _on_changes_requested(self, folder_key: str, workflow_name: str, params: dict):
        """A request tab's Generate: run every image of ``folder_key`` again with
        its own seed and the rewritten prompt, and land on the folder they make.

        One job per image, all of them into the one new settings folder — the
        seed is not part of what places a row (see
        :func:`~origenerator.gallery.signatures.canonical_settings`), so the
        rewrite comes out as this folder's parallel: the same seeds in the same
        recipe, saying something slightly different.

        Each new generation is linked to the image it was rewritten from, one
        by one rather than folder to folder — what it says now beside what it
        said, on the item itself, which is the same record a spoken request
        leaves (:meth:`Database.record_request`).
        """
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        # _tree_item_for, not a bare lookup: a folder has a row per side now and
        # the key a tab carries is the folder's own, with no side on it.
        item = self._tree_item_for(folder_key)
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        rows = self._folder_request_rows(group) if group is not None else []
        if self._client is None or wf is None or not rows:
            return
        params = {**wf.default_params(), **params}  # form values win over defaults
        key = self.folder_key_for(workflow_name, params)
        launching = self._info_tabs.current_config_panel()
        seed_keys = wf.seed_keys()
        launched = 0
        # Oldest first. A folder lists newest first, and a row's place in that
        # list is the order it was made in, so launching in reading order would
        # build the new folder back to front and its seeds would line up with
        # the old one's only in reverse — the one thing a glance is checking.
        for row in reversed(rows):
            # The row's own settings, filled from the workflow's defaults the way
            # a re-roll fills them — so a sparsely-recorded import still yields a
            # seed to keep rather than silently inheriting the open tab's.
            was = filled_params(row, wf)
            run = {**params, **{k: was[k] for k in seed_keys if k in was}}
            prompt_id = self._reroll.start_prepared(key, wf, run)
            if not prompt_id:
                continue  # the submit failed; the rest of the folder still goes
            launched += 1
            if launching is not None:
                launching.note_launched(self._reroll.newest_job_for(key).origin)
            self._db.record_request(
                prompt_id=prompt_id, source_prompt_id=row["prompt_id"], heard="",
                old_positive=was.get("positive_prompt", ""),
                old_negative=was.get("negative_prompt", ""),
                new_positive=run.get("positive_prompt", ""),
                new_negative=run.get("negative_prompt", ""),
            )
        logger.info("Requested changes to %s: %d of %d images queued into %s",
                    folder_key, launched, len(rows), key)
        if launched:
            self._navigate_to_reroll(key)

    def _job_source_picture(self, job) -> str | None:
        """A file showing what ``job`` came from, for the tile to stand blurred
        under the wait until the run streams a frame of its own.

        The image it was requested of first — a folder-wide request queues a run
        per image and none of them animates anything, so what it was asked about
        is the only picture it has — then the start frame an i2v or an enhance is
        built on. ``None`` for a run that came from nothing, which keeps the
        plain plate: a queued image looks like every other queued image because
        it genuinely is.
        """
        if job is None:
            return None
        record = self._db.get_request(job.prompt_id)
        source = self._db.get_generation(record["source_prompt_id"]) \
            if record else None
        if source is not None and source.get("thumbnail_path"):
            return source["thumbnail_path"]
        frame = resolve_input_image_path(job.params.get("input_image"))
        return str(frame) if frame is not None else None

    def _job_recipe_row(self, job) -> dict | None:
        """The clip whose settings ``job`` follows, as its row — or ``None``.

        The other half of what a combine's run was made from, stood gray beside
        the frame wherever the run has no picture of its own yet. Only where a
        *video* was dropped: an act picked off the Combine dropdown names what
        the run will do rather than a clip, and a picture of some video the user
        never chose reads as a job that is that video — the same reason the
        queue's rows leave it out (see BrowserPane).
        """
        row = self._db.get_generation(job.prompt_id) if job is not None else None
        if row is None or row.get("recipe_category"):
            return None
        return self._db.get_generation(row.get("recipe_video_id") or "")

    def _job_recipe_picture(self, job) -> str | None:
        """That clip as a still, for the plate on the folder's own tile."""
        recipe = self._job_recipe_row(job)
        return recipe.get("thumbnail_path") if recipe else None

    def _job_made_from(self, job) -> tuple:
        """What ``job`` was made from, for a config tab with no frame of it yet:
        the picture, and the clip looping beside it — the pair a tab draws as a
        sum, which is what the strip's corner and the tile stand in stills."""
        recipe = self._job_recipe_row(job)
        return (self._job_source_picture(job),
                self.animated_preview(recipe) if recipe is not None else None)

    def typical_run_seconds(self, job) -> float | None:
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
                self._voice.re_home(key, target)
                self._pending_auto_key = target
                key, working = target, self._auto_working[target]
            params = randomize_seeds(working["params"], working["workflow"].seed_keys())
            self._reroll.start_prepared(key, working["workflow"], params)
        else:
            self._reroll.start(key, self.group_for_key(key), self._image_rows)
        self._claim_launch(key)  # the tab on this folder shows it, and can discard it
        if not from_auto:
            # A no-op if the launch above failed to register. The tile is lit and
            # the tab on this folder, if any, follows the run; no other tab is
            # made to — the press asked for a picture, not to be shown one.
            self._select_reroll(key, land=False)
        else:
            self._note_auto_launch(key)  # its result is the loop's, not a tab's
            if self._selected_reroll_key == key:
                # The lit tile stands for the loop: watching one variation is
                # watching the next, and the tab following the folder gets the
                # new run's frames by that key without being pointed at it again.
                self._enter_reroll_selection(key)
        return self._reroll.has(key)

    def _note_auto_launch(self, key: str):
        """Remember that the loop, not a tab, asked for the run just launched — so
        no tab shows its result when it lands (:meth:`_on_reroll_finished`).

        Recorded by the id the run began under, the same name a tab knows its own
        runs by, and pruned to what is still in flight as it goes: only a live run
        can still finish, so a cancelled variation leaves nothing.
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
        # The folder's own key, not the row's: a loop is filed with the jobs it
        # launches, and those are keyed by folder wherever it is being watched from.
        group = self.current_group()
        if not checked:
            self._auto.stop_all()
        elif group is not None:
            self._begin_auto(group.key)
        self._re_aim()  # reflect the real state — a start may not take
        self._sync_discard_buttons()  # Cancel ⇄ Next seed, on all three surfaces

    def _begin_auto(self, key: str):
        """Capture the folder's settings as the loop's working params and start
        the loop, giving an open mic a prompt to steer."""
        self._capture_working(key)
        self._auto.start(key)
        if self._auto.is_active(key):
            self._voice.steer(key)  # steers this folder's prompt, if the mic is on
        else:
            self._auto_working.pop(key, None)  # the launch didn't take

    def _capture_working(self, key: str):
        """Hold the folder's settings as the loop's working params.

        The folder on screen when it is the one being looped, which is every
        press of the Auto switch; otherwise the one ``key`` names, looked up in
        the tree — Esc resuming a loop is the case where the two differ, and the
        folder the user has navigated to since is not the one to capture.
        """
        group = (self.current_group() if key == self.selected_folder_key()
                 else self.group_for_key(key))
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        workflow = WORKFLOW_REGISTRY.get(group.rows[0].get("workflow_name") or "")
        if workflow is not None:
            self._auto_working[key] = {
                "workflow": workflow, "params": filled_params(group.rows[0], workflow),
                "row": group.rows[0],
            }

    def working_prompts(self, key: str) -> dict:
        params = self._auto_working.get(key, {}).get("params", {})
        return {"positive": params.get("positive_prompt", ""),
                "negative": params.get("negative_prompt", "")}

    def steer_prompts(self, key: str, new_prompts: dict):
        """A voice command rewrote the prompts: the loop's next launches use them."""
        working = self._auto_working.get(key)
        if working is not None:
            working["params"]["positive_prompt"] = new_prompts.get("positive", "")
            working["params"]["negative_prompt"] = new_prompts.get("negative", "")

    def _working_folder_key(self, working: dict) -> str:
        """The settings-folder key the working params now belong to — recomputed as
        voice edits the prompt, so a steered loop can re-home to the matching folder."""
        row = {**working["row"], "params_json": json.dumps(working["params"])}
        return self.folder_key_of(row)

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
        if key == self._voice.steering:
            self._voice.steer(None)
            self._pending_auto_key = None
        self._re_aim()
        self._sync_discard_buttons()  # the in-flight run's button is a Cancel again

    def _sync_discard_buttons(self):
        """Re-label every button that throws a run away — the folder's live tile, the
        lower strip's rows, each config tab's — after a loop started or ended.

        Nothing else repaints them at that moment: switching Auto on over a folder
        that is already generating launches nothing, so there is no re-roll change
        to ride, and the label would keep promising a stop that the press no longer
        performs (or offering a next seed after the loop is off).
        """
        self._rerender_current_leaf()
        self._update_queue()
        self._reconcile_generating()

    # --- what the spoken words ask of this window ----------------------------

    def say(self, message: str) -> None:
        """Flash a line on the voice caption. What the shows use when there is no
        show up to put it in the corner of."""
        self._voice.say(message)

    def shelf_label(self, key: str) -> str:
        """A shelf's plain name, for a spoken word to be answered in."""
        return _SHELF_LABELS[key]

    def stand_in_shelf(self, key: str, side: str | None) -> bool:
        """Select a shelf's row, exactly as clicking it does, and say whether the
        tree had one — Recents and Starred appear only once there is one."""
        item = self._tree_item_for(oriented_key(key, side) if side else key)
        if item is None:
            return False
        self._tree.setCurrentItem(item)  # whose signal draws it
        return True

    def run_spoken_command(self, text: str) -> bool:
        """Run a command the hosting session's own microphone heard, and say
        whether it was one. The session's bridge posts them here."""
        return self._voice.run_spoken_command(text)

    def _go_to_looping_folder(self, _href: str):
        """Follow the tip's link to whichever folder is looping right now.

        Read at the click rather than baked into the link, so a loop that has
        since moved or ended takes the user to where it actually is, or nowhere.
        """
        key = self._auto.active_key()
        if key is not None:
            self._navigate_to_reroll(key)

    def rows_to_play(self) -> list[dict]:
        """The generations the slideshow would play from the view on screen: the
        shelf's collection on a shelf, else everything under the selected
        folder.  All of it: narrowing a show to its favorites or its enhanced
        pictures is the show's own doing, from the two switches on its HUD.
        """
        rows = self._browser.shelf_rows()
        if rows is None:
            group = self.current_group()
            rows = gallery.rows_under(group) if group is not None else []
        return rows

    def slideshow_subject(self) -> str:
        """What the slideshow button would play, named for its tooltip."""
        if self._showing_search():
            return "these results"
        base, orientation = _split_shelf_key(self._current_shelf_key())
        label = _SHELF_LABELS.get(base, "this folder")
        if orientation and base in _SHELF_LABELS:
            # The side leads, as it does in the shelf's own header and in a
            # folder's breadcrumb — one wording for where you are standing.
            label = f"{_ORIENTATION_LABELS[orientation]}  ›  {label}"
        return label

    # --- standalone enhance: the bank button, the selection action, the queue ---

    def _re_aim(self) -> None:
        """Re-aim everything that follows what is in front of the user: the whole
        bank, and the Enhance settings beside it.

        One call rather than nine. Which buttons an event moves is not something
        a handler should have to know — that knowledge was what two bugs came out
        of, each fixed by adding the call somebody had forgotten — so every
        handler asks for all of it and the state says how it stands.
        """
        self._bank.apply(self.bank_state())
        self._enhance.sync_panel()

    def bank_state(self) -> BankState:
        """How the bank stands right now, gathered from the seams the buttons
        belong to: the trail, the undo stack, the tree's selection, the pictures
        picked, the enhance settings, the shows, and the auto-generate loop.

        Assembled here because here is where those meet. Everything it reads is
        a question already asked by name, so the record can be written by hand in
        a test and the bank written from it with no gallery at all.
        """
        can_go_back, can_go_forward = self._trail
        undo_label = self._actions.undo_label()
        redo_label = self._actions.redo_label()
        enhance = self._enhance.offer()
        looping = self._auto.active_key()
        group = self.current_group()
        loopable = isinstance(group, gallery.SettingsGroup) and self._can_reroll(group)
        elsewhere = looping is not None and looping != getattr(group, "key", None)
        return BankState(
            back=Button(enabled=can_go_back, tip="Back"),
            forward=Button(enabled=can_go_forward, tip="Forward"),
            undo=Button(enabled=self._actions.can_undo(),
                        tip=f"Undo: {undo_label}" if undo_label else "Nothing to undo"),
            redo=Button(enabled=self._actions.can_redo(),
                        tip=f"Redo: {redo_label}" if redo_label else "Nothing to redo"),
            # Several folders picked ARE the grouping, unsaved; one folder is not
            # a grouping, and the button would only ask what it meant.
            group=Button(visible=self._selection_group is not None,
                         tip="Group the selected folders into a folder of your own"),
            star=self._star_offer(),
            enhance=Button(enabled=enhance.available, tip=enhance.tip),
            delete=self._delete_offer(),
            # Media, not rows: a folder gets its node the moment a generation
            # starts, so a folder being filled can hold nothing anyone can look at
            # yet, and a button that opens an empty show is worse than no button.
            slideshow=Button(visible=self._shows.anything_to_play(),
                             tip=f"Play {self.slideshow_subject()} as a slideshow"),
            # Lit means "a loop is running", in this folder or any other: clicking
            # it off stops whichever folder has it, from wherever the user is.
            # Greyed only when there is genuinely nothing to do. While the loop is
            # elsewhere its clickable tip says so and the plain tooltip stands
            # down, so only one of the two ever appears.
            auto=Button(enabled=loopable or looping is not None,
                        tip="" if elsewhere else self._auto_tip(loopable, looping),
                        checked=looping is not None),
            auto_tip=AUTO_ELSEWHERE_TIP if elsewhere else "",
        )

    @staticmethod
    def _auto_tip(loopable: bool, looping: str | None) -> str:
        """What the Auto toggle says it will do, for every case but the loop being
        elsewhere — that one is the clickable tip's to say."""
        if looping is not None:
            return "Auto-generate is running in this folder — click to stop it (Esc too)"
        return (
            "Auto-generate: repeatedly generate variations of this folder "
            "until toggled off (Esc stops it too)"
            if loopable else
            "Auto-generate: open a settings folder to generate variations of it"
        )

    def _star_offer(self) -> Button:
        """Star, aimed like Delete and Enhance: the picked thumbnails, else the
        folder on screen. It toggles, so the tip says which way it will go — a set
        already starred all over unstars.

        Dark where a star means nothing: a shelf, or a deleted item in the bin,
        which has no folder to be bookmarked in.
        """
        pids = self.selected_prompt_ids() if self._browser.selected_ids else []
        if pids and not self._browser.showing_trash():
            starring = not self._all_starred(pids)
            return Button(tip=f"{'Star' if starring else 'Unstar'} {len(pids)} "
                              f"item{'s' if len(pids) != 1 else ''}")
        group = None if pids else self._starrable_folder()
        if group is None:
            return Button(enabled=False, tip="Nothing here to star")
        return Button(tip=f"{'Unstar' if group.starred else 'Star'} "
                          f"folder “{group.label}”")

    def _delete_offer(self) -> Button:
        """Delete, aimed the same way: the picked thumbnails, else the folder on
        screen, with the tip saying which.

        In the bin the button's one remaining meaning is "for good", and the tip
        has to say so before it is clicked.
        """
        count = len(self._browser.selected_ids)
        if self._browser.showing_trash():
            return Button(
                enabled=bool(count),
                tip=f"Permanently delete {count} item{'s' if count != 1 else ''}"
                if count else "Pick an item to delete permanently")
        if count:
            return Button(tip=f"Delete {count} item{'s' if count != 1 else ''}")
        folder = self._current_deletable_folder()
        if folder is None:
            return Button(enabled=False, tip="Nothing to delete")
        return Button(tip=f"Delete folder “{folder.label}”")

    def _starrable_folder(self):
        """The folder on screen if a star can be set on it, else ``None``.

        A shelf has no group at all, and a multi-selection's folder isn't one
        yet — it has no row to hang a star on until it's saved, which is what
        the Group button beside this one is for."""
        if self._selection_group is not None:
            return None
        return self.current_group()

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

    def fill_the_regions(self) -> None:
        """Put a show on each satellite region — what entering origenerator
        mode means. The hosting session's bridge asks this window for it.
        """
        self._shows.fill_the_regions()

    def close_the_shows(self) -> None:
        """Give every show back — the session leaving origenerator mode, or
        this view going away with shows still up.
        """
        self._shows.close_the_shows()

    # --- a spoken request's own generation -----------------------------------

    def queue_request(self, row, workflow, params, spoken, revision) -> str:
        """Launch the revised generation and record the request under it;
        return the line to say about it.

        The revision is the target's own recipe with its prompt pair edited and
        *the same seed* — "the same picture but without X" means the picture, so
        the one thing deliberately not re-rolled is the seed that draws it.
        """
        params = {**params, "positive_prompt": revision.positive,
                  "negative_prompt": revision.negative}
        key = self.folder_key_for(row.get("workflow_name") or "", params)
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
        self._re_aim()
        self.refresh()
        updated = self._db.get_generation(prompt_id)
        if updated is not None:
            # Every tab showing this image, not just the front one — the delete
            # can come from a tab that isn't in front, and a stale list would
            # still be offering a version that is gone.
            for panel in self._info_tabs.config_panels():
                shown = panel.displayed_row()
                if shown is not None and shown.get("prompt_id") == prompt_id:
                    panel.show_completed_result(updated, self._image_rows)
        self._re_aim()  # an image with no enhancement left awaits one

    def show_location(self):
        """Where the view on screen is playing FROM, as something re-askable:
        a shelf key on a shelf, else the open folder's key.

        A key rather than the rows themselves, because the point of holding it
        is to ask again later — after a generation lands in that folder, when
        the rows are new objects and the browser is somewhere else entirely.
        """
        shelf = self._current_shelf_key()
        if shelf is not None:
            return shelf
        # The row's own key, not the folder's: which side the folder is being
        # looked at from is what decides the screen a show of it goes to.
        return (self.selected_folder_key()
                if self.current_group() is not None else None)

    def set_session_paused(self, paused: bool) -> None:
        """The hosting session's OmniPause, applied to every open show and
        remembered for the ones not opened yet (the director keeps that flag).
        The bridge calls this on the flag's edges; the memory is what makes
        the freeze cover a show the user opens mid-pause.

        And to this window's own moving pictures — OmniPause means the room
        stops, not the shows stop.  Two kinds, held in the two places that
        build them rather than widget by widget here: every looping WebP
        thumbnail, wherever it is drawn (the grid, the shelves, a tab's history
        strip, the "Animated in" strip), through
        :mod:`origenerator.gui.looping_preview`; and the real video a generate
        tab plays, through the tabs.  Wiring each widget separately is how a
        strip nobody remembered went on playing through a frozen room.

        The shows come first and the rest cannot be skipped if one of them
        raises, so each is its own step: a freeze that stopped at the shows
        left the thumbnails running with no sign of why.
        """
        self._shows.set_session_paused(paused)
        set_previews_paused(paused)
        self._info_tabs.set_previews_paused(paused)

    def region_show(self, side: str):
        """The show occupying satellite region *side*, or None. The hosting
        session's bridge asks this window for it."""
        return self._shows.region_show(side)

    def star_generation(self, prompt_id: str):
        """Bookmark a generation from a fullscreen show (its Down key) — the same
        star the gallery's own control sets."""
        self.set_items_starred([prompt_id], True)

    def trash_generation(self, prompt_id: str):
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
            self._re_aim()
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
        key = self.folder_key_of(row)
        if key in self._reroll_jobs:
            return  # this folder already has a re-roll running
        if which == "video":
            self._reroll.reroll_video_seed(key, row)
        else:
            self._reroll.reroll_image_seed(key, row, self._image_rows)
        self._select_reroll(key)  # a no-op if the launch above failed to register

    # --- combine: a video's recipe applied to a dropped image -------------

    # --- the line's answer to the press, before there is a job ------------

    def off_thread(self, work, done):
        """Run one slow call away from the UI and hand its result back here.

        A seam as much as a call: the suite replaces this with a straight-through
        version, so a test can poll or launch and inspect in one breath rather
        than pumping an event loop for every one. The poll and the combine's
        recipe match are both slow for the same reason — something on the other
        end of a socket thinks for seconds — and both answer through here.
        """
        run_off_thread(work, done)

    def enhance_offer_changed(self) -> None:
        """Re-aim the Enhance button: what the act would run on has changed."""
        self._re_aim()

    def enhance_settings(self) -> str:
        """The app-wide enhancement settings, for the session to persist."""
        return self._enhance.settings_json()

    def set_enhance_settings(self, raw: str | None) -> None:
        """Restore the enhancement settings a previous session left."""
        self._enhance.restore_settings(raw)

    def enhance_items(self, prompt_ids: list[str]) -> None:
        """Queue a standalone enhance of each of these generations — what the
        thumbnail menu and the session's own relayed command ask for."""
        self._enhance.enhance_items(prompt_ids)

    def enhance_from_slideshow(self, prompt_id: str) -> bool:
        """A held slide asked to be enhanced; whether a run started."""
        return self._enhance.enhance_from_slideshow(prompt_id)

    def enhance_it(self, prompt_id: str | None) -> tuple[str | None, str]:
        """The spoken "enhance" over a picture."""
        return self._enhance.enhance_it(prompt_id)

    def fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str]:
        """The spoken "fix <part>" over a picture."""
        return self._enhance.fix_parts(prompt_id, parts)

    def image_rows(self) -> list[dict]:
        """Every image row the gallery is holding, as its last rebuild read them."""
        return self._image_rows

    def queue_changed(self) -> None:
        """Redraw the line — a stand-in row went on it or came off it."""
        self._update_queue()

    def ask_which_seed(self, workflow, *, can_reroll_image: bool) -> str | None:
        """Ask which seed to re-roll rather than reproduce a past run."""
        return offer_reroll(self, workflow, can_reroll_image=can_reroll_image)

    def tell(self, title: str, message: str) -> None:
        """Say something that needs acknowledging, in a dialog over this window."""
        QMessageBox.information(self, title, message)

    def combine_selection(self) -> dict:
        """What the combine panel is holding, for session save."""
        return self._combine.selection()

    def restore_combine_selection(self, saved) -> None:
        """Put the combine panel back the way a session left it."""
        self._combine.restore(saved)

    def genau_it(self, image_id: str | None) -> tuple[str | None, str]:
        """Animate a picture as a Genau clip — what a spoken "genau it" runs."""
        return self._combine.genau_it(image_id)

    def reveal_launch(self, key: str):
        """Show a just-launched combine. If its (image × settings) folder already
        exists, open it and mirror the live tile; otherwise it's a brand-new
        combination with no folder yet, so park on Recents — where its in-flight
        card shows — and remember the key for :meth:`_on_reroll_finished` to drill
        into once the finished row gives the folder a node."""
        item = self._tree_item_for(key)
        if item is not None:
            self._tree.setCurrentItem(item)  # existing folder: watch the live tile
            self._select_reroll(key)
        elif (recents := self._shelf_item(_RECENTS_KEY, self._launched_side(key))) is not None:
            self._pending_combine_key = key
            self._tree.setCurrentItem(recents)

    def _launched_side(self, key: str) -> str:
        """Which side a job just launched in folder ``key`` will land on.

        Read off the size it asked for, since it has no picture to measure yet —
        the same thing that puts its in-flight card on one Recents shelf rather
        than the other. With no job to ask, the side being browsed.
        """
        job = self._reroll.job_for(key)
        asked = requested_orientation(job.params) if job is not None else None
        return asked or self.side_in_view()

    # --- re-roll as the info-pane source ----------------------------------

    def _reveal_reroll(self, key: str):
        """Open the folder a re-roll runs in and select its live tile — an
        in-flight card's click, relayed by the browser pane.

        Leaves a running search first: results take the pane over, and picking
        a tree row underneath them re-scopes the search rather than showing the
        folder — so the click landed on the row and the wall of results stayed
        up, which reads as the click doing nothing at all.
        """
        self._search.leave()
        item = self._tree_item_for(key)
        if item is None:
            # A folder the tree has not drawn yet: the first run in a brand-new
            # settings folder makes the node, and this click can land in the
            # gap.  Rebuild and ask once more rather than dropping the gesture.
            self.refresh()
            item = self._tree_item_for(key)
        if item is None:
            logger.info("Nothing to reveal for %s: no folder row", key)
            return
        self._tree.setCurrentItem(item)  # shows the folder and its re-roll tile
        self._select_reroll(key)

    def _select_reroll(self, key: str, *, land: bool = True):
        """Make a running re-roll's tile the selected item, and show the run
        full size in the tab it belongs to.

        That tab is never simply the one in front: it is a tab already following
        this folder, else the tab that launched the run — a Generate, or a claim
        on the folder's own launch (:meth:`_claim_launch`). With ``land``, a run
        no tab is for is landed the way a clicked thumbnail is: in the front tab
        when its settings are this very folder, else in the pane's preview tab,
        seeded from the run's own settings
        (:meth:`GenerateConfigPanel.show_running_generation`) so the tab is *for*
        this run — its form is the run's recipe, its bar fills with the run's
        progress, its button discards it, and its preview follows the run's
        frames to the picture they land as
        (:meth:`GenerateConfigPanel.watch_folder`). That is what a click on the
        tile or on the shelf's card asks for, and the tab comes to the front as a
        clicked thumbnail's does. The folder tile's "+" passes ``land=False``: a
        press there is a request to make something, not to be shown it, so a
        tab parked on other settings is left exactly as it was and the run shows
        on its tile until the tile is clicked.
        """
        job = self._reroll_jobs.get(key)
        if job is None:
            return
        self._enter_reroll_selection(key)
        tabs = self._info_tabs
        panel = tabs.panel_watching(key) or tabs.panel_that_launched(job.origin)
        if panel is None:
            if not land:
                return
            front = tabs.current_config_panel()
            if (front is not None and front.settings_key() is not None
                    and self._panel_reroll_key(front) == key):
                panel = front
            else:
                panel = tabs.landing_panel()
                row = self._db.get_generation(job.prompt_id)
                if row is not None:
                    panel.show_running_generation(row)
            if job.origin not in panel.launched_runs():
                panel.note_launched(job.origin)  # its Cancel and progress are this run's now
            self._reconcile_generating()
        panel.watch_folder(key, job.last_preview, self._wait_note(key),
                           self._job_made_from(job))
        tabs.setCurrentWidget(panel)

    def _restore_reroll_selection(self, key: str | None):
        """After a rebuild, re-assert a still-running re-roll as the selected
        item — its tile lit again in the folder now on screen. The tabs following
        the run kept their frames across the rebuild (an i2v's image frame while
        the video stage warms up included); the tile is the one thing redrawn.
        A no-op unless that re-roll is still running in the folder on screen.
        """
        # ``key`` is the folder the job is filed under, so what it is checked
        # against is the folder on screen rather than the row showing it.
        if (key is None or key not in self._reroll_jobs
                or getattr(self.current_group(), "key", None) != key):
            return
        self._enter_reroll_selection(key)

    def _enter_reroll_selection(self, key: str):
        """Make re-roll ``key``'s tile the gallery's selected item, in place of
        any saved generation."""
        self._selected_reroll_key = key
        self._selected_row = None  # a running re-roll isn't a saved generation
        self._browser.clear_thumbnail_selection()
        if self._reroll_tile is not None:
            self._reroll_tile.set_selected(True)

    def _wait_note(self, key: str) -> str | None:
        """What re-roll ``key`` is waiting on, when another app is holding ComfyUI
        in front of it — a following tab's wait text, in place of a bare 'waiting
        for preview'. Its own folder's queue isn't a wait worth naming."""
        job = self._reroll_jobs.get(key)
        return queue_wait_text(job.foreign_ahead) if job is not None else None

    def _refresh_wait_note(self):
        """Keep that wait text current between rebuilds, in every tab standing on
        one. The count falls as the queue drains, and a pane frozen on a stale
        number is the mystery this is here to end. Only while the followed run
        has streamed no frame — once it has, the frame itself is the answer."""
        for panel in self._info_tabs.config_panels():
            key = panel.watched_key()
            if key is not None and panel.is_awaiting_frame():
                panel.show_live_wait(self._wait_note(key))

    def _on_reroll_preview(self, key: str, prompt_id: str, data: bytes):
        """A run streamed a frame: put it in every tab following its folder — and
        nowhere else. A tab that isn't following the folder is showing something
        of its own, and a frame painted over that is the picture nobody asked for.
        """
        for panel in self._info_tabs.watchers_of(key):
            panel.show_live_frame(data)
        # An enhance's frames show on the tile of the image being enhanced and in
        # the version list of any tab displaying it — an enhancement isn't a
        # generation taking a preview over.
        self._enhance.reconcile()
        # And straight onto an open show, which is watching for exactly this.
        self._shows.note_generating(prompt_id, data)

    def _clear_reroll_selection(self):
        """Stop treating a running re-roll's tile as the selected item — a saved
        generation is the selection now, or the re-roll has ended."""
        self._selected_reroll_key = None
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
        """A run in folder ``key`` ended with nothing to show (cancelled or
        failed): its tile stops being the selected item and a show opened over
        its frames closes; and once the folder has no run left, the tabs
        following it put their own pictures back. While it still has one — the
        next of a batch, the loop's next seed — they keep following, since that
        run's frames are what comes next."""
        if key == self._selected_reroll_key:
            self._shows.close_live()
            self._clear_reroll_selection()
            self._selected_row = None
        if not self._reroll.has(key):
            for panel in self._info_tabs.watchers_of(key):
                panel.stop_watching()

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
        folded = False
        if finished_row is not None \
                and finished_row.get("workflow_name") == gallery.ENHANCE_WORKFLOW:
            # A standalone enhance is an upgrade, not a generation: fold its
            # output onto the image it enhanced — same row, same folder, same
            # star, now wearing the enhanced pixels and badge — and let the
            # upgraded image be what the front tab shows.
            source_id = gallery.fold_enhancement(self._db, finished_row)
            if source_id is not None:
                folded = True
                finished_row = self._db.get_generation(source_id)
                # A slideshow that asked for this one swaps the slide for it.
                self._shows.note_enhanced(finished_row)
        self._combine.send_to_genau_if_requested(finished_row)
        # The tile stops being the selected item — unless a loop is running here,
        # where the key stands for the loop rather than for this one variation:
        # someone watching it churn is watching what it does next, so the
        # selection waits for the variation after this one (see :meth:`_start_reroll`).
        if key == self._selected_reroll_key and not self._auto.is_active(key):
            self._clear_reroll_selection()  # refresh re-selects it as a finished thumbnail
        self.refresh()
        self._shows.note_finished(finished_row)  # a show of its folder gains it
        self._show_reroll_result_in_tab(finished_row, launcher)
        if folded:
            # The image itself changed — it now holds a level it did not a
            # moment ago — and a tab holds the row it was handed, not a live
            # view of the database. Without this the new version reaches the
            # list only when the tab is next opened, which is a tab away and
            # back.
            self._info_tabs.refresh_displayed(finished_row, self._image_rows)
        self._show_landed_to_watchers(key, finished_row, launcher)
        # A voice-steered loop that re-homed to a new-prompt folder: open it now that
        # its first generation has given the folder a node.
        if self._pending_auto_key is not None:
            item = self._tree_item_for(self._pending_auto_key)
            if item is not None:
                self._pending_auto_key = None
                self._tree.setCurrentItem(item)
        # A combine whose brand-new folder we parked off (on Recents) now has a
        # finished row, so the rebuild above gave that folder a node: drill in.
        if key == self._pending_combine_key:
            self._pending_combine_key = None
            item = self._tree_item_for(key)
            if item is not None:
                self._tree.setCurrentItem(item)
        self._enhance.forget(prompt_id)  # a run that is over is nobody's enhance
        self._reconcile_generating()  # the run ended: the front tab drops its Cancel
        self._auto.note_finished(key)  # if auto-looping this folder, launch the next
        self._enhance.enhance_when_wanted(finished_row)  # while the Auto switch is on
        self._re_aim()  # a landed enhance may retire the button
        self._enhance.reconcile()  # the live tile gives way to the level

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

    def _show_landed_to_watchers(self, key: str, finished_row: dict | None, launcher):
        """The run a tab was following has landed: put its picture where its live
        frames were, in every tab following folder ``key``.

        Without this a tab watching a loop — or a fullscreen show opened over
        those frames — would sit on the last partial frame of a run that has
        finished. Only the preview changes: the tab holds no more of a run it
        didn't ask for. The ``launcher`` is skipped, having just been given the
        whole end-state instead.
        """
        if finished_row is None or not gallery.produced_output(finished_row):
            return
        for panel in self._info_tabs.watchers_of(key):
            if panel is not launcher:
                panel.show_finished_media(finished_row)

    def _on_reroll_failed(self, key: str, message: str = ""):
        """A re-roll failed (recorded by the controller): let go of it wherever it
        was being watched, redraw the folder without its tile, and SAY SO.

        A failed run leaves nothing — no file, so no tile, and the row it
        does leave is one every shelf filters out for having produced nothing. So
        without this the whole thing simply vanished: a couple of minutes of GPU,
        the tile disappearing off the strip, and no word anywhere but the log.
        The user watching it took that for a success and went looking for the
        clip. The same dialog a failed hand-off to a sibling app gets, for the
        same reason: it is the only thing that happens, so it has to be visible.
        """
        self._auto.note_failed(key)  # end the loop rather than spin on a broken workflow
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()  # the run ended: the front tab drops its Cancel
        self._enhance.reconcile()  # nothing is cooking for it now
        QMessageBox.warning(self, "Generation failed", format_execution_error(message))

    def _rerender_current_leaf(self):
        """Redraw the open settings folder so its re-roll tile reflects the job."""
        group = self.current_group()
        if isinstance(group, gallery.SettingsGroup):
            self._browser.show_thumbnails(group)

    def visible_prompt_ids(self) -> list[str]:
        return self._browser.visible_prompt_ids()

    def media_types(self) -> set[str]:
        """The media types the gallery's two ticks currently include — what
        the folder tree, every shelf, the in-flight cards and the search index are
        all built from. Both on (the default) means every type; both off means
        none."""
        types = set()
        if self._image_cb.isChecked():
            types.add("image")
        if self._video_cb.isChecked():
            types.add("video")
        return types

    def _on_media_filter_changed(self, _checked=False):
        """A media-type tick toggled: rebuild the gallery under the new filter.

        A full rebuild rather than a re-list, because the ticks decide which
        *folders* exist as well as which items do — the tree, the shelves and the
        search index are all built from the same narrowed set."""
        self._browser.restart_recents_listing()  # a new filter is a new listing
        self.refresh()
        # A filter that empties the gallery leaves the tree with no row to
        # select, so the folder-selected signal that normally re-syncs this
        # button never fires — and it went on offering a show of nothing.
        self._re_aim()

    def queue_now(self) -> tuple[list, int]:
        """What is in flight here and how much of ComfyUI's queue is another
        app's — the pair the lower strip and a show's corner plate both draw."""
        return self._inflight_items(), self._foreign_queue.total

    def _inflight_items(self, rows=None, requests=None) -> list:
        return self._browser.inflight_items(rows=rows, requests=requests)

    def _update_queue(self, inflight=None):
        """Feed the lower strip every in-flight job, in the order ComfyUI will
        work through them, plus whatever another app has on ComfyUI — so the whole
        queue shows from anywhere, and one that isn't ours is visible before
        Generate rather than after.

        After those, any Generate pressed but not yet turned into a job
        (:meth:`CombineController._show_launching`). They go on here rather than
        in the in-flight list itself: that list is what the database says is in
        flight, and
        these have no row in it: they are the press's answer, not a record of
        anything, and they last only until the real row exists.

        An open slideshow is fed the same list twice over: once for the queue it
        covers, which is the one stretch where the line deliberately stops
        moving, and once for the slides themselves, since a run that has begun to
        look like something is a slide of that show.

        ``inflight`` is the already-built card list, when the caller (the poll)
        holds one; every other caller lets it be built fresh here.
        """
        items = (self._inflight_items() if inflight is None else inflight) \
            + self._combine.launching_rows()
        self._queue.set_items(items, self._foreign_queue.total)
        self._shows.note_queue(items, self._foreign_queue.total)
        self._shows.note_in_flight(items)

    def _refresh_foreign_queue(self):
        """Re-read what another app has on the shared ComfyUI.

        Read whether or not anything of ours is in flight: the point is to see a
        queue full of somebody else's work *before* pressing Generate, instead of
        learning about it from a submit that reports six jobs ahead of it out of
        nowhere. ComfyUI outlives every app that queues on it, so that backlog can
        be a branch preview's background experiments that outlived the preview.
        """
        queue = _read_foreign_queue(self._client)
        if queue is not None:
            self._foreign_queue = queue

    def clear_foreign_queue(self):
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

    def selected_prompt_ids(self) -> list[str]:
        return self._browser.selected_prompt_ids()

    # --- deletion & undo ---------------------------------------------------

    def generation_menu(self, prompt_ids: list[str], global_pos):
        """The right-click menu a generation's picture offers, wherever it is shown.

        One menu rather than one per surface: a thumbnail in the browser pane and
        the preview in a config tab are looking at the same generation, so a
        right-click has to reach the same four acts either way — go to its folder,
        bookmark it, enhance it, bin it.

        "Go to folder" is left off when the pane already IS that folder, which is
        what makes it appear exactly where it is worth having: on the shelves and
        among a search's hits, where what you are looking at was gathered from
        somewhere else. Enhance is offered whenever any picked item is a finished
        image — the handler skips the rest — and enhances deliberately, so an
        image that already holds one is re-enhanced rather than skipped; the
        corner's plus is where "you already have this one" is said. The star entry
        reads Unstar only when every picked item is already starred, and toggles
        the whole selection to the opposite state.

        A fifth act appears only while something is being made of a picked image:
        cancel the enhancement in flight. An enhancement has no card of its own —
        it is shown on the tile of the image it improves, under a scrim — so this
        menu is the only thing that tile can be asked to stop it with, and without
        it the run had to be hunted down among the lower strip's rows. It sits
        beside Enhance, the act that started it.
        """
        rows = [row for pid in prompt_ids
                if (row := self._db.get_generation(pid)) is not None]
        if not rows:
            return
        count = len(rows)
        suffix = f" {count} item{'s' if count != 1 else ''}"
        menu = QMenu(self)
        folder_action = None
        if count == 1 and self._can_open_containing_folder(rows[0]):
            folder_action = menu.addAction("Go to folder")
            menu.addSeparator()
        all_starred = all(row.get("starred") for row in rows)
        star_action = menu.addAction(("Unstar" if all_starred else "Star") + suffix)
        enhanceable = [row["prompt_id"] for row in rows
                       if gallery.is_enhanceable_row(row)]
        enhance_action = None
        if enhanceable:
            n = len(enhanceable)
            enhance_action = menu.addAction(
                f"Enhance {n} image{'s' if n != 1 else ''}"
            )
        cooking = self._enhance.jobs_targeting(rows)
        cancel_action = None
        if cooking:
            n = len(cooking)
            cancel_action = menu.addAction(
                f"Cancel {n} enhancement{'s' if n != 1 else ''}"
            )
        delete_action = menu.addAction("Delete" + suffix)
        chosen = menu.exec(global_pos)
        if folder_action is not None and chosen is folder_action:
            self.follow_link(rows[0]["prompt_id"])
        elif chosen is star_action:
            self.set_items_starred([row["prompt_id"] for row in rows], not all_starred)
        elif enhance_action is not None and chosen is enhance_action:
            self._enhance.enhance_items(enhanceable)
        elif cancel_action is not None and chosen is cancel_action:
            self._enhance.cancel_for(rows)
        elif chosen is delete_action:
            self._delete_rows(rows)

    def _can_open_containing_folder(self, row: dict) -> bool:
        """Whether there is a folder to send this generation's picture to.

        A deleted one has none — it left its folder when its row did — and neither
        has one whose folder is already the pane you are standing in, where going
        there would be a click that changes nothing.
        """
        if row.get("deleted_at") is not None:
            return False
        leaf = self._leaf_by_id.get(row.get("prompt_id"))
        return leaf is not None and leaf is not self._tree.currentItem()

    def run_item_action(self, prompt_id: str, action: str):
        """Run one corner control's act on one generation.

        The corner controls are drawn on a particular picture, so unlike the menu
        they never act on a selection: pressing the star on a tile bookmarks THAT
        tile, whichever tiles happen to be picked.
        """
        row = self._db.get_generation(prompt_id)
        if row is None:
            return
        if action == corner_controls.STAR:
            self.set_items_starred([prompt_id], not row.get("starred"))
        elif action == corner_controls.TRASH:
            self._delete_rows([row])
        elif action == corner_controls.ENHANCE:
            self._enhance.enhance_items([prompt_id])

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
        """The held deletions the Trash shelf offers."""
        return self._db.list_deletions()

    def _on_trash_action(self, prompt_id: str, action_id: str):
        """A Trash tile's hover control: restore this item, or end it now."""
        if action_id == "restore":
            self.restore_from_trash([prompt_id])
        else:
            self.purge_from_trash([prompt_id])

    def _trash_menu(self, global_pos):
        """Right-click on the Trash shelf: restore or permanently delete the
        picked items — the same two actions the tiles' hover corners carry,
        reachable for a whole selection at once. The pane has already narrowed
        the selection to the tile under the cursor when it was outside it."""
        ids = self.selected_prompt_ids()
        suffix = f" {len(ids)} item{'s' if len(ids) != 1 else ''}"
        menu = QMenu(self)
        restore_action = menu.addAction("Restore" + suffix)
        purge_action = menu.addAction("Delete" + suffix + " permanently")
        chosen = menu.exec(global_pos)
        if chosen is restore_action:
            self.restore_from_trash(ids)
        elif chosen is purge_action:
            self.purge_from_trash(ids)

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
        if restored:
            self._go_to_generation(restored)

    def purge_from_trash(self, prompt_ids):
        """End deleted items for good — nothing else ever will. Confirmed
        first, and pointedly: this is the one action in the gallery with no undo
        and no second copy under it."""
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
        group = self.current_group()
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
        item = self._tree_item_for(group.key)
        return item.parent() if item is not None else None

    def _keys_under(self, group) -> set[str]:
        """The tree keys of every row drawing ``group``, and of every row nested
        under those — what a delete of ``group`` takes off the tree, so a return
        target can avoid them.

        Both sides, because a folder holding both shapes is drawn twice and the
        delete takes both copies.
        """
        keys, stack = set(), [self._item_by_key[key] for key
                              in self._tree_view.keys_for_folder(group.key)]
        while stack:
            node = stack.pop()
            if node.data(0, _GROUP_ROLE) is not None:
                keys.add(node.data(0, _TREE_KEY_ROLE))
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
        self._shows.release_media(paths)

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
        self._re_aim()

    def _undo(self):
        if not self._actions.can_undo():
            return
        focus = self._actions.undo()  # a restored generation to return to, if any
        self._browser.clear_selection()
        self.refresh()
        # After undoing a delete, go back to the folder it emptied (now restored),
        # rather than leaving the user on the parent we'd navigated to.
        if focus:
            self._go_to_generation(focus)
        self._re_aim()

    def _redo(self):
        """Re-apply what Undo took back. There is nothing to navigate to — a redo
        takes something away rather than restoring it — so this only rebuilds."""
        if not self._actions.can_redo():
            return
        self._actions.redo()
        self._browser.clear_selection()
        self.refresh()
        self._re_aim()

    def _confirm(self, text: str) -> bool:
        reply = QMessageBox.question(
            self, "Delete", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    # --- rename & star -----------------------------------------------------

    def _on_tree_context_menu(self, item, global_pos: QPoint):
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
        if item.data(0, _GROUP_ROLE) is not None:
            # The row under the cursor, not the folder it draws: the same folder
            # on the other side is a different row with its own menu.
            self._folder_context_menu(item.data(0, _TREE_KEY_ROLE), global_pos)

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
        group = self.group_for_key(key)
        if group is None:
            return
        if isinstance(group, gallery.CustomGroup):
            self._custom_folder_context_menu(group, global_pos)
            return
        menu = QMenu(self)
        # No rename for a folder named after what it holds — a workflow, a model,
        # a LoRA, a source image (see :func:`gallery.is_renamable`).
        rename_action = menu.addAction("Rename…") if gallery.is_renamable(group) else None
        star_action = menu.addAction("Unstar" if group.starred else "Star")
        # Inside a folder the user made, an item tile can also be dropped from it.
        # Right-clicking the same folder in the tree offers nothing of the sort —
        # it isn't in any grouping from there.
        open_custom = self.current_group()
        remove_action = None
        if isinstance(open_custom, gallery.CustomGroup) and open_custom.folder_id is not None \
                and any(m.key == group.key for m in gallery.child_groups(open_custom)):
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
            self._remove_from_custom_folder(open_custom, group.key)
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
                   if not any(m.key == _base_of(key) for m in gallery.child_groups(f))]
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
        group = self.group_for_key(key)
        current = group.label if group is not None else ""
        # A derived folder's name is an overlay over the one its settings produce,
        # so blank resets it; a custom folder's name is all it has, so it can't.
        prompt = ("Folder name:" if gallery.is_custom_key(key)
                  else "Folder name (blank to reset):")
        text, ok = QInputDialog.getText(self, "Rename Folder", prompt, text=current)
        if ok:
            self._apply_rename(key, text)

    def _apply_rename(self, key: str, name: str):
        # The name belongs to the folder, so it is saved against the folder's own
        # key — both sides draw the renamed folder.
        self._actions.rename_folder(_base_of(key), name.strip() or None)
        self.refresh()
        self._re_aim()

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
        self._re_aim()
        # Rebuild after the editor has fully closed to avoid deleting it mid-edit.
        defer(self, self.refresh)

    def _begin_title_rename(self):
        """Double-clicking the title bar edits the selected folder's name — but not
        while several are picked, where the title is a count of them and the rename
        would land on whichever one happened to be current, and not over a search,
        where the title is the query and there is no folder under it to rename.

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
        group = self.current_group()
        if group is None:
            return
        self._actions.rename_folder(group.key, name.strip() or None)
        self._re_aim()
        # Rebuild on the next turn of the event loop rather than here. What
        # usually ends this edit is a click somewhere else in the window, and
        # "somewhere else" is most often a thumbnail — so refreshing inside the
        # editor's own focus-out deletes the browser pane that Qt is still
        # delivering that click to, and the app goes down with an access
        # violation. The tree's inline rename defers for the same reason.
        defer(self, self.refresh)

    def _toggle_star(self, key: str):
        # A star is the folder's, not the row's: both sides draw the same folder,
        # so starring it on one is starring it.
        group = self.group_for_key(key)
        self._db.set_folder_starred(_base_of(key), not bool(group and group.starred))
        self.refresh()

    def _delete_folder_by_key(self, key: str):
        """Delete the folder a hover-row trash click names."""
        group = self.group_for_key(key)
        if group is not None:
            self._delete_folder(group)

    # --- the selected generation drives a config tab -----------------------

    def row_for(self, prompt_id: str) -> dict | None:
        """The generation under a tile: the gallery's own row, else a held
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
        """A generation was picked, wherever it was picked — in a folder, on a
        shelf, among a search's hits, through a followed link, by a step Back:
        it becomes the selected item and loads into a config tab, its output in
        the preview, its settings in the form, a footer for its media type.
        Which tab is :meth:`InfoPaneTabs.load_selection`'s to say — the one
        already on this row's folder, else the pane's preview tab — and a tab is
        only ever painted through there: no tab's preview is repainted from the
        outside, so what a tab shows is always what that tab is for.
        """
        row = self.row_for(prompt_id)
        if not row:
            return
        self._select_saved_generation(row)
        self._info_tabs.load_selection(row, self._image_rows,
                                       request=self._request_for(prompt_id))
        # Each generation looked at is its own browsing step, wherever it was
        # looked at: in a folder, on a shelf, or among a search's hits. The view it
        # was picked in goes on the stack with it, so Back returns to the item AND
        # to the pane it was one of — not to some other folder that also holds it.
        self._navigation.record(prompt_id)

    def _select_saved_generation(self, row: dict):
        """Make a saved generation the gallery's selected item, in place of any
        running re-roll's tile — the gallery's own state, no tab touched."""
        self._clear_reroll_selection()
        self._selected_row = row

    def animated_preview(self, row: dict) -> str | None:
        """The looping-WebP preview for a video ``row`` — ``None`` for an image or a
        video whose file is gone or unreadable, so the tile shows its still instead.
        Feeds the grid tiles and the Recents shelf (the info pane's 'Animated in'
        strip resolves the same path through :func:`gallery.animated_preview_path`)."""
        return gallery.animated_preview_path(row, COMFYUI_OUTPUT_DIR, THUMB_DIR)

    def follow_link(self, prompt_id: str):
        """Follow a link to another generation — a video's source image, an
        image's animation, a "Go to folder", a search hit's double-click.

        Only the search handling is its own: following a link is a decision to go
        somewhere, so a running query is put away first, or the folder the move
        opens is drawn straight over by the results the link was clicked among.
        The going itself is the one move every other gesture makes.
        """
        self._search.leave()
        self._go_to_generation(prompt_id)

    def _go_to_generation(self, prompt_id: str):
        """Go to a generation: open the folder holding it, draw that folder, pick
        the item's own tile in it, and show the item in the info pane.

        The single move under every "take me to this picture" — a link, a
        right-click "Go to folder", Back and Forward, a hosted show's lock, an
        undo landing on what it brought back. There is no lighter version of it
        and no separate path for any of them: a move that did some of those and
        not the others is how the middle pane came to be standing still while the
        tab beside it filled with the item that was asked for.

        The folder it opens on the way is not a stop of its own — passing
        through somewhere to reach an item is not somewhere you went — so that
        step records nothing, and the arrival at the item records itself. Whether
        the move is a stop at all is the caller's business: Back and Forward walk
        history rather than add to it, and suppress it around this.
        """
        item = self._folder_row_for(prompt_id)
        if item is not None:
            with self._navigation.off_the_record():
                # Setting a row that is already its half's current one fires no
                # signal, and the pane would go on showing whatever it holds —
                # the shelf or the search hits the move was made from. So the
                # drawing is done here in that case rather than waited for.
                drawn_by_the_signal = not self._tree.is_current(item)
                self._tree.setCurrentItem(item)
                if not drawn_by_the_signal:
                    self._on_folder_selected(item, None)
        self._on_thumbnail_clicked(prompt_id)   # the arrival: its tab, and its stop
        self._browser.reveal_tile(prompt_id)    # once the folder's tiles are drawn
        logger.info("Went to %s: folder %s, %d tiles drawn, tile shown %s",
                    prompt_id, self.selected_folder_key(),
                    len(self._browser.visible_prompt_ids()),
                    prompt_id in self._browser.visible_prompt_ids())

    def _folder_row_for(self, prompt_id: str):
        """The tree row of the folder a generation lives in: its settings row, or
        — for one the tree holds no row for, a generation that failed with no
        file, or one held in the trash — the row its settings key names.

        ``None`` only when the tree has nowhere at all to put it, which is the
        one case a move has no folder to open. Answering ``None`` for anything
        less than that is what left a move opening no folder while the item it
        named went on to fill the info pane, so the click read as having done
        nothing.
        """
        leaf = self._leaf_by_id.get(prompt_id)
        if leaf is not None:
            return leaf
        row = self.row_for(prompt_id)
        if row is None:
            return None
        key = self.folder_key_of(row)
        return self._tree_item_for(key) if key else None

    # --- back/forward navigation ------------------------------------------

    def _current_shelf_key(self) -> str | None:
        """The key of the shelf on screen — one side's Latest, Favorites,
        Experiments, Requests or Trash — or ``None`` off them."""
        key = self.selected_folder_key()
        base, _orientation = _split_shelf_key(key)
        return key if base in _SHELF_KEYS else None




    def _clear_metadata(self):
        """Drop the gallery's selection: no saved generation is the selected
        item. The tabs are left as they are — each shows what it is for, and
        nothing about the selection going was about any of them."""
        self._selected_row = None

    def pin_config_tab(self):
        """Keep the front config tab — the double-click half of the pane's
        preview-tab rule. Relayed here because the browser owns the gesture and
        the info pane owns the tabs."""
        self._info_tabs.pin_current_tab()


def _group_workflow(group) -> str | None:
    """The single workflow a folder belongs to, or ``None`` if it spans several
    (the All row) and so has no one workflow time to fall back on."""
    if isinstance(group, gallery.AllGroup):
        return None
    if isinstance(group, gallery.WorkflowGroup):
        return group.workflow_name
    rows = gallery.rows_under(group)  # model or settings folder: ask its rows
    return rows[0]["workflow_name"] if rows else None


class _PollFacts(NamedTuple):
    """One tick's answers from ComfyUI, fetched together and applied together."""

    histories: dict  # prompt_id -> its /history, for jobs that may have finished
    backlogs: dict   # prompt_id -> another app's jobs ahead of it (None unread)
    foreign: object  # the shared queue's state, or None for nothing-to-read


def _fetch_poll_facts(client, targets) -> _PollFacts:
    """Every blocking read one poll tick makes of ComfyUI, batched.

    ``targets`` is ``(prompt_id, state)`` per live job at tick time — names and
    strings rather than the job objects, so nothing here touches GUI-owned
    state. /history is pulled for a job whose completion could have been
    missed, the queue position for one still waiting, and the shared queue once
    for the strip. Each read fails soft, exactly as it did when made inline: a
    fetch that raises leaves its entry unread rather than failing the tick.
    """
    histories, backlogs = {}, {}
    if client is not None:
        for prompt_id, state in targets:
            if state in ("queued", "running"):
                try:
                    histories[prompt_id] = client.fetch_history(prompt_id)
                except Exception as e:
                    logger.debug("Reconcile fetch failed for %s: %s", prompt_id, e)
            if state == "queued":
                try:
                    backlogs[prompt_id] = client.foreign_backlog(prompt_id)
                except Exception as e:
                    logger.debug("Could not read the queue position of %s: %s",
                                 prompt_id, e)
                    backlogs[prompt_id] = None
    return _PollFacts(histories, backlogs, _read_foreign_queue(client))


def _read_foreign_queue(client):
    """The shared ComfyUI queue's current state, ``None`` with no client to ask.

    Unreadable (server down, wedged, restarting) claims nothing rather than
    leave a stale count on screen offering to clear a queue we can no longer
    see.
    """
    if client is None:
        return None
    try:
        return client.foreign_queue()
    except Exception as e:
        logger.debug("Could not read ComfyUI's queue: %s", e)
        return ForeignQueue(running=[], pending=[])


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
