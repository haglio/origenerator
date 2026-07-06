"""The gallery's image + video combine panel, sitting under the TOC folder tree.

Drop an image into the top slot, then supply a *recipe* one of two ways: drop a
specific i2v video, or pick an act from the category dropdown and let the app find
a fitting past video for you. Either way, Generate re-runs that recipe on the
dropped image. The panel is pure UI: it holds the two :class:`DropSlot`s, the
category dropdown and a Generate button, and reports the request through
:attr:`generate_requested` (a dropped video) or :attr:`category_requested` (a
picked act) — the view owns the database, the predicates that gate each slot, the
category→recipe routing, and the generation itself.
"""

from collections.abc import Callable

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton, QComboBox
from PyQt6.QtCore import pyqtSignal

from origenerator.gui.drop_slot import DropSlot
from origenerator.recipe_match import CATEGORIES

# The dropdown's leading neutral option: no act chosen, so a dropped video is used
# instead. Selecting it clears a previously-picked act (there is no other way back).
_NO_CATEGORY_LABEL = "Pick a move…"


class CombinePanel(QWidget):
    """Image slot + a recipe (dropped video or picked category) + Generate."""

    generate_requested = pyqtSignal(str, str)   # (image prompt_id, video prompt_id): a dropped recipe
    category_requested = pyqtSignal(str, str)   # (image prompt_id, category): let the app find the recipe

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

        # The video part's fast path: pick an act and the view finds a fitting past
        # video for you. A selectable neutral option leads the list (index 0, the
        # default), so no act is forced — and picking it again is how you clear an act
        # and bring the video slot back (see _sync).
        self._category = QComboBox()
        self._category.addItem(_NO_CATEGORY_LABEL)
        self._category.addItems(CATEGORIES)
        self._category.setToolTip(
            "Pick an act and Generate — the app reuses a fitting past video's recipe "
            f"on the dropped image. Leave it on “{_NO_CATEGORY_LABEL}” to drop a "
            "specific video instead."
        )
        self._category.currentIndexChanged.connect(self._sync)

        # The video part: both ways to supply the recipe, kept in one container so the
        # dropdown reads as belonging to the video side (not the image) — pick an act,
        # or drop a video below it. A picked act hides the slot (see _sync).
        self._video_part = QWidget()
        video_box = QVBoxLayout(self._video_part)
        video_box.setContentsMargins(0, 0, 0, 0)
        video_box.setSpacing(2)  # the dropdown hugs its slot as one unit
        video_box.addWidget(self._category)
        video_box.addWidget(self.video_slot)

        self._generate_btn = QPushButton("Generate")
        self._generate_btn.clicked.connect(self._emit)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        heading = QLabel("Combine")
        heading.setObjectName("combineHeading")
        heading.setToolTip(
            "Re-run a video's recipe on the dropped image: drop a video, or pick an act."
        )
        layout.addWidget(heading)
        layout.addWidget(self.image_slot)
        layout.addSpacing(8)  # set the video part apart from the image slot above it
        layout.addWidget(self._video_part)
        layout.addWidget(self._generate_btn)
        self._sync()

    # --- category ---------------------------------------------------------

    def selected_category(self) -> str:
        """The picked act, or "" when the neutral option (index 0) is selected."""
        index = self._category.currentIndex()
        return self._category.currentText() if index >= 1 else ""

    def set_category(self, category: str):
        """Select ``category`` (a member of ``CATEGORIES``), or the neutral option
        for anything else."""
        index = self._category.findText(category)
        self._category.setCurrentIndex(index if index >= 1 else 0)

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
        """Generate is live once a source image sits and a recipe is chosen — either
        by picking an act or by dropping a video. A picked act supersedes any dropped
        video, so the now-unused slot is hidden while an act is selected."""
        category = self.selected_category()
        self.video_slot.setVisible(not category)
        has_recipe = bool(category or self.video_slot.current_id())
        self._generate_btn.setEnabled(bool(self.image_slot.current_id()) and has_recipe)

    def _emit(self):
        image_id = self.image_slot.current_id()
        if not image_id:
            return
        category = self.selected_category()
        if category:  # a picked act takes precedence over any dropped video
            self.category_requested.emit(image_id, category)
        elif self.video_slot.current_id():
            self.generate_requested.emit(image_id, self.video_slot.current_id())
