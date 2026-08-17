import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter,
    QComboBox, QPushButton, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator import evolver_export
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    EnhanceSettings, animated_preview_path,
    build_image_config_index, config_tab_title, describe_enhance_params,
    displayed_levels, enhance_params_for, find_source_image_id,
    level_matching_settings, media_type_of_row, output_file_path,
    resolve_preview, row_output_files, rows_in_settings, settings_signature,
    videos_from_source_image,
)
from origenerator.generation_config import ConfigSnapshot, merge_denormalized
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.enhance_versions import EnhanceVersions
from origenerator.gui.generate_button import GenerateButton
from origenerator.gui.metadata_block import MetadataBlock
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.osr2_driver import drive_target_for
from origenerator.gui.param_form import ParamForm
from origenerator.gui.preview_widget import PreviewWidget
from origenerator.gui.source_image_tile import SourceImageTile
from origenerator.gui.thumbnail_strip import ThumbnailStrip
from origenerator.timing import estimate_label
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.config import (
    COMFYUI_OUTPUT_DIR, EVOLVER_INBOX_DIR, EVOLVER_SOURCE, THUMB_DIR,
)

logger = logging.getLogger(__name__)

_ANIMATED_STRIP_LIMIT = 8  # most animation previews shown for one image at once


class GenerateConfigPanel(QWidget):
    """One generation configuration: pick a workflow and set its params.

    Clicking Generate doesn't run a job here — it emits :attr:`generate_requested`
    for the gallery to launch as a re-roll of this config's settings folder. The
    panel lays out two resizable panes itself — a main column beside this tab's own
    slim strip of past runs. The main column stacks a fixed preview on top, then one
    scroll holding the File/Created block above the editable form and, at its bottom,
    the displayed generation's related media, then a single button bank
    (Go-to-folder, Send-to-Evolver, Cancel, Generate). There's no status line —
    Generate itself doubles as the progress bar, filling as a run advances. Clicking a
    strip thumbnail re-emits its prompt id via ``strip_activated`` so a container can
    open (or reuse) a tab for it. The preview is driven from outside: a browsed
    selection's output, a running re-roll's live frames, or this config's newest
    matching result when idle.

    The info appears only while the tab is displaying a saved generation
    (:meth:`show_saved_generation`): a File/Created block above the form, and at the
    bottom of the scroll the videos an image was animated into, or a clickable
    source-image tile for a video. Go-to-folder (any saved generation), Send-to-
    Evolver (a video), and the Drive-OSR2 toggle key off the displayed row. A blank
    tab, or one showing a bare autoshow, hides them all.

    A fresh panel opens with no workflow picked — the picker sits on its
    placeholder, and everything the workflow decides (its typical time, its param
    form, its Generate) waits until one is chosen. That is the pane's resting
    state: a tab is always open, so the pane is never a blank rectangle, and the
    one question it asks first is which workflow to run.
    """

    title_changed = pyqtSignal(str)     # current tab title
    form_replaced = pyqtSignal()        # a new workflow swapped the param form out
    strip_activated = pyqtSignal(str)   # a strip thumbnail was clicked (prompt_id)
    source_activated = pyqtSignal(str)      # the source-image tile was clicked (prompt_id)
    animated_activated = pyqtSignal(str)    # an animation tile was clicked (prompt_id)
    containing_folder_requested = pyqtSignal(str)  # "Go to folder" clicked (prompt_id)
    generate_requested = pyqtSignal(str, dict)  # Generate clicked: (workflow_name, form params)
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
        self._custom_title: str | None = None        # user-set name; overrides the auto title
        self._strip_ids: list[str] = []               # this tab's strip: seeded folder + its own runs, newest first
        self._param_form: ParamForm | None = None
        self._generating = False                       # a run this tab launched is in flight (drives the progress button)
        self._generating_prompt_id: str | None = None  # that run's prompt, so only ITS progress fills the button
        self._launched_runs: list[str] = []            # the runs this tab's Generate started (see launched_runs)
        self._displayed_row: dict | None = None        # a saved generation this tab is showing (footer visible); None when blank
        # (status, frame, settings) of an enhancement running on the displayed
        # image, fed from outside (the gallery owns the jobs); None when nothing
        # is cooking. Beside it, the app-wide enhance settings the "+ Enhance"
        # card would run at — also the gallery's, pushed in the same way.
        self._pending_enhancement: tuple | None = None
        self._enhance_settings = EnhanceSettings()
        self._build_ui()
        self._connect_signals()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Two resizable panes, the divider doubling as a drag handle: a main column
        # (preview on top, then the settings and Generate) and this tab's own slim
        # strip of past runs on the right.
        self._panes = QSplitter(Qt.Orientation.Horizontal)
        self._panes.setChildrenCollapsible(False)  # a pane can't be dragged shut
        self._panes.setHandleWidth(6)

        # Main pane: the preview over the settings form and the Generate button. The
        # preview leads (a running re-roll's frames, then the finished output); the
        # status bar and button sit at the bottom, under the settings.
        main = QWidget()
        main_box = QVBoxLayout(main)
        main_box.setContentsMargins(0, 0, 0, 0)
        main_box.setSpacing(8)
        # The preview leads the column: it mirrors a running re-roll's frames (driven
        # from outside), shows the browsed generation's output when one is loaded, and
        # the newest matching result otherwise.
        self._preview = PreviewWidget(show_funscript_strip=True)
        # Dragging the shown generation out of the preview onto a combine slot, like a
        # gallery thumbnail: relay the drag start/end so the view can light the slots.
        self._preview.drag_started.connect(self.preview_drag_started)
        self._preview.drag_ended.connect(self.preview_drag_ended)
        main_box.addWidget(self._preview, 3)
        # One scroll under the preview holds everything else: the read-only info on
        # top, the editable form below it, so they scroll together. This replaces the
        # old split — a cramped form-only scroll above a separate, non-scrolling info
        # footer — that buried the form (width/height, the swap button) out of reach.
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        body_host = QWidget()
        body = QVBoxLayout(body_host)
        body.setContentsMargins(0, 0, 0, 0)
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
        header = QHBoxLayout()
        header.addWidget(QLabel("Workflow"))
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
        # Elide to a short floor when the window is narrow instead of holding the
        # width of the longest workflow name, which would set the tab's whole
        # minimum width and block tiling. It still expands to fill (stretch=1).
        self._workflow_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self._workflow_combo.setMinimumContentsLength(12)
        header.addWidget(self._workflow_combo, 1)
        body.addLayout(header)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
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
        main_box.addWidget(self._scroll, 4)

        # One button bank, fixed under the scroll so Generate is always reachable.
        # Go-to-folder and Send-to-Evolver show only while displaying a saved
        # generation (Evolver only for a video); Cancel only while a run this tab
        # launched is in flight (the gallery owns the job and drives set_generating),
        # stopping it from the tab like the folder's tile. Generate itself doubles as
        # the progress bar — it fills as the run advances — so there's no status line.
        btn_row = QHBoxLayout()
        self._folder_btn = QPushButton("Go to folder")
        self._folder_btn.setToolTip("Open this generation's folder in the gallery.")
        self._folder_btn.clicked.connect(self._on_go_to_folder)
        self._folder_btn.hide()  # shown only while displaying a saved generation
        self._evolver_btn = QPushButton("Send to Evolver")
        self._evolver_btn.setToolTip(
            "Copy this video into Evolver's inbox for sorting and upscaling."
        )
        self._evolver_btn.clicked.connect(self._on_send_to_evolver)
        self._evolver_btn.hide()  # shown only for a video the tab is displaying
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.hide()
        self._generate_btn = GenerateButton()
        self._generate_btn.clicked.connect(self._on_generate)
        btn_row.addStretch()
        btn_row.addWidget(self._folder_btn)
        btn_row.addWidget(self._evolver_btn)
        btn_row.addWidget(self._cancel_btn)
        btn_row.addWidget(self._generate_btn)
        main_box.addLayout(btn_row)

        self._panes.addWidget(main)

        # Right pane: this tab's own accumulating strip of past runs, kept slim so
        # the whole window can still tile into a monitor third or a portrait half.
        self._strip = ThumbnailStrip(self._db)
        self._strip.thumbnail_activated.connect(self.strip_activated)
        self._panes.addWidget(self._strip)
        # The main column grows with the window; the strip holds its width. The
        # floor stays low enough that the window can still tile narrow.
        main.setMinimumWidth(230)
        self._panes.setStretchFactor(0, 1)
        self._panes.setStretchFactor(1, 0)
        self._panes.setSizes([500, 150])

        layout.addWidget(self._panes)

        # Lays out the empty state on a fresh panel — no form, no estimate, and a
        # Generate with nothing to run — and everything below the picker once a
        # workflow is chosen.
        self._on_workflow_changed()

    def _connect_signals(self):
        if self._client is None:
            return  # a read-only gallery: no client to track
        # Mirror the running job's step progress onto the Generate button.
        self._client.progress.connect(self._on_progress)

    def teardown(self):
        """Disconnect from the shared client before the panel is destroyed."""
        if self._client is None:
            return  # never connected
        try:
            self._client.progress.disconnect(self._on_progress)
        except TypeError:
            pass

    def _on_progress(self, prompt_id: str, value: int, max_val: int):
        """Fill the Generate button with this tab's own run's progress.

        The client's progress is multiplexed across every job on the server, and
        generation is no longer serial from this tab's point of view — a background
        experiment can be executing while this tab's job still waits — so the event
        must match the tracked prompt, not just arrive while generating. Without
        the check, an experiment's steps filled the user's button, then their real
        run reset it to zero: "progress" that lies. A caller that never learned the
        prompt id (``set_generating(True)`` bare) keeps the old any-run behavior."""
        if not self._generating:
            return
        if self._generating_prompt_id is not None and prompt_id != self._generating_prompt_id:
            return  # someone else's run (e.g. a background experiment)
        self._generate_btn.set_progress(value, max_val)

    def _on_go_to_folder(self):
        """Ask the gallery to open the displayed generation's own folder."""
        if self._displayed_row:
            self.containing_folder_requested.emit(self._displayed_row["prompt_id"])

    def _can_generate(self) -> bool:
        """Is there anything to run? A run needs a server to send it to and a
        workflow to send — a tab still on the picker's placeholder has neither a
        graph nor params, so its Generate is greyed rather than silently inert."""
        return self._client is not None and self._workflow_combo.currentData() is not None

    def _on_workflow_changed(self):
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
        if not self._generating:
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
        self._param_form.changed.connect(self._emit_title)
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
        self.generate_requested.emit(key, params)

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

    def set_generating(self, generating: bool, prompt_id: str | None = None):
        """Reflect whether a run of this config's folder is in flight.

        While it is, Cancel shows and the Generate button switches to progress mode
        (filling as the run advances) so it can't be relaunched over; when it ends,
        Generate returns — still disabled where there is nothing to run: a
        read-only gallery with no client, or a tab with no workflow picked.

        ``prompt_id`` names the run, so the button fills only with that job's
        progress (see :meth:`_on_progress`). It's tracked even on a redundant
        re-assert, because a chained i2v swaps to a new prompt mid-flight (image
        stage, then video stage) without ever leaving the generating state.

        Idempotent: only an actual change flips the button, because ``start`` resets
        the fill to zero. The gallery re-asserts this state on every rebuild (so a
        reconnected run lights the right tab's button), and re-entering progress mode
        on each of those would keep snapping a filling bar back to empty.
        """
        self._generating_prompt_id = prompt_id if generating else None
        if generating == self._generating:
            return
        self._generating = generating
        self._cancel_btn.setVisible(generating)
        if generating:
            self._generate_btn.start()
        else:
            self._generate_btn.finish(enabled=self._can_generate())

    def use_random_seed(self):
        """Switch this config's seed(s) to Random.

        Called when the user accepts the "already generated" dialog's offer of a
        fresh seed: the choice to stop pinning that seed sticks, so a re-Generate
        (even after cancelling the first attempt) draws a new seed instead of
        reproducing the old one and re-asking.
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

    def _recent_matching_row(self) -> dict | None:
        """The newest saved generation in this tab's settings folder, or None."""
        rows = self._db.list_generations()  # newest first
        index = build_image_config_index([r for r in rows if media_type_of_row(r) == "image"])
        matching = rows_in_settings(rows, self.settings_key(), index)
        return matching[0] if matching else None

    def seed_strip(self, prompt_ids):
        """Seed this tab's strip with a settings folder when it opens from one.

        An accumulating history: whatever folder the tab was seeded with plus
        every generation it produces after — including runs whose settings no
        longer match the current form, so tweak-and-regenerate stays visible.
        """
        self._strip_ids = list(prompt_ids)
        self._strip.show_generations(self._strip_ids)

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
        """The tab title: the user's custom name, else the model + gallery folder."""
        if self._custom_title:
            return self._custom_title
        params = self._param_form.get_values_static() if self._param_form else {}
        return config_tab_title(self._workflow_combo.currentData(), params)

    def set_custom_title(self, name: str):
        """Pin a user-chosen tab name that overrides the auto gallery-folder name."""
        self._custom_title = name
        self._emit_title()

    def custom_title(self) -> str | None:
        """The user-set tab name, or ``None`` when the title is auto-derived.

        Distinct from :meth:`title`, which always returns a displayable string;
        this reports only an explicit rename, for session persistence.
        """
        return self._custom_title

    def prefill(self, workflow_name: str, params: dict):
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

    # --- displaying a saved generation (the browsed selection) ----------------

    def show_saved_generation(self, row: dict, image_rows: list[dict]):
        """Display a browsed generation in this tab: seed the editable form with
        its settings, show its output in the preview, and reveal the info for its
        media type (an image's animations, a video's source-image tile + Evolver).

        The form is seeded first so its recent-preview autoshow doesn't override
        the selection's own output. A workflow the app can't rebuild leaves the
        form as it was but still shows the preview and info.

        Pointing the tab at someone else's generation ends its claim on the runs
        it launched: the bar would otherwise sit mid-run over a picture that has
        nothing to do with it, and its Cancel would stop something off screen.
        """
        self.forget_launched()
        workflow_name = row.get("workflow_name", "")
        if workflow_name in WORKFLOW_REGISTRY:
            self.prefill(workflow_name, merge_denormalized(row))
        # Prefill's autoshow just set _displayed_row to this tab's recent result; the
        # browsed selection is what's actually on display, so _display_result (below)
        # overrides it.
        self._display_result(row, image_rows)

    def show_completed_result(self, row: dict, image_rows: list[dict]):
        """Show a generation this tab's own Generate just produced: swap the live
        preview for the saved output and reveal its footer, leaving the form exactly
        as the user left it.

        Unlike :meth:`show_saved_generation`, the form is not re-seeded — the tab
        already holds the settings that made this result, and the user may have kept
        editing the next prompt while the run was in flight. Re-seeding here would
        wipe those edits, so the completed result touches only the preview and info.
        """
        self._display_result(row, image_rows)

    def _display_result(self, row: dict, image_rows: list[dict]):
        """Point the preview and footer at ``row`` — the shared tail of showing a
        generation, whether freshly browsed or just completed. The form is left
        untouched; :meth:`show_saved_generation` seeds it first, before this runs."""
        self._displayed_row = row
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is not None:
            self._preview.show_media(*preview)  # after any prefill, so it wins over autoshow
            self._preview.set_draggable_id(row["prompt_id"])  # its preview drags onto combine
        else:
            self._preview.clear()
        self._show_footer(row, image_rows, preview)
        self.displayed_changed.emit()  # the view reconciles OSR2 driving off this

    def _hide_footer(self):
        """Hide every info/action element that belongs only to a saved generation —
        the state of a blank tab, or one whose preview is a bare autoshow rather than
        an explicit selection."""
        self._metadata_block.hide()
        self._versions.hide()
        self._pending_enhancement = None  # nothing on display to be enhancing
        self._source_tile.clear()
        self._animated_strip.hide()
        self._folder_btn.hide()
        self._evolver_btn.hide()

    def _show_footer(self, row: dict, image_rows: list[dict], preview):
        """Reveal the info and actions for the generation on display: the read-only
        metadata block for every selection, the source-image tile + Evolver for a
        video, and the animations strip for an image. ``preview`` is the already-
        resolved ``(path, media_type)`` (or ``None``), so Evolver keys off the same
        on-disk lookup."""
        # Only files no version claims are left for this block, which for an
        # image is usually none of them — so it shows only when it has content
        # rather than opening a bare gap above the form.
        self._metadata_block.setVisible(self._metadata_block.show_row(row))
        self._refresh_versions()
        # Any saved generation has a containing folder to open — except a deleted
        # one, whose folder it left when its row did. Everything else about it is
        # still here to look at; there is just nowhere to go.
        self._folder_btn.setVisible(row.get("deleted_at") is None)
        self._animated_strip.show_videos(self._animated_items(row))  # hides itself when empty
        self._show_source_tile(row, image_rows)
        self._update_evolver_button(preview)

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
        """
        if pending == self._pending_enhancement:
            return
        was_running = self._pending_enhancement is not None
        self._pending_enhancement = pending
        if pending is not None:
            frame = pending[1]
            if frame:
                self._preview.show_frame(frame)
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

    def _show_source_tile(self, row: dict, image_rows: list[dict]):
        """Reveal the source-image tile when this row is a video built on a known
        image generation, else hide it. The tile shows that image's thumbnail and
        filename and navigates to it on click."""
        source_id = find_source_image_id(row, image_rows)
        source_row = next(
            (r for r in image_rows if r.get("prompt_id") == source_id), None
        ) if source_id else None
        if source_row is None:
            self._source_tile.clear()
            return
        files = row_output_files(source_row)
        filename = files[0]["filename"] if files else ""
        self._source_tile.show_source(source_id, source_row.get("thumbnail_path"), filename)

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
