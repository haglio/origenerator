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
    animated_preview_path, build_image_config_index, config_tab_title,
    find_source_image_id, media_type_of_row, resolve_preview, row_output_files,
    rows_in_settings, settings_signature, videos_from_source_image,
)
from origenerator.generation_config import ConfigSnapshot, merge_denormalized
from origenerator.gui.animated_strip import AnimatedVideoStrip
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
    """

    title_changed = pyqtSignal(str)     # current tab title
    strip_activated = pyqtSignal(str)   # a strip thumbnail was clicked (prompt_id)
    source_activated = pyqtSignal(str)      # the source-image tile was clicked (prompt_id)
    animated_activated = pyqtSignal(str)    # an animation tile was clicked (prompt_id)
    containing_folder_requested = pyqtSignal(str)  # "Go to folder" clicked (prompt_id)
    generate_requested = pyqtSignal(str, dict)  # Generate clicked: (workflow_name, form params)
    cancel_requested = pyqtSignal()         # Cancel clicked: stop this config's in-flight run
    displayed_changed = pyqtSignal()        # the shown generation changed (drive reconcile cue)
    fullscreen_opened = pyqtSignal(object)  # the preview popped a video open fullscreen

    def __init__(self, client: ComfyUIClient | None, db: Database, parent=None):
        super().__init__(parent)
        self._client = client                        # None in a read-only gallery: the form shows, but Generate is off
        self._db = db
        self._custom_title: str | None = None        # user-set name; overrides the auto title
        self._strip_ids: list[str] = []               # this tab's strip: seeded folder + its own runs, newest first
        self._param_form: ParamForm | None = None
        self._generating = False                       # a run this tab launched is in flight (drives the progress button)
        self._displayed_row: dict | None = None        # a saved generation this tab is showing (footer visible); None when blank
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
        self._preview.fullscreen_opened.connect(self.fullscreen_opened)  # → view drives it
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
        header.addWidget(QLabel("Workflow:"))
        self._workflow_combo = NoWheelComboBox()
        for key, wf in WORKFLOW_REGISTRY.items():
            self._workflow_combo.addItem(wf.display_name, key)
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
        body.addStretch(1)  # push the related-media tiles below to the bottom

        # The displayed generation's related media, at the bottom of the scroll just
        # above the buttons: a clickable source-image tile for a video, or the
        # "animated in" strip for an image. Mutually exclusive; both hidden when the
        # tab isn't showing a saved generation.
        self._source_tile = SourceImageTile()
        self._source_tile.activated.connect(self.source_activated)
        body.addWidget(self._source_tile)
        self._animated_strip = AnimatedVideoStrip()
        self._animated_strip.video_activated.connect(self.animated_activated)
        body.addWidget(self._animated_strip)

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

        if self._client is None:
            self._generate_btn.setEnabled(False)  # nothing to run against
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
        """Fill the Generate button with the run's progress while this tab's re-roll
        is in flight. Generation is serial (one GPU), so the running job is this
        tab's whenever it's the one marked generating."""
        if self._generating:
            self._generate_btn.set_progress(value, max_val)

    def _on_go_to_folder(self):
        """Ask the gallery to open the displayed generation's own folder."""
        if self._displayed_row:
            self.containing_folder_requested.emit(self._displayed_row["prompt_id"])

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
            self._install_form(ParamForm(wf.param_definitions(), size_deriver=deriver))
            self._form_workflow_key = key
            defaults = wf.default_params()
            carried = {
                k: v for k, v in edited.items()
                if k in defaults and v != defaults[k]
            }
            if carried:
                self._param_form.set_values(carried)
        self._refresh_estimate()
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

    def _install_form(self, form: ParamForm):
        """Swap the workflow's ParamForm into the form host inside the scroll,
        discarding the previous one. The form lives in the shared scroll so it moves
        with the info above it, not boxed in a separate scroll of its own.

        The old form is detached from its parent at once (not just scheduled for
        deletion), so it leaves the screen immediately instead of lingering under
        the new form until the event loop next spins."""
        if self._param_form is not None:
            self._form_host_box.removeWidget(self._param_form)
            self._param_form.setParent(None)
            self._param_form.deleteLater()
        self._param_form = form
        self._param_form.changed.connect(self._emit_title)
        self._form_host_box.addWidget(self._param_form)

    def _emit_title(self):
        self.title_changed.emit(self.title())

    def _refresh_estimate(self):
        """Show how long this workflow typically takes, from its recent runs."""
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
        durations = self._db.recent_durations(wf.name) if wf else []
        self._estimate_label.setText(f"Typical time: {estimate_label(durations)}")

    def _on_generate(self):
        """Ask the gallery to generate this config — a re-roll of its settings folder.

        A Generate is conceptually a gallery re-roll: it emits the form's workflow
        and values (a Random seed already re-rolled by :meth:`ParamForm.get_values`)
        as :attr:`generate_requested`, and the gallery launches the job in the
        folder's own re-roll slot and navigates there. The panel keeps only the
        form-level guard that an image workflow has its input picked.
        """
        if self._client is None or self._generating:
            return  # nothing to run against, or a run is already in flight
        key = self._workflow_combo.currentData()
        if not key or key not in WORKFLOW_REGISTRY:
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

    def set_generating(self, generating: bool):
        """Reflect whether a run of this config's folder is in flight.

        While it is, Cancel shows and the Generate button switches to progress mode
        (filling as the run advances) so it can't be relaunched over; when it ends,
        Generate returns — still disabled in a read-only gallery with no client.
        """
        self._generating = generating
        self._cancel_btn.setVisible(generating)
        if generating:
            self._generate_btn.start()
        else:
            self._generate_btn.finish(enabled=self._client is not None)

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
        # Switch to the matching workflow if found
        for i in range(self._workflow_combo.count()):
            if self._workflow_combo.itemData(i) == workflow_name:
                self._workflow_combo.setCurrentIndex(i)
                break
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
        """
        workflow_name = row.get("workflow_name", "")
        if workflow_name in WORKFLOW_REGISTRY:
            self.prefill(workflow_name, merge_denormalized(row))
        # Prefill's autoshow just set _displayed_row to this tab's recent result; the
        # browsed selection is what's actually on display, so it wins.
        self._displayed_row = row
        preview = resolve_preview(row, COMFYUI_OUTPUT_DIR)
        if preview is not None:
            self._preview.show_media(*preview)  # after prefill, so it wins over autoshow
        else:
            self._preview.clear()
        self._show_footer(row, image_rows, preview)
        self.displayed_changed.emit()  # the view reconciles OSR2 driving off this

    def _hide_footer(self):
        """Hide every info/action element that belongs only to a saved generation —
        the state of a blank tab, or one whose preview is a bare autoshow rather than
        an explicit selection."""
        self._metadata_block.hide()
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
        self._metadata_block.show_row(row)
        self._metadata_block.show()
        self._folder_btn.show()  # any saved generation has a containing folder to open
        self._animated_strip.show_videos(self._animated_items(row))  # hides itself when empty
        self._show_source_tile(row, image_rows)
        self._update_evolver_button(preview)

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
