"""Drives the gallery's info pane — the right-hand column that shows the selected
generation: its preview, metadata, the videos an image was animated into, and the
Reuse / Send-to-Evolver actions.

Holds references to the pane's widgets (the GalleryView builds and lays them out)
and owns the row on display plus everything that populates it, so that concern
lives here rather than in the view. It reports the two things the view must act on
as signals: a source link the user followed (``link_activated``) and a request to
reuse the selection's parameters (``reuse_requested``). A running re-roll borrows
the pane through :meth:`show_generating` / :meth:`show_frame`; a saved generation
takes it back through :meth:`show_generation`.
"""

import logging
from pathlib import Path

from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtWidgets import QMessageBox

from origenerator import evolver_export, gallery, timing
from origenerator.config import (
    COMFYUI_OUTPUT_DIR, EVOLVER_INBOX_DIR, EVOLVER_SOURCE, THUMB_DIR,
)
from origenerator.generation_config import merge_denormalized
from origenerator.workflows import WORKFLOW_REGISTRY

logger = logging.getLogger(__name__)

_ANIMATED_STRIP_LIMIT = 8  # most animation previews shown for one image at once


def _is_reusable_workflow(workflow_name) -> bool:
    """Whether the app can rebuild this workflow from its template.

    The single gate for both Reuse Parameters and the gallery re-roll, so the
    re-roll '+' appears exactly where Reuse works (a re-roll is just Reuse with
    a random seed).
    """
    return (workflow_name or "") in WORKFLOW_REGISTRY


class InfoPaneController(QObject):
    """Populates the info pane's widgets from the generation on display."""

    link_activated = pyqtSignal(str)          # a followed source/animation link (prompt_id)
    reuse_requested = pyqtSignal(str, dict)   # workflow_name, params to rebuild

    def __init__(self, db, *, preview, meta_panel, meta_title, estimate_label,
                 animated_strip, reuse_btn, reuse_wrap, evolver_btn, parent=None):
        super().__init__(parent)
        self._db = db
        self._preview = preview
        self._meta_panel = meta_panel
        self._meta_title = meta_title
        self._estimate_label = estimate_label
        self._animated_strip = animated_strip
        self._reuse_btn = reuse_btn
        self._reuse_wrap = reuse_wrap
        self._evolver_btn = evolver_btn
        self._row: dict | None = None  # the saved generation on display, if any
        self._strip_pid: str | None = None  # generation whose animations the strip shows
        # An i2v's input_image links to the image it came from; a strip clip opens
        # the video it names. Both surface as a source link the view follows.
        meta_panel.link_activated.connect(self.link_activated)
        animated_strip.video_activated.connect(self.link_activated)
        reuse_btn.clicked.connect(self._on_reuse)
        evolver_btn.clicked.connect(self._on_send_to_evolver)

    def current_row(self) -> dict | None:
        """The saved generation on display, or ``None`` (idle, or mirroring a live
        re-roll frame rather than a saved generation)."""
        return self._row

    def show_generation(self, row: dict, image_rows: list[dict]):
        """Fill the pane with a saved generation: its preview, metadata, the videos
        it was animated into, and the Reuse/Evolver buttons' state."""
        self._row = row
        reusable = _is_reusable_workflow(row.get("workflow_name"))
        self._reuse_btn.setEnabled(reusable)
        self._reuse_wrap.setToolTip(
            "" if reusable else
            "This workflow isn't built into the app yet — ask Claude to "
            "implement it if you want to reuse its parameters."
        )
        # Resolve the preview once and share it: both the player and the
        # Send-to-Evolver button key off the same on-disk file.
        preview = gallery.resolve_preview(row, COMFYUI_OUTPUT_DIR)
        self._update_evolver_button(preview)
        self._render_preview(preview)
        self._meta_title.setText(f"{row['workflow_name']} ({row['workflow_version']})")
        self._estimate_label.setText(
            f"Typical time: {timing.estimate_label(self._db.recent_durations(row['workflow_name']))}"
        )
        source_id = gallery.find_source_image_id(row, image_rows)
        self._meta_panel.show_row(row, source_id)
        self._update_animated_strip(row)

    def clear(self):
        """Reset the pane to its idle 'select a generation' state."""
        self._row = None
        self._reuse_btn.setEnabled(False)
        self._reuse_wrap.setToolTip("")
        self._update_evolver_button(None)
        self._meta_title.setText("Select a generation")
        self._estimate_label.clear()
        self._meta_panel.clear()
        self._preview.clear()

    def reset_animated_strip(self):
        """Empty the 'Animated in' strip and forget which image it last showed, so
        the next selection rebuilds it — used when a rebuild leaves nothing on
        screen to select."""
        self._strip_pid = None
        self._animated_strip.show_videos([])

    def show_generating(self, frame: bytes | None):
        """Point the pane at a running re-roll: its last ``frame`` (or a 'waiting'
        note, never the idle placeholder), with the saved-generation actions off."""
        self._row = None
        self._reuse_btn.setEnabled(False)
        self._reuse_wrap.setToolTip("")
        self._update_evolver_button(None)  # a running re-roll isn't a saved video
        self._meta_title.setText("Generating a new variation…")
        self._estimate_label.clear()
        self._meta_panel.clear()
        if frame:
            self._preview.show_frame(frame)
        else:
            self._preview.show_message("Waiting for preview…")

    def show_frame(self, data: bytes):
        """Mirror a re-roll's live frame into the preview."""
        self._preview.show_frame(data)

    def _render_preview(self, preview):
        """Play/show the already-resolved ``(path, media_type)``, or clear when
        ``None`` (nothing displayable resolved for the selection)."""
        if preview is None:
            self._preview.clear()
        else:
            self._preview.show_media(*preview)

    def _update_evolver_button(self, preview):
        """Reflect the selection on the Send-to-Evolver button.

        Shown only when the selection is a video with a file on disk; Evolver is
        a video pipeline, so for an image or a missing file the button is hidden
        rather than shown disabled. A video already sent shows a persistent,
        disabled "Sent ✓" so the gallery remembers the handoff across selections
        and sessions (the flag is read from the row, which the DB persists).

        ``preview`` is the selection's resolved ``(path, media_type)``, or
        ``None`` when nothing displayable is selected.
        """
        is_video = preview is not None and preview[1] == "video"
        self._evolver_btn.setVisible(is_video)
        if not is_video:
            return
        already_sent = bool(self._row and self._row.get("evolver_exported_at"))
        self._evolver_btn.setText("Sent to Evolver ✓" if already_sent else "Send to Evolver")
        self._evolver_btn.setEnabled(not already_sent)

    def _exportable_video_path(self) -> Path | None:
        """The on-disk video file backing the current selection, or ``None`` when
        the selection isn't a video (or its file is missing) and can't be sent.
        Resolved fresh at send time, so a file deleted since selection is caught."""
        if not self._row:
            return None
        preview = gallery.resolve_preview(self._row, COMFYUI_OUTPUT_DIR)
        if preview is None or preview[1] != "video":
            return None
        return preview[0]

    def _on_send_to_evolver(self):
        """Copy the selected video into Evolver's inbox and remember the send.

        Re-checks the persisted flag (not just the button's disabled state) so
        the handoff can't be repeated, mirroring how reuse re-gates. The copy
        lands in another app's inbox with no other visible result here, so a
        failure must surface loudly; success is remembered on the button.
        """
        if not self._row or self._row.get("evolver_exported_at"):
            return
        path = self._exportable_video_path()
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
        prompt_id = self._row["prompt_id"]
        self._db.mark_evolver_exported(prompt_id)
        # Re-read so the row (and thus the button) reflects the persisted send.
        self._row = self._db.get_generation(prompt_id) or self._row
        self._update_evolver_button((path, "video"))

    def _on_reuse(self):
        # Gate on reusability here, not just via the button's enabled state, so
        # the double-click path is inert for a workflow the app can't rebuild.
        if not self._row or not _is_reusable_workflow(self._row.get("workflow_name")):
            return
        params = merge_denormalized(self._row)
        if not params:
            return
        workflow_name = self._row.get("workflow_name", "")
        self.reuse_requested.emit(workflow_name, params)

    def _update_animated_strip(self, row: dict):
        """Show the videos an image was animated into. Rebuilt only when the
        selection changes, so a poll's re-selection doesn't restart the previews
        every tick."""
        if row["prompt_id"] == self._strip_pid:
            return
        self._strip_pid = row["prompt_id"]
        self._animated_strip.show_videos(self._animated_items(row))

    def _animated_items(self, row: dict) -> list[tuple]:
        """(prompt_id, looping-preview path, still path) for each video this image
        was animated into — empty for anything but an image with animations."""
        if gallery.media_type_of_row(row) != "image":
            return []
        videos = gallery.videos_from_source_image(row, self._video_rows())
        if len(videos) > _ANIMATED_STRIP_LIMIT:
            logger.info("Image %s has %d animations; showing the first %d",
                        row["prompt_id"], len(videos), _ANIMATED_STRIP_LIMIT)
        return [
            (v["prompt_id"], gallery.animated_preview_path(v, COMFYUI_OUTPUT_DIR, THUMB_DIR),
             v.get("thumbnail_path"))
            for v in videos[:_ANIMATED_STRIP_LIMIT]
        ]

    def _video_rows(self) -> list[dict]:
        return [r for r in self._db.list_generations() if gallery.media_type_of_row(r) == "video"]
