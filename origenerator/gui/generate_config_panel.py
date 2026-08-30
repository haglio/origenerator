import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel,
    QPushButton, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap

from origenerator import evolver_export
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    EnhanceSettings, animated_preview_path,
    build_image_config_index, config_folder_name, describe_enhance_params,
    displayed_levels, enhance_params_for, find_source_image_id, item_label,
    level_matching_settings, media_type_of_row, output_file_path,
    resolve_preview, row_output_files, rows_in_settings, settings_signature,
    videos_from_source_image, workflow_output_type,
)
from origenerator.generation_config import (
    ConfigSnapshot, configs_match, merge_denormalized,
    would_reproduce_a_completed_run,
)
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.enhance_versions import EnhanceVersions
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.generate_button import DEFAULT_CAPTION, GenerateButton
from origenerator.gui import icons
from origenerator.gui.inflight import discard_run_text, discard_run_tooltip
from origenerator.gui.metadata_block import MetadataBlock
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.osr2_driver import drive_target_for
from origenerator.gui.param_form import ParamForm
from origenerator.gui.corner_controls import enhance_state
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.source_image_tile import SourceImageTile
from origenerator.timing import estimate_label
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.config import (
    COMFYUI_OUTPUT_DIR, EVOLVER_INBOX_DIR, EVOLVER_SOURCE, GENAU_SOURCE, THUMB_DIR,
)
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.spacing import BUTTON_GAP, BUTTON_ROW_GAP

logger = logging.getLogger(__name__)

_ANIMATED_STRIP_LIMIT = 8  # most animation previews shown for one image at once
_CAPTION_DELAY_MS = 250    # settle before re-reading whether Generate would duplicate
_RANDOM_SEED_CAPTION = "Generate with Random seed"
_RANDOM_SEED_TIP = (
    "These settings have already been generated with this exact seed, so "
    "Generate draws a fresh one rather than re-creating the same file. "
    "Change a setting to generate something else instead."
)
# Breathing room round the tab's contents, and between the form and the scroll
# bar beside it — enough that nothing reads as jammed into a corner, small
# enough that a narrow pane still spends its width on the fields.
_PANE_MARGIN = 8
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

# What a tab opened on a folder-wide request says on its Generate and above
# its tabs. The count is in the hover rather than on the face: the press does
# submit that many runs at once, which is worth being able to read, but what
# the button asks for is one thing — this folder, said the way it now reads.
_REQUEST_CAPTION = "Request changes"
_REQUEST_TIP = (
    "Run all {count} images in this folder again, each with its own seed and "
    "the prompt as you have rewritten it, landing them together in a new "
    "folder."
)
# Its own wording rather than a plural switched off, which left "Run all 1
# image ... each with its own seed" on a folder holding one.
_REQUEST_TIP_ONE = (
    "Run this folder's one image again with its own seed and the prompt as "
    "you have rewritten it, landing it in a new folder."
)
_REQUEST_GUARD = "Rewrite the prompt first"
_REQUEST_TITLE = "Request {folder}"


class GenerateConfigPanel(QWidget):
    """One generation configuration: pick a workflow and set its params.

    Clicking Generate doesn't run a job here — it emits :attr:`generate_requested`
    for the gallery to launch as a re-roll of this config's settings folder. The
    panel is one column: a fixed preview on top, then one scroll holding the
    File/Created block above the editable form and, at its bottom, the displayed
    generation's related media, then a single button bank
    (Go-to-folder, Send-to-Evolver, Send-to-Genau, Cancel, Generate).
    There's no status line —
    Generate itself doubles as the progress bar, filling as a run advances, and its
    caption says when a press will draw a fresh seed rather than re-create a
    generation these settings have already made. The
    preview is driven from outside: a browsed selection's output, a running
    re-roll's live frames, or this config's newest matching result when idle.

    The info appears only while the tab is displaying a saved generation
    (:meth:`show_saved_generation`): a File/Created block above the form, and at the
    bottom of the scroll the videos an image was animated into, or a clickable
    source-image tile for a video. Send-to-Evolver and Send-to-Genau (a video), and
    the Drive-OSR2 toggle key off the displayed row. A blank
    tab, or one showing a bare autoshow, hides them all.

    What acts on the generation itself does not live in the button bank at all:
    the preview wears the same star / trash / plus corners a gallery thumbnail of
    it does, and right-clicking it raises the same menu — go to its folder,
    bookmark it, enhance it, bin it. A picture is where those belong, and a bank
    under the settings was a strange place to keep a "Go to folder".

    A fresh panel opens with no workflow picked — the picker sits on its
    placeholder, and everything the workflow decides (its typical time, its param
    form, its Generate) waits until one is chosen. That is the pane's resting
    state: a tab is always open, so the pane is never a blank rectangle, and the
    one question it asks first is which workflow to run.
    """

    title_changed = pyqtSignal(str)     # current tab name (its mark moves with it)
    form_edited = pyqtSignal()          # any field changed — every keystroke
    form_replaced = pyqtSignal()        # a new workflow swapped the param form out
    source_activated = pyqtSignal(str)      # the source-image tile was clicked (prompt_id)
    animated_activated = pyqtSignal(str)    # an animation tile was clicked (prompt_id)
    item_action_requested = pyqtSignal(str, str)   # a preview corner: prompt_id, action
    context_menu_requested = pyqtSignal(str, QPoint)  # preview right-clicked: id, global pos
    generate_requested = pyqtSignal(str, dict)  # Generate clicked: (workflow_name, form params)
    # Generate clicked on a folder rewrite: (source folder key, workflow_name, form
    # params). A separate signal because it asks for something else entirely — one
    # run per picture in that folder, each keeping its own seed.
    changes_requested = pyqtSignal(str, str, dict)
    cancel_requested = pyqtSignal()         # Cancel clicked: stop this config's in-flight run
    displayed_changed = pyqtSignal()        # the shown generation changed (drive reconcile cue)
    preview_drag_started = pyqtSignal(str)  # the preview's media began dragging (prompt_id) — combine cue
    preview_drag_ended = pyqtSignal()       # that drag finished (dropped or canceled)
    enhance_requested = pyqtSignal(str)      # the version list's "+ Enhance" was pressed (prompt_id)
    levels_delete_requested = pyqtSignal(str, list)  # bin these versions of this image (prompt_id, filenames)

    def __init__(self, client: ComfyUIClient | None, db: Database, parent=None):
        super().__init__(parent)
        self._client = client                        # None in a read-only gallery: the form shows, but Generate is off
        self._db = db
        self._param_form: ParamForm | None = None
        self._generating = False                       # a run this tab launched is in flight (offers the discard button)
        self._launched_runs: list[str] = []            # the runs this tab's Generate started (see launched_runs)
        self._displayed_row: dict | None = None        # a saved generation this tab is showing (footer visible); None when blank
        # (status, frame, settings) of an enhancement running on the displayed
        # image, fed from outside (the gallery owns the jobs); None when nothing
        # is cooking. Beside it, the app-wide enhance settings the "+ Enhance"
        # card would run at — also the gallery's, pushed in the same way.
        self._pending_enhancement: tuple | None = None
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
        self._folder_request: dict | None = None
        # Where this tab's settings came from, when the Combine panel opened them
        # here: the act picked in its dropdown and the video whose recipe they
        # are, as (category, video_prompt_id). Carried so a run launched from this
        # tab — the combination as opened, or edited first — says in the queue what
        # it was asked for. Nothing else on the form remembers either.
        self._recipe_source: tuple[str, str | None] = ("", None)
        # Re-reads (shortly) whether Generate would reproduce a past run — see
        # refresh_generate_caption for why the answer isn't taken on the spot.
        self._caption_timer = QTimer(self)
        self._caption_timer.setSingleShot(True)
        self._caption_timer.setInterval(_CAPTION_DELAY_MS)
        self._caption_timer.timeout.connect(self._apply_generate_caption)
        self._build_ui()

    def _build_ui(self):
        # One column: the preview over the settings form and the Generate button.
        # The preview leads (a running re-roll's frames, then the finished output);
        # the button bank sits at the bottom, under the settings.
        layout = QVBoxLayout(self)
        # A margin round the whole tab, so nothing in it — the preview, the form's
        # headings, the button bank — sits flush against the pane's edge.
        layout.setContentsMargins(_PANE_MARGIN, _PANE_MARGIN, _PANE_MARGIN, _PANE_MARGIN)
        layout.setSpacing(8)
        # The preview leads the column: it mirrors a running re-roll's frames (driven
        # from outside), shows the browsed generation's output when one is loaded, and
        # the newest matching result otherwise.
        self._preview = PreviewWidget(show_funscript_strip=True)
        # Dragging the shown generation out of the preview onto a combine slot, like a
        # gallery thumbnail: relay the drag start/end so the view can light the slots.
        self._preview.drag_started.connect(self.preview_drag_started)
        self._preview.drag_ended.connect(self.preview_drag_ended)
        # Its corners and its right-click go to the gallery, which owns the
        # bookmark, the bin and the enhance queue — the same route the browser
        # pane's thumbnails take, so an act means the same thing either side.
        self._preview.action_triggered.connect(self.item_action_requested)
        self._preview.context_requested.connect(self.context_menu_requested)
        layout.addWidget(self._preview, 3)
        # One scroll under the preview holds everything else: the read-only info on
        # top, the editable form below it, so they scroll together. This replaces the
        # old split — a cramped form-only scroll above a separate, non-scrolling info
        # footer — that buried the form (width/height, the swap button) out of reach.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        body_host = QWidget()
        body = QVBoxLayout(body_host)
        # A gap on the right so the fields stop short of the scroll bar rather than
        # running under it; the pane's own margin covers the other three sides.
        body.setContentsMargins(0, 0, _PANE_MARGIN, 0)
        body.setSpacing(8)

        # The output file + when it was made, at the top of the scroll (shown only
        # while displaying a saved generation). Params — editable or read-only — all
        # live in the form below now, so this block carries only those two facts.
        self._metadata_block = MetadataBlock()
        self._metadata_block.hide()
        body.addWidget(self._metadata_block)

        # Editable: the workflow picker, its typical-time estimate, and the param
        # form (swapped into _form_host whenever the workflow changes).
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
        # It shrinks to a short floor when the pane is narrow rather than holding
        # the width of the longest workflow name — see NoWheelComboBox, which every
        # picker in the app inherits that from. It still expands to fill the row.
        header.addRow(ElidingLabel("Workflow"), self._workflow_combo)
        body.addLayout(header)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        # A sentence, so it wraps rather than holding the pane open at its own
        # length — the form below it shrinks, and this has to shrink with it.
        self._estimate_label.setWordWrap(True)
        body.addWidget(self._estimate_label)
        self._form_host = QWidget()
        self._form_host_box = QVBoxLayout(self._form_host)
        self._form_host_box.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self._form_host)

        # The displayed generation's related media, below the form: a clickable
        # source-image tile for a video, or the "animated in" strip for an image.
        # Mutually exclusive; both hidden when the tab isn't showing a saved
        # generation.
        #
        # Stacked straight under it, with no stretch between. A stretch here used
        # to push these to the bottom of the viewport, which meant folding a form
        # section opened an elastic gap above them — the space growing by exactly
        # what the fold saved, so the closer the form got the further away they
        # went. Every gap in this column is the layout's spacing now, the same as
        # between the form's own sections.
        # One tile, one place: the start frame for a video, and for something a
        # spoken request made, the item it was asked about — the same kind of
        # link (this came from that) in the same spot, rather than a second tile
        # teaching the reader a second place to look.
        self._source_tile = SourceImageTile()
        self._source_tile.activated.connect(self.source_activated)
        body.addWidget(self._source_tile)
        self._animated_strip = AnimatedVideoStrip()
        self._animated_strip.video_activated.connect(self.animated_activated)
        body.addWidget(self._animated_strip)
        # Every version an enhanced image holds, alongside the other cross-links:
        # the preview opens on the most-enhanced one, and this is where the
        # earlier levels (and the original) are, each captioned with what made
        # it and draggable onto the Enhance subpanel to reuse those settings.
        # Hides itself for an image with only its original, which is most of them.
        self._versions = EnhanceVersions()
        self._versions.level_selected.connect(self._show_level)
        self._versions.enhance_requested.connect(self._on_enhance_requested)
        self._versions.delete_requested.connect(self._on_levels_delete_requested)
        body.addWidget(self._versions)
        # The slack goes here, under everything, so a short column rests at the
        # top of the scroll rather than spreading itself out.
        body.addStretch(1)

        self._scroll.setWidget(body_host)
        layout.addWidget(self._scroll, 4)

        # One button bank, fixed under the scroll so Generate is always reachable.
        # Send-to-Evolver shows only while displaying a saved
        # generation (and only for a video); the discard button only while a run
        # this tab launched is in flight (the gallery owns the job and drives
        # set_generating), throwing it away from the tab like the folder's tile —
        # "Cancel", or "Next seed" while that folder is auto-generating. Generate
        # only ever submits: a run in flight is watched in the strip's queue and on
        # the browser pane's card, so the button says nothing about one.
        # A flow rather than a row: the bank wraps onto a second line when the pane
        # is too narrow to hold it, instead of squeezing every label down to an
        # unreadable stub ("o fo", "to E", "ner"). Right-aligned, so Generate keeps
        # the corner it has always sat in, and at the family's two gaps — close
        # along a row, wider between wrapped rows — like the gallery's own bank.
        btn_row = FlowLayout(spacing=BUTTON_GAP, row_spacing=BUTTON_ROW_GAP,
                             align_right=True)
        self._evolver_btn = QPushButton("Send to Evolver")
        self._evolver_btn.setToolTip(
            "Copy this video into Evolver's inbox for sorting and upscaling."
        )
        self._evolver_btn.clicked.connect(self._on_send_to_evolver)
        self._evolver_btn.hide()  # shown only for a video the tab is displaying
        self._genau_btn = QPushButton("Send to Genau")
        self._genau_btn.setToolTip(
            "Send this clip down the Genau lane: Evolver upscales it on its usual "
            "schedule, then delivers it to the folder Genau plays from."
        )
        self._genau_btn.clicked.connect(self._on_send_to_genau)
        self._genau_btn.hide()  # shown only for a video the tab is displaying
        self._cancel_btn = QPushButton(discard_run_text(False))
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.hide()
        self._generate_btn = GenerateButton()
        self._generate_btn.clicked.connect(self._on_generate)
        btn_row.addWidget(self._evolver_btn)
        btn_row.addWidget(self._genau_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._generate_btn)
        layout.addLayout(btn_row)


        # Lays out the empty state on a fresh panel — no form, no estimate, and a
        # Generate with nothing to run — and everything below the picker once a
        # workflow is chosen.
        self._on_workflow_changed()

    def minimumSizeHint(self):
        """Never narrower than the settings can be squeezed into.

        The pane refuses to be dragged past what its contents fit in, rather than
        going there and scrolling them sideways: a horizontal scroll bar under a
        form is a bad trade for the drag it allows. Read live from the scroll's
        contents, which is what makes the floor follow the workflow on show — a
        form with more fields, or an image with a list of versions under it, is a
        wider thing and says so.

        No explicit ``setMinimumWidth`` here, and none on the wrapper this sits in
        (see :mod:`origenerator.gui.gallery_view`): an explicit minimum *replaces*
        this hint rather than joining it, so one would pin the floor at its own
        number and put the scroll bar back. Capped at ``_FLOOR_CAP``, which is
        where holding the floor would cost the window its tiling slot.

        It *replaces* the width the layout would otherwise ask for rather than
        joining it, and there is no comfortable-looking minimum under it: the
        settings are the only thing here with a claim on how narrow the pane may
        be, and any other floor — the preview's, a round number that looks about
        right — stops the drag while there is still room to give.
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
                + 2 * _PANE_MARGIN)

    def _can_generate(self) -> bool:
        """Is there anything to run? A run needs a server to send it to and a
        workflow to send — a tab still on the picker's placeholder has neither a
        graph nor params, so its Generate is greyed rather than silently inert."""
        return self._client is not None and self._workflow_combo.currentData() is not None

    def _on_workflow_changed(self):
        # A different workflow is a different recipe: whatever Combine opened
        # here no longer describes what this tab would run, so its mark goes
        # rather than riding onto an unrelated launch. Set again after a prefill,
        # which is what re-picks the workflow in the first place.
        self._recipe_source = ("", None)
        # And a folder's rewrite is a rewrite of that folder's own recipe. Swap
        # the workflow and the form is rebuilt from scratch — the tracked prompt
        # fields with it — so what is left is an ordinary config, not a rewrite
        # of anything.
        self._end_folder_request()
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
                                         hidden_keys=wf.enhance_keys()))
            self._form_workflow_key = key
            defaults = wf.default_params()
            carried = {
                k: v for k, v in edited.items()
                if k in defaults and v != defaults[k]
            }
            if carried:
                self._param_form.set_values(carried)
        else:
            self._clear_form()  # no workflow picked: nothing below is known yet
        self._refresh_estimate()
        self.refresh_generate_caption()
        self._generate_btn.setEnabled(self._can_generate())
        self._emit_title()
        self.show_recent_preview()  # these settings' newest result, not a blank pane

    def _edited_form_values(self) -> dict:
        """What the user changed on the installed form: its values minus the keys
        still sitting at its own workflow's defaults. Switching workflows carries
        these over (where the new workflow shares the param), so a typed prompt or
        picked image survives the switch — while the departing workflow's defaults
        never leak into the next one's."""
        prior = WORKFLOW_REGISTRY.get(self._form_workflow_key or "")
        if self._param_form is None or prior is None:
            return {}
        defaults = prior.default_params()
        return {
            k: v for k, v in self._param_form.get_values_static().items()
            if k not in defaults or v != defaults[k]
        }

    def _detach_form(self):
        """Take the installed form off the panel, if there is one.

        Detached from its parent at once (not just scheduled for deletion), so it
        leaves the screen immediately instead of lingering under whatever comes
        next until the event loop spins.
        """
        if self._param_form is None:
            return
        self._form_host_box.removeWidget(self._param_form)
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
        with the info above it, not boxed in a separate scroll of its own."""
        self._detach_form()
        self._param_form = form
        self._param_form.changed.connect(self.form_edited)
        self._param_form.changed.connect(self.refresh_modified_notice)
        # Any edit can make the config match a past generation, or stop matching one.
        self._param_form.changed.connect(self.refresh_generate_caption)
        self._form_host_box.addWidget(self._param_form)
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
        generation's params, a table read and a JSON parse per row — tens of
        milliseconds, far too much to spend on each keystroke of a prompt. Every
        cue restarts the one timer, so a burst of edits costs a single read once
        the typing stops.

        Public because the gallery has the other cue: a run of these very settings
        completing is what makes this tab's pinned seed a duplicate.
        """
        self._caption_timer.start()

    def _apply_generate_caption(self):
        """Say on the button what a press will do, and why, or leave it plain."""
        if self._folder_request is not None:
            count = self._folder_request["count"]
            self._generate_btn.set_caption(_REQUEST_CAPTION)
            self._generate_btn.setToolTip(
                _REQUEST_TIP_ONE if count == 1
                else _REQUEST_TIP.format(count=count))
            return
        wf = WORKFLOW_REGISTRY.get(self._workflow_combo.currentData())
        config = self.current_config()
        duplicate = (
            wf is not None and self._can_generate()
            and would_reproduce_a_completed_run(
                self._db.list_generations(), wf, config.params,
                seed_is_random=config.seed_is_random,
            )
        )
        self._generate_btn.set_caption(
            _RANDOM_SEED_CAPTION if duplicate else DEFAULT_CAPTION)
        self._generate_btn.setToolTip(_RANDOM_SEED_TIP if duplicate else "")

    def _on_generate(self):
        """Ask the gallery to generate this config — a re-roll of its settings folder.

        A Generate is conceptually a gallery re-roll: it emits the form's workflow
        and values (a Random seed already re-rolled by :meth:`ParamForm.get_values`)
        as :attr:`generate_requested`, and the gallery launches the job in that
        folder and navigates there. Pressing it again while a run of this tab's is
        still in flight asks for another one — ComfyUI works through a queue — so
        the panel keeps only the form-level guard that an image workflow has its
        input picked.
        """
        if not self._can_generate():
            return  # no server to run against, or no workflow picked yet
        key = self._workflow_combo.currentData()
        if key not in WORKFLOW_REGISTRY:
            return
        wf = WORKFLOW_REGISTRY[key]
        params = self._param_form.get_values()

        missing_images = [
            pd.label for pd in wf.param_definitions()
            if pd.type == "image" and not str(params.get(pd.key, "")).strip()
        ]
        if missing_images:
            self._generate_btn.flash_guard(
                f"Select an input image ({', '.join(missing_images)})"
            )
            return
        if self._folder_request is not None:
            # A request that asked for nothing would re-run every seed in the
            # folder to re-create the folder, so the press says what it still
            # needs rather than filling the queue with copies.
            if configs_match(self._folder_request["opened_on"], self.current_config()):
                self._generate_btn.flash_guard(_REQUEST_GUARD)
                return
            self.changes_requested.emit(self._folder_request["folder_key"], key, params)
            return
        self.generate_requested.emit(key, params)

    def set_recipe_source(self, category: str, video_prompt_id: str | None) -> None:
        """Remember that these settings came out of Combine — the act off its
        dropdown, and the video whose recipe they are.

        Set after the settings are in (:meth:`prefill` re-picks the workflow,
        which clears this), so what the tab launches carries the mark whether it
        is run as opened or edited first.
        """
        self._recipe_source = (category or "", video_prompt_id or None)

    def recipe_source(self) -> tuple[str, str | None]:
        """``(category, video_prompt_id)`` for a tab Combine opened, else
        ``("", None)`` — what a launch from here stamps on its row."""
        return self._recipe_source

    def show_combination(self, image_path, video_path) -> None:
        """Put the combination this tab was opened with in the preview: the frame,
        a plus, and the gray clip whose settings came with it. Nothing has been
        made from the pair yet, so there is no result for the pane to show."""
        self._preview.show_combination(image_path, video_path)

    def launched_runs(self) -> list[str]:
        """The runs this tab's Generate started, oldest first.

        Each named by the prompt id it *began* under, so a chained i2v (a frame,
        then the video on it) stays one run to this tab. A tab can hold several:
        ComfyUI takes a queue, so pressing Generate again asks for another. Empty
        once the tab has been pointed at someone else's generation, or before it
        has generated anything.
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

        All it moves is the discard button, which shows while there is a run of
        this tab's to throw away. Generate itself is untouched: it submits, and
        every reading of the run it submitted is in the strip's queue and on the
        browser pane's in-flight card.

        ``auto_generating`` says the run's folder is auto-looping, which is what
        the discard button reads as "Next seed" rather than "Cancel" (see
        :func:`inflight.discard_run_text`). Re-labeled ahead of the idempotence
        guard below, because the Auto toggle flips mid-run without the generating
        state ever changing.
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
            self._param_form.set_seed_random(True)

    def _image_rows(self):
        return [r for r in self._db.list_generations() if media_type_of_row(r) == "image"]

    def settings_key(self) -> tuple[str, str] | None:
        """The gallery settings-folder this config maps to: (workflow, signature).

        The signature is normalized against the workflow's defaults (see
        ``canonical_settings``), so it matches the folder this tab's outputs land
        in and groups reruns that differ only by per-instance keys.
        ``None`` when no workflow is selected.
        """
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
        if wf is None or self._param_form is None:
            return None
        params = self._param_form.get_values_static()
        index = build_image_config_index(self._image_rows())
        return key, settings_signature(key, json.dumps(params), index)

    def show_recent_preview(self):
        """Fill the preview with the newest saved generation matching this tab's
        settings, or the empty 'select a generation' placeholder when nothing has
        been generated with them yet.

        The shown generation becomes ``_displayed_row``, so an idle autoshow of a
        scripted video arms the OSR2 drive exactly like a browsed selection — the
        drive follows whatever video is actually on screen, however it got there.

        The footer stays hidden: an autoshow is a peek, not an explicit selection,
        so it shows the preview alone and never a prior selection's metadata."""
        self._hide_footer()
        row = self._recent_matching_row()
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR) if row is not None else None
        if preview is not None:
            self._preview.show_media(*preview)
            self._preview.set_draggable_id(row["prompt_id"])  # its preview drags onto combine
            self._displayed_row = row
        else:
            self._preview.clear()  # nothing generated with these settings yet
            self._displayed_row = None
        self._arm_preview_actions()
        self._note_displayed_config()
        self._emit_title()  # the tab is named after what it shows

    def _recent_matching_row(self) -> dict | None:
        """The newest saved generation in this tab's settings folder, or None."""
        rows = self._db.list_generations()  # newest first
        index = build_image_config_index([r for r in rows if media_type_of_row(r) == "image"])
        matching = rows_in_settings(rows, self.settings_key(), index)
        return matching[0] if matching else None

    def current_config(self) -> ConfigSnapshot:
        """Snapshot the live settings for comparison (without randomizing the seed)."""
        if self._param_form is None:
            return ConfigSnapshot(self._workflow_combo.currentData(), {}, False)
        return ConfigSnapshot(
            self._workflow_combo.currentData(),
            self._param_form.get_values_static(),
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
        of tabs reads as the things you have open. A config that has never run
        has no item to name it, so it takes its folder's name — the same name the
        folder wears in the tree, code or typed.
        """
        if self._folder_request is not None:
            return _REQUEST_TITLE.format(folder=self._folder_request["label"])
        name = item_label(self._displayed_row)
        if not name:
            key = self.settings_key()
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
        # arms the rewrite afterwards, so it is not undoing itself.)
        self._end_folder_request()
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
        self.prefill(snapshot.workflow_name, snapshot.params)
        if self._param_form:
            self._param_form.set_seed_random(snapshot.seed_is_random)

    # --- rewriting a whole folder's prompt ------------------------------------

    def open_folder_request(self, folder_key: str, label: str, workflow_name: str,
                      params: dict, pictures: list) -> None:
        """Open this tab as a rewrite of one folder's prompt.

        The folder's own settings fill the form, its prompts are marked against
        what they say now — lit where words arrive, struck through where they go
        (:mod:`origenerator.gui.tracked_prompt`) — and its images fill the
        preview, all of them, tiled. Nothing about it is one generation, so the
        tab shows no file, no footer and no "modified" notice: what the settings
        are about is the wall above them.

        ``pictures`` carries one entry per run the press will make, whether or
        not there is a thumbnail to draw for it, so the count in the hover is
        the number of images rather than of readable files.
        """
        self.prefill(workflow_name, params)  # ends any rewrite already here
        self._folder_request = {
            "folder_key": folder_key,
            "label": label,
            "count": len(pictures),
            # What the tab opened on, so a press can tell a rewrite from a
            # re-run of the folder it was rewriting.
            "opened_on": self.current_config(),
        }
        self._hide_footer()
        self._displayed_row = None     # a folder, not a generation on display
        self._displayed_config = None  # ...so no settings for a notice to deviate from
        self._preview.show_folder(pictures)
        if self._param_form is not None:
            self._param_form.track_prompt_rewrites()
        self._apply_generate_caption()
        self._emit_title()

    def _end_folder_request(self) -> None:
        """Stop this tab being a folder rewrite, leaving an ordinary config.

        The prompt fields go back to plain inputs holding the prompts they show —
        a marked-up field left behind would go on measuring edits against a
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
        """Display a browsed generation in this tab: seed the editable form with
        its settings, show its output in the preview, and reveal the info for its
        media type (an image's animations, a video's source-image tile + Evolver)
        and, when ``request`` says a spoken request made it, a link back to the
        item it was asked about.

        The form is seeded first so its recent-preview autoshow doesn't override
        the selection's own output. A workflow the app can't rebuild leaves the
        form as it was but still shows the preview and info.

        Pointing the tab at someone else's generation ends its claim on the runs
        it launched: the bar would otherwise sit mid-run over a picture that has
        nothing to do with it, and its Cancel would stop something off screen.
        The same goes for a combination Combine opened here — the tab is about
        this row now, and a launch from it is not the combination's.
        """
        self.forget_launched()
        self._recipe_source = ("", None)
        self._end_folder_request()  # a workflow this app can't rebuild never reaches prefill
        workflow_name = row.get("workflow_name", "")
        if workflow_name in WORKFLOW_REGISTRY:
            self.prefill(workflow_name, merge_denormalized(row))
        # Prefill's autoshow just set _displayed_row to this tab's recent result; the
        # browsed selection is what's actually on display, so _display_result (below)
        # overrides it.
        self._display_result(row, image_rows, request)

    def show_completed_result(self, row: dict, image_rows: list[dict]):
        """Show a generation this tab's own Generate just produced: swap the live
        preview for the saved output and reveal its footer, leaving the form exactly
        as the user left it.

        Unlike :meth:`show_saved_generation`, the form is not re-seeded — the tab
        already holds the settings that made this result, and the user may have kept
        editing the next prompt while the run was in flight. Re-seeding here would
        wipe those edits, so the completed result touches only the preview and info.
        A tab holding a folder rewrite takes none of it: that tab is about the
        folder, and the batch it launched lands a picture at a time — each one
        would swap the wall of pictures for whichever finished last.
        """
        if self._folder_request is not None:
            return
        self._display_result(row, image_rows)

    def refresh_displayed(self, row: dict, image_rows: list[dict]):
        """``row`` has changed under this tab: re-show it if it is what the tab
        is displaying, else leave the tab alone.

        A tab holds the row it was given, not a live view of the database, so a
        change made to that row elsewhere — an enhancement folding in a new
        level — leaves the tab describing the image as it was. The version list
        is where that shows: it is built from the row, so without this the level
        only appears the next time the tab is opened.

        The form is left exactly as the user has it, the same deal
        :meth:`show_completed_result` makes: nothing about the settings changed,
        only what the image now holds.
        """
        shown = self._displayed_row
        if shown is None or shown.get("prompt_id") != row.get("prompt_id"):
            return
        self._display_result(row, image_rows)

    def show_finished_media(self, row: dict):
        """Put a finished run's saved output in the preview alone — no footer, no
        form, and not as this tab's displayed generation.

        What the tab *mirroring* a run shows when it lands: the live frames it has
        been streaming give way to the picture they were making (and a fullscreen
        show opened over them lands on it too), while the tab itself stays whatever
        it was. That last part is the point — a run this tab didn't launch must not
        make the pane's blank resting tab hold a generation, or a click would open
        a tab beside it instead of filling it. The tab that *did* launch the run
        gets the whole end-state through :meth:`show_completed_result`.
        """
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is None:
            return  # nothing to look at; leave the frames rather than blank the pane
        self._preview.show_media(*preview)
        self._preview.set_draggable_id(row["prompt_id"])  # its preview drags onto combine
        self._arm_preview_actions(row["prompt_id"])  # …and wears its corners

    def _display_result(self, row: dict, image_rows: list[dict], request=None):
        """Point the preview and footer at ``row`` — the shared tail of showing a
        generation, whether freshly browsed or just completed. The form is left
        untouched; :meth:`show_saved_generation` seeds it first, before this runs."""
        arriving = (self._displayed_row is None
                    or self._displayed_row.get("prompt_id") != row.get("prompt_id"))
        self._displayed_row = row
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is not None:
            self._preview.show_media(*preview)  # after any prefill, so it wins over autoshow
            self._preview.set_draggable_id(row["prompt_id"])  # its preview drags onto combine
        else:
            self._preview.clear()
        self._show_footer(row, image_rows, preview, request)
        self._arm_preview_actions()
        if arriving:
            self._note_displayed_config()
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

        Re-run after every change to the picture, because showing media is what
        takes them away — a control on a picture can no more outlive that picture
        than the "no longer these settings" notice beside it can — and because
        everything they report moves under the picture too: the bookmark when the
        menu toggles one, what the plus is offering whenever a knob turns on the
        Enhance panel. An autoshow arms them as readily as an explicit selection:
        the footer stays hidden there because an autoshow is a peek rather than a
        choice, but the picture is a real generation and starring it means exactly
        what starring it anywhere means.

        ``prompt_id`` names the generation when it is NOT the row this tab holds —
        a suppressed re-selection puts another item's output in the preview
        without the tab taking it on (:meth:`show_selection_media`), and the
        corners have to be about the picture rather than about the row behind it.
        """
        row = (self._displayed_row if prompt_id is None
               else self._db.get_generation(prompt_id))
        if row is None:
            self._preview.set_actions(None)
            return
        self._preview.set_actions(
            row["prompt_id"], starred=bool(row.get("starred")),
            enhance=enhance_state(row, self._enhance_settings),
        )

    def show_selection_media(self, preview, prompt_id: str):
        """Put ``prompt_id``'s output in this tab's preview and nothing else — no
        form, no footer, and the row the tab holds left alone.

        The light-touch refresh a suppressed re-selection makes: the rebuild after
        every poll, and a Back/Forward that never re-seeded the form. Everything
        the picture carries is re-asserted here, because showing media clears the
        lot — the drag payload, the modified notice, and the corner controls. The
        gallery reaches for this rather than the preview directly, so a surface
        the tab owns is only ever driven through the tab.
        """
        self._preview.show_media(*preview)
        self._preview.set_draggable_id(prompt_id)
        self._arm_preview_actions(prompt_id)
        # Re-showing the media clears whatever the pane was saying about it, so
        # put this tab's own notice back if its form still deviates.
        self.refresh_modified_notice()

    def _note_displayed_config(self):
        """Take the settings a generation arriving in this tab is being shown under
        as the mark to measure edits against, and clear any notice left from the
        last one. From here it is the form moving away from these that says the
        picture is no longer what a Generate would make.

        For a generation *arriving* — the one the form was just seeded from, or the
        result this tab's own Generate made. What happens to the generation already
        on display leaves the mark alone (see :meth:`_display_result`).
        """
        self._displayed_config = (
            self.current_config() if self._displayed_row is not None else None
        )
        self.refresh_modified_notice()

    def refresh_modified_notice(self):
        """Mark the preview when the form no longer describes the picture on it.

        A tab pointed at a saved generation — a browsed selection, a finished run,
        or the idle autoshow of this config's newest result — shows that
        generation's output beside the settings that made it. Change any of them
        and what's on screen stops being an answer to what the form now asks, so
        the preview says so instead of standing there as a silent one. Putting the
        settings back takes the notice away again.

        Public because the preview is also driven from outside (a suppressed
        re-selection re-shows the same row's media), and anything that changes
        what's on screen clears the notice — so whoever did that re-asserts it.
        """
        modified = (self._displayed_config is not None
                    and not configs_match(self._displayed_config, self.current_config()))
        self._preview.set_notice(_MODIFIED_NOTICE if modified else None)

    def _hide_footer(self):
        """Hide every info/action element that belongs only to a saved generation —
        the state of a blank tab, or one whose preview is a bare autoshow rather than
        an explicit selection."""
        self._metadata_block.hide()
        self._versions.hide()
        self._pending_enhancement = None  # nothing on display to be enhancing
        self._source_tile.clear()
        self._animated_strip.hide()
        self._evolver_btn.hide()
        self._genau_btn.hide()

    def _show_footer(self, row: dict, image_rows: list[dict], preview, request=None):
        """Reveal the info and actions for the generation on display: the read-only
        metadata block for every selection, the source tile + Evolver for a video,
        and the animations strip for an image. ``preview`` is the already-resolved
        ``(path, media_type)`` (or ``None``), so Evolver keys off the same on-disk
        lookup.

        ``request`` is the spoken request that made this row, when one did: it
        marks the prompt fields with what it changed and points the source tile
        at the item it was asked about."""
        # Only files no version claims are left for this block, which for an
        # image is usually none of them — so it shows only when it has content
        # rather than opening a bare gap above the form.
        self._metadata_block.setVisible(self._metadata_block.show_row(row))
        self._refresh_versions()
        self._animated_strip.show_videos(self._animated_items(row))  # hides itself when empty
        self._show_source_tile(row, image_rows, request)
        self._show_request_diff(request)
        self._update_evolver_button(preview)
        self._update_genau_button(preview)

    def displayed_row(self) -> dict | None:
        """The saved generation this tab is showing, or ``None``.

        Whatever is in the preview — a browsed selection or an idle autoshow —
        which is what the gallery matches its live enhance jobs against.
        """
        return self._displayed_row

    def set_pending_enhancement(self, pending: tuple | None):
        """Reflect an enhancement being generated for the image on display.

        ``pending`` is ``(status, frame, settings)`` while one is running,
        ``None`` otherwise. Fed from the gallery, which owns the jobs. A new
        frame updates the level's row in place; only a run starting or ending
        rebuilds the list, so a stream of frames doesn't thrash the layout.

        The frame also goes up to the preview — a run of this image is a run
        you are watching, and the pane at the top of the tab is where this app
        shows you what is being made. It was the one surface that stayed on the
        old picture while the little row beside it streamed. When the run ends,
        the preview goes back to the image itself (by then the enhanced one).

        These frames keep whatever the pane is saying about the picture rather
        than clearing it, which every other live frame does. An enhancement is
        not a run of the settings beside it — it is the coming state of the very
        image those settings are being edited away from — so a mark that the form
        has moved off it is as true of the version being made. Clearing it here
        left the mark and the frames trading places several times a second while
        the form was typed in: each frame took the mark off, each keystroke put
        it back.
        """
        if pending == self._pending_enhancement:
            return
        was_running = self._pending_enhancement is not None
        self._pending_enhancement = pending
        if pending is not None:
            frame = pending[1]
            if frame:
                self._preview.show_frame(frame, keep_notice=True)
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
        self._preview.show_media(*preview)
        self._preview.set_draggable_id(row["prompt_id"])
        self._arm_preview_actions()
        self.refresh_modified_notice()  # the picture is back; so is anything said about it

    def set_fullscreen_factory(self, make):
        """Wire what a double-click on this tab's preview opens — a slideshow of
        the folder behind it, which only the gallery can assemble. Passed straight
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
        self._arm_preview_actions()

    def _on_enhance_requested(self):
        if self._displayed_row is not None:
            self.enhance_requested.emit(self._displayed_row["prompt_id"])

    def _on_levels_delete_requested(self, positions: list):
        """Relay a version-list delete by filename, not by position.

        The list is rebuilt from the row on every refresh, so a position is only
        good for as long as the widget that produced it — the gallery does the
        deleting and it must be told *which files*, resolved here while the list
        and the row still agree."""
        row = self._displayed_row
        if row is None:
            return
        levels = displayed_levels(row)
        names = [levels[p].file.get("filename") for p in positions
                 if 0 <= p < len(levels)]
        if names:
            self.levels_delete_requested.emit(row["prompt_id"], names)

    def _refresh_versions(self):
        """Rebuild the version list for whatever this tab is displaying.

        The preview is already on ``output_files[0]`` — the most-enhanced
        version — so the list leads with that level and offers the rest below
        it, under the ``+ Enhance`` row. A video has no versions and no row to
        press: the enhancer takes images.
        """
        row = self._displayed_row
        if row is None or media_type_of_row(row) != "image":
            self._versions.show_levels([])
            return
        self._versions.show_levels(
            self._version_items(row), self._pending_enhancement,
            self._add_card_for(row), str(row.get("created_at", "")),
            row.get("days_in_trash"),
        )

    def _add_card_for(self, row: dict) -> tuple:
        """``(settings, duplicate_of)`` for the ``+ Enhance`` row on ``row``."""
        params = enhance_params_for(row, self._enhance_settings)
        return (describe_enhance_params(params or {}),
                level_matching_settings(row, self._enhance_settings))

    @staticmethod
    def _level_path(level) -> Path:
        """Where one version's file lives — under ComfyUI's output folder, or in
        the trash once the generation has been deleted."""
        return output_file_path(level.file, COMFYUI_OUTPUT_DIR)

    def _version_items(self, row: dict) -> list[tuple]:
        """``(level, image path)`` for each version this image holds — the list
        draws each picture from the file itself, so a level shows what it
        actually looks like rather than the row's one shared thumbnail."""
        return [(level, self._level_path(level))
                for level in displayed_levels(row)]

    def _show_level(self, position: int):
        """Put one of the displayed image's enhancement levels in the preview.

        Only the picture changes: the row on display, its form, its metadata and
        the OSR2 drive all still belong to the generation — the levels are
        versions of one image, not separate generations, so switching between
        them is a look rather than a navigation.
        """
        if self._displayed_row is None:
            return
        levels = displayed_levels(self._displayed_row)
        if not 0 <= position < len(levels):
            return
        path = self._level_path(levels[position])
        if path.exists():
            self._preview.show_media(path, "image")
            self._arm_preview_actions()  # still the same generation, still actionable
            self.refresh_modified_notice()  # a version of the same generation, same notice

    def _show_source_tile(self, row: dict, image_rows: list[dict], request=None):
        """Reveal the source tile for whatever this row was built from, else hide
        it. The tile shows that item's thumbnail and filename and navigates to it
        on click.

        For a video that is its start frame. For something a spoken request made
        it is the item the request was asked about — the same relation in the
        same place, since a requested image has no start frame and a requested
        video's start frame is the one it already had.
        """
        source_id = find_source_image_id(row, image_rows)
        source_row = next(
            (r for r in image_rows if r.get("prompt_id") == source_id), None
        ) if source_id else None
        heading = None
        if source_row is None and request is not None:
            source_row = request.get("source_row")
            heading = "Requested from"
        if not source_row:
            self._source_tile.clear()
            return
        files = row_output_files(source_row)
        self._source_tile.show_source(
            source_row["prompt_id"], source_row.get("thumbnail_path"),
            files[0]["filename"] if files else "", heading=heading,
        )

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

    def _animated_items(self, row: dict) -> list[tuple]:
        """(prompt_id, looping-preview path, still path) for each video an image
        was animated into — empty for anything but an image with animations."""
        if media_type_of_row(row) != "image":
            return []
        videos = videos_from_source_image(row, self._video_rows())
        if len(videos) > _ANIMATED_STRIP_LIMIT:
            logger.info("Image %s has %d animations; showing the first %d",
                        row["prompt_id"], len(videos), _ANIMATED_STRIP_LIMIT)
        return [
            (v["prompt_id"], animated_preview_path(v, COMFYUI_OUTPUT_DIR, THUMB_DIR),
             v.get("thumbnail_path"))
            for v in videos[:_ANIMATED_STRIP_LIMIT]
        ]

    def _video_rows(self) -> list[dict]:
        return [r for r in self._db.list_generations() if media_type_of_row(r) == "video"]

    # --- Send to Genau: hand a clip to the lane that ends in Genau's folder ---

    def _update_genau_button(self, preview):
        """Reflect the displayed generation on the Send-to-Genau button.

        Shown only for a video with a file on disk — the Genau lane carries clips.
        One already sent shows a persistent, disabled "Sent ✓", read from the row
        rather than the button's state so it survives a restart. ``preview`` is the
        resolved ``(path, media_type)``, or ``None``.
        """
        is_video = preview is not None and preview[1] == "video"
        self._genau_btn.setVisible(is_video)
        if not is_video:
            return
        already_sent = bool(self._displayed_row and self._displayed_row.get("genau_exported_at"))
        self._genau_btn.setText("Sent to Genau ✓" if already_sent else "Send to Genau")
        self._genau_btn.setEnabled(not already_sent)

    def _on_send_to_genau(self):
        """Copy the displayed video into the Genau lane's inbox and remember the send.

        The same handoff as :meth:`_on_send_to_evolver` down to the re-read of the
        persisted flag and the loud failure — only the source folder differs, which
        is what tells Evolver to deliver the upscaled result to Genau.
        """
        if not self._displayed_row or self._displayed_row.get("genau_exported_at"):
            return
        path = self._displayed_video_path()
        if path is None:
            return
        try:
            evolver_export.export_video(path, EVOLVER_INBOX_DIR / GENAU_SOURCE)
        except Exception as e:
            logger.exception("Failed to send %s to Genau", path)
            QMessageBox.warning(
                self._preview, "Send to Genau failed",
                f"Could not send this clip to Genau:\n\n{e}",
            )
            return
        prompt_id = self._displayed_row["prompt_id"]
        self._db.mark_genau_exported(prompt_id)
        # Re-read so the row (and thus the button) reflects the persisted send.
        self._displayed_row = self._db.get_generation(prompt_id) or self._displayed_row
        self._update_genau_button((path, "video"))

    # --- Send to Evolver: hand a displayed video to the sibling pipeline -------

    def _update_evolver_button(self, preview):
        """Reflect the displayed generation on the Send-to-Evolver button.

        Shown only when the generation is a video with a file on disk; Evolver is
        a video pipeline, so for an image or a missing file the button is hidden.
        A video already sent shows a persistent, disabled "Sent ✓" (the flag is
        read from the row, which the DB persists). ``preview`` is the resolved
        ``(path, media_type)``, or ``None``."""
        is_video = preview is not None and preview[1] == "video"
        self._evolver_btn.setVisible(is_video)
        if not is_video:
            return
        already_sent = bool(self._displayed_row and self._displayed_row.get("evolver_exported_at"))
        self._evolver_btn.setText("Sent to Evolver ✓" if already_sent else "Send to Evolver")
        self._evolver_btn.setEnabled(not already_sent)

    def _displayed_video_path(self) -> Path | None:
        """The on-disk video file backing the displayed generation, or ``None``
        when it isn't a video (or its file is missing). Resolved fresh, so a file
        deleted since selection is caught. Shared by Send-to-Evolver and OSR2 drive.

        ``_displayed_row`` is whatever the preview is showing — a browsed selection
        or this tab's idle autoshow — so a scripted video on screen arms the drive
        either way."""
        if not self._displayed_row:
            return None
        preview = resolve_preview(self._displayed_row, COMFYUI_OUTPUT_DIR)
        if preview is None or preview[1] != "video":
            return None
        return preview[0]

    # --- Drive OSR2: what the (global) driver should stream for this tab -------

    def set_preview_paused(self, paused: bool) -> None:
        """Freeze or resume this tab's preview video (the session's OmniPause)."""
        self._preview.set_playback_paused(paused)

    def osr2_drive_target(self):
        """``(video_path, player, actions)`` for the shown video, or ``None``.

        The view's single global driver asks the front tab for this whenever driving
        is on and the shown video changes: the on-disk video (the drive identity), the
        media player to follow, and the funscript actions beside it. ``None`` when the
        tab isn't showing a video, or that video has no funscript."""
        return drive_target_for(self._displayed_video_path(), self._preview.player())

    def _on_send_to_evolver(self):
        """Copy the displayed video into Evolver's inbox and remember the send.

        Re-checks the persisted flag (not just the button's disabled state) so the
        handoff can't be repeated. The copy lands in another app's inbox with no
        other visible result here, so a failure must surface loudly."""
        if not self._displayed_row or self._displayed_row.get("evolver_exported_at"):
            return
        path = self._displayed_video_path()
        if path is None:
            return
        try:
            evolver_export.export_video(path, EVOLVER_INBOX_DIR / EVOLVER_SOURCE)
        except Exception as e:
            logger.exception("Failed to send %s to Evolver", path)
            QMessageBox.warning(
                self._preview, "Send to Evolver failed",
                f"Could not send this video to Evolver:\n\n{e}",
            )
            return
        prompt_id = self._displayed_row["prompt_id"]
        self._db.mark_evolver_exported(prompt_id)
        # Re-read so the row (and thus the button) reflects the persisted send.
        self._displayed_row = self._db.get_generation(prompt_id) or self._displayed_row
        self._update_evolver_button((path, "video"))
