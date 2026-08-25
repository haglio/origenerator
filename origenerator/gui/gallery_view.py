import json
import logging
import random
from typing import NamedTuple
from functools import partial

from PyQt6.QtWidgets import (
    QWidget, QFrame, QHBoxLayout, QVBoxLayout, QLabel,
    QToolButton, QSplitter,
    QMenu, QInputDialog, QAbstractItemView, QMessageBox, QApplication,
    QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox,
)
from PyQt6.QtCore import Qt, QEvent, QThreadPool, QTimer, QPoint, QSize, pyqtSignal

from origenerator import (
    evolver_export, gallery, prompt_edit, recipe_match, recovery, search, timing,
)
from origenerator.gui import corner_controls, icons
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
from origenerator.fun_time_mode import FunTimeSession, SHOW_TITLES, region_for_items
from origenerator.gui.show_filters import ShowFilters
from origenerator.gui.find_bar import FindBar
from origenerator.gui.inflight import EnhancingRun, InFlightItem
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_tree import TREE_KEY_ROLE as _TREE_KEY_ROLE
from origenerator.gui.split_folder_tree import SplitFolderTree
from origenerator.gui.prompt_find import PromptFind
from origenerator.gui.combine_panel import CombinePanel
from origenerator.gui.auto_generate_controller import AutoGenerateController
from origenerator.gui.reroll_controller import RerollController
from origenerator.gui.request_worker import RevisionWorker, ReviseTask
from origenerator.gui.slideshow_view import SlideshowView
from origenerator.prompt_edit import apply_request
from origenerator.slideshow import DEFAULT_IMAGE_DWELL_MS, ShowState, in_order
from origenerator.voice.app_commands import (
    AppCommand, DialSetting, app_command_bias, match_app_command,
)
from origenerator.voice.commands import (
    ShelfCommand, ShowControl, SurfaceCommand, match_voice_command,
    sided_app_command, split_side, voice_command_bias,
)
from origenerator.voice.dictation import COMPLETED, RequestDictation, request_bias
from origenerator.voice.show_commands import (
    ShowCommand, match_show_command, show_command_bias,
)
from origenerator.voice.dictation import COMPLETED, RequestDictation, request_bias
from origenerator.voice.show_commands import ShowCommand
from origenerator.voice.show_commands import ShowCommand
from origenerator.voice.steering import VoiceSteering
from origenerator.gui.reroll_prompt import (
    REROLL_BOTH, REROLL_IMAGE, REROLL_VIDEO, offer_reroll,
)
from origenerator.gui.folder_request_tile import FolderRequestTile
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
    BrowserPane, BrowserScrollArea, SEARCH_DRAW_LIMIT, SearchTile,
)
from origenerator.gui.gallery_tree import (
    GalleryTree,
    SideModel,
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
from origenerator.gui.orientation import (
    ORIENTATIONS as _ORIENTATIONS,
    ORIENTATION_LABELS as _ORIENTATION_LABELS,
    LANDSCAPE as _LANDSCAPE,
    base_of as _base_of,
    filter_rows,
    oriented_key,
    orientation_of as _orientation_of,
    requested_orientation,
    split_key as _split_shelf_key,
    split_rows,
)
from origenerator.gui.looping_preview import set_previews_paused
from origenerator.navigation import Location, NavigationHistory
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.derived_size import resolve_input_image_path

ensure_shared_ui_on_path()
from shared_ui.check_box import CheckBox
from shared_ui.colors import BORDER_SUBTLE
from shared_ui.spacing import BUTTON_GAP, BUTTON_ICON, BUTTON_ROW_GAP

logger = logging.getLogger(__name__)


def _shared_hud_widget():
    """The players' HUD widget, or ``None`` where player_core has not got one.

    Reached for here rather than imported at module top, and reached for at all
    rather than assumed, for the same reason: the panel lives in the newest
    player_core, while this app's other reaches into that sibling (genau's
    console, the stroke) resolve against an older checkout perfectly well.  A
    session names the checkout it wants on PYTHONPATH; a plain launch walks up
    to the primary one, and that one only grows the panel when it lands.

    So a checkout without it starts, browses and generates exactly as before,
    and a show opened on it is the show that used to be: its own neighbor
    stills and position plate, no map.  Losing the panel is a bad afternoon;
    losing the fullscreen view over the panel would be a dead app.
    """
    try:
        from origenerator.gui.show_hud import ShowHud
    except ImportError:
        logger.warning(
            "This player_core carries no shared HUD, so shows wear none",
            exc_info=True)
        return None
    return ShowHud


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


class _Running(NamedTuple):
    """What the app is doing under its own steam — everything Esc turns off, and
    everything a second Esc turns back on.

    Not the mic, which Esc never touches, and not the work already in flight: a
    generation that is rendering lands either way. What is here is the standing
    instructions — the device, the loop, the show, the sound.
    """

    osr2: bool = False       # the device switch: a funscript, or the stroke behind it
    stroke: bool = False     # the bare stroke, running with the switch off
    auto: str | None = None  # the folder looping, if one is
    audio: bool = False      # the audio bed
    show: bool = False       # a fullscreen slideshow is up
    # ...and the pass it was playing, to take up again. A show following a
    # generation in flight has none, which is why this is asked separately from
    # whether there is a show at all.
    show_pass: tuple | None = None

    @property
    def anything(self) -> bool:
        return bool(self.osr2 or self.stroke or self.auto or self.audio or self.show)


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


# The whole answer to "genau it" on a picture that has already been Genau'd:
# said in the show's corner, and nothing runs. Deliberately not a dialog — the
# combine panel asks which seed to re-roll when a press would reproduce a run,
# and that question thrown over the picture someone is talking to is the one
# thing that must never appear (:meth:`GalleryView._generate_combination`).
ALREADY_GENAUD = "🎤 already Genau'd"

# What a spoken command about the picture is asking for, in the words its "no
# picture on screen" answer names it by. A fix names its own parts instead, and
# "enhance" never gets here with no show — it is a bank button as well as an
# order about the picture, and with no picture filling the screen it is the
# button (see :meth:`GalleryView._on_picture_command`).
_VOICE_WANTS = {
    gallery.GENAU_COMMAND: "a Genau clip",
}


def _match_voice_command(text: str):
    """The one command an utterance is, or ``None`` — the vocabularies that
    tolerate a filler word or two, in the order they are tried.

    The show's own controls, then everything said about the picture on screen
    (:func:`~origenerator.gallery.voice_commands.match_command`, which owns that
    half's order). Each matcher is strict about its own shape and none can claim
    another's — a show command names the slideshow, a fix leads with "fix" — so
    the order only decides which is asked first. Everything unclaimed falls
    through to a prompt rewrite, which is why none of them may be loose.

    The bare vocabulary (:mod:`origenerator.voice.app_commands`) is not here.
    It matches whole utterances only, which is strict enough to be asked ahead
    of an opening request — so the mic is given it separately, as its
    ``bare_matcher``.
    """
    return match_show_command(text) or gallery.match_command(text)


# The shelf each spoken shelf name stands you in. What to call it back comes
# from ``_SHELF_LABELS``, so a row renamed is renamed in one place.
_VOICE_SHELVES = {
    AppCommand.RECENTS: _RECENTS_KEY,
    AppCommand.STARRED: _STARRED_KEY,
    AppCommand.EXPERIMENTS: _EXPERIMENTS_KEY,
    AppCommand.REQUESTS: _REQUESTS_KEY,
    AppCommand.TRASH: _TRASH_KEY,
}

# The stroke knob each spoken word turns, as (the driver's method, its argument
# or ``None`` for a method that takes none) — the very moves the keys make (see
# :mod:`origenerator.gui.stroke_hud`), said out loud instead of pressed.
_VOICE_STROKE = {
    AppCommand.SPEED_UP: ("adjust_speed", 5),
    AppCommand.SPEED_DOWN: ("adjust_speed", -5),
    AppCommand.AMP_UP: ("adjust_amplitude", 10),
    AppCommand.AMP_DOWN: ("adjust_amplitude", -10),
    AppCommand.CENTER_UP: ("adjust_center", 5),
    AppCommand.CENTER_DOWN: ("adjust_center", -5),
    AppCommand.NEXT_SHAPE: ("cycle_shape", 1),
    AppCommand.PREVIOUS_SHAPE: ("cycle_shape", -1),
    AppCommand.CRUISE: ("toggle_cruise", None),
    AppCommand.CRUISE_ON: ("set_cruise", True),
    AppCommand.CRUISE_OFF: ("set_cruise", False),
    AppCommand.OFFSET: ("quarter_offset", None),
}

# The driver's setter for each dial the numeric grid names
# (:class:`~origenerator.voice.app_commands.DialSetting`), so "amp fifty" puts
# the dial at fifty rather than walking it there ten at a time.
_VOICE_DIALS = {
    "speed": "set_speed",
    "amp": "set_amplitude",
    "center": "set_center",
}

# The app-wide switch each spoken word flips, as (the button's attribute, the
# state asked for — ``None`` flips whichever way it is standing — and what the
# answer calls it). Set through the button rather than around it, so a spoken
# switch and a clicked one are the same event and the bank shows both.
_VOICE_SWITCHES = {
    AppCommand.AUTO: ("_auto_btn", None, "auto-generate"),
    AppCommand.AUTO_ON: ("_auto_btn", True, "auto-generate"),
    AppCommand.AUTO_OFF: ("_auto_btn", False, "auto-generate"),
    AppCommand.AUDIO: ("_audio_btn", None, "the audio bed"),
    AppCommand.AUDIO_ON: ("_audio_btn", True, "the audio bed"),
    AppCommand.AUDIO_OFF: ("_audio_btn", False, "the audio bed"),
    AppCommand.DRIVE: ("_osr2_btn", None, "the OSR2"),
    AppCommand.DRIVE_ON: ("_osr2_btn", True, "the OSR2"),
    AppCommand.DRIVE_OFF: ("_osr2_btn", False, "the OSR2"),
    AppCommand.MIC_OFF: ("_mic_btn", False, "the mic"),
}

# The bank button each spoken word presses with no show up, as (the button, the
# action it runs, what to say when it cannot run — ``None`` to use the button's
# own tooltip, which for most of them already says why: "Nothing to undo",
# "Nothing here to star"). Only the two whose tips are bare labels, and Group,
# whose tip explains the button rather than refusing it, carry their own words.
_VOICE_BANK_ACTIONS = {
    AppCommand.BACK: ("_back_btn", "_go_back", "nowhere back"),
    AppCommand.FORWARD: ("_forward_btn", "_go_forward", "nowhere forward"),
    AppCommand.CULL: ("_delete_btn", "_delete_selection", None),
    AppCommand.STAR: ("_star_btn", "_star_selection", None),
    AppCommand.UNDO: ("_undo_btn", "_undo", None),
    AppCommand.REDO: ("_redo_btn", "_redo", None),
    AppCommand.GROUP: ("_group_btn", "_group_selection", "pick some folders first"),
}

# What a spoken word does to the enhanced-only filter. Both ways round rather
# than one toggle — see AppCommand.FILTER_ENHANCED.
_VOICE_FILTERS = {
    AppCommand.FILTER_ENHANCED: True,
    AppCommand.FILTER_OFF: False,
}

# The words that are about the slide on screen when there is one. The rest of
# the bank (undo, redo, group) is the gallery's whether or not a show covers it:
# undoing a cull you regret is exactly a thing to do mid-show.
_ABOUT_THE_SLIDE = frozenset({
    AppCommand.BACK, AppCommand.FORWARD, AppCommand.CULL,
    AppCommand.LOCK, AppCommand.UNLOCK, AppCommand.STAR,
})


class GalleryView(QWidget):
    def __init__(self, db: Database, parent=None, *,
                 client: ComfyUIClient | None = None,
                 actions: GalleryActions | None = None,
                 osr2_stroke: Osr2StrokeDriver | None = None,
                 ambient_audio: AmbientAudio | None = None,
                 search_expander: SearchExpander | None = None,
                 fun_time: FunTimeSession | None = None):
        super().__init__(parent)
        self._db = db
        self._client = client
        # The Fun Time session hosting this app, or None standalone.  Inside one
        # the layout goes vertical, the fullscreen surfaces land on the satellite
        # regions, and the OSR2 is Fun Time's alone (see origenerator.fun_time_mode).
        self._fun_time = fun_time
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
        # None inside a Fun Time session: the OSR2 there is the main player's
        # alone, so no surface of this app may reach the device.
        if fun_time is not None:
            self._osr2_stroke = None
        else:
            self._osr2_stroke = osr2_stroke if osr2_stroke is not None else Osr2StrokeDriver(parent=self)
        # How long a slide holds the screen, app-wide: Genau's console shows
        # it as clip seconds and sets it, from whichever window the console
        # is on — including this one, with nothing playing, where it is what
        # the next slideshow opens at.
        self._pace = SlideshowPace(parent=self)
        # What a show may play — the favorites, the enhanced ones, or all of
        # it. The console's own switches, app-wide for the same reason the pace
        # is, and read wherever a show is decided from.
        self._filters = ShowFilters(parent=self)
        self._filters.changed.connect(self._on_show_filters_changed)
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
            command_matcher=match_voice_command,
            bare_matcher=sided_app_command,
            dictation=RequestDictation(),
            transcribe_bias=(f"{voice_command_bias()} {app_command_bias()} "
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
        # Every show currently up, each with the shelf/folder key it opened
        # from: what a landing generation is offered to, so a show keeps up
        # with an auto-generating folder however far the browser has moved on.
        # A list rather than one, because Fun Time runs two at once.
        self._live_shows: list[tuple] = []
        # Inside Fun Time, what occupies each satellite region — a show per
        # region, at most one each.  A show is "open" while its window is
        # visible; a closed one just goes stale in its slot until something
        # replaces it.
        # Whether the hosting session has asked for its regions (OPEN_SHOWS,
        # until CLOSE_SHOWS): a region it wants is never left empty -- what
        # covers it may end, but the base state comes back under it.
        self._regions_wanted = False
        self._region_shows: dict[str, QWidget | None] = (
            {"portrait": None, "landscape": None} if fun_time is not None else {}
        )
        # Whether the hosting session is OmniPaused, remembered so a show
        # opened mid-pause opens frozen (see set_session_paused).
        self._session_paused = False
        # Where the last show was when it closed, so opening one comes back to
        # the slide it left off on rather than the top of a fresh shuffle.
        self._show_state = ShowState()
        # Runs the open show has already turned down as slides of their own
        # frames — another folder's work, an enhancement. Asked once and kept,
        # since every frame of such a run asks again (:meth:`_show_would_play`).
        self._show_refused: set[str] = set()
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
        # Pictures whose spoken "genau it" is still choosing a recipe, so a
        # second one said into that wait is refused rather than queued twice
        # (:meth:`_already_genaud`). Only until the launch is a row.
        self._genau_resolving: set[str] = set()
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
        # What the last Esc took off, for the next one to put back — cleared as
        # soon as it is put back, so the key goes on alternating.
        self._stopped_by_escape: _Running | None = None
        # Stand-in queue rows for a Generate pressed but not yet a job, by key
        # (:meth:`_show_launching`), and the counter their keys are drawn from —
        # anything that can't be mistaken for a prompt id.
        self._launching: dict[str, InFlightItem] = {}
        self._launch_seq = 0
        self._build_ui()
        self._sync_history_buttons()
        self._sync_nav_buttons()
        self._sync_action_buttons()
        # Catch Delete/Ctrl+Z application-wide while the Gallery tab is showing.
        # Neither keyPressEvent nor a shortcut delivered the key in the running
        # app — a clicked thumbnail's key press never reached the view through
        # the scroll area — so intercept it before delivery, independent of which
        # widget holds focus. Taken off again in closeEvent, and re-armed by
        # showEvent for a view shown after one.
        self._intercept_the_rooms_keys(True)

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._poll)
        self._poll_timer.start()

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
        """Esc turns off everything the app is doing, wherever focus is: the OSR2
        drive (a funscript or the genau stroke), the auto-generate loop, the
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
        the loop, the device and the sound running behind it, which is the
        opposite of what the key means. Returns whether it acted.
        """
        if self._other_window_owns_keys() and not self._our_show_is_in_front():
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
        show = self._slideshow
        return _Running(
            osr2=self._osr2_enabled,
            # Space reaches the switch rather than the stroke, so a stroke
            # running with the switch off is one something else started — the
            # stop has always covered that case, and so does the resume.
            stroke=self._osr2_stroke.active and not self._osr2_enabled,
            auto=self._auto.active_key(),
            audio=self._audio_btn is not None and self._audio_btn.isChecked(),
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
        return _Running(osr2=True, auto=_base_of(self._selected_folder_key()),
                        audio=True, show=True)

    def _stop_running(self, running: _Running) -> None:
        """Take all of ``running`` off."""
        if running.osr2:
            # One switch, so one thing to turn off: untoggling stops whichever
            # source is on the device — a funscript drive or the stroke.
            self._osr2_btn.setChecked(False)
        elif running.stroke:
            self._osr2_stroke.stop()
        if running.auto:
            self._auto.stop_all()
        if running.show:
            self._slideshow.close()  # _on_slideshow_closed lets it go
        if running.audio:
            if self._audio_btn is not None:
                self._audio_btn.setChecked(False)  # drives _on_audio_toggle → silence

    def _resume(self, stopped: _Running) -> None:
        """Put back what Esc took away.

        In the order that leaves each one aimed where it was: the show goes up
        before the device switch, so the one reconcile that picks a drive source
        finds the show's video in front of it exactly as it did the first time.

        A loop resumes in the folder it was running in rather than the one on
        screen — the gallery is somewhere else by now as often as not, and the
        loop was never about where the user is looking.

        A show with no pass behind it opens on what is in front instead, which is
        both the standing start and the show that was following a generation in
        flight: that one has no pass to take up, and what it was watching has
        landed or gone by now.
        """
        if stopped.audio:
            if self._audio_btn is not None:
                self._audio_btn.setChecked(True)
        if stopped.show_pass is not None:
            items, index, dwell_ms = stopped.show_pass
            self._open_slideshow(items, start=index, image_dwell_ms=dwell_ms,
                                 shuffle=in_order)
        elif stopped.show:
            self._start_slideshow()
        if stopped.auto:
            self._begin_auto(stopped.auto)
            self._sync_auto_button()      # a resumed loop lights its switch again
            self._sync_discard_buttons()  # and its run offers a next seed, not a cancel
        if stopped.osr2:
            self._osr2_btn.setChecked(True)
        elif stopped.stroke:
            self._osr2_stroke.start()

    def _our_show_is_in_front(self) -> bool:
        """True when the window ahead of the gallery is our own fullscreen
        slideshow — one of the things Esc turns off, rather than a window to hand
        the key back to. A dialog or popup over the show still owns it."""
        if self._slideshow is None:
            return False
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return False
        return QApplication.activeWindow() is self._slideshow

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
        #
        # Hosted by Fun Time the rect is an upright column, so the panes fold
        # into _stack instead of sitting side by side: the info pane on top, the
        # tree and browser as one row under it, and the queue across the foot of
        # all three.  _left_column goes unused there — hosted, the queue belongs
        # to the window rather than to the folder column.
        self._panes = QSplitter(Qt.Orientation.Horizontal)
        self._panes.setChildrenCollapsible(False)  # a pane can't be dragged shut
        self._panes.setHandleWidth(6)
        self._folder_panes = QSplitter(Qt.Orientation.Horizontal)
        self._folder_panes.setChildrenCollapsible(False)
        self._folder_panes.setHandleWidth(6)
        self._left_column = QSplitter(Qt.Orientation.Vertical)
        self._left_column.setChildrenCollapsible(False)  # the strip keeps its slot
        self._left_column.setHandleWidth(6)
        self._stack = None
        if self._fun_time is not None:
            self._stack = QSplitter(Qt.Orientation.Vertical)
            self._stack.setChildrenCollapsible(False)
            self._stack.setHandleWidth(6)

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
        # The gallery's image/video filter: two boxes saying which kinds of
        # generation the gallery is made of at all, both on so it opens showing
        # everything. It sits between the search box and the tree because it
        # prunes the tree: a gallery with videos switched off has no video folders
        # in it, and no video tiles in the pane beside them either. (It replaces a
        # pair that filtered the Recents shelf alone, which could only ever answer
        # "which of these do I want to look at" for one shelf.)
        self._image_cb = CheckBox("Images")
        self._video_cb = CheckBox("Videos")
        for checkbox in (self._image_cb, self._video_cb):
            checkbox.setChecked(True)
            checkbox.setToolTip(
                "Which kinds of generation the gallery lists — the folders below "
                "as well as the items in the pane beside them"
            )
            checkbox.toggled.connect(self._on_media_filter_changed)
        media_filter = QWidget()
        media_row = QHBoxLayout(media_filter)
        media_row.setContentsMargins(0, 0, 0, 0)
        media_row.addWidget(self._image_cb)
        media_row.addWidget(self._video_cb)
        media_row.addStretch(1)
        toc_box.addWidget(media_filter)
        toc_box.addWidget(self._tree, 1)  # the trees take the height; combine sits below
        # Combine: drop an image + an i2v video, Generate re-runs that video's recipe
        # on the image. Needs a client to generate, so it hides without one.
        self._combine = CombinePanel(
            self._combine_accepts_image, self._combine_accepts_video, self._combine_preview
        )
        # Both Generate paths go through a wrapper that puts a stand-in row in the
        # line first: the work between the press and a real job is seconds long,
        # and a button that seems to do nothing reads as an app that has died.
        self._combine.generate_requested.connect(self._combine_generate)
        self._combine.category_requested.connect(self._combine_generate_category)
        self._combine.open_requested.connect(self._open_combination)
        self._combine.open_category_requested.connect(self._open_category)
        # Switching lanes re-asks which acts are answerable: an act with plenty of
        # long-form video behind it may have no loop at all.
        self._combine.intent_changed.connect(self._on_combine_intent_changed)
        self._combine.setVisible(self._client is not None)
        toc_box.addWidget(self._combine)
        # Hosted, the tree is the upright column's own left edge (collapsible,
        # see _toc_toggle) rather than a member of the folder row, so it goes
        # straight into the outer splitter.
        (self._panes if self._stack is not None else self._folder_panes).addWidget(toc)

        # Browser pane: a header (the folder's path, then a back/forward/undo
        # toolbar under it) over the flowing contents. Double-clicking the path
        # renames the folder it ends at.
        browser = QWidget()
        browser_box = QVBoxLayout(browser)
        browser_box.setContentsMargins(*_PANE_MARGINS)
        # Fun Time's column is narrow, so the folder tree earns a collapse
        # toggle at the head of the button bank: the tree's width goes to the
        # browser while it's away, and the divider can be dragged shut too.
        self._toc_toggle = None
        if self._fun_time is not None:
            self._toc_toggle = QToolButton()
            self._toc_toggle.setObjectName("iconButton")
            self._toc_toggle.setArrowType(Qt.ArrowType.LeftArrow)
            self._toc_toggle.setToolTip("Collapse or restore the folder tree")
            self._toc_toggle.clicked.connect(self._toggle_toc)
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
        # The room's two shared appliances: the audio bed and the microphone.
        # Hosted by Fun Time this app has neither — the session's main player
        # owns the room's sound, and the session owns the mic (it hears every
        # spoken command, this app's included, and posts them on the channel),
        # so a second switch for either would be a switch over something this
        # window does not hold.
        self._audio_btn = None
        self._mic_btn = None
        if self._fun_time is None:
            # While it's on, a few library clips play at once with only their
            # sound — something to work over, tied to nothing on screen.
            self._audio_btn = self._tool_button(
                icons.audio_icon(),
                f"Play {AMBIENT_AUDIO_VOICES} library clips at once, sound only, "
                "shuffling endlessly",
                self._on_audio_toggle, checkable=True,
            )
            self._audio_btn.setStyleSheet(
                "QToolButton:checked { background-color: #2d6cdf; border-radius: 4px; }"
            )
            # The microphone, standing apart from the switches above: those
            # are what the app is doing, and Esc turns all of them off at once —
            # the mic is the one thing it leaves alone, since speaking is how
            # any of them get going again without the keyboard.  On is
            # listening, off is not, and that is the whole of it.
            self._mic_btn = self._tool_button(
                icons.mic_icon(),
                "Listen: bare words for the shelves and this bank (“experiments”, "
                "“undo”, “star”), Fun Time's own words over a show (“next”, "
                "“weird”, “lock”), orders about the picture (“enhance”, “fix "
                "hands”, “genau it”), and prompt steering while a folder is "
                "auto-generating (left listening by Esc, which stops everything else)",
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
        #
        # None where this app may not touch the device at all: a Fun Time
        # session keeps the OSR2 on its main player, so a hosted gallery builds
        # no switch and the device is unreachable from here.
        self._osr2_btn = None
        if self._osr2_stroke is not None:
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
            (self._toc_toggle,),                                    # the tree itself
            (self._back_btn, self._forward_btn),                    # where you are
            (self._undo_btn, self._redo_btn),                       # what you did
            (self._group_btn,),                                     # …to the picked folders
            (self._star_btn, self._enhance_btn, self._delete_btn),  # …to what's in front
            (self._slideshow_btn, self._auto_btn,                   # what the app is
             self._audio_btn, self._osr2_btn),                      # doing, and Esc stops
            (self._mic_btn,),                                       # what it hears with
        ):
            buttons = tuple(b for b in buttons if b is not None)
            gap = _toolbar_gap()
            toolbar.addWidget(gap)
            for button in buttons:
                toolbar.addWidget(button)
            self._toolbar_groups.append((gap, buttons))
        self._sync_toolbar_gaps()
        browser_box.addWidget(self._toolbar_host)
        # The search results' own controls, riding under the header and appearing
        # only while a query is running: how many
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
        # switch and a one-line status. Rides under the header, and appears only
        # while that shelf is open.
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
        self._scroll = BrowserScrollArea()
        self._scroll.setWidgetResizable(True)
        # A click on the background between the tiles puts the selection down,
        # as it does in a file browser — and here it is also the only way back
        # to aiming Star / Enhance / Delete at the whole folder once a tile has
        # been picked.
        self._scroll.background_clicked.connect(
            self._browser.clear_thumbnail_selection)
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
        if self._stack is not None:
            # Hosted, the queue is not the folder column's strip.  It spans the
            # whole foot of the rect (added to _stack below), so the corner
            # under the tree is the queue rather than more tree — which is where
            # a standalone window's eye finds it, and the upright fold has no
            # reason to move it.  The folder panes go straight beside the tree.
            self._panes.addWidget(self._folder_panes)
        else:
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
        # None where this app may not touch the device at all (hosted by Fun
        # Time, whose main player owns the OSR2).
        self._osr2_driver = Osr2Driver(parent=self) if self._osr2_stroke is not None else None
        self._osr2_enabled = False
        self._osr2_driving = None
        # The bottom of the center (browser) pane, shared by two panels that each
        # take their own room rather than floating over anyone's buttons: genau's
        # readout, copied, held to the left at its fixed size, and the open
        # folder's Enhance settings taking the width left beside it.  Hosted by
        # Fun Time there is no readout — the real console is on the session's
        # main player — so the Enhance settings take the row alone.
        bottom = QHBoxLayout()
        bottom.setContentsMargins(0, 0, 0, 0)
        bottom.setSpacing(12)
        self._stroke_panel = None
        if self._osr2_stroke is not None:
            self._stroke_panel = StrokePanel(self._osr2_stroke, pace=self._pace,
                                             filters=self._filters)
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
            if self._osr2_driver is not None:
                app.aboutToQuit.connect(self._osr2_driver.stop)
                app.aboutToQuit.connect(self._osr2_stroke.stop)
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
        info_box = QVBoxLayout(info_pane)
        info_box.setContentsMargins(0, 0, 0, 0)
        info_box.addWidget(self._info_tabs, 1)
        info_box.addWidget(self._find_bar)

        if self._stack is not None:
            # The upright arrangement, top to bottom: the generate tabs (with
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
        else:
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

        layout.addWidget(self._stack if self._stack is not None else self._panes, 1)

    def _toggle_toc(self):
        """Collapse or restore the folder tree (the Fun Time column's toggle).

        Hiding the splitter child hands its width to the browser stack; the
        arrow flips to show which way the next press moves it.
        """
        toc = self._panes.widget(0)
        showing = not toc.isVisible()
        toc.setVisible(showing)
        self._toc_toggle.setArrowType(
            Qt.ArrowType.LeftArrow if showing else Qt.ArrowType.RightArrow
        )

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
        image" link and an animation-tile click both navigate like any source link,
        and its preview's corner controls and right-click menu act on the shown
        generation exactly as a browser thumbnail's do.
        Its ``displayed_changed`` re-aims the global OSR2 drive at the front video
        and re-reads whether the tab still owns a run in flight, a double-click on
        its preview opens the folder behind it as a held slideshow,
        and its Cancel stops the re-roll running in the tab's folder. Called for the
        initial tab and every tab forked afterward."""
        panel.source_activated.connect(self._on_source_link)
        panel.animated_activated.connect(self._on_source_link)
        # Its preview's corners and its right-click are the same acts, on the same
        # generation, as a browser thumbnail's — so they land in the same places.
        panel.item_action_requested.connect(self.run_item_action)
        panel.context_menu_requested.connect(
            lambda prompt_id, pos: self.generation_menu([prompt_id], pos))
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
        streaming alongside whatever the switch already had going.

        A no-op with no switch to flip: hosted by Fun Time the device belongs
        to the session's main player, so nothing here may start it."""
        if self._osr2_btn is not None:
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
        # Neither shuffled nor newest-first, and not a loop: this is one folder
        # in the browser's own order, held on one picture.  Said plainly rather
        # than left at the defaults, because the HUD reads them now — an order
        # slot saying "Shuffle" over a folder listed in its own order would be
        # the panel making something up.
        return self._open_slideshow(items, start=index, frame=frame,
                                    image_dwell_ms=0, shuffle=in_order,
                                    folder_items=self._folder_media(),
                                    order_label="", looping=False,
                                    starred_ids=self._starred_prompt_ids())

    def _open_slideshow(self, items, *, folder_items=None, location=None,
                        side=None, resume=None, **kwargs):
        """Build, wire and show a fullscreen slideshow of ``items``.

        The one place a show is made, however it was asked for, so the toolbar's
        and a double-click's differ only in the order and the pace they pass.
        ``folder_items`` is what to arm a show that opened over a running
        generation with, since that one has no items of its own yet, and
        ``resume`` where a closed show left off, for one picking that back up
        rather than naming its own opening slide.

        ``location`` is the shelf or folder key the set came from, kept so the
        show can be fed what lands there while it runs
        (:meth:`_feed_slideshow_finished`) — a running show has to keep up with
        the folder it is playing, and the browser will have moved on by then.
        ``side`` names the satellite region to land it on inside Fun Time,
        for a show asked for by side rather than routed by its own shape.
        """
        self._show_refused = set()  # a new show, a new set to be judged against
        self._slideshow = SlideshowView(
            items, on_delete=self._trash_generation,
            on_enhance=self._enhance_from_slideshow,
            on_star=self._star_generation,
            on_lock=(self._open_generate_tab_for
                     if self._fun_time is not None else None),
            on_reset=(self.reset_region if self._fun_time is not None else None),
            pace=self._pace, stroke=self._osr2_stroke,
            filters=self._filters,
            # Its Space reaches the one OSR2 switch, like every other surface's.
            on_drive_toggle=self._toggle_osr2_drive, **kwargs)
        self._live_shows.append((self._slideshow, location))
        if folder_items and self._slideshow.is_live():
            # Watching something render is no reason to lose the folder it is
            # being made in: the first arrow leaves the live frames for it.
            self._slideshow.set_playlist(folder_items, 0)
        # Shift+Left/Right gets its own axis: the versions of whichever image is
        # on screen, so a level can be compared against the one below it at full
        # size rather than in a thumbnail.
        self._slideshow.set_levels(self._folder_level_playlists())
        if resume is not None:
            # After the levels: the version a slide was left showing is only a
            # version once they are armed.
            self._slideshow.resume(resume)
        self._slideshow.open_requested.connect(self._open_from_slideshow)
        show = self._slideshow
        show.closed.connect(lambda s=show: self._on_slideshow_closed(s))
        self._slideshow.media_changed.connect(self._reconcile_osr2)
        # Standalone that is a monitor to take over; hosted, it is one of the
        # satellite regions — the side asked for, else the one this set's own
        # shape belongs on.
        self._present_surface(self._slideshow, side or region_for_items(items))
        self._reconcile_osr2()
        # However the show was asked for, it now owns the card it is drawn with: a
        # video generation would saturate that card, and a show is exactly the
        # stretch when nobody is waiting on a video. The queue holds them until it
        # closes and keeps making images.
        self._reroll.hold_videos(True)
        # The queue it floats in its corner is the same widget as the bottom
        # strip and asks for the same things, so it goes to the same handlers:
        # a row dragged there re-lines the queue, and its Clear drops another
        # app's work off ComfyUI.
        self._slideshow.queue().reorder_requested.connect(self._reroll.reorder)
        self._slideshow.queue().clear_queue_requested.connect(self._clear_foreign_queue)
        # And fill it at once rather than a poll later: the hold on videos is
        # this opening's own doing, so the corner comes up already saying what
        # is waiting on it rather than blank for a second and a half.
        self._slideshow.set_queue(self._inflight_items(), self._foreign_queue.total)
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


    def _open_surfaces(self) -> list:
        """Every tracked full-screen surface, each once: the standalone singles
        and whatever the satellite regions hold inside Fun Time.  The
        enhancement feed and the media release address all of them — a surface
        that has since closed takes the note inertly, so nothing here polices
        visibility; only region occupancy does (see :meth:`region_show`)."""
        candidates = [self._slideshow, *self._region_shows.values()]
        surfaces, seen = [], set()
        for surface in candidates:
            if surface is None or id(surface) in seen:
                continue
            seen.add(id(surface))
            surfaces.append(surface)
        return surfaces


    def _group_for_key(self, key: str):
        """The folder ``key`` names, as the side it is being looked at holds it."""
        item = self._tree_item_for(key)
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
        """Restore the global OSR2 toggle from a saved session.  With no OSR2
        surface (hosted by Fun Time) a stale saved value has nothing to restore."""
        if self._osr2_btn is not None:
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
        return self._audio_btn is not None and self._audio_btn.isChecked()

    def set_audio_enabled(self, enabled):
        """Restore the audio bed's switch from a saved session.  With no switch
        (hosted by Fun Time, whose main player owns the room's sound) a stale
        saved value has nothing to restore."""
        if self._audio_btn is not None:
            self._audio_btn.setChecked(bool(enabled))  # drives _on_audio_toggle → start

    # --- the microphone: the one switch Esc leaves alone ---------------------

    def mic_enabled(self) -> bool:
        """Whether the mic switch is on (for session persistence).

        Hosted there is no switch — the session owns the room's microphone — so
        the answer is no.  Asked on the way out either way, and an
        AttributeError raised inside closeEvent takes the whole process down
        with it rather than surfacing anywhere.
        """
        return self._mic_btn is not None and self._mic_btn.isChecked()

    def set_mic_enabled(self, enabled):
        """Restore the mic switch from a saved session — on when the session has
        nothing to say, which is where the app opens.

        The other switches default off because each of them spends something: the
        GPU, the device, the room's sound. Listening spends nothing until it hears
        something, and it is the only way back in after Esc has stopped everything
        else — so off is a state to be chosen, not one to be arrived at.
        """
        if self._mic_btn is not None:  # hosted, the session owns the microphone
            self._mic_btn.setChecked(True if enabled is None else bool(enabled))

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
        let go: the poll, and the filter that takes the room's keys.

        ``hideEvent`` alone is not enough for either: a widget that was never
        shown is never hidden, so ``close()`` on one left the 1.5 s poll running
        — blocking HTTP and a whole-table SELECT, on a view nobody can see —
        and left a closed gallery answering Esc from whatever window has focus,
        which is the panic-stop for the whole room.
        """
        self._poll_timer.stop()
        self._intercept_the_rooms_keys(False)
        super().closeEvent(event)

    # --- data loading & live update ---------------------------------------

    def refresh(self):
        rows = self._db.list_generations()
        meta = self._db.folder_meta_map()
        self._fingerprint = _fingerprint(rows, meta)
        self._rebuild(rows, meta)
        if self._regions_wanted:
            # The tree this rebuild just made is what the base state is read
            # from, and the session's OPEN_SHOWS can land before the first one
            # (its launch races this app's boot).  Filling here costs nothing
            # when both regions are already playing, and is the only thing that
            # rescues a session that opened into the mode a moment too early.
            self.fill_the_regions()

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
        else:
            # No DB change, but the in-flight cards still need each running
            # re-roll's live frame pushed in — it advances between rebuilds.
            # Wherever they were drawn: the Recents shelf, or a folder with a
            # batch of them cooking in it.
            self._browser.refresh_inflight()
        # The bottom strip is always on screen, so refresh it every tick — its
        # rows' live frames and progress advance between rebuilds.
        self._update_queue()
        # And a show's corner, for the same reason and one more: a run starting
        # is not a change to any row, so nothing else here would tell the show
        # its held slide went from waiting to being made.
        self._feed_slideshow_enhancing()
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
        # An act with no video behind it has no recipe to mine, so gray it out rather
        # than let it be picked only to answer "no recipe yet".
        self._combine.set_available_categories(
            recipe_match.available_categories(
                self._rebuildable_videos(rows), self._combine.selected_intent()
            )
        )
        # The Images/Videos boxes narrow everything the gallery shows: which
        # folders the tree grows, which items each shelf lists, and what a search
        # can turn up. The tree takes the filter itself rather than pre-filtered
        # rows, because the start-frame index behind a video's source-image
        # folders has to see every image whichever way the boxes stand.
        media_types = self._media_types()
        listed = gallery.rows_of_media_types(rows, media_types)
        tree_model = gallery.build_gallery_tree(rows, meta, media_types)
        unreviewed = self._review_queue(listed)
        # The bin holds every kind, so a restore can still resolve a row of a type
        # the boxes are hiding; only what the Trash shelf lists is narrowed.
        self._held_rows = recovery.bin_items(self._bin_records())
        held = gallery.rows_of_media_types(self._held_rows, media_types)
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
        self._search.update(listed + held, gallery.named_folders_by_row(
            tree_model, meta, self._custom_folders))
        requested = gallery.requested_generations(self._db.list_requests(), listed)  # the Requests shelf
        # Every side is built from the rows the media filter keeps, so switching
        # videos off empties both halves of them rather than one.
        sides, starred_by_side = self._build_sides(listed, meta, unreviewed, held, requested)
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

    def _build_sides(self, rows, meta, unreviewed, held, requested):
        """The two sides of the tree, and the starred folders each one holds.

        A side is the whole table of contents over one shape's rows: its own
        media/workflow/model/LoRA/settings hierarchy, its own copies of the
        folders the user composed, and shelves whose counts are its own — a
        number covering both sides would send you to a shelf that then showed
        you nothing.  Built from a single deal of the rows, because measuring
        each row's shape is the expensive part and a rebuild runs on every poll.
        """
        dealt = split_rows(rows)
        custom_records = self._db.list_custom_folders()
        request_rows = [item["row"] for item in requested]
        inflight = self._browser.inflight_orientations()
        sides, starred = [], {}
        for orientation in _ORIENTATIONS:
            model = gallery.build_gallery_tree(dealt[orientation], meta)
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
        try. The All row over the workflow folders is what covers the library
        entire, since every other folder narrows the answer before the query does.

        ``path`` is the row's breadcrumb — what the box, the header and the
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
            self._sync_action_buttons()
            return
        if base == _RECENTS_KEY:
            self._browser.show_recents_overview(orientation)
            return
        if base == _STARRED_KEY:
            self._browser.show_starred_overview(orientation)
            return
        if base == _EXPERIMENTS_KEY:
            self._sync_experiments_bar()
            self._browser.show_experiments_overview(orientation)
            return
        if base == _REQUESTS_KEY:
            self._browser.show_requests_overview(orientation)
            return
        if base == _TRASH_KEY:
            self._browser.show_trash_overview(orientation)
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
        item = self._tree_item_for(gallery.custom_folder_key(folder_id))
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

    def _selected_folder_key(self) -> str | None:
        """The selected row's tree key (or a shelf's), from the tree renderer."""
        return self._tree_view.selected_folder_key()

    def _current_side(self) -> str:
        """Which of the two sides the tree is standing on.

        Every row lives under one, so this is only ever a fallback: nothing
        selected at all (a fresh window, a rebuild that found no target) reads
        as Landscape, the roomier side and the one an unmeasurable item files
        under everywhere else.
        """
        return _orientation_of(self._selected_folder_key()) or _LANDSCAPE

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
        here = oriented_key(key, self._current_side())
        return self._item_by_key[here if here in drawn else drawn[0]]

    def _shelf_item(self, shelf_key: str, orientation: str | None = None):
        """One side's copy of a shelf row — the side being browsed by default."""
        return self._tree_view.shelf_item(shelf_key, orientation or self._current_side())

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
                          typical_seconds=self._typical_run_seconds(job),
                          source_picture=self._job_source_picture(job))
        tile.set_selected(group.key == self._selected_reroll_key)
        tile.add_requested.connect(lambda k=group.key: self._start_reroll(k))
        tile.cancel_requested.connect(lambda k=group.key: self._cancel_reroll(k))
        tile.selected.connect(lambda k=group.key: self._select_reroll(k))
        flow.addWidget(tile)
        self._reroll_tile = tile

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
        key = self._folder_key_for(workflow_name, params)
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
        behind the wait until the run streams a frame of its own.

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
            self._reroll.start(key, self._group_for_key(key), self._image_rows)
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
        # The folder's own key, not the row's: a loop is filed with the jobs it
        # launches, and those are keyed by folder wherever it is being watched from.
        group = self._current_group()
        if not checked:
            self._auto.stop_all()
        elif group is not None:
            self._begin_auto(group.key)
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
        """Hold the folder's settings as the loop's working params.

        The folder on screen when it is the one being looped, which is every
        press of the Auto switch; otherwise the one ``key`` names, looked up in
        the tree — Esc resuming a loop is the case where the two differ, and the
        folder the user has navigated to since is not the one to capture.
        """
        group = (self._current_group() if key == self._selected_folder_key()
                 else self._group_for_key(key))
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
        if self._listening():  # still listening
            self._show_voice_status("🎤 Listening…", transient=False)
        else:
            self._voice_status.hide()

    def _on_voice_heard(self, text: str):
        """Say what the mic heard — a command in the words the app knows it by,
        anything else as it was transcribed.

        Whisper renders a command word a dozen ways and the matcher answers to
        all of them, so the transcription of one is a misspelling of a word that
        was understood perfectly well: "gunow it" printed over a caption that
        then goes and makes a Genau clip. The spelling it was recognized as is
        the truthful thing to show
        (:func:`~origenerator.gallery.voice_commands.recognized_spelling`).
        """
        if any(char.isalpha() for char in text):
            self._say_of_voice(f"🎤 heard: “{gallery.recognized_spelling(text) or text}”")

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

        A spoken line, not an answer to a request — which matters while one is
        being worked out, because the show's corner is holding that work and a
        line said over it has to fade back to it rather than take its place.
        """
        self._show_voice_status(message, transient=True)
        if self._slideshow is not None:
            self._slideshow.note_voice_command(message)

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
        elsewhere = looping is not None and looping != getattr(group, "key", None)
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
        shelf's collection on a shelf, else everything under the selected folder
        — narrowed by whichever of the show filters are on.

        The one place they are applied, so everything a show is decided by goes
        through it: what one opens with, whether the button has anything to
        play, and whether a generation that lands mid-show joins it.
        """
        rows = self._browser.shelf_rows()
        if rows is None:
            group = self._current_group()
            rows = gallery.rows_under(group) if group is not None else []
        if not self._filters.any_on:
            return rows
        return [row for row in rows if self._filters.keeps(row)]

    def _on_show_filters_changed(self):
        """A show filter moved — from the console, or from a word.

        A show that is up narrows (or widens) where it stands, the way turning
        the pace changes a running show under you: the console is on screen over
        that show, so a switch that only took effect on the NEXT one would look
        like a button that does nothing. The bank follows too, since what there
        is to play has changed.
        """
        self._sync_action_buttons()
        self._sync_slideshow_button()
        if self._slideshow is not None:
            self._slideshow.refilter(self._slideshow_items(self._slideshow_rows()))
        logger.info("Show filters: favorites=%s enhanced=%s",
                    self._filters.favorites, self._filters.enhanced)

    def _slideshow_subject(self) -> str:
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
        # Every picture on screen is answering it too, in its own corner.
        self._browser.refresh_enhance_corners()

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

    def _listening(self) -> bool:
        """Whether this app is listening on its own mic.

        Never when hosted: the session owns the microphone there, hears the
        spoken commands for both of us, and posts this app's on its channel —
        two listeners on one mic is two transcriptions of every utterance.
        """
        return self._mic_btn is not None and self._mic_btn.isChecked()

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
        if not self._listening():
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

    def run_spoken_command(self, text: str) -> bool:
        """Run a command the HOSTING session heard, and say whether it was one.

        Fun Time owns the microphone while this app is hosted — one mic, one
        transcription — so its recognizer hears "landscape favorites", posts the
        words on this app's channel, and they are matched here against this
        app's own vocabulary: the session cannot know which shelves this tree
        has or which detail parts have detectors installed.

        A request has first refusal, exactly as it does on this app's own mic.
        "Request … over" runs to as many utterances as the speaker takes
        breaths, so a matcher that only ever saw one at a time could not hear a
        sentence said in three; while one is open the dictation swallows what
        it hears, which is what keeps the words of a request from also matching
        a command.  The side is split off first — it rides every utterance the
        session posts, and fed in it would become the first word of the
        request instead of the region the request is about.
        """
        side, rest = split_side(text)
        spoken = self._voice.push_dictation(rest)
        if spoken is not None:
            self._on_spoken_request(spoken, side=side)
            return True
        matched = match_voice_command(text)
        if matched is None:
            logger.info("Voice (from the session): %r matched no command", text)
            return False
        self._on_voice_command(matched)
        return True

    def _on_voice_command(self, matched):
        """One recognized utterance: a shelf to play, a show command, a bare
        word about the app or the slide in front of the speaker, or an order
        about the picture — each with the side it named, if it named one.

        A bare command with no wrapper round it named no side, which is what
        every utterance was before the room had two shows to aim at.
        """
        if isinstance(matched, ShelfCommand):
            self._play_shelf_aloud(matched)
        elif isinstance(matched, ShowControl):
            self._run_show_command(matched.command, matched.side)
        elif isinstance(matched, SurfaceCommand):
            if isinstance(matched.command, AppCommand):
                self._run_app_command(matched.command, matched.side)
            else:
                self._on_picture_command(matched)
        elif isinstance(matched, ShowCommand):
            self._run_show_command(matched)
        elif isinstance(matched, AppCommand):
            self._run_app_command(matched)
        elif isinstance(matched, DialSetting):
            self._set_stroke_dial(matched)
        else:
            self._on_picture_command(SurfaceCommand(matched))

    def _answer_command(self, message: str):
        """Say what a spoken command did, where the speaker is looking — the
        show's own corner while one is up, since the window behind it is covered
        by the very thing being talked to, and this pane's caption otherwise."""
        show = self._slideshow
        if show is not None:
            show.note_voice_command(message)
        else:
            self._show_voice_status(message, transient=True)

    def _run_show_command(self, command: ShowCommand, side: str | None = None):
        """Get the show going, hold it, or close it — on *side*'s region when
        the utterance named one, else on the show that is up.

        Pausing is a pace of nought and starting is that pace back at the
        standard number, because a show that never moves on is exactly what a
        held picture is here — there is no separate paused state to keep.

        The pace is set through the show when there is one, not only posted to
        the app-wide number: a show sitting at nought while that number already
        reads four would get no word of a change that never happened, and would
        stay frozen through the very command meant to start it.
        """
        show = self._voice_surface(side)
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
            self._start_slideshow(side=side)
            if self._slideshow is None:
                self._show_voice_status("🎤 nothing here to play", transient=True)
            return
        show.set_dwell_s(seconds)
        show.note_voice_command(
            "🎤 slideshow paused" if command is ShowCommand.PAUSE
            else f"🎤 slideshow at {seconds}s"
        )

    # --- the bare vocabulary: a shelf, a switch, a knob, or the slide --------

    def _run_app_command(self, command: AppCommand, side: str | None = None):
        """One bare spoken word.

        Four kinds, and which it is decides where it lands: a shelf name stands
        the tree in that shelf, a switch word flips one of the app-wide
        switches, a knob word turns the stroke — and everything else is about
        whatever surface is in front of the speaker, which is the fullscreen
        show while one is up and the gallery otherwise.
        """
        if command in _VOICE_SHELVES:
            self._go_to_shelf(command, side)
        elif command in _VOICE_FILTERS:
            self._set_enhanced_filter(_VOICE_FILTERS[command])
        elif command in _VOICE_SWITCHES:
            self._flip_switch(command)
        elif command in _VOICE_STROKE:
            self._turn_stroke_knob(command)
        elif self._slideshow is not None and command in _ABOUT_THE_SLIDE:
            self._run_on_show(self._slideshow, command)
        else:
            self._run_in_gallery(command)

    def _go_to_shelf(self, command: AppCommand, side: str | None = None):
        """Stand in the shelf a spoken name asks for, exactly as clicking its
        row does.

        Said over a show it still moves — the tree is behind the show, and the
        move is what the show leaves you standing in — so the answer says which
        shelf rather than refusing a command whose whole effect is out of sight.

        Every shelf has two rows now, one per side, so the utterance's own side
        picks which; unsided, _tree_item_for takes the tree's own answer for
        the folder — the same row a click would have landed on.
        """
        key = _VOICE_SHELVES[command]
        label = _SHELF_LABELS[key]
        item = self._tree_item_for(oriented_key(key, side) if side else key)
        if item is None:  # Recents and Starred appear only once there is one
            self._answer_command(f"🎤 no {label} shelf yet")
            return
        self._tree.setCurrentItem(item)  # whose signal draws it
        self._answer_command(f"🎤 {label}")

    def _flip_switch(self, command: AppCommand):
        """Set one of the app-wide switches, through its button rather than
        around it — a spoken switch is the same event as a clicked one, so the
        bank lights the same way and nothing has to be kept in step.

        "Mic off" is the one with no way back: a shut mic hears nothing, so the
        button is what turns it on again. Its answer is still worth saying —
        with a show up it lands in the show's corner, where the bank is not
        visible to say it instead.
        """
        attribute, want, name = _VOICE_SWITCHES[command]
        button = getattr(self, attribute)
        if button is None:  # hosted: the session owns the audio bed and the mic
            self._answer_command(f"🎤 {name} is the session's here")
            return
        if not button.isEnabled():
            self._answer_command(f"🎤 {name} can't be switched here")
            return
        on = (not button.isChecked()) if want is None else want
        button.setChecked(on)  # its toggled signal is what does the work
        self._answer_command(f"🎤 {name} {'on' if on else 'off'}")

    def _set_enhanced_filter(self, active: bool):
        """Narrow a show to the enhanced pictures, or put them all back.

        Answered with what is left rather than with the switch's name: a speaker
        who has just narrowed a show wants to know there is still something in
        it, and "nothing here is enhanced" is the one answer worth hearing at
        once. Said even when the switch was already that way — a word that did
        nothing and said nothing reads as a mic that missed it.

        Turning it off clears the other switch with it: "clear filter" is the
        way out of ALL of the narrowing, which is what the same phrase means on
        every satellite in this family.
        """
        if not active:
            self._filters.clear()
            self._answer_command("🎤 showing all of them")
            return
        self._filters.set_enhanced(True)
        count = len(self._slideshow_items(self._slideshow_rows()))
        self._answer_command(
            f"🎤 enhanced only — {count} to play" if count
            else "🎤 nothing here is enhanced")

    def _turn_stroke_knob(self, command: AppCommand):
        """Turn one of the stroke's knobs — the move its key makes.

        The driver is app-wide, so this answers from the gallery and from a show
        alike, and the knobs read the same whether or not the device is running:
        a stroke can be set up before it is started, exactly as the panel allows.
        """
        method, argument = _VOICE_STROKE[command]
        turn = getattr(self._osr2_stroke, method)
        turn() if argument is None else turn(argument)
        self._answer_command(f"🎤 {self._osr2_stroke.status_text()}")

    def _set_stroke_dial(self, setting: DialSetting):
        """Put one of the stroke's dials where a spoken number asks for it.

        The nudges above are for a stroke that is nearly right; this is for one
        that is not, and it is the same driver either way — so it answers with
        the same line, and from the gallery and a show alike. The dial does its
        own clamping, which is why "min speed" can say nought and land on the
        slowest the device actually strokes at.
        """
        put = getattr(self._osr2_stroke, _VOICE_DIALS[setting.dial])
        put(setting.value)
        self._answer_command(f"🎤 {self._osr2_stroke.status_text()}")

    def _run_on_show(self, show, command: AppCommand):
        """A word about the slide filling the screen: step off it either way,
        take it away, hold it, or bookmark it.

        The words are Fun Time's, and so is what they do — "weird" condemns what
        is on screen, a lock holds it — because the two rooms are one room to
        whoever is speaking, and a word that means one thing there and another
        here is a word nobody can use.
        """
        if command is AppCommand.BACK:
            show.step(-1)
            said = "🎤 back"
        elif command is AppCommand.FORWARD:
            show.step(1)
            said = "🎤 next"
        elif command is AppCommand.CULL:
            show.cull()
            said = "🎤 gone"
        elif command is AppCommand.STAR:
            said = "🎤 starred" if show.star() else "🎤 nothing here to star"
        elif command is AppCommand.LOCK:
            said = "🎤 holding this one" if show.set_held(True) else "🎤 already holding it"
        else:  # UNLOCK
            said = "🎤 let go" if show.set_held(False) else "🎤 nothing was held"
        self._answer_command(said)

    def _run_in_gallery(self, command: AppCommand):
        """A word said with no show to take it: the bank button it names, aimed
        exactly as a click on it would be."""
        if command in (AppCommand.LOCK, AppCommand.UNLOCK):
            self._answer_command(f"🎤 {command.value} is a slideshow's — none is up")
            return
        attribute, action, refusal = _VOICE_BANK_ACTIONS[command]
        self._press_bank_button(getattr(self, attribute), getattr(self, action),
                                refusal)

    def _press_bank_button(self, button, act, refusal: str | None = None):
        """Do what a bank button does, and answer in that button's own words.

        Its tip already says what it will do to what is in front of you — "Star
        3 items", "Undo: delete of 2 items" — which is precisely what a speaker
        who is not looking at the bank needs told back, and it cannot drift from
        what the button does. A button that is away or dead says why instead of
        quietly doing nothing: ``refusal``, or its tip where that already reads
        as one.
        """
        if button.isHidden() or not button.isEnabled():
            self._answer_command(f"🎤 {refusal or button.toolTip()}")
            return
        said = button.toolTip()  # read first: the action re-aims the bank
        act()
        self._answer_command(f"🎤 {said}")

    def _on_picture_command(self, command):
        """A spoken command about the picture on screen: a targeted "fix <part>"
        (or several parts, or "fix all"), "enhance" for the better version of
        it, or "genau it" to animate it as a Genau clip.

        A named side takes that region's show — hosted, two shows run at once
        and neither is the active window, so naming one is the only way to say
        which picture is meant.  Unnamed, it goes to whichever show is up.
        Answered out of the show's own note — the speaker is looking at it, not
        at this pane. Said with no show up, "enhance" falls to the bank button of
        the same name; the other two have no "on screen" to act on, and the
        utterance has already been claimed as a command by the time it gets here,
        so the caption says so rather than letting it vanish."""
        show = self._voice_surface(command.side)
        if show is None:
            if command.command == gallery.ENHANCE_COMMAND:
                # The word names a bank button too, and with no picture filling
                # the screen the button is what it means — aimed the way a click
                # aims it, at the picked thumbnails else the folder's unenhanced
                # images. A refusal here would be a dead end where there is a
                # perfectly good thing to do.
                self._press_bank_button(self._enhance_btn, self._enhance_selection)
                return
            wants = (_VOICE_WANTS.get(command.command)
                     or f"a {gallery.name_parts(command.command)} fix")
            self._show_voice_status(
                f"🎤 {wants} needs a picture on screen", transient=True)
            return
        target = show.voice_target()
        if command.command == gallery.GENAU_COMMAND:
            prompt_id, message = self._genau_it(target)
        elif command.command == gallery.ENHANCE_COMMAND:
            prompt_id, message = self._enhance_it(target)
        else:
            prompt_id, message = self._fix_parts(target, command.command)
        show.note_voice_run(prompt_id, message)

    def _voice_surface(self, side: str | None):
        """The show a spoken command means: *side*'s region show when it named
        one, else the show that is up.

        Hosted, a named side that holds nothing is an answer in itself —
        falling back to the other region's show would act on the picture the
        speaker did not name."""
        if side is not None and self._fun_time is not None:
            return self.region_show(side)
        return self._slideshow

    def region_base_location(self, side: str) -> str:
        """Where a region plays from with nothing else asked for: the whole
        library, narrowed to that region's shape.

        The base state of origenerator mode, and what its reset goes back to.
        It is what the satellite players do in player mode — each shuffles the
        whole library of its own orientation — and this side is meant to read
        the same way.
        """
        return oriented_key(gallery.ALL_KEY, side)

    def fill_the_regions(self) -> None:
        """Put a show on each region: the whole library, shuffled, one shape each.

        What entering origenerator mode means — the session's own mode opens
        with both players playing, so this one opens with both regions playing
        rather than with two empty rectangles and a mode that has to be started
        by hand.  Each side gets the shape it can show, and a region already
        holding a show is left alone: the switch is no reason to interrupt
        something already up.
        """
        self._regions_wanted = True
        for side in ("portrait", "landscape"):
            if self.region_show(side) is not None:
                continue
            key = self.region_base_location(side)
            items = self._slideshow_items(self._rows_at(key))
            if not items:
                # Not a dead end: the tree this reads is built by the first
                # refresh, and the session's OPEN_SHOWS can arrive before it
                # (the launch races the boot).  A region owed its base state
                # gets it on the next refresh -- see :meth:`refresh` -- because
                # a black rectangle is what this mode's base state exists to
                # not be.
                logger.info("Nothing of %s shape to open on the %s region yet",
                            side, side)
                continue
            logger.info("The %s region opens on the library of its shape: %d items",
                        side, len(items))
            self._open_slideshow(items, location=key, side=side, looping=False,
                                 starred_ids=self._starred_prompt_ids())

    def close_the_regions(self) -> None:
        """Give both regions back -- the session leaving origenerator mode.

        The wanting is dropped first: a show closing while the mode still wants
        its regions is refilled with the base state, and these closes must not
        be.
        """
        self._regions_wanted = False
        for side in ("portrait", "landscape"):
            show = self.region_show(side)
            if show is not None:
                show.close()

    def _refill_region(self, side: str) -> None:
        """Put *side* back on its base state, if the mode still wants it there.

        What a region does when the show covering it ends -- the loop button
        pressed off, an Escape, a set culled empty.  In origenerator mode the
        player underneath is blacked for the whole mode, so a region left empty
        is a black rectangle rather than a fallback.
        """
        if not self._regions_wanted or self.region_show(side) is not None:
            return
        key = self.region_base_location(side)
        items = self._slideshow_items(self._rows_at(key))
        if not items:
            return
        self._open_slideshow(items, location=key, side=side, looping=False,
                             starred_ids=self._starred_prompt_ids())

    def _side_of(self, show) -> str | None:
        """Which satellite region *show* is holding, if it holds one."""
        return next((side for side, held in self._region_shows.items()
                     if held is show), None)

    def reset_region(self, show) -> None:
        """A region's reset: back to the base state, not to the top of whatever
        that region happens to be playing.

        The players' own meaning of the button — reset drops the narrowing and
        leaves the satellite shuffling its whole library again — so a show
        started on one folder goes back to the library of its shape.  A region
        with nothing to play there, and a show holding no region at all, fall
        back to the show's own reset rather than emptying the screen.
        """
        side = self._side_of(show)
        if side is None:
            show.reset_in_place()
            return
        key = self.region_base_location(side)
        items = self._slideshow_items(self._rows_at(key))
        if not items:
            show.reset_in_place()
            return
        # The show is being re-pointed, so what feeds it has to move with it:
        # a generation landing in the library must reach a reset region.
        self._live_shows = [(held, key if held is show else where)
                            for held, where in self._live_shows]
        show.retune(items, order_label="Shuffle", looping=False)

    def _play_shelf_aloud(self, command) -> None:
        """A spoken shelf name, on the named side.

        "Favorites" is the exception, and it is the players' own meaning: on a
        player that word is F-mode — narrow what is playing to the favorites —
        so on a show it is the same switch, the one its HUD draws.  Opening the
        shelf as a fresh show instead would answer a word the HUD already has a
        button for with something else entirely.

        The rest play: every shelf belongs to one side, so a named side picks
        that side's copy and what lands on a region is homogeneous — exactly as
        it is when that shelf's own slideshow button opens it — and Latest plays
        newest-first the way that shelf's own show does.  Standalone, and hosted
        with no side named, it is the shelf on the side being browsed: there is
        no shelf spanning both to fall back to, and the half you are looking at
        is the half the word meant.  The browser is left where it is: this
        starts a show, it does not go browsing."""
        if command.shelf_key == _STARRED_KEY:
            self._toggle_f_mode_aloud(command.side)
            return
        orientation = (command.side if command.side and self._fun_time is not None
                       else self._current_side())
        key = oriented_key(command.shelf_key, orientation)
        rows = self._browser.rows_for_shelf(key) or []
        items = self._slideshow_items(rows)
        if not items:
            self._show_voice_status("🎤 nothing there to play", transient=True)
            return
        latest = command.shelf_key == _RECENTS_KEY
        self._open_slideshow(
            items, location=key, side=command.side,
            shuffle=(lambda order: None) if latest else None,
            order_label="Latest" if latest else "Shuffle",
            starred_ids=self._starred_prompt_ids(),
        )

    def _toggle_f_mode_aloud(self, side) -> None:
        """The spoken "favorites": the show's own F-mode switch, flipped.

        The same thing its HUD button does and the same thing the word does on
        a player, so the readout — the lit button and the status line — says so
        without anything here having to draw it."""
        show = self._voice_surface(side)
        if show is None or not hasattr(show, "toggle_f_mode"):
            self._show_voice_status(
                "🎤 F-mode needs a show to narrow", transient=True)
            return
        show.toggle_f_mode()
        self._show_voice_status(
            "🎤 F-mode on" if getattr(show, "hud_f_mode", False) else "🎤 F-mode off",
            transient=True)

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

    def _fix_parts(self, prompt_id: str | None, parts) -> tuple[str | None, str]:
        """Launch a targeted fix if the image wants one: the id it launched on
        (``None`` when it didn't) and the line the surface should say about it.

        The run is the image's latest enhancement done again with a detail pass
        aimed at each part named (:func:`~origenerator.gallery.enhance.
        fix_params_for`) — so the answer to a bad hand on an already-enhanced
        image is the same image, same settings, hand redrawn.

        Said back in the parts it is actually redrawing, which is not always the
        parts asked for: one with nothing installed to find it is dropped rather
        than taking the rest of the command down with it, and the caption is
        where that shows. Refused outright only when none of them can run."""
        asked = gallery.name_parts(parts)
        row = self._db.get_generation(prompt_id) if prompt_id else None
        if row is None or not gallery.is_enhanceable_row(row):
            return None, f"🎤 only a finished image can get a {asked} fix"
        params = gallery.fix_params_for(row, parts, self._enhance_settings)
        if params is None:
            return None, (f"🎤 no {asked} detector installed "
                          "(ComfyUI models/ultralytics/bbox)")
        if gallery.level_matching_params(row, params) is not None:
            return None, f"🎤 already has this {asked} fix"
        fixing = gallery.name_parts(
            [part for part in parts if part.name in params["enhance_detail_fixes"]])
        return self._launch_spoken_enhance(row, params, f"{fixing} fix",
                                           f"fixing {fixing}…")

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

    def _on_spoken_request(self, spoken, side: str | None = None):
        """One step of a spoken request — from the mic's dictation, or from the
        hosting session's channel with the region it was said to.

        While it is still being said the show holds and the corner says so;
        finished, it queues a revision of the item it was opened over. The
        target is taken at the opening step and kept, because a request is about
        the picture that prompted it, not whatever is up when the words run out.

        Hosted, *side* is what makes "the picture" a picture at all: two shows
        run at once on the satellite regions and neither is the active window,
        so the region named is the only thing that says which one the words are
        about.
        """
        show = self._voice_surface(side)
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
        self._begin_request(target, spoken, side)

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

    def _answer_request(self, show, message: str, *, working: bool = False):
        """Say what the request did, where the speaker is looking.

        *working* is the one line that is not an answer but a promise of one, so
        it is held rather than flashed: the working-out may go to the local LLM,
        and a corner that empties while the app is still at it says the request
        was dropped. Whatever comes back next releases the hold.
        """
        if show is not None:
            show.note_request(message, working=working)
        else:
            self._show_voice_status(message, transient=not working)

    def _begin_request(self, prompt_id: str | None, spoken, side: str | None = None):
        """Start working out what a finished request changes.

        The working-out goes to the pool because it may have to ask the local
        LLM which of the prompt's own terms the speaker meant, and a second of
        network wait on this thread is a second of frozen slideshow — at the one
        moment the app must not stutter. Whatever can be answered without that
        (nothing on screen, a recipe this app can't rebuild) is answered here,
        so a request that was never going to run doesn't wait on a model.

        The side rides the pool's context so the answer comes back to the same
        region the request was said to — seconds later, with two shows running,
        it is the only thing that still says which.
        """
        row = self._db.get_generation(prompt_id) if prompt_id else None
        show = self._voice_surface(side)
        if row is None:
            self._answer_request(show, "🎤 nothing on screen to request a change to")
            return
        workflow = WORKFLOW_REGISTRY.get(row.get("workflow_name") or "")
        if workflow is None or self._client is None:
            self._answer_request(
                show, "🎤 this one can't be re-made, so there's nothing to revise")
            return
        params = filled_params(row, workflow)
        self._answer_request(show, f"🎤 working out “{spoken.text}”…", working=True)
        QThreadPool.globalInstance().start(ReviseTask(
            self._revision, (row, workflow, params, spoken, side),
            params.get("positive_prompt", ""), params.get("negative_prompt", ""),
            spoken.text,
        ))

    def _on_request_revised(self, context, revision):
        """The revision came back from the pool: queue it, and say what it did.

        The show is looked up now rather than remembered, so an answer that took
        a couple of seconds still lands wherever the speaker is looking — on
        the region the request named, hosted, since two of them are up.
        """
        row, workflow, params, spoken, side = context
        show = self._voice_surface(side)
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
        """Hand a landed enhancement to every open show, so the item becomes
        the better version there rather than the version it was made from.
        Every one is told; each ignores an id it isn't holding — hosted, two
        run at once on the satellite regions.

        Not only while that item is the one on screen: an enhancement asked for
        from a show lands minutes later, by which time it has long paged on, so an
        upgrade it doesn't take here it never takes at all. The show also draws
        each item small as a neighbor, so it takes the new thumbnail with the file.
        """
        if row is None:
            return
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            return
        for surface in self._open_surfaces():
            surface.note_enhanced(row["prompt_id"], preview[0], preview[1],
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
        self._feed_slideshow_enhancing()

    def _feed_slideshow_enhancing(self):
        """Tell an open show how the enhancements in flight are going.

        A show is where a batch of them gets asked for — every held slide is a
        run — so it is the surface most likely to be looking at a picture whose
        turn has not come. The show cannot tell on its own: a hold hears only
        that a run started, not where in the line it landed. Told, its corner
        says whether the version is being made or waiting to be.

        Keyed by the mapping the tiles are drawn from, which covers every image
        in the library rather than the open folder's — a show of a shelf plays
        items from anywhere. The status is :meth:`_enhancing_run`'s, read off the
        job rather than its row: the row says "running" from the moment the job
        is handed to ComfyUI, and the wait on ComfyUI's own queue is exactly the
        stretch this is here to name.
        """
        if self._slideshow is None:
            return
        self._slideshow.note_enhancing({
            prompt_id: "running" if job.state == "running" else "queued"
            for prompt_id, (_key, job) in self._enhancing_by_prompt.items()
        })

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

    def _start_slideshow(self, *, side: str | None = None):
        """Open what's on screen — a folder, or the Latest/Favorites shelf —
        as a fullscreen slideshow, shuffled and running at the app-wide pace,
        and standing where the last show was closed when that slide is in
        here."""
        items = self._slideshow_items(self._slideshow_rows())
        if not items:
            return
        location = self._show_location()
        # Recents is Latest, exactly as on a Fun Time player: the shelf lists
        # newest first and its slideshow plays that order, where every other
        # set shuffles — and the show's HUD status line says which.
        base, orientation = _split_shelf_key(location)
        latest = base == _RECENTS_KEY
        show = self._open_slideshow(
            items, location=location, side=side or orientation,
            resume=self._show_state,
            shuffle=(lambda order: None) if latest else None,
            order_label="Latest" if latest else "Shuffle",
            starred_ids=self._starred_prompt_ids(),
        )
        logger.info("Slideshow of %s: %d items, %s order[:10]=%s",
                    self._slideshow_subject(), len(items),
                    "latest" if latest else "shuffled", show._playlist.order[:10])

    def _on_slideshow_closed(self, show=None):
        """A show was dismissed (however): let it go, with the hold it put on
        videos, and hand the OSR2 back to whatever the toggle was driving. The
        mic is untouched — it answers to its own button, and "start slideshow"
        has to still be heard now there is no show to hear it over.

        Named rather than assumed, because inside Fun Time two shows run at
        once: closing the portrait one must not forget the landscape one — and
        the videos stay held while the other one is still playing them.
        """
        # Where it had got to, so the next one opens back on that slide: the
        # look at the folder behind a picture doesn't cost the place among them.
        if show is not None and hasattr(show, "state"):
            self._show_state = show.state()
        self._live_shows = [entry for entry in self._live_shows
                            if entry[0] is not show]
        side = self._side_of(show) if show is not None else None
        if show is None or self._slideshow is show:
            self._slideshow = next((s for s, _loc in reversed(self._live_shows)), None)
        if self._slideshow is None:
            self._reroll.hold_videos(False)
        self._reconcile_osr2()
        if side is not None:
            # Whatever ended it -- the loop button pressed off, an Escape, a set
            # culled empty -- the region goes back to browsing its library.  The
            # player under it is blacked for the whole mode, so an empty region
            # is a black rectangle, which is the one thing the base state is for.
            self._region_shows[side] = None
            self._refill_region(side)

    def _show_location(self):
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
        return (self._selected_folder_key()
                if self._current_group() is not None else None)

    def _rows_at(self, location) -> list[dict]:
        """What a show opened at *location* would play if it opened now.

        Every key names a shape as well as a place: the shelves narrow
        themselves (``rows_for_shelf`` splits the key it is handed), and a
        folder row was built from one side's rows to begin with.  That is what
        lets a region's base state be "the whole library, this side's shape"
        and still be re-askable as the library grows.
        """
        if not location:
            return []
        rows = self._browser.rows_for_shelf(location)
        if rows is not None:
            return rows
        group = self._group_for_key(location)
        return gallery.rows_under(group) if group is not None else []

    def _open_generate_tab_for(self, prompt_id: str) -> None:
        """A lock on a hosted show: go to the held item, in the browser and in
        the tabs — the way the RFB answers a lock by opening the video's tab.

        The item itself, not one of its siblings.  Asking the pane to reveal a
        config brings forward whichever tab is already on that SETTINGS folder,
        and every seed of one recipe shares that folder — so the tab that came
        up was a sibling of the held picture rather than the picture, which is
        the "wrong item, a similar one" this used to open.  So the browser is
        navigated to the item first (its own folder, its own tile picked), and
        the tab is then loaded from the row that navigation selected.
        """
        row = self._row_for(prompt_id)
        if row is None:
            return
        self._on_source_link(prompt_id)  # its folder, its tile, out of any search
        self._info_tabs.load_selection(row, self._image_rows)


    def _starred_prompt_ids(self) -> set[str]:
        """Which generations are favorites (starred), for the shows' HUD: the
        star readout on the current item, and the F-mode narrowing — the same
        concepts the players' HUD wears, over the same collection the
        Favorites shelf lists."""
        return {row["prompt_id"] for row in self._db.list_generations()
                if row.get("starred")}

    def _present_surface(self, view, side: str):
        """Put a full-screen surface on screen: over the whole monitor
        standalone, or — inside Fun Time — on the satellite region *side*,
        replacing whatever show currently holds it.

        A region show is frameless (the region IS the window, like every
        managed player) and topmost, since the satellite player it covers is
        topmost itself; Fun Time restacks the band as its modes change.

        Either way it ends up wearing the players' HUD (:meth:`_wear_the_hud`):
        the panel is about the show, and a show is a show wherever it is.
        """
        if self._fun_time is None:
            view.showFullScreen()
            self._wear_the_hud(view, side)
            return
        occupant = self._region_shows.get(side)
        if occupant is not None and occupant.isVisible():
            occupant.close()
        view.setWindowTitle(SHOW_TITLES[side])
        view.setWindowFlags(
            view.windowFlags()
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
        )
        # Silent like every satellite: the session's main player owns the
        # room's audio, and this surface is landing on a satellite's region.
        # Standalone the same view is the deliberate foreground and plays sound.
        if hasattr(view, "set_audio_muted"):
            view.set_audio_muted(True)
        rect = self._fun_time.region_rect(side)
        view.setGeometry(rect.x, rect.y, rect.width, rect.height)
        view.show()
        # The show answers its own keys (a slideshow's arrows, a fullscreen
        # view's paging), so it takes the keyboard the moment it opens —
        # left unfocused, those keys land in the main window and the view
        # reads as dead.  raise_() first: activation alone does not lift a
        # window over the topmost players it shares the region with.
        view.raise_()
        view.activateWindow()
        self._region_shows[side] = view
        # A show opened while the hosting session is frozen opens frozen: the
        # room's OmniPause holds everything, this surface included, from its
        # first frame — not from whenever the flag next changes.
        if self._session_paused and hasattr(view, "set_session_paused"):
            view.set_session_paused(True)
        self._wear_the_hud(view, side)

    def _wear_the_hud(self, view, side: str) -> None:
        """Put the players' own HUD on *view* — the same panel, rendered by the
        same shared code: the status line, this side's transport, and the nav
        map speaking the set as a seed family.  The view's own furnishings come
        off with it, because the map says all of it.

        Hosted, the show covers a satellite player's HUD and has to BE that
        HUD: its session commands go out on the session's channel and the mode
        pair leads the panel.  Standalone the panel is the same panel minus
        those two — no channel to post on, so the transport lands on the show
        itself, and no session to switch modes on, so no mode row.

        A player_core with no shared HUD in it leaves the show as it was, with
        its own stills and plate still on — see :func:`_shared_hud_widget`.
        """
        hud = _shared_hud_widget()
        if hud is None or not hasattr(view, "adopt_hud"):
            return
        view.adopt_hud()
        hud(view, side=side,
            dashboard_cmd_file=(None if self._fun_time is None
                                else self._fun_time.dashboard_cmd_file))

    def set_session_paused(self, paused: bool) -> None:
        """The hosting session's OmniPause, applied to every open show and
        remembered for the ones not opened yet (see :meth:`_present_surface`).
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
        raises, so each is its own step: a freeze that stopped at the first
        show left the thumbnails running with no sign of why.
        """
        self._session_paused = paused
        # Every show this window has open, taken from the list it keeps of them
        # rather than from the region map: that map answers only for a show it
        # considers VISIBLE, and a show the session has covered or parked is
        # still a show that must not go on playing through a frozen room.
        for show, _where in list(self._live_shows):
            if not hasattr(show, "set_session_paused"):
                continue
            try:
                show.set_session_paused(paused)
            except Exception:
                logger.exception("Freezing a show failed")
        set_previews_paused(paused)
        self._info_tabs.set_previews_paused(paused)

    def region_show(self, side: str):
        """The show occupying satellite region *side*, or None — a closed
        window is no occupant, however recently it was one."""
        show = self._region_shows.get(side)
        return show if show is not None and show.isVisible() else None

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
        """A generation landed: it joins every open show that would be playing
        it had that show opened now.

        Which is the whole point of watching a folder that is auto-generating —
        the playlist is otherwise the fixed set the show opened with, so the
        items the loop makes while it runs are exactly the ones it never reaches.
        Asked of each show's OWN location, remembered when it opened, rather
        than of the view on screen: inside Fun Time the shows play on the
        satellite regions while the main window goes on being used, so by the
        time a generation lands the browser is usually somewhere else — and
        there may be two shows, of two different folders, both keeping up.
        """
        if row is None:
            return
        for show, location in list(self._live_shows):
            if not any(r["prompt_id"] == row["prompt_id"]
                       for r in self._rows_at(location)):
                continue
            for item in self._slideshow_items([row]):
                show.note_added(*item)

    def _feed_slideshow_generating(self, prompt_id: str, frame: bytes):
        """A run streamed a frame: an open show playing its folder takes it in as
        a slide of that frame, right now, and keeps it current from there.

        Waiting for the file is waiting minutes for the one thing the show is
        being watched for. The first iterations are already worth looking at, so
        the run joins on its first frame and swaps for the file when it lands.

        The membership question is asked once per run, either way: a run the show
        holds answers itself, and one it turned down is remembered as turned down
        (:attr:`_show_refused`). A frame arrives every second or so, and the
        question costs a row lookup and a walk of what is on screen.
        """
        show = self._slideshow
        if show is None or show.is_live():
            return  # a show already following one run full-screen is that run's
        if not show.holds(prompt_id) and not self._show_would_play(prompt_id):
            return
        show.note_generating(prompt_id, frame)

    def _show_would_play(self, prompt_id: str) -> bool:
        """Whether the open show would be playing a generation that has no file
        yet — the question :meth:`_feed_slideshow_finished` asks of the rows on
        screen, asked a few minutes earlier.

        A folder's show answers off those rows as usual: the tree keeps a run in
        flight in the folder its settings put it in, so it is already among them.
        A shelf's cannot — Recents is a shelf of results and a run has none yet —
        so Recents answers for itself, by its own rule: every generation this app
        makes lands there, and this is one. The other shelves are deliberate sets
        (starred, requested, condemned) that nothing joins by being made, and a
        search's hits are a set that was already asked for.

        An enhancement is nobody's slide, wherever it is running. It is a better
        version of a picture the show may already be playing, and it says so in
        that picture's own corner note — a second slide of it half-rendered
        would be the same image twice, one of them worse.

        A no is kept for the life of the show, since it is asked again of every
        frame of a run in some other folder — and the set behind a show doesn't
        move while one is up, the gallery being covered by it.
        """
        if prompt_id in self._show_refused:
            return False
        row = self._db.get_generation(prompt_id)
        plays = bool(
            row is not None
            and row.get("workflow_name") != gallery.ENHANCE_WORKFLOW
            and (any(r["prompt_id"] == prompt_id for r in self._slideshow_rows())
                 # Recents by its own rule, having no list of its own to consult.
                 or (self._browser.showing_recents()
                     and not self._browser.showing_search()
                     and (row.get("source") or "generated") == "generated"
                     and gallery.media_type_of_row(row) in self._media_types()))
        )
        if not plays:
            self._show_refused.add(prompt_id)
        return plays

    def _feed_slideshow_in_flight(self, items):
        """Tell an open show what is still being made, off the same in-flight list
        the queue plate in its corner is drawn from.

        Two things the frames alone can't say. A run whose frames began before the
        show opened sends no new one for a while — the tail of a run is all decode
        and save — and would otherwise be missing from a show of its own folder;
        and a run that was cancelled or failed sends nothing ever again, leaving
        the half-rendered frame it got to in the pass forever.
        """
        show = self._slideshow
        if show is None or show.is_live():
            return
        for item in items:
            if item.frame is not None and (show.holds(item.key)
                                           or self._show_would_play(item.key)):
                show.note_generating(item.key, item.frame)
        show.note_in_flight({item.key for item in items})

    def _open_from_slideshow(self, prompt_id: str):
        """A slideshow handed its item over on the way out — Enter, or a show
        ended while that slide was locked. Land in the item's own folder with it
        selected, the same jump a shelf tile's double-click makes, and open the
        item itself in a config tab.

        The tab matters as much as the folder: leaving a show *for* an item is a
        decision to work on it, and a folder open behind a form still holding
        whatever was there before the show is not that. Following a link only
        refreshes the front tab's preview, which is right for a link and wrong
        here. The slideshow has already closed itself, so this arrives on the
        gallery.
        """
        self._slideshow = None
        self._browser.open_in_containing_folder(prompt_id)
        row = self._row_for(prompt_id)
        if row is not None:
            self._info_tabs.load_selection(row, self._image_rows,
                                           self._request_for(prompt_id))

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

    # --- the line's answer to the press, before there is a job ------------

    def _combine_generate(self, image_id: str, video_id: str):
        """The combine panel's Generate with a dropped video, with the line
        showing it at once.

        The launch itself is left for the next turn of the event loop: reading
        every stored generation to check for a duplicate, building the params and
        posting the prompt all happen on this thread, and nothing painted while
        they did — so the stand-in row would have appeared only once the work it
        was standing in for was already over.
        """
        key = self._show_launching(image_id, video_id=video_id)

        def run():
            try:
                self._generate_combination(image_id, video_id)
            finally:
                self._drop_launching(key)

        self._after_painting(run)

    def _combine_generate_category(self, image_id: str, category: str, intent: str):
        """The combine panel's Generate with an act picked, with the line showing
        it at once. The act's own resolution is the long part — a question put to
        a local model — and :meth:`_generate_category` drops the stand-in when it
        has an answer, however that turns out."""
        key = self._show_launching(image_id, category=category)
        self._after_painting(lambda: self._generate_category(
            image_id, category, intent, launching=key))

    def _after_painting(self, work):
        """Run ``work`` on the next turn of the event loop, once what has just
        been laid out has actually reached the screen.

        A seam as much as a call, like :meth:`_run_off_thread`: the suite replaces
        this with a straight-through version, so a test can press and inspect in
        one breath rather than pumping an event loop for every launch.
        """
        QTimer.singleShot(0, work)

    def _show_launching(self, image_id: str, *, category: str = "",
                        video_id: str | None = None) -> str:
        """Put a stand-in row at the back of the line for a Generate just pressed,
        and return its key.

        It carries everything already known about the run — the frame being
        animated, the act, or the dropped video's clip in gray — so the row that
        replaces it is the same row with its price filled in, rather than a
        different-looking one appearing somewhere else. It offers no Cancel: there
        is nothing on the server to stop yet, and a button that did nothing is what
        this row exists to prevent.

        At the back because that is where it will land: nothing has been submitted,
        so every job already in the line is in front of it.
        """
        self._launch_seq += 1
        key = f"launching-{self._launch_seq}"
        image_row = self._db.get_generation(image_id) or {}
        video_row = self._db.get_generation(video_id) if video_id else None
        self._launching[key] = InFlightItem(
            key=key,
            caption="A video from Combine, still being started",
            status="queued",
            frame=None,
            reveal=lambda: None,  # no folder to open yet: it has no settings
            media_type="video",
            job_kind="I2V",  # the video slot takes nothing else
            recipe_category=category,
            # The same rule the finished row follows: a picked act names itself in
            # the text, and only a dropped video is shown.
            recipe_thumbnail=None if category else (video_row or {}).get("thumbnail_path"),
            source_image=gallery.output_file_reference(
                gallery.row_output_files(image_row)),
            starting=True,
        )
        self._update_queue()
        return key

    def _drop_launching(self, key: str | None):
        """Take a stand-in row back off the line — what it stood for is a real row
        now, or never became one. A no-op for a key already gone, so an exit path
        that drops it twice costs nothing."""
        if key is not None and self._launching.pop(key, None) is not None:
            self._update_queue()

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

    def _open_combination(self, image_id: str, video_id: str, category: str = ""):
        """Open a dropped image + video's recipe as an editable generate tab instead
        of running it — the combine panel's "Open in generator" path. The tab is
        prefilled with the same combination Generate would launch, ready to tweak,
        and shows the pair it was opened with rather than an empty pane."""
        built = self._combined_params(image_id, video_id)
        if built is None:
            return
        workflow, params, video_row, image_row = built
        self._open_prepared(workflow, params, image_row, video_row, category, video_id)

    def _open_prepared(self, workflow, params, image_row, video_row,
                       category: str, video_id: str | None):
        """Hand a built combination to a generate tab: its settings on the form, its
        two halves in the preview, and the mark saying where they came from.

        The preview is the point of the pair being visible at all — nothing has
        been generated from it yet, so the pane would otherwise sit on the line a
        tab pointed at nothing wears, with both things the tab is about on hand.
        A curated act has no ``video_row`` behind it, and shows the frame alone.
        """
        panel = self._info_tabs.open_config(workflow.name, params)
        if panel is None:
            return
        panel.set_recipe_source(category, video_id)
        panel.show_combination(
            self._still_path(image_row),
            self._animated_preview(video_row) if video_row is not None else None,
        )

    def _still_path(self, row: dict) -> str | None:
        """The best picture of ``row`` for a pane to show: its full-size output
        where that is a still, else the stored thumbnail (which a pane this big
        would be enlarging), else nothing."""
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is not None and preview[1] == "image":
            return str(preview[0])
        return row.get("thumbnail_path")

    def _generate_combination(self, image_id: str, video_id: str, send: bool = False,
                              category: str = ""):
        """Generate a new video from a dropped image + a dropped video's recipe.

        Reuses the video's workflow, settings and seed, swapping only the input
        image to the dropped one, and lands the result in the folder for that
        (image × settings) combination. A pinned seed can reproduce an identical
        past run, so a *pressed* combine warns first via the shared "already
        generated" dialog — which, when the dropped image is itself a re-buildable
        generation, offers a fresh video seed (same frame), a fresh image seed
        (re-draw the dropped image), or both. A no-op if either row is gone, the
        video isn't a rebuildable image-conditioned recipe, the image has no
        output file, or that folder is already generating.

        No lane reaches here: the lane chose which recipe ``video_id`` names, and
        from that point a Genau clip is made exactly like any other video. ``send``
        is the one thing that still rides along — a spoken "genau it" wants its
        clip handed on the moment it exists, and wants no dialog at all: it is
        answered in the show's corner and nothing runs, so the re-roll answers
        (and the frame re-draw behind them) belong to the pressed path alone.
        ``category`` names the act the dropdown was set to, when one was picked.
        The frame re-draw is the one answer it does not reach: that launches the
        frame first and the clip second, under an id this never sees, so such a
        clip's row goes without the recipe mark the queue reads.
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
            if send:
                # Spoken. The dialog below asks which of two seeds to re-roll,
                # and that question thrown over the fullscreen picture someone
                # is talking to is the one thing that must never appear — so the
                # spoken path gives the same answer the up-front guard gives and
                # stops. This is the case that guard can't see: the identical run
                # was made by hand, not said.
                self._say_already_genaud()
                return
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
            self._db.set_recipe_source(prompt_id, category=category,
                                       video_prompt_id=video_id)
            self._mark_for_sending(prompt_id, send)
            self._reveal_combination(key)

    def _say_already_genaud(self):
        """Say this picture has its clip already, where the speaker is looking.

        Only ever reached from a spoken command, which only runs with a show up
        — and where :meth:`_say_no_recipe` falls back to a dialog, this one has
        nothing to fall back to: a modal is precisely what it exists to avoid.
        """
        if self._slideshow is not None:
            self._slideshow.note_voice_run(None, ALREADY_GENAUD)

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
            then(None)  # nothing to match against, and the caller stops waiting
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
            # The act, with no video behind it: a curated recipe is pinned in the
            # overlay, so there is no past run for the queue row to show in gray.
            self._db.set_recipe_source(prompt_id, category=category)
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
                           intent: str = recipe_match.PLAYERS, send: bool = False,
                           launching: str | None = None):
        """Run the recipe that fits ``category`` on the dropped image: the
        overlay's curated recipe when one is pinned for the act, else the mined
        exemplar handed off to the shared combine launch. ``intent`` chooses which
        lane both tiers answer from; ``send`` hands the finished clip to Genau
        without a second ask.

        ``send`` also holds the picture until the launch is a row, because only a
        spoken "genau it" sets it and only a spoken one can be said again into
        the wait — see :meth:`_already_genaud`.

        ``launching`` is the stand-in row the press already put in the line
        (:meth:`_show_launching`), taken back off however this ends — launched,
        answered by no recipe, or unresolvable. The mined path is where it earns
        its keep: the act is answered by a local model that thinks for several
        seconds, and until it does there is nothing to queue.
        """
        if send:
            self._genau_resolving.add(image_id)
        if self._generate_curated(image_id, category, intent, send):
            self._genau_resolving.discard(image_id)
            self._drop_launching(launching)
            return
        self._resolve_category(
            image_id, category, intent,
            partial(self._combine_resolved, image_id, send, category, launching),
        )

    def _combine_resolved(self, image_id: str, send: bool, category: str,
                          launching: str | None, video_id: str | None):
        """The recipe match came back: run what it found on the image, if it
        found anything. ``category`` is the act it was asked for, which the
        launched row records — the mined video answers it, but only the act says
        what the user actually chose.

        The picture and the stand-in row are both let go of either way — a launch
        is a row from here on, which is where :meth:`_already_genaud` reads it and
        where the line reads the job, and a match that found nothing leaves
        nothing to wait for.
        """
        try:
            if video_id is not None:
                self._generate_combination(image_id, video_id, send, category)
        finally:
            self._genau_resolving.discard(image_id)
            self._drop_launching(launching)

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
            image_row = self._db.get_generation(image_id)
            if image_row is not None:
                self._open_prepared(workflow, params, image_row, None, category, None)
            return
        self._resolve_category(
            image_id, category, intent,
            lambda video_id: video_id is not None
            and self._open_combination(image_id, video_id, category),
        )

    def _on_combine_intent_changed(self, _intent: str):
        """Re-gray the act list for the lane just chosen."""
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

    def _already_genaud(self, row: dict) -> bool:
        """Whether this picture has been Genau'd — a clip made from it already,
        or one on the way.

        Saying it twice is what someone does when the first time appeared to do
        nothing, and it usually did appear to: the clip queues behind whatever
        the machine is on and the picture on screen doesn't change. Answering
        that with a second identical run spends minutes of the one GPU making a
        clip that already exists, and sends both to Genau.

        A run is a row stamped as spoken for (:meth:`_mark_for_sending`) and
        matched to this picture by its start frame — counted whether it is still
        coming (pending, running) or has landed, since both mean this picture
        has its clip. Read from the database rather than the live jobs, so a run
        reconnected after a restart still counts, and one made in a session
        since closed counts forever. A row that errored counts as nothing: it
        made no clip, and asking again is the only way to get one.

        There is also a stretch with no row at all: the mined tier asks the
        local model which recipe fits and that thinks for several seconds, which
        is exactly the silence a second command is said into, so the picture is
        held in :attr:`_genau_resolving` from the moment the command is heard
        until its row exists.
        """
        if row.get("prompt_id") in self._genau_resolving:
            return True
        return any(
            other.get("genau_requested_at")
            and (gallery.is_in_progress(other) or gallery.produced_output(other))
            and gallery.find_source_image_id(other, [row]) is not None
            for other in self._db.list_generations()
        )

    def _genau_it(self, image_id: str | None) -> tuple[str | None, str]:
        """Animate an image as a Genau clip: the act read off its own prompt.

        Returns the id it launched on (``None`` when it didn't) and the line the
        speaking surface should say — the same shape as :meth:`_fix_parts`, because
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
        if self._already_genaud(row):
            return None, ALREADY_GENAUD
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
        return asked or self._current_side()

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
        # ``key`` is the folder the job is filed under, so what it is checked
        # against is the folder on screen rather than the row showing it.
        if (key is None or key not in self._reroll_jobs
                or getattr(self._current_group(), "key", None) != key):
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

    def _on_reroll_preview(self, key: str, prompt_id: str, data: bytes):
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
        # And straight onto an open show, which is watching for exactly this.
        self._feed_slideshow_generating(prompt_id, data)

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
        if folded:
            # The image itself changed — it now holds a level it did not a
            # moment ago — and a tab holds the row it was handed, not a live
            # view of the database. Without this the new version reaches the
            # list only when the tab is next opened, which is a tab away and
            # back.
            self._info_tabs.refresh_displayed(finished_row, self._image_rows)
        if was_mirrored:
            self._show_mirrored_result(finished_row, launcher)
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

    def _media_types(self) -> set[str]:
        """The media types the gallery's two checkboxes currently include — what
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
        """A media-type checkbox toggled: rebuild the gallery under the new filter.

        A full rebuild rather than a re-list, because the boxes decide which
        *folders* exist as well as which items do — the tree, the shelves and the
        search index are all built from the same narrowed set."""
        self._browser.restart_recents_listing()  # a new filter is a new listing
        self.refresh()
        # A filter that empties the gallery leaves the tree with no row to
        # select, so the folder-selected signal that normally re-syncs this
        # button never fires — and it went on offering a show of nothing.
        self._sync_slideshow_button()

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
        Generate rather than after.

        Behind those, any Generate pressed but not yet turned into a job
        (:meth:`_show_launching`). They go on here rather than in the in-flight
        list itself because that list is what the database says is in flight, and
        these have no row in it: they are the press's answer, not a record of
        anything, and they last only until the real row exists.

        An open slideshow is fed the same list twice over: once for the queue it
        covers, which is the one stretch where the line deliberately stops
        moving, and once for the slides themselves, since a run that has begun to
        look like something is a slide of that show (:meth:`_feed_slideshow_in_flight`).
        """
        items = self._inflight_items() + list(self._launching.values())
        self._queue.set_items(items, self._foreign_queue.total)
        if self._slideshow is not None:
            self._slideshow.set_queue(items, self._foreign_queue.total)
            self._feed_slideshow_in_flight(items)

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
        delete_action = menu.addAction("Delete" + suffix)
        chosen = menu.exec(global_pos)
        if folder_action is not None and chosen is folder_action:
            self._on_source_link(rows[0]["prompt_id"])
        elif chosen is star_action:
            self.set_items_starred([row["prompt_id"] for row in rows], not all_starred)
        elif enhance_action is not None and chosen is enhance_action:
            self.enhance_items(enhanceable)
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
            self.enhance_items([prompt_id])

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
        for surface in self._open_surfaces():
            surface.release_media(paths)

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
        group = self._group_for_key(key)
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
        # Inside a folder the user made, a member tile can also be dropped from it.
        # Right-clicking the same folder in the tree offers nothing of the sort —
        # it isn't in any grouping from there.
        open_custom = self._current_group()
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
        group = self._group_for_key(key)
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
        group = self._current_group()
        if group is None:
            return
        self._actions.rename_folder(group.key, name.strip() or None)
        self._sync_history_buttons()
        # Rebuild on the next turn of the event loop rather than here. What
        # usually ends this edit is a click somewhere else in the window, and
        # "somewhere else" is most often a thumbnail — so refreshing inside the
        # editor's own focus-out deletes the browser pane that Qt is still
        # delivering that click to, and the app goes down with an access
        # violation. The tree's inline rename defers for the same reason.
        QTimer.singleShot(0, self.refresh)

    def _toggle_star(self, key: str):
        # A star is the folder's, not the row's: both sides draw the same folder,
        # so starring it on one is starring it.
        group = self._group_for_key(key)
        self._db.set_folder_starred(_base_of(key), not bool(group and group.starred))
        self.refresh()

    def _delete_folder_by_key(self, key: str):
        """Delete the folder a hover-row trash click names."""
        group = self._group_for_key(key)
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
        """The key of the shelf on screen — one side's Latest, Favorites,
        Experiments, Requests or Trash — or ``None`` off them."""
        key = self._selected_folder_key()
        base, _orientation = _split_shelf_key(key)
        return key if base in _SHELF_KEYS else None

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
            # _tree_item_for rather than a bare lookup: a stop recorded before the
            # tree grew sides names a folder key with no side on it, and that key
            # still has to find its row.
            row = self._tree_item_for(location.view)
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
    (the All row) and so has no one workflow time to fall back on."""
    if isinstance(group, gallery.AllGroup):
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
