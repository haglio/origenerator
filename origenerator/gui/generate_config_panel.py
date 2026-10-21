from __future__ import annotations

import json
import logging
from contextlib import contextmanager
from pathlib import Path

from PyQt6.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap
from PyQt6.QtWidgets import (
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shared_ui.orientation import orientation_of_size
from shared_ui.spacing import BUTTON_GAP, BUTTON_ROW_GAP, MARGIN_STANDARD

from origenerator import evolver_export
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import (
    COMFYUI_OUTPUT_DIR,
    EVOLVER_SOURCE,
    EVOLVER_UPSCALED_DIR,
)
from origenerator.db import Database
from origenerator.evolver_upscales import EvolverUpscales
from origenerator.gallery import (
    EnhanceSettings,
    config_folder_key,
    config_folder_name,
    describe_enhance_params,
    displayed_levels,
    enhance_params_for,
    level_matching_settings,
    media_type_of_row,
    output_file_path,
    prompts_differ_from,
    resolve_preview,
    settings_signature,
    workflow_output_type,
)
from origenerator.gallery.sides import PORTRAIT
from origenerator.generation_config import (
    ConfigSnapshot,
    configs_match,
    merge_denormalized,
    would_reproduce_a_completed_run,
)
from origenerator.gui import icons
from origenerator.gui.combination import Combination
from origenerator.gui.corner_controls import enhance_state
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.enhance_versions import EnhanceOffer, EnhanceVersions, RunningEnhancement
from origenerator.gui.export_lane import UNSEND_CAPTION, lane_for
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.folder_request import FolderRequest
from origenerator.gui.generate_button import (
    DEFAULT_CAPTION,
    RANDOM_SEED_CAPTION,
    GenerateButton,
)
from origenerator.gui.how_many import GenerateWithHowMany, HowManyPicker
from origenerator.gui.inflight import (
    ALREADY_MAKING_ONE_TIP,
    discard_run_text,
    discard_run_tooltip,
)
from origenerator.gui.label_cells import LabelCell, LabelColumn
from origenerator.gui.metadata_block import MetadataBlock
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.panes import PaneSplitter, pane, pane_border
from origenerator.gui.param_form import ParamForm
from origenerator.gui.picture_state_picker import PictureStatePicker
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.related_media import RelatedMedia
from origenerator.gui.warning_mark import WarningMark
from origenerator.item_names import ItemNames
from origenerator.library_views import LibraryViews
from origenerator.media import MediaType
from origenerator.osr2_driver import drive_target_for
from origenerator.picture_states import state_names
from origenerator.seed_history import SeedUse, SeedUseKind, seed_history
from origenerator.setting_advice import (
    fresh_settings,
    recommendations,
    recommended_choices,
    setting_advice,
)
from origenerator.timing import estimate_label
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_CAPTION_DELAY_MS = 250    # settle before re-reading whether Generate would duplicate
_RANDOM_SEED_TIP = (
    "These settings have already been generated with this exact seed, so "
    "Generate draws a fresh one rather than re-creating the same file. "
    "Change a setting to generate something else instead."
)
# Breathing room round the tab's contents, and between the form and the scroll
# bar beside it — enough that nothing reads as jammed into a corner, small
# enough that a narrow pane still spends its width on the fields.
# How far the "never narrower than its contents" floor below is allowed to go.
# One thing in the tab is wider than a tiling-narrow window can give the info pane
# — an image's list of versions, a picture beside a file's facts and buttons — and
# a floor that insisted on it would take the whole window out of the monitor-third
# slot it has to fit (see tests/test_main_window.py). Past this the settings scroll
# sideways after all, which is the smaller of the two losses.
_FLOOR_CAP = 330

# What the preview says once the form has been edited away from the generation
# on it: that picture was generated, these settings have not been.
_MODIFIED_NOTICE = "(not yet generated with modifications)"

# What the preview says while following a run that has streamed no frame yet,
# where the gallery has nothing more specific to say about the wait.
_WAITING_NOTE = "Waiting for preview…"

# What a tab opened on a folder-wide request says on its Generate and above
# its tabs. The count is in the hover rather than on the face: the press does
# submit that many runs at once, which is worth being able to read, but what
# the button asks for is one thing — this folder, said the way it now reads.
_REQUEST_GUARD = "Rewrite the prompt first"

_GO_TO_FOLDER_TIP = "Go to the folder this item is in"


def _nothing_to_start_from(missing_images: list[str]) -> str:
    named = " and ".join(missing_images)
    article = "an" if named[:1].lower() in "aeiou" else "a"
    return f"Nothing to start from — pick {article} {named} first"


class GenerateConfigPanel(QWidget):
    """One generation configuration: pick a workflow and set its params.

    Clicking Generate doesn't run a job here — it emits :attr:`generate_requested`
    for the gallery to launch as a re-roll of this config's settings folder. The
    panel is one column: a fixed preview on top, then a single button bank over
    one scroll holding the File/Created block above the editable form and, at its
    foot, the displayed generation's related media. Generate's caption says when a
    press will draw a fresh seed rather than re-create what these settings have
    already made, and the info appears only while a saved generation is on show.

    What acts on the generation itself is on the picture rather than in the bank:
    the preview wears the same star / trash / plus corners a gallery thumbnail
    does, and right-clicking it raises the same menu. Each file row carries a
    "Go to folder" beside its Show in Explorer.

    A fresh panel opens with no workflow picked — the pane's resting state.
    """

    title_changed = pyqtSignal(str)     # current tab name (its mark moves with it)
    form_edited = pyqtSignal()          # any field changed — every keystroke
    # A field changed because someone changed it — the workflow picker included,
    # and never the seeding a load does. What tells the tab strip this tab is
    # being worked in rather than looked at (see _loading_config).
    user_edited = pyqtSignal()
    form_replaced = pyqtSignal()        # a new workflow swapped the param form out
    source_activated = pyqtSignal(str)      # the source-image tile was clicked (prompt_id)
    animated_activated = pyqtSignal(str)    # an animation tile was clicked (prompt_id)
    item_action_requested = pyqtSignal(str, str)   # a preview corner: prompt_id, action
    context_menu_requested = pyqtSignal(str, QPoint)  # preview right-clicked: id, global pos
    go_to_folder_requested = pyqtSignal(str)  # a file row's "Go to folder": the shown prompt_id
    generate_requested = pyqtSignal(str, list)  # Generate clicked: (workflow_name, each one's params)
    # Generate clicked on a folder rewrite: (source folder key, workflow_name, form
    # params). A separate signal because it asks for something else entirely — one
    # run per picture in that folder, each keeping its own seed.
    changes_requested = pyqtSignal(str, str, dict)
    cancel_requested = pyqtSignal()         # Cancel clicked: stop this config's in-flight run
    how_many_chosen = pyqtSignal(int)
    displayed_changed = pyqtSignal()        # the shown generation changed (drive reconcile cue)
    preview_drag_started = pyqtSignal(str)  # the preview's media began dragging (prompt_id) — combine cue
    preview_drag_ended = pyqtSignal()       # that drag finished (dropped or canceled)
    enhance_requested = pyqtSignal(str)      # the version list's "+ Enhance" was pressed (prompt_id)
    levels_delete_requested = pyqtSignal(str, list)  # bin these versions of this image (prompt_id, filenames)

    def __init__(self, client: ComfyUIClient | None, db: Database, parent=None,
                 *, fun_time=None, heights=None,
                 inbox: evolver_export.EvolverInbox | None = None,
                 library: LibraryViews | None = None,
                 names: ItemNames | None = None):
        super().__init__(parent)
        self._heights = heights  # the window's prompt heights, for its forms
        # Where a clip is handed to Evolver. Asked for rather than performed
        # here: the destination is one object's to know, and a test points it at
        # a directory of its own instead of patching a constant this module
        # imported (origenerator.evolver_export).
        self._inbox = inbox or evolver_export.default_inbox()
        self._client = client                        # None in a read-only gallery: the form shows, but Generate is off
        self._db = db
        self._library = library or LibraryViews(db)
        self._names = names or ItemNames(db)
        self._param_form: ParamForm | None = None
        self._generating = False                       # a run this tab launched is in flight (offers the discard button)
        self._folder_generating = False
        self._launched_runs: list[str] = []            # the runs this tab's Generate started (see launched_runs)
        # The settings folder whose live run this tab's preview follows — its
        # own Generate's, or the run it was pointed at by a click on that
        # folder's live tile (see watch_folder). None while the preview is the
        # tab's own picture. Beside it, the wait text standing in for a frame
        # that hasn't streamed yet, so the same text isn't re-painted every poll.
        self._watched_key: str | None = None
        self._live_note: str | None = None
        # The pair standing in for a frame that hasn't streamed — kept so the
        # same one isn't rebuilt every poll, which would restart the clip's loop
        # from frame one each second.
        self._live_source: Combination | None = None
        self._displayed_row: dict | None = None        # a saved generation this tab is showing (footer visible); None when blank
        # (status, frame, settings) of an enhancement running on the displayed
        # image, fed from outside (the gallery owns the jobs); None when nothing
        # is in flight. Beside it, the app-wide enhance settings the "+ Enhance"
        # card would run at — also the gallery's, pushed in the same way.
        self._pending_enhancement: RunningEnhancement | None = None
        self._enhance_settings = EnhanceSettings()
        # The settings the preview's generation went on display under, captured
        # whenever one does. Editing the form away from these is what marks the
        # preview as no longer showing what a Generate would make; None whenever
        # there's no saved generation on display to be modified away from.
        self._displayed_config: ConfigSnapshot | None = None
        # Set while this tab is a whole folder's prompt rewrite rather than one
        # configuration: the folder being rewritten, what to call it, how many
        # pictures the press will run, and the settings it opened on — which is
        # what says whether anything has actually been rewritten yet.
        self._folder_request: FolderRequest | None = None
        # Where this tab's settings came from, when the Combine panel opened them
        # here: the act picked in its dropdown and the video whose recipe they
        # are, as (category, video_prompt_id). Carried so a run launched from this
        # tab — the combination as opened, or edited first — says in the queue what
        # it was asked for. Nothing else on the form remembers either.
        self._recipe_source: tuple[str, str | None] = ("", None)
        self._recipe_row: dict | None = None
        # Re-reads (shortly) whether Generate would reproduce a past run — see
        # refresh_generate_caption for why the answer isn't taken on the spot.
        self._caption_timer = QTimer(self)
        self._caption_timer.setSingleShot(True)
        self._caption_timer.setInterval(_CAPTION_DELAY_MS)
        self._caption_timer.timeout.connect(self._apply_generate_caption)
        # The hosting session, or None standalone.  Hosted, this tab lives in
        # the RFB's upright column, where a portrait picture stacked over the
        # form pushes every prompt field off the foot (_reflow_for_the_media).
        self._fun_time = fun_time
        # How deep we are inside a load — a prefill, a restore, a seed the
        # gallery set. Every one of those writes to the same widgets a person
        # types in, so the widgets' own signals cannot tell the two apart; this
        # is what does, and user_edited is silent while it is up. A depth rather
        # than a flag because the loads nest (restore_config prefills, prefill
        # re-picks the workflow, which re-seeds the carried-over fields).
        self._loading_config = 0
        self._fresh_form = False
        self._form_checkpoint = None
        self._autoshow_held = False   # see _point_elsewhere
        self._go_to_folder = QAction("Go to folder", self)
        self._go_to_folder.setToolTip(_GO_TO_FOLDER_TIP)
        self._go_to_folder.setVisible(False)  # until the gallery says there is a folder
        self._go_to_folder.triggered.connect(self._on_go_to_folder)
        self._can_go_to_folder = None   # the gallery's; see set_folder_check
        self._build_ui()

    @contextmanager
    def _loading(self):
        """Mark everything done inside as a load, not as someone editing."""
        self._loading_config += 1
        try:
            yield
        finally:
            self._loading_config -= 1

    def _note_user_edit(self):
        """Pass on a field change someone made; swallow the ones a load makes."""
        if not self._loading_config:
            self.user_edited.emit()

    def _build_ui(self):
        """The column, in the order it reads: the preview, then the splitter's
        handle, then the button bank over one scroll holding everything that is
        about the settings.

        Each region below builds itself and says why it is the way it is; this
        is only their order, which is the one thing about them a reader has to
        take in at once. Two orderings inside them are load-bearing and are
        noted where they happen: the picker takes its index before its signal is
        connected, and _on_workflow_changed runs last, once everything it lays
        out below the picker exists.
        """
        layout = QVBoxLayout(self)
        # Top and foot only: the splitter below spans the tab, so its handle
        # meets the pane's own border instead of stopping short of it, and the
        # margin that keeps the preview, the form and the bank off the pane's
        # sides is inside each of them.
        layout.setContentsMargins(0, MARGIN_STANDARD, 0, MARGIN_STANDARD)
        self._build_preview()
        body = self._build_body_scroll()
        self._build_saved_generation_block(body)
        self._build_workflow_header(body)
        self._build_related_media(body)
        # The slack goes here, under everything, so a short column rests at the
        # top of the scroll rather than spreading itself out.
        body.addStretch(1)
        self._settings_pane = self._build_settings_pane()
        self._media_split.addWidget(self._settings_pane)
        self._media_split.hold_still(self._fun_time is not None)
        layout.addWidget(self._media_split, 1)
        self._media_side_by_side = False
        self._picture_border: list[int] | None = None
        # Lays out the empty state on a fresh panel — no form, no estimate, and a
        # Generate with nothing to run — and everything below the picker once a
        # workflow is chosen. Last, because everything it lays out has to exist.
        self._on_workflow_changed()

    def _build_preview(self) -> PreviewWidget:
        """The pane leading the column: a running re-roll's frames (driven from
        outside), the browsed generation's output when one is loaded, and the
        newest matching result otherwise."""
        self._preview = PreviewWidget(show_timeline=True)
        # Dragging the shown generation out of the preview onto a combine slot, like a
        # gallery thumbnail: relay the drag start/end so the view can light the slots.
        self._preview.drag_out.started.connect(self.preview_drag_started)
        self._preview.drag_out.ended.connect(self.preview_drag_ended)
        # Its corners and its right-click go to the gallery, which owns the
        # bookmark, the bin and the enhance queue — the same route the browser
        # pane's thumbnails take, so an act means the same thing either side.
        self._preview.action_triggered.connect(self.item_action_requested)
        self._preview.context_requested.connect(self.context_menu_requested)
        # The preview and the settings under it share a splitter, so the line
        # between them is a drag handle like every other pane boundary in this
        # app: a tall picture can be given the room it wants without the form
        # being pinned to a ratio someone else chose.
        self._media_split = PaneSplitter(Qt.Orientation.Vertical)
        # The picture keeps its margin inside this, so the splitter itself can
        # span the tab (see _build_ui).
        self._preview_pane, preview_column = pane()
        preview_column.setContentsMargins(MARGIN_STANDARD, 0, MARGIN_STANDARD, 0)
        preview_column.addWidget(self._preview)
        self._media_split.addWidget(self._preview_pane)
        self._preview.media_resized.connect(self._reflow_for_the_media)
        return self._preview

    def _build_body_scroll(self) -> QVBoxLayout:
        """One scroll under the button bank for everything else, and the column
        inside it that the three regions below fill.

        The read-only info on top, the editable form below it, so they scroll
        together. This replaces the old split — a cramped form-only scroll above
        a separate, non-scrolling info footer — that buried the form
        (width/height, the swap button) out of reach.
        """
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        # Said here rather than left to the stylesheet's `border: none`, so the
        # margin below is the whole of what stands between the fields and the
        # pane's edge however this is styled.
        self._scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        body_host = QWidget()
        body = QVBoxLayout(body_host)
        # The scroll spans the tab, so the margin keeping the fields off the
        # pane's sides and off the border above them is here; on the right it
        # also stops them running under the scroll bar.
        body.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD,
                                MARGIN_STANDARD, 0)
        body.setSpacing(8)
        self._scroll.setWidget(body_host)
        return body

    def _build_saved_generation_block(self, body: QVBoxLayout) -> None:
        """The output file, when it was made and the workflow version that made
        it, at the top of the scroll (shown only while displaying a saved
        generation). Above the form, because it names what the settings below it
        made. Params — editable or read-only — all live in that form now, so
        this block carries only those facts.

        What the picture shows sits with them, for the same reason: it is a fact
        about the finished picture rather than a setting that made it, and it is
        the one of these facts anyone can change."""
        self._metadata_block = MetadataBlock(go_to_folder=self._go_to_folder)
        self._metadata_block.hide()
        body.addWidget(self._metadata_block)
        self._picture_state = PictureStatePicker(state_names())
        self._picture_state.chosen.connect(self._on_picture_state_chosen)
        body.addWidget(self._picture_state)

    def _on_picture_state_chosen(self, prompt_id: str, state: str) -> None:
        """Record what the picture on display shows — the same column the
        sorting window writes, so a picture answered here is answered there."""
        self._db.set_picture_state(prompt_id, state or None)

    def _build_workflow_header(self, body: QVBoxLayout) -> None:
        """The editable half: the workflow picker, its typical-time estimate, and
        the host the param form is swapped into whenever the workflow changes."""
        self._form_workflow_key = None  # which workflow the installed form belongs to
        # A form row rather than a plain side-by-side pair, so that squeezed past
        # what the word and the picker can share, the picker drops onto its own
        # line — the same wrap the sections below it do — instead of holding the
        # pane open and putting a horizontal scroll bar under the whole form.
        header = QFormLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(8)
        header.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        header.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )
        self._workflow_combo = NoWheelComboBox()
        # Machinery workflows (the standalone image enhancer) stay out of the
        # picker: they're launched by gallery buttons, and their results fold
        # into existing images rather than forming generations of their own.
        for key, wf in WORKFLOW_REGISTRY.items():
            if wf.selectable:
                self._workflow_combo.addItem(wf.display_name, key)
        # Open on no workflow at all, so a fresh tab asks which one to run rather
        # than presenting whichever happens to be registered first as a choice
        # already made. Set before the signal is connected: nothing below the
        # picker is built yet at this point in the layout.
        self._workflow_combo.setPlaceholderText("Select a workflow…")
        self._workflow_combo.setCurrentIndex(-1)
        self._workflow_combo.currentIndexChanged.connect(self._on_workflow_changed)
        # Picking a workflow is an edit as much as typing in a field is, and on a
        # form with nothing to carry over it is the only signal there is.
        self._workflow_combo.currentIndexChanged.connect(self._note_user_edit)
        self._workflow_warning = WarningMark()
        self._workflow_warning.pressed.connect(self._resolve_every_warning)
        # It shrinks to a short floor when the pane is narrow rather than holding
        # the width of the longest workflow name — see NoWheelComboBox, which every
        # picker in the app inherits that from. It still expands to fill the row.
        header.addRow(LabelCell(self._workflow_warning, ElidingLabel("Workflow"), LabelColumn()),
                      self._workflow_combo)
        body.addLayout(header)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        # A sentence, so it wraps rather than holding the pane open at its own
        # length — the form below it shrinks, and this has to shrink with it.
        self._estimate_label.setWordWrap(True)
        body.addWidget(self._estimate_label)
        self._form_host = QWidget()
        self._form_host_column = QVBoxLayout(self._form_host)
        self._form_host_column.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self._form_host)

    def _build_related_media(self, body: QVBoxLayout) -> None:
        """What the generation on display is tied to, below the form: what it
        was built from and what it was animated into
        (:class:`~origenerator.gui.related_media.RelatedMedia`), and every version
        an enhanced image holds. All of it hidden while the tab shows no saved
        generation, unless Combine opened it, and stacked straight under the form
        with no stretch between — a stretch grew an elastic gap above them by
        exactly what folding a form section saved.
        """
        self._related = RelatedMedia(video_rows=self._video_rows,
                                     row_of=self._db.get_generation,
                                     name_of=self._names.of)
        self._related.source_activated.connect(self.source_activated)
        self._related.animated_activated.connect(self.animated_activated)
        body.addWidget(self._related)
        # The preview opens on the most-enhanced version, and this is where the
        # earlier levels (and the original) are, each captioned with what made
        # it and draggable onto the Enhance subpanel to reuse those settings.
        # Hides itself for an image with only its original, which is most of them.
        self._versions = EnhanceVersions()
        # What the list is showing, in its order: the positions its rows report
        # are only good against this.
        self._listed_levels = []
        self._versions.level_selected.connect(self._show_level)
        self._versions.enhance_requested.connect(self._on_enhance_requested)
        self._versions.delete_requested.connect(self._on_levels_delete_requested)
        body.addWidget(self._versions)

    def _build_settings_pane(self) -> QWidget:
        settings_pane = QWidget()
        column = QVBoxLayout(settings_pane)
        column.setContentsMargins(0, MARGIN_STANDARD, 0, 0)
        column.setSpacing(0)
        bank = self._build_button_bank()
        bank.setContentsMargins(MARGIN_STANDARD, 0, MARGIN_STANDARD, MARGIN_STANDARD)
        column.addLayout(bank)
        self._settings_border = pane_border()
        column.addWidget(self._settings_border)
        column.addWidget(self._scroll, 1)
        return settings_pane

    def _build_button_bank(self) -> FlowLayout:
        """One bank, fixed over the scroll so Generate is always reachable.

        The lane button shows only for a video on display, and the discard
        button only while a run this tab launched is in flight — "Cancel", or "Next
        seed" while that folder is auto-generating. A flow rather than a row: it
        wraps onto a second line when the pane is too narrow, instead of squeezing
        every label down to an unreadable stub.
        """
        btn_row = FlowLayout(spacing=BUTTON_GAP, row_spacing=BUTTON_ROW_GAP,
                             align_right=True)
        self._lane_button = QPushButton()
        self._lane_button.clicked.connect(
            lambda _checked=False: self._on_send(self._offered_lane))
        btn_row.addWidget(self._lane_button)
        self._sent_row = self._build_sent_row()
        btn_row.addWidget(self._sent_row)
        self._offered_lane = None
        self._update_lane_button(None)
        self._cancel_btn = QPushButton(discard_run_text(False))
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.hide()
        self._generate_btn = GenerateButton()
        self._generate_btn.clicked.connect(self._on_generate)
        self._how_many = HowManyPicker()
        self._how_many.chosen.connect(self.how_many_chosen)
        btn_row.addWidget(self._cancel_btn)
        self._generate_pair = GenerateWithHowMany(self._generate_btn, self._how_many)
        btn_row.addWidget(self._generate_pair)
        return btn_row

    def _build_sent_row(self) -> QWidget:
        row = QWidget()
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.setSpacing(BUTTON_GAP)
        self._sent_note = QLabel()
        self._unsend_button = QPushButton(UNSEND_CAPTION)
        self._unsend_button.clicked.connect(
            lambda _checked=False: self._on_unsend(self._offered_lane))
        line.addWidget(self._sent_note)
        line.addWidget(self._unsend_button)
        return row

    def minimumSizeHint(self):
        """Never narrower than the settings can be squeezed into.

        The pane refuses to be dragged past what its contents fit in rather than
        scrolling them sideways, read live from the scroll's contents so the floor
        follows the workflow on show. No explicit ``setMinimumWidth`` here or on
        the wrapper this sits in: an explicit minimum *replaces* this hint rather
        than joining it, so one would pin the floor at its own number and put the
        scroll bar back. Capped at ``_FLOOR_CAP``, where holding the floor would
        cost the window its tiling slot.
        """
        hint = super().minimumSizeHint()
        hint.setWidth(min(self._contents_floor(), _FLOOR_CAP))
        return hint

    def _contents_floor(self) -> int:
        """The narrowest the tab can be with its settings still whole: what the
        scroll's contents need, plus the vertical scroll bar beside them, the
        scroll's own frame, and the pane's margins."""
        body = self._scroll.widget()
        return (body.minimumSizeHint().width()
                + self._scroll.verticalScrollBar().sizeHint().width()
                + 2 * self._scroll.frameWidth()
                + 2 * MARGIN_STANDARD)

    def _can_generate(self) -> bool:
        return (self._client is not None
                and self._workflow_combo.currentData() is not None
                and not self._folder_generating
                and not self._missing_images())

    def _sync_generate(self) -> None:
        self._generate_pair.setEnabled(self._can_generate())
        missing = self._missing_images()
        if missing:
            self._generate_btn.setToolTip(_nothing_to_start_from(missing))

    def set_how_many(self, count: int) -> None:
        self._how_many.set_how_many(count)

    def note_folder_generating(self, generating: bool) -> None:
        self._folder_generating = generating
        self._sync_generate()
        self.refresh_generate_caption()

    def _missing_images(self) -> list[str]:
        wf = WORKFLOW_REGISTRY.get(self._workflow_combo.currentData() or "")
        if wf is None or self._param_form is None:
            return []
        return wf.missing_images(self._param_form.get_values())

    def _on_workflow_changed(self):
        # A different workflow is a different recipe: whatever Combine opened
        # here no longer describes what this tab would run, so its mark goes
        # rather than riding onto an unrelated launch. Set again after a prefill,
        # which is what re-picks the workflow in the first place.
        self._forget_recipe_source()
        # And a folder's rewrite is a rewrite of that folder's own recipe. Swap
        # the workflow and the form is rebuilt from scratch — the tracked prompt
        # fields with it — so what is left is an ordinary config, not a rewrite
        # of anything.
        self._end_folder_request()
        self._fresh_form = False
        key = self._workflow_combo.currentData()
        if key and key in WORKFLOW_REGISTRY:
            wf = WORKFLOW_REGISTRY[key]
            edited = self._edited_form_values()
            # An i2v workflow derives its output size from the input image; hand
            # the form that deriver so it can show the size in a locked, unlockable
            # Dimensions field. A manual-size workflow passes None and lays out its
            # own width/height as usual.
            deriver = wf.derived_display_size if wf.derives_size_from_input else None
            # The enhance params stay off the form: everything laid out here
            # decides which gallery folder a run lands in, and an enhancement
            # doesn't — the browser pane's Enhance subpanel owns it per folder.
            # They still round-trip, so reusing an old run reproduces it exactly.
            self._install_form(ParamForm(wf.param_definitions(), size_deriver=deriver,
                                         hidden_keys=wf.enhance_keys(),
                                         pins_reused_seed=wf.pins_reused_seed(),
                                         heights=self._heights,
                                         seed_history=self._seed_history))
            self._form_workflow_key = key
            defaults = wf.default_params()
            carried = {
                k: v for k, v in edited.items()
                if k in defaults and v != defaults[k]
            }
            if carried:
                self._param_form.set_values(carried)
                self._param_form.put_seeds(carried, is_random=False)
            checkpoint = self._param_form.get_values().get("checkpoint")
            if not self._loading_config:
                self._rebase_on_the_model(None, checkpoint, keep=edited)
                self._fresh_form = True
            self._form_checkpoint = checkpoint
        else:
            self._clear_form()  # no workflow picked: nothing below is known yet
        self._show_advice()
        self._refresh_estimate()
        self.refresh_generate_caption()
        self._sync_generate()
        self._emit_title()
        self.show_recent_preview()  # these settings' newest result, not a blank pane

    def _edited_form_values(self) -> dict:
        """What the user changed on the installed form: its values minus the keys
        still where a fresh form of its workflow and model puts them. Switching
        workflows carries these over (where the new workflow shares the param), so
        a typed prompt or picked image survives the switch — while the departing
        form's own starting values never leak into the next one's."""
        prior = WORKFLOW_REGISTRY.get(self._form_workflow_key or "")
        if self._param_form is None or prior is None:
            return {}
        values = self._param_form.get_values()
        fresh = fresh_settings(prior.default_params(), values.get("checkpoint"))
        drawn = self._param_form.random_seed_keys()
        return {
            k: v for k, v in values.items()
            if k not in drawn and (k not in fresh or v != fresh[k])
        }

    def _follow_the_model(self):
        if self._param_form is None:
            return
        before = self._form_checkpoint
        self._form_checkpoint = self._param_form.get_values().get("checkpoint")
        if self._fresh_form and not self._loading_config and before != self._form_checkpoint:
            self._rebase_on_the_model(before, self._form_checkpoint)

    def _rebase_on_the_model(self, before, after, keep=()):
        defaults = WORKFLOW_REGISTRY[self._form_workflow_key].default_params()
        old, new = fresh_settings(defaults, before), fresh_settings(defaults, after)
        following = {k: new[k] for k, v in self._param_form.get_values().items()
                     if k in old and k not in keep and v == old[k] != new[k]}
        with self._loading():
            self._param_form.set_values(following)

    def _show_advice(self):
        form = self._param_form
        if form is not None:
            values = form.get_values()
            form.set_warnings(setting_advice(values, form.definitions()))
            form.mark_recommended(recommended_choices(values))
            form.explain(recommendations(values))
        self._workflow_warning.warn(form.every_warning() if form is not None else "")

    def _resolve_every_warning(self):
        self._param_form.resolve_every_warning()

    def _detach_form(self):
        """Take the installed form off the panel, if there is one.

        Detached from its parent at once (not just scheduled for deletion), so it
        leaves the screen immediately instead of lingering under whatever comes
        next until the event loop spins.
        """
        if self._param_form is None:
            return
        self._form_host_column.removeWidget(self._param_form)
        self._param_form.setParent(None)
        self._param_form.deleteLater()
        self._param_form = None

    def _clear_form(self):
        """Leave the panel with no form at all — the state of a tab whose picker
        is still on its placeholder. Which params exist is the workflow's answer,
        so until one is chosen there is nothing truthful to lay out."""
        had_form = self._param_form is not None
        self._detach_form()
        self._form_workflow_key = None
        if had_form:
            self.form_replaced.emit()  # an open find must let go of its fields

    def _install_form(self, form: ParamForm):
        """Swap the workflow's ParamForm into the form host inside the scroll,
        discarding the previous one. The form lives in the shared scroll so it moves
        with the info above it, not walled into a separate scroll of its own."""
        self._detach_form()
        self._param_form = form
        self._param_form.changed.connect(self.form_edited)
        self._param_form.changed.connect(self._note_user_edit)
        self._param_form.changed.connect(self._follow_the_model)
        self._param_form.changed.connect(self._show_advice)
        self._param_form.changed.connect(self.refresh_modified_notice)
        self._param_form.changed.connect(self._mark_recipe_prompt_edits)
        # Any edit can make the config match a past generation, or stop matching one.
        self._param_form.changed.connect(self.refresh_generate_caption)
        self._param_form.changed.connect(self._sync_generate)
        self._param_form.seed_drawn.connect(self._record_drawn_seed)
        self._form_host_column.addWidget(self._param_form)
        # Announced while the outgoing form is still alive (Qt defers the actual
        # deletion), so an open find can let go of its fields before they die.
        self.form_replaced.emit()

    def prompt_fields(self) -> list:
        """This tab's prompt inputs, for a find over the words it would generate
        from. Empty until a workflow's form is installed."""
        return self._param_form.text_fields() if self._param_form is not None else []

    def _emit_title(self):
        self.title_changed.emit(self.title())

    def _refresh_estimate(self):
        """Show how long this workflow typically takes, from its recent runs.

        Hidden entirely with no workflow picked: a typical time belongs to a
        workflow, and "no runs yet" over an unanswered picker reads as a fact
        about the app rather than about the question still being asked.
        """
        wf = WORKFLOW_REGISTRY.get(self._workflow_combo.currentData())
        self._estimate_label.setVisible(wf is not None)
        if wf is not None:
            self._estimate_label.setText(
                f"Typical time: {estimate_label(self._db.recent_durations(wf.name))}"
            )

    def refresh_generate_caption(self):
        """Re-read, shortly, whether Generate would reproduce a past run.

        Deferred rather than answered on the spot: the answer needs every stored
        generation's params, far too much to spend on each keystroke, and every
        cue restarts the one timer. Public because the gallery has the other cue:
        a run of these very settings completing.
        """
        self._caption_timer.start()

    def _apply_generate_caption(self):
        """Say on the button what a press will do, and why, or leave it plain."""
        self._generate_pair.offer_how_many(self._folder_request is None)
        if self._folder_request is not None:
            self._generate_btn.set_caption(self._folder_request.caption())
            self._generate_btn.setToolTip(self._folder_request.tooltip())
            return
        wf = WORKFLOW_REGISTRY.get(self._workflow_combo.currentData())
        config = self.current_config()
        duplicate = (
            wf is not None and self._can_generate()
            and (self._would_remake_what_it_shows()
                 or (config.seed_is_random
                     and self._shown_run_the_form_still_holds() is not None)
                 or would_reproduce_a_completed_run(
                     self._library.now().rows, wf, config.params,
                     seed_is_random=config.seed_is_random,
                 ))
        )
        self._generate_btn.set_caption(
            RANDOM_SEED_CAPTION if duplicate else DEFAULT_CAPTION)
        missing = self._missing_images()
        self._generate_btn.setToolTip(
            _nothing_to_start_from(missing) if missing
            else ALREADY_MAKING_ONE_TIP if self._folder_generating
            else _RANDOM_SEED_TIP if duplicate else "")

    def _on_generate(self):
        """Ask the gallery to generate this config — a re-roll of its settings folder,
        as many times as the dropdown beside the button says."""
        if not self._can_generate():
            return  # no server, no workflow picked yet, or no picture to start from
        key = self._workflow_combo.currentData()
        if key not in WORKFLOW_REGISTRY:
            return
        params = self._param_form.get_values()
        if self._folder_request is not None:
            # A request that asked for nothing would re-run every seed in the
            # folder to re-create the folder, so the press says what it still
            # needs rather than filling the queue with copies.
            if self._folder_request.is_unchanged(self.current_config()):
                self._generate_btn.flash_guard(_REQUEST_GUARD)
                return
            self.changes_requested.emit(self._folder_request.folder_key, key, params)
            return
        if self._would_remake_what_it_shows():
            self.use_random_seed()
        self.generate_requested.emit(key, self._batch_of(self._how_many.how_many()))
        self._param_form.roll_random_seeds()

    def _batch_of(self, how_many: int) -> list[dict]:
        batch = [self._param_form.get_values()]
        while len(batch) < how_many:
            if self._param_form.random_seed_keys():
                self._param_form.roll_random_seeds()
            else:
                self.use_random_seed()
            batch.append(self._param_form.get_values())
        return batch

    def set_recipe_source(self, category: str, video_prompt_id: str | None) -> None:
        """Remember that these settings came out of Combine — the act off its
        dropdown, and the video whose recipe they are — and link to that video
        and the picture under the form, as the generation they make will.

        Set after the settings are in (:meth:`prefill` re-picks the workflow,
        which clears this), so what the tab launches carries the mark whether it
        is run as opened or edited first.
        """
        self._recipe_source = (category or "", video_prompt_id or None)
        self._recipe_row = self._db.get_generation(video_prompt_id) if video_prompt_id else None
        self._related.show_row(self._the_row_generate_would_make(), self._image_rows())

    def _the_row_generate_would_make(self) -> dict:
        return {"workflow_name": self._workflow_combo.currentData(),
                "params_json": json.dumps(self._param_form.get_values()),
                "recipe_video_id": self._recipe_source[1]}

    def recipe_source(self) -> tuple[str, str | None]:
        """``(category, video_prompt_id)`` for a tab Combine opened, else
        ``("", None)`` — what a launch from here stamps on its row."""
        return self._recipe_source

    def _recipe_prompts_differ(self) -> bool:
        workflow = WORKFLOW_REGISTRY.get(self._workflow_combo.currentData())
        return (self._recipe_row is not None and workflow is not None
                and self._param_form is not None
                and prompts_differ_from(self._param_form.get_values(),
                                        self._recipe_row, workflow))

    def _forget_recipe_source(self) -> None:
        self._recipe_source = ("", None)
        self._recipe_row = None

    def _mark_recipe_prompt_edits(self) -> None:
        if self._live_source is None:
            self._preview.mark_recipe_prompt_edited(self._recipe_prompts_differ())

    def show_combination(self, combination: Combination) -> None:
        """Put the combination this tab was opened with in the preview: the frame,
        a plus, and the gray clip whose settings came with it. Nothing has been
        made from the pair yet, so there is no result for the pane to show."""
        if self._live_source is None:
            combination = combination._replace(
                recipe_prompt_edited=self._recipe_prompts_differ())
        self._preview.show_combination(combination)
        self._reflow_for_the_media()

    def launched_runs(self) -> list[str]:
        """The runs this tab's Generate started, oldest first.

        Each named by the prompt id it *began* under, so a chained i2v stays one
        run to this tab, and a tab can hold several. Empty once the tab has been
        pointed at someone else's generation.
        """
        return list(self._launched_runs)

    def note_launched(self, origin: str):
        """Claim a run this tab's Generate just started, at the back of its own."""
        self._launched_runs.append(origin)

    def forget_launched(self, origins=None):
        """Let go of runs this tab claimed — all of them, or the named ones (those
        that have finished, failed or been cancelled)."""
        if origins is None:
            self._launched_runs = []
        else:
            self._launched_runs = [r for r in self._launched_runs if r not in origins]

    def set_generating(self, generating: bool, *, auto_generating: bool = False):
        """Reflect whether a run of this config's folder is in flight.

        All it moves is the discard button. ``auto_generating`` says the run's
        folder is auto-looping, which reads that button as "Next seed" rather than
        "Cancel" (see :func:`inflight.discard_run_text`) — re-labeled ahead of the
        idempotence guard below, because the Auto toggle flips mid-run without the
        generating state ever changing.
        """
        self._cancel_btn.setText(discard_run_text(auto_generating))
        self._cancel_btn.setToolTip(discard_run_tooltip(auto_generating))
        if generating == self._generating:
            return
        self._generating = generating
        self._cancel_btn.setVisible(generating)

    def use_random_seed(self):
        """Switch this config's seed(s) to Random.

        Called by the gallery when a press drew a fresh seed rather than reproduce a
        past run: the form then shows what the next press will do too, and the choice
        outlives a cancelled first attempt instead of snapping back to the pinned
        seed that was already generated.
        """
        if self._param_form is not None:
            with self._loading():  # the gallery ticked this, not the user
                self._param_form.set_seed_random(True)

    def _set_displayed_row(self, row: dict | None) -> None:
        self._displayed_row = row
        if self._param_form is not None:
            self._param_form.show_item(merge_denormalized(row) if row is not None else {},
                                       (row or {}).get("thumbnail_path"))

    def _seed_history(self, key: str) -> list[SeedUse]:
        return seed_history(self._db.seed_history_rows(), key, self._db.list_seed_uses())

    def _record_drawn_seed(self, key: str, seed: int) -> None:
        width, height = self._param_form.output_size() or (None, None)
        self._db.record_seed_use(kind=SeedUseKind.DRAWN, seed_key=key, seed=seed,
                                 width=width, height=height)

    def _image_rows(self):
        return self._library.now().image_rows

    def workflow_and_signature(self, image_index: dict | None = None,
                               ) -> tuple[str, str] | None:
        """The two parts the gallery builds this config's folder key out of.

        The signature is normalized against the workflow's defaults (see
        ``canonical_settings``), so it matches the folder this tab's outputs land
        in and groups reruns that differ only by per-instance keys.
        ``None`` when no workflow is selected.
        """
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
        if wf is None or self._param_form is None:
            return None
        params_json = json.dumps(self._param_form.get_values())
        if image_index is None:
            image_index = self._library.now().image_config_index
        shown = self._shown_run_the_form_still_holds(params_json, image_index) or {}
        return key, settings_signature(key, params_json, image_index,
                                       workflow_version=shown.get("workflow_version"))

    def _shown_run_the_form_still_holds(self, params_json: str | None = None,
                                       image_index: dict | None = None) -> dict | None:
        """The saved generation on display while the form still holds its
        settings, else ``None`` — the seeds left out of the question."""
        row = self._displayed_row
        workflow_name = self._workflow_combo.currentData()
        if row is None or self._param_form is None or not workflow_name:
            return None
        if (row.get("workflow_name") or "") != workflow_name:
            return None
        if params_json is None:
            params_json = json.dumps(self._param_form.get_values())
        if image_index is None:
            image_index = self._library.now().image_config_index
        holds_it = (settings_signature(workflow_name, params_json, image_index)
                    == settings_signature(workflow_name, row.get("params_json"), image_index))
        return row if holds_it else None

    def settings_folder_key(self) -> str | None:
        """The gallery folder this tab's settings have been generating into,
        by the key the tree files it under -- the same key the tab is *named* off
        (:meth:`title`).

        ``None`` when there is no such folder: no workflow picked, or nothing
        generated with these settings yet, and a folder with nothing in it is not
        in the tree to go to.
        """
        key = self.workflow_and_signature()
        if key is None or self._recent_matching_row() is None:
            return None
        return config_folder_key(*key)

    def refresh_media_layout(self) -> None:
        """Re-ask what shape the picture is and lay out for it.

        Called when this tab comes to the front as well as when its media
        changes: the shape belongs to the tab, so switching to one holding a
        landscape picture has to stand the panes back up even though nothing in
        THIS tab resized.  Left to the resize signal alone the old arrangement
        stayed until something else nudged the splitter.
        """
        self._reflow_for_the_media()

    def become_hosted(self, session) -> None:
        self._fun_time = session
        self._reflow_for_the_media()

    def become_standalone(self) -> None:
        self._fun_time = None
        self._stand_the_media(beside=False)

    def _reflow_for_the_media(self) -> None:
        """Stand the picture beside the settings when it is a PORTRAIT one.

        Only hosted by Fun Time, where this tab lives in the Random Favs Browser's
        upright rect and a stacked portrait picture pushes every prompt field off
        the foot. Landscape media stays stacked: beside a form it gets a column too
        narrow to show it, and the form loses the width its prompt fields need.
        """
        if self._fun_time is None:
            return  # standalone the pane is wide; stacking is right at any shape
        self._stand_the_media(beside=self._media_is_portrait())

    def _stand_the_media(self, *, beside: bool) -> None:
        if beside == self._media_side_by_side:
            return
        self._media_side_by_side = beside
        sizes = self._media_split.sizes()
        if beside:
            self._media_split.setOrientation(Qt.Orientation.Horizontal)
            self._media_split.insertWidget(0, self._settings_pane)  # settings lead
        else:
            self._media_split.setOrientation(Qt.Orientation.Vertical)
            self._media_split.insertWidget(0, self._preview_pane)
        self._media_split.setStretchFactor(0, 3 if beside else 0)
        self._media_split.setStretchFactor(1, 4 if beside else 0)
        if sum(sizes) > 0:
            self._media_split.setSizes(sorted(sizes, reverse=True))

    def _media_is_portrait(self) -> bool:
        size = self._preview.media_size()
        return bool(size) and orientation_of_size(*size) == PORTRAIT

    def show_recent_preview(self):
        """Put up the newest saved generation matching this tab's settings, through
        the same tail a clicked one goes through (:meth:`_display_result`), else the
        'select a generation' placeholder. The form is all an autoshow leaves alone:
        these settings chose the row, so seeding them from it would overwrite what
        the user typed."""
        if self._autoshow_held:
            return
        row = self._recent_matching_row()
        if row is not None and resolve_preview(row, COMFYUI_OUTPUT_DIR) is not None:
            self._display_result(row, self._image_rows())
            return
        self._preview.clear()  # nothing generated with these settings yet
        self._set_displayed_row(None)
        self._hide_footer()
        self._arm_preview_actions()
        self._note_displayed_config()
        self._emit_title()  # the tab is named after what it shows

    def _recent_matching_row(self) -> dict | None:
        """The newest saved generation in this tab's settings folder, or None."""
        library = self._library.now()
        matching = library.in_settings(self.workflow_and_signature(library.image_config_index))
        return matching[0] if matching else None

    def current_config(self) -> ConfigSnapshot:
        if self._param_form is None:
            return ConfigSnapshot(self._workflow_combo.currentData(), {}, False)
        return ConfigSnapshot(
            self._workflow_combo.currentData(),
            self._param_form.get_values(),
            self._param_form.seed_is_random(),
        )

    def is_blank(self) -> bool:
        """Has this tab been used for anything yet?

        True only for a panel still on the picker's placeholder with nothing on
        display — the pane's resting tab. Such a tab is what a clicked generation
        loads into rather than opening beside; a tab whose workflow has been
        picked holds a choice someone made, so it is left alone.
        """
        return self._workflow_combo.currentData() is None and self._displayed_row is None

    def title(self) -> str:
        """This tab's name: the item on display, else the gallery folder this
        config would generate into, else what a tab with no workflow yet is.

        Named after what it is showing rather than after its settings, so the row
        of tabs reads as the things you have open.
        """
        if self._folder_request is not None:
            return self._folder_request.title()
        name = self._names.of((self._displayed_row or {}).get("prompt_id"))
        if not name:
            key = self.workflow_and_signature()
            if key is not None:
                name = config_folder_name(*key, self._db.folder_meta_map())
        return name or "New generation"

    def tab_icon(self) -> QIcon:
        """The mark beside this tab's name: the displayed item's own thumbnail,
        else the plain image/video mark for what this config makes.

        A null icon for a tab with no workflow picked — nothing is known yet, and
        a mark guessing at one would be the tab's most confident claim.
        """
        row = self._displayed_row
        thumb = (row or {}).get("thumbnail_path")
        if thumb and Path(thumb).exists():
            return QIcon(QPixmap(str(thumb)))
        media = (media_type_of_row(row) if row is not None
                 else workflow_output_type(self._workflow_combo.currentData()))
        return icons.media_type_icon(media) if media else QIcon()

    def prefill(self, workflow_name: str, params: dict):
        # Seeding the form with one configuration is the end of any folder-wide
        # rewrite this tab was holding: the prompts it lands are a recipe to run,
        # not a change to a folder's. (:meth:`open_folder_request` prefills first and
        # arms the rewrite afterwards, so it is not undoing itself.) It is the end
        # of following a run, too: the next frame would land over the picture
        # these settings just put up. (A tab pointed at a run is re-seeded first
        # and told to follow afterwards, so that is not undoing itself either.)
        #
        # The whole of it under _loading: this writes the workflow picker and
        # every field, exactly as a person would, and a tab filled by an open is
        # not a tab someone has worked in.
        with self._loading():
            self._fresh_form = False
            self._end_folder_request()
            self._forget_watch()
            # Switch to the matching workflow. A registered workflow the picker
            # normally hides (machinery, selectable False) is added on demand, so
            # reusing such a row still lands on the right form instead of silently
            # applying its params to whatever workflow was already selected.
            index = self._workflow_combo.findData(workflow_name)
            if index < 0 and workflow_name in WORKFLOW_REGISTRY:
                self._workflow_combo.addItem(
                    WORKFLOW_REGISTRY[workflow_name].display_name, workflow_name
                )
                index = self._workflow_combo.findData(workflow_name)
            if index >= 0:
                self._workflow_combo.setCurrentIndex(index)
            if self._param_form:
                self._param_form.set_values(params)
            # Now that the settings match a real folder, show its newest result (the
            # workflow may not have changed above, so this doesn't ride on that signal).
            self.show_recent_preview()

    def restore_config(self, snapshot: ConfigSnapshot):
        """Reapply a snapshot captured by :meth:`current_config`.

        Like :meth:`prefill`, but also restores the seed's Random state so a tab
        comes back the way it was left instead of pinned to the stale seed that was
        in its field at save time.
        """
        with self._loading():
            self.prefill(snapshot.workflow_name, snapshot.params)
            if self._param_form:
                self._param_form.set_seed_random(snapshot.seed_is_random)
                self._param_form.put_seeds(snapshot.params, is_random=snapshot.seed_is_random)

    def saved_layout(self) -> dict:
        if self._fun_time is None:
            self._picture_border = self._media_split.dragged_sizes() or self._picture_border
        return {"folds": self._param_form.folds() if self._param_form else {},
                "enhancement_levels_folded": self._versions.is_collapsed(),
                "details_folded": self._metadata_block.is_folded(),
                "source_folded": self._related.is_source_folded(),
                "picture_border": self._picture_border}

    def restore_layout(self, saved) -> None:
        if not isinstance(saved, dict):
            return
        folds = saved.get("folds")
        if self._param_form and isinstance(folds, dict):
            self._param_form.set_folds(folds)
        if isinstance(saved.get("enhancement_levels_folded"), bool):
            self._versions.set_collapsed(saved["enhancement_levels_folded"])
        if isinstance(saved.get("details_folded"), bool):
            self._metadata_block.set_folded(saved["details_folded"])
        if isinstance(saved.get("source_folded"), bool):
            self._related.set_source_folded(saved["source_folded"])
        self._picture_border = saved.get("picture_border")
        if self._fun_time is None:
            self._media_split.take_dragged_sizes(self._picture_border)

    # --- rewriting a whole folder's prompt ------------------------------------

    def open_folder_request(self, folder_key: str, label: str, workflow_name: str,
                      params: dict, pictures: list) -> None:
        """Open this tab as a rewrite of one folder's prompt.

        The folder's own settings fill the form, its prompts are marked against
        what they say now (:mod:`origenerator.gui.tracked_prompt`), and its images
        fill the preview, tiled. Nothing about it is one generation, so the tab
        shows no file, no footer and no "modified" notice. ``pictures`` carries one
        entry per run the press will make, whether or not there is a thumbnail for
        it, so the count in the hover is of images rather than of readable files.
        """
        self.prefill(workflow_name, params)  # ends any rewrite already here
        self._folder_request = FolderRequest(
            folder_key=folder_key, label=label, count=len(pictures),
            # What the tab opened on, so a press can tell a rewrite from a
            # re-run of the folder it was rewriting.
            opened_on=self.current_config(),
        )
        self._hide_footer()
        self._set_displayed_row(None)  # a folder, not a generation on display
        self._displayed_config = None  # ...so no settings for a notice to deviate from
        self._preview.show_folder(pictures)
        self._reflow_for_the_media()
        if self._param_form is not None:
            self._param_form.track_prompt_rewrites()
        self._apply_generate_caption()
        self._emit_title()

    def _end_folder_request(self) -> None:
        """Stop this tab being a folder rewrite, leaving an ordinary config.

        The prompt fields go back to plain inputs holding the prompts they show —
        a marked-up field left over would go on measuring edits against a
        folder the tab is no longer about, and would keep its undo switched off.
        """
        if self._folder_request is None:
            return
        self._folder_request = None
        if self._param_form is not None:
            self._param_form.clear_prompt_rewrites()
        self._apply_generate_caption()

    # --- displaying a saved generation (the browsed selection) ----------------

    def show_saved_generation(self, row: dict, image_rows: list[dict], request=None):
        """Display a browsed generation in this tab: its settings in the
        editable form, its output in the preview, the info for its media type, and,
        when ``request`` says a spoken request made it, a link back to the item it
        was asked about.

        The form is seeded first, with the newest-result autoshow held back while
        it is, so nothing but the selection is ever put up. A workflow the app
        can't rebuild leaves the form as it was. Whatever the tab was about before
        it lets go of (:meth:`_point_elsewhere`).
        """
        self._point_elsewhere(row)
        self._display_result(row, image_rows, request)

    def show_running_generation(self, row: dict):
        """Point this tab at a generation still being made: its settings
        fill the form the way a saved generation's would, and nothing else -- there
        is no file to show until the run lands, which the preview follows from here
        (:meth:`watch_folder`).

        What a click on a folder's live tile lands in a tab: the tab is *for* this
        run now, and is named after the folder the run will land in.
        """
        self._point_elsewhere(row)
        self._hide_footer()
        self._preview.clear()          # whatever was up is not this run's
        self._set_displayed_row(None)  # a running generation isn't a saved one
        self._displayed_config = None  # ...so no settings for a notice to deviate from
        self._emit_title()

    def _point_elsewhere(self, row: dict):
        """Aim this tab at ``row``'s settings, letting go of what it was about.

        Its claim on the runs it launched and the run it was watching ends, or the
        bar would sit mid-run over an unrelated picture, its Cancel would stop
        something off screen, and the next frame would paint over what was just
        put here. The same goes for a combination Combine opened here. Both
        callers put up a picture of their own straight after, so the one the
        seeded settings would show is held back rather than loaded for nothing.
        """
        self.forget_launched()
        self._forget_watch()
        self._forget_recipe_source()
        self._end_folder_request()  # a workflow this app can't rebuild never reaches prefill
        workflow_name = row.get("workflow_name", "")
        if workflow_name in WORKFLOW_REGISTRY:
            self._autoshow_held = True
            try:
                self.prefill(workflow_name, merge_denormalized(row))
            finally:
                self._autoshow_held = False

    def show_completed_result(self, row: dict, image_rows: list[dict]):
        """Show a generation this tab's own Generate just produced: the saved
        output in place of the live preview, its footer revealed, and the form left
        as the user left it but for a seed still on Random, which takes this
        result's seed.

        Re-seeding the form here would wipe edits made while the run was in flight.
        A tab holding a folder rewrite takes none of it: its batch lands a picture
        at a time, and each would swap the wall of pictures for the last to finish.
        """
        if self._folder_request is not None:
            return
        self._display_result(row, image_rows, made_with=merge_denormalized(row))

    def refresh_displayed(self, row: dict, image_rows: list[dict]):
        """``row`` has changed under this tab: re-show it if it is what the tab
        is displaying, else leave the tab alone.

        A tab holds the row it was given rather than a live view of the database,
        so an enhancement folding in a new level would otherwise show only the next
        time the tab was opened. The form is left exactly as the user has it.
        """
        shown = self._displayed_row
        if shown is None or shown.get("prompt_id") != row.get("prompt_id"):
            return
        self._display_result(row, image_rows)

    def show_finished_media(self, row: dict):
        """Put a finished run's saved output in the preview alone -- no footer,
        no form, and not as this tab's displayed generation.

        What the tab *mirroring* a run shows when it lands. Taking it on would
        leave the pane's blank resting tab holding a generation, and the next click
        would open a tab beside it instead of filling it; the tab that *did* launch
        the run gets the whole end state through :meth:`show_completed_result`.
        """
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            return  # nothing to look at; leave the frames rather than blank the pane
        self._live_note = None
        self._preview.show_media(*preview, row["prompt_id"])
        self._arm_preview_actions(row["prompt_id"])  # …and wears its corners

    # --- following a run in flight ------------------------------------------

    def watched_key(self) -> str | None:
        """The settings folder whose live run this tab's preview follows, or
        ``None`` while the preview is the tab's own picture.

        A tab follows a folder rather than one run, because a folder's runs come
        one after another and watching one is watching the next. Set by this tab's
        Generate and by a click on the folder's live tile; ended by pointing the
        tab at a saved generation, or by :meth:`stop_watching`.
        """
        return self._watched_key

    def watch_folder(self, key: str, frame: bytes | None, note: str | None = None,
                     made_from: Combination | None = None):
        """Follow the run leading folder ``key``: its latest ``frame`` now, each
        later one as it streams (:meth:`show_live_frame`), and the picture it
        lands as.

        With no frame yet the pane stands ``made_from`` — the picture and clip the
        run was built on — or, for a run made from nothing, says it is waiting:
        ``note`` where the caller knows what for, marked live so a double-click
        opens the run fullscreen before its first frame.
        """
        self._watched_key = key
        self._live_note = None
        if frame:
            self.show_live_frame(frame)
        elif made_from is not None and (made_from.picture or made_from.recipe):
            self.show_live_source(made_from)
        else:
            self.show_live_wait(note)

    def show_live_source(self, made_from: Combination):
        """Stand what the followed run is being made from, in place of a frame it
        has not streamed yet. Repainted only when the pair changes, since the
        poll re-reads the watch every tick and the clip beside it is looping."""
        if made_from == self._live_source:
            return
        self._live_source = made_from
        self.show_combination(made_from)

    def show_live_frame(self, frame: bytes):
        """The run this tab follows streamed a frame: put it up."""
        self._live_note = None
        self._live_source = None
        self._preview.show_frame(frame)

    def show_live_wait(self, note: str | None):
        """Say what the followed run is waiting on, in place of a frame it has
        not streamed yet. Repainted only when the text changes, since the poll
        re-reads the wait every tick."""
        text = note or _WAITING_NOTE
        if text == self._live_note:
            return
        self._live_note = text
        self._live_source = None
        self._preview.show_message(text, live=True)

    def is_awaiting_frame(self) -> bool:
        """Whether the preview is standing on a *worded* wait for the followed
        run's first frame — the one state a fresher wait text should replace.
        A pane standing the pair the run is made from is not waiting in words,
        and has nothing for a changed count to rewrite."""
        return self._watched_key is not None and self._live_note is not None

    def stop_watching(self):
        """Let go of the folder this tab was following — its run ended with
        nothing to show — and put the tab's own picture back: the generation on
        display, else the newest result of the settings on the form, else the
        idle placeholder."""
        if self._watched_key is None:
            return
        self._forget_watch()
        if self._displayed_row is not None:
            self._restore_preview()
        elif self._workflow_combo.currentData() is not None:
            self.show_recent_preview()
        else:
            self._preview.clear()

    def _forget_watch(self):
        self._watched_key = None
        self._live_note = None
        self._live_source = None

    def _display_result(self, row: dict, image_rows: list[dict], request=None,
                        made_with: dict | None = None):
        """Point the preview and footer at ``row`` — the shared tail of showing a
        generation, whether freshly browsed or just completed. The form is left
        untouched; :meth:`show_saved_generation` seeds it first, before this runs."""
        arriving = (self._displayed_row is None
                    or self._displayed_row.get("prompt_id") != row.get("prompt_id"))
        self._set_displayed_row(row)
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is not None:
            self._preview.show_media(*preview, row["prompt_id"])  # after any prefill, so it wins over autoshow
        else:
            self._preview.clear()
        self._show_footer(row, image_rows, preview, request)
        self._arm_preview_actions()
        if arriving:
            self._note_displayed_config(made_with)
        else:
            # The same generation, changed under the tab: an enhancement folded
            # in, a version deleted. Nothing about the settings moved, so the mark
            # edits are measured against stays where it is — re-taking it read the
            # user's edits as the new baseline, and the "not yet generated with
            # modifications" plate vanished the moment an enhancement landed, from
            # over the very frames it had been standing over. Only re-asserted,
            # because the picture put up above took the notice off with the old one.
            self.refresh_modified_notice()
        self._emit_title()  # the tab is named after what it shows
        self.displayed_changed.emit()  # the view reconciles OSR2 driving off this

    def _arm_preview_actions(self, prompt_id: str | None = None):
        """Point the preview's corners and right-click menu at what is on it.

        Re-run after every change to the picture: showing media is what takes them
        away, everything they report moves under the picture too, and an autoshow
        arms them as readily as an explicit selection. ``prompt_id`` names the
        generation when it is NOT the row this tab holds — a followed run's picture
        goes up without the tab taking it on.
        """
        if prompt_id is None and self._displayed_row is not None:
            prompt_id = self._displayed_row["prompt_id"]
        row = self._db.get_generation(prompt_id) if prompt_id is not None else None
        if row is None:
            self._preview.set_actions(None)
            return
        self._preview.set_actions(
            row["prompt_id"], favorite=bool(row.get("starred")),
            enhance=enhance_state(row, self._enhance_settings),
        )

    def reconcile_preview(self, live_ids):
        shown = self._displayed_row
        if shown is not None and shown.get("prompt_id") not in live_ids:
            self._preview.clear()
        self._reread_corners()

    def _reread_corners(self):
        armed = self._preview.actions_id()
        if armed is not None:
            self._arm_preview_actions(armed)

    def _note_displayed_config(self, made_with: dict | None = None):
        """Take the settings a generation arriving in this tab was made with
        as the mark to measure edits against, and clear any notice left from the
        last one: the form's, or ``made_with`` for a result of this tab's own
        Generate, since the form may have been edited while that run was made.
        What happens to the generation already on display leaves the mark alone
        (see :meth:`_display_result`).
        """
        self._displayed_config = (
            self._item_config(made_with) if self._displayed_row is not None else None
        )
        self.refresh_modified_notice()

    def _item_config(self, made_with: dict | None = None) -> ConfigSnapshot:
        current = self.current_config()
        if self._param_form is None:
            return current
        params = {key: (made_with or {}).get(key, value)
                  for key, value in current.params.items()}
        return ConfigSnapshot(current.workflow_name,
                              {**params, **self._param_form.item_seeds()},
                              seed_is_random=False)

    def refresh_modified_notice(self):
        """Mark the preview when the form no longer describes the picture on it.

        Putting the settings back takes the notice away again. Public because the
        version list re-shows a level of the same row from outside the form, which
        clears the notice, so whoever did that re-asserts it.
        """
        modified = (self._displayed_config is not None
                    and not self._would_remake_what_it_shows())
        self._preview.set_notice(_MODIFIED_NOTICE if modified else None)

    def _would_remake_what_it_shows(self) -> bool:
        return (self._displayed_config is not None
                and configs_match(self._displayed_config, self.current_config()))

    def _hide_footer(self):
        """Hide every info/action element that belongs only to a saved generation —
        the state of a tab with none on display: blank, following a run still
        being made, or holding a whole folder's rewrite."""
        self._metadata_block.hide()
        self._picture_state.clear()
        self._related.clear()
        self._versions.hide()
        self._pending_enhancement = None  # nothing on display to be enhancing
        self._update_lane_button(None)

    def _show_footer(self, row: dict, image_rows: list[dict], preview, request=None):
        """Reveal the info and actions for the generation on display: the
        read-only metadata block for every selection, the source tile + the lane
        button for a video, and the animations strip for an image. ``preview`` is the
        resolved ``(path, media_type)`` (or ``None``), so the lane button keys off the
        same lookup.

        ``request`` is the spoken request that made this row, when one did.
        """
        self.reread_folder_buttons()
        # An image's files are all listed as its versions, so its block is at
        # most the workflow version — it shows only when it has content rather
        # than opening a bare gap above the form.
        self._metadata_block.setVisible(
            self._metadata_block.show_row(row, self._upscale_of(row)))
        self._picture_state.show_row(row)
        self._related.show_row(row, image_rows, request)
        self._refresh_versions()
        self._show_request_diff(request)
        self._update_lane_button(preview)

    def displayed_row(self) -> dict | None:
        """The saved generation this tab is showing, or ``None``.

        Whatever is in the preview — a browsed selection or an idle autoshow —
        which is what the gallery matches its live enhance jobs against.
        """
        return self._displayed_row

    def set_pending_enhancement(self, pending: RunningEnhancement | None):
        """Reflect an enhancement being generated for the image on display.

        ``pending`` is a :class:`RunningEnhancement` while one is running, ``None``
        otherwise. A frame updates the level's row in place and goes up to the
        preview; only a run starting or ending rebuilds the list. These frames keep
        whatever the pane says about the picture rather than clearing it, which
        every other live frame does: an enhancement is the coming state of that
        very image, and clearing it left the mark and the frames trading places
        several times a second while the form was typed in.
        """
        if pending == self._pending_enhancement:
            return
        was_running = self._pending_enhancement is not None
        self._pending_enhancement = pending
        if pending is not None:
            frame = pending.frame
            if frame:
                self._preview.show_frame(frame, enhancing=True)
        elif was_running:
            self._restore_preview()
        if self._versions.update_pending(pending):
            return
        self._refresh_versions()

    def _restore_preview(self):
        """Put the displayed generation's own output back in the preview, after
        a live enhancement of it has finished streaming over the top."""
        row = self._displayed_row
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR) if row else None
        if preview is None:
            self._preview.clear()
            return
        self._preview.show_media(*preview, row["prompt_id"])
        self._arm_preview_actions()
        self.refresh_modified_notice()  # the picture is back; so is anything said about it

    def set_fullscreen_factory(self, make):
        """Wire what a double-click on this tab's preview opens — a slideshow of
        the folder under it, which only the gallery can assemble. Passed straight
        through to the preview (see
        :meth:`~origenerator.gui.preview_widget.PreviewWidget.set_fullscreen_factory`).
        """
        self._preview.set_fullscreen_factory(make)

    def set_enhance_settings(self, settings: EnhanceSettings):
        """The app-wide enhance settings the ``+ Enhance`` card would run at.

        Pushed in by the gallery whenever the Enhance panel changes, so the card
        names the current settings and knows whether they would only duplicate a
        version this image already holds.
        """
        if settings == self._enhance_settings:
            return
        self._enhance_settings = settings
        self._refresh_versions()
        self._reread_corners()

    def _on_enhance_requested(self):
        if self._displayed_row is not None:
            self.enhance_requested.emit(self._displayed_row["prompt_id"])

    def _on_go_to_folder(self):
        if self._displayed_row is not None:
            self.go_to_folder_requested.emit(self._displayed_row["prompt_id"])

    def set_folder_check(self, can_go) -> None:
        self._can_go_to_folder = can_go

    def reread_folder_buttons(self) -> None:
        """Asked again whenever the gallery moves: in the picture's own folder it
        would do nothing, and is not there."""
        row, can_go = self._displayed_row, self._can_go_to_folder
        self._go_to_folder.setVisible(
            row is not None and can_go is not None and can_go(row))
        if row is not None:
            self._metadata_block.setVisible(self._metadata_block.has_content())

    def _on_levels_delete_requested(self, positions: list):
        """Relay a version-list delete by filename, not by position.

        The list is rebuilt from the row on every refresh, so a position is only
        good for as long as the widget that produced it — the gallery does the
        deleting and it must be told *which files*, resolved here while the list
        and the row still agree."""
        row = self._displayed_row
        if row is None:
            return
        levels = self._listed_levels
        names = [levels[p].file.get("filename") for p in positions
                 if 0 <= p < len(levels)]
        if names:
            self.levels_delete_requested.emit(row["prompt_id"], names)

    def _refresh_versions(self):
        """Rebuild the version list for whatever this tab is displaying.

        The preview is already on ``output_files[0]`` — the most-enhanced
        version — so the list leads with that level and offers the rest below
        it, under the ``+ Enhance`` row. A video has no row to press — the
        enhancer takes images — and lists versions only once Evolver has
        upscaled it, none of them binned from here.
        """
        row = self._displayed_row
        if row is None:
            self._listed_levels = []
            self._versions.show_levels([])
            return
        if media_type_of_row(row) != MediaType.IMAGE:
            self._listed_levels = displayed_levels(row, self._upscale_of(row))
            # A video file is no picture, so both versions wear its thumbnail.
            self._versions.show_levels(
                [(level, row.get("thumbnail_path")) for level in self._listed_levels],
                created_fallback=str(row.get("created_at", "")),
                held_days=row.get("days_in_trash"), deletable=False,
            )
            return
        self._listed_levels = displayed_levels(row)
        # Each drawn from its own file, so a level shows what it actually looks
        # like rather than the row's one shared thumbnail.
        self._versions.show_levels(
            [(level, self._level_path(level)) for level in self._listed_levels],
            self._pending_enhancement, self._add_card_for(row),
            str(row.get("created_at", "")), row.get("days_in_trash"),
        )

    def _upscale_of(self, row: dict) -> Path | None:
        """The upscale Evolver has made of the video on display, if it has."""
        if media_type_of_row(row) != MediaType.VIDEO:
            return None
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            return None
        return EvolverUpscales.scan(EVOLVER_UPSCALED_DIR, EVOLVER_SOURCE).upscale_of(preview[0])

    def _add_card_for(self, row: dict) -> EnhanceOffer:
        """What the ``+ Enhance`` row on ``row`` would run, and what it repeats."""
        params = enhance_params_for(row, self._enhance_settings)
        return EnhanceOffer(describe_enhance_params(params or {}),
                            level_matching_settings(row, self._enhance_settings))

    @staticmethod
    def _level_path(level) -> Path:
        """Where one version's file lives — under ComfyUI's output folder, or in
        the trash once the generation has been deleted."""
        return output_file_path(level.file, COMFYUI_OUTPUT_DIR)

    def _show_level(self, position: int):
        """Put one of the displayed generation's versions in the preview.

        Only the picture changes: the row on display, its form, its metadata and
        the OSR2 drive all still belong to the generation — the levels are
        versions of one image or video, not separate generations, so switching
        between them is a look rather than a navigation.
        """
        if self._displayed_row is None or not 0 <= position < len(self._listed_levels):
            return
        path = self._level_path(self._listed_levels[position])
        if path.exists():
            self._preview.show_media(path, media_type_of_row(self._displayed_row),
                                     self._displayed_row["prompt_id"])
            self._arm_preview_actions()  # still the same generation, still actionable
            self.refresh_modified_notice()  # a version of the same generation, same notice

    def _show_request_diff(self, request):
        """Mark the prompt fields with what a spoken request changed — struck
        through where words went, lit where they arrived.

        In the fields themselves, because that is where the prompt is: a change
        described anywhere else has to be carried back to the words it is about.
        Nothing marked when this row wasn't asked for, so the fields clear as
        the tab moves on to an ordinary generation.
        """
        if self._param_form is None:
            return
        self._param_form.clear_prompt_diffs()
        if not request:
            return
        for key, before, after in (
            ("positive_prompt", request.get("old_positive"), request.get("new_positive")),
            ("negative_prompt", request.get("old_negative"), request.get("new_negative")),
        ):
            self._param_form.show_prompt_diff(key, before or "", after or "")

    def _video_rows(self) -> list[dict]:
        return self._library.now().video_rows

    # --- the export lanes: hand a displayed clip to a sibling app -----------

    def _update_lane_button(self, preview):
        """Offer the displayed generation to the one app :func:`lane_for` picks.

        Shown only for a video with a file on disk — every lane carries clips,
        and Evolver is a video pipeline — so an image or a missing file hides it.
        One already sent says so beside Unsend instead, read from the row rather
        than from the button's own state so it survives a restart.
        ``preview`` is the resolved ``(path, media_type)``, or ``None``.
        """
        is_video = preview is not None and preview[1] == MediaType.VIDEO
        row = self._displayed_row or {}
        lane = self._offered_lane = lane_for(row) if is_video else None
        sent = is_video and bool(row.get(lane.flag))
        self._lane_button.setVisible(is_video and not sent)
        self._sent_row.setVisible(sent)
        if not is_video:
            return
        self._lane_button.setText(lane.send_caption)
        self._lane_button.setToolTip(
            lane.withdrawn_tooltip if row.get(lane.unsent_flag) else lane.tooltip)
        self._sent_note.setText(lane.sent_caption)
        self._unsend_button.setToolTip(lane.unsend_tooltip)

    def _on_send(self, lane):
        """Copy the displayed video into *lane*'s inbox folder and remember it.

        Re-checks the persisted flag rather than the button's disabled state, so
        the handoff cannot be repeated. The copy lands in another app's inbox
        with no other visible result here, so a failure that reached only the log
        would look exactly like a success — hence the dialog.
        """
        if not self._displayed_row or self._displayed_row.get(lane.flag):
            return
        path = self._displayed_video_path()
        if path is None:
            return
        try:
            lane.send(path, self._displayed_row["prompt_id"], db=self._db,
                      inbox=self._inbox, output_dir=COMFYUI_OUTPUT_DIR)
        except Exception as e:
            logger.exception("Failed to send %s to %s", path, lane.name)
            QMessageBox.warning(self._preview, lane.failure_title,
                                lane.failure_body(e))
            return
        self._redraw_lane_button()

    def _on_unsend(self, lane):
        """Take the send back: the app it went to deletes every copy it holds.

        Nothing is deleted from here. The clip has been sorted, upscaled and
        re-filed since it was handed over, and only the app whose folders those
        are can still find it — so the whole of this is a stamp on the row, which
        that app reads on its next run. The button goes back to offering the
        send, which from here on puts a fresh copy in that app's hands.
        """
        if not self._displayed_row or not self._displayed_row.get(lane.flag):
            return
        lane.unmark(self._db, self._displayed_row["prompt_id"])
        self._redraw_lane_button()

    def _redraw_lane_button(self):
        prompt_id = self._displayed_row["prompt_id"]
        self._set_displayed_row(self._db.get_generation(prompt_id) or self._displayed_row)
        path = self._displayed_video_path()
        self._update_lane_button(None if path is None else (path, MediaType.VIDEO))

    def _displayed_video_path(self) -> Path | None:
        """The on-disk video file backing the displayed generation, or ``None``
        when it isn't a video (or its file is missing). Resolved fresh, so a file
        deleted since selection is caught. Shared by the lane button and OSR2 drive.

        ``_displayed_row`` is whatever the preview is showing — a browsed selection
        or this tab's idle autoshow — so a scripted video on screen arms the drive
        either way."""
        if not self._displayed_row:
            return None
        preview = resolve_preview(self._displayed_row, COMFYUI_OUTPUT_DIR)
        if preview is None or preview[1] != MediaType.VIDEO:
            return None
        return preview[0]

    # --- Drive OSR2: what the (global) driver should stream for this tab -------

    def release_media(self, paths) -> None:
        """Let go of any of ``paths`` this tab is showing — files about to be
        moved or deleted, which Windows will not let go of while a player holds
        them open."""
        self._preview.release_media(paths)

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the shown video, or ``None``.

        The view's single global driver asks the front tab for this whenever driving
        is on and the shown video changes: the on-disk video (the drive identity), the
        media player to follow, and the funscript actions beside it. ``None`` when the
        tab isn't showing a video, or that video has no funscript."""
        return drive_target_for(self._displayed_video_path(), self._preview.player())

    def video_on_screen(self) -> str | None:
        return self._preview.video_on_screen()
