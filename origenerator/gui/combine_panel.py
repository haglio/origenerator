"""The gallery's image + video combine panel, sitting under the TOC folder tree.

Drop an image into the top slot and an i2v video into the bottom slot, then click
Generate to re-run that video's recipe on the dropped image. The panel is pure UI:
it holds the two :class:`DropSlot`s and a Generate button, and reports the chosen
pair through :attr:`generate_requested` — the view owns the database, the predicates
that gate each slot, and the generation itself.
"""

from collections.abc import Callable

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtCore import pyqtSignal

from origenerator.gui.drop_slot import DropSlot


class CombinePanel(QWidget):
    """Two kind-gated drop slots and a Generate button; emits the chosen pair."""

    generate_requested = pyqtSignal(str, str)  # image prompt_id, video prompt_id

    def __init__(
        self,
        image_accepts: Callable[[str], bool],
        video_accepts: Callable[[str], bool],
        preview: Callable[[str], tuple[str | None, str | None]],
        parent=None,
    ):
        super().__init__(parent)
        self.image_slot = DropSlot("image", image_accepts, preview, "Drop an image")
        self.video_slot = DropSlot("video", video_accepts, preview, "Drop an I2V video")
        self.image_slot.changed.connect(self._sync)
        self.video_slot.changed.connect(self._sync)

        self._generate_btn = QPushButton("Generate")
        self._generate_btn.clicked.connect(self._emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        heading = QLabel("Combine")
        heading.setObjectName("combineHeading")
        heading.setToolTip(
            "Re-run the dropped video's recipe on the dropped image, then Generate."
        )
        layout.addWidget(heading)
        layout.addWidget(self.image_slot)
        layout.addWidget(self.video_slot)
        layout.addWidget(self._generate_btn)
        self._sync()

    def show_drop_candidates(self, prompt_id: str):
        """Light whichever slot accepts a now-dragging item, so its target is
        obvious the instant the drag begins — before the cursor gets there."""
        self.image_slot.set_candidate(self.image_slot.accepts(prompt_id))
        self.video_slot.set_candidate(self.video_slot.accepts(prompt_id))

    def clear_drop_candidates(self):
        """Drop the drag-target highlight from both slots (the drag ended)."""
        self.image_slot.set_candidate(False)
        self.video_slot.set_candidate(False)

    def _sync(self):
        """Generate is live only once both a source image and a recipe video sit."""
        self._generate_btn.setEnabled(
            bool(self.image_slot.current_id() and self.video_slot.current_id())
        )

    def _emit(self):
        image_id, video_id = self.image_slot.current_id(), self.video_slot.current_id()
        if image_id and video_id:
            self.generate_requested.emit(image_id, video_id)
