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
from origenerator.gallery.shapes import (
    LANDSCAPE as _LANDSCAPE,
)
from origenerator.gallery.shapes import (
    SEPARATE as _SEPARATE,
)
from origenerator.gallery.shapes import (
    TOGETHER as _TOGETHER,
)
from origenerator.gallery.shapes import (
    shape_covers as _shape_covers,
)
from origenerator.gallery.shapes import (
    shape_holding as _shape_holding,
)
from origenerator.gallery_edits import GalleryEdits, GalleryEnvironment
from origenerator.generation_config import (
    filled_params,
    randomize_seeds,
    would_reproduce_a_completed_run,
)
from origenerator.generation_state import GenerationSource
from origenerator.gui import corner_buttons, omnipause
from origenerator.gui.auto_generate_controller import AutoGenerateController
from origenerator.gui.busy_cursor import working
from origenerator.gui.combination import Combination
from origenerator.gui.combine_controller import CombineController
from origenerator.gui.copy_names import copy_names, offer_copy_names
from origenerator.gui.drop_target import DropTarget
from origenerator.gui.enhance_controller import ALREADY_AT_THESE_SETTINGS, EnhanceController, Offer
from origenerator.gui.folder_modify_tile import FolderModifyTile
from origenerator.gui.folder_path import FolderPath
from origenerator.gui.folder_tree import TREE_KEY_ROLE as _TREE_KEY_ROLE
from origenerator.gui.folder_tree import offer_collapse_and_expand
from origenerator.gui.gallery_navigation import NavigationController
from origenerator.gui.gallery_pane import (
    REROLL_VIDEO,
    GalleryPane,
    GalleryPaneScrollArea,
    LeadTiles,
    PaneHost,
    TreeNavigation,
)
from origenerator.gui.gallery_pane_buttons import (
    AUTO_ELSEWHERE_TIP,
    Button,
    ButtonHandlers,
    ButtonStates,
    GalleryPaneButtons,
)
from origenerator.gui.gallery_search import GallerySearchController
from origenerator.gui.gallery_tree import (
    GROUP_ROLE as _GROUP_ROLE,
)
from origenerator.gui.gallery_tree import (
    GalleryTree,
    PathStep,
    ShapeModel,
    path_text,
)
from origenerator.gui.generate_pane import GeneratePane
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
from origenerator.gui.job_queue import JobQueue
from origenerator.gui.job_queue_view import JobQueueView
from origenerator.gui.look_training_controller import LookTrainingController
from origenerator.gui.message import ERROR, HEARD_MARK, INFO
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.new_tile import NewTile
from origenerator.gui.off_thread import run_off_thread
from origenerator.gui.osr2_control import Osr2Control
from origenerator.gui.osr2_controls import Osr2Controls
from origenerator.gui.pane_arrangement import PaneArrangement
from origenerator.gui.panes import FootSplitter, PaneSplitter, hold_the_borders_still, pane
from origenerator.gui.prompt_reveal import reveal_prompt
from origenerator.gui.search_expander import SearchExpander
from origenerator.gui.slideshow_director import SlideshowDirector
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.gui.starting_rows import StartingRows
from origenerator.gui.voice_router import VoiceRouter
from origenerator.item_names import ItemNames
from origenerator.item_shape import (
    base_of as _base_of,
)
from origenerator.item_shape import (
    filter_rows,
    requested_shape,
    row_shape,
    shaped_key,
)
from origenerator.item_shape import (
    shape_of as _shape_of,
)
from origenerator.item_shape import (
    split_key as _split_collection_key,
)
from origenerator.media import MediaType
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
_SEARCH_EXPAND_DELAY_MS = 700
_SEARCH_DELAY_MS = 300
_SEARCH_MIN_CHARS = 3


class _SearchScope(NamedTuple):
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
    if row is None or _shape_of(folder_key) is not None:
        return None
    return next((child for child in (row.child(i) for i in range(row.childCount()))
                 if _base_of(child.data(0, _TREE_KEY_ROLE)) == folder_key), None)


def _folder_of_your_own_above(rows):
    parent = rows[0].parent()
    return _saved_custom_collection(parent.data(0, _GROUP_ROLE)) if parent is not None else None


def _saved_custom_collection(group):
    return group if isinstance(group, gallery.CustomCollection) and group.folder_id is not None else None


def _takes_a_favorite(group) -> bool:
    return group is not None and not isinstance(group, gallery.CustomCollection)


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
    workflow's entire history can never be wiped in one action. A custom collection is
    off-limits too, and for a stronger reason: deleting one must remove the
    grouping, never the generations it gathers, so it has its own path
    (:meth:`GalleryView._remove_custom_collection`) rather than this one.
    """
    return isinstance(
        group,
        (gallery.ModelGroup, gallery.LoraGroup, gallery.SourceImageGroup, gallery.SettingsGroup),
    )


class GalleryView(QWidget):
    run_ended = pyqtSignal(object)

    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryEdits | None = None,
                 osr2_motion: Osr2MotionDriver | None = None,
                 radio: OrigeneratorRadio | None = None,
                 search_expander: SearchExpander | None = None,
                 fun_time: FunTimeSession | None = None,
                 prompt_heights=None):
        super().__init__(parent)
        self._db = db
        self._prompt_heights = prompt_heights
        self._client = client
        self._fun_time = fun_time
        self._radio = radio if radio is not None else OrigeneratorRadio()
        omnipause.holds(self._radio)
        if fun_time is not None:
            self._osr2_motion = None
        else:
            self._osr2_motion = osr2_motion if osr2_motion is not None else Osr2MotionDriver(parent=self)
            omnipause.holds(self._osr2_motion)
        self.osr2_control = Osr2Control(self._osr2_motion, parent=self)
        self._osr2_left_in = None
        self.osr2_control.changed.connect(self.reconcile_osr2)
        self._pace = SlideshowPace(parent=self)
        self._reconciling_osr2 = False
        self._build_the_queue_of_runs(db, client)
        self._edits = actions or GalleryEdits(
            db, OUTPUT_PLACES, Trash(TRASH_DIR),
            environment=GalleryEnvironment(
                release_files=self._release_held_media, thumb_dir=THUMB_DIR,
                cancel_enhancements=lambda rows: self._enhance.cancel_for_delete(rows),
            ),
        )
        self._forget_the_listing()
        self._build_the_panes(db, client, search_expander)
        self._foreign_queue = ForeignQueue(running=[], pending=[])
        self._build_ui()
        self._voice.bind_the_buttons(
            auto=self._buttons.auto, radio=self._buttons.radio,
            drive=self.osr2_control if self._osr2_motion is not None else None,
            mic=self._buttons.mic,
            enhance=(self._buttons.enhance, self._enhance.enhance_the_selection),
            actions={
                AppCommand.BACK: (self._buttons.back, self._navigation.go_back),
                AppCommand.FORWARD: (self._buttons.forward, self._navigation.go_forward),
                AppCommand.CULL: (self._buttons.delete, self._delete_selection),
                AppCommand.FAVORITE: (self._buttons.favorite, self._favorite_selection),
                AppCommand.UNDO: (self._buttons.undo, self._undo),
                AppCommand.REDO: (self._buttons.redo, self._redo),
                AppCommand.GROUP: (self._buttons.group, self._group_selection),
            },
        )
        self._re_aim()
        self._intercept_the_rooms_keys(True)

        self._poll_inflight = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _build_the_queue_of_runs(self, db, client):
        self._jobs = JobQueue(db, client)
        self._jobs.changed.connect(self._rerender_current_leaf)
        self._jobs.changed.connect(self._reconcile_generating)
        self._jobs.changed.connect(lambda: self._enhance.reconcile())
        self._jobs.preview.connect(self._on_reroll_preview)
        self._jobs.finished.connect(self._on_reroll_finished)
        self._jobs.failed.connect(self._on_reroll_failed)
        self._jobs.run_ended.connect(self.run_ended)
        self._generation_failed = GenerationFailed(self)
        self._auto = AutoGenerateController(self._start_auto_reroll)
        self._auto.stopped.connect(self._on_auto_stopped)
        self._auto_generate_settings: dict = {}
        self._auto_origins: set[str] = set()
        self._selected_reroll_key: str | None = None
        self._generating_tile: GeneratingTile | None = None

    def _forget_the_listing(self):
        self._image_rows: list[dict] = []
        self._live_ids: set[str] = set()
        self._listed_rows: list[dict] = []
        self._listed_requests: list[dict] = []
        self._image_index: dict | None = None

    def _build_the_panes(self, db, client, search_expander):
        self._search = GallerySearchController(
            self, parent=self, expander=search_expander)
        self._held_rows: list[dict] = []
        self._selected_row: dict | None = None
        self._item_names = ItemNames(db)
        self._scroll = GalleryPaneScrollArea()
        DropTarget(self._scroll, self._landing_in_the_open_custom_collection, self._on_dropped)
        self._gallery_pane = GalleryPane(
            self._scroll, db, self._jobs, self._auto,
            TreeNavigation(
                selected_folder_key=self.selected_folder_key,
                folder_context=self._folder_context,
                group_for_key=self.group_for_key,
            ),
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
        self._gallery_pane.pane_reset.connect(self._forget_generating_tile)
        self._gallery_pane.thumbnail_activated.connect(self._on_thumbnail_clicked)
        self._gallery_pane.tab_pin_requested.connect(self.pin_generate_tab)
        self._gallery_pane.item_jump_requested.connect(self.follow_link)
        self._gallery_pane.folder_open_requested.connect(self._go_to_folder)
        self._gallery_pane.reveal_reroll_requested.connect(self._reveal_reroll)
        self._gallery_pane.folder_menu_requested.connect(self._folder_context_menu)
        self._gallery_pane.menu_requested.connect(self.generation_menu)
        self._gallery_pane.trash_menu_requested.connect(self._trash_menu)
        self._gallery_pane.item_action_triggered.connect(self.run_item_action)
        self._gallery_pane.seed_reroll_requested.connect(self._reroll_item_seed)
        self._gallery_pane.experiment_verdict.connect(self._on_experiment_verdict)
        self._gallery_pane.trash_action_triggered.connect(self._on_trash_action)
        self._gallery_pane.cancel_requested.connect(self._cancel_job)
        self._gallery_pane.selection_changed.connect(self._re_aim)
        self._fingerprint = (None, None)
        self._folder_meta: dict = {}
        self._drawn_version = 0
        self._pending_key: str | None = None
        self._pending_selection: str | None = None
        self._pending_combine_key: str | None = None
        self._custom_collections: list = []
        self._custom_collections_by_shape: dict[str, list] = {}
        self._lists_built_from = None
        self._lists_by_shape: dict[str, list] = {}
        self._start_frames: dict = {}
        self._selection_group = None
        self._navigation = NavigationController(self, search=self._search)
        self._trail = (False, False)
        self._slideshows = SlideshowDirector(
            self, db=db, gallery_pane=self._gallery_pane, jobs=self._jobs,
            pace=self._pace, motion=self._osr2_motion, fun_time=self._fun_time,
            names=self._item_names, radio=self._radio,
            turn_the_radio_on=lambda: self._buttons.turn_the_radio_on())
        self._starting = StartingRows(self)
        self._starting.changed.connect(self._update_queue)
        self._combine = CombineController(
            self, parent=self, db=db, jobs=self._jobs, client=client,
            info_tabs_of=lambda: self._generate_pane, slideshows=self._slideshows,
            starting=self._starting, names=self._item_names)
        self._enhance = EnhanceController(
            self, db=db, jobs=self._jobs, gallery_pane=self._gallery_pane,
            slideshows=self._slideshows, info_tabs_of=lambda: self._generate_pane)
        self._jobs.enhance_images_with(
            lambda image: self._enhance.enhance_items([image["prompt_id"]]))
        self._look_training = LookTrainingController(
            self._jobs, tabs=lambda: self._generate_pane.generate_tabs(),
            show_tab=lambda tab: self._generate_pane.setCurrentWidget(tab), parent=self)
        self._voice = VoiceRouter(self, parent=self, db=db, slideshows=self._slideshows,
                                  client=client, motion=self._osr2_motion,
                                  starting=self._starting)
        self._folder_history: list[str] = []

    def _intercept_the_rooms_keys(self, intercepting: bool):
        """Take (or hand back) every key the application delivers; Qt installs a filter already on its list once."""
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
            if (event.key() == Qt.Key.Key_F
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and self.isVisible() and not self._other_window_owns_keys()):
                self._open_find()
                return True
            if self._gallery_owns_keys():
                if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Insert):
                    self._delete_selection()
                    return True
                if (event.key() == Qt.Key.Key_C
                        and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    self._copy_names_of_the_selection()
                    return True
                if (event.key() == Qt.Key.Key_Z
                        and event.modifiers() & Qt.KeyboardModifier.ControlModifier):
                    if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                        self._redo()
                    else:
                        self._undo()
                    return True
            if (self._gallery_owns_keys(even_from_the_generate_pane=True)
                    and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
                    and apply_motion_key(self._osr2_motion, event.key(),
                                         on_drive_toggle=self.toggle_osr2_drive)):
                self._osr2_controls.refresh()
                return True
        # An application-wide filter is handed events for objects being destroyed;
        # the base class's answer for one dereferences a freed C++ pointer and aborts.
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
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return True
        active = QApplication.activeWindow()
        return active is not None and active is not self.window()

    def _gallery_owns_keys(self, *, even_from_the_generate_pane: bool = False) -> bool:
        if not self.isVisible() or self._other_window_owns_keys():
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, _TEXT_FIELDS):
            return False
        return even_from_the_generate_pane or not (
            focus is not None and self._generate_pane.isAncestorOf(focus))

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
        gallery_pane = self._build_gallery_pane()
        self._queue = JobQueueView()
        self._queue.move_requested.connect(self._jobs.move)
        self._jobs.reordered.connect(self._update_queue)
        self._queue.clear_queue_requested.connect(self.clear_foreign_queue)
        self._queue.start_now_requested.connect(self.start_now)
        self._queue.cancel_all_requested.connect(self.cancel_all)
        self._arrangement = PaneArrangement(
            toc=toc, gallery_pane=gallery_pane, generate_column=self._build_generate_pane(),
            generate_pane=self._generate_pane, queue=self._queue)
        folded = self._fun_time is not None and not self._fun_time.in_a_headset
        layout.addWidget(self._arrangement.hosted() if folded
                         else self._arrangement.standalone(), 1)
        hold_the_borders_still(self, self._fun_time is not None)

    def _build_toc_pane(self):
        self._tree = SplitFolderTree(_GROUP_ROLE, takes_item=self._custom_collection_takes,
                                     takes_folder=self._collecting_row_takes_folder)
        self._tree.offer_separate_and_together(self._fun_time is None)
        self._tree.shapes_changed.connect(self._on_shapes_changed)
        self._tree_view = GalleryTree(self._tree)
        self._tree.context_menu_requested.connect(self._on_tree_context_menu)
        self._tree.currentItemChanged.connect(self._on_folder_selected)
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        self._tree.favorite_clicked.connect(self._toggle_favorite)
        self._tree.delete_clicked.connect(self._delete_folder_by_key)
        self._tree.dropped.connect(self._on_dropped)
        listening, listening_column = pane()
        listening_column.addWidget(self._voice.status)
        if self._voice.status.isHidden():
            listening.hide()
        self._voice.caption_shown.connect(listening.setVisible)
        finding, toc_column = pane()
        toc_column.addWidget(self._search.field)
        toc_column.addWidget(self._tree, 1)
        combining, combining_column = pane()
        combining_column.addWidget(self._combine.widget)
        if self._combine.widget.isHidden():
            combining.hide()
        sections = [listening, finding, combining]
        self._osr2_controls = None
        self._motion_pane = None
        if self._osr2_motion is not None:
            self._osr2_controls = Osr2Controls(self._osr2_motion, control=self.osr2_control)
            self._osr2_controls.setToolTip(f"{self._osr2_controls.toolTip()} · Esc pauses")
            hud_scroll = QScrollArea()
            hud_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
            hud_scroll.setWidget(self._osr2_controls)
            self._motion_pane, hud_column = pane()
            hud_column.addWidget(hud_scroll)
            sections.insert(0, self._motion_pane)
        toc = PaneSplitter(Qt.Orientation.Vertical, "left_pane_sections")
        for section in sections:
            toc.addWidget(section)
        toc.setStretchFactor(sections.index(finding), 1)
        return toc

    def _build_gallery_pane(self):
        gallery_pane, gallery_column = pane()
        self._folder_path = FolderPath()
        self._folder_path.folder_chosen.connect(self._go_to_folder)
        gallery_column.addWidget(self._folder_path)
        self._buttons = GalleryPaneButtons(
            ButtonHandlers(
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
        gallery_column.addWidget(self._buttons)
        self._experiments_cb = TickControl("Run experiments while the app is closed")
        self._experiments_cb.toggled.connect(self._on_experiments_toggled)
        self._experiments_cb.setEnabled(not is_branch_session())
        self._experiments_status = QLabel("")
        self._experiments_status.setObjectName("estimateLabel")
        self._experiments_bar = QWidget()
        experiments_row = QHBoxLayout(self._experiments_bar)
        experiments_row.setContentsMargins(0, 0, 0, 0)
        experiments_row.addWidget(self._experiments_cb)
        experiments_row.addWidget(self._experiments_status)
        experiments_row.addStretch(1)
        self._experiments_bar.hide()
        self._sync_experiments_bar()
        gallery_column.addWidget(self._experiments_bar)
        gallery_column.addWidget(self._search.bar)
        self._avg_label = QLabel("")
        self._avg_label.setObjectName("estimateLabel")
        self._avg_label.setWordWrap(True)
        gallery_column.addWidget(self._avg_label)
        self._scroll.setWidgetResizable(True)
        self._scroll.background_clicked.connect(
            self._gallery_pane.clear_thumbnail_selection)
        gallery_column.addWidget(self._scroll, 1)
        enhance, enhance_column = pane()
        enhance_column.addWidget(self._enhance.pane)
        browsing = FootSplitter("browser_and_enhance")
        browsing.addWidget(gallery_pane)
        browsing.addWidget(enhance)
        browsing.setStretchFactor(0, 1)
        browsing.setStretchFactor(1, 0)
        return browsing

    def _build_generate_pane(self):
        self._generate_pane = GeneratePane(self._client, self._db, fun_time=self._fun_time,
                                       heights=self._prompt_heights, names=self._item_names,
                                       animated_preview=self.animated_preview)
        self._osr2_driver = Osr2Driver(parent=self) if self._osr2_motion is not None else None
        if self._osr2_driver is not None:
            omnipause.holds(self._osr2_driver)
        self.osr2_control.script = self._osr2_driver
        self._osr2_driving = None
        self._find_bar = FindBar("Find in prompts:", "a word you wrote…",
                                 dismiss_key="Esc", reveal=reveal_prompt)
        self._generate_pane.tab_added.connect(self._wire_generate_tab)
        for tab in self._generate_pane.generate_tabs():
            self._wire_generate_tab(tab)
        self._generate_pane.currentChanged.connect(self._on_front_tab_changed)
        app = QApplication.instance()
        if app is not None:
            if self._osr2_driver is not None:
                app.aboutToQuit.connect(self._osr2_driver.stop)
                app.aboutToQuit.connect(self._osr2_motion.stop)
            app.aboutToQuit.connect(self._radio.stop)
        self._generate_pane.generate_requested.connect(self._on_generate_requested)
        self._generate_pane.modify_requested.connect(self._on_modify_requested)
        self._generate_pane.folder_requested.connect(self._go_to_folder)
        generate_pane = QWidget()
        info_column = QVBoxLayout(generate_pane)
        info_column.setContentsMargins(0, 0, 0, 0)
        info_column.addWidget(self._generate_pane, 1)
        info_column.addWidget(self._find_bar)
        return generate_pane

    def become_hosted(self, session) -> None:
        for switch in (self._buttons.radio, self._buttons.mic):
            if switch is not None:
                switch.setChecked(False)
        self.osr2_control.drive_with(None, None)
        if self._osr2_motion is not None:
            self._osr2_motion.stop()
        self._fun_time = session
        self._tree.offer_separate_and_together(False)
        self._slideshows.become_hosted(session)
        self._generate_pane.become_hosted(session)
        self._voice.become_hosted()
        self._buttons.become_hosted()
        if self._motion_pane is not None:
            self._motion_pane.hide()
        self._kept_device = (self._osr2_motion, self._osr2_driver, self._osr2_controls)
        self._osr2_motion = self._osr2_driver = self._osr2_controls = None
        self.wear_the_room(session)

    def wear_the_room(self, session) -> None:
        folded = self._arrangement.stack is not None
        wants_the_fold = session is not None and not session.in_a_headset
        if wants_the_fold and not folded:
            self._arrangement.fold_into_the_session_column(self.layout())
        elif folded and not wants_the_fold:
            self._arrangement.unfold_from_the_session_column(self.layout())
        hold_the_borders_still(self, session is not None)

    def become_standalone(self) -> None:
        self.set_room_paused(False)
        self._osr2_motion, self._osr2_driver, self._osr2_controls = self._kept_device
        self.osr2_control.drive_with(self._osr2_motion, self._osr2_driver)
        if self._motion_pane is not None:
            self._motion_pane.show()
        self._fun_time = None
        self._tree.offer_separate_and_together(True)
        self._slideshows.become_standalone(self._osr2_motion)
        self._generate_pane.become_standalone()
        self._buttons.become_standalone()
        self._voice.become_standalone(
            self._osr2_motion, radio=self._buttons.radio,
            drive=self.osr2_control if self._osr2_motion is not None else None,
            mic=self._buttons.mic)
        self.wear_the_room(None)

    def _wire_generate_tab(self, tab):
        """Route a Generate tab's footer links to the gallery: its "from source
        image" link and an animation-tile click both navigate like any source link,
        and its preview's corner buttons and right-click menu act on the shown
        generation exactly as a Gallery pane thumbnail's do.
        Its ``displayed_changed`` re-aims the global OSR2 drive at the front video
        and re-reads whether the tab still owns a run in flight, a double-click on
        its preview opens the folder under it as a slideshow standing on it,
        and its Cancel stops the re-roll running in the tab's folder. Called for the
        initial tab and every tab forked afterward."""
        tab.link_clicked.connect(self.follow_link)
        tab.go_to_folder_requested.connect(self.follow_link)
        tab.set_folder_check(self._can_open_containing_folder)
        tab.set_making_one_check(
            lambda config: self._config_folder_key(config) in self._live_jobs)
        tab.item_action_requested.connect(self.run_item_action)
        tab.context_menu_requested.connect(
            lambda prompt_id, pos: self.generation_menu([prompt_id], pos))
        tab.displayed_changed.connect(self.reconcile_osr2)
        tab.displayed_changed.connect(lambda: self._enhance.reconcile())
        tab.displayed_changed.connect(self._reconcile_generating)
        tab.enhance_requested.connect(lambda pid: self._enhance.enhance_items([pid]))
        tab.versions_delete_requested.connect(self.delete_enhance_versions)
        tab.set_enhance_settings(self._enhance.settings)
        tab.set_fullscreen_factory(self._slideshows.open_on_preview)
        tab.cancel_requested.connect(lambda p=tab: self._cancel_tab_reroll(p))
        tab.prompt_fields_changed.connect(self._retarget_find)
        tab.form_edited.connect(self._find_bar.refresh)
        self._look_training.wire(tab)

    def toggle_osr2_drive(self):
        self.osr2_control.setChecked(not self.osr2_control.isChecked())

    def reconcile_osr2(self):
        if self._osr2_driver is None:
            return
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
            if not wants_motion and self._osr2_motion.active:
                self._osr2_motion.stop()
            if target is None:
                if self._osr2_driving is not None:
                    self._osr2_driver.stop()
                    self._osr2_driving = None
            else:
                video_path, player, actions = target
                driving = (video_path, player)
                if self._osr2_driving != driving:
                    self._osr2_driver.start(player, actions)
                    self._osr2_driving = driving
            if wants_motion and not self._osr2_motion.active:
                self._osr2_motion.start()
            self.osr2_control.settled.emit()
        finally:
            self._reconciling_osr2 = False

    def video_in_front(self) -> str | None:
        surface = self._surface_in_front()
        return surface.video_on_screen() if surface is not None else None

    def _surface_in_front(self):
        slideshow = self._slideshows.surface_for(None)
        if slideshow is not None:
            return slideshow
        return self._generate_pane.current_generate_tab()

    def group_for_key(self, key: str):
        item = self._tree_item_for(key)
        return item.data(0, _GROUP_ROLE) if item is not None else None

    def _on_front_tab_changed(self, _index):
        self.reconcile_osr2()
        self._reconcile_generating()
        self._retarget_find()

    def osr2_state(self):
        if not self.osr2_control.isEnabled():
            return self._osr2_left_in
        return self.osr2_control.state()

    def restore_osr2_state(self, saved):
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

    def _on_radio_toggle(self, on: bool):
        if on:
            self._radio.start()
        else:
            self._radio.stop()

    def radio_enabled(self) -> bool:
        return self._buttons.radio is not None and self._buttons.radio.isChecked()

    def set_radio_enabled(self, enabled):
        if self._buttons.radio is not None:
            self._buttons.radio.setChecked(bool(enabled))

    def mic_enabled(self) -> bool:
        return self._buttons.mic is not None and self._buttons.mic.isChecked()

    def set_mic_enabled(self, enabled):
        if self._buttons.mic is not None:
            self._buttons.mic.setChecked(True if enabled is None else bool(enabled))

    def experiments_enabled(self) -> bool:
        return self._experiments_cb.isChecked()

    def set_experiments_enabled(self, enabled):
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
        return gallery.unreviewed_experiments(rows)

    def _sync_experiments_bar(self):
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
        if action_id == "keep":
            self._db.set_experiment_verdict(prompt_id, "up")
        else:
            row = self._db.get_generation(prompt_id)
            if row is not None:
                self._edits.reject_experiment(row)
            self._re_aim()
        self.refresh()

    def folder_key_for(self, workflow_name: str, params: dict,
                        workflow_version: str | None = None) -> str:
        return gallery.folder_key_for(workflow_name, params, self.image_config_index(),
                                      workflow_version)

    def folder_key_of(self, row: dict) -> str:
        return gallery.settings_folder_key(row, self.image_config_index())

    def _config_folder_key(self, config) -> str:
        return self.folder_key_for(config.workflow_name, config.params)

    def _reconcile_generating(self):
        """Point every Generate tab's discard button at the run *it* launched, and
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
        for tab in self._generate_pane.generate_tabs():
            live = [(origin, job) for origin in tab.launched_runs()
                    if (job := self._jobs.job_for_origin(origin)) is not None]
            tab.forget_launched({origin for origin in tab.launched_runs()
                                   if origin not in {o for o, _ in live}})
            job = live[0][1] if live else None
            tab.set_generating(job is not None,
                                 auto_generating=self._auto_generating(job))
            tab.reread_generate_button()
        self._combine.reconcile_generating()

    def _auto_generating(self, job) -> bool:
        key = self._job_folder_key(job)
        return key is not None and self._auto.is_active(key)

    def _job_folder_key(self, job) -> str | None:
        if job is None:
            return None
        return next((k for k, jobs in self._jobs.jobs_by_folder.items()
                     if job in jobs), None)

    def _claim_launch(self, key: str):
        """Give a run launched outside any tab — the folder tile's "+",
        Auto-Generate — to the front Generate tab when that tab is showing the same folder.

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
        tab = self._generate_pane.current_generate_tab()
        job = self._jobs.newest_job_for(key)
        if tab is None or job is None or tab.workflow_and_signature() is None:
            return
        if self._config_folder_key(tab.current_config()) == key:
            tab.note_launched(job.origin)
            self._generate_pane.pin_tab(tab)
            self._reconcile_generating()

    def _cancel_tab_reroll(self, tab):
        for origin in tab.launched_runs():
            job = self._jobs.job_for_origin(origin)
            if job is not None:
                self._cancel_job(job.prompt_id)
                return

    def would_reproduce_a_completed_run(self, workflow, params: dict) -> bool:
        return would_reproduce_a_completed_run(
            self._db.list_generations(), workflow, params)

    def _on_generate_requested(self, workflow_name: str, batch: list[dict]):
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        if self._client is None or wf is None:
            return
        batch = [{**wf.default_params(), **params} for params in batch]
        key = self.folder_key_for(workflow_name, batch[0])
        if key in self._live_jobs:
            return
        launching = self._generate_pane.current_generate_tab()
        if self.would_reproduce_a_completed_run(wf, batch[0]):
            batch[0] = randomize_seeds(batch[0], wf.seed_keys())
            if launching is not None:
                launching.use_random_seed()
        launched = [prompt_id for prompt_id in self._jobs.start_batch(key, wf, batch)
                    if prompt_id]
        if not launched:
            return
        if launching is not None:
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
                launching.note_launched(prompt_id, made_of=None if asked else batch[0])
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
        self._intercept_the_rooms_keys(True)
        self.refresh(only_if_moved=True)

    def hideEvent(self, event):
        super().hideEvent(event)
        if not (event.spontaneous() or self.window().isMinimized()):
            self._poll_timer.stop()

    def closeEvent(self, event):
        """A widget that was never shown is never hidden, so ``hideEvent`` alone leaves the poll and the key filter armed."""
        self._poll_timer.stop()
        self._intercept_the_rooms_keys(False)
        self.close_the_slideshows()
        self._voice.shut_the_mic()
        self._jobs.close()
        super().closeEvent(event)

    def refresh(self, *, only_if_moved: bool = False):
        rows = self._db.list_generations()
        meta = self._db.folder_meta_map()
        fingerprint = _fingerprint(rows, meta)
        moved = fingerprint != self._fingerprint
        self._fingerprint = fingerprint
        if moved or not only_if_moved:
            self._rebuild(rows, meta)
            self._slideshows.library_moved()
        self._slideshows.fill_the_wanted_regions()

    def _poll(self):
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
        try:
            if facts is not None:
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
        try:
            if listing is None:
                return
            rows, meta, requests, fingerprint = listing
            if fingerprint != self._fingerprint and read_at == self._drawn_version:
                self._fingerprint = fingerprint
                self._rebuild(rows, meta)
            else:
                self._gallery_pane.refresh_inflight(rows=rows, requests=requests)
            self._update_queue(self._inflight_items(rows=rows, requests=requests))
            self._enhance.tell_the_slideshows()
            self._refresh_wait_note()
        finally:
            self._poll_inflight = False

    def _apply_poll_facts(self, jobs, facts: _PollFacts):
        for job in jobs:
            job.reconcile_with(facts.histories.get(job.prompt_id))
            job.take_backlog(facts.backlogs.get(job.prompt_id))
            job.take_executing(job.prompt_id in facts.executing)
        if facts.foreign is not None:
            self._foreign_queue = facts.foreign

    def _rebuild(self, rows, meta):
        self._folder_meta = meta
        self._drawn_version += 1
        standing = self._tree_view.selected_folder_key()
        place = self._gallery_pane.place()
        selected_key = standing or self._pending_key
        multi_keys = self._tree.selected_folder_keys()
        if len(multi_keys) <= 1:
            multi_keys = []
        selected_gen = self.selected_generation()
        reroll_key = self._selected_reroll_key
        self._pending_key = None
        self._pending_selection = None
        self._image_rows = [r for r in rows
                            if gallery.media_type_of_row(r) == MediaType.IMAGE]
        self._combine.offer_the_actions(rows)
        self._listed_rows = rows
        trash_collection.settle_regenerations(self._db)
        self._held_rows = trash_collection.trash_items(self._db.list_trashed())
        start_frames, trees = self._lists_for(rows, meta, self._tree.shapes)
        self._image_index = start_frames
        unreviewed = self._review_queue(rows)
        held = self._held_rows
        self._live_ids = {row["prompt_id"] for row in rows}
        self._custom_collections_by_shape = _custom_collections_by_shape(
            trees, self._db.list_custom_collections())
        self._custom_collections = [folder for folders in self._custom_collections_by_shape.values()
                                for folder in folders]
        self._search.index.update(rows + held, gallery.folder_names_by_row(
            [folder for tree in trees.values() for folder in tree], meta,
            self._custom_collections), item_name=self._item_names.of)
        requests = self._listed_requests = self._db.list_requests()
        bumped = gallery.enhancement_recency(rows)
        self._gallery_pane.set_model(
            gallery.recent_generations(rows, bumped=bumped),
            trees,
            rows,
            unreviewed,
            held,
            image_index=start_frames,
        )
        self._tree_view.populate(
            self._build_sides(trees), folder_meta=meta,
            recently_worked=gallery.recently_worked_folders(trees, rows, bumped=bumped),
        )
        self._selection_group = None
        self._selected_row = None
        self._generate_pane.reconcile_previews(self._live_ids)
        self._generate_pane.reread_names()
        self._combine.reread_names()
        target = (self._tree_item_for(selected_key) if selected_key
                  else None) or self._tree_view.default_item()
        with self._navigation.off_the_record():
            if target is not None:
                self._tree.setCurrentItem(target)
                self._reselect_generation(selected_gen)
            else:
                self._folder_path.set_display("")
                self._avg_label.setText("")
                self._gallery_pane.show_empty()
                self._selected_row = None
            self._restore_multi_selection(multi_keys)
            self._restore_reroll_selection(reroll_key)
        self._navigation.seed()
        if self._search.query:
            self._search.run()
        if standing is not None and self._tree_view.selected_folder_key() == standing:
            self._gallery_pane.return_to(place)
        self._update_queue(self._inflight_items(rows=rows, requests=requests))
        self._reconcile_generating()
        for tab in self._generate_pane.generate_tabs():
            tab.refresh_generate_caption()

    def _lists_for(self, rows, meta, shapes):
        library = _fingerprint(rows, meta)
        if library != self._lists_built_from:
            self._lists_built_from = library
            self._start_frames = gallery.start_frame_index(rows)
            self._item_names.take(rows, self._held_rows, self._start_frames)
            self._lists_by_shape = {}
        for shape in shapes:
            if shape not in self._lists_by_shape:
                self._lists_by_shape[shape] = _side_list(
                    rows, meta, self._start_frames, shape, self._item_names.of)
        return self._start_frames, {shape: self._lists_by_shape[shape] for shape in shapes}

    def _build_sides(self, trees):
        """The shapes the pane is drawing, in the order it draws them.

        A shape is the whole tree of contents over the rows it holds: its own
        hierarchy, its own copies of the folders the user composed, and collections
        whose counts are its own — a number covering more than the shape draws
        would send you to a collection that then showed you nothing.

        Only the drawn shapes are built. The radio's other answer is a section
        nobody can see, and filling it would cost every rebuild a table of
        contents for nothing.
        """
        return [ShapeModel(
            shape=shape,
            tree_model=trees[shape],
            custom_collections=gallery.outermost(self._custom_collections_by_shape[shape]),
            show_latest=bool(trees[shape]),
            collection_counts=self._gallery_pane.collection_counts(shape),
        ) for shape in self._tree.shapes]

    def open_folders(self) -> list[str]:
        return sorted(self._tree_view.folders_left_open())

    def set_open_folders(self, saved) -> None:
        if isinstance(saved, list):
            self._tree_view.leave_folders_open(key for key in saved if isinstance(key, str))

    def toc_shapes(self) -> list[str]:
        return list(self._tree.chosen_sides)

    def set_toc_sides(self, saved) -> None:
        self._tree.choose_shapes(_TOGETHER if saved == list(_TOGETHER) else _SEPARATE)

    def _on_shapes_changed(self):
        if not self._tree_view.built:
            return
        with working():
            self.refresh()
        self._re_aim()

    def _reselect_generation(self, prompt_id: str | None):
        if not prompt_id or prompt_id not in self._gallery_pane.listed_prompt_ids():
            return
        row = self.row_for(prompt_id)
        if row:
            self._select_saved_generation(row)

    def _open_find(self):
        fields = self._prompt_fields()
        if not fields:
            self._search.focus_field()
            return
        self._find_bar.open_find(fields)

    def _prompt_fields(self) -> list:
        tab = self._generate_pane.current_generate_tab()
        return tab.prompt_fields() if tab is not None else []

    def _retarget_find(self):
        typing = QApplication.focusWidget()
        caret = typing.textCursor() if isinstance(typing, QPlainTextEdit) else None
        self._find_bar.retarget(self._prompt_fields())
        if caret is not None:
            typing.setTextCursor(caret)


    def image_config_index(self) -> dict:
        if self._image_index is None:
            self._image_index = gallery.build_image_config_index(self._image_rows)
        return self._image_index

    def name_search_on_screen(self, query: str, scope: _SearchScope) -> None:
        self._folder_path.show_search(f"Search: “{query}” in ", scope.steps)
        self._avg_label.setText("")
        self._experiments_bar.hide()

    def show_search_results(self, tiles, **terms) -> None:
        self._gallery_pane.show_search_results(tiles, **terms)

    def search_results_drawn(self) -> None:
        self._re_aim()
        self._navigation.record()

    def suppress_history(self):
        return self._navigation.off_the_record()

    def selected_prompt_id(self) -> str | None:
        return self._selected["prompt_id"] if self._selected else None

    def pane_holds(self, prompt_id: str) -> bool:
        return prompt_id in self._gallery_pane.listed_prompt_ids()

    def show_folder(self, key: str) -> bool:
        row = self._tree_item_for(key)
        if row is None:
            return False
        if self._tree.currentItem() is row:
            self._on_folder_selected(row, None)
        else:
            self._tree.setCurrentItem(row)
        return True

    def reveal(self, prompt_id: str) -> bool:
        if self._gallery_pane.reveal_tile(prompt_id):
            self._on_thumbnail_clicked(prompt_id)
            return True
        row = self._db.get_generation(prompt_id)
        return row is not None and self._gallery_pane.reveal_folder(
            gallery.settings_folder_key(row, self.image_config_index()))

    def clear_selection(self) -> None:
        self._clear_metadata()

    def nav_state_changed(self, can_go_back: bool, can_go_forward: bool) -> None:
        self._trail = (can_go_back, can_go_forward)
        self._re_aim()

    def hand_pane_back(self) -> None:
        self._on_folder_selected(self._tree.currentItem(), None)

    def search_scope(self) -> _SearchScope:
        item = self._tree.currentItem()
        if self._current_collection_key() is not None:
            rows = self._gallery_pane.selected_collection_rows() or []
            return _SearchScope(tuple(self._tree_view.path_steps(item)),
                                {row["prompt_id"] for row in rows})
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if group is None:
            return _SearchScope((PathStep(gallery.ALL_LABEL, None),), self._live_ids)
        return _SearchScope(tuple(self._tree_view.path_steps(item)),
                            {row["prompt_id"] for row in gallery.rows_under(group)})

    def search_sort(self) -> str:
        return self._search.sort()

    def set_search_sort(self, mode: str | None):
        self._search.set_sort(mode)

    def remembered_slideshows(self) -> dict:
        return self._slideshows.remembered()

    def slideshow_showing_on(self) -> str | None:
        return self._slideshows.slideshow_showing_on()

    def remember_slideshows(self, saved) -> None:
        if self._fun_time is None:
            self._slideshows.remember(saved)

    def how_many(self) -> int:
        return self._generate_pane.how_many()

    def set_how_many(self, count) -> None:
        self._generate_pane.set_how_many(count if count in HOW_MANY else HOW_MANY[0])

    def _showing_search(self) -> bool:
        return self._gallery_pane.showing_search()

    def _on_folder_selected(self, current, _previous):
        if self._selection_group is not None:
            return
        self._search.sync_placeholder()
        if self._search.query and not self._navigation.suppressed:
            self._search.run()
            return
        self._re_aim()
        base, shape = _split_collection_key(self._tree_view.selected_folder_key())
        collection = folder_collection(base)
        self._experiments_bar.setVisible(collection is not None
                                         and collection.which == _EXPERIMENTS_KEY)
        if current is None:
            self._folder_path.set_display("")
            self._avg_label.setText("")
            self._gallery_pane.show_empty()
            self._re_aim()
            return
        if collection is not None:
            self._open_collection(collection, shape, current)
            return
        group = current.data(0, _GROUP_ROLE)
        here = self._tree_view.selected_folder_key()
        self._note_folder_visit(here if group is not None else None)
        self._folder_path.show_folder(self._tree_view.path_steps(current))
        self._update_folder_average(group)
        self._show_group_contents(group, current)
        landed = self._land_on_the_first_item()
        if group is not None:
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
        first = next(iter(self._gallery_pane.listed_prompt_ids()), None)
        if first is None or not self._show_generation(first):
            return None
        self._gallery_pane.apply_selection(first, Qt.KeyboardModifier.NoModifier)
        return first

    def _open_collection(self, collection: FolderCollection, shape: str | None, item):
        if collection.which == _EXPERIMENTS_KEY:
            self._sync_experiments_bar()
        self._folder_path.show_folder(self._tree_view.path_steps(item),
                                      mark=_PATH_MARK_OF.get(collection.which, ""))
        self._avg_label.setText("")
        self._clear_metadata()
        self._gallery_pane.show_collection(collection.key, shape)
        self._navigation.record()

    def _show_group_contents(self, group, item):
        if isinstance(group, gallery.SettingsGroup):
            self._gallery_pane.show_thumbnails(group)
        elif isinstance(group, gallery.CustomCollection):
            self._gallery_pane.show_custom_collection(group)
        else:
            self._gallery_pane.show_folder_tiles(gallery.child_groups(group),
                                            collections=self._tree_view.collections_in(item))

    def _go_to_folder(self, key: str):
        """Go to a folder: select its tree row, which draws it.

        The one move under every gesture that names a folder to open — a folder
        tile's click, a Generate tab's "Go to folder", a step of the path — as
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

    def _on_tree_selection_changed(self):
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
        return [group for key in self._tree.selected_folder_keys()
                if (group := self.group_for_key(key)) is not None]

    def _show_selection(self):
        group = self._selection_group
        self._experiments_bar.hide()
        self._folder_path.set_display(group.label)
        self._update_folder_average(group)
        self._gallery_pane.show_custom_collection(group)
        self._re_aim()

    def _restore_multi_selection(self, keys: list[str]):
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
        group = self._selection_group
        if group is None:
            return
        folders = gallery.child_groups(group)
        name, ok = QInputDialog.getText(
            self, "New Collection",
            f"Name for a collection holding these {len(folders)} folders:",
        )
        if not ok or not name.strip():
            return
        folder_id = self._edits.custom_collections.create(
            name.strip(), [self._folder_identity(f) for f in folders], self.shape_in_view()
        )
        self._open_custom_collection(folder_id)

    def _folder_identity(self, group) -> tuple:
        rows = gallery.rows_under(group)
        return (group.key, gallery.group_level(group),
                rows[0]["prompt_id"] if rows else None)

    def _open_custom_collection(self, folder_id: int):
        self._tree.clearSelection()
        self._selection_group = None
        self.refresh()
        self._re_aim()
        item = self._tree_item_for(gallery.custom_collection_key(folder_id))
        if item is not None:
            self._tree.setCurrentItem(item)

    def _on_dropped(self, target_key: str, keys: list, prompt_ids: list = ()):
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
        self._edits.custom_collections.add_to(
            folder_id, [self._folder_identity(g) for g in groups], prompt_ids
        )
        self._open_custom_collection(folder_id)

    def _custom_collection_takes(self, row_key: str, prompt_id: str) -> bool:
        folder = self.group_for_key(row_key)
        leaf = self._leaf_by_id.get(prompt_id)
        return (isinstance(folder, gallery.CustomCollection) and leaf is not None
                and _shape_of(leaf.data(0, _TREE_KEY_ROLE)) == _shape_of(row_key))

    def _collecting_row_takes_folder(self, row_key: str, folder_key: str) -> bool:
        target, dragged = self.group_for_key(row_key), self.group_for_key(folder_key)
        if dragged is None:
            return False
        if isinstance(target, gallery.CustomCollection):
            return not gallery.holds(dragged, target)
        return _takes_a_favorite(dragged)

    def _landing_in_the_open_custom_collection(self, mime, source):
        if _saved_custom_collection(self.current_group()) is None:
            return None
        return self._tree.landing_on(self._tree.currentItem(), mime, source)

    def _new_custom_collection(self, shape: str):
        name, ok = QInputDialog.getText(self, "New Collection", "Collection name:")
        if ok and name.strip():
            self._open_custom_collection(
                self._edits.custom_collections.create(name.strip(), [], shape))

    def _remove_custom_collection(self, group):
        if not self._confirm(f"Remove the folder “{group.label}”?\n\n{_kept_on_removal(group)}"):
            return
        self._edits.custom_collections.delete(group.folder_id)
        self._tree.clearSelection()
        self._selection_group = None
        self.refresh()
        self._re_aim()

    def _remove_from_custom_collection(self, group, folder_keys=(), items=()):
        folders = [self._folder_identity(gathered)
                   if (gathered := self.group_for_key(key)) is not None else (key, None, None)
                   for key in folder_keys]
        self._edits.custom_collections.remove_from(group.folder_id, folders, items)
        self.refresh()
        self._re_aim()

    def _note_folder_visit(self, key: str | None):
        if self._navigation.suppressed or key is None:
            return
        if not self._folder_history or self._folder_history[-1] != key:
            self._folder_history.append(key)

    def _update_folder_average(self, group):
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

    def _can_reroll(self, group) -> bool:
        if self._client is None or not group.rows:
            return False
        return gallery.rerollable(group.rows[0])

    @property
    def _live_jobs(self) -> dict:
        return self._jobs.jobs

    @property
    def _selected(self) -> dict | None:
        return self._selected_row

    @property
    def _item_by_key(self) -> dict:
        return self._tree_view.item_by_key

    @property
    def _leaf_by_id(self) -> dict:
        return self._tree_view.leaf_by_id

    def selected_folder_key(self) -> str | None:
        return self._tree_view.selected_folder_key()

    def shape_in_view(self) -> str:
        return (_shape_of(self.selected_folder_key())
                or _shape_holding(_LANDSCAPE, self._tree.shapes))

    def _tree_item_for(self, key: str):
        item = self._item_by_key.get(key)
        if item is not None:
            return item
        folder = _base_of(key)
        drawn = self._tree_view.keys_for_folder(folder)
        if _shape_of(key) in self._tree.shapes:
            return next((self._item_by_key[row] for row in drawn
                         if _shape_of(row) == _shape_of(key)), None)
        if not drawn:
            return None
        here = shaped_key(folder, self.shape_in_view())
        return self._item_by_key[here if here in drawn else drawn[0]]

    def _collection_item(self, collection_key: str, shape: str | None = None):
        return self._tree_view.collection_item(collection_key, shape or self.shape_in_view())

    def _folder_context(self, key: str) -> str:
        item = self._tree_item_for(key)
        if item is None or item.parent() is None:
            return ""
        return self._tree_view.folder_path(item.parent())

    def current_group(self):
        if self._selection_group is not None:
            return self._selection_group
        if self._showing_search():
            return None
        item = self._tree.currentItem()
        return item.data(0, _GROUP_ROLE) if item else None

    def _lead_tiles(self, group) -> LeadTiles:
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

    def _can_modify(self, group) -> bool:
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
        :meth:`GenerateTab.open_folder_modify`.
        """
        rows = self._folder_modify_rows(group)
        workflow = WORKFLOW_REGISTRY.get(rows[0].get("workflow_name") or "") if rows else None
        if workflow is None or self._client is None:
            return
        thumbnails = [row.get("thumbnail_path") for row in rows]
        self._clear_reroll_selection()
        self._generate_pane.open_folder_modify(group.key, group.label, workflow.name,
                                      filled_params(rows[0], workflow), thumbnails)

    def _on_modify_requested(self, folder_key: str, workflow_name: str, params: dict):
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        item = self._tree_item_for(folder_key)
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        rows = self._folder_modify_rows(group) if group is not None else []
        if self._client is None or wf is None or not rows:
            return
        params = {**wf.default_params(), **params}
        key = self.folder_key_for(workflow_name, params)
        launching = self._generate_pane.current_generate_tab()
        seed_keys = wf.seed_keys()
        olds = [(row, filled_params(row, wf)) for row in reversed(rows)]
        batch = [{**params, **{k: was[k] for k in seed_keys if k in was}} for _, was in olds]
        launched = 0
        for (row, was), run, prompt_id in zip(olds, batch,
                                              self._jobs.start_batch(key, wf, batch), strict=True):
            if not prompt_id:
                continue
            launched += 1
            if launching is not None:
                launching.note_launched(prompt_id, made_of=params)
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
        that video — a still on the folder's tile, a loop in a Generate tab.

        The video only where a *video* was dropped: an action picked off the Combine
        dropdown names what the run will do rather than a video, and a thumbnail of
        some video the user never chose reads as a job that is that video — the
        same reason the queue's rows leave it out (see GalleryPane).
        """
        row = self._db.get_generation(job.prompt_id) if job is not None else None
        source_video = (None if row is None or row.get("action")
                        else self._db.get_generation(row.get("source_video") or ""))
        return Combination(
            self._job_source_image(job),
            source_video_media(source_video) if source_video is not None else None,
            source_video is not None
            and gallery.prompts_differ_from(job.params, source_video, job.workflow))

    def typical_run_seconds(self, job) -> float | None:
        if job is None:
            return None
        return timing.estimate_seconds(self._db.recent_durations(job.workflow.name))

    def _start_auto_reroll(self, key: str) -> bool:
        """Auto-Generate's own launch: the variation the tile's "+" would start,
        except that nothing about it reaches a Generate tab.

        Auto-Generate is left running while the user works, so what it is making is not
        what they are looking at. Its frames used to fill the Generate pane — that is,
        the preview of whichever tab was open, over the item the user had put
        there — and its results landed in a tab too. Both belong to the folder's
        own live tile in the middle column, which streams the run whether or not
        the pane is pointed at it.
        """
        return self._start_reroll(key, from_auto=True)

    def _start_reroll(self, key: str, *, from_auto: bool = False) -> bool:
        if self._client is None:
            return False
        if key in self._live_jobs:
            return True
        settings = self._auto_generate_settings.get(key)
        if settings is not None:
            workflow, params = settings
            self._jobs.start_prepared(key, workflow,
                                      randomize_seeds(params, workflow.seed_keys()))
        else:
            self._jobs.start_reroll(key, self.group_for_key(key), self._image_rows)
        self._claim_launch(key)
        if not from_auto:
            self._select_reroll(key)
        else:
            self._note_auto_launch(key)
            if self._selected_reroll_key == key:
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
            return
        self._auto_origins = {origin for origin in self._auto_origins
                              if self._jobs.job_for_origin(origin) is not None}
        self._auto_origins.add(job.origin)

    def _toggle_auto(self, checked: bool):
        group = self.current_group()
        if not checked:
            self._auto.stop_all()
        elif group is not None:
            self._begin_auto(group.key)
        self._re_aim()
        self._sync_cancel_buttons()

    def _begin_auto(self, key: str):
        self._capture_auto_generate_settings(key)
        self._auto.start(key)
        if self._auto.is_active(key):
            self._set_folder_favorite(key, True)
        else:
            self._auto_generate_settings.pop(key, None)

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
        self._auto_generate_settings.pop(key, None)
        if key == self._selected_reroll_key and key not in self._live_jobs:
            self._clear_reroll_selection()
        self._re_aim()
        self._sync_cancel_buttons()

    def _sync_cancel_buttons(self):
        """Re-word the hover of every Cancel that throws a run away — the
        folder's live tile, the Job Queue's rows, each Generate tab's — after
        Auto-Generate started or ended.

        Nothing else repaints them at that moment: switching Auto on over a folder
        that is already generating launches nothing, so there is no re-roll change
        to ride, and the hover would keep promising a stop that the press no
        longer performs (or a next seed after Auto-Generate is off).
        """
        self._rerender_current_leaf()
        self._update_queue()
        self._reconcile_generating()

    def say(self, message: str, *, mark: str = HEARD_MARK) -> None:
        self._voice.say(message, mark=mark)

    def collection_label(self, key: str) -> str:
        return COLLECTION_LABELS[key]

    def stand_in_collection(self, key: str, shape: str | None) -> bool:
        item = self._tree_item_for(shaped_key(key, shape) if shape else key)
        if item is None:
            return False
        self._tree.setCurrentItem(item)
        return True

    def run_spoken_command(self, text: str, said_at: float | None = None) -> bool:
        return self._voice.run_spoken_command(text, said_at)

    def taking_a_request(self) -> bool:
        return self._voice.listener.taking_a_request

    def drop_the_request(self) -> None:
        self._voice.drop_the_request()

    def _go_to_auto_generating_folder(self, _href: str):
        key = self._auto.active_key()
        if key is not None:
            self._stand_on_the_run_in(key, rebuild=True)

    def rows_to_play(self) -> list[dict]:
        """The generations the slideshow would play from the view on screen: the
        collection's own rows in a collection, else everything under the selected
        folder.  All of it: narrowing a slideshow to its favorites or its enhanced
        images is the slideshow's own doing, from the two switches on its HUD.
        """
        rows = [] if self._in_the_trash() else self._gallery_pane.collection_rows()
        if rows is None:
            group = self.current_group()
            rows = gallery.rows_under(group) if group is not None else []
        return rows

    def slideshow_subject(self) -> str:
        if self._showing_search():
            return "these results"
        if self._current_collection_key() is not None:
            return self._tree_view.folder_path(self._tree.currentItem())
        return "this folder"

    def _re_aim(self) -> None:
        enhance = self._enhance.offer()
        self._buttons.apply(self.button_states(enhance))
        self._enhance.sync_pane(enhance)
        self._generate_pane.reread_folder_buttons()
        self._tree.offer_delete_on_picked_rows(
            self._selection_group is None or bool(self._current_deletable_folders()))

    def button_states(self, enhance: Offer) -> ButtonStates:
        """How the Gallery pane buttons stand right now, gathered from the seams the buttons
        belong to: the trail, the undo stack, the tree's selection, the items
        picked, the enhance settings, the slideshows, and Auto-Generate.

        Assembled here because here is where those meet. Everything it reads is
        a question already asked by name, so the record can be written by hand in
        a test and the buttons written from it with no gallery at all.
        """
        can_go_back, can_go_forward = self._trail
        undo_label = self._edits.undo_label()
        redo_label = self._edits.redo_label()
        auto_generate_folder = self._auto.active_key()
        group = self.current_group()
        can_auto_generate = (isinstance(group, gallery.SettingsGroup)
                             and self._can_reroll(group))
        elsewhere = (auto_generate_folder is not None
                     and auto_generate_folder != getattr(group, "key", None))
        return ButtonStates(
            back=Button(enabled=can_go_back, tip="Back"),
            forward=Button(enabled=can_go_forward, tip="Forward"),
            undo=Button(enabled=self._edits.can_undo(),
                        tip=f"Undo: {undo_label}" if undo_label else "Nothing to undo"),
            redo=Button(enabled=self._edits.can_redo(),
                        tip=f"Redo: {redo_label}" if redo_label else "Nothing to redo"),
            group=Button(visible=self._selection_group is not None,
                         tip="Group the selected folders into a collection of your own"),
            favorite=self._favorite_offer(),
            enhance=Button(enabled=enhance.available, tip=enhance.tip),
            delete=self._delete_offer(),
            slideshow=(Button(enabled=False, tip="Trash doesn't play as a slideshow")
                       if self._in_the_trash()
                       else Button(visible=self._slideshows.anything_to_play(),
                                   tip=f"Play {self.slideshow_subject()} as a slideshow")),
            auto=Button(enabled=can_auto_generate or auto_generate_folder is not None,
                        tip="" if elsewhere else self._auto_tip(can_auto_generate,
                                                                auto_generate_folder),
                        checked=auto_generate_folder is not None),
            auto_tip=AUTO_ELSEWHERE_TIP if elsewhere else "",
        )

    @staticmethod
    def _auto_tip(can_auto_generate: bool, auto_generate_folder: str | None) -> str:
        if auto_generate_folder is not None:
            return "Auto-generate is running in this folder — click to stop it"
        return (
            "Auto-generate: repeatedly generate variations of this folder "
            "until toggled off"
            if can_auto_generate else
            "Auto-generate: open a settings folder to generate variations of it"
        )

    def _favorite_offer(self) -> Button:
        pids = self.selected_prompt_ids() if self._gallery_pane.selected_ids else []
        if pids and not self._in_the_trash():
            favoriting = not self._all_favorites(pids)
            return Button(tip=f"{'Favorite' if favoriting else 'Unfavorite'} {len(pids)} "
                              f"item{'s' if len(pids) != 1 else ''}")
        group = None if pids else self._favoritable_folder()
        if group is None:
            return Button(enabled=False, tip="Nothing here to favorite")
        return Button(tip=f"{'Unfavorite' if group.favorite else 'Favorite'} "
                          f"folder “{group.label}”")

    def _delete_offer(self) -> Button:
        count = len(self._gallery_pane.selected_ids)
        if self._in_the_trash():
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
        if self._selection_group is not None:
            return None
        return self.current_group()

    def _all_favorites(self, prompt_ids) -> bool:
        rows = [self._db.get_generation(pid) for pid in prompt_ids]
        return all(row and row.get("starred") for row in rows)

    def _favorite_selection(self):
        """The Gallery pane button's action: favorite the picked thumbnails, or the
        folder on screen — and un-favorite them when they already are, so the one
        button is the whole of the toggle."""
        if self._gallery_pane.selected_ids and not self._in_the_trash():
            pids = self.selected_prompt_ids()
            self.set_items_favorite(pids, not self._all_favorites(pids))
            return
        group = self._favoritable_folder()
        if group is not None:
            self._toggle_favorite(group.key)

    def close_the_slideshows(self) -> None:
        self._slideshows.close_the_slideshows()

    def fill_the_region(self, shape: str) -> None:
        self._slideshows.fill_the_region(shape)

    def close_the_slideshow(self, shape: str) -> None:
        self._slideshows.close_the_slideshow(shape)

    def queue_request(self, row, workflow, params, spoken, revision) -> tuple[str, str]:
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
        self.refresh()
        return "Request submitted", INFO

    def delete_enhance_versions(self, prompt_id: str, filenames: list):
        row = self._db.get_generation(prompt_id)
        if row is None or not self._edits.delete_enhance_versions(row, filenames):
            return
        self._re_aim()
        self.refresh()
        updated = self._db.get_generation(prompt_id)
        if updated is not None:
            self._generate_pane.refresh_displayed(updated, self._image_rows)
        self._re_aim()

    def slideshow_location(self):
        collection = self._current_collection_key()
        if collection is not None:
            return collection
        return (self.selected_folder_key()
                if self.current_group() is not None else None)

    def set_room_paused(self, paused: bool) -> None:
        if paused != omnipause.frozen():
            logger.info("The room is %s", "paused" if paused else "playing")
        self._slideshows.set_room_paused(paused)
        omnipause.freeze(paused)

    def hud_place(self, shape: str) -> tuple:
        return self._slideshows.hud_place(shape)

    def tell_the_hud(self, shape: str, action: str, argument: str) -> None:
        self._slideshows.tell_the_hud(shape, action, argument)

    def region_slideshow(self, shape: str):
        return self._slideshows.region_slideshow(shape)

    def favorite_generation(self, prompt_id: str, favorite: bool = True):
        self.set_items_favorite([prompt_id], favorite)

    def trash_generation(self, prompt_id: str):
        row = self._db.get_generation(prompt_id)
        if row is None:
            return
        if gallery.unreviewed_experiments([row]):
            self._edits.reject_experiment(row)
            self._re_aim()
        else:
            self._edits.delete_rows([row])

    def _reroll_item_seed(self, prompt_id: str, which: str):
        if self._client is None:
            return
        row = self._db.get_generation(prompt_id)
        if row is None:
            return
        key = self.folder_key_of(row)
        if key in self._live_jobs:
            return
        if which == REROLL_VIDEO:
            self._jobs.reroll_video_seed(key, row)
        else:
            self._jobs.reroll_image_seed(key, row, self._image_rows)
        self._select_reroll(key)

    def off_thread(self, work, done):
        run_off_thread(work, done, owner=self)

    def enhance_offer_changed(self) -> None:
        self._re_aim()

    def enhance_settings(self) -> str:
        return self._enhance.settings_json()

    def set_enhance_settings(self, raw: str | None) -> None:
        self._enhance.restore_settings(raw)

    def enhance_items(self, prompt_ids: list[str]) -> None:
        self._enhance.enhance_items(prompt_ids)

    def enhance_from_slideshow(self, prompt_id: str) -> bool:
        return self._enhance.enhance_from_slideshow(prompt_id)

    def enhance_it(self, prompt_id: str | None) -> tuple[str | None, str, str]:
        return self._enhance.enhance_it(prompt_id)

    def fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str, str]:
        return self._enhance.fix_parts(prompt_id, parts)

    def image_rows(self) -> list[dict]:
        return self._image_rows

    def tell(self, title: str, message: str) -> None:
        QMessageBox.information(self, title, message)

    def combine_selection(self) -> dict:
        return self._combine.selection()

    def restore_combine_selection(self, saved) -> None:
        self._combine.restore(saved)

    def animate_it(self, image_id: str | None,
                   asked) -> tuple[str | None, str, str]:
        return self._combine.animate_it(image_id, asked)

    def reveal_launch(self, key: str):
        if self._stand_on_the_run_in(key):
            return
        if (latest := self._collection_item(_LATEST_KEY, self._launched_side(key))) is not None:
            self._pending_combine_key = key
            self._tree.setCurrentItem(latest)

    def _launched_side(self, key: str) -> str:
        job = self._jobs.job_for(key)
        asked = requested_shape(job.params) if job is not None else None
        return _shape_holding(asked, self._tree.shapes) or self.shape_in_view()

    def _reveal_reroll(self, key: str):
        self._search.leave()
        if not (self._stand_on_the_run_in(key)
                or self._stand_on_the_run_in(key, rebuild=True)):
            logger.info("Nothing to reveal for %s: no folder row", key)

    def _select_reroll(self, key: str):
        job = self._live_jobs.get(key)
        if job is None:
            return
        self._enter_reroll_selection(key)
        tabs = self._generate_pane
        tab = tabs.tab_watching(key) or tabs.tab_that_launched(job.origin)
        if tab is None:
            front = tabs.current_generate_tab()
            if (front is not None and front.workflow_and_signature() is not None
                    and self._config_folder_key(front.current_config()) == key):
                tab = front
            else:
                tab = tabs.landing_tab()
                row = self._db.get_generation(job.prompt_id)
                if row is not None:
                    tab.show_running_generation(row)
            if job.origin not in tab.launched_runs():
                tab.note_launched(job.origin)
            tabs.pin_tab(tab)
            self._reconcile_generating()
        tab.watch_folder(key, job.last_preview, self._wait_note(key),
                           self._job_made_from(job, self.animated_preview))
        tabs.setCurrentWidget(tab)

    def _restore_reroll_selection(self, key: str | None):
        """After a rebuild, re-assert a still-running re-roll as the selected
        item — its tile lit again in the folder now on screen. The tabs following
        the run kept their frames across the rebuild (an i2v's image frame while
        the video stage warms up included); the tile is the one thing redrawn.
        A no-op unless that re-roll is still running in the folder on screen.
        """
        if (key is None or key not in self._live_jobs
                or getattr(self.current_group(), "key", None) != key):
            return
        self._enter_reroll_selection(key)

    def _enter_reroll_selection(self, key: str):
        self._selected_reroll_key = key
        self._selected_row = None
        self._gallery_pane.clear_thumbnail_selection()
        if self._generating_tile is not None:
            self._generating_tile.set_selected(True)

    def _wait_note(self, key: str) -> str | None:
        job = self._live_jobs.get(key)
        if job is None:
            return None
        return queue_wait_text(job.foreign_ahead, self._jobs.starts_at(job.prompt_id))

    def _refresh_wait_note(self):
        for tab in self._generate_pane.generate_tabs():
            key = tab.watched_key()
            if key is not None and tab.is_awaiting_frame():
                tab.show_live_wait(self._wait_note(key))

    def _on_reroll_preview(self, key: str, prompt_id: str, data: bytes):
        for tab in self._generate_pane.watchers_of(key):
            tab.show_live_frame(data)
        self._enhance.reconcile()
        self._slideshows.note_generating(prompt_id, data)

    def _clear_reroll_selection(self):
        self._selected_reroll_key = None
        if self._generating_tile is not None:
            self._generating_tile.set_selected(False)

    def reconnect_running_jobs(self):
        self._enhance.take_up_trainings()
        self._look_training.take_up_trainings()
        self._jobs.reconnect_running()

    def _cancel_reroll(self, key: str):
        self._jobs.cancel(key)
        self._auto.note_canceled(key)
        self._after_a_job_ended_unfinished(key)

    def _cancel_job(self, prompt_id: str):
        key = self._job_folder_key(self._jobs.job_for_prompt(prompt_id))
        self._jobs.cancel_job(prompt_id)
        if key is not None:
            self._auto.note_canceled(key)
            self._after_a_job_ended_unfinished(key)

    def _after_a_job_ended_unfinished(self, key: str):
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()
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
            for tab in self._generate_pane.watchers_of(key):
                tab.stop_watching()

    def _on_reroll_finished(self, key: str, prompt_id: str, origin: str = ""):
        run = origin or prompt_id
        launcher = (None if run in self._auto_origins
                    else self._generate_pane.tab_that_launched(run))
        self._auto_origins.discard(run)
        finished_row = self._db.get_generation(prompt_id)
        if (finished_row is not None
                and finished_row.get("source") == GenerationSource.EXPERIMENT):
            self.refresh()
            return
        folded = False
        if finished_row is not None \
                and finished_row.get("workflow_name") == gallery.ENHANCE_WORKFLOW:
            source_id = gallery.fold_enhancement(self._db, finished_row)
            if source_id is not None:
                folded = True
                finished_row = self._db.get_generation(source_id)
                self._slideshows.note_enhanced(finished_row)
        self._combine.send_to_genau_if_requested(finished_row)
        if key == self._selected_reroll_key and not self._auto.is_active(key):
            self._clear_reroll_selection()
        self._slideshows.note_landed(finished_row)
        self.refresh()
        self._slideshows.note_finished(finished_row)
        self._show_reroll_result_in_tab(finished_row, launcher)
        if folded:
            self._generate_pane.refresh_displayed(finished_row, self._image_rows)
        self._show_landed_to_watchers(key, finished_row, launcher)
        if key == self._pending_combine_key:
            self._pending_combine_key = None
            item = self._tree_item_for(key)
            if item is not None:
                self._tree.setCurrentItem(item)
        self._enhance.forget(prompt_id)
        self._reconcile_generating()
        self._auto.note_finished(key)
        self._enhance.enhance_when_wanted(finished_row)
        self._re_aim()
        self._enhance.reconcile()

    def _show_reroll_result_in_tab(self, finished_row: dict | None, launcher):
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
        for tab in self._generate_pane.watchers_of(key):
            if tab is not launcher:
                tab.show_finished_media(finished_row)

    def _on_reroll_failed(self, key: str, message: str = ""):
        self._auto.note_failed(key)
        self._after_a_job_ended_unfinished(key)
        self._generation_failed.say(format_execution_error(message))

    def _rerender_current_leaf(self):
        group = self.current_group()
        if isinstance(group, gallery.SettingsGroup):
            self._gallery_pane.show_thumbnails(group)

    def listed_prompt_ids(self) -> list[str]:
        return self._gallery_pane.listed_prompt_ids()

    def queue_now(self) -> tuple[list, int]:
        listed = self._listed_rows
        holds_every_job = {row["prompt_id"] for row in listed} >= set(self._jobs.queue_order)
        items = (self._inflight_items(rows=listed, requests=self._listed_requests)
                 if holds_every_job else self._inflight_items())
        return items, self._foreign_queue.total

    def _inflight_items(self, rows=None, requests=None) -> list:
        return self._starting.placed_among(
            self._gallery_pane.inflight_items(rows=rows, requests=requests), self._jobs)

    def _update_queue(self, inflight=None):
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
        self._update_queue()

    def _confirm_clear_queue(self, total: int) -> bool:
        reply = QMessageBox.question(
            self, "Clear ComfyUI's queue",
            f"{clear_queue_tooltip(total)}?\n\nAnything you queued from here is left alone;"
            " one of theirs already running is interrupted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def selected_folder(self) -> str | None:
        return self._tree_view.selected_folder_key() or self._pending_key

    def select_folder(self, key: str | None):
        self._pending_key = key or None

    def selected_generation(self) -> str | None:
        if self._selected:
            return self._selected.get("prompt_id")
        return self._pending_selection

    def select_generation(self, prompt_id: str | None):
        self._pending_selection = prompt_id or None

    def capture_generate_tabs(self) -> dict:
        return self._generate_pane.capture_state()

    def restore_generate_tabs(self, state):
        self._generate_pane.restore_state(state)

    def selected_prompt_ids(self) -> list[str]:
        return self._gallery_pane.selected_prompt_ids()

    def generation_menu(self, prompt_ids: list[str], global_pos):
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
        open_custom = _saved_custom_collection(self.current_group())
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
            self._remove_from_custom_collection(open_custom, items=held_here)
        elif enhance_action is not None and chosen is enhance_action:
            self._enhance.enhance_items(to_enhance)
        elif cancel_action is not None and chosen is cancel_action:
            self._enhance.cancel_for(rows)
        elif chosen is delete_action:
            self._delete_rows(rows)

    def _can_open_containing_folder(self, row: dict) -> bool:
        if row.get("deleted_at") is not None:
            return False
        leaf = self._leaf_by_id.get(row.get("prompt_id"))
        return leaf is not None and leaf is not self._tree.currentItem()

    def run_item_action(self, prompt_id: str, action: str):
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
            self._gallery_pane.refresh_corners()
        self._generate_pane.reconcile_previews(self._live_ids)
        if ids & self._gallery_pane.selected_ids:
            self._re_aim()

    def _recount_the_collections(self) -> None:
        for shape in self._tree.shapes:
            self._tree_view.set_collection_counts(shape, self._gallery_pane.collection_counts(shape))

    def _redrew_the_favorites_collection(self) -> bool:
        self._recount_the_collections()
        base, shape = _split_collection_key(self.selected_folder_key())
        collection = folder_collection(base)
        if collection is None or collection.which != _FAVORITES_KEY:
            return False
        place = self._gallery_pane.place()
        self._gallery_pane.show_collection(collection.key, shape)
        self._gallery_pane.return_to(place)
        return True

    def _delete_selection(self):
        """Delete picked thumbnails, or else the folder or picked folders on screen.

        In the Trash collection the picked items are already deleted, so Delete means
        the only deletion left: ending them for good. Same button, same key, the
        one meaning it can have where it is standing — rather than a control that
        looks live and quietly does nothing.
        """
        if self._in_the_trash():
            self.purge_from_trash(self.selected_prompt_ids())
            return
        if self._gallery_pane.selected_ids:
            rows = [self._db.get_generation(pid) for pid in self.selected_prompt_ids()]
            self._delete_rows([r for r in rows if r])
            return
        self._delete_folders(self._current_deletable_folders())

    def _copy_names_of_the_selection(self):
        if self._gallery_pane.selected_ids:
            copy_names([self._item_names.of(pid) for pid in self.selected_prompt_ids()])
        elif self._selection_group is not None:
            copy_names(_names_of_the_picked_folders(self._selection_group))
        elif (group := self.current_group()) is not None:
            copy_names([group.label])


    def _in_the_trash(self) -> bool:
        return self._gallery_pane.showing_trash()

    def _on_trash_action(self, prompt_id: str, action_id: str):
        if action_id == "restore":
            self.restore_from_trash([prompt_id])
        else:
            self.purge_from_trash([prompt_id])

    def _trash_menu(self, global_pos):
        ids = self.selected_prompt_ids()
        suffix = f" {len(ids)} item{'s' if len(ids) != 1 else ''}"
        menu = QMenu(self)
        _offer_copy_names_above_a_line(menu, [self._item_names.of(pid) for pid in ids])
        restore_action = trash_collection.restore_action_on(menu, "Restore" + suffix,
                                                    [self.row_for(pid) or {} for pid in ids])
        purge_action = menu.addAction("Delete" + suffix + " permanently")
        chosen = menu.exec(global_pos)
        if chosen is restore_action:
            self.restore_from_trash(ids)
        elif chosen is purge_action:
            self.purge_from_trash(ids)

    def restore_from_trash(self, prompt_ids):
        if not prompt_ids:
            return
        try:
            restored = trash_collection.restore_from_trash(self._db, self._jobs, prompt_ids,
                                                   self._edits.restore_deleted,
                                                   self.image_config_index())
        except Exception as e:
            logger.exception("Failed to restore %d deleted item(s)", len(prompt_ids))
            QMessageBox.warning(
                self, "Restore failed",
                f"Could not restore the selected item(s):\n\n{e}",
            )
            return
        self._gallery_pane.clear_selection()
        self.refresh()
        if restored:
            self._go_to_generation(restored)

    def purge_from_trash(self, prompt_ids):
        if not prompt_ids:
            return
        count = len(prompt_ids)
        plural = "s" if count != 1 else ""
        if not self._confirm(
            f"Permanently delete {count} item{plural}? This cannot be undone."
        ):
            return
        try:
            self._edits.purge_deleted(prompt_ids)
        except Exception as e:
            logger.exception("Failed to permanently delete %d item(s)", count)
            QMessageBox.warning(
                self, "Delete failed",
                f"Could not permanently delete the selected item(s):\n\n{e}",
            )
            return
        self._gallery_pane.clear_selection()
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
        doomed = set().union(*(self._keys_under(group) for group in groups))
        for key in reversed(self._folder_history):
            if key not in doomed and (item := self._item_by_key.get(key)) is not None:
                return item
        item = self._tree_item_for(groups[0].key)
        while item is not None and item.data(0, _TREE_KEY_ROLE) in doomed:
            item = item.parent()
        return item

    def _keys_under(self, group) -> set[str]:
        keys, stack = set(), [self._item_by_key[key] for key
                              in self._tree_view.keys_for_folder(group.key)]
        while stack:
            node = stack.pop()
            if node.data(0, _GROUP_ROLE) is not None:
                keys.add(node.data(0, _TREE_KEY_ROLE))
            stack.extend(node.child(i) for i in range(node.childCount()))
        return keys

    def _release_held_media(self, paths):
        """Drop every on-screen view of ``paths``: Windows won't move a file while a handle on it is open."""
        self._generate_pane.release_media(paths)
        self._slideshows.release_media(paths)

    def _delete_rows(self, rows):
        if not rows:
            return
        try:
            self._edits.delete_rows(rows)
        except Exception as e:
            logger.exception("Failed to delete %d generation(s)", len(rows))
            QMessageBox.warning(
                self, "Delete failed",
                f"Could not delete the selected item(s):\n\n{e}",
            )
            return
        self._gallery_pane.clear_selection()
        self.refresh()
        self._re_aim()

    def _undo(self):
        if not self._edits.can_undo():
            return
        focus = self._edits.undo()
        self._gallery_pane.clear_selection()
        self.refresh()
        if focus:
            self._go_to_generation(focus)
        self._re_aim()

    def _redo(self):
        if not self._edits.can_redo():
            return
        self._edits.redo()
        self._gallery_pane.clear_selection()
        self.refresh()
        self._re_aim()

    def _confirm(self, text: str) -> bool:
        reply = QMessageBox.question(
            self, "Delete", text,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _on_tree_context_menu(self, item, global_pos: QPoint, shape: str):
        if item is None:
            self._empty_tree_context_menu(global_pos, shape)
            return
        if _is_one_of_the_picked(self._selection_group, item.data(0, _GROUP_ROLE)):
            self._selection_context_menu(global_pos)
            return
        if item.data(0, _GROUP_ROLE) is not None:
            self._folder_context_menu(item.data(0, _TREE_KEY_ROLE), global_pos,
                                      toc_rows=[item])

    def _empty_tree_context_menu(self, global_pos: QPoint, shape: str):
        menu = QMenu(self)
        new_action = menu.addAction("New collection…")
        if menu.exec(global_pos) == new_action:
            self._new_custom_collection(shape)

    def _selection_context_menu(self, global_pos: QPoint):
        names = _names_of_the_picked_folders(self._selection_group)
        menu = QMenu(self)
        _offer_copy_names_above_a_line(menu, names)
        group_action = menu.addAction(f"Group {len(names)} folders into a new collection…")
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
                  else _saved_custom_collection(self.current_group()))
        if isinstance(group, gallery.CustomCollection):
            self._custom_collection_context_menu(group, global_pos, holder, toc_rows)
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
            self._remove_from_custom_collection(holder, [group.key])
        elif chosen in add_menu:
            self._on_dropped(add_menu[chosen], [key])
        elif delete_action is not None and chosen == delete_action:
            self._delete_folders([group])
        elif chosen in collapse_and_expand:
            collapse_and_expand[chosen]()

    def _add_to_folder_menu(self, menu: QMenu, key: str) -> dict:
        shape = _shape_of(key) or self.shape_in_view()
        targets = [f for f in self._custom_collections_by_shape.get(shape, ())
                   if not any(m.key == _base_of(key) for m in gallery.child_groups(f))]
        if not targets:
            return {}
        submenu = menu.addMenu("Add to collection")
        return {submenu.addAction(folder.label): folder.key for folder in targets}

    def _custom_collection_context_menu(self, group, global_pos: QPoint, holder, toc_rows):
        menu = QMenu(self)
        _offer_copy_names_above_a_line(menu, [group.label])
        take_out_action = _offer_taking_out(menu, holder, group)
        remove_action = menu.addAction("Remove collection…")
        collapse_and_expand = offer_collapse_and_expand(menu, toc_rows)
        chosen = menu.exec(global_pos)
        if take_out_action is not None and chosen == take_out_action:
            self._remove_from_custom_collection(holder, [group.key])
        elif chosen == remove_action:
            self._remove_custom_collection(group)
        elif chosen in collapse_and_expand:
            collapse_and_expand[chosen]()

    def _toggle_favorite(self, key: str):
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
            self._gallery_pane.mark_folder_favorite(key, favorite)

    def _delete_folder_by_key(self, key: str):
        group = self.group_for_key(key)
        if _is_one_of_the_picked(self._selection_group, group):
            self._delete_folders(self._current_deletable_folders())
        elif group is not None:
            self._delete_folders([group])

    def row_for(self, prompt_id: str) -> dict | None:
        row = self._db.get_generation(prompt_id)
        if row:
            return row
        return next((r for r in self._held_rows if r["prompt_id"] == prompt_id), None)

    def _on_thumbnail_clicked(self, prompt_id: str):
        if not self._show_generation(prompt_id):
            return
        self._navigation.record(prompt_id)

    def _show_generation(self, prompt_id: str) -> bool:
        """Make a generation the selected item and load it into a Generate tab —
        its output in the preview, its settings in the form, a footer for its
        media type — saying whether the gallery still has a row for it.

        Which tab is :meth:`GeneratePane.load_selection`'s to say — the one
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
        self._generate_pane.load_selection(row, self._image_rows)
        return True

    def _select_saved_generation(self, row: dict):
        self._clear_reroll_selection()
        self._selected_row = row

    def animated_preview(self, row: dict) -> str | None:
        """The looping-WebP preview for a video ``row``, or ``None`` for an image or a
        video with no animated thumbnail, whose tile shows its still."""
        thumb_dir = self._edits.thumb_dir
        return (gallery.animated_preview_if_made(row, self._edits.places, thumb_dir)
                if thumb_dir is not None else None)

    def follow_link(self, prompt_id: str):
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
        prompt_id = gallery.landing_for(prompt_id, self._listed_rows, self.image_config_index())
        item = self._folder_row_for(prompt_id)
        if item is not None:
            with self._navigation.off_the_record():
                drawn_by_the_signal = not self._tree.is_current(item)
                self._tree.setCurrentItem(item)
                if not drawn_by_the_signal:
                    self._on_folder_selected(item, None)
        self._on_thumbnail_clicked(prompt_id)
        revealed = self._gallery_pane.reveal_tile(prompt_id)
        logger.info("Went to %s: folder %s, %d items listed, tile shown %s",
                    prompt_id, self.selected_folder_key(),
                    len(self._gallery_pane.listed_prompt_ids()), revealed)

    def _folder_row_for(self, prompt_id: str):
        """The tree row of the folder a generation lives in: its settings row, or
        — for one the tree holds no row for, such as a generation that failed
        with no file — the row its settings key names, and for one held in the
        trash, the Trash.

        ``None`` only when the tree has nowhere at all to put it, which is the
        one case a move has no folder to open. Answering ``None`` for anything
        less than that is what left a move opening no folder while the item it
        named went on to fill the Generate pane, so the click read as having done
        nothing.
        """
        leaf = self._leaf_by_id.get(prompt_id)
        if leaf is not None:
            return leaf
        row = self._db.get_generation(prompt_id)
        if row is None:
            held = self.row_for(prompt_id)
            return self._tree_item_for(shaped_key(_TRASH_KEY, row_shape(held))) if held else None
        key = self.folder_key_of(row)
        return self._tree_item_for(key) if key else None

    def _current_collection_key(self) -> str | None:
        key = self.selected_folder_key()
        return key if folder_collection(_base_of(key)) is not None else None

    def _clear_metadata(self):
        self._selected_row = None

    def pin_generate_tab(self):
        self._generate_pane.pin_current_tab()


def _side_list(rows, meta, start_frames, shape, name_of):
    return gallery.build_gallery_tree(filter_rows(rows, shape), meta,
                                      image_index=start_frames, name_of=name_of)


def _custom_collections_by_shape(trees, records) -> dict[str, list]:
    return {shape: gallery.build_custom_collections(
                tree, [record for record in records
                       if _shape_covers(shape, record["side"] or _LANDSCAPE)])
            for shape, tree in trees.items()}


def _group_workflow(group) -> str | None:
    if isinstance(group, (gallery.AllGroup, gallery.MediaGroup)):
        return None
    if isinstance(group, gallery.WorkflowGroup):
        return group.workflow_name
    rows = gallery.rows_under(group)
    return rows[0]["workflow_name"] if rows else None


class _PollFacts(NamedTuple):
    histories: dict
    backlogs: dict
    foreign: object
    executing: frozenset = frozenset()


def _fetch_poll_facts(client, targets) -> _PollFacts:
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
    if client is None:
        return None
    try:
        return client.foreign_queue()
    except Exception as e:
        logger.debug("Could not read ComfyUI's queue: %s", e)
        return ForeignQueue(running=[], pending=[])


def _fingerprint(rows, meta) -> tuple[int, int]:
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
