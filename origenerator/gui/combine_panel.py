"""The gallery's image + video combine panel, sitting under the TOC folder tree.

Drop an image into the top slot, then supply a *recipe* one of two ways — side by
side in the video part: pick an act from the category dropdown and let the app find
a fitting past video for you, or drop a specific i2v video for a custom action. The
two are mutually exclusive: picking an act clears a dropped video (and relabels the
slot as the override path), and dropping a video wipes the dropdown back to "-".
Either way, two buttons act on the chosen recipe: Generate re-runs it on the dropped
image now, while Open in generator hands it to a generate tab to edit before running.

Acts the gallery holds no video of are greyed out (:meth:`CombinePanel.set_available_categories`),
so the dropdown only ever offers what a recipe can actually be mined for.

The panel is pure UI: it holds the two :class:`DropSlot`s, the category dropdown and
the two buttons, and reports the request through one of four signals — a dropped
video versus a picked act, crossed with run-now (:attr:`generate_requested` /
:attr:`category_requested`) versus edit-first (:attr:`open_requested` /
:attr:`open_category_requested`). The view owns the database, the slot predicates,
the category→recipe routing, and both the generation and the generator tab.
"""

from collections.abc import Callable, Collection

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.drop_slot import DropSlot
from origenerator.recipe_match import CATEGORIES

# The dropdown's leading neutral option: no act chosen, so a dropped video is used.
_NEUTRAL_LABEL = "-"
# The video slot's prompt when neutral (drop a video to use its recipe) versus when
# an act is picked (the slot becomes the override — drop a video for a custom action).
_DROP_PLACEHOLDER = "Drop an I2V video"
_OVERRIDE_PLACEHOLDER = "use custom action from video"


class CombinePanel(QWidget):
    """Image slot + a recipe (dropped video or picked act) + Generate."""

    generate_requested = pyqtSignal(str, str)   # (image prompt_id, video prompt_id): a dropped recipe
    category_requested = pyqtSignal(str, str)   # (image prompt_id, category): let the app find the recipe
    # The same two recipe sources, but bound for the generator to edit rather than to run.
    open_requested = pyqtSignal(str, str)           # (image prompt_id, video prompt_id): a dropped recipe
    open_category_requested = pyqtSignal(str, str)  # (image prompt_id, category): let the app find the recipe

    def __init__(
        self,
        image_accepts: Callable[[str], bool],
        video_accepts: Callable[[str], bool],
        preview: Callable[[str], tuple[str | None, str | None]],
        parent=None,
    ):
        super().__init__(parent)
        self.image_slot = DropSlot("image", image_accepts, preview, "Drop an image")
        self.video_slot = DropSlot("video", video_accepts, preview, _DROP_PLACEHOLDER)
        self.image_slot.changed.connect(self._sync)
        self.video_slot.changed.connect(self._on_video_changed)

        # The video part's fast path: pick an act and the view finds a fitting past
        # video for you. A neutral "-" leads the list (index 0, the default) so no act
        # is forced; picking it again clears an act.
        self._category = QComboBox()
        self._category.addItem(_NEUTRAL_LABEL)
        self._category.addItems(CATEGORIES)
        self._category.setToolTip(
            "Pick an act and Generate — the app reuses a fitting past video's recipe "
            "on the dropped image. Or drop a specific video for a custom action instead."
        )
        self._category.currentIndexChanged.connect(self._on_category_changed)

        # The video part: the two ways to supply the recipe, side by side in one
        # container so the dropdown reads as belonging to the video side, not the image.
        self._video_part = QWidget()
        video_box = QHBoxLayout(self._video_part)
        video_box.setContentsMargins(0, 0, 0, 0)
        video_box.setSpacing(6)
        video_box.addWidget(self._category, 1)  # each takes half the video part's width
        video_box.addWidget(self.video_slot, 1)

        # Two ways to act on the same chosen recipe: run it now, or open it in the
        # generator to tweak first. Both gate on the same "image + recipe" readiness.
        self._generate_btn = QPushButton("Generate")
        self._generate_btn.clicked.connect(self._emit)
        self._open_btn = QPushButton("Open in generator")
        self._open_btn.setToolTip(
            "Load this combination into a generate tab to edit before running it."
        )
        self._open_btn.clicked.connect(self._emit_open)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        heading = QLabel("Combine")
        heading.setObjectName("combineHeading")
        heading.setToolTip(
            "Re-run a video's recipe on the dropped image: pick an act, or drop a video."
        )
        layout.addWidget(heading)
        layout.addWidget(self.image_slot)
        layout.addSpacing(8)  # set the video part apart from the image slot above it
        layout.addWidget(self._video_part)
        layout.addWidget(self._generate_btn)
        layout.addWidget(self._open_btn)
        self._sync()

    # --- category ---------------------------------------------------------

    def selected_category(self) -> str:
        """The picked act, or "" when the neutral "-" option (index 0) is selected."""
        index = self._category.currentIndex()
        return self._category.currentText() if index >= 1 else ""

    def set_category(self, category: str):
        """Select ``category`` (a member of ``CATEGORIES``), or the neutral option
        for anything else."""
        index = self._category.findText(category)
        self._category.setCurrentIndex(index if index >= 1 else 0)

    def set_available_categories(self, available: Collection[str]):
        """Grey out every act the gallery holds no video of — there's no recipe to mine
        for it, so offering it could only ever answer "no recipe yet". A disabled item
        says why on hover. The neutral "-" is never greyed."""
        model = self._category.model()
        for index in range(1, self._category.count()):
            act = self._category.itemText(index)
            usable = act in available
            model.item(index).setEnabled(usable)
            self._category.setItemData(
                index,
                "" if usable else f"No past “{act}” video to base a recipe on yet",
                Qt.ItemDataRole.ToolTipRole,
            )

    def show_drop_candidates(self, prompt_id: str):
        """Light whichever slot accepts a now-dragging item, so its target is
        obvious the instant the drag begins — before the cursor gets there."""
        self.image_slot.set_candidate(self.image_slot.accepts(prompt_id))
        self.video_slot.set_candidate(self.video_slot.accepts(prompt_id))

    def clear_drop_candidates(self):
        """Drop the drag-target highlight from both slots (the drag ended)."""
        self.image_slot.set_candidate(False)
        self.video_slot.set_candidate(False)

    # --- mutual exclusion: an act and a dropped video never coexist -------

    def _on_category_changed(self):
        """A picked act supersedes a dropped video: clear the slot and relabel it as
        the override path. Blanking back to "-" restores the plain drop prompt."""
        if self.selected_category():
            self.video_slot.clear()
            self.video_slot.set_placeholder(_OVERRIDE_PLACEHOLDER)
        else:
            self.video_slot.set_placeholder(_DROP_PLACEHOLDER)
        self._sync()

    def _on_video_changed(self):
        """A dropped video supersedes a picked act: wipe the dropdown back to "-"."""
        if self.video_slot.current_id():
            self._category.setCurrentIndex(0)
        self._sync()

    def _sync(self):
        """Both actions go live once a source image sits and a recipe is chosen —
        either by picking an act or by dropping a video. The video part keeps its
        size throughout; neither control ever hides the other."""
        has_recipe = bool(self.selected_category() or self.video_slot.current_id())
        ready = bool(self.image_slot.current_id()) and has_recipe
        self._generate_btn.setEnabled(ready)
        self._open_btn.setEnabled(ready)

    def _emit(self):
        """Generate: run the chosen recipe on the dropped image now."""
        self._dispatch(self.generate_requested, self.category_requested)

    def _emit_open(self):
        """Open in generator: hand the chosen recipe to a generate tab to edit first."""
        self._dispatch(self.open_requested, self.open_category_requested)

    def _dispatch(self, video_signal, category_signal):
        """Emit the chosen recipe on the pair of signals for the requested action: a
        picked act on ``category_signal``, else a dropped video on ``video_signal``."""
        image_id = self.image_slot.current_id()
        if not image_id:
            return
        category = self.selected_category()
        if category:
            category_signal.emit(image_id, category)
        elif self.video_slot.current_id():
            video_signal.emit(image_id, self.video_slot.current_id())
