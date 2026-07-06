import json
import logging
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QSplitter,
    QComboBox, QPushButton, QProgressBar, QScrollArea, QMessageBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator import evolver_export
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database
from origenerator.gallery import (
    animated_preview_path, build_image_config_index, config_tab_title,
    find_source_image_id, media_type_of_row, resolve_preview, rows_in_settings,
    settings_signature, videos_from_source_image,
)
from origenerator.generation_config import ConfigSnapshot, merge_denormalized
from origenerator.funscript import funscript_path_for, read_actions
from origenerator.gui.animated_strip import AnimatedVideoStrip
from origenerator.gui.no_wheel import NoWheelComboBox
from origenerator.gui.param_form import ParamForm
from origenerator.gui.preview_widget import PreviewWidget
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
    panel lays out two resizable panes itself — a main column with the preview over
    the settings and the Generate button, and this tab's own slim strip of past
    runs on the right. Clicking a strip thumbnail re-emits its prompt id via
    ``strip_activated`` so a container can open (or reuse) a tab for it. The preview
    is driven from outside: a browsed selection's output, a running re-roll's live
    frames, or this config's newest matching result when idle.

    Below the Generate button sits a footer that appears only while the tab is
    displaying a saved generation (:meth:`show_saved_generation`): for an image,
    the videos it was animated into; for a video, a link back to its source image,
    a Send-to-Evolver button, and a Drive-OSR2 toggle (when it has a funscript). A
    blank tab hides them all.
    """

    title_changed = pyqtSignal(str)     # current tab title
    strip_activated = pyqtSignal(str)   # a strip thumbnail was clicked (prompt_id)
    source_activated = pyqtSignal(str)      # the "from source image" link (prompt_id)
    animated_activated = pyqtSignal(str)    # a footer animation tile (prompt_id)
    generate_requested = pyqtSignal(str, dict)  # Generate clicked: (workflow_name, form params)
    displayed_changed = pyqtSignal()        # the shown generation changed (drive reconcile cue)

    def __init__(self, client: ComfyUIClient | None, db: Database, parent=None):
        super().__init__(parent)
        self._client = client                        # None in a read-only gallery: the form shows, but Generate is off
        self._db = db
        self._custom_title: str | None = None        # user-set name; overrides the auto title
        self._strip_ids: list[str] = []               # this tab's strip: seeded folder + its own runs, newest first
        self._param_form: ParamForm | None = None
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
        main_box.addWidget(self._preview, 3)
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
        main_box.addLayout(header)
        self._estimate_label = QLabel()
        self._estimate_label.setObjectName("estimateLabel")
        main_box.addWidget(self._estimate_label)
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        main_box.addWidget(self._scroll, 2)
        # A slim status line: the ComfyUI connection state, and the form-level guard
        # when a Generate is blocked. It never shows a running job's progress — that
        # lives in the gallery's re-roll tile and bottom bar, which own the run.
        self._progress = QProgressBar()
        self._progress.setTextVisible(True)
        main_box.addWidget(self._progress)
        self._show_ready()
        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton("Generate")
        self._generate_btn.setObjectName("generateBtn")
        self._generate_btn.clicked.connect(self._on_generate)
        btn_row.addStretch()
        btn_row.addWidget(self._generate_btn)
        main_box.addLayout(btn_row)

        # Footer: shown only while this tab is displaying a saved generation (see
        # show_saved_generation). A "‹ From source image" link for a video whose
        # start frame is a known generation; the "Animated in" strip for an image;
        # Send-to-Evolver and Drive-OSR2 for a video. All hidden on a fresh tab.
        self._source_link = QLabel()
        self._source_link.setTextFormat(Qt.TextFormat.RichText)
        self._source_link.setOpenExternalLinks(False)
        self._source_link.linkActivated.connect(self.source_activated)
        self._source_link.hide()
        main_box.addWidget(self._source_link)

        self._animated_strip = AnimatedVideoStrip()
        self._animated_strip.video_activated.connect(self.animated_activated)
        main_box.addWidget(self._animated_strip)

        self._evolver_btn = QPushButton("Send to Evolver")
        self._evolver_btn.setToolTip(
            "Copy this video into Evolver's inbox for sorting and upscaling."
        )
        self._evolver_btn.clicked.connect(self._on_send_to_evolver)
        self._evolver_btn.hide()  # shown only for a video the tab is displaying
        main_box.addWidget(self._evolver_btn)

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
        self._client.connected.connect(self._on_connected)
        self._client.disconnected.connect(self._on_disconnected)

    def teardown(self):
        """Disconnect from the shared client before the panel is destroyed."""
        if self._client is None:
            return  # never connected
        for signal, slot in (
            (self._client.connected, self._on_connected),
            (self._client.disconnected, self._on_disconnected),
        ):
            try:
                signal.disconnect(slot)
            except TypeError:
                pass

    def _on_connected(self):
        self._show_ready("Connected to ComfyUI")

    def _on_disconnected(self):
        self._show_ready("Disconnected")

    def _on_workflow_changed(self):
        key = self._workflow_combo.currentData()
        if key and key in WORKFLOW_REGISTRY:
            wf = WORKFLOW_REGISTRY[key]
            self._param_form = ParamForm(wf.param_definitions())
            self._param_form.changed.connect(self._emit_title)
            self._scroll.setWidget(self._param_form)
        self._refresh_estimate()
        self._emit_title()
        self.show_recent_preview()  # these settings' newest result, not a blank pane

    def _emit_title(self):
        self.title_changed.emit(self.title())

    def _refresh_estimate(self):
        """Show how long this workflow typically takes, from its recent runs."""
        key = self._workflow_combo.currentData()
        wf = WORKFLOW_REGISTRY.get(key)
        durations = self._db.recent_durations(wf.name) if wf else []
        self._estimate_label.setText(f"Typical time: {estimate_label(durations)}")

    def _show_ready(self, text: str = "Ready"):
        """Show a status message on the slim bar (connection state or a form guard)."""
        self._progress.setRange(0, 1)
        self._progress.setValue(0)
        self._progress.setFormat(text)

    def _on_generate(self):
        """Ask the gallery to generate this config — a re-roll of its settings folder.

        A Generate is conceptually a gallery re-roll: it emits the form's workflow
        and values (a Random seed already re-rolled by :meth:`ParamForm.get_values`)
        as :attr:`generate_requested`, and the gallery launches the job in the
        folder's own re-roll slot and navigates there. The panel keeps only the
        form-level guard that an image workflow has its input picked.
        """
        if self._client is None:
            return  # a read-only gallery: nothing to run against
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
            self._show_ready(
                f"Select an input image ({', '.join(missing_images)}) before generating."
            )
            return
        self.generate_requested.emit(key, params)

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
        drive follows whatever video is actually on screen, however it got there."""
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
        its settings, show its output in the preview, and reveal the footer for
        its media type (an image's animations, a video's source link + Evolver).

        The form is seeded first so its recent-preview autoshow doesn't override
        the selection's own output. A workflow the app can't rebuild leaves the
        form as it was but still shows the preview and footer.
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

    def _show_footer(self, row: dict, image_rows: list[dict], preview):
        """Populate and reveal the footer for the generation on display: the
        animations strip for an image, and the source link + Evolver + Drive-OSR2
        for a video. ``preview`` is the already-resolved ``(path, media_type)`` (or
        ``None``), so those buttons key off the same on-disk lookup."""
        self._animated_strip.show_videos(self._animated_items(row))  # hides itself when empty
        source_id = find_source_image_id(row, image_rows)
        if source_id is not None:
            self._source_link.setText(f'<a href="{source_id}">‹ From source image</a>')
            self._source_link.show()
        else:
            self._source_link.hide()
        self._update_evolver_button(preview)

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
        path = self._displayed_video_path()
        if path is None:
            return None
        actions = read_actions(funscript_path_for(path))
        if not actions:
            return None
        return path, self._preview.player(), actions

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
