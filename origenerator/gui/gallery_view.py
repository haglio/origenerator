from __future__ import annotations

import logging
import time
from functools import partial
from typing import NamedTuple

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shared_ui.find_bar import FindBar
from shared_ui.message_shape import ERROR, INFO
from shared_ui.spacing import GAP_MEDIUM
from shared_ui.tick_control import TickControl

from origenerator import (
    evolver_export,
    gallery,
    outside_videos,
    timing,
    trash_collection,
)
from origenerator.action_setter_tool import SetterHost, ThrownInto
from origenerator.branch_session import is_branch_session
from origenerator.comfyui_api import format_execution_error
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import (
    EVOLVER_SOURCE,
    GENAU_DIR,
    KINO_TRASH_DIR,
    KINO_UPSCALES_DIR,
    OUTPUT_PLACES,
    THUMB_DIR,
    TRASH_DIR,
)
from origenerator.db import Database, NewRequest
from origenerator.evolver_trash import in_the_background as delete_through_evolver
from origenerator.fun_time_bridge import ask_for_origenerator_mode
from origenerator.fun_time_mode import FunTimeSession
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
from origenerator.gallery.collection import (
    FolderCollection,
    collection,
    folder_collection,
)
from origenerator.gallery.shapes import (
    SEPARATE as _SEPARATE,
)
from origenerator.gallery.shapes import (
    TOGETHER as _TOGETHER,
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
from origenerator.gui.app_keys import AppKeys, Presses
from origenerator.gui.app_title import under
from origenerator.gui.busy_cursor import working
from origenerator.gui.combination import Combination
from origenerator.gui.combine_controller import CombineController, CombineParts
from origenerator.gui.copy_names import copy_names, offer_copy_names_above_a_line
from origenerator.gui.deleting import asked_to_delete
from origenerator.gui.drop_target import DropTarget
from origenerator.gui.enhance_controller import (
    ALREADY_AT_THESE_SETTINGS,
    EnhanceController,
    EnhanceParts,
)
from origenerator.gui.folder_actions import FolderActions
from origenerator.gui.folder_icons import collection_mark
from origenerator.gui.folder_path import FolderPath
from origenerator.gui.folder_switches import FolderSwitches
from origenerator.gui.folder_tree import TREE_KEY_ROLE as _TREE_KEY_ROLE
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
    GROUP_TIP,
    POPULATE_ELSEWHERE_TIP,
    Button,
    ButtonHandlers,
    ButtonStates,
    GalleryPaneButtons,
    OfferedPress,
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
    takes_a_favorite,
)
from origenerator.gui.gallery_view_parts import NO_SHARED, Shared
from origenerator.gui.generate_pane import GeneratePane, TabViews
from origenerator.gui.generating_tile import GeneratingTile
from origenerator.gui.generation_failed import GenerationFailed
from origenerator.gui.how_many import HOW_MANY
from origenerator.gui.inflight import (
    CANCEL_TEXT,
    cancel_tooltip,
    queue_wait_text,
    stop_populate_text,
    stop_populate_tooltip,
)
from origenerator.gui.job_queue import JobQueue
from origenerator.gui.look_training_controller import LookTrainingController
from origenerator.gui.modify_batch_tile import ModifyBatchTile
from origenerator.gui.motion_hud import apply_motion_key
from origenerator.gui.new_tile import NewTile
from origenerator.gui.off_thread import run_off_thread
from origenerator.gui.open_setters import OpenSetters
from origenerator.gui.osr2_controls import Osr2Controls
from origenerator.gui.osr2_driving import Osr2Driving
from origenerator.gui.pane_arrangement import PaneArrangement
from origenerator.gui.panes import (
    FootSplitter,
    PaneSplitter,
    hold_the_borders_still,
    pane,
)
from origenerator.gui.picking import Picks
from origenerator.gui.populate_controller import PopulateController
from origenerator.gui.prompt_reveal import reveal_prompt
from origenerator.gui.shown_job_queue import ShownJobQueue, read_foreign_queue
from origenerator.gui.slideshow_director import (
    DirectorSources,
    DirectorSurroundings,
    SlideshowDirector,
)
from origenerator.gui.slideshow_pace import SlideshowPace
from origenerator.gui.slideshow_wiring import Listing
from origenerator.gui.starting_rows import StartingRows
from origenerator.gui.toc_editing import (
    AroundAnEdit,
    TocEditing,
    names_of_the_picked_folders,
    saved_custom_collection,
)
from origenerator.gui.two_screens import TwoScreens
from origenerator.gui.voice_router import VoiceRouter, VoiceSources, VoiceSwitches
from origenerator.item_names import ItemNames
from origenerator.item_shape import (
    base_of as _base_of,
)
from origenerator.item_shape import (
    requested_shape,
    row_shape,
    shaped_key,
    what_plays_at,
)
from origenerator.item_shape import (
    shape_of as _shape_of,
)
from origenerator.item_shape import (
    split_key as _split_collection_key,
)
from origenerator.library_readings import LibraryReadings, arrived, read_whole
from origenerator.one_look import looking_once
from origenerator.prompt_tokens import boxed_as_typed
from origenerator.published_actions import give_the_launch_its_actions
from origenerator.radio import OrigeneratorRadio
from origenerator.trash import Genau, Kino, Trash
from origenerator.voice.app_commands import AppCommand
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.derived_size import resolve_input_image_path

logger = logging.getLogger(__name__)


_POLL_INTERVAL_MS = 1500


class _SearchScope(NamedTuple):
    steps: tuple[PathStep, ...]
    ids: set[str] | None

    @property
    def path(self) -> str:
        return path_text(self.steps)


def _row_under(row, folder_key: str):
    if row is None or _shape_of(folder_key) is not None:
        return None
    return next((child for child in (row.child(i) for i in range(row.childCount()))
                 if _base_of(child.data(0, _TREE_KEY_ROLE)) == folder_key), None)


ONLY_A_LEAF_IS_DELETED = "Only a leaf folder can be deleted"


def _top_section(folder_path: QWidget, buttons: QWidget, folder_actions: QWidget) -> QHBoxLayout:
    left = QVBoxLayout()
    left.setContentsMargins(0, 0, 0, 0)
    left.addWidget(folder_path)
    left.addWidget(buttons)
    top = QHBoxLayout()
    top.setContentsMargins(0, 0, 0, 0)
    top.setSpacing(GAP_MEDIUM)
    top.addLayout(left, 1)
    top.addWidget(folder_actions, 1, Qt.AlignmentFlag.AlignTop)
    return top


class GalleryView(QWidget):
    run_ended = Signal(object)
    quit_asked = Signal()

    def __init__(self, db: Database, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryEdits | None = None,
                 fun_time: FunTimeSession | None = None,
                 shared: Shared = NO_SHARED):
        super().__init__()
        self._db = db
        self._prompt_heights = shared.prompt_heights
        self._inbox = shared.inbox or evolver_export.default_inbox()
        self._two_screens = shared.two_screens or TwoScreens(self)
        self._app_title = shared.app_title
        self._client = client
        self._fun_time = fun_time
        self._radio = shared.radio if shared.radio is not None else OrigeneratorRadio()
        omnipause.holds(self._radio)
        self.osr2 = Osr2Driving(
            self._surface_in_front, hosted=fun_time is not None, motion=shared.osr2_motion,
            waits_for_the_window=shared.device_waits_for_the_window, parent=self)
        self._pace = SlideshowPace(parent=self)
        self._build_the_queue_of_runs(db, client)
        self._item_names = ItemNames(db)
        self.library = LibraryReadings(db, self._item_names, shared.publish_names)
        self._build_the_panes(db, client)
        self._edits = actions or GalleryEdits(
            db, OUTPUT_PLACES, Trash(TRASH_DIR),
            environment=GalleryEnvironment(
                release_files=self._release_held_media, thumb_dir=THUMB_DIR,
                cancel_enhancements=self._enhance.cancel_for_delete,
                kino=Kino(KINO_UPSCALES_DIR, KINO_TRASH_DIR, EVOLVER_SOURCE),
                genau=Genau.in_folder(GENAU_DIR),
                bring_in=partial(outside_videos.bring_in_one, db),
                delete_for_good=delete_through_evolver,

            ),

        )
        self.toc_editing = TocEditing(
            self._tree, self.toc, edits=self._edits, library=self.library,
            folder_switches=self._folder_switches, asks_over=self,
            screen=AroundAnEdit(
                refresh=self.refresh, re_aim_every_button=self._re_aim_every_button,
                delete_rows=self._delete_rows, current_group=self.current_group,
                showing_search=self._gallery_pane.showing_search,
                draw_folder_favorite=self._draw_a_folders_favorite))
        DropTarget(self._scroll, self.toc_editing.landing_in_the_open_collection,
                   self.toc_editing.dropped)
        self._gallery_pane.folder_menu_requested.connect(self.toc_editing.folder_context_menu)
        self._tree.context_menu_requested.connect(self.toc_editing.tree_context_menu)
        self._tree.favorite_clicked.connect(self.toc_editing.toggle_favorite)
        self._tree.delete_clicked.connect(self.toc_editing.delete_folder_by_key)
        self._tree.dropped.connect(self.toc_editing.dropped)
        self._build_ui()
        self._voice.bind_the_buttons(
            VoiceSwitches(
                populate=self._buttons.populate, radio=self._buttons.radio,
                drive=self._the_osr2_switch(), mic=self._buttons.mic),
            enhance=(OfferedPress(self._enhance_the_picked_offer),
                     self._enhance.enhance_the_selection),
            actions={
                AppCommand.BACK: (self._buttons.back, self._navigation.go_back),
                AppCommand.FORWARD: (self._buttons.forward, self._navigation.go_forward),
                AppCommand.CULL: (OfferedPress(self._delete_the_picked_offer),
                                  self._delete_selection),
                AppCommand.FAVORITE: (OfferedPress(self._favorite_the_picked_offer),
                                      self._favorite_selection),
                AppCommand.UNDO: (self._buttons.undo, self._undo),
                AppCommand.REDO: (self._buttons.redo, self._redo),
                AppCommand.GROUP: (self._buttons.group, self.toc_editing.group_the_picked),
            },
        )
        self._re_aim_every_button()
        self.keys = AppKeys(
            self, find_bar=self._find_bar, generate_pane=self._generate_pane,
            standalone=lambda: self._fun_time is None,
            presses=Presses(
                delete=self._delete_selection, copy_names=self._copy_names_of_the_selection,
                undo=self._undo, redo=self._redo, open_find=self._open_find,
                pause_or_play=self._slideshows.pause_or_play_the_room,
                motion_key=self._motion_key,
                slideshows_key=self._slideshows.take_key))
        self.keys.intercept(True)

        self._poll_inflight = False
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

    def _build_the_queue_of_runs(self, db, client):
        self._jobs = JobQueue(db, client)
        self._jobs.changed.connect(self._rerender_current_leaf)
        self._jobs.changed.connect(self._reconcile_generating)
        self._jobs.preview.connect(self._on_reroll_preview)
        self._jobs.finished.connect(self._on_reroll_finished)
        self._jobs.failed.connect(self._on_reroll_failed)
        self._jobs.run_ended.connect(self.run_ended)
        self._generation_failed = GenerationFailed(self)
        self._populate = PopulateController(self._start_populate_reroll)
        self._populate.stopped.connect(self._on_populate_stopped)
        self._populate_settings: dict = {}
        self._populate_origins: set[str] = set()
        self._selected_reroll_key: str | None = None
        self._generating_tile: GeneratingTile | None = None

    def _build_the_panes(self, db, client):
        self._build_the_toc()
        self._search = GallerySearchController(self, parent=self)
        self._selected_row: dict | None = None
        self._scroll = GalleryPaneScrollArea()
        self._gallery_pane = GalleryPane(
            self._scroll, db, self._jobs, self._populate,
            PaneHost(
                image_rows=lambda: self.library.reading.image_rows,
                animated_preview=self.animated_preview,
                enhancing=lambda: self._enhance,
                experiments_enabled=self.experiments_enabled,
                lead_tiles=self._lead_tiles,
                item_name=self._item_names.of,
                tree=TreeNavigation(
                    selected_folder_key=self.selected_folder_key,
                    folder_context=self.toc.folder_context,
                    group_for_key=self.group_for_key,
                ),
            ),
        )
        self._gallery_pane.pane_reset.connect(self._forget_generating_tile)
        self._gallery_pane.thumbnail_activated.connect(self._on_thumbnail_clicked)
        self._gallery_pane.tab_pin_requested.connect(self.pin_generate_tab)
        self._gallery_pane.item_jump_requested.connect(self.follow_link)
        self._gallery_pane.folder_open_requested.connect(self._go_to_folder)
        self._gallery_pane.reveal_reroll_requested.connect(self._reveal_reroll)
        self._gallery_pane.menu_requested.connect(self.generation_menu)
        self._gallery_pane.trash_menu_requested.connect(self._trash_menu)
        self._gallery_pane.item_action_triggered.connect(self.run_item_action)
        self._gallery_pane.seed_reroll_requested.connect(self._reroll_item_seed)
        self._gallery_pane.experiment_verdict.connect(self._on_experiment_verdict)
        self._gallery_pane.trash_action_triggered.connect(self._on_trash_action)
        self._gallery_pane.cancel_requested.connect(self._cancel_job)
        self._gallery_pane.selection_changed.connect(self._re_aim_every_button)
        self._pending_key: str | None = None
        self._pending_selection: str | None = None
        self._pending_combine_key: str | None = None
        self._navigation = NavigationController(self, search=self._search)
        self._trail = (False, False)
        self._starting = StartingRows(self)
        self.job_queue = ShownJobQueue(
            self._jobs, client, starting=self._starting,
            in_flight=self._gallery_pane.inflight_items,
            listed=lambda: (self.library.reading.rows, self.library.requests), asks_over=self)
        self._slideshows = SlideshowDirector(
            self,
            DirectorSources.of_this_library(db=db, jobs=self._jobs, names=self._item_names,
                                            library=lambda: self.library.reading, listing=self.listing),
            DirectorSurroundings(
                pace=self._pace, motion=self.osr2.motion, osr2=self.osr2,
                job_queue=self.job_queue, fun_time=self._fun_time,
                radio=self._radio, buttons_of=lambda: self._buttons,
                two_screens=self._two_screens))
        self._gallery_pane.slideshow_requested.connect(self._slideshows.open_on_tile)
        self._combine = CombineController(
            self,
            CombineParts(
                jobs=self._jobs, client=client, info_tabs_of=lambda: self._generate_pane,
                slideshows=self._slideshows, starting=self._starting,
                names=self._item_names, inbox=self._inbox),
            parent=self, db=db)
        self._enhance = EnhanceController(
            self,
            EnhanceParts(
                jobs=self._jobs, gallery_pane=self._gallery_pane,
                slideshows=self._slideshows, info_tabs_of=lambda: self._generate_pane),
            db=db)
        self._folder_switches = FolderSwitches(self, db, self._enhance)
        self._jobs.changed.connect(self._enhance.reconcile)
        self._jobs.enhance_images_with(self._enhance.enhance_a_videos_start_image)
        self._look_training = LookTrainingController(
            self._jobs, info_tabs_of=lambda: self._generate_pane, parent=self)
        open_setters = OpenSetters()
        self._setter_host = SetterHost(
            lambda library: ThrownInto(library, self._delete_rows, self.restore_from_trash),
            open_setters.hold)
        self._voice = VoiceRouter(
            self, VoiceSources(db=db, slideshows=self._slideshows, client=client,
                               starting=self._starting, jobs=self._jobs, setters=open_setters),
            parent=self, motion=self.osr2.motion)
        self._gallery_pane.selection_changed.connect(
            lambda: self._voice.note_picks(self._gallery_pane.picks(), now=time.monotonic()))

    def _motion_key(self, key) -> bool:
        if not apply_motion_key(self.osr2.motion, key, on_drive_toggle=self.osr2.toggle):
            return False
        self._osr2_controls.refresh()
        return True

    def _build_ui(self):
        layout = QVBoxLayout(self)
        toc = self._build_toc_pane()
        gallery_pane = self._build_gallery_pane()
        self._arrangement = PaneArrangement(
            toc=toc, gallery_pane=gallery_pane, generate_column=self._build_generate_pane(),
            generate_pane=self._generate_pane, queue=self.job_queue.view)
        self.job_queue.changed.connect(self._tell_of_the_queue)
        self._folder_actions.saved.connect(self._generate_pane.hear_actions)
        folded = self._fun_time is not None and not self._fun_time.in_a_headset
        layout.addWidget(self._arrangement.hosted() if folded
                         else self._arrangement.standalone(), 1)
        hold_the_borders_still(self, self._fun_time is not None)

    def _build_the_toc(self):
        self.toc = GalleryTree()
        self._tree = self.toc.widget
        self._tree.offer_separate_and_together(self._fun_time is None)

    def _build_toc_pane(self):
        self._tree.shapes_changed.connect(self._on_shapes_changed)
        self._tree.currentItemChanged.connect(self._on_folder_selected)
        # Qt emits itemSelectionChanged after currentItemChanged, so the selection has the last word on what the panes show.
        self._tree.itemSelectionChanged.connect(self._on_tree_selection_changed)
        finding, toc_column = pane()
        toc_column.addWidget(self._search.row)
        toc_column.addWidget(self._tree, 1)
        combining, combining_column = pane()
        combining_column.addWidget(self._combine.widget)
        if self._combine.widget.isHidden():
            combining.hide()
        sections = [finding, combining]
        self._osr2_controls = None
        self._motion_pane = None
        if self.osr2.motion is not None:
            self._osr2_controls = Osr2Controls(self.osr2.motion, control=self.osr2.control)
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
        return toc if self._app_title is None else under(self._app_title, toc)

    def _build_gallery_pane(self):
        gallery_pane, gallery_column = pane()
        self._folder_path = FolderPath()
        self._folder_path.folder_chosen.connect(self._go_to_folder)
        self._folder_actions = FolderActions(self._db)
        self._folder_actions.set_setter_host(self._setter_host)
        self._buttons = GalleryPaneButtons(
            ButtonHandlers(
                go_back=self._navigation.go_back,
                go_forward=self._navigation.go_forward,
                undo=self._undo,
                redo=self._redo,
                start_slideshow=self._slideshows.start,
                toggle_populate=self._toggle_populate,
                go_to_populating_folder=self._go_to_populating_folder,
                favorite=self._switch_the_open_folders_favorite,
                enhance=self._switch_the_open_folders_enhance,
                group=self.toc_editing.group_the_picked,
                delete=self._delete_the_open_folder,
                toggle_radio=self._on_radio_toggle,
                toggle_mic=self._voice.mic_toggled,
                pause_or_play=self._slideshows.pause_or_play_the_room,
                quit=self.quit_asked.emit,
            ),
            hosted=self._fun_time is not None, two_screens=self._two_screens,
        )
        gallery_column.addLayout(_top_section(self._folder_path, self._buttons, self._folder_actions))
        self._experiments_cb = TickControl("Run experiments while the app is closed")
        self._experiments_cb.toggled.connect(self._on_experiments_toggled)
        self._experiments_cb.setEnabled(not is_branch_session())
        self._experiments_status = QLabel("")
        self._experiments_status.setObjectName("mutedLabel")
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
        self._avg_label.setObjectName("mutedLabel")
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
        self._generate_pane = GeneratePane(
            self._client, self._db, fun_time=self._fun_time, inbox=self._inbox,
            views=TabViews(heights=self._prompt_heights, names=self._item_names,
                           animated_preview=self.animated_preview,
                           requests=self._voice.requests))
        self._find_bar = FindBar("Find in prompts:", "a word you wrote…",
                                 dismiss_key="Esc", reveal=reveal_prompt)
        self._generate_pane.tab_added.connect(self._wire_generate_tab)
        for tab in self._generate_pane.generate_tabs():
            self._wire_generate_tab(tab)
        self._generate_pane.currentChanged.connect(self._on_front_tab_changed)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._radio.stop)
        self._generate_pane.generate_requested.connect(self._on_generate_requested)
        self._generate_pane.turn_generate_requested.connect(self._on_turn_generate_requested)
        self._generate_pane.modify_batch_requested.connect(self._on_modify_batch_requested)
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
        self.osr2.let_go_for_a_session()
        self._fun_time = session
        self._tree.offer_separate_and_together(False)
        self._slideshows.become_hosted(session)
        self._generate_pane.become_hosted(session)
        self._voice.become_hosted()
        self._buttons.become_hosted()
        if self._motion_pane is not None:
            self._motion_pane.hide()
        self.osr2.leave_the_device_to_the_session()
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
        self.osr2.take_the_device_back()
        if self._motion_pane is not None:
            self._motion_pane.show()
        self._fun_time = None
        self._tree.offer_separate_and_together(True)
        self._slideshows.become_standalone(self.osr2.motion)
        self._generate_pane.become_standalone()
        self._buttons.become_standalone()
        self._voice.become_standalone(
            self.osr2.motion, radio=self._buttons.radio, drive=self._the_osr2_switch(),
            mic=self._buttons.mic)
        self.wear_the_room(None)

    def _wire_generate_tab(self, tab):
        tab.link_clicked.connect(self.follow_link)
        tab.go_to_folder_requested.connect(self.follow_link)
        tab.set_folder_check(self._can_open_containing_folder)
        tab.set_making_one_check(
            lambda config: self._config_folder_key(config) in self._live_jobs)
        tab.item_action_requested.connect(self.run_item_action)
        tab.context_menu_requested.connect(
            lambda prompt_id, pos: self.generation_menu([prompt_id], pos))
        tab.displayed_changed.connect(self.osr2.reconcile)
        tab.displayed_changed.connect(self._enhance.reconcile)
        tab.displayed_changed.connect(self._reconcile_generating)
        tab.enhance_requested.connect(lambda pid: self._enhance.enhance_items([pid]))
        tab.versions_delete_requested.connect(self.delete_enhance_versions)
        tab.set_enhance_settings(self._enhance.settings)
        tab.set_fullscreen_factory(self._slideshows.open_on_preview)
        tab.set_setter_host(self._setter_host)
        tab.actions_saved.connect(self._folder_actions.hear)
        tab.actions_saved.connect(self._generate_pane.hear_actions)
        tab.cancel_requested.connect(lambda p=tab: self._cancel_tab_reroll(p))
        tab.prompt_fields_changed.connect(self._retarget_find)
        tab.form_edited.connect(self._find_bar.refresh)
        self._look_training.wire(tab)

    def _the_osr2_switch(self):
        return self.osr2.control if self.osr2.motion is not None else None

    def video_in_front(self) -> str | None:
        surface = self._surface_in_front()
        return surface.video_on_screen() if surface is not None else None

    def _surface_in_front(self):
        slideshow = self._slideshows.surface_for(None)
        if slideshow is not None:
            return slideshow
        return self._generate_pane.current_generate_tab()

    def group_for_key(self, key: str):
        return self.toc.group_for_key(key)

    def _on_front_tab_changed(self, _index):
        self.osr2.reconcile()
        self._reconcile_generating()
        self._retarget_find()

    def _on_radio_toggle(self, on: bool):
        if on:
            if self.isVisible():
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
        return self._jobs.flush_to_server()

    def _on_experiments_toggled(self, _checked: bool):
        self._sync_experiments_bar()

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
            self._re_aim_every_button()
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
        for tab in self._generate_pane.generate_tabs():
            live = [(origin, job) for origin in tab.launched_runs()
                    if (job := self._jobs.job_for_origin(origin)) is not None]
            tab.forget_launched({origin for origin in tab.launched_runs()
                                   if origin not in {o for o, _ in live}})
            job = live[0][1] if live else None
            tab.set_generating(job is not None,
                                 populating=self._populating(job))
            tab.reread_generate_button()
        self._combine.reconcile_generating()

    def _populating(self, job) -> bool:
        key = self._job_folder_key(job)
        return key is not None and self._populate.is_active(key)

    def _job_folder_key(self, job) -> str | None:
        if job is None:
            return None
        return next((k for k, jobs in self._jobs.jobs_by_folder.items()
                     if job in jobs), None)

    def _claim_launch(self, key: str):
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
        launching = self._generate_pane.current_generate_tab()
        launch = self._launch(workflow_name, batch, launching,
                              launching.asked() if launching is not None else None)
        if launch is None:
            return
        key, launched = launch
        if launching is not None:
            for prompt_id in launched:
                launching.note_launched(prompt_id, made_of=batch[0])
        self._stand_on_the_run_in(key, rebuild=True)

    def _on_turn_generate_requested(self, tab, workflow_name: str, params: dict, asked: dict):
        launch = self._launch(workflow_name, [params], tab, asked)
        if launch is None:
            return
        _key, (prompt_id, *_more) = launch
        tab.note_turn_made(prompt_id)
        self.refresh()

    def _launch(self, workflow_name: str, batch: list[dict], launching,
                asked: dict | None) -> tuple[str, list[str]] | None:
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        if self._client is None or wf is None:
            return None
        batch = [{**wf.default_params(), **params} for params in batch]
        key = self.folder_key_for(workflow_name, batch[0])
        if key in self._live_jobs:
            return None
        if self.would_reproduce_a_completed_run(wf, batch[0]):
            batch[0] = randomize_seeds(batch[0], wf.seed_keys())
            if launching is not None:
                launching.use_random_seed()
        launched = [prompt_id for prompt_id in self._jobs.start_batch(key, wf, batch)
                    if prompt_id]
        if not launched:
            return None
        if launching is not None:
            category, video_id, intent, checked = launching.settings_source()
            for prompt_id in launched:
                if category or video_id:
                    self._db.set_settings_source(prompt_id, category=category,
                                                 video_prompt_id=video_id)
                give_the_launch_its_actions(self._db, prompt_id, category, checked)
                if video_id and not category:
                    self._db.record_combine_video_use(intent, video_id, prompt_id)
                if asked is not None:
                    self._db.record_request(NewRequest(
                        prompt_id=prompt_id, heard="",
                        new_positive=batch[0].get("positive_prompt", ""),
                        new_negative=batch[0].get("negative_prompt", ""), **asked))
        return key, launched

    def _stand_on_the_run_in(self, key: str, *, rebuild: bool = False) -> bool:
        if rebuild:
            self.refresh()
        item = self.toc.item_for(key)
        if item is None:
            return False
        with self._navigation.off_the_record():
            self._tree.setCurrentItem(item)
        self._note_folder_visit(self.toc.selected_folder_key())
        self._select_reroll(key)
        self._navigation.record()
        return True

    def showEvent(self, event):
        super().showEvent(event)
        self._poll_timer.start()
        self.keys.intercept(True)
        self.refresh(only_if_moved=True)
        if self.radio_enabled():
            self._radio.start()
        self.osr2.the_window_is_up()

    def hideEvent(self, event):
        super().hideEvent(event)
        if not (event.spontaneous() or self.window().isMinimized()):
            self._poll_timer.stop()

    def closeEvent(self, event):
        """Qt never hides a widget that was never shown, so ``hideEvent`` alone leaves the poll and the key filter armed."""
        self._poll_timer.stop()
        self.keys.intercept(False)
        self.close_the_slideshows()
        self._voice.close()
        self._jobs.close()
        super().closeEvent(event)

    def refresh(self, *, only_if_moved: bool = False):
        rows, meta = self.library.read()
        if self.library.moved_to(rows, meta) or not only_if_moved:
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
        read_at = self.library.drawn_version
        self.off_thread(lambda: read_whole(db),
                        lambda read: self._finish_poll_rebuild(read, read_at))

    def _finish_poll_rebuild(self, read, read_at: int):
        try:
            if read is None:
                return
            if self.library.is_news(read, read_at):
                listed_before = self.library.reading.rows
                self._rebuild(read.rows, read.meta)
                self._slideshows.note_arrived(arrived(self.library.reading.rows, listed_before))
            else:
                self._gallery_pane.refresh_inflight(rows=read.rows, requests=read.requests)
            self.job_queue.update(
                self.job_queue.items(rows=read.rows, requests=read.requests))
            self._enhance.tell_the_slideshows()
            self._refresh_wait_note()
        finally:
            self._poll_inflight = False

    def _apply_poll_facts(self, jobs, facts: _PollFacts):
        for job in jobs:
            job.reconcile_with(facts.histories.get(job.prompt_id))
            job.take_backlog(facts.backlogs.get(job.prompt_id))
            job.take_executing(job.prompt_id in facts.executing)
        self.job_queue.take_foreign(facts.foreign)

    def _rebuild(self, rows, meta):
        standing = self.toc.selected_folder_key()
        place = self._gallery_pane.place()
        selected_key = standing or self._pending_key
        multi_keys = self._tree.selected_folder_keys()
        if len(multi_keys) <= 1:
            multi_keys = []
        selected_gen = self.selected_generation()
        reroll_key = self._selected_reroll_key
        self._pending_key = self._pending_selection = None
        self._combine.offer_the_actions(rows)
        trash_collection.settle_regenerations(self._db)
        library = self.library.take(rows, meta, self._tree.shapes)
        rows = library.rows
        trees = {shape: library.tree(shape) for shape in self._tree.shapes}
        self._search.index.update(rows + library.held_rows, gallery.named_folders(
            [folder for tree in trees.values() for folder in tree], meta,
            self.library.customs), item_name=self._item_names.of)
        requests = self.library.requests
        self._gallery_pane.set_model(library)
        self.toc.populate(
            self._build_sides(trees), folder_meta=meta,
            recently_worked=gallery.recently_worked_folders(trees, rows, bumped=library.recency),
        )
        self.toc.picked_together = None
        self._selected_row = None
        self._generate_pane.reconcile_previews(self.library.live_ids)
        self._generate_pane.reread_names()
        self._combine.reread_names()
        target = (self.toc.item_for(selected_key) if selected_key
                  else None) or self.toc.default_item()
        with self._navigation.off_the_record():
            if target is not None:
                self._tree.setCurrentItem(target)
                self._reselect_generation(selected_gen)
            else:
                self._folder_path.set_display("")
                self._avg_label.setText("")
                self._gallery_pane.show_empty()
            self._restore_multi_selection(multi_keys)
            self._restore_reroll_selection(reroll_key)
        self._navigation.seed()
        if self._search.query:
            self._search.run()
        if standing is not None and self.toc.selected_folder_key() == standing:
            self._gallery_pane.return_to(place)
        self.job_queue.update(self.job_queue.items(rows=rows, requests=requests))
        self._reconcile_generating()
        for tab in self._generate_pane.generate_tabs():
            tab.refresh_generate_caption()
        self._folder_switches.take_in_the_arrivals()

    def _build_sides(self, trees):
        return [ShapeModel(
            shape=shape,
            tree_model=trees[shape],
            custom_collections=gallery.outermost(self.library.customs_by_shape[shape]),
            show_latest=bool(trees[shape]),
            collection_counts=self._gallery_pane.collection_counts(shape),
        ) for shape in self._tree.shapes]

    def open_folders(self) -> list[str]:
        return sorted(self.toc.folders_left_open())

    def set_open_folders(self, saved) -> None:
        if isinstance(saved, list):
            self.toc.leave_folders_open(key for key in saved if isinstance(key, str))

    def toc_shapes(self) -> list[str]:
        return list(self._tree.chosen_sides)

    def set_toc_sides(self, saved) -> None:
        self._tree.choose_shapes(_TOGETHER if saved == list(_TOGETHER) else _SEPARATE)

    def _on_shapes_changed(self):
        if not self.toc.built:
            return
        with working():
            self.refresh()
        self._re_aim_every_button()

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
        return self.library.reading.image_index

    def name_search_on_screen(self, query: str, scope: _SearchScope) -> None:
        self._folder_path.show_search(f"Search: “{query}” in ", scope.steps)
        self._folder_actions.show_folder(None)
        self._avg_label.setText("")
        self._experiments_bar.hide()

    def show_search_results(self, tiles, terms) -> None:
        self._gallery_pane.show_search_results(tiles, terms)

    def search_results_drawn(self) -> None:
        self._re_aim_every_button()
        self._navigation.record()

    def suppress_history(self):
        return self._navigation.off_the_record()

    def selected_prompt_id(self) -> str | None:
        return self._selected["prompt_id"] if self._selected else None

    def pane_holds(self, prompt_id: str) -> bool:
        return prompt_id in self._gallery_pane.listed_prompt_ids()

    def show_folder(self, key: str) -> bool:
        row = self.toc.item_for(key)
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
        self._re_aim_every_button()

    def hand_pane_back(self) -> None:
        self._on_folder_selected(self._tree.currentItem(), None)

    def search_scope(self) -> _SearchScope:
        item = self._tree.currentItem()
        if self._current_collection_key() is not None:
            rows = self._gallery_pane.selected_collection_rows() or []
            return _SearchScope(tuple(self.toc.path_steps(item)),
                                {row["prompt_id"] for row in rows})
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        if group is None:
            return self.everything_scope()
        return _SearchScope(tuple(self.toc.path_steps(item)),
                            {row["prompt_id"] for row in gallery.rows_under(group)})

    def everything_scope(self) -> _SearchScope:
        return _SearchScope((PathStep(gallery.ALL_LABEL, None),), self.library.live_ids)

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

    def remembered_session_slideshows(self) -> dict:
        return self._slideshows.remembered_regions()

    def remember_session_slideshows(self, saved) -> None:
        self._slideshows.remember_regions(saved)

    def how_many(self) -> int:
        return self._generate_pane.how_many()

    def set_how_many(self, count) -> None:
        self._generate_pane.set_how_many(count if count in HOW_MANY else HOW_MANY[0])

    def request_auto_generate(self) -> bool:
        return self._generate_pane.request_auto_generate()

    def set_request_auto_generate(self, on) -> None:
        self._generate_pane.set_request_auto_generate(on is True)

    def _showing_search(self) -> bool:
        return self._gallery_pane.showing_search()

    def _on_folder_selected(self, current, _previous):
        if self.toc.picked_together is not None:
            return
        self._search.sync_placeholder()
        if self._search.query and not self._navigation.suppressed:
            self._search.follow_the_folder()
            self._search.run()
            return
        self._re_aim_every_button()
        base, shape = _split_collection_key(self.toc.selected_folder_key())
        collection = folder_collection(base)
        self._experiments_bar.setVisible(collection is not None
                                         and collection.which == _EXPERIMENTS_KEY)
        if current is None:
            self._folder_path.set_display("")
            self._folder_actions.show_folder(None)
            self._avg_label.setText("")
            self._gallery_pane.show_empty()
            self._re_aim_every_button()
            return
        if collection is not None:
            self._open_collection(collection, shape, current)
            return
        group = current.data(0, _GROUP_ROLE)
        here = self.toc.selected_folder_key()
        self._note_folder_visit(here if group is not None else None)
        self._folder_path.show_folder(self.toc.path_steps(current))
        self._update_folder_average(group)
        self._show_group_contents(group, current)
        landed = self._land_on_the_first_item()
        if group is not None:
            self._navigation.record(landed)
        self._re_aim_every_button()

    def _land_on_the_first_item(self) -> str | None:
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
        self._folder_path.show_folder(self.toc.path_steps(item),
                                      mark=collection_mark(collection.which))
        self._folder_actions.show_folder(None)
        self._avg_label.setText("")
        self._clear_metadata()
        self._gallery_pane.show_collection(collection.key, shape)
        self._navigation.record()

    def _show_group_contents(self, group, item):
        self._folder_actions.show_folder(group)
        if isinstance(group, gallery.SettingsGroup):
            self._gallery_pane.show_thumbnails(group)
        elif isinstance(group, gallery.CustomCollection):
            self._gallery_pane.show_custom_collection(group)
        else:
            self._gallery_pane.show_folder_tiles(gallery.child_groups(group),
                                            collections=self.toc.collections_in(item))

    def _go_to_folder(self, key: str):
        item = _row_under(self._tree.currentItem(), key) or self.toc.item_for(key)
        if item is not None:
            self._search.leave()
            self._tree.setCurrentItem(item)

    def _on_tree_selection_changed(self):
        groups = self._selected_groups()
        if len(groups) > 1:
            self.toc.picked_together = gallery.selection_group(groups)
            self._show_selection()
            return
        was_multi = self.toc.picked_together is not None
        self.toc.picked_together = None
        if was_multi:
            self._on_folder_selected(self._tree.currentItem(), None)
        else:
            self._re_aim_every_button()

    def _selected_groups(self) -> list:
        return [group for key in self._tree.selected_folder_keys()
                if (group := self.group_for_key(key)) is not None]

    def _show_selection(self):
        group = self.toc.picked_together
        self._experiments_bar.hide()
        self._folder_path.set_display(group.label)
        self._folder_actions.show_folder(None)
        self._update_folder_average(group)
        self._gallery_pane.show_custom_collection(group)
        self._re_aim_every_button()

    def _restore_multi_selection(self, keys: list[str]):
        items = [item for key in keys if (item := self.toc.item_by_key.get(key)) is not None]
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

    def _note_folder_visit(self, key: str | None):
        if not self._navigation.suppressed and key is not None:
            self.toc_editing.note_visit(key)

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
        return self._why_no_more_can_be_made(group) is None

    @property
    def _live_jobs(self) -> dict:
        return self._jobs.jobs

    @property
    def _selected(self) -> dict | None:
        return self._selected_row

    def selected_folder_key(self) -> str | None:
        return self.toc.selected_folder_key()

    def current_group(self):
        if self.toc.picked_together is not None:
            return self.toc.picked_together
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
            modify_batch=(self._modify_batch_tile_for(group)
                           if self._can_modify_batch(group) else None),
            generating=None if job is None else self._generating_tile_for(group.key, job))

    def _forget_generating_tile(self):
        self._generating_tile = None

    def _generating_tile_for(self, key: str, job) -> GeneratingTile:
        tile = GeneratingTile(job,
                              populating=self._populate.is_active(key),
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
        populate = self._populate.is_active(key)
        discard = menu.addAction(CANCEL_TEXT)
        discard.setToolTip(cancel_tooltip(populate))
        stop = None
        if populate:
            stop = menu.addAction(stop_populate_text())
            stop.setToolTip(stop_populate_tooltip())
        chosen = menu.exec(global_pos)
        if chosen is discard:
            self._cancel_reroll(key)
        elif stop is not None and chosen is stop:
            self._populate.stop(key)
            self._cancel_reroll(key)

    def _can_modify_batch(self, group) -> bool:
        return self._can_reroll(group) and bool(self._modify_batch_rows(group))

    @staticmethod
    def _modify_batch_rows(group) -> list[dict]:
        if not isinstance(group, gallery.SettingsGroup):
            return []
        return [row for row in group.rows if gallery.produced_output(row)]

    def _modify_batch_tile_for(self, group) -> ModifyBatchTile:
        tile = ModifyBatchTile()
        tile.clicked.connect(lambda g=group: self._open_modify_batch(g))
        return tile

    def _open_modify_batch(self, group):
        rows = self._modify_batch_rows(group)
        workflow = WORKFLOW_REGISTRY.get(rows[0].get("workflow_name") or "") if rows else None
        if workflow is None or self._client is None:
            return
        thumbnails = [row.get("thumbnail_path") for row in rows]
        self._clear_reroll_selection()
        self._generate_pane.open_modify_batch(group.key, group.label, workflow.name,
                                              filled_params(rows[0], workflow), thumbnails)

    def _on_modify_batch_requested(self, folder_key: str, workflow_name: str, params: dict):
        wf = WORKFLOW_REGISTRY.get(workflow_name)
        item = self.toc.item_for(folder_key)
        group = item.data(0, _GROUP_ROLE) if item is not None else None
        rows = self._modify_batch_rows(group) if group is not None else []
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
            self._db.record_request(NewRequest(
                prompt_id=prompt_id, source_prompt_id=row["prompt_id"], heard="",
                old_positive=was.get("positive_prompt", ""),
                old_negative=was.get("negative_prompt", ""),
                new_positive=run.get("positive_prompt", ""),
                new_negative=run.get("negative_prompt", ""),
            ))
        logger.info("Requested changes to %s: %d of %d images queued into %s",
                    folder_key, launched, len(rows), key)
        if launched:
            self._stand_on_the_run_in(key, rebuild=True)

    def _job_source_image(self, job) -> str | None:
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

    def _start_populate_reroll(self, key: str) -> bool:
        return self._start_reroll(key, from_populate=True)

    def _start_reroll(self, key: str, *, from_populate: bool = False) -> bool:
        if self._client is None:
            return False
        if key in self._live_jobs:
            return True
        settings = self._populate_settings.get(key)
        if settings is not None:
            workflow, params = settings
            self._jobs.start_prepared(key, workflow,
                                      randomize_seeds(params, workflow.seed_keys()))
        else:
            self._jobs.start_reroll(key, self.group_for_key(key), self.library.reading.image_rows)
        self._claim_launch(key)
        if not from_populate:
            self._select_reroll(key)
        else:
            self._note_populate_launch(key)
            if self._selected_reroll_key == key:
                self._enter_reroll_selection(key)
        return self._jobs.has(key)

    def _note_populate_launch(self, key: str):
        job = self._jobs.newest_job_for(key)
        if job is None:
            return
        self._populate_origins = {origin for origin in self._populate_origins
                              if self._jobs.job_for_origin(origin) is not None}
        self._populate_origins.add(job.origin)

    def _toggle_populate(self, checked: bool):
        group = self.current_group()
        if not checked:
            self._populate.stop_all()
        elif group is not None:
            self._begin_populate(group.key)
        self._re_aim_every_button()
        self._sync_cancel_buttons()

    def _begin_populate(self, key: str):
        self._capture_populate_settings(key)
        self._populate.start(key)
        if self._populate.is_active(key):
            self.toc_editing.set_folder_favorite(key, True)
        else:
            self._populate_settings.pop(key, None)

    def _capture_populate_settings(self, key: str):
        group = (self.current_group() if key == self.selected_folder_key()
                 else self.group_for_key(key))
        if not isinstance(group, gallery.SettingsGroup) or not group.rows:
            return
        workflow = WORKFLOW_REGISTRY.get(group.rows[0].get("workflow_name") or "")
        if workflow is not None:
            self._populate_settings[key] = (
                workflow, filled_params(group.rows[0], workflow))

    def _on_populate_stopped(self, key: str):
        self._populate_settings.pop(key, None)
        if key == self._selected_reroll_key and key not in self._live_jobs:
            self._clear_reroll_selection()
        self._re_aim_every_button()
        self._sync_cancel_buttons()

    def _sync_cancel_buttons(self):
        self._rerender_current_leaf()
        self.job_queue.update()
        self._reconcile_generating()

    def collection_label(self, key: str) -> str:
        return collection(key).label

    def stand_in_collection(self, key: str, shape: str | None) -> bool:
        item = self.toc.item_for(shaped_key(key, shape) if shape else key)
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

    def _go_to_populating_folder(self, _href: str):
        key = self._populate.active_key()
        if key is not None:
            self._stand_on_the_run_in(key, rebuild=True)

    def rows_to_play(self) -> list[dict]:
        rows = [] if self._in_the_trash() else self._gallery_pane.collection_rows()
        if rows is None:
            group = self.current_group()
            rows = gallery.rows_under(group) if group is not None else []
        return rows if self._showing_search() else what_plays_at(self.slideshow_location(), rows)

    def listing(self) -> Listing:
        pane = self._gallery_pane
        return Listing(location=self.slideshow_location(), rows=tuple(self.rows_to_play()),
                       shown=tuple(self.listed_prompt_ids()),
                       picked=tuple(self.selected_prompt_ids()),
                       subject=self.slideshow_subject(), shape=self.toc.shape_in_view(),
                       latest=pane.showing_latest() and not pane.showing_search())

    def slideshow_subject(self) -> str:
        if self._showing_search():
            return "these results"
        if self._current_collection_key() is not None:
            return self.toc.folder_path(self._tree.currentItem())
        return "this folder"

    def _re_aim_every_button(self) -> None:
        enhance = self._enhance.offer()
        self._buttons.apply(self.button_states())
        self._enhance.sync_pane(enhance)
        self._generate_pane.reread_folder_buttons()
        self._tree.offer_delete_on_picked_rows(
            self.toc.picked_together is None or bool(self.toc_editing.deletable_folders()))

    def button_states(self) -> ButtonStates:
        can_go_back, can_go_forward = self._trail
        undo_label = self._edits.undo_label()
        redo_label = self._edits.redo_label()
        populate_folder = self._populate.active_key()
        group = self.current_group()
        why_not = self._why_populate_cannot(group)
        can_populate = why_not is None
        elsewhere = (populate_folder is not None
                     and populate_folder != getattr(group, "key", None))
        return ButtonStates(
            back=Button(enabled=can_go_back, tip="Back"),
            forward=Button(enabled=can_go_forward, tip="Forward"),
            undo=Button(enabled=self._edits.can_undo(),
                        tip=f"Undo: {undo_label}" if undo_label else "Nothing to undo"),
            redo=Button(enabled=self._edits.can_redo(),
                        tip=f"Redo: {redo_label}" if redo_label else "Nothing to redo"),
            group=Button(visible=self.toc.picked_together is not None,
                         tip=GROUP_TIP),
            favorite=self._folder_switches.favorite_switch(),
            enhance=self._folder_switches.enhance_switch(),
            delete=self._delete_the_folder_offer(),
            slideshow=(Button(enabled=False, tip="Trash doesn't play as a slideshow")
                       if self._in_the_trash()
                       else Button(visible=self._slideshows.anything_to_play(),
                                   tip=f"Play {self.slideshow_subject()} as a slideshow")),
            populate=Button(enabled=can_populate or populate_folder is not None,
                        tip="" if elsewhere else self._populate_tip(why_not, populate_folder),
                        checked=populate_folder is not None),
            populate_tip=POPULATE_ELSEWHERE_TIP if elsewhere else "",
        )

    @staticmethod
    def _populate_tip(why_not: str | None, populate_folder: str | None) -> str:
        if populate_folder is not None:
            return "Populate is running in this folder — click to stop it"
        return why_not or ("Populate: repeatedly generate variations of this folder "
                           "until toggled off")

    def _why_populate_cannot(self, group) -> str | None:
        if not isinstance(group, gallery.SettingsGroup):
            return ("Populate works in a leaf folder, where every item shares its settings. "
                    "Open one to use it.")
        return self._why_no_more_can_be_made(group)

    def _why_no_more_can_be_made(self, group) -> str | None:
        if self._client is None:
            return "Populate needs ComfyUI, and Origenerator is not connected to it."
        if not group.rows:
            return "Populate has nothing to make more of: this folder is empty."
        if WORKFLOW_REGISTRY.get(group.rows[0].get("workflow_name") or "") is None:
            return "Populate can't make more of these: they were made outside Origenerator."
        if not gallery.rerollable(group.rows[0]):
            return "Populate can't make more of these: what they were made from is gone."
        return None

    def _favorite_the_picked_offer(self) -> Button:
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

    def _enhance_the_picked_offer(self) -> Button:
        offer = self._enhance.offer()
        return Button(enabled=offer.available, tip=offer.tip)

    def _delete_the_picked_offer(self) -> Button:
        count = len(self._gallery_pane.selected_ids)
        if self._in_the_trash():
            return Button(
                enabled=bool(count),
                tip=f"Permanently delete {count} item{'s' if count != 1 else ''}"
                if count else "Pick an item to delete permanently")
        if count:
            return Button(tip=f"Delete {count} item{'s' if count != 1 else ''}")
        return self._delete_the_folder_offer()

    def _delete_the_folder_offer(self) -> Button:
        folders = self.toc_editing.deletable_folders()
        if not folders:
            return Button(enabled=False, tip=ONLY_A_LEAF_IS_DELETED)
        if len(folders) == 1:
            return Button(tip=f"Delete folder “{folders[0].label}”")
        return Button(tip=f"Delete {len(folders)} folders")

    def _delete_the_open_folder(self):
        self.toc_editing.delete_folders(self.toc_editing.deletable_folders())

    def open_leaf_folder(self):
        group = self.current_group()
        if (self.toc.picked_together is not None or self._current_collection_key() is not None
                or not isinstance(group, gallery.SettingsGroup)):
            return None
        return group

    def leaf_folders(self) -> dict[str, list[dict]]:
        return self.library.reading.leaf_folders(self._tree.shapes)

    def highest_id_listed(self) -> int:
        return self.library.reading.highest_id

    def folder_meta(self) -> dict[str, dict]:
        return self.library.folder_meta

    def _switch_the_open_folders_favorite(self, on: bool):
        leaf = self.open_leaf_folder()
        if leaf is not None:
            self.toc_editing.set_folder_favorite(leaf.key, on)
        self._re_aim_every_button()

    def _switch_the_open_folders_enhance(self, on: bool):
        leaf = self.open_leaf_folder()
        if leaf is not None:
            self._folder_switches.set_enhancing(leaf.key, on)
        self._re_aim_every_button()

    def _favoritable_folder(self):
        if self.toc.picked_together is not None or not takes_a_favorite(self.current_group()):
            return None
        return self.current_group()

    def _all_favorites(self, prompt_ids) -> bool:
        rows = [self._db.get_generation(pid) for pid in prompt_ids]
        return all(row and row.get("starred") for row in rows)

    def _favorite_selection(self):
        if self._gallery_pane.selected_ids and not self._in_the_trash():
            pids = self.selected_prompt_ids()
            self.set_items_favorite(pids, not self._all_favorites(pids))
            return
        group = self._favoritable_folder()
        if group is not None:
            self.toc_editing.toggle_favorite(group.key)

    def close_the_slideshows(self) -> None:
        self._slideshows.close_the_slideshows()

    def fill_the_region(self, shape: str) -> None:
        self._slideshows.fill_the_region(shape)

    def queue_request(self, row, workflow, params, spoken, revision) -> tuple[str, str]:
        name = row.get("workflow_name") or ""
        revised = {**params, **dict(revision.settings),
                   **{key: boxed_as_typed(name, params, key, said) for key, said in (
                       ("positive_prompt", revision.positive), ("negative_prompt", revision.negative))}}
        key = self.folder_key_for(name, revised)
        if not self._jobs.start_prepared(key, workflow, revised):
            return "couldn't queue the request — see the log", ERROR
        job = self._jobs.newest_job_for(key)
        logger.info("Request on %s: term %s, queued as %s", row.get("prompt_id"),
                    revision.action, job.prompt_id)
        self._db.record_request(NewRequest(
            prompt_id=job.prompt_id, source_prompt_id=row["prompt_id"],
            heard=spoken.heard, asked=spoken.text, term=revision.term,
            polarity=revision.polarity, action=revision.action,
            old_positive=params.get("positive_prompt", ""),
            old_negative=params.get("negative_prompt", ""),
            new_positive=revised["positive_prompt"], new_negative=revised["negative_prompt"],
            turns=(revision.turn(spoken.text),),
        ))
        self.refresh()
        return revision.answer or "Request submitted", INFO

    def delete_enhance_versions(self, prompt_id: str, filenames: list):
        row = self._db.get_generation(prompt_id)
        if row is None or not self._edits.delete_enhance_versions(row, filenames):
            return
        self.refresh()
        updated = self._db.get_generation(prompt_id)
        if updated is not None:
            self._generate_pane.refresh_displayed(updated, self.library.reading.image_rows)
            self._slideshows.note_versions_deleted(updated)

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
        if row is not None and self._edits.trash(row):
            self._re_aim_every_button()

    def trash_file(self, path: str, already_at: str | None = None):
        try:
            self._edits.trash_file(path, already_at)

        except OSError:
            logger.exception("Could not send %s to Trash", path)
            return
        self.refresh()
        self._re_aim_every_button()

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
            self._jobs.reroll_image_seed(key, row, self.library.reading.image_rows)
        self._select_reroll(key)

    def off_thread(self, work, done):
        run_off_thread(work, done, owner=self)

    def enhance_offer_changed(self) -> None:
        self._re_aim_every_button()

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
        return self.library.reading.image_rows

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
        if (latest := self.toc.collection_item(_LATEST_KEY, self._launched_side(key))) is not None:
            self._pending_combine_key = key
            self._tree.setCurrentItem(latest)

    def _launched_side(self, key: str) -> str:
        job = self._jobs.job_for(key)
        asked = requested_shape(job.params) if job is not None else None
        return _shape_holding(asked, self._tree.shapes) or self.toc.shape_in_view()

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
        row = self._db.get_generation(job.prompt_id)
        tab = tabs.tab_watching(key) or tabs.tab_that_launched(job.origin)
        if tab is None:
            front = tabs.current_generate_tab()
            if (front is not None and front.workflow_and_signature() is not None
                    and self._config_folder_key(front.current_config()) == key):
                tab = front
            else:
                tab = tabs.landing_tab()
                if row is not None:
                    tab.show_running_generation(row)
            if job.origin not in tab.launched_runs():
                tab.note_launched(job.origin)
            tabs.pin_tab(tab)
            self._reconcile_generating()
        tab.watch_folder(key, row, job.last_preview, self._wait_note(key),
                           self._job_made_from(job, self.animated_preview))
        tabs.setCurrentWidget(tab)

    def _restore_reroll_selection(self, key: str | None):
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
        self._populate.note_canceled(key)
        self._after_a_job_ended_unfinished(key)

    def _cancel_job(self, prompt_id: str):
        key = self._job_folder_key(self._jobs.job_for_prompt(prompt_id))
        self._jobs.cancel_job(prompt_id)
        if key is not None:
            self._populate.note_canceled(key)
            self._after_a_job_ended_unfinished(key)

    def _after_a_job_ended_unfinished(self, key: str):
        self._abandon_reroll_preview(key)
        self._rerender_current_leaf()
        self._reconcile_generating()
        self._enhance.reconcile()

    def _abandon_reroll_preview(self, key: str):
        if key == self._selected_reroll_key:
            self._clear_reroll_selection()
            self._selected_row = None
        if not self._jobs.has(key):
            for tab in self._generate_pane.watchers_of(key):
                tab.stop_watching()

    def _on_reroll_finished(self, key: str, prompt_id: str, origin: str = ""):
        run = origin or prompt_id
        launcher = (None if run in self._populate_origins
                    else self._generate_pane.tab_that_launched(run))
        self._populate_origins.discard(run)
        finished_row = self._db.get_generation(prompt_id)
        if (finished_row is not None
                and finished_row.get("source") == GenerationSource.EXPERIMENT):
            self.refresh()
            self._populate.note_finished(key)
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
        if key == self._selected_reroll_key and not self._populate.is_active(key):
            self._clear_reroll_selection()
        self._slideshows.note_landed(finished_row)
        self.refresh()
        self._slideshows.note_finished(finished_row)
        self._show_reroll_result_in_tab(finished_row, launcher)
        if folded:
            self._generate_pane.refresh_displayed(finished_row, self.library.reading.image_rows)
        self._show_landed_to_watchers(key, finished_row, launcher)
        if key == self._pending_combine_key:
            self._pending_combine_key = None
            item = self.toc.item_for(key)
            if item is not None:
                self._tree.setCurrentItem(item)
        self._reconcile_generating()
        self._populate.note_finished(key)
        self._enhance.enhance_when_wanted(finished_row)
        self._enhance.reconcile()

    def _show_reroll_result_in_tab(self, finished_row: dict | None, launcher):
        if launcher is not None and finished_row is not None \
                and gallery.produced_output(finished_row):
            launcher.show_completed_result(finished_row, self.library.reading.image_rows)

    def _show_landed_to_watchers(self, key: str, finished_row: dict | None, launcher):
        if finished_row is not None and gallery.produced_output(finished_row):
            self._generate_pane.show_landed(key, finished_row, besides=launcher)

    def _on_reroll_failed(self, key: str, message: str = ""):
        self._populate.note_failed(key)
        self._after_a_job_ended_unfinished(key)
        self._generation_failed.say(format_execution_error(message))

    def _rerender_current_leaf(self):
        group = self.current_group()
        if isinstance(group, gallery.SettingsGroup):
            place = self._gallery_pane.place()
            self._gallery_pane.show_thumbnails(group)
            self._gallery_pane.return_to(place)
            self._folder_actions.show_folder(group)

    def listed_prompt_ids(self) -> list[str]:
        return self._gallery_pane.listed_prompt_ids()

    def _tell_of_the_queue(self, items: list, foreign_total: int) -> None:
        self._generate_pane.note_in_flight(items)
        self._slideshows.note_queue(items, foreign_total)
        self._slideshows.note_in_flight(items)

    def selected_folder(self) -> str | None:
        return self.toc.selected_folder_key() or self._pending_key

    def select_folder(self, key: str | None):
        self._pending_key = key or None

    def selected_generation(self) -> str | None:
        if self._selected:
            return self._selected.get("prompt_id")
        return self._pending_selection

    def select_generation(self, prompt_id: str | None):
        self._pending_selection = prompt_id or None

    def picks(self) -> Picks:
        return self._gallery_pane.picks()

    def pick_again(self, picks: Picks) -> None:
        self._gallery_pane.pick_again(picks)

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
        offer_copy_names_above_a_line(
            menu, [self._item_names.of(row["prompt_id"]) for row in rows])
        all_favorites = all(row.get("starred") for row in rows)
        favorite_action = menu.addAction(("Unfavorite" if all_favorites else "Favorite") + suffix)
        open_custom = saved_custom_collection(self.current_group())
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
            self.toc_editing.remove_from_collection(open_custom, items=held_here)
        elif enhance_action is not None and chosen is enhance_action:
            self._enhance.enhance_items(to_enhance)
        elif cancel_action is not None and chosen is cancel_action:
            self._enhance.cancel_for(rows)
        elif chosen is delete_action:
            self._delete_rows(rows)

    def _can_open_containing_folder(self, row: dict) -> bool:
        if row.get("deleted_at") is not None:
            return False
        leaf = self.toc.leaf_by_id.get(row.get("prompt_id"))
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
        for row in self.library.reading.rows:
            if row["prompt_id"] in ids:
                row["starred"] = 1 if favorite else 0
        if not self._redrew_the_favorites_collection():
            self._gallery_pane.refresh_corners()
        self._generate_pane.reconcile_previews(self.library.live_ids)
        if ids & self._gallery_pane.selected_ids:
            self._re_aim_every_button()

    def _recount_the_collections(self) -> None:
        for shape in self._tree.shapes:
            self.toc.set_collection_counts(shape, self._gallery_pane.collection_counts(shape))

    def _draw_a_folders_favorite(self, key: str, favorite: bool) -> None:
        if not self._redrew_the_favorites_collection():
            self._gallery_pane.mark_folder_favorite(key, favorite)

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
        if self._in_the_trash():
            self.purge_from_trash(self.selected_prompt_ids())
            return
        if self._gallery_pane.selected_ids:
            rows = [self._db.get_generation(pid) for pid in self.selected_prompt_ids()]
            self._delete_rows([r for r in rows if r])
            return
        self.toc_editing.delete_folders(self.toc_editing.deletable_folders())

    def _copy_names_of_the_selection(self):
        if self._gallery_pane.selected_ids:
            copy_names([self._item_names.of(pid) for pid in self.selected_prompt_ids()])
        elif self.toc.picked_together is not None:
            copy_names(names_of_the_picked_folders(self.toc.picked_together))
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
        offer_copy_names_above_a_line(menu, [self._item_names.of(pid) for pid in ids])
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
        self._edit_then_redraw(
            lambda: trash_collection.restore_from_trash(self._db, self._jobs, prompt_ids,
                                                        self._edits.restore_deleted,
                                                        self.image_config_index()),
            lambda restored: restored and self.go_to_generation(restored),
            failed="Restore failed", could_not="Could not restore the selected item(s)",
            logged=f"Failed to restore {len(prompt_ids)} deleted item(s)")

    def _edit_then_redraw(self, edit, then, *, failed: str, could_not: str, logged: str):
        error = None
        with working():
            try:
                outcome = edit()
            except Exception as e:
                logger.exception(logged)
                error = e
            else:
                self._gallery_pane.clear_selection()
                self.refresh()
                then(outcome)
        if error is not None:
            QMessageBox.warning(self, failed, f"{could_not}:\n\n{error}")

    def purge_from_trash(self, prompt_ids):
        if not prompt_ids:
            return
        count = len(prompt_ids)
        plural = "s" if count != 1 else ""
        if not self._confirm(
            f"Permanently delete {count} item{plural}? This cannot be undone."
        ):
            return
        self._edit_then_redraw(
            lambda: self._edits.purge_deleted(prompt_ids), lambda _outcome: None,
            failed="Delete failed", could_not="Could not permanently delete the selected item(s)",
            logged=f"Failed to permanently delete {count} item(s)")

    def _release_held_media(self, paths, *, the_item_stays: bool = False):
        """Drop every on-screen view of ``paths``: Windows won't move a file while a handle on it is open."""
        self._generate_pane.release_media(paths)
        self._slideshows.release_media(paths, the_item_stays=the_item_stays)

    def _delete_rows(self, rows):
        if not rows:
            return
        self._edit_then_redraw(
            lambda: self._edits.delete_rows(rows), lambda _outcome: self._re_aim_every_button(),
            failed="Delete failed", could_not="Could not delete the selected item(s)",
            logged=f"Failed to delete {len(rows)} generation(s)")

    def _undo(self):
        if not self._edits.can_undo():
            return
        focus = self._edits.undo()
        self._gallery_pane.clear_selection()
        self.refresh()
        if focus:
            self.go_to_generation(focus)
        self._re_aim_every_button()

    def _redo(self):
        if not self._edits.can_redo():
            return
        self._edits.redo()
        self._gallery_pane.clear_selection()
        self.refresh()
        self._re_aim_every_button()

    def _confirm(self, text: str) -> bool:
        return asked_to_delete(self, text)

    def row_for(self, prompt_id: str) -> dict | None:
        return self.library.row_for(prompt_id)

    def _on_thumbnail_clicked(self, prompt_id: str):
        if not self._show_generation(prompt_id):
            return
        self._navigation.record(prompt_id)

    def _show_generation(self, prompt_id: str) -> bool:
        row = self.row_for(prompt_id)
        if not row:
            return False
        self._select_saved_generation(row)
        self._generate_pane.load_selection(row, self.library.reading.image_rows)
        return True

    def _select_saved_generation(self, row: dict):
        self._clear_reroll_selection()
        self._selected_row = row

    def animated_preview(self, row: dict) -> str | None:
        thumb_dir = self._edits.thumb_dir
        return (gallery.animated_preview_if_made(row, self._edits.places, thumb_dir)
                if thumb_dir is not None else None)

    @looking_once
    def follow_link(self, prompt_id: str):
        self._search.leave()
        self.go_to_generation(prompt_id)

    def go_to_file(self, path: str):
        prompt_id = self._db.generation_of_file(path)
        if prompt_id is not None:
            self.show_generation(prompt_id)

    def show_generation(self, prompt_id: str) -> None:
        if self._fun_time is not None:
            ask_for_origenerator_mode(self._fun_time.dashboard_cmd_file)
        self.follow_link(prompt_id)

    def go_to_generation(self, prompt_id: str):
        prompt_id = gallery.landing_for(prompt_id, self.library.reading.rows, self.image_config_index())
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
        leaf = self.toc.leaf_by_id.get(prompt_id)
        if leaf is not None:
            return leaf
        row = self._db.get_generation(prompt_id)
        if row is None:
            held = self.row_for(prompt_id)
            return self.toc.item_for(shaped_key(_TRASH_KEY, row_shape(held))) if held else None
        key = self.folder_key_of(row)
        return self.toc.item_for(key) if key else None

    def _current_collection_key(self) -> str | None:
        key = self.selected_folder_key()
        return key if folder_collection(_base_of(key)) is not None else None

    def _clear_metadata(self):
        self._selected_row = None

    def pin_generate_tab(self):
        self._generate_pane.pin_current_tab()


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
    return _PollFacts(histories, backlogs, read_foreign_queue(client), executing)


