"""The gallery's image + video combine panel, sitting under the TOC folder tree.

Drop an image into the top slot, then supply a *recipe* one of two ways — side by
side in the video part: pick an act from the category dropdown and let the app find
a fitting past video for you, or drop a specific i2v video for a custom action. A
dropped video shows in gray: it is here for its settings, not as a second picture
to be made. The two are mutually exclusive: picking an act clears a dropped video
and hides the slot until "(custom)" is picked again, and dropping a video wipes the
dropdown back to "(custom)".
Either way, two buttons act on the chosen recipe: Generate re-runs it on the dropped
image now, while “Edit…” hands it to a generate tab to change first.

Under the dropdown, a pair of radios says what the result is *for*: a full-length
video (the default), or a Genau clip — one complete cycle, looping. That choice
picks which recipes the act is answered from, so the dropdown's usable acts change
with it: an act only the video lane can answer greys out under Genau, and acts that
are no kind of cycle at all are not offered there.

Acts with nothing to answer a pick — no video to mine a recipe from and no curated
recipe in the content overlay — are greyed out
(:meth:`CombinePanel.set_available_categories`).

The panel is pure UI: it holds the two :class:`DropSlot`s, the category dropdown, the
intent radios and the two buttons, and reports what was asked for as one
:class:`CombineRequest` on :attr:`combine_requested` — which recipe (a dropped video
or a picked act), which lane, and whether the press was Generate or “Edit…”. Its
controller (:mod:`origenerator.gui.combine_controller`) owns the database, the slot
predicates, the category→recipe routing, and both the generation and the generator
tab.
"""
from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass

from origenerator.paths import ensure_shared_ui_on_path

# Before any shared_ui import: that checkout is a sibling on the path, not a
# dependency the launch interpreter has installed (see tests/test_sibling_imports).
ensure_shared_ui_on_path()

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import BUTTON_GAP, BUTTON_GROUP_GAP

from origenerator.gui.drop_slot import DropSlot
from origenerator.media import MediaType
from origenerator.recipe_match import CATEGORIES, GENAU, VIDEO

# The dropdown's leading neutral option: no act chosen, so a dropped video is used.
_NEUTRAL_LABEL = "(custom)"
_DROP_PLACEHOLDER = "Drop a video"


@dataclass(frozen=True)
class CombineRequest:
    """One press of Generate or “Edit…”: the picture, the recipe to run on it —
    a dropped video or a picked act, never both — the lane it is answered from,
    and whether it is bound for the generator rather than for a run now."""

    image_id: str
    video_id: str = ""
    category: str = ""
    intent: str = VIDEO
    edit_first: bool = False


class CombinePanel(QWidget):
    """Image slot + a recipe (dropped video or picked act) + an intent + Generate."""

    combine_requested = pyqtSignal(object)  # a CombineRequest: what was asked for
    intent_changed = pyqtSignal(str)  # the Video/Genau radio moved — regrey the acts
    item_activated = pyqtSignal(str)  # a slot's picture or clip was clicked (prompt_id)

    def __init__(
        self,
        image_accepts: Callable[[str], bool],
        video_accepts: Callable[[str], bool],
        preview: Callable[[str], tuple[str | None, str | None]],
        parent=None,
    ):
        super().__init__(parent)
        self.image_slot = DropSlot(MediaType.IMAGE, image_accepts, preview, "Drop an image")
        # Gray, always: the video in this slot is never what gets made — only the
        # settings the making follows. In color it reads as a second subject beside
        # the image, which is the one thing it is not.
        self.video_slot = DropSlot(MediaType.VIDEO, video_accepts, preview, _DROP_PLACEHOLDER,
                                   grayscale=True)
        room = self.video_slot.sizePolicy()
        room.setRetainSizeWhenHidden(True)
        self.video_slot.setSizePolicy(room)
        self.image_slot.changed.connect(self._sync)
        self.video_slot.changed.connect(self._on_video_changed)
        self.image_slot.activated.connect(self.item_activated)
        self.video_slot.activated.connect(self.item_activated)
        self._dropped: dict[str, str] = {}

        # The video part's fast path: pick an act and the view finds a fitting past
        # video for you. A neutral "(custom)" leads the list (index 0, the default) so
        # no act is forced; picking it again clears an act.
        self._category = QComboBox()
        self._category.addItem(_NEUTRAL_LABEL)
        self._category.addItems(CATEGORIES)
        self._category.setToolTip(
            "Pick an act and Generate — the app reuses a fitting past video's recipe "
            "on the dropped image. Or pick (custom) and drop a specific video instead."
        )
        self._category.currentIndexChanged.connect(self._on_category_changed)

        # The video part: the two ways to supply the recipe, side by side in one
        # container so the dropdown reads as belonging to the video side, not the image.
        self._video_part = QWidget()
        video_row = QHBoxLayout(self._video_part)
        video_row.setContentsMargins(0, 0, 0, 0)
        video_row.setSpacing(BUTTON_GAP)  # the family's gap inside a group
        video_row.addWidget(self._category, 1)  # each takes half the video part's width
        video_row.addWidget(self.video_slot, 1)

        # What the result is for. Video is the default because it is the long-
        # standing behavior of this panel and by far the more common ask; Genau is
        # the deliberate detour. Under it the act list narrows, so the radio sits
        # directly beneath the dropdown it changes.
        self._video_radio = QRadioButton("Video")
        self._video_radio.setToolTip(
            "Make a full-length video for the satellite players."
        )
        self._video_radio.setChecked(True)
        self._genau_radio = QRadioButton("Genau")
        self._genau_radio.setToolTip(
            "Make a Genau clip: one complete cycle, looping, sent to Genau when done."
        )
        self._intent_group = QButtonGroup(self)
        self._intent_group.addButton(self._video_radio)
        self._intent_group.addButton(self._genau_radio)
        self._intent_group.buttonToggled.connect(self._on_intent_changed)
        self._intent_part = QWidget()
        intent_row = QHBoxLayout(self._intent_part)
        intent_row.setContentsMargins(0, 0, 0, 0)
        intent_row.setSpacing(BUTTON_GAP)  # two radios are one group
        intent_row.addWidget(self._video_radio)
        intent_row.addWidget(self._genau_radio)
        intent_row.addStretch(1)

        # Two ways to act on the same chosen recipe: run it now, or open it in the
        # generator to tweak first. Both gate on the same "image + recipe" readiness.
        self._generate_btn = QPushButton("Generate")
        self._generate_btn.clicked.connect(self._emit)
        self._open_btn = QPushButton("Edit…")
        self._open_btn.setToolTip(
            "Load this combination into a generate tab to edit before running it."
        )
        self._open_btn.clicked.connect(self._emit_open)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(BUTTON_GAP)  # rows of one group sit a group's gap apart
        heading = QLabel("Combine")
        heading.setObjectName("combineHeading")
        heading.setToolTip(
            "Re-run a video's recipe on the dropped image: pick an act, or drop a video."
        )
        layout.addWidget(heading)
        layout.addWidget(self.image_slot)
        # One group apart from the next, the same distance the button bank
        # puts between its groups.
        layout.addSpacing(BUTTON_GROUP_GAP)
        layout.addWidget(self._video_part)
        layout.addWidget(self._intent_part)
        layout.addWidget(self._generate_btn)
        layout.addWidget(self._open_btn)
        self._sync()

    # --- intent (what the result is for) ----------------------------------

    def selected_intent(self) -> str:
        """``VIDEO`` or ``GENAU`` — which lane the chosen recipe is answered from."""
        return GENAU if self._genau_radio.isChecked() else VIDEO

    def set_intent(self, intent: str):
        """Select the ``VIDEO``/``GENAU`` radio; anything else selects video.

        For putting the panel back the way a session left it
        (:meth:`GalleryView.restore_combine_selection`) -- the lane decides which
        acts are answerable, so it goes in before the act does.
        """
        self._genau_radio.setChecked(intent == GENAU)
        self._video_radio.setChecked(intent != GENAU)

    def _on_intent_changed(self, _button, checked: bool):
        """Announce the new lane once, on the radio that just went on.

        ``buttonToggled`` fires twice for one click — off for the old radio, on for
        the new — and the view answers by re-greying the whole act list, so only the
        on edge is passed along.
        """
        if checked:
            if not self.selected_category():
                self._show_dropped()
            self.intent_changed.emit(self.selected_intent())

    # --- category ---------------------------------------------------------

    def selected_category(self) -> str:
        """The picked act, or "" when the neutral "(custom)" option (index 0) is selected."""
        index = self._category.currentIndex()
        return self._category.currentText() if index >= 1 else ""

    def set_category(self, category: str):
        """Select ``category``, or the neutral option for anything else --
        including an act the current lane cannot answer, which
        :meth:`set_available_categories` has greyed out. A greyed act must not
        arrive selected for the same reason it must not stay selected: the
        buttons would go live on a pick that can only answer "no recipe yet".
        """
        index = self._category.findText(category)
        usable = index >= 1 and self._category.model().item(index).isEnabled()
        self._category.setCurrentIndex(index if usable else 0)

    def set_available_categories(self, available: Collection[str]):
        """Gray out every act the current lane has no recipe for — nothing to mine and
        nothing pinned, so offering it could only ever answer "no recipe yet". A
        disabled item says why on hover, naming the lane, since an act the video
        lane answers happily can still be unanswerable as a loop. The neutral
        "(custom)" is never greyed."""
        genau = self.selected_intent() == GENAU
        model = self._category.model()
        for index in range(1, self._category.count()):
            act = self._category.itemText(index)
            usable = act in available
            reason = (f"No past looping “{act}” clip to base a Genau recipe on yet" if genau
                      else f"No past “{act}” video to base a recipe on yet")
            model.item(index).setEnabled(usable)
            self._category.setItemData(
                index, "" if usable else reason, Qt.ItemDataRole.ToolTipRole,
            )
            # A greyed-out act must not stay selected under it — the buttons would be
            # live on a pick the lane cannot answer. Dropping to neutral is what the
            # panel already means by "no act chosen".
            if not usable and self._category.currentIndex() == index:
                self._category.setCurrentIndex(0)

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
        """A picked act supersedes a dropped video: clear the slot and hide it, its
        room kept. Going back to "(custom)" shows it again, holding the video this
        lane last had dropped in it."""
        custom = not self.selected_category()
        if custom:
            self._show_dropped()
        else:
            self.video_slot.clear()
        self.video_slot.setVisible(custom)
        self._sync()

    def _on_video_changed(self):
        """A dropped video supersedes a picked act: wipe the dropdown back to "(custom)"."""
        if self.video_slot.current_id():
            self._dropped[self.selected_intent()] = self.video_slot.current_id()
            self._category.setCurrentIndex(0)
        self._sync()

    def _show_dropped(self):
        lane = self.selected_intent()
        video = self._dropped.get(lane)
        if video and self.video_slot.accepts(video):
            self.video_slot.set_item(video)
        else:
            self._dropped.pop(lane, None)
            self.video_slot.clear()

    def dropped_videos(self) -> dict[str, str]:
        return dict(self._dropped)

    def set_dropped_videos(self, videos: dict[str, str]):
        self._dropped = dict(videos)
        if not self.selected_category():
            self._show_dropped()

    def _sync(self):
        """Both actions go live once a source image sits and a recipe is chosen —
        either by picking an act or by dropping a video."""
        has_recipe = bool(self.selected_category() or self.video_slot.current_id())
        ready = bool(self.image_slot.current_id()) and has_recipe
        self._generate_btn.setEnabled(ready)
        self._open_btn.setEnabled(ready)

    def _emit(self):
        """Generate: run the chosen recipe on the dropped image now."""
        self._dispatch(edit_first=False)

    def _emit_open(self):
        """“Edit…”: hand the chosen recipe to a generate tab to change first."""
        self._dispatch(edit_first=True)

    def _dispatch(self, *, edit_first: bool):
        """Announce what was asked for: a picked act, else the dropped video, and
        nothing at all while either the picture or the recipe is missing."""
        image_id = self.image_slot.current_id()
        category = self.selected_category()
        video_id = "" if category else (self.video_slot.current_id() or "")
        if not image_id or not (category or video_id):
            return
        self.combine_requested.emit(CombineRequest(
            image_id=image_id, video_id=video_id, category=category,
            intent=self.selected_intent(), edit_first=edit_first))
