from __future__ import annotations

import logging
from typing import NamedTuple

from PyQt6.QtCore import QEvent, QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from shared_ui.find_bar import FindBar
from shared_ui.tick_control import TickControl

from origenerator import (
    gallery,
    outside_videos,
    timing,
    trash_collection,
)
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_api import format_execution_error
from origenerator.comfyui_client import ComfyUIClient, ForeignQueue
from origenerator.config import (
    OUTPUT_PLACES,
    THUMB_DIR,
    TRASH_DIR,
)
from origenerator.db import Database
from origenerator.fun_time_bridge import ask_for_origenerator_mode
from origenerator.fun_time_mode import FunTimeSession
from origenerator.gallery.collection import COLLECTION_LABELS, FolderCollection, folder_collection
from origenerator.gallery.collection import (
    ENHANCED_KEY as _ENHANCED_KEY,
)
from origenerator.gallery.collection import (
    EXPERIMENTS_KEY as _EXPERIMENTS_KEY,
)
from origenerator.gallery.collection import (
    FAVORITES_KEY as _FAVORITES_KEY,
)
from origenerator.gallery.collection import (
    LATEST_KEY as _LATEST_KEY,
)
from origenerator.gallery.collection import (
    TRASH_KEY as _TRASH_KEY,
)
from origenerator.gallery.sides import (
    LANDSCAPE as _LANDSCAPE,
)
from origenerator.gallery.sides import (
    SEPARATE as _SEPARATE,
)
from origenerator.gallery.sides import (
    TOGETHER as _TOGETHER,
)
from origenerator.gallery.sides import (
    side_covers as _side_covers,
)
from origenerator.gallery.sides import (
    side_holding as _side_holding,
)
from origenerator.gallery_actions import GalleryActions, GalleryEnvironment
from origenerator.generation_config import (
    filled_params,
    randomize_seeds,
    would_reproduce_a_completed_run,
)
from origenerator.generation_state import GenerationSource
from origenerator.gui import corner_buttons, omnipause
from origenerator.gui.auto_generate_controller import AutoGenerateController
from origenerator.gui.browser_pane import (
    REROLL_VIDEO,
    BrowserPane,
    BrowserScrollArea,
    LeadTiles,
    PaneHost,
    TreeNavigation,
    play_once_made,
)
from origenerator.gui.busy_cursor import working
from origenerator.gui.combination import Combination
from origenerator.gui.combine_controller import CombineController
from origenerator.gui.copy_names import copy_names, offer_copy_names
from origenerator.gui.drop_target import DropTarget
from origenerator.gui.enhance_controller import ALREADY_AT_THESE_SETTINGS, EnhanceController, Offer
from origenerator.gui.folder_modify_tile import FolderModifyTile
from origenerator.gui.folder_path_header import FolderPathHeader
from origenerator.gui.folder_tree import TREE_KEY_ROLE as _TREE_KEY_ROLE
from origenerator.gui.folder_tree import offer_collapse_and_expand
from origenerator.gui.gallery_navigation import NavigationController
from origenerator.gui.gallery_search import GallerySearchController
from origenerator.gui.gallery_tree import (
    GROUP_ROLE as _GROUP_ROLE,
)
from origenerator.gui.gallery_tree import (
    GalleryTree,
    PathStep,
    SideModel,
    path_text,
)
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.generation_failed import GenerationFailed
from origenerator.gui.how_many import HOW_MANY
from origenerator.gui.inflight import (
    CANCEL_ALL_TEXT,
    CANCEL_TEXT,
    cancel_all_question,
    cancel_tooltip,
    clear_queue_tooltip,
    jobs_to_cancel,
    queue_wait_text,
    stop_auto_generate_text,
    stop_auto_generate_tooltip,
)
from origenerator.gui.info_pane_tabs import InfoPaneTabs
from origenerator.gui.job_queue import JobQueue
from origenerator.gui.job_queue_view import JobQueueView
from origenerator.gui.look_training_controller import LookTrainingController
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.motion_panel import MotionPanel
from origenerator.gui.moving_previews import MovingPreviews
from origenerator.gui.new_tile import NewTile
from origenerator.gui.notice_overlay import ERROR, HEARD_MARK, NOTICE
from origenerator.gui.off_thread import run_off_thread
from origenerator.gui.osr2_control import Osr2Control
from origenerator.gui.pane_arrangement import PaneArrangement
from origenerator.gui.panes import FootSplitter, PaneSplitter, hold_the_borders_still, pane
from origenerator.gui.prompt_reveal import reveal_prompt
from origenerator.gui.search_expander import SearchExpander
from origenerator.gui.slideshow_director import SlideshowDirector
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.gui.starting_rows import StartingRows
from origenerator.gui.toolbar_bank import (
    AUTO_ELSEWHERE_TIP,
    BankActs,
    BankState,
    Button,
    ToolbarBank,
)
from origenerator.gui.voice_router import VoiceRouter
from origenerator.item_names import ItemNames
from origenerator.media import MediaType
from origenerator.orientation import (
    base_of as _base_of,
)
from origenerator.orientation import (
    filter_rows,
    oriented_key,
    requested_orientation,
    row_orientation,
)
from origenerator.orientation import (
    side_of as _side_of,
)
from origenerator.orientation import (
    split_key as _split_collection_key,
)
from origenerator.osr2_driver import Osr2Driver
from origenerator.osr2_motion_driver import Osr2MotionDriver
from origenerator.prompt_tokens import boxed_as_typed
from origenerator.radio import OrigeneratorRadio
from origenerator.trash import Trash
from origenerator.voice.app_commands import AppCommand
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.derived_size import resolve_input_image_path

logger = logging.getLogger(__name__)


_POLL_INTERVAL_MS = 1500
_TEXT_FIELDS = (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)
_PATH_MARK_OF = {_FAVORITES_KEY: "star", _ENHANCED_KEY: "plus"}
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


class _SearchScope(NamedTuple):
    """What a search covers: the selected row's breadcrumb and the generations it
    holds (``None`` for no restriction at all).

    The path rather than the folder's own name, everywhere it is said: a folder
    is named by a short code, so "Search 3A7F2C10…" names nothing the user can
    place, where the path they clicked down does.
    """

    steps: tuple[PathStep, ...]
    ids: set[str] | None

    @property
    def path(self) -> str:
        return path_text(self.steps)


def _kept_on_removal(custom) -> str:
    folders, items = len(gallery.child_groups(custom)), len(custom.rows)
    if not items:
        return f"The {folders} folder{'s' if folders != 1 else ''} it holds, and their items, are kept."
    held = f"{items} item{'s' if items != 1 else ''}"
    if folders:
        held = f"{folders} folder{'s' if folders != 1 else ''} and {held}"
    return f"The {held} it holds are kept."


def _offer_taking_out(menu: QMenu, open_custom, group):
    if open_custom and any(m.key == group.key for m in gallery.child_groups(open_custom)):
        return menu.addAction(f"Remove from “{open_custom.label}”")
    return None


def _row_under(row, folder_key: str):
    if row is None or _side_of(folder_key) is not None:
        return None
    return next((child for child in (row.child(i) for i in range(row.childCount()))
                 if _base_of(child.data(0, _TREE_KEY_ROLE)) == folder_key), None)


def _folder_of_your_own_above(rows):
    parent = rows[0].parent()
    return _saved_custom_folder(parent.data(0, _GROUP_ROLE)) if parent is not None else None


def _saved_custom_folder(group):
    return group if isinstance(group, gallery.CustomGroup) and group.folder_id is not None else None


def _takes_a_favorite(group) -> bool:
    return group is not None and not isinstance(group, gallery.CustomGroup)


def _offer_copy_names_above_a_line(menu: QMenu, names: list[str]) -> None:
    offer_copy_names(menu, names)
    if not menu.isEmpty():
        menu.addSeparator()


def _names_of_the_picked_folders(selection_group) -> list[str]:
    return [group.label for group in gallery.child_groups(selection_group)]


def _is_one_of_the_picked(selection_group, group) -> bool:
    return (selection_group is not None and group is not None
            and any(m.key == group.key for m in gallery.child_groups(selection_group)))


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
    # A run ended, as one :class:`~origenerator.run_notice.RunOutcome`. The view
    # has nowhere left to draw that news — the run's tile went with it — so it
    # passes it out to the window, which owns the tray icon Windows' own
    # notifications come from (:mod:`origenerator.gui.desktop_notices`).
    run_ended = pyqtSignal(object)

    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryActions | None = None,
                 osr2_motion: Osr2MotionDriver | None = None,
                 radio: OrigeneratorRadio | None = None,
                 search_expander: SearchExpander | None = None,
                 fun_time: FunTimeSession | None = None,
                 prompt_heights=None):
        super().__init__(parent)
        self._db = db
        # The window's prompt heights, handed down to every form opened here
        # rather than reached for by each field (see gui.prompt_field).
        self._prompt_heights = prompt_heights
        self._client = client
        # The Fun Time session hosting this app, or None standalone.  Inside one
        # the layout goes vertical, the fullscreen surfaces land on the satellite
        # regions, and the OSR2 is Fun Time's alone (see origenerator.fun_time_mode).
        self._fun_time = fun_time
        # Origenerator Radio, under the toolbar's switch of that name: several
        # library videos at once, sound only. Injectable so tests never open a
        # real engine. Built before _build_ui, whose switch drives it.
        self._radio = radio if radio is not None else OrigeneratorRadio()
        omnipause.holds(self._radio)
        # The one app-global motion driver (genau's engine, no funscript needed):
        # every surface — this window and whatever slideshow is up —
        # drives it through the shared motion keys, and while it holds the device
        # the funscript reconcile stands down. Injectable so tests never touch
        # the broker. Built before _build_ui, which wires its window feedback.
        # None inside a Fun Time session: the OSR2 there is the Main Funestra's
        # alone, so no surface of this app may reach the device.
        if fun_time is not None:
            self._osr2_motion = None
        else:
            self._osr2_motion = osr2_motion if osr2_motion is not None else Osr2MotionDriver(parent=self)
            omnipause.holds(self._osr2_motion)
        # The app's one OSR2 switch, and now its only one: the Funestras' console
        # carries the control-state group that sets it, on every surface.  Public
        # because a slideshow is handed it whole -- see SlideshowActions.
        self.osr2_control = Osr2Control(self._osr2_motion, parent=self)
        # What the session file said to reopen in, kept for a window that may
        # not drive to hand back untouched (see osr2_state).
        self._osr2_left_in = None
        # Every move of the group re-aims the device, not only a flip of the
        # switch: driving to parked leaves the switch on, and what has to change
        # is which driver is sending and what it is sending.
        self.osr2_control.changed.connect(self.reconcile_osr2)
        # Standalone's Clip seconds, which each Satellite's starts at in a session.
        self._pace = SlideshowPace(parent=self)
        # Guards the one reconcile that owns both drive sources: starting or
        # stopping the motion is something it does, not something it reacts to.
        self._reconciling_osr2 = False
        self._build_the_queue_of_runs(db, client)
        self._actions = actions or GalleryActions(
            db, OUTPUT_PLACES, Trash(TRASH_DIR),
            environment=GalleryEnvironment(
                release_files=self._release_held_media, thumb_dir=THUMB_DIR,
                cancel_enhancements=lambda rows: self._enhance.cancel_for_delete(rows),
            ),
        )
        self._moving_previews = MovingPreviews(self._actions.places,
                                               self._actions.thumb_dir, parent=self)
        self._moving_previews.made.connect(
            lambda prompt_id, path: play_once_made(self._browser, prompt_id, path))
        self._forget_the_listing()
        self._build_the_panes(db, client, search_expander)
        # What another app has on the shared ComfyUI, re-read on every poll so the
        # lower bar can say the server is busy before a Generate goes in after it.
        self._foreign_queue = ForeignQueue(running=[], pending=[])
        self._build_ui()
        self._voice.bind_the_bank(
            auto=self._bank.auto, radio=self._bank.radio,
            drive=self.osr2_control if self._osr2_motion is not None else None,
            mic=self._bank.mic,
            enhance=(self._bank.enhance, self._enhance.enhance_the_selection),
            actions={
                AppCommand.BACK: (self._bank.back, self._navigation.go_back),
                AppCommand.FORWARD: (self._bank.forward, self._navigation.go_forward),
                AppCommand.CULL: (self._bank.delete, self._delete_selection),
                AppCommand.FAVORITE: (self._bank.favorite, self._favorite_selection),
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
        """The Job Queue: the controller that owns the live jobs,
        Auto-Generate, which keeps one folder generating, and what each of those
        has to remember between launches.
        """
        # The re-roll controller owns the live jobs and their DB lifecycle; the
        # view reacts to its signals with the redraws they call for.
        self._jobs = JobQueue(db, client)
        self._jobs.changed.connect(self._rerender_current_leaf)
        self._jobs.changed.connect(self._reconcile_generating)
        self._jobs.changed.connect(lambda: self._enhance.reconcile())
        self._jobs.preview.connect(self._on_reroll_preview)
        self._jobs.finished.connect(self._on_reroll_finished)
        self._jobs.failed.connect(self._on_reroll_failed)
        self._jobs.run_ended.connect(self.run_ended)
        self._generation_failed = GenerationFailed(self)
        # Auto-Generate is that same re-roll, again and again: launch the next
        # variation each time one finishes, until stopped or one fails.
        self._auto = AutoGenerateController(self._start_auto_reroll)
        self._auto.stopped.connect(self._on_auto_stopped)
        # The workflow and settings each folder's Auto-Generate runs on, read
        # from the folder as it starts.
        self._auto_generate_settings: dict = {}
        # The runs Auto-Generate launched, by the id each began under. It is left
        # running while the user works, so what it makes is the gallery's, not any
        # tab's: no tab shows its frames or its result (see :meth:`_start_auto_reroll`).
        self._auto_origins: set[str] = set()
        # The folder whose running re-roll is the gallery's selected item (its
        # tile lit in the middle column), and that tile. Which tab shows the
        # run's frames full size is the tabs' own affair: a tab follows the
        # folder it launched into or was pointed at (see
        # :meth:`GenerateConfigPanel.watch_folder`), and the frames are routed
        # to it by folder key, never to "the tab in front".
        self._selected_reroll_key: str | None = None
        self._generating_tile: GeneratingTile | None = None

    def _forget_the_listing(self):
        """Empty every slot a rebuild fills in.

        Called once at construction and never again: a rebuild replaces what is
        here rather than clearing it first, so these are the values a gallery has
        before its first refresh.
        """
        self._image_rows: list[dict] = []
        # Images whose spoken animation is still choosing a video, so a
        # second one said into that wait is refused rather than queued twice
        # (:meth:`_already_genaud`). Only until the launch is a row.
        self._live_ids: set[str] = set()  # the gallery's own rows, minus the trash
        self._listed_rows: list[dict] = []
        self._listed_requests: list[dict] = []
        self._image_index: dict | None = None  # memo, dropped by every rebuild

    def _build_the_panes(self, db, client, search_expander):
        """The three panes' own objects, in the order they need each other: the
        search over the tree, the browser in the middle, the trail across both,
        then the slideshows, the combine, the enhance and the spoken words that all
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
        # The trashed items the Trash collection lists, as gallery rows re-pointed at
        # their files in the trash — the rows under everything a deleted item can
        # still do (see :meth:`row_for`).
        self._held_rows: list[dict] = []
        self._selected_row: dict | None = None  # the saved generation on display in the info pane
        self._item_names = ItemNames(db)
        # The browser pane renders the middle column (tiles / thumbnails / collections)
        # and owns the thumbnail multi-selection and in-flight tiles. Its signals
        # carry every gesture made on a tile; the handlers here answer them. The
        # scroll area is its canvas — built here so it can be handed over, placed
        # into the layout by _build_ui.
        self._scroll = BrowserScrollArea()
        DropTarget(self._scroll, self._landing_in_the_open_custom_folder, self._on_dropped)
        self._browser = BrowserPane(
            self._scroll, db, self._jobs, self._auto,
            TreeNavigation(
                selected_folder_key=self.selected_folder_key,
                folder_context=self._folder_context,
                group_for_key=self.group_for_key,
            ),
            # Each answer looks itself up through self at call time, as the
            # pane's old view reads did — so a per-instance stub (tests fake
            # animated_preview this way) still lands.
            PaneHost(
                image_rows=lambda: self._image_rows,
                animated_preview=lambda row: self.animated_preview(row),
                enhancing_run=lambda row: self._enhance.run_of(row),
                enhance_settings=lambda: self._enhance.settings,
                experiments_enabled=lambda: self.experiments_enabled(),
                lead_tiles=lambda group: self._lead_tiles(group),
                item_name=self._item_names.of,
            ),
        )
        self._browser.pane_reset.connect(self._forget_generating_tile)
        self._browser.thumbnail_activated.connect(self._on_thumbnail_clicked)
        self._browser.tab_pin_requested.connect(self.pin_config_tab)
        self._browser.item_jump_requested.connect(self.follow_link)
        self._browser.folder_open_requested.connect(self._go_to_folder)
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
        self._fingerprint = (None, None)
        self._folder_meta: dict = {}
        self._drawn_version = 0
        self._pending_key: str | None = None  # a folder to open once the tree exists
        self._pending_selection: str | None = None  # a generation to highlight once shown
        # A combine's brand-new folder doesn't exist until its job finishes; hold
        # its key so _on_reroll_finished can drill in once the tree has the folder.
        self._pending_combine_key: str | None = None
        # The user's own folders, resolved against the live tree on each rebuild,
        # and the throwaway one a multi-selection stands up (None with 0 or 1 row
        # picked). Both are CustomGroups, so the pane, breadcrumb, and slideshow
        # treat them exactly as they treat a derived folder.
        self._custom_folders: list = []
        self._custom_folders_by_side: dict[str, list] = {}
        self._lists_built_from = None
        self._lists_by_side: dict[str, list] = {}
        self._start_frames: dict = {}
        self._selection_group = None
        self._navigation = NavigationController(self, search=self._search)
        # What the trail allows right now, as it last told us: the bank is written
        # from one state, so Back and Forward read it there rather than being set
        # on their own (see :meth:`nav_state_changed`).
        self._trail = (False, False)
        # The fullscreen slideshows: the one in front, the two a hosting session
        # runs on its satellite regions, and everything that keeps them
        # current. Built after the browser it reads and before _build_ui,
        # whose slideshow button starts one.
        self._slideshows = SlideshowDirector(
            self, db=db, browser=self._browser, jobs=self._jobs,
            pace=self._pace, motion=self._osr2_motion, fun_time=self._fun_time,
            names=self._item_names, radio=self._radio,
            turn_the_radio_on=lambda: self._bank.turn_the_radio_on())
        self._starting = StartingRows(self)
        self._starting.changed.connect(self._update_queue)
        # Combine: a video's settings run again on a dropped image, and the
        # spoken "animate as" that asks for the same thing out loud
        # (:mod:`origenerator.gui.combine_controller`). It builds its own panel,
        # which _build_ui places under the tree.
        self._combine = CombineController(
            self, parent=self, db=db, jobs=self._jobs, client=client,
            info_tabs_of=lambda: self._info_tabs, slideshows=self._slideshows,
            starting=self._starting, names=self._item_names)
        # The standalone enhance: its settings panel, what the Enhance button
        # would run on, and the live run's appearance on every surface showing
        # the image it improves
        # (:mod:`origenerator.gui.enhance_controller`). It builds its own panel,
        # which _build_ui seats in the footer.
        self._enhance = EnhanceController(
            self, db=db, jobs=self._jobs, browser=self._browser,
            slideshows=self._slideshows, info_tabs_of=lambda: self._info_tabs)
        self._jobs.enhance_images_with(
            lambda image: self._enhance.enhance_items([image["prompt_id"]]))
        self._look_training = LookTrainingController(
            self._jobs, panels=lambda: self._info_tabs.config_panels(),
            show_panel=lambda panel: self._info_tabs.setCurrentWidget(panel), parent=self)
        # Everything spoken: the microphone, the caption that says what it heard,
        # and where each word lands (:mod:`origenerator.gui.voice_router`). Its
        # caption is placed by _build_ui, and the bank it presses is bound to it
        # once _build_ui has built one.
        self._voice = VoiceRouter(self, parent=self, db=db, slideshows=self._slideshows,
                                  client=client, motion=self._osr2_motion,
                                  starting=self._starting)
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
            if event.key() == Qt.Key.Key_Escape and self._handle_escape():
                return True
            if (event.key() == Qt.Key.Key_Escape and self._find_bar.isVisible()
                    and not self._other_window_owns_keys()):
                self._find_bar.close_find()
                return True
            # Ctrl+F opens the find from wherever focus happens to be — including
            # the prompt field it will search, which the gallery otherwise hands
            # its keys to. Searching is what the chord means everywhere else and
            # nothing in this window competes for it, so it is answered before
            # that yielding happens.
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
                if (event.key() == Qt.Key.Key_C
                        and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self._copy_names_of_the_selection()
                    return True
                if (event.key() == Qt.Key.Key_Z
                        and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    # Ctrl+Shift+Z is the other direction, as everywhere else.
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        self._redo()
                    else:
                        self._undo()
                    return True
            # The OSR2 motion keys work right here in Core too — not
            # only in the fullscreen slideshow — whatever was clicked last, unless it
            # is a text field taking the key as a character.
            if (self._gallery_owns_keys(even_from_the_info_pane=True)
                    and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
                    and apply_motion_key(self._osr2_motion, event.key(),
                                         on_drive_toggle=self.toggle_osr2_drive)):
                self._motion_panel.refresh()
                return True
        # Not the base class's answer, which is this one anyway: this filter is
        # on the whole application, so it is handed events about objects that
        # are being destroyed, and handing one of those back to C++ dereferences
        # a freed pointer and aborts the process.
        return False

    def _handle_escape(self) -> bool:
        if self._other_window_owns_keys():
            return False
        if self._escape_cancels_something():
            return False
        self._slideshows.pause_or_play_the_room()
        return True

    def _escape_cancels_something(self) -> bool:
        if self._find_bar.isVisible():
            return True
        return isinstance(QApplication.focusWidget(), _TEXT_FIELDS)

    def _other_window_owns_keys(self) -> bool:
        """True when a keystroke belongs to something other than the gallery: an open
        modal dialog or popup, or a separate top-level window that's active, such
        as a slideshow. The gallery's filter is installed on the application, so it
        sees those windows' keys first and has to hand them back."""
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return True
        active = QApplication.activeWindow()
        return active is not None and active is not self.window()

    def _gallery_owns_keys(self, *, even_from_the_info_pane: bool = False) -> bool:
        """True when a gallery key should act rather than pass through: the view
        is on screen, nothing else owns the keystroke (no dialog/popup and no other
        active window), and the focus isn't in a text field typing it. Delete and
        Undo also yield to the info-pane config tabs, so editing a form cannot wipe
        a thumbnail; the device's keys are asked for even from there."""
        if not self.isVisible() or self._other_window_owns_keys():
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, _TEXT_FIELDS):
            return False
        return even_from_the_info_pane or not (
            focus is not None and self._info_tabs.isAncestorOf(focus))

    def _build_ui(self):
        """Put the three panes on screen, in the order their contents need.

        Each pane builds itself and hands back the widget it built; the
        arrangement they are handed to is the one place the hosted and
        standalone shapes differ. Sequence rather than grouping is what this
        preserves -- the motion, the sound and the device driver must exist
        before the widgets that wire them, and each pane's own comments say which.
        """
        layout = QVBoxLayout(self)
        toc = self._build_toc_pane()
        browser = self._build_browser_pane()
        # The Job Queue under those two lists every generation in flight — the app hands
        # ComfyUI one at a time, so a batch of Generates is a queue — reachable
        # from any folder or config tab. Fed on every rebuild and poll; a row
        # dragged to a new place asks the controller to re-line the queue. Its top
        # edge is this column's splitter handle, so a long queue can be dragged
        # open at the cost of the folder listing above it.
        self._queue = JobQueueView()
        self._queue.move_requested.connect(self._jobs.move)
        self._jobs.reordered.connect(self._update_queue)
        self._queue.clear_queue_requested.connect(self.clear_foreign_queue)
        self._queue.start_now_requested.connect(self.start_now)
        self._queue.cancel_all_requested.connect(self.cancel_all)
        self._arrangement = PaneArrangement(
            toc=toc, browser=browser, info_pane=self._build_info_pane(),
            info_tabs=self._info_tabs, queue=self._queue)
        folded = self._fun_time is not None and not self._fun_time.in_a_headset
        layout.addWidget(self._arrangement.hosted() if folded
                         else self._arrangement.standalone(), 1)
        hold_the_borders_still(self, self._fun_time is not None)

    def _build_toc_pane(self):
        """The left pane's sections: the OSR2 HUD of a window that drives the
        device, what voice heard, the search field over the folder list, and the
        combine panel."""
        # The folder list: media -> workflow -> model -> LoRA -> [source image]
        # -> settings, the LoRA level collapsing to one "(no LoRA)" folder for a
        # LoRA-less workflow and the source-image level showing only for an
        # image-conditioned one.
        # One tree per side, each under a standing label and each scrolling on
        # its own: the tree of contents exists once per side, and which one you
        # are in is what decides the screen a slideshow goes to.
        self._tree = SplitFolderTree(_GROUP_ROLE, takes_item=self._custom_folder_takes,
                                     takes_folder=self._collecting_row_takes_folder)
        self._tree.offer_separate_and_together(self._fun_time is None)
        self._tree.sides_changed.connect(self._on_sides_changed)
        self._tree_view = GalleryTree(self._tree)  # fills it + the key/prompt→item maps
        self._tree.context_menu_requested.connect(self._on_tree_context_menu)
        self._tree.currentItemChanged.connect(self._on_folder_selected)
        # Picking several folders (Shift/Ctrl) shows them together, as the folder
        # they would make; this fires after currentItemChanged, so it has the last
        # word on what the panes show.
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self._tree.favorite_clicked.connect(self._toggle_favorite)          # hover-row action
        self._tree.delete_clicked.connect(self._delete_folder_by_key)
        self._tree.dropped.connect(self._on_dropped)
        # What voice heard, the search field over the folder list, and the
        # combine panel: three sections under handles of their own, the same
        # handle the folder list's own sections are parted by — so the sections
        # outside the list read as sections too rather than as loose rows above
        # and below it.
        listening, listening_column = pane()
        # Voice's caption sits above everything else in this pane — the top-left
        # corner of the view, where it obscures no control while it's up. Its
        # section comes and goes with it, rather than standing empty while the
        # mic is shut.
        listening_column.addWidget(self._voice.status)
        if self._voice.status.isHidden():
            listening.hide()
        self._voice.caption_shown.connect(listening.setVisible)
        finding, toc_column = pane()
        # The gallery search: its field over the tree, its results bar over the
        # browser pane below (:mod:`origenerator.gui.gallery_search`).
        toc_column.addWidget(self._search.field)
        toc_column.addWidget(self._tree, 1)  # the trees take this section's height
        combining, combining_column = pane()
        combining_column.addWidget(self._combine.panel)
        # With no ComfyUI there is nothing to combine, and the panel says so by
        # hiding; its section says the same rather than framing the gap.
        if self._combine.panel.isHidden():
            combining.hide()
        sections = [listening, finding, combining]
        self._motion_panel = None
        self._motion_pane = None
        if self._osr2_motion is not None:
            self._motion_panel = MotionPanel(self._osr2_motion, control=self.osr2_control)
            self._motion_panel.setToolTip(f"{self._motion_panel.toolTip()} · Esc pauses")
            hud_scroll = QScrollArea()
            hud_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            hud_scroll.setWidget(self._motion_panel)
            self._motion_pane, hud_column = pane()
            hud_column.addWidget(hud_scroll)
            sections.insert(0, self._motion_pane)
        toc = PaneSplitter(Qt.Orientation.Vertical, "left_pane_sections")
        for section in sections:
            toc.addWidget(section)
        toc.setStretchFactor(sections.index(finding), 1)  # the folder list takes the height
        return toc

    def _build_browser_pane(self):
        """The middle pane: the folder's path, the button bank under it, the
        collection's own bars, and the flowing contents -- with the Enhance settings
        standing at its foot, under a handle of their own.
        """
        browser, browser_column = pane()
        self._folder_path = FolderPathHeader()
        self._folder_path.folder_chosen.connect(self._go_to_folder)
        browser_column.addWidget(self._folder_path)
        # The button bank over this pane (:mod:`origenerator.gui.toolbar_bank`).
        # It builds and lays out every button and is written from one state; what
        # each button depends on is gathered in :meth:`bank_state`.
        self._bank = ToolbarBank(
            BankActs(
                go_back=self._navigation.go_back,
                go_forward=self._navigation.go_forward,
                undo=self._undo,
                redo=self._redo,
                start_slideshow=self._slideshows.start,
                toggle_auto=self._toggle_auto,
                go_to_auto_generating_folder=self._go_to_auto_generating_folder,
                favorite=self._favorite_selection,
                enhance=self._enhance.enhance_the_selection,
                group=self._group_selection,
                delete=self._delete_selection,
                toggle_radio=self._on_radio_toggle,
                toggle_mic=self._voice.mic_toggled,
            ),
            hosted=self._fun_time is not None,
        )
        browser_column.addWidget(self._bank)
        # The Experiments collection's controls: the background experimenter's on/off
        # switch and a one-line status. Rides under the header, and appears only
        # while that collection is open.
        self._experiments_cb = TickControl("Run experiments while the app is closed")
        self._experiments_cb.toggled.connect(self._on_experiments_toggled)
        # Scheduling an absence is the production app's alone, so a branch session
        # can't reach the switch.
        self._experiments_cb.setEnabled(not is_branch_session())
        self._experiments_status = QLabel("")
        self._experiments_status.setObjectName("estimateLabel")
        self._experiments_bar = QWidget()
        experiments_row = QHBoxLayout(self._experiments_bar)
        experiments_row.setContentsMargins(0, 0, 0, 0)
        experiments_row.addWidget(self._experiments_cb)
        experiments_row.addWidget(self._experiments_status)
        experiments_row.addStretch(1)
        self._experiments_bar.hide()  # shown only in the Experiments collection
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
        # to aiming Favorite / Enhance / Delete at the whole folder once a tile has
        # been picked.
        self._scroll.background_clicked.connect(
            self._browser.clear_thumbnail_selection)
        browser_column.addWidget(self._scroll, 1)
        # The foot of the center (browser) pane, under a handle of its own: what
        # an enhancement runs at — the Enhance All button, a single image's
        # Enhance, and (with its tick on) each image the app newly generates.
        # App-wide and always here: enhancement is whatever you are doing at the
        # moment, not a property of the folder you happen to be standing in, so
        # it shows in the collections as readily as on a settings folder. Deliberately
        # not on the Generate form: every setting there picks the folder a run
        # lands in, and this one doesn't.
        enhance, enhance_column = pane()
        enhance_column.addWidget(self._enhance.panel)
        browsing = FootSplitter("browser_and_enhance")
        browsing.addWidget(browser)
        browsing.addWidget(enhance)
        browsing.setStretchFactor(0, 1)
        browsing.setStretchFactor(1, 0)
        return browsing

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
        self._info_tabs = InfoPaneTabs(self._client, self._db, fun_time=self._fun_time,
                                       heights=self._prompt_heights, names=self._item_names,
                                       previews=self._moving_previews)
        # One OSR2 driver for the whole view, under the one global switch
        # (self.osr2_control): while that's on it follows whichever video is foreground —
        # an open slideshow, else whatever scripted video is in the front tab —
        # and with it off nothing drives on either surface.
        # Switching tabs/videos or opening/closing a slideshow re-aims it; with
        # nothing to drive it stops. self._osr2_driving is the (video, player) currently
        # driven, so a redundant reconcile doesn't churn the device. Built before the
        # panels are wired, since wiring connects their displayed_changed here.
        # None where this app may not touch the device at all (hosted by Fun
        # Time, whose Main Funestra owns the OSR2).
        self._osr2_driver = Osr2Driver(parent=self) if self._osr2_motion is not None else None
        if self._osr2_driver is not None:
            omnipause.holds(self._osr2_driver)
        # The switch answers "what is the OSR2 doing" for every console over it,
        # so it holds both drivers rather than only the motion.
        self.osr2_control.script = self._osr2_driver
        self._osr2_driving = None
        self._find_bar = FindBar("Find in prompts:", "a word you wrote…",
                                 dismiss_key="Esc", reveal=reveal_prompt)
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
            # The radio's stations let their engines go before the process does.
            app.aboutToQuit.connect(self._radio.stop)
        # A tab's Generate is a re-roll of its settings folder: launch it in that
        # folder and navigate there, its generating tile and all.
        self._info_tabs.generate_requested.connect(self._on_generate_requested)
        self._info_tabs.modify_requested.connect(self._on_modify_requested)
        # ...and its right-click's "Go to folder" goes the other way: from a
        # tab's settings across to the items they have made.
        self._info_tabs.folder_requested.connect(self._go_to_folder)
        info_pane = QWidget()
        info_column = QVBoxLayout(info_pane)
        info_column.setContentsMargins(0, 0, 0, 0)
        info_column.addWidget(self._info_tabs, 1)
        info_column.addWidget(self._find_bar)
        return info_pane

    def become_hosted(self, session) -> None:
        for switch in (self._bank.radio, self._bank.mic):
            if switch is not None:
                switch.setChecked(False)
        self.osr2_control.drive_with(None, None)
        if self._osr2_motion is not None:
            self._osr2_motion.stop()
        self._fun_time = session
        self._tree.offer_separate_and_together(False)
        self._slideshows.become_hosted(session)
        self._info_tabs.become_hosted(session)
        self._voice.become_hosted()
        self._bank.become_hosted()
        if self._motion_pane is not None:
            self._motion_pane.hide()
        self._kept_device = (self._osr2_motion, self._osr2_driver, self._motion_panel)
        self._osr2_motion = self._osr2_driver = self._motion_panel = None
        self.wear_the_room(session)

    def wear_the_room(self, session) -> None:
        """The panes in the shape this room leaves them: the upright fold for
        the rect a session on the monitors names, side by side anywhere else."""
        folded = self._arrangement.stack is not None
        wants_the_fold = session is not None and not session.in_a_headset
        if wants_the_fold and not folded:
            self._arrangement.fold_into_the_session_column(self.layout())
        elif folded and not wants_the_fold:
            self._arrangement.unfold_from_the_session_column(self.layout())
        hold_the_borders_still(self, session is not None)

    def become_standalone(self) -> None:
        self.set_room_paused(False)
        self._osr2_motion, self._osr2_driver, self._motion_panel = self._kept_device
        self.osr2_control.drive_with(self._osr2_motion, self._osr2_driver)
        if self._motion_pane is not None:
            self._motion_pane.show()
        self._fun_time = None
        self._tree.offer_separate_and_together(True)
        self._slideshows.become_standalone(self._osr2_motion)
        self._info_tabs.become_standalone()
        self._bank.become_standalone()
        self._voice.become_standalone(
            self._osr2_motion, radio=self._bank.radio,
            drive=self.osr2_control if self._osr2_motion is not None else None,
            mic=self._bank.mic)
        self.wear_the_room(None)

    def _wire_config_panel(self, panel):
        """Route a config tab's footer links to the gallery: its "from source
        image" link and an animation-tile click both navigate like any source link,
        and its preview's corner buttons and right-click menu act on the shown
        generation exactly as a browser thumbnail's do.
        Its ``displayed_changed`` re-aims the global OSR2 drive at the front video
        and re-reads whether the tab still owns a run in flight, a double-click on
        its preview opens the folder under it as a slideshow standing on it,
        and its Cancel stops the re-roll running in the tab's folder. Called for the
        initial tab and every tab forked afterward."""
        panel.link_clicked.connect(self.follow_link)
        panel.go_to_folder_requested.connect(self.follow_link)
        panel.set_folder_check(self._can_open_containing_folder)
        panel.set_making_one_check(
            lambda config: self._config_folder_key(config) in self._live_jobs)
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
        panel.set_fullscreen_factory(self._slideshows.open_on_preview)
        panel.cancel_requested.connect(lambda p=panel: self._cancel_panel_reroll(p))
        panel.prompt_fields_changed.connect(self._retarget_find)
        # Every keystroke in a tab's form moves the text an open find is marking
        # up — re-run rather than leave highlights on words that shifted.
        panel.form_edited.connect(self._find_bar.refresh)
        self._look_training.wire(panel)

    # --- Drive OSR2: one switch, the app picking funscript or motion ----------

    def toggle_osr2_drive(self):
        """Flip the one switch — what Space does, from any surface. The motion's
        own toggle is deliberately not reachable from a key any more: with two
        sources for one device, whichever one a key started would have been
        streaming alongside whatever the switch already had going.

        A no-op with no switch to flip: hosted by Fun Time the device belongs
        to the session's Main Funestra, so nothing here may start it."""
        self.osr2_control.setChecked(not self.osr2_control.isChecked())

    def reconcile_osr2(self):
        """Put the right thing on the device, or nothing.

        With the app off the device, neither source drives. Parked, the motion
        is what drives — stilled at home, which is how the device gets there and
        stays — and the funscript stands down however scripted the video in
        front is, or it would drive straight through the park.
        Otherwise the surface in front picks: a funscript when what it has on
        screen carries one, and the self-generated motion every other moment,
        which is most of them — a folder of images, a video with no script, an
        empty tab.

        Idempotent, so tab switches, browsing, completions and opening or closing
        a slideshow all resolve without churning the device. The guard makes it
        re-entrant-safe too: starting or stopping the motion emits
        ``active_changed``, and a listener that reconciles must not land back
        here mid-flight.
        """
        if self._osr2_driver is None:
            return  # hosted by Fun Time — the device is the Main Funestra's
        if self._reconciling_osr2:
            return
        self._reconciling_osr2 = True
        try:
            held = self._osr2_motion.held is not None
            in_front = self._surface_in_front()
            target = (in_front.osr2_drive_target()
                      if in_front is not None and self.osr2_control.engaged() and not held
                      else None)
            wants_motion = self.osr2_control.engaged() and target is None
            # Whoever gives the device up goes first: each driver puts back what
            # it found on taking over, and must not find the other still there.
            if not wants_motion and self._osr2_motion.active:
                self._osr2_motion.stop()
            if target is None:
                if self._osr2_driving is not None:
                    self._osr2_driver.stop()
                    self._osr2_driving = None
            else:
                video_path, player, actions = target
                # Same video, new player (a slideshow opened over it) still re-aims.
                driving = (video_path, player)
                if self._osr2_driving != driving:
                    self._osr2_driver.start(player, actions)
                    self._osr2_driving = driving
            if wants_motion and not self._osr2_motion.active:
                self._osr2_motion.start()
            # Said inside the guard, so a console redrawing on it cannot land
            # back in here mid-flight.
            self.osr2_control.settled.emit()
        finally:
            self._reconciling_osr2 = False

    def video_in_front(self) -> str | None:
        surface = self._surface_in_front()
        return surface.video_on_screen() if surface is not None else None

    def _surface_in_front(self):
        """A slideshow while one is up, else the front tab."""
        slideshow = self._slideshows.surface_for(None)
        if slideshow is not None:
            return slideshow
        return self._info_tabs.current_config_panel()

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

    def osr2_state(self):
        """Whether to reopen with the switch on or off.  A window that may not
        drive (hosted by Fun Time) hands back what it was opened with instead:
        the standalone app keeps the same state file, and a hosted run would
        otherwise leave it saying parked."""
        if not self.osr2_control.isEnabled():
            return self._osr2_left_in
        return self.osr2_control.state()

    def restore_osr2_state(self, saved):
        """Put the control state a saved session was left in back on."""
        self._osr2_left_in = saved
        self.osr2_control.restore(saved)

    def max_intensity(self) -> int:
        return self.osr2_control.max_intensity

    def set_max_intensity(self, saved) -> None:
        if isinstance(saved, int):
            self.osr2_control.set_max_intensity(saved)

    def motion_settings(self) -> dict | None:
        return None if self._osr2_motion is None else self._osr2_motion.settings()

    def set_motion_settings(self, saved) -> None:
        if self._osr2_motion is not None:
            self._osr2_motion.take_settings(saved)

    # --- Origenerator Radio: one app-global switch, following nothing on screen --

    def _on_radio_toggle(self, on: bool):
        """Tune Origenerator Radio in, or silence it. Unlike the OSR2's switch it
        has nothing to re-aim: it plays under whatever the user is doing, so the
        toggle is the whole of it."""
        if on:
            self._radio.start()
        else:
            self._radio.stop()

    def radio_enabled(self) -> bool:
        """Whether Origenerator Radio's switch is on (for session persistence)."""
        return self._bank.radio is not None and self._bank.radio.isChecked()

    def set_radio_enabled(self, enabled):
        """Restore Origenerator Radio's switch from a saved session.  With no
        switch (hosted by Fun Time, where each Satellite Funestra plays its own
        stations) a stale saved value has nothing to restore."""
        if self._bank.radio is not None:
            self._bank.radio.setChecked(bool(enabled))  # drives _on_radio_toggle → start

    # --- the microphone -------------------------------------------------------

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
        something, so off is a state to be chosen, not one to be arrived at.
        """
        if self._bank.mic is not None:  # hosted, the session owns the microphone
            self._bank.mic.setChecked(True if enabled is None else bool(enabled))

    # --- background experiments: the closing batch and the collection's controls ---

    def experiments_enabled(self) -> bool:
        """Whether the background experimenter is on (for session persistence)."""
        return self._experiments_cb.isChecked()

    def set_experiments_enabled(self, enabled):
        """Restore the background experimenter's switch from a saved session —
        off in a branch session whatever was saved, since a branch session's
        state is seeded from the production app's, switch position included."""
        self._experiments_cb.setChecked(bool(enabled) and not is_branch_session())

    def flush_queue_to_server(self) -> int:
        """Hand ComfyUI everything the queue is still holding, as the app closes.

        The queue hands ComfyUI one prompt at a time so the line stays
        re-orderable for whoever is watching, and closing the app ends that
        reason. ComfyUI outlives it and works through the rest alone; the next
        launch picks up whatever finished. Returns how many jobs went.
        """
        return self._jobs.flush_to_server()

    def _on_experiments_toggled(self, _checked: bool):
        self._sync_experiments_bar()

    def _review_queue(self, rows) -> list[dict]:
        """The experiments waiting on the user's verdict — the Experiments collection."""
        return gallery.unreviewed_experiments(rows)

    def _sync_experiments_bar(self):
        """Say what the switch's current position means, under the switch."""
        if is_branch_session():
            self._experiments_status.setText(
                "Off — a branch preview never queues experiments; "
                "that's the production app's")
            return
        self._experiments_status.setText(
            "On — variations run after you close the app and land here for review"
            if self.experiments_enabled() else "Off — the GPU stays all yours"
        )

    def _on_experiment_verdict(self, prompt_id: str, action_id: str):
        """A review from the Experiments collection: "keep" admits the result to the
        gallery proper; "reject" records the down-verdict the policy learns from
        and trashes the files (undoable). Either way the item leaves the collection."""
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
        return gallery.folder_key_for(workflow_name, params, self.image_config_index(),
                                      workflow_version)

    def folder_key_of(self, row: dict) -> str:
        """The settings-folder key a stored row lands in — the same derivation,
        for a caller holding the row rather than a config."""
        return gallery.settings_folder_key(row, self.image_config_index())

    def _config_folder_key(self, config) -> str:
        """The settings-folder key ``config`` would run in."""
        return self.folder_key_for(config.workflow_name, config.params)

    def _reconcile_generating(self):
        """Point every config tab's discard button at the run *it* launched, and
        have its Generate ask again whether its folder is making one.

        A tab follows the *oldest still alive* of its own runs — the one nearest to
        being made, and so the one its button discards — across a chained i2v's
        hand-off, which is two prompts but one run. Launches from outside a tab —
        the folder tile's "+", Auto-Generate — are claimed by the tab looking at
        that same folder (:meth:`_claim_launch`), so they light it up too.

        Idempotent — driven by every re-roll lifecycle change and by switching the
        front tab. Every tab is reconciled, not just the front one, so a run
        launched from a tab that is now under another still shows there.
        """
        for panel in self._info_tabs.config_panels():
            live = [(origin, job) for origin in panel.launched_runs()
                    if (job := self._jobs.job_for_origin(origin)) is not None]
            panel.forget_launched({origin for origin in panel.launched_runs()
                                   if origin not in {o for o, _ in live}})
            job = live[0][1] if live else None  # the oldest still alive: nearest done
            panel.set_generating(job is not None,
                                 auto_generating=self._auto_generating(job))
            panel.reread_generate_button()
        self._combine.reconcile_generating()

    def _auto_generating(self, job) -> bool:
        """Whether ``job``'s own folder is auto-generating — so the hover on the
        Cancel that throws the run away says Auto-Generate starts the next seed.
        Its folder, not the front tab's: the hover has to match what pressing it
        actually does."""
        key = self._job_folder_key(job)
        return key is not None and self._auto.is_active(key)

    def _job_folder_key(self, job) -> str | None:
        """The settings folder a live job runs in, or ``None`` for one no longer
        tracked. Read from the controller's grouping rather than recomputed from the
        job's params, so it is the key the job was actually filed under."""
        if job is None:
            return None
        return next((k for k, jobs in self._jobs.jobs_by_folder.items()
                     if job in jobs), None)

    def _claim_launch(self, key: str):
        """Give a run launched outside any tab — the folder tile's "+",
        Auto-Generate — to the front config tab when that tab is showing the same folder.

        Unclaimed, such a run belonged to no tab at all, so the tab looking
        straight at it showed neither the discard button nor a filling Generate
        while the pane beside it streamed the very frames it was making. Only a
        matching folder claims it, so a tab parked on other settings is untouched.

        A tab that claims one is kept, for the reason a tab that pressed its own
        Generate is: the run's Cancel and its filling bar are in it now, and a
        later click replacing the tab would take both away mid-run. Since opening
        a folder puts the pane's italic tab on that folder, the claimer usually is
        that tab.
        """
        panel = self._info_tabs.current_config_panel()
        job = self._jobs.newest_job_for(key)
        if panel is None or job is None or panel.workflow_and_signature() is None:
            return
        if self._config_folder_key(panel.current_config()) == key:
            panel.note_launched(job.origin)
            self._info_tabs.pin_tab(panel)
            self._reconcile_generating()  # the launch's own reconcile ran before this

    def _cancel_panel_reroll(self, panel):
        """Discard the run this tab's bar is showing — its Cancel button.

        The oldest of the tab's own still alive, so the press acts on the thing on
        screen rather than something queued after it.
        """
        for origin in panel.launched_runs():
            job = self._jobs.job_for_origin(origin)
            if job is not None:
                self._cancel_job(job.prompt_id)
                return

    def would_reproduce_a_completed_run(self, workflow, params: dict) -> bool:
        """True when launching ``workflow`` with ``params`` would re-create a
        byte-identical past generation — the cue to re-roll rather than waste a slot.

        The form sends the seed its field shows, so the seed is taken as pinned
        here; a freshly drawn seed would simply never match.
        """
        return would_reproduce_a_completed_run(
            self._db.list_generations(), workflow, params)

    def _on_generate_requested(self, workflow_name: str, batch: list[dict]):
        """A tab's Generate: launch each of ``batch`` as a re-roll of its settings
        folder and land the browser there, its live tile showing the run.

        Identical in outcome to clicking the folder's New tile: the jobs land in
        that folder (its :class:`GeneratingTile` shows the leading run's live frame), so
        an edited config's brand-new folder appears and is navigated to at once —
        the running row it inserts gives the folder a tree node immediately (see
        :func:`build_gallery_tree`). Missing form params are filled from the
        workflow's defaults. A no-op without a client or an unknown workflow.

        The launched runs are noted on the tab that asked for them, so that tab's
        Cancel and progress fill follow its own Generate rather than its folder.
        """
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        if self._client is None or wf is None:
            return
        batch = [{**wf.default_params(), **params} for params in batch]
        key = self.folder_key_for(workflow_name, batch[0])
        if key in self._live_jobs:
            return  # one press at a time per folder
        # A pinned seed that would reproduce a past run draws a fresh one instead of
        # launching a copy — the press was made against a button already reading
        # "Generate with Random seed" (:meth:`GenerateConfigPanel._apply_generate_caption`),
        # so this is what it said it would do, not a question worth stopping for.
        # The tab keeps the Random seed, so its form goes on saying the same thing.
        launching = self._info_tabs.current_config_panel()
        if self.would_reproduce_a_completed_run(wf, batch[0]):
            batch[0] = randomize_seeds(batch[0], wf.seed_keys())
            if launching is not None:
                launching.use_random_seed()
        launched = [prompt_id for prompt_id in self._jobs.start_batch(key, wf, batch)
                    if prompt_id]
        if not launched:
            return  # no client, or every submit failed
        if launching is not None:
            # A tab Combine opened stamps its runs with where the settings came
            # from, whether they were launched as opened or edited first — that
            # mark is the only thing telling the queue what act a video is of.
            category, video_id, intent = launching.settings_source()
            asked = launching.asked()
            for prompt_id in launched:
                if category or video_id:
                    self._db.set_settings_source(prompt_id, category=category,
                                                 video_prompt_id=video_id)
                if video_id and not category:
                    self._db.record_combine_video_use(intent, video_id, prompt_id)
                if asked is not None:
                    self._db.record_request(
                        prompt_id=prompt_id, heard="",
                        new_positive=batch[0].get("positive_prompt", ""),
                        new_negative=batch[0].get("negative_prompt", ""), **asked)
                launching.note_launched(prompt_id)
        self._stand_on_the_run_in(key, rebuild=True)

    def _stand_on_the_run_in(self, key: str, *, rebuild: bool = False) -> bool:
        """Open the folder ``key`` names and land on the run in flight there,
        saying whether the tree had a row to open at all.

        The ways here are one move — a Generate, a folder's prompt rewrite, a
        combine's launch, the Auto-Generate tip's link, a click on an in-flight tile —
        and in all of them the open is a step on the way to that run's tile rather
        than somewhere browsed to. So it lands on no saved item of its own
        (:meth:`_land_on_the_first_item`): one loaded here would paint an item
        nobody asked for over the very tab the run belongs to, and re-seed that
        tab's form from a saved row mid-run. The folder is a stop and a visit all
        the same, both recorded once the tile is picked.

        ``rebuild`` first, for a run just started: it inserts a running row, and a
        rebuild is what gives even a brand-new settings folder a node
        (:func:`build_gallery_tree` includes in-flight rows).
        """
        if rebuild:
            self.refresh()
        item = self._tree_item_for(key)
        if item is None:
            return False
        with self._navigation.off_the_record():
            self._tree.setCurrentItem(item)
        self._note_folder_visit(self._tree_view.selected_folder_key())
        self._select_reroll(key)
        self._navigation.record()
        return True

    def showEvent(self, event):
        super().showEvent(event)
        self._poll_timer.start()
        self._intercept_the_rooms_keys(True)  # back on screen: back on the keys
        self.refresh(only_if_moved=True)

    def hideEvent(self, event):
        super().hideEvent(event)
        if not (event.spontaneous() or self.window().isMinimized()):
            self._poll_timer.stop()  # no need to poll while the tab is hidden

    def closeEvent(self, event):
        """Put down everything this view arms application-wide, however it was
        let go: the poll, the filter that takes the room's keys, and the slideshows,
        each a window of its own that would otherwise outlive the view that
        answers for it.

        ``hideEvent`` alone is not enough for either: a widget that was never
        shown is never hidden, so ``close()`` on one left the 1.5 s poll running
        — blocking HTTP and a whole-table SELECT, on a view nobody can see —
        and left a closed gallery answering Esc from whatever window has focus,
        which is the pause for the whole room.
        """
        self._poll_timer.stop()
        self._intercept_the_rooms_keys(False)
        self.close_the_slideshows()
        self._voice.shut_the_mic()
        self._jobs.close()
        super().closeEvent(event)

    # --- data loading & live update ---------------------------------------

    def refresh(self, *, only_if_moved: bool = False):
        """Re-read the library and draw everything off it again.

        ``only_if_moved`` draws again only when the rows or their folder meta
        differ from what is already on screen -- the same test the 1.5 s poll
        applies, asked by a caller who is not itself a change.  Being shown is
        such a caller, and an expensive one to answer blindly: Windows answers
        a minimize with a hide and then a show, so a hosted window is shown
        again every time the session parks it, and drawing a four-thousand-row
        library afresh takes seconds of the one thread that also answers the
        session's commands.
        """
        rows = self._db.list_generations()
        meta = self._db.folder_meta_map()
        fingerprint = _fingerprint(rows, meta)
        moved = fingerprint != self._fingerprint
        self._fingerprint = fingerprint
        if moved or not only_if_moved:
            self._rebuild(rows, meta)
            self._slideshows.library_moved()
        # The tree a rebuild makes is what the base state is read from, and
        # the session's open can land before the first one (its launch races
        # this app's boot).  Filling here costs nothing when the regions are
        # already playing, and is the only thing that rescues a session that
        # opened into the mode a moment too early.
        self._slideshows.fill_the_wanted_regions()

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
        if self._poll_inflight or (self.window().isMinimized()
                                   and not self._slideshows.any_up()):
            return
        self._poll_inflight = True
        jobs = self._jobs.all_jobs
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
            self._enhance.put_what_is_locked_first()
        except Exception:
            self._poll_inflight = False
            raise
        db = self._db

        def read_listing():
            rows = db.list_generations()
            meta = db.folder_meta_map()
            return rows, meta, db.list_requests(), _fingerprint(rows, meta)

        read_at = self._drawn_version
        self.off_thread(read_listing,
                        lambda listing: self._finish_poll_rebuild(listing, read_at))

    def _finish_poll_rebuild(self, listing, read_at: int):
        """The tick's last hop: fold the freshly read listing into the panes."""
        try:
            if listing is None:  # only if the read itself died
                return
            rows, meta, requests, fingerprint = listing
            if fingerprint != self._fingerprint and read_at == self._drawn_version:
                self._fingerprint = fingerprint
                self._rebuild(rows, meta)
            else:
                # No DB change, but the in-flight tiles still need each running
                # re-roll's live frame pushed in — it advances between rebuilds.
                # Wherever they were drawn: the Latest collection, or a folder with
                # a batch of them in flight.
                self._browser.refresh_inflight(rows=rows, requests=requests)
            # The Job Queue is always on screen, so refresh it every tick —
            # its rows' live frames and progress advance between rebuilds. The
            # listing already in hand feeds it, so the Job Queue costs the tick no
            # further table reads.
            self._update_queue(self._inflight_items(rows=rows, requests=requests))
            # And a slideshow's corner, for the same reason and one more: a run
            # starting is not a change to any row, so nothing else here would
            # tell the slideshow its locked slide went from waiting to being made.
            self._enhance.tell_the_slideshows()
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
            job.take_executing(job.prompt_id in facts.executing)
        if facts.foreign is not None:
            self._foreign_queue = facts.foreign

    def _rebuild(self, rows, meta):
        self._folder_meta = meta
        self._drawn_version += 1
        standing = self._tree_view.selected_folder_key()
        place = self._browser.place()
        # Pending restore targets stand in until the user makes a live choice.
        selected_key = standing or self._pending_key
        # A live multi-selection is a folder the user is composing, so a rebuild
        # (a poll, a completed generation) must not silently collapse it back to
        # one row — the keys are re-picked once the tree is rebuilt.
        multi_keys = self._tree.selected_folder_keys()
        if len(multi_keys) <= 1:
            multi_keys = []
        selected_gen = self.selected_generation()
        # A running re-roll's tile is the selected item, not a saved row, so
        # capture it to restore afterward rather than let the folder's default
        # selection replace it. This matters because every re-roll (and each i2v
        # stage) triggers a rebuild the moment its running row lands.
        reroll_key = self._selected_reroll_key
        self._pending_key = None
        self._pending_selection = None
        self._image_rows = [r for r in rows
                            if gallery.media_type_of_row(r) == MediaType.IMAGE]
        self._combine.offer_the_acts(rows)
        self._listed_rows = rows
        self._held_rows = trash_collection.trash_items(self._trash_records())
        # Built once here off the whole library and handed to every tree below —
        # the split trees included, which are the ones that cannot build it for
        # themselves (see :func:`gallery.start_frame_index`) — and kept as the
        # index every folder key is derived against until the next rebuild.
        start_frames, trees = self._lists_for(rows, meta, self._tree.sides)
        self._image_index = start_frames
        unreviewed = self._review_queue(rows)
        held = self._held_rows
        self._live_ids = {row["prompt_id"] for row in rows}
        self._custom_folders_by_side = _custom_folders_by_side(
            trees, self._db.list_custom_folders())
        self._custom_folders = [folder for folders in self._custom_folders_by_side.values()
                                for folder in folders]
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
        # standing in the Trash collection and searching it has to find something —
        # a deleted row is out of ``list_generations`` and lives only in the Trash.
        # They are reachable only from that collection: every other scope is a set of
        # ids drawn from the live tree (see :meth:`search_scope`).
        self._search.index.update(rows + held, gallery.folder_names_by_row(
            [folder for tree in trees.values() for folder in tree], meta,
            self._custom_folders), item_name=self._item_names.of)
        requests = self._listed_requests = self._db.list_requests()
        bumped = gallery.enhancement_recency(rows)
        self._browser.set_model(
            gallery.recent_generations(rows, bumped=bumped),
            trees,
            rows,
            unreviewed,
            held,
            image_index=start_frames,
        )
        self._tree_view.populate(
            self._build_sides(trees), folder_meta=meta,
            # Where the work has lately been. The tree keeps the order the
            # settings were tried in, so nothing else in it says so.
            recently_worked=gallery.recently_worked_folders(trees, rows, bumped=bumped),
        )
        # The rows the old selection group pointed at are gone with the rebuild;
        # _restore_multi_selection below stands a fresh one up from multi_keys.
        self._selection_group = None
        # The gallery's own selection is dropped and re-picked below. The tabs are
        # not: a rebuild used to empty the front tab's preview outright and count on
        # that re-pick to paint it back, so a tab showing anything the gallery
        # wasn't pointed at went blank every time a generation landed — once per
        # variation Auto-Generate makes. Only what has actually gone (a deleted or
        # trashed item) is taken off a tab now.
        self._selected_row = None
        self._info_tabs.reconcile_previews(self._live_ids)
        self._info_tabs.reread_names()
        self._combine.reread_names()
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
                self._folder_path.set_display("")
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
        if standing is not None and self._tree_view.selected_folder_key() == standing:
            self._browser.return_to(place)
        self._update_queue(self._inflight_items(rows=rows, requests=requests))
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

    def _lists_for(self, rows, meta, sides):
        """The start frames, every item's name and a tree of contents for each
        of *sides*, kept against the library they were read off; only the drawn
        sides are built."""
        library = _fingerprint(rows, meta)
        if library != self._lists_built_from:
            self._lists_built_from = library
            self._start_frames = gallery.start_frame_index(rows)
            self._item_names.take(rows, self._held_rows, self._start_frames)
            self._lists_by_side = {}
        for side in sides:
            if side not in self._lists_by_side:
                self._lists_by_side[side] = _side_list(
                    rows, meta, self._start_frames, side, self._item_names.of)
        return self._start_frames, {side: self._lists_by_side[side] for side in sides}

    def _build_sides(self, trees):
        """The sides the pane is drawing, in the order it draws them.

        A side is the whole tree of contents over the rows it holds: its own
        hierarchy, its own copies of the folders the user composed, and collections
        whose counts are its own — a number covering more than the side draws
        would send you to a collection that then showed you nothing.

        Only the drawn sides are built. The radio's other answer is a section
        nobody can see, and filling it would cost every rebuild a table of
        contents for nothing.
        """
        return [SideModel(
            side=side,
            tree_model=trees[side],
            custom_folders=gallery.outermost(self._custom_folders_by_side[side]),
            show_latest=bool(trees[side]),
            collection_counts=self._browser.collection_counts(side),
        ) for side in self._tree.sides]

    def open_folders(self) -> list[str]:
        return sorted(self._tree_view.folders_left_open())

    def set_open_folders(self, saved) -> None:
        if isinstance(saved, list):
            self._tree_view.leave_folders_open(key for key in saved if isinstance(key, str))

    def toc_sides(self) -> list[str]:
        return list(self._tree.chosen_sides)

    def set_toc_sides(self, saved) -> None:
        self._tree.choose_sides(_TOGETHER if saved == list(_TOGETHER) else _SEPARATE)

    def _on_sides_changed(self):
        """The radio over the list moved: draw the list again on the new sides.

        A full rebuild rather than a redraw, because each side's table of
        contents is built from the rows that side holds — the one list of both
        shapes is a different hierarchy, not the two stacked.
        """
        if not self._tree_view.built:
            return
        with working():
            self.refresh()
        # The row that was selected is on a side nobody draws now, so the
        # folder-selected signal that normally re-syncs the slideshow button never
        # fires for the row the rebuild landed on instead.
        self._re_aim()

    def _reselect_generation(self, prompt_id: str | None):
        """Re-select a generation after a rebuild, if it's still on screen.

        The gallery's own selection only. The tabs keep what they were showing
        across a rebuild — one happens whenever anything lands, once per
        variation Auto-Generate makes — and a tab is repainted only when the
        generation it shows changes under it or goes (see
        :meth:`InfoPaneTabs.refresh_displayed` and
        :meth:`InfoPaneTabs.reconcile_previews`). Painting the selection
        into whichever tab was in front is how a tab came to show an item that
        was not its own."""
        if not prompt_id or prompt_id not in self._browser.listed_prompt_ids():
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
        self._find_bar.open_find(fields)

    def _prompt_fields(self) -> list:
        """The prompt inputs of the config tab in front — what a find searches."""
        panel = self._info_tabs.current_config_panel()
        return panel.prompt_fields() if panel is not None else []

    def _retarget_find(self):
        typing = QApplication.focusWidget()
        caret = typing.textCursor() if isinstance(typing, QPlainTextEdit) else None
        self._find_bar.retarget(self._prompt_fields())
        if caret is not None:
            typing.setTextCursor(caret)

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

    def name_search_on_screen(self, query: str, scope: _SearchScope) -> None:
        """Say in the header that a search is what the pane is showing, in place
        of the folder that was there."""
        self._folder_path.show_search(f"Search: “{query}” in ", scope.steps)
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
        return prompt_id in self._browser.listed_prompt_ids()

    def show_folder(self, key: str) -> bool:
        """Draw the folder or collection ``key`` names, saying whether the tree had a
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

    def reveal(self, prompt_id: str) -> bool:
        """Pick and scroll to the tile where the pane stands, and put the item
        back in the info pane; a pane of folders marks the square holding it.
        Whether anything the pane shows held it."""
        if self._browser.reveal_tile(prompt_id):
            self._on_thumbnail_clicked(prompt_id)
            return True
        row = self._db.get_generation(prompt_id)
        return row is not None and self._browser.reveal_folder(
            gallery.settings_folder_key(row, self.image_config_index()))

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

        The tree's selection is the scope, whatever kind of row it is. A collection
        counts: Latest, Favorites, Experiments and Trash are each a set of
        generations, and standing in one and searching it is the obvious thing to
        try. The All row is what covers the library entire, since every other
        folder narrows the answer before the query does.

        ``path`` is the row's breadcrumb — what the field, the header and the
        empty-result message all name the scope by.
        """
        item = self._tree.currentItem()
        if self._current_collection_key() is not None:
            rows = self._browser.selected_collection_rows() or []
            return _SearchScope(tuple(self._tree_view.path_steps(item)),
                                {row["prompt_id"] for row in rows})
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if group is None:
            # Nothing selected, or a side's header row selected: the
            # whole gallery, since neither names a folder to narrow to. The
            # trash's held rows share the index but belong to their collection alone.
            return _SearchScope((PathStep(gallery.ALL_LABEL, None),), self._live_ids)
        return _SearchScope(tuple(self._tree_view.path_steps(item)),
                            {row["prompt_id"] for row in gallery.rows_under(group)})

    def search_sort(self) -> str:
        """The results order in force, for the session state to remember."""
        return self._search.sort()

    def set_search_sort(self, mode: str | None):
        """Restore the remembered results order."""
        self._search.set_sort(mode)

    def remembered_slideshows(self) -> dict:
        return self._slideshows.remembered()

    def slideshow_showing_on(self) -> str | None:
        return self._slideshows.slideshow_showing_on()

    def remember_slideshows(self, saved) -> None:
        if self._fun_time is None:
            self._slideshows.remember(saved)

    def how_many(self) -> int:
        return self._info_tabs.how_many()

    def set_how_many(self, count) -> None:
        self._info_tabs.set_how_many(count if count in HOW_MANY else HOW_MANY[0])

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
        base, side = _split_collection_key(self._tree_view.selected_folder_key())
        collection = folder_collection(base)
        self._experiments_bar.setVisible(collection is not None
                                         and collection.which == _EXPERIMENTS_KEY)
        if current is None:
            self._folder_path.set_display("")
            self._avg_label.setText("")
            self._browser.show_empty()
            self._re_aim()
            return
        if collection is not None:
            self._open_collection(collection, side, current)
            return
        group = current.data(0, _GROUP_ROLE)
        # A folder's place in the tree is where the user is standing, side and
        # all, so that — not the folder's own key — is what history and the
        # return-after-delete trail record.
        here = self._tree_view.selected_folder_key()
        self._note_folder_visit(here if group is not None else None)
        self._folder_path.show_folder(self._tree_view.path_steps(current))
        self._update_folder_average(group)
        self._show_group_contents(group, current)
        landed = self._land_on_the_first_item()
        if group is not None:
            # A folder is somewhere the user went, so Back can return to it — and
            # so leaving a collection for one is a step Back can undo at all. The item
            # it landed on goes on the stop with it, so coming back lands there
            # too rather than on a folder with nothing picked in it.
            self._navigation.record(landed)
        self._re_aim()

    def _land_on_the_first_item(self) -> str | None:
        """Pick the folder's first generation and show it, returning which one —
        ``None`` where the folder has none to pick.

        Opening a folder is opening what is in it, so the first tile lands
        selected and on the form, exactly as clicking it would. A folder of
        sub-folders has no generation of its own on screen and lands on nothing.

        Skipped while a rebuild or a Back/Forward is what re-drew the folder:
        those restore the item that stop was recorded with (or none at all), and
        a landing of our own would overwrite it.
        """
        if self._navigation.suppressed:
            return None
        first = next(iter(self._browser.listed_prompt_ids()), None)
        if first is None or not self._show_generation(first):
            return None
        # Picked rather than revealed: the first tile leads a pane just drawn, so
        # there is nothing to scroll to, and the highlight is the whole of what
        # "selected" means here.
        self._browser.apply_selection(first, Qt.KeyboardModifier.NoModifier)
        return first

    def _open_collection(self, collection: FolderCollection, side: str | None, item):
        if collection.which == _EXPERIMENTS_KEY:
            self._sync_experiments_bar()
        self._folder_path.show_folder(self._tree_view.path_steps(item),
                                      mark=_PATH_MARK_OF.get(collection.which, ""))
        self._avg_label.setText("")
        self._clear_metadata()
        self._browser.show_collection(collection.key, side)
        self._navigation.record()

    def _show_group_contents(self, group, item):
        if isinstance(group, gallery.SettingsGroup):
            self._browser.show_thumbnails(group)
        elif isinstance(group, gallery.CustomGroup):
            self._browser.show_custom_folder(group)
        else:
            self._browser.show_folder_tiles(gallery.child_groups(group),
                                            collections=self._tree_view.collections_in(item))

    def _go_to_folder(self, key: str):
        """Go to a folder: select its tree row, which draws it.

        The one move under every gesture that names a folder to open — a folder
        tile's click, a config tab's "Go to folder", a step of the path — as
        :meth:`_go_to_generation` is the one under every gesture that names an
        item. Each is a decision to go there, so a running search is put away
        first: a search's results are folder tiles too, and this is how they
        open; without it the field would still be full while the pane shows the
        folder it drilled into.
        """
        item = _row_under(self._tree.currentItem(), key) or self._tree_item_for(key)
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
        """The folders the tree currently has picked, in tree order."""
        return [group for key in self._tree.selected_folder_keys()
                if (group := self.group_for_key(key)) is not None]

    def _show_selection(self):
        """Render the picked folders as the folder they would make: their tiles in
        the browser pane, and the toolbar offering to save the grouping."""
        group = self._selection_group
        self._experiments_bar.hide()
        self._folder_path.set_display(group.label)
        self._update_folder_average(group)
        self._browser.show_custom_folder(group)
        self._re_aim()

    def _restore_multi_selection(self, keys: list[str]):
        """Re-pick the folders a rebuild dropped, and re-show them together.

        The first is set as the current row, which clears whatever the rebuild's
        own restore had picked — so what comes back is exactly what was picked
        before, never that plus the folder the restore landed on."""
        items = [item for key in keys if (item := self._item_by_key.get(key)) is not None]
        if len(items) <= 1:
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
        folder_id = self._actions.custom_folders.create(
            name.strip(), [self._folder_identity(f) for f in folders], self.side_in_view()
        )
        self._open_custom_folder(folder_id)

    def _folder_identity(self, group) -> tuple:
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

    def _on_dropped(self, target_key: str, keys: list, prompt_ids: list = ()):
        """Folders or an item dragged onto a collecting row: Favorites favorites the
        folders (the drag-and-drop way to favorite), a custom folder gathers them
        and takes the item."""
        groups = [g for key in keys if (g := self.group_for_key(key)) is not None]
        if target_key == _FAVORITES_KEY:
            for group in groups:
                if _takes_a_favorite(group):
                    self._set_folder_favorite(group.key, True)
            self._re_aim()
            return
        folder_id = gallery.custom_folder_id(target_key)
        if folder_id is None:
            return
        self._actions.custom_folders.add_to(
            folder_id, [self._folder_identity(g) for g in groups], prompt_ids
        )
        self._open_custom_folder(folder_id)

    def _custom_folder_takes(self, row_key: str, prompt_id: str) -> bool:
        """Whether the TOC row ``row_key`` is a folder of your own that an item
        dragged over it can go in: one the gallery shows, on the row's own side."""
        folder = self.group_for_key(row_key)
        leaf = self._leaf_by_id.get(prompt_id)
        return (isinstance(folder, gallery.CustomGroup) and leaf is not None
                and _side_of(leaf.data(0, _TREE_KEY_ROLE)) == _side_of(row_key))

    def _collecting_row_takes_folder(self, row_key: str, folder_key: str) -> bool:
        """Favorites takes any folder that takes a star, a folder of your own any
        folder but one that would end up inside itself."""
        target, dragged = self.group_for_key(row_key), self.group_for_key(folder_key)
        if dragged is None:
            return False
        if isinstance(target, gallery.CustomGroup):
            return not gallery.holds(dragged, target)
        return _takes_a_favorite(dragged)

    def _landing_in_the_open_custom_folder(self, mime, source):
        if _saved_custom_folder(self.current_group()) is None:
            return None
        return self._tree.landing_on(self._tree.currentItem(), mime, source)

    def _new_custom_folder(self, side: str):
        """Make an empty folder of the user's own — the tree's right-click action,
        for when the folders to fill it with are easier dragged in than picked."""
        name, ok = QInputDialog.getText(self, "New Folder", "Folder name:")
        if ok and name.strip():
            self._open_custom_folder(
                self._actions.custom_folders.create(name.strip(), [], side))

    def _remove_custom_folder(self, group):
        """Delete a folder the user made. Only the grouping goes — what it gathers
        is untouched — so the confirmation says so rather than reading like the
        delete that trashes files."""
        if not self._confirm(f"Remove the folder “{group.label}”?\n\n{_kept_on_removal(group)}"):
            return
        self._actions.custom_folders.delete(group.folder_id)
        self._tree.clearSelection()
        self._selection_group = None
        self.refresh()
        self._re_aim()

    def _remove_from_custom_folder(self, group, folder_keys=(), items=()):
        """Take gathered folders and items out of the custom folder on screen."""
        folders = [self._folder_identity(gathered)
                   if (gathered := self.group_for_key(key)) is not None else (key, None, None)
                   for key in folder_keys]
        self._actions.custom_folders.remove_from(group.folder_id, folders, items)
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
        if self._client is None or not group.rows:
            return False
        return gallery.rerollable(group.rows[0])

    @property
    def _live_jobs(self) -> dict:
        """The live re-roll jobs, keyed by settings-folder key. Owned by the
        controller; surfaced here for the Latest collection and the info pane."""
        return self._jobs.jobs

    @property
    def _selected(self) -> dict | None:
        """The saved generation on display in the info pane, or ``None`` — read
        here for navigation, delete, and the Latest "containing folder" jump. Set
        by :meth:`_on_thumbnail_clicked`, cleared when a re-roll or nothing is
        showing."""
        return self._selected_row

    # The folder tree's key→item and prompt→item maps are owned by the GalleryTree
    # renderer; surfaced here for navigation, selection, and rebuild. A collection's row
    # is reached separately, through _collection_item.
    @property
    def _item_by_key(self) -> dict:
        return self._tree_view.item_by_key

    @property
    def _leaf_by_id(self) -> dict:
        return self._tree_view.leaf_by_id

    def selected_folder_key(self) -> str | None:
        """The selected row's tree key (or a collection's), from the tree renderer."""
        return self._tree_view.selected_folder_key()

    def side_in_view(self) -> str:
        """Which side of the list the tree is standing on.

        Every row lives under one, so this is only ever a fallback: nothing
        selected at all (a fresh window, a rebuild that found no target) reads
        as the side holding landscape, the roomier shape and the one an
        unmeasurable item files under everywhere else.
        """
        return (_side_of(self.selected_folder_key())
                or _side_holding(_LANDSCAPE, self._tree.sides))

    def _tree_item_for(self, key: str):
        """The tree row for ``key`` — a tree key resolves to its own row, and a
        folder's own key to the copy of it on the side being browsed.

        A folder key names a folder, not a place: a re-roll, a combine, a folder
        tile and a delete's return target all hold one, and each side draws its
        own row for it. Staying on the side already open is the answer that
        doesn't teleport the user across the tree; a folder only the other side
        holds is followed there rather than dropped.

        A key naming a side the pane draws is answered by that side alone.
        Falling back across the split would hand a portrait region a landscape
        library the moment the portrait one happened to be empty, which is the
        whole of what the split exists to prevent. A key naming a side the pane
        is *not* drawing — the radio has moved, or a window reopened in the
        other arrangement — has no row of its own anywhere, so its folder is
        looked for among the sides that are drawn.
        """
        item = self._item_by_key.get(key)
        if item is not None:
            return item
        folder = _base_of(key)
        drawn = self._tree_view.keys_for_folder(folder)
        if _side_of(key) in self._tree.sides:
            return next((self._item_by_key[row] for row in drawn
                         if _side_of(row) == _side_of(key)), None)
        if not drawn:
            return None
        here = oriented_key(folder, self.side_in_view())
        return self._item_by_key[here if here in drawn else drawn[0]]

    def _collection_item(self, collection_key: str, side: str | None = None):
        """One side's copy of a collection row — the side being browsed by default."""
        return self._tree_view.collection_item(collection_key, side or self.side_in_view())

    def _folder_context(self, key: str) -> str:
        """Where folder ``key`` lives: the breadcrumb of its parent, or "" at the
        top of the tree. The caption a tile drawn far from the tree wears
        (see :class:`~origenerator.gui.browser_pane.TreeNavigation`)."""
        item = self._tree_item_for(key)
        if item is None or item.parent() is None:
            return ""
        return self._tree_view.breadcrumb(item.parent())

    def current_group(self):
        """The folder on screen, or ``None`` (a collection, a search, or an empty
        selection).

        While several folders are picked that's the unsaved folder they make, so
        everything reading this — the slideshow, the title, the average — sees one
        folder whether or not it has been saved yet.

        A running search is ``None`` for the same reason a collection is: the tree
        still has a row selected, but that folder is not what the pane is showing,
        and every reader of this would otherwise offer its action — auto-generate,
        Enhance All, delete-the-folder — against something off screen."""
        if self._selection_group is not None:
            return self._selection_group
        if self._showing_search():
            return None
        item = self._tree.currentItem()
        return item.data(0, _GROUP_ROLE) if item else None

    def _lead_tiles(self, group) -> LeadTiles:
        """A settings folder's own tiles — the re-roll tile, its mirror (the same
        seeds again, said differently) and the run in front of its line — where
        the folder has each, for the pane to place
        (:attr:`~origenerator.gui.browser_pane.PaneHost.lead_tiles`)."""
        if not self._can_reroll(group):
            return LeadTiles()
        job = self._jobs.job_for(group.key)
        plus = NewTile(making_one=job is not None)
        plus.add_requested.connect(lambda: self._start_reroll(group.key))
        return LeadTiles(
            reroll=plus,
            modify=(self._folder_modify_tile_for(group)
                     if self._can_modify(group) else None),
            generating=None if job is None else self._generating_tile_for(group.key, job))

    def _forget_generating_tile(self):
        """The pane is dropping what it holds, the generating tile with it."""
        self._generating_tile = None

    def _generating_tile_for(self, key: str, job) -> GeneratingTile:
        tile = GeneratingTile(job,
                              auto_generating=self._auto.is_active(key),
                              typical_seconds=self.typical_run_seconds(job),
                              made_from=self._job_made_from(
                                  job, lambda source_video: source_video.get("thumbnail_path")))
        tile.set_selected(key == self._selected_reroll_key)
        tile.cancel_requested.connect(lambda: self._cancel_reroll(key))
        tile.context_requested.connect(lambda pos: self._generating_tile_menu(key, pos))
        tile.selected.connect(lambda: self._select_reroll(key))
        self._generating_tile = tile
        return tile

    def _generating_tile_menu(self, key: str, global_pos):
        """Right-click a folder's live tile: throw away the run it is showing.

        The same act as the button on its face, on the gesture the rest of the
        grid answers — a right-click that worked on every other tile and died on
        this one read as a tile that wasn't listening. The wording is the
        button's, so both say the same thing about the same press.

        With one more entry the button has no room for: while the folder is
        auto-generating, that Cancel only starts the next seed and nothing on the
        tile stops anything, so the menu carries the real stop too
        (:func:`inflight.stop_auto_generate_text`). Auto-Generate is ended first — a
        discard while it is still on is the cue for the next seed.
        """
        menu = QMenu(self)
        auto = self._auto.is_active(key)
        discard = menu.addAction(CANCEL_TEXT)
        discard.setToolTip(cancel_tooltip(auto))
        stop = None
        if auto:
            stop = menu.addAction(stop_auto_generate_text())
            stop.setToolTip(stop_auto_generate_tooltip())
        chosen = menu.exec(global_pos)
        if chosen is discard:
            self._cancel_reroll(key)
        elif stop is not None and chosen is stop:
            self._auto.stop(key)
            self._cancel_reroll(key)

    # --- Modify (all seeds): same seeds, changed words --------------------

    def _can_modify(self, group) -> bool:
        """True when this folder can be run again with its prompt rewritten.

        Everything a re-roll needs, plus at least one image to rewrite: the
        request reproduces the folder seed for seed, so a folder holding nothing
        finished yet has nothing to reproduce.
        """
        return self._can_reroll(group) and bool(self._folder_modify_rows(group))

    @staticmethod
    def _folder_modify_rows(group) -> list[dict]:
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

    def _folder_modify_tile_for(self, group) -> FolderModifyTile:
        tile = FolderModifyTile()
        tile.clicked.connect(lambda g=group: self._open_folder_modify(g))
        return tile

    def _open_folder_modify(self, group):
        """Open this folder's prompt in a tab, ready to be rewritten.

        Nothing is launched: the tile is the start of an edit made by hand, which
        is the whole reason it is typed rather than spoken. The tab carries the
        folder's settings, its prompts marked against themselves, and its images
        tiled in the preview — see
        :meth:`GenerateConfigPanel.open_folder_modify`.
        """
        rows = self._folder_modify_rows(group)
        workflow = WORKFLOW_REGISTRY.get(rows[0].get("workflow_name") or "") if rows else None
        if workflow is None or self._client is None:
            return
        # One entry per run the press will make, thumbnail or not, so the count
        # in the hover is the number of images and not of readable files.
        thumbnails = [row.get("thumbnail_path") for row in rows]
        self._clear_reroll_selection()  # the tab is about the folder, not a live run
        self._info_tabs.open_folder_modify(group.key, group.label, workflow.name,
                                      filled_params(rows[0], workflow), thumbnails)

    def _on_modify_requested(self, folder_key: str, workflow_name: str, params: dict):
        """A Modify tab's Generate: run every image of ``folder_key`` again with
        its own seed and the rewritten prompt, and land on the folder they make.

        One job per image, all of them into the one new settings folder — the
        seed is not part of what places a row (see
        :func:`~origenerator.gallery.signatures.canonical_settings`), so the
        rewrite comes out as this folder's parallel: the same seeds in the same
        settings, saying something slightly different.

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
        rows = self._folder_modify_rows(group) if group is not None else []
        if self._client is None or wf is None or not rows:
            return
        params = {**wf.default_params(), **params}  # form values win over defaults
        key = self.folder_key_for(workflow_name, params)
        launching = self._info_tabs.current_config_panel()
        seed_keys = wf.seed_keys()
        # Oldest first. A folder lists newest first, and a row's place in that
        # list is the order it was made in, so launching in reading order would
        # build the new folder back to front and its seeds would line up with
        # the old one's only in reverse — the one thing a glance is checking.
        # The row's own settings, filled from the workflow's defaults the way
        # a re-roll fills them — so a sparsely-recorded import still yields a
        # seed to keep rather than silently inheriting the open tab's.
        olds = [(row, filled_params(row, wf)) for row in reversed(rows)]
        batch = [{**params, **{k: was[k] for k in seed_keys if k in was}} for _, was in olds]
        launched = 0
        for (row, was), run, prompt_id in zip(olds, batch,
                                              self._jobs.start_batch(key, wf, batch), strict=True):
            if not prompt_id:
                continue  # the submit failed; the rest of the folder still goes
            launched += 1
            if launching is not None:
                launching.note_launched(prompt_id)
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
            self._stand_on_the_run_in(key, rebuild=True)

    def _job_source_image(self, job) -> str | None:
        """A file showing what ``job`` came from, for the tile to stand blurred
        under the wait until the run streams a frame of its own.

        The image it was requested or modified from first — a folder's Modify
        queues a run per image and none of them animates anything, so what it
        rewrites is the only image it has — then the start frame an i2v or an enhance is
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

    def _job_made_from(self, job, source_video_media) -> Combination:
        """What ``job`` was made from, for a surface with no frame of it yet: the
        image, and the video whose settings it follows as ``source_video_media`` shows
        that video — a still on the folder's tile, a loop in a config tab.

        The video only where a *video* was dropped: an act picked off the Combine
        dropdown names what the run will do rather than a video, and a thumbnail of
        some video the user never chose reads as a job that is that video — the
        same reason the queue's rows leave it out (see BrowserPane).
        """
        row = self._db.get_generation(job.prompt_id) if job is not None else None
        source_video = (None if row is None or row.get("act")
                        else self._db.get_generation(row.get("source_video") or ""))
        return Combination(
            self._job_source_image(job),
            source_video_media(source_video) if source_video is not None else None,
            source_video is not None
            and gallery.prompts_differ_from(job.params, source_video, job.workflow))

    def typical_run_seconds(self, job) -> float | None:
        """What a whole run of ``job``'s workflow usually takes — the prior the
        tile's countdown opens on, before the run has a pace of its own worth
        reading. ``None`` for an idle tile, or a workflow with no history yet."""
        if job is None:
            return None
        return timing.estimate_seconds(self._db.recent_durations(job.workflow.name))

    def _start_auto_reroll(self, key: str) -> bool:
        """Auto-Generate's own launch: the variation the tile's "+" would start,
        except that nothing about it reaches a config tab.

        Auto-Generate is left running while the user works, so what it is making is not
        what they are looking at. Its frames used to fill the info pane — that is,
        the preview of whichever tab was open, over the item the user had put
        there — and its results landed in a tab too. Both belong to the folder's
        own live tile in the middle column, which streams the run whether or not
        the pane is pointed at it.
        """
        return self._start_reroll(key, from_auto=True)

    def _start_reroll(self, key: str, *, from_auto: bool = False) -> bool:
        """Start a fresh variation for the folder ``key`` names and select it, so
        its live preview fills the info pane at once. Returns whether a variation
        is now running for the folder — Auto-Generate's cue that a launch
        took hold, and its cue to stop when one can't.

        The tile's "+" and Auto-Generate both come through here, and neither
        pressed a tab's Generate, so the run is offered to the tab showing that
        folder (:meth:`_claim_launch`) — otherwise it would run with no tab
        showing its progress or offering to discard it.

        ``from_auto`` is Auto-Generate's launch (:meth:`_start_auto_reroll`), and the
        one that goes up in no tab of its own: it takes the info pane only where the
        user already had it on this folder's Auto-Generate — watching one variation
        is watching the next — and otherwise leaves there whatever they put there.

        Skips a folder already re-rolling (or a missing client) without stealing
        the info pane — the same guard the controller enforces before launching.
        """
        if self._client is None:
            return False
        if key in self._live_jobs:
            return True  # one is already running for this folder
        settings = self._auto_generate_settings.get(key)
        if settings is not None:
            workflow, params = settings
            self._jobs.start_prepared(key, workflow,
                                      randomize_seeds(params, workflow.seed_keys()))
        else:
            self._jobs.start_reroll(key, self.group_for_key(key), self._image_rows)
        self._claim_launch(key)  # the tab on this folder shows it, and can discard it
        if not from_auto:
            # A no-op if the launch above failed to register. The tile is lit and
            # the run goes up in a tab — the tab on this folder where there is
            # one, else one opened on the run, the way a click on a running tile
            # lands it.
            self._select_reroll(key)
        else:
            self._note_auto_launch(key)  # its result is Auto-Generate's, not a tab's
            if self._selected_reroll_key == key:
                # The lit tile stands for Auto-Generate: watching one variation is
                # watching the next, and the tab following the folder gets the
                # new run's frames by that key without being pointed at it again.
                self._enter_reroll_selection(key)
        return self._jobs.has(key)

    def _note_auto_launch(self, key: str):
        """Remember that Auto-Generate, not a tab, asked for the run just launched — so
        no tab shows its result when it lands (:meth:`_on_reroll_finished`).

        Recorded by the id the run began under, the same name a tab knows its own
        runs by, and pruned to what is still in flight as it goes: only a live run
        can still finish, so a cancelled variation leaves nothing.
        """
        job = self._jobs.newest_job_for(key)
        if job is None:
            return  # the launch didn't take
        self._auto_origins = {origin for origin in self._auto_origins
                              if self._jobs.job_for_origin(origin) is not None}
        self._auto_origins.add(job.origin)

    def _toggle_auto(self, checked: bool):
        """Start or stop auto-generating fresh variations.

        Switching it on runs the open folder; switching it off stops Auto-Generate
        wherever it is running, since the lit switch means one is running rather
        than that this folder is the one running it (see :meth:`_sync_auto_button`).
        Cleanup runs in :meth:`_on_auto_stopped` either way.
        """
        # The folder's own key, not the row's: Auto-Generate is filed with the jobs it
        # launches, and those are keyed by folder wherever it is being watched from.
        group = self.current_group()
        if not checked:
            self._auto.stop_all()
        elif group is not None:
            self._begin_auto(group.key)
        self._re_aim()  # reflect the real state — a start may not take
        self._sync_cancel_buttons()

    def _begin_auto(self, key: str):
        """Read the workflow and settings the folder's Auto-Generate will run on,
        start it and star the folder."""
        self._capture_auto_generate_settings(key)
        self._auto.start(key)
        if self._auto.is_active(key):
            self._set_folder_favorite(key, True)
        else:
            self._auto_generate_settings.pop(key, None)  # the launch didn't take

    def _capture_auto_generate_settings(self, key: str):
        group = (self.current_group() if key == self.selected_folder_key()
                 else self.group_for_key(key))
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        workflow = WORKFLOW_REGISTRY.get(group.rows[0].get("workflow_name") or "")
        if workflow is not None:
            self._auto_generate_settings[key] = (
                workflow, filled_params(group.rows[0], workflow))

    def _on_auto_stopped(self, key: str):
        """A folder's Auto-Generate ended (toggled off or failed — a cancelled
        variation doesn't end it): drop the settings it ran on."""
        self._auto_generate_settings.pop(key, None)
        if key == self._selected_reroll_key and key not in self._live_jobs:
            # The pane was following this Auto-Generate between variations; there is no next
            # one to wait for now.
            self._clear_reroll_selection()
        self._re_aim()
        self._sync_cancel_buttons()

    def _sync_cancel_buttons(self):
        """Re-word the hover of every Cancel that throws a run away — the
        folder's live tile, the Job Queue's rows, each config tab's — after
        Auto-Generate started or ended.

        Nothing else repaints them at that moment: switching Auto on over a folder
        that is already generating launches nothing, so there is no re-roll change
        to ride, and the hover would keep promising a stop that the press no
        longer performs (or a next seed after Auto-Generate is off).
        """
        self._rerender_current_leaf()
        self._update_queue()
        self._reconcile_generating()

    # --- what the spoken words ask of this window ----------------------------

    def say(self, message: str, *, mark: str = HEARD_MARK) -> None:
        """Flash a line on the voice caption. What the slideshows use when there is no
        slideshow up to put it in the corner of."""
        self._voice.say(message, mark=mark)

    def collection_label(self, key: str) -> str:
        """A collection's plain name, for a spoken word to be answered in."""
        return COLLECTION_LABELS[key]

    def stand_in_collection(self, key: str, side: str | None) -> bool:
        """Select a collection's row, exactly as clicking it does, and say whether the
        tree had one — Latest and Favorites appear only once there is one."""
        item = self._tree_item_for(oriented_key(key, side) if side else key)
        if item is None:
            return False
        self._tree.setCurrentItem(item)  # whose signal draws it
        return True

    def run_spoken_command(self, text: str, said_at: float | None = None) -> bool:
        """Run a command the hosting session's own microphone heard, and say
        whether it was one. The session's bridge posts them here."""
        return self._voice.run_spoken_command(text, said_at)

    def taking_a_request(self) -> bool:
        return self._voice.listener.taking_a_request

    def drop_the_request(self) -> None:
        self._voice.drop_the_request()

    def _go_to_auto_generating_folder(self, _href: str):
        """Follow the tip's link to whichever folder Auto-Generate is running in.

        Read at the click rather than baked into the link, so an Auto-Generate that has
        since moved or ended takes the user to where it actually is, or nowhere.
        """
        key = self._auto.active_key()
        if key is not None:
            self._stand_on_the_run_in(key, rebuild=True)

    def rows_to_play(self) -> list[dict]:
        """The generations the slideshow would play from the view on screen: the
        collection's own rows in a collection, else everything under the selected
        folder.  All of it: narrowing a slideshow to its favorites or its enhanced
        images is the slideshow's own doing, from the two switches on its HUD.
        """
        rows = self._browser.collection_rows()
        if rows is None:
            group = self.current_group()
            rows = gallery.rows_under(group) if group is not None else []
        return rows

    def slideshow_subject(self) -> str:
        """What the slideshow button would play, named for its tooltip."""
        if self._showing_search():
            return "these results"
        if self._current_collection_key() is not None:
            return self._tree_view.breadcrumb(self._tree.currentItem())
        return "this folder"

    # --- standalone enhance: the bank button, the selection action, the queue ---

    def _re_aim(self) -> None:
        """Re-aim everything that follows what is in front of the user: the whole
        bank, the Enhance settings beside it, each tab's "Go to folder", and the
        trash cans on picked rows.

        One call rather than nine. Which buttons an event moves is not something
        a handler should have to know — that knowledge was what two bugs came out
        of, each fixed by adding the call somebody had forgotten — so every
        handler asks for all of it and the state says how it stands.
        """
        enhance = self._enhance.offer()
        self._bank.apply(self.bank_state(enhance))
        self._enhance.sync_panel(enhance)
        self._info_tabs.reread_folder_buttons()
        self._tree.offer_delete_on_picked_rows(
            self._selection_group is None or bool(self._current_deletable_folders()))

    def bank_state(self, enhance: Offer) -> BankState:
        """How the bank stands right now, gathered from the seams the buttons
        belong to: the trail, the undo stack, the tree's selection, the items
        picked, the enhance settings, the slideshows, and Auto-Generate.

        Assembled here because here is where those meet. Everything it reads is
        a question already asked by name, so the record can be written by hand in
        a test and the bank written from it with no gallery at all.
        """
        can_go_back, can_go_forward = self._trail
        undo_label = self._actions.undo_label()
        redo_label = self._actions.redo_label()
        auto_generate_folder = self._auto.active_key()
        group = self.current_group()
        can_auto_generate = (isinstance(group, gallery.SettingsGroup)
                             and self._can_reroll(group))
        elsewhere = (auto_generate_folder is not None
                     and auto_generate_folder != getattr(group, "key", None))
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
            favorite=self._favorite_offer(),
            enhance=Button(enabled=enhance.available, tip=enhance.tip),
            delete=self._delete_offer(),
            # Media, not rows: a folder gets its node the moment a generation
            # starts, so a folder being filled can hold nothing anyone can look at
            # yet, and a button that opens an empty slideshow is worse than no button.
            slideshow=Button(visible=self._slideshows.anything_to_play(),
                             tip=f"Play {self.slideshow_subject()} as a slideshow"),
            # Lit means "Auto-Generate is running", in this folder or any other:
            # clicking it off stops whichever folder has it, from wherever the user is.
            # Grayed only when there is genuinely nothing to do. While Auto-Generate
            # is elsewhere its clickable tip says so and the plain tooltip stands
            # down, so only one of the two ever appears.
            auto=Button(enabled=can_auto_generate or auto_generate_folder is not None,
                        tip="" if elsewhere else self._auto_tip(can_auto_generate,
                                                                auto_generate_folder),
                        checked=auto_generate_folder is not None),
            auto_tip=AUTO_ELSEWHERE_TIP if elsewhere else "",
        )

    @staticmethod
    def _auto_tip(can_auto_generate: bool, auto_generate_folder: str | None) -> str:
        """What the Auto toggle says it will do, for every case but Auto-Generate
        running elsewhere — that one is the clickable tip's to say."""
        if auto_generate_folder is not None:
            return "Auto-generate is running in this folder — click to stop it"
        return (
            "Auto-generate: repeatedly generate variations of this folder "
            "until toggled off"
            if can_auto_generate else
            "Auto-generate: open a settings folder to generate variations of it"
        )

    def _favorite_offer(self) -> Button:
        """Favorite, aimed like Delete and Enhance: the picked thumbnails, else the
        folder on screen. It toggles, so the tip says which way it will go — a set
        already favorited all over unfavorites.

        Dark where a star means nothing: a collection, or a deleted item in the Trash,
        which has no folder to be favorited in.
        """
        pids = self.selected_prompt_ids() if self._browser.selected_ids else []
        if pids and not self._browser.showing_trash():
            favoriting = not self._all_favorites(pids)
            return Button(tip=f"{'Favorite' if favoriting else 'Unfavorite'} {len(pids)} "
                              f"item{'s' if len(pids) != 1 else ''}")
        group = None if pids else self._favoritable_folder()
        if group is None:
            return Button(enabled=False, tip="Nothing here to favorite")
        return Button(tip=f"{'Unfavorite' if group.favorite else 'Favorite'} "
                          f"folder “{group.label}”")

    def _delete_offer(self) -> Button:
        """Delete, aimed the same way: the picked thumbnails, else the folder or
        the picked folders on screen, with the tip saying which.

        In the Trash the button's one remaining meaning is "for good", and the tip
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
        folders = self._current_deletable_folders()
        if not folders:
            return Button(enabled=False, tip="Nothing to delete")
        if len(folders) == 1:
            return Button(tip=f"Delete folder “{folders[0].label}”")
        return Button(tip=f"Delete {len(folders)} folders")

    def _favoritable_folder(self):
        """The folder on screen if a star can be set on it, else ``None``.

        A collection has no group at all, and a multi-selection's folder isn't one
        yet — it has no row to hang a star on until it's saved, which is what
        the Group button beside this one is for."""
        if self._selection_group is not None:
            return None
        return self.current_group()

    def _all_favorites(self, prompt_ids) -> bool:
        rows = [self._db.get_generation(pid) for pid in prompt_ids]
        return all(row and row.get("starred") for row in rows)

    def _favorite_selection(self):
        """The bank button's action: favorite the picked thumbnails, or the
        folder on screen — and un-favorite them when they already are, so the one
        button is the whole of the toggle."""
        if self._browser.selected_ids and not self._browser.showing_trash():
            pids = self.selected_prompt_ids()
            self.set_items_favorite(pids, not self._all_favorites(pids))
            return
        group = self._favoritable_folder()
        if group is not None:
            self._toggle_favorite(group.key)

    def close_the_slideshows(self) -> None:
        """Give every slideshow back — the session leaving origenerator mode, or
        this view going away with slideshows still up.
        """
        self._slideshows.close_the_slideshows()

    def fill_the_region(self, side: str) -> None:
        self._slideshows.fill_the_region(side)

    def close_the_slideshow(self, side: str) -> None:
        self._slideshows.close_the_slideshow(side)

    # --- a spoken request's own generation -----------------------------------

    def queue_request(self, row, workflow, params, spoken, revision) -> tuple[str, str]:
        """Launch the revised generation and record the request under it;
        return the line to say about it and its kind.

        The revision is the target's own settings with its prompt pair edited and
        *the same seed* — "the same image but without X" means the image, so
        the one thing deliberately not re-rolled is the seed that draws it.
        """
        name = row.get("workflow_name") or ""
        revised = {**params, **{key: boxed_as_typed(name, params, key, said) for key, said in (
            ("positive_prompt", revision.positive), ("negative_prompt", revision.negative))}}
        key = self.folder_key_for(name, revised)
        if not self._jobs.start_prepared(key, workflow, revised):
            return "couldn't queue the request — see the log", ERROR
        job = self._jobs.newest_job_for(key)
        logger.info("Request on %s: term %s, queued as %s", row.get("prompt_id"),
                    revision.action, job.prompt_id)
        self._db.record_request(
            prompt_id=job.prompt_id, source_prompt_id=row["prompt_id"],
            heard=spoken.heard, asked=spoken.text, term=revision.term,
            polarity=revision.polarity, action=revision.action,
            old_positive=params.get("positive_prompt", ""),
            old_negative=params.get("negative_prompt", ""),
            new_positive=revised["positive_prompt"], new_negative=revised["negative_prompt"],
        )
        self.refresh()  # the queue marks the job as a request the moment it is spoken
        return "Request submitted", NOTICE

    def delete_enhance_levels(self, prompt_id: str, filenames: list):
        """Trash some of one image's versions, from the info pane's version list.

        Undoable like every other delete here, and only ever a delete of files:
        the generation keeps its row, its folder, its star and its other
        versions. The rebuild after is what redraws the tile — a trashed top
        version means a new thumbnail and, once the last enhancement goes, no more
        yellow plus."""
        row = self._db.get_generation(prompt_id)
        if row is None or not self._actions.delete_enhance_levels(row, filenames):
            return
        self._re_aim()
        self.refresh()
        updated = self._db.get_generation(prompt_id)
        if updated is not None:
            self._info_tabs.refresh_displayed(updated, self._image_rows)
        self._re_aim()  # an image with no enhancement left awaits one

    def slideshow_location(self):
        """Where the view on screen is playing FROM, as something re-askable:
        a collection key in a collection, else the open folder's key.

        A key rather than the rows themselves, because the point of holding it
        is to ask again later — after a generation lands in that folder, when
        the rows are new objects and the browser is somewhere else entirely.
        """
        collection = self._current_collection_key()
        if collection is not None:
            return collection
        # The row's own key, not the folder's: which side the folder is being
        # looked at from is what decides the screen a slideshow of it goes to.
        return (self.selected_folder_key()
                if self.current_group() is not None else None)

    def set_room_paused(self, paused: bool) -> None:
        """The room stops, not just the slideshows: a hosting session's OmniPause,
        or a click on a Standalone slideshow.

        The director keeps its own flag for a slideshow not opened yet, because a
        slideshow is built from a set rather than held as a widget. Everything else
        that moves or sounds in this window — every looping thumbnail, the
        video a generate tab plays, Origenerator Radio and the OSR2 — asks
        :mod:`~origenerator.gui.omnipause`, so one write here reaches the ones
        built after it as well.

        The slideshows come first and the freeze cannot be skipped if they raise, so
        each is its own step: a freeze that stopped at the slideshows left the
        thumbnails running with no sign of why.
        """
        if paused != omnipause.frozen():
            logger.info("The room is %s", "paused" if paused else "playing")
        self._slideshows.set_room_paused(paused)
        omnipause.freeze(paused)

    def hud_place(self, side: str) -> tuple:
        return self._slideshows.hud_place(side)

    def place_a_hud(self, side: str, action: str, argument: str) -> None:
        self._slideshows.place_a_hud(side, action, argument)

    def region_slideshow(self, side: str):
        """The slideshow occupying satellite region *side*, or None. The hosting
        session's bridge asks this window for it."""
        return self._slideshows.region_slideshow(side)

    def favorite_generation(self, prompt_id: str, favorite: bool = True):
        """Favorite a generation from a fullscreen slideshow (its Down key) — the same
        star the gallery's own control sets — or take the favorite back (its Up
        key over a favorite, the Funestras' "weird" on one)."""
        self.set_items_favorite([prompt_id], favorite)

    def trash_generation(self, prompt_id: str):
        """Trash a generation condemned from a slideshow (its Up key) — the same
        undoable delete as anywhere else.

        An unreviewed experiment is rejected instead of deleted: the Experiments
        collection plays as a slideshow, so Up there is the collection's own Reject, and
        that keeps the row whose params the policy learns to steer away from.

        An item already in the Trash has no row to delete, so Up does nothing over
        the Trash collection's slideshow. Deliberate: the only delete left there is the
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
        if key in self._live_jobs:
            return  # this folder already has a re-roll running
        if which == REROLL_VIDEO:
            self._jobs.reroll_video_seed(key, row)
        else:
            self._jobs.reroll_image_seed(key, row, self._image_rows)
        self._select_reroll(key)  # a no-op if the launch above failed to register

    # --- combine: a video's settings applied to a dropped image -----------

    # --- the line's answer to the press, before there is a job ------------

    def off_thread(self, work, done):
        """Run one slow call away from the UI and hand its result back here.

        A seam as much as a call: the suite replaces this with a straight-through
        version, so a test can poll and inspect in one breath rather than pumping
        an event loop for every tick.
        """
        run_off_thread(work, done, owner=self)

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
        """A locked slide asked to be enhanced; whether a run started."""
        return self._enhance.enhance_from_slideshow(prompt_id)

    def enhance_it(self, prompt_id: str | None) -> tuple[str | None, str, str]:
        """The spoken "enhance" over an image."""
        return self._enhance.enhance_it(prompt_id)

    def fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str, str]:
        """The spoken "fix <part>" over an image."""
        return self._enhance.fix_parts(prompt_id, parts)

    def image_rows(self) -> list[dict]:
        """Every image row the gallery is holding, as its last rebuild read them."""
        return self._image_rows

    def tell(self, title: str, message: str) -> None:
        """Say something that needs acknowledging, in a dialog over this window."""
        QMessageBox.information(self, title, message)

    def combine_selection(self) -> dict:
        """What the combine panel is holding, for session save."""
        return self._combine.selection()

    def restore_combine_selection(self, saved) -> None:
        """Put the combine panel back the way a session left it."""
        self._combine.restore(saved)

    def animate_it(self, image_id: str | None,
                   asked) -> tuple[str | None, str, str]:
        """Animate an image as a named act — what an "animate as" runs."""
        return self._combine.animate_it(image_id, asked)

    def reveal_launch(self, key: str):
        """Show a just-launched combine. If its (image × settings) folder already
        exists, open it and mirror the live tile; otherwise it's a brand-new
        combination with no folder yet, so park on Latest — where its in-flight
        tile shows — and remember the key for :meth:`_on_reroll_finished` to drill
        into once the finished row gives the folder a node."""
        if self._stand_on_the_run_in(key):
            return  # an existing folder: watch the live tile there
        if (latest := self._collection_item(_LATEST_KEY, self._launched_side(key))) is not None:
            self._pending_combine_key = key
            self._tree.setCurrentItem(latest)

    def _launched_side(self, key: str) -> str:
        """Which side a job just launched in folder ``key`` will land on.

        Read off the size it asked for, since it has no result to measure yet —
        the same thing that puts its in-flight tile in one Latest collection rather
        than the other. With no job to ask, the side being browsed.
        """
        job = self._jobs.job_for(key)
        asked = requested_orientation(job.params) if job is not None else None
        return _side_holding(asked, self._tree.sides) or self.side_in_view()

    # --- re-roll as the info-pane source ----------------------------------

    def _reveal_reroll(self, key: str):
        """Open the folder a re-roll runs in and select its live tile — an
        in-flight tile's click, relayed by the browser pane.

        Leaves a running search first: results take the pane over, and picking
        a tree row underneath them re-scopes the search rather than showing the
        folder — so the click landed on the row and the wall of results stayed
        up, which reads as the click doing nothing at all.
        """
        self._search.leave()
        # The second try rebuilds: a folder the tree has not drawn yet — the first
        # run in a brand-new settings folder makes the node — is a gap this click
        # can land in, and rebuilding beats dropping the gesture.
        if not (self._stand_on_the_run_in(key)
                or self._stand_on_the_run_in(key, rebuild=True)):
            logger.info("Nothing to reveal for %s: no folder row", key)

    def _select_reroll(self, key: str):
        """Make a running re-roll's tile the selected item, and show the run
        full size in the tab it belongs to.

        That tab is never simply the one in front: it is a tab already following
        this folder, else the tab that launched the run — a Generate, or a claim
        on the folder's own launch (:meth:`_claim_launch`). A run no tab is for
        is landed the way a clicked thumbnail is: in the front tab when its
        settings are this very folder, else in the pane's preview tab, seeded
        from the run's own settings
        (:meth:`GenerateConfigPanel.show_running_generation`) so the tab is *for*
        this run — its form is the run's settings, its bar fills with the run's
        progress, its button discards it, and its preview follows the run's
        frames to the item they land as
        (:meth:`GenerateConfigPanel.watch_folder`). That is what a click on the
        tile or on the collection's tile asks for, and the tab comes to the front as a
        clicked thumbnail's does.

        The folder tile's "+" lands its run the same way: that press is a press
        for an item, and its tile is a thumbnail's worth of one. The tab it
        lands in is the pane's resting or preview tab, else a new one, so no tab
        anybody is working in is taken.
        """
        job = self._live_jobs.get(key)
        if job is None:
            return
        self._enter_reroll_selection(key)
        tabs = self._info_tabs
        panel = tabs.panel_watching(key) or tabs.panel_that_launched(job.origin)
        if panel is None:
            front = tabs.current_config_panel()
            if (front is not None and front.workflow_and_signature() is not None
                    and self._config_folder_key(front.current_config()) == key):
                panel = front
            else:
                panel = tabs.landing_panel()
                row = self._db.get_generation(job.prompt_id)
                if row is not None:
                    panel.show_running_generation(row)
            if job.origin not in panel.launched_runs():
                panel.note_launched(job.origin)  # its Cancel and progress are this run's now
            tabs.pin_tab(panel)  # ...so a later click opens beside it, not over it
            self._reconcile_generating()
        panel.watch_folder(key, job.last_preview, self._wait_note(key),
                           self._job_made_from(job, self.animated_preview))
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
        if (key is None or key not in self._live_jobs
                or getattr(self.current_group(), "key", None) != key):
            return
        self._enter_reroll_selection(key)

    def _enter_reroll_selection(self, key: str):
        """Make re-roll ``key``'s tile the gallery's selected item, in place of
        any saved generation."""
        self._selected_reroll_key = key
        self._selected_row = None  # a running re-roll isn't a saved generation
        self._browser.clear_thumbnail_selection()
        if self._generating_tile is not None:
            self._generating_tile.set_selected(True)

    def _wait_note(self, key: str) -> str | None:
        """What holds re-roll ``key`` up, when that is not its own folder's queue: a
        following tab's wait text, in place of a bare 'waiting for preview'."""
        job = self._live_jobs.get(key)
        if job is None:
            return None
        return queue_wait_text(job.foreign_ahead, self._jobs.starts_at(job.prompt_id))

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
        of its own, and a frame painted over that is the one nobody asked for.
        """
        for panel in self._info_tabs.watchers_of(key):
            panel.show_live_frame(data)
        # An enhance's frames show on the tile of the image being enhanced and in
        # the version list of any tab displaying it — an enhancement isn't a
        # generation taking a preview over.
        self._enhance.reconcile()
        # And straight onto an open slideshow, which is watching for exactly this.
        self._slideshows.note_generating(prompt_id, data)

    def _clear_reroll_selection(self):
        """Stop treating a running re-roll's tile as the selected item — a saved
        generation is the selection now, or the re-roll has ended."""
        self._selected_reroll_key = None
        if self._generating_tile is not None:
            self._generating_tile.set_selected(False)

    def reconnect_running_jobs(self):
        """Rebind live jobs to any re-rolls left running by a previous session, so
        each shows live progress and records its completion again. Called once at
        startup; a tab's Generate is itself a re-roll, so every still-running row is
        the re-roll controller's to reconnect."""
        self._enhance.take_up_trainings()
        self._look_training.take_up_trainings()
        self._jobs.reconnect_running()

    def _cancel_reroll(self, key: str):
        """The live tile's button: drop the variation it leads with.

        Auto-Generate survives it and launches the next seed at once — cancel
        discards the run, only the Auto toggle stops Auto-Generate. Told *after* the
        drop, so the relaunch doesn't see the job it is replacing and no-op.
        """
        self._jobs.cancel(key)
        self._auto.note_canceled(key)
        self._after_a_job_ended_unfinished(key)

    def _cancel_job(self, prompt_id: str):
        """Throw away one named run — a queue row's button, and a config tab's.

        A folder can hold several runs at once, so the one to drop is named rather
        than inferred from its folder; the redraw afterwards is the same.
        Auto-Generate in that folder takes it as a discarded seed and launches the next —
        after the drop, and a no-op while another of the folder's runs is still
        alive (:meth:`_start_reroll`), so Auto-Generate never doubles up.
        """
        key = self._job_folder_key(self._jobs.job_for_prompt(prompt_id))
        self._jobs.cancel_job(prompt_id)
        if key is not None:
            self._auto.note_canceled(key)
            self._after_a_job_ended_unfinished(key)

    def _after_a_job_ended_unfinished(self, key: str):
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()  # a tab's run may have stopped
        self._enhance.reconcile()

    def _abandon_reroll_preview(self, key: str):
        """A run in folder ``key`` ended with nothing to show (cancelled or
        failed): its tile stops being the selected item; and once the folder has
        no run left, the tabs following it put their own items back. While it
        still has one — the next of a batch, Auto-Generate's next seed — they keep
        following, since that run's frames are what comes next."""
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()
            self._selected_row = None
        if not self._jobs.has(key):
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
        # a variation Auto-Generate made has none at all: it is not what the user is
        # working on, so it never takes a tab's preview over.
        run = origin or prompt_id
        launcher = (None if run in self._auto_origins
                    else self._info_tabs.panel_that_launched(run))
        self._auto_origins.discard(run)
        finished_row = self._db.get_generation(prompt_id)
        if (finished_row is not None
                and finished_row.get("source") == GenerationSource.EXPERIMENT):
            # A background experiment landed: it waits in the Experiments collection
            # for review rather than moving the user's view — no front-tab load,
            # no slideshow feed, no Auto-Generate or combine bookkeeping.
            self.refresh()
            return
        folded = False
        if finished_row is not None \
                and finished_row.get("workflow_name") == gallery.ENHANCE_WORKFLOW:
            # A standalone enhance is an upgrade, not a generation: fold its
            # output onto the image it enhanced — same row, same folder, same
            # star, now wearing the enhanced pixels and plus — and let the
            # upgraded image be what the front tab shows.
            source_id = gallery.fold_enhancement(self._db, finished_row)
            if source_id is not None:
                folded = True
                finished_row = self._db.get_generation(source_id)
                # A slideshow that asked for this one swaps the slide for it.
                self._slideshows.note_enhanced(finished_row)
        self._combine.send_to_genau_if_requested(finished_row)
        # The tile stops being the selected item — unless Auto-Generate is running
        # here, where the key stands for it rather than for this one variation:
        # someone watching it churn is watching what it does next, so the
        # selection waits for the variation after this one (see :meth:`_start_reroll`).
        if key == self._selected_reroll_key and not self._auto.is_active(key):
            self._clear_reroll_selection()  # refresh re-selects it as a finished thumbnail
        self._slideshows.note_landed(finished_row)  # before refresh says it left the queue
        self.refresh()
        self._slideshows.note_finished(finished_row)  # a slideshow of its folder gains it
        self._show_reroll_result_in_tab(finished_row, launcher)
        if folded:
            # The image itself changed — it now holds a level it did not a
            # moment ago — and a tab holds the row it was handed, not a live
            # view of the database. Without this the new version reaches the
            # list only when the tab is next opened, which is a tab away and
            # back.
            self._info_tabs.refresh_displayed(finished_row, self._image_rows)
        self._show_landed_to_watchers(key, finished_row, launcher)
        # A combine whose brand-new folder we parked off (on Latest) now has a
        # finished row, so the rebuild above gave that folder a node: drill in.
        if key == self._pending_combine_key:
            self._pending_combine_key = None
            item = self._tree_item_for(key)
            if item is not None:
                self._tree.setCurrentItem(item)
        self._enhance.forget(prompt_id)  # a run that is over is nobody's enhance
        self._reconcile_generating()  # the run ended: the front tab drops its Cancel
        self._auto.note_finished(key)  # if auto-generating in this folder, launch the next
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
        """The run a tab was following has landed: put its item where its live
        frames were, in every tab following folder ``key``.

        Without this a tab watching Auto-Generate — or a fullscreen slideshow opened over
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
        was being watched, redraw the folder without its tile, and SAY SO."""
        self._auto.note_failed(key)  # end Auto-Generate rather than spin on a broken workflow
        self._after_a_job_ended_unfinished(key)
        self._generation_failed.say(format_execution_error(message))

    def _rerender_current_leaf(self):
        """Redraw the open settings folder so its tiles reflect the job."""
        group = self.current_group()
        if isinstance(group, gallery.SettingsGroup):
            self._browser.show_thumbnails(group)

    def listed_prompt_ids(self) -> list[str]:
        return self._browser.listed_prompt_ids()

    def queue_now(self) -> tuple[list, int]:
        """What is in flight here and how much of ComfyUI's queue is another
        app's — the pair the Job Queue and a slideshow's corner plate both draw."""
        listed = self._listed_rows
        holds_every_job = {row["prompt_id"] for row in listed} >= set(self._jobs.queue_order)
        items = (self._inflight_items(rows=listed, requests=self._listed_requests)
                 if holds_every_job else self._inflight_items())
        return items, self._foreign_queue.total

    def _inflight_items(self, rows=None, requests=None) -> list:
        return self._starting.placed_among(
            self._browser.inflight_items(rows=rows, requests=requests), self._jobs)

    def _update_queue(self, inflight=None):
        """Feed the Job Queue every in-flight job, in the order ComfyUI will
        work through them, plus whatever another app has on ComfyUI — so the whole
        queue shows from anywhere, and one that isn't ours is visible before
        Generate rather than after.

        An open slideshow is fed the same list twice over: once for the queue it
        covers, and once for the slides themselves, since a run that has begun to
        look like something is a slide of that slideshow.

        ``inflight`` is the already-built tile list, when the caller (the poll)
        holds one; every other caller lets it be built fresh here.
        """
        items = self._inflight_items() if inflight is None else inflight
        self._queue.set_items(items, self._foreign_queue.total)
        self._slideshows.note_queue(items, self._foreign_queue.total)
        self._slideshows.note_in_flight(items)

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

    def start_now(self):
        self._jobs.start_now()
        self._update_queue()

    def cancel_all(self):
        items = jobs_to_cancel(self._inflight_items())
        if not items or not _confirmed_cancel_all(self, len(items)):
            return
        for item in reversed(items):
            item.cancel()
        self._update_queue()

    def clear_foreign_queue(self):
        """Wipe another app's work off ComfyUI, on the user's say-so.

        The shared server accumulates jobs no window here can account for — a
        branch preview's absence experiments outlive the preview that queued
        them, and the production app cancels only the experiments its own database
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
        self._update_queue()  # the Job Queue goes blank now rather than a poll later

    def _confirm_clear_queue(self, total: int) -> bool:
        """Ask before dropping it: the jobs are somebody's work, and one of them
        may be part-rendered. Spelled out, since the button sits beside a caption
        that is often the user's own running job."""
        reply = QMessageBox.question(
            self, "Clear ComfyUI's queue",
            f"{clear_queue_tooltip(total)}?\n\nAnything you queued from here is left alone;"
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
        :meth:`reconnect_running_jobs`."""
        self._info_tabs.restore_state(state)

    # --- selection ---------------------------------------------------------

    def selected_prompt_ids(self) -> list[str]:
        return self._browser.selected_prompt_ids()

    # --- deletion & undo ---------------------------------------------------

    def generation_menu(self, prompt_ids: list[str], global_pos):
        """The right-click menu a generation offers, wherever it is shown.

        One menu rather than one per surface: a thumbnail in the browser pane and
        the preview in a config tab are looking at the same generation, so a
        right-click has to reach the same acts either way.

        "Go to folder" is left off when the pane already IS that folder, which is
        what makes it appear exactly where it is worth having: in the collections and
        among a search's hits, where what you are looking at was gathered from
        somewhere else. Enhance is offered whenever any picked item is a finished
        image — the handler skips the rest — and enhances deliberately, so an
        image that already holds one is re-enhanced rather than skipped; the
        corner's plus is where "you already have this one" is said. The star entry
        reads Unfavorite only when every picked item is already favorited, and toggles
        the whole selection to the opposite state.

        Another act appears only while something is being made of a picked image:
        cancel the enhancement in flight. An enhancement has no tile of its own —
        it is shown on the tile of the image it improves, under a scrim — so this
        menu is the only thing that tile can be asked to stop it with, and without
        it the run had to be hunted down among the Job Queue's rows. It sits
        beside Enhance, the act that started it. And inside a custom folder, what
        it holds on its own can be taken back out of it, as its folders can.
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
        _offer_copy_names_above_a_line(
            menu, [self._item_names.of(row["prompt_id"]) for row in rows])
        all_favorites = all(row.get("starred") for row in rows)
        favorite_action = menu.addAction(("Unfavorite" if all_favorites else "Favorite") + suffix)
        open_custom = _saved_custom_folder(self.current_group())
        held = {row["prompt_id"] for row in open_custom.rows} if open_custom else set()
        held_here = [row["prompt_id"] for row in rows if row["prompt_id"] in held]
        remove_action = (menu.addAction(f"Remove from “{open_custom.label}”")
                         if held_here else None)
        enhanceable = [row for row in rows if gallery.is_enhanceable_row(row)]
        to_enhance = [row["prompt_id"] for row in enhanceable if self._enhance.would_enhance(row)]
        enhance_action = None
        if enhanceable:
            n = len(to_enhance) or len(enhanceable)
            enhance_action = menu.addAction(
                f"Enhance {n} image{'s' if n != 1 else ''}"
            )
            if not to_enhance:
                enhance_action.setEnabled(False)
                enhance_action.setToolTip(ALREADY_AT_THESE_SETTINGS)
                menu.setToolTipsVisible(True)
        in_flight = self._enhance.jobs_targeting(rows)
        cancel_action = None
        if in_flight:
            n = len(in_flight)
            cancel_action = menu.addAction(
                f"Cancel {n} enhancement{'s' if n != 1 else ''}"
            )
        delete_action = menu.addAction("Delete" + suffix)
        chosen = menu.exec(global_pos)
        if folder_action is not None and chosen is folder_action:
            self.follow_link(rows[0]["prompt_id"])
        elif chosen is favorite_action:
            self.set_items_favorite([row["prompt_id"] for row in rows], not all_favorites)
        elif remove_action is not None and chosen is remove_action:
            self._remove_from_custom_folder(open_custom, items=held_here)
        elif enhance_action is not None and chosen is enhance_action:
            self._enhance.enhance_items(to_enhance)
        elif cancel_action is not None and chosen is cancel_action:
            self._enhance.cancel_for(rows)
        elif chosen is delete_action:
            self._delete_rows(rows)

    def _can_open_containing_folder(self, row: dict) -> bool:
        """Whether there is a folder to send this generation's file to.

        A deleted one has none — it left its folder when its row did — and neither
        has one whose folder is already the pane you are standing in, where going
        there would be a click that changes nothing.
        """
        if row.get("deleted_at") is not None:
            return False
        leaf = self._leaf_by_id.get(row.get("prompt_id"))
        return leaf is not None and leaf is not self._tree.currentItem()

    def run_item_action(self, prompt_id: str, action: str):
        """Run one corner button's act on one generation.

        The corner buttons are drawn on a particular item, so unlike the menu
        they never act on a selection: pressing the star on a tile favorites THAT
        tile, whichever tiles happen to be picked.
        """
        row = self._db.get_generation(prompt_id)
        if row is None:
            return
        if action == corner_buttons.STAR:
            self.set_items_favorite([prompt_id], not row.get("starred"))
        elif action == corner_buttons.TRASH:
            self._delete_rows([row])
        elif action == corner_buttons.ENHANCE:
            self._enhance.enhance_items([prompt_id])

    def set_items_favorite(self, prompt_ids, favorite: bool):
        for pid in prompt_ids:
            self._db.set_generation_favorite(pid, favorite)
        ids = set(prompt_ids)
        outside_videos.tell_fun_time([row for row in self._listed_rows if row["prompt_id"] in ids],
                                     favorite)
        for row in self._listed_rows:
            if row["prompt_id"] in ids:
                row["starred"] = 1 if favorite else 0
        if not self._redrew_the_favorites_collection():
            self._browser.refresh_corners()
        self._info_tabs.reconcile_previews(self._live_ids)
        if ids & self._browser.selected_ids:
            self._re_aim()

    def _recount_the_collections(self) -> None:
        for side in self._tree.sides:
            self._tree_view.set_collection_counts(side, self._browser.collection_counts(side))

    def _redrew_the_favorites_collection(self) -> bool:
        self._recount_the_collections()
        base, side = _split_collection_key(self.selected_folder_key())
        collection = folder_collection(base)
        if collection is None or collection.which != _FAVORITES_KEY:
            return False
        place = self._browser.place()
        self._browser.show_collection(collection.key, side)
        self._browser.return_to(place)
        return True

    def _delete_selection(self):
        """Delete picked thumbnails, or else the folder or picked folders on screen.

        In the Trash collection the picked items are already deleted, so Delete means
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
        self._delete_folders(self._current_deletable_folders())

    def _copy_names_of_the_selection(self):
        if self._browser.selected_ids:
            copy_names([self._item_names.of(pid) for pid in self.selected_prompt_ids()])
        elif self._selection_group is not None:
            copy_names(_names_of_the_picked_folders(self._selection_group))
        elif (group := self.current_group()) is not None:
            copy_names([group.label])

    # --- the Trash collection: restoring a delete, or ending it --------------

    def _trash_records(self) -> list[dict]:
        """The trashed items the Trash collection offers."""
        return self._db.list_trashed()

    def _on_trash_action(self, prompt_id: str, action_id: str):
        """A Trash tile's hover control: restore this item, or end it now."""
        if action_id == "restore":
            self.restore_from_trash([prompt_id])
        else:
            self.purge_from_trash([prompt_id])

    def _trash_menu(self, global_pos):
        ids = self.selected_prompt_ids()
        suffix = f" {len(ids)} item{'s' if len(ids) != 1 else ''}"
        menu = QMenu(self)
        _offer_copy_names_above_a_line(menu, [self._item_names.of(pid) for pid in ids])
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
        with the thing you recovered in front of you rather than in the collection it
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

    def _current_deletable_folders(self) -> list:
        if self._showing_search():
            return []
        if self._selection_group is None:
            folders = [self.current_group()]
        else:
            folders = [self.group_for_key(key) for key in self._tree.selected_folder_keys()]
        return folders if all(_is_deletable_folder(group) for group in folders) else []

    def _delete_folders(self, groups):
        if not groups or not all(_is_deletable_folder(group) for group in groups):
            return
        rows = list({row["prompt_id"]: row for group in groups
                     for row in gallery.rows_under(group)}.values())
        if not rows:
            return
        plural = "s" if len(rows) != 1 else ""
        named = (f"“{groups[0].label}” and its" if len(groups) == 1
                 else f"{len(groups)} folders and their")
        if not self._confirm(f"Delete {named} {len(rows)} item{plural}?"):
            return
        target = self._post_delete_target(groups)
        if target is not None:
            self._tree.setCurrentItem(target)
        self._delete_rows(rows)

    def _post_delete_target(self, groups):
        """The tree item to select after deleting ``groups``: the most recently
        visited folder that isn't inside a deleted subtree, else the nearest one
        above the first of them that survives."""
        doomed = set().union(*(self._keys_under(group) for group in groups))
        for key in reversed(self._folder_history):
            if key not in doomed and (item := self._item_by_key.get(key)) is not None:
                return item
        item = self._tree_item_for(groups[0].key)
        while item is not None and item.data(0, _TREE_KEY_ROLE) in doomed:
            item = item.parent()
        return item

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
        self._slideshows.release_media(paths)

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

    # --- right-click menus & star --------------------------------------------

    def _on_tree_context_menu(self, item, global_pos: QPoint, side: str):
        if item is None:
            self._empty_tree_context_menu(global_pos, side)
            return
        # Right-clicking inside a multi-selection offers what to do with the whole
        # set; right-clicking outside it is about the one row under the cursor.
        if _is_one_of_the_picked(self._selection_group, item.data(0, _GROUP_ROLE)):
            self._selection_context_menu(global_pos)
            return
        if item.data(0, _GROUP_ROLE) is not None:
            # The row under the cursor, not the folder it draws: the same folder
            # on the other side is a different row with its own menu.
            self._folder_context_menu(item.data(0, _TREE_KEY_ROLE), global_pos,
                                      toc_rows=[item])

    def _empty_tree_context_menu(self, global_pos: QPoint, side: str):
        """Below the last row there is no folder to act on, so the only thing on
        offer is starting a new folder of your own."""
        menu = QMenu(self)
        new_action = menu.addAction("New folder…")
        if menu.exec(global_pos) == new_action:
            self._new_custom_folder(side)

    def _selection_context_menu(self, global_pos: QPoint):
        names = _names_of_the_picked_folders(self._selection_group)
        menu = QMenu(self)
        _offer_copy_names_above_a_line(menu, names)
        group_action = menu.addAction(f"Group {len(names)} folders into a new folder…")
        doomed = self._current_deletable_folders()
        delete_action = None
        if doomed:
            menu.addSeparator()
            delete_action = menu.addAction(f"Delete {len(doomed)} folders…")
        collapse_and_expand = offer_collapse_and_expand(menu, self._tree.selectedItems())
        chosen = menu.exec(global_pos)
        if chosen == group_action:
            self._group_selection()
        elif delete_action is not None and chosen == delete_action:
            self._delete_folders(doomed)
        elif chosen in collapse_and_expand:
            collapse_and_expand[chosen]()

    def _folder_context_menu(self, key: str, global_pos: QPoint, toc_rows=()):
        group = self.group_for_key(key)
        if group is None:
            return
        holder = (_folder_of_your_own_above(toc_rows) if toc_rows
                  else _saved_custom_folder(self.current_group()))
        if isinstance(group, gallery.CustomGroup):
            self._custom_folder_context_menu(group, global_pos, holder, toc_rows)
            return
        menu = QMenu(self)
        _offer_copy_names_above_a_line(menu, [group.label])
        favorite_action = menu.addAction("Unfavorite" if group.favorite else "Favorite")
        remove_action = _offer_taking_out(menu, holder, group)
        add_menu = self._add_to_folder_menu(menu, key)
        delete_action = None
        if _is_deletable_folder(group):
            menu.addSeparator()
            delete_action = menu.addAction("Delete folder…")
        collapse_and_expand = offer_collapse_and_expand(menu, toc_rows)
        chosen = menu.exec(global_pos)
        if chosen == favorite_action:
            self._toggle_favorite(key)
        elif remove_action is not None and chosen == remove_action:
            self._remove_from_custom_folder(holder, [group.key])
        elif chosen in add_menu:
            self._on_dropped(add_menu[chosen], [key])
        elif delete_action is not None and chosen == delete_action:
            self._delete_folders([group])
        elif chosen in collapse_and_expand:
            collapse_and_expand[chosen]()

    def _add_to_folder_menu(self, menu: QMenu, key: str) -> dict:
        """An "Add to" sub-menu naming each of the user's folders — the menu route
        to what a drag onto its row does, for when dragging is awkward (a long tree,
        a folder scrolled out of sight). Returns ``{action: custom folder key}``,
        empty when there are no folders of the user's own yet."""
        side = _side_of(key) or self.side_in_view()
        targets = [f for f in self._custom_folders_by_side.get(side, ())
                   if not any(m.key == _base_of(key) for m in gallery.child_groups(f))]
        if not targets:
            return {}
        submenu = menu.addMenu("Add to folder")
        return {submenu.addAction(folder.label): folder.key for folder in targets}

    def _custom_folder_context_menu(self, group, global_pos: QPoint, holder, toc_rows):
        menu = QMenu(self)
        _offer_copy_names_above_a_line(menu, [group.label])
        take_out_action = _offer_taking_out(menu, holder, group)
        remove_action = menu.addAction("Remove folder…")
        collapse_and_expand = offer_collapse_and_expand(menu, toc_rows)
        chosen = menu.exec(global_pos)
        if take_out_action is not None and chosen == take_out_action:
            self._remove_from_custom_folder(holder, [group.key])
        elif chosen == remove_action:
            self._remove_custom_folder(group)
        elif chosen in collapse_and_expand:
            collapse_and_expand[chosen]()

    def _toggle_favorite(self, key: str):
        # A star is the folder's, not the row's: both sides draw the same folder,
        # so favoriting it on one is favoriting it.
        group = self.group_for_key(key)
        if _takes_a_favorite(group):
            self._set_folder_favorite(group.key, not group.favorite)
            self._re_aim()

    def _set_folder_favorite(self, key: str, favorite: bool):
        if bool(self._folder_meta.get(key, {}).get("starred")) == favorite:
            return
        self._db.set_folder_favorite(key, favorite)
        self._tree_view.mark_favorite(key, favorite)
        self._folder_meta[key] = {**self._folder_meta.get(key, {"custom_name": None}),
                                  "starred": favorite}
        self._fingerprint = (self._fingerprint[0],
                             _folder_meta_fingerprint(self._folder_meta))
        self._drawn_version += 1
        if not self._redrew_the_favorites_collection():
            self._browser.mark_folder_favorite(key, favorite)

    def _delete_folder_by_key(self, key: str):
        """Delete what a row's trash can names: its folder, or every picked folder."""
        group = self.group_for_key(key)
        if _is_one_of_the_picked(self._selection_group, group):
            self._delete_folders(self._current_deletable_folders())
        elif group is not None:
            self._delete_folders([group])

    # --- the selected generation drives a config tab -----------------------

    def row_for(self, prompt_id: str) -> dict | None:
        """The generation under a tile: the gallery's own row, else a held
        deletion's.

        A deleted item's row is out of the ``generations`` table — that is what
        deleting is — but the Trash kept it whole, and its files are all
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
        """A generation was picked, wherever it was picked — in a folder, on a
        collection, among a search's hits, through a followed link, by a step Back.
        """
        if not self._show_generation(prompt_id):
            return
        # Each generation looked at is its own browsing step, wherever it was
        # looked at: in a folder, in a collection, or among a search's hits. The view it
        # was picked in goes on the stack with it, so Back returns to the item AND
        # to the pane it was one of — not to some other folder that also holds it.
        self._navigation.record(prompt_id)

    def _show_generation(self, prompt_id: str) -> bool:
        """Make a generation the selected item and load it into a config tab —
        its output in the preview, its settings in the form, a footer for its
        media type — saying whether the gallery still has a row for it.

        Which tab is :meth:`InfoPaneTabs.load_selection`'s to say — the one
        already on this row's folder, else the pane's preview tab — and a tab is
        only ever painted through there: no tab's preview is repainted from the
        outside, so what a tab shows is always what that tab is for.

        The move itself, with no step recorded: a click records the stop it made,
        while a folder opening onto its first item records that landing as part
        of the folder's own stop rather than as a second one beside it.
        """
        row = self.row_for(prompt_id)
        if not row:
            return False
        self._select_saved_generation(row)
        self._info_tabs.load_selection(row, self._image_rows)
        return True

    def _select_saved_generation(self, row: dict):
        """Make a saved generation the gallery's selected item, in place of any
        running re-roll's tile — the gallery's own state, no tab touched."""
        self._clear_reroll_selection()
        self._selected_row = row

    def animated_preview(self, row: dict) -> str | None:
        """The looping-WebP preview for a video ``row`` once one is made — until then
        ``None``, and the tile shows its still while one is made off the window's
        thread and starts playing it when it is. Feeds the grid tiles, the Latest
        collection and Combine's slots; the info pane's strip asks the same maker."""
        return self._moving_previews.of(row)

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

    def go_to_file(self, path: str):
        prompt_id = gallery.generation_of_file(path, self._db.list_generations())
        if prompt_id is not None:
            self.show_generation(prompt_id)

    def show_generation(self, prompt_id: str) -> None:
        if self._fun_time is not None:
            ask_for_origenerator_mode(self._fun_time.dashboard_cmd_file)
        self.follow_link(prompt_id)

    def _go_to_generation(self, prompt_id: str):
        """Go to a generation: open the folder holding it, draw that folder, pick
        the item's own tile in it, and show the item in the info pane.

        The single move under every "take me to this item" — a link, a
        right-click "Go to folder", Back and Forward, a hosted slideshow's lock, an
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
        prompt_id = gallery.landing_for(prompt_id, self._listed_rows, self.image_config_index())
        item = self._folder_row_for(prompt_id)
        if item is not None:
            with self._navigation.off_the_record():
                # Setting a row that is already its half's current one fires no
                # signal, and the pane would go on showing whatever it holds —
                # the collection or the search hits the move was made from. So the
                # drawing is done here in that case rather than waited for.
                drawn_by_the_signal = not self._tree.is_current(item)
                self._tree.setCurrentItem(item)
                if not drawn_by_the_signal:
                    self._on_folder_selected(item, None)
        self._on_thumbnail_clicked(prompt_id)   # the arrival: its tab, and its stop
        revealed = self._browser.reveal_tile(prompt_id)
        logger.info("Went to %s: folder %s, %d items listed, tile shown %s",
                    prompt_id, self.selected_folder_key(),
                    len(self._browser.listed_prompt_ids()), revealed)

    def _folder_row_for(self, prompt_id: str):
        """The tree row of the folder a generation lives in: its settings row, or
        — for one the tree holds no row for, such as a generation that failed
        with no file — the row its settings key names, and for one held in the
        trash, the Trash.

        ``None`` only when the tree has nowhere at all to put it, which is the
        one case a move has no folder to open. Answering ``None`` for anything
        less than that is what left a move opening no folder while the item it
        named went on to fill the info pane, so the click read as having done
        nothing.
        """
        leaf = self._leaf_by_id.get(prompt_id)
        if leaf is not None:
            return leaf
        row = self._db.get_generation(prompt_id)
        if row is None:
            held = self.row_for(prompt_id)
            return self._tree_item_for(oriented_key(_TRASH_KEY, row_orientation(held))) if held else None
        key = self.folder_key_of(row)
        return self._tree_item_for(key) if key else None

    # --- back/forward navigation ------------------------------------------

    def _current_collection_key(self) -> str | None:
        key = self.selected_folder_key()
        return key if folder_collection(_base_of(key)) is not None else None

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


def _side_list(rows, meta, start_frames, side, name_of):
    return gallery.build_gallery_tree(filter_rows(rows, side), meta,
                                      image_index=start_frames, name_of=name_of)


def _custom_folders_by_side(trees, records) -> dict[str, list]:
    return {side: gallery.build_custom_folders(
                tree, [record for record in records
                       if _side_covers(side, record["side"] or _LANDSCAPE)])
            for side, tree in trees.items()}


def _group_workflow(group) -> str | None:
    """The single workflow a folder belongs to, or ``None`` if it spans several
    (All, Images, Videos) and so has no one workflow time to fall back on."""
    if isinstance(group, (gallery.AllGroup, gallery.MediaGroup)):
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
    executing: frozenset = frozenset()  # what ComfyUI is making, while one waits there


def _fetch_poll_facts(client, targets) -> _PollFacts:
    """Every blocking read one poll tick makes of ComfyUI, batched.

    ``targets`` is ``(prompt_id, state)`` per live job at tick time — names and
    strings rather than the job objects, so nothing here touches GUI-owned
    state. /history is pulled for a job whose completion could have been
    missed, the queue position for one still waiting, what ComfyUI is making
    once while any waits there, and the shared queue once for the Job Queue. Each
    read fails soft: a fetch that raises leaves its entry unread rather than
    failing the tick.
    """
    histories, backlogs, executing = {}, {}, frozenset()
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
        if any(state == "queued" for _prompt_id, state in targets):
            try:
                executing = frozenset(client.executing_prompts())
            except Exception as e:
                logger.debug("Could not read what ComfyUI is making: %s", e)
    return _PollFacts(histories, backlogs, _read_foreign_queue(client), executing)


def _confirmed_cancel_all(parent, total: int) -> bool:
    reply = QMessageBox.question(
        parent, CANCEL_ALL_TEXT, cancel_all_question(total),
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
    )
    return reply == QMessageBox.StandardButton.Yes


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


def _fingerprint(rows, meta) -> tuple[int, int]:
    """Cheap hashes of everything the gallery renders, to detect DB changes."""
    return _rows_fingerprint(rows), _folder_meta_fingerprint(meta)


def _rows_fingerprint(rows) -> int:
    return hash(tuple(
        (r.get("prompt_id"), r.get("status"), r.get("thumbnail_path"),
         r.get("workflow_name"), r.get("params_json"), r.get("output_files"))
        for r in rows
    ))


def _folder_meta_fingerprint(meta) -> int:
    return hash(tuple(sorted(
        (k, v.get("custom_name"), v.get("starred")) for k, v in meta.items()
    )))
