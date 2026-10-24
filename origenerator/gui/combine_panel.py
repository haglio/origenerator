"""The gallery's image + video combine panel, sitting under the TOC folder tree.

Drop an image into the top slot, then supply a *recipe* either by picking an act
from the Action list, which sends the app looking for a fitting past video, or by
dropping a specific i2v video (shown in gray: it is here for its settings). The two
are mutually exclusive. A video dropped into the top slot lends it only the picture
it was made from, and one let go between the slots lends each what it can. Generate
re-runs the chosen recipe on the dropped image; “Edit individual…” hands it to a
generate tab first.

Under the dropdown, a pair of radios says what the result is *for*: a full-length
video (the default), or a Genau flick — one complete cycle, looping. That choice
picks which recipes the act is answered from, so the dropdown's usable acts change
with it: an act only the video lane can answer grays out under Genau, and acts that
are no kind of cycle at all are not offered there.

The panel is pure UI, reporting what was asked for as one :class:`CombineRequest` on
:attr:`combine_requested`; its controller
(:mod:`origenerator.gui.combine_controller`) owns the database, what each slot is
lent, the routing and both the generation and the generator tab.
"""
from __future__ import annotations

from collections.abc import Callable, Collection
from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QStyle,
    QStyleOptionComboBox,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import BUTTON_GAP, BUTTON_GROUP_GAP

from origenerator import animation_paths
from origenerator.content import genau_flick_word
from origenerator.gui.action_picker import ACTION_LABEL
from origenerator.gui.drop_slot import DropSlot, DropZone
from origenerator.gui.eliding import open_the_list_in_full
from origenerator.gui.generate_button import (
    DEFAULT_CAPTION,
    RANDOM_SEED_CAPTION,
    GenerateButton,
)
from origenerator.gui.inflight import ALREADY_MAKING_ONE_TIP
from origenerator.gui.recent_videos import RecentVideo, RecentVideos
from origenerator.media import MediaType
from origenerator.recipe_match import GENAU, VIDEO

# The dropdown's leading neutral option: no act chosen, so a dropped video is used.
_NEUTRAL_LABEL = "(custom)"
_DROP_PLACEHOLDER = "Drop a video"
_NEEDS_IMAGE = "Nothing to start from — drop an image first"
_NEEDS_RECIPE = "Pick an act or drop a video first"
_EDIT_TIP = "Load this combination into a generate tab to edit before running it."


def _text_inset(combo: QComboBox) -> int:
    """How far in from a dropdown's left edge its own text starts, so a label
    under it lines up with the words rather than with the frame."""
    opt = QStyleOptionComboBox()
    combo.initStyleOption(opt)
    field = combo.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, opt,
        QStyle.SubControl.SC_ComboBoxEditField, combo)
    return field.x() + 1  # the style insets the text a pixel before drawing it


def _keep_its_room_when_hidden(widget: QWidget) -> None:
    room = widget.sizePolicy()
    room.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(room)


@dataclass(frozen=True)
class CombineRequest:
    """One press of Generate or “Edit individual…”: the picture, the recipe —
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
    animation_settings_requested = pyqtSignal()  # "Edit default…": settle an animation
    intent_changed = pyqtSignal(str)  # the Video/Genau radio moved — regray the acts
    item_activated = pyqtSignal(str)  # a slot's picture or clip was clicked (prompt_id)
    video_used = pyqtSignal(str, str)  # (intent, prompt_id) a video put in the slot by hand

    def __init__(
        self,
        image_lent_by: Callable[[str], str | None],
        video_lent_by: Callable[[str], str | None],
        preview: Callable[[str], tuple[str | None, str | None]],
        history: Callable[[str], list[str]],
        parent=None,
    ):
        super().__init__(parent)
        self._preview = preview
        self._history = history
        self.image_slot = DropSlot(MediaType.IMAGE, image_lent_by, preview, "Drop an image")
        # Gray, always: the video in this slot is never what gets made — only the
        # settings the making follows. In color it reads as a second subject beside
        # the image, which is the one thing it is not.
        self.video_slot = DropSlot(MediaType.VIDEO, video_lent_by, preview, _DROP_PLACEHOLDER,
                                   grayscale=True)
        _keep_its_room_when_hidden(self.video_slot)
        self._between = DropZone((self.image_slot, self.video_slot))
        self._between.setFixedHeight(BUTTON_GAP + BUTTON_GROUP_GAP)
        self.image_slot.changed.connect(self._sync)
        self.video_slot.changed.connect(self._on_video_changed)
        self.image_slot.activated.connect(self.item_activated)
        self.video_slot.activated.connect(self.item_activated)
        self._dropped: dict[str, str] = {}
        self._folder_generating = False
        self._recent_videos = RecentVideos(self._recent_rows,
                                           lambda video: self._preview(video)[1])
        self._recent_videos.picked.connect(self.video_slot.set_item)
        _keep_its_room_when_hidden(self._recent_videos)

        # The video part's fast path: pick an act and the view finds a fitting past
        # video for you. A neutral "(custom)" leads the list (index 0, the default) so
        # no act is forced; picking it again clears an act.
        self._category = QComboBox()
        self._list_the_acts(VIDEO)
        open_the_list_in_full(self._category)
        self._category.setToolTip(
            "Pick an act and Generate — the app reuses a fitting past video's recipe "
            "on the dropped image. Or pick (custom) and drop a specific video instead."
        )
        self._category.currentIndexChanged.connect(self._on_category_changed)

        # The word under the dropdown: beside it this pane cuts it to "Ac…", and
        # the list opens upwards, so underneath stays clear.
        self._action_part = QWidget()
        action_column = QVBoxLayout(self._action_part)
        action_column.setContentsMargins(0, 0, 0, 0)
        action_column.setSpacing(0)  # a word and the thing it names
        action_column.addWidget(self._category)
        named = QLabel(ACTION_LABEL)
        named.setIndent(_text_inset(self._category))
        action_column.addWidget(named)
        action_column.addSpacing(BUTTON_GAP)
        action_column.addWidget(self._recent_videos)
        # Or the row's spare height goes to the word, which then floats in it.
        action_column.addStretch(1)

        # The video part: the two ways to supply the recipe, side by side in one
        # container so the dropdown reads as belonging to the video side, not the image.
        self._video_part = QWidget()
        video_row = QHBoxLayout(self._video_part)
        video_row.setContentsMargins(0, 0, 0, 0)
        video_row.setSpacing(BUTTON_GAP)  # the family's gap inside a group
        video_row.addWidget(self._action_part, 1)  # each takes half the part's width
        video_row.addWidget(self.video_slot, 1)

        # What the result is for. Kino is the default because it is the long-
        # standing behavior of this panel and by far the more common ask; Genau is
        # the deliberate detour. Under it the act list narrows, so the radio sits
        # directly beneath the dropdown it changes.
        self._video_radio = QRadioButton("Kino")
        self._video_radio.setToolTip(
            "Make a full-length video for the Satellite Funestras."
        )
        self._video_radio.setChecked(True)
        self._genau_radio = QRadioButton("Genau")
        self._genau_radio.setToolTip(
            f"Make a Genau {genau_flick_word()}: one complete cycle, looping, sent to "
            "Genau when done."
        )
        self._intent_group = QButtonGroup(self)
        self._intent_group.addButton(self._video_radio)
        self._intent_group.addButton(self._genau_radio)
        self._intent_group.buttonToggled.connect(self._on_intent_changed)
        self._intent_part = QWidget()
        intent_row = QHBoxLayout(self._intent_part)
        intent_row.setContentsMargins(0, 0, 0, 0)
        # Wider than the gap a radio leaves between its own circle and its word,
        # or each word reads as labelling the circle after it.
        intent_row.setSpacing(BUTTON_GROUP_GAP)
        intent_row.addWidget(self._video_radio)
        intent_row.addWidget(self._genau_radio)
        intent_row.addStretch(1)

        # Two ways to act on the same chosen recipe: run it now, or open it in the
        # generator to tweak first. Both gate on the same "image + recipe" readiness.
        self._generate_btn = GenerateButton()
        self._generate_btn.clicked.connect(self._emit)
        self._open_btn = QPushButton("Edit individual…")
        self._open_btn.clicked.connect(self._emit_open)
        self._defaults_btn = QPushButton("Edit default…")
        self._defaults_btn.setToolTip(
            "Settle what each animation runs: an act, in a lane, from each kind "
            "of picture")
        self._defaults_btn.clicked.connect(self.animation_settings_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)
        layout.setSpacing(BUTTON_GAP)  # rows of one group sit a group's gap apart
        heading = QLabel("Combine")
        heading.setObjectName("combineHeading")
        heading.setToolTip(
            "Re-run a video's recipe on the dropped image: pick an act, or drop a video."
        )
        layout.addWidget(heading)
        parted = QVBoxLayout()
        parted.setSpacing(0)  # the room between them is the whole gap
        parted.addWidget(self.image_slot)
        parted.addWidget(self._between)
        parted.addWidget(self._video_part)
        layout.addLayout(parted)
        layout.addWidget(self._intent_part)
        layout.addWidget(self._generate_btn)
        layout.addWidget(self._open_btn)
        layout.addWidget(self._defaults_btn)
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
        the new — and the view answers by re-graying the whole act list, so only the
        on edge is passed along.
        """
        if checked:
            self._list_the_acts(self.selected_intent())
            if not self.selected_category():
                self._show_dropped()
            self.intent_changed.emit(self.selected_intent())

    # --- category ---------------------------------------------------------

    def _list_the_acts(self, lane: str) -> None:
        picked = self.selected_category() if self._category.count() else ""
        self._category.clear()
        self._category.addItem(_NEUTRAL_LABEL)
        self._category.addItems(animation_paths.acts(lane))
        self.set_category(picked)

    def selected_category(self) -> str:
        """The picked act, or "" when the neutral "(custom)" option (index 0) is selected."""
        index = self._category.currentIndex()
        return self._category.currentText() if index >= 1 else ""

    def set_category(self, category: str):
        """Select ``category``, or the neutral option for anything else --
        including an act the current lane cannot answer, which
        :meth:`set_available_categories` has grayed out. A grayed act must not
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
        "(custom)" is never grayed."""
        genau = self.selected_intent() == GENAU
        model = self._category.model()
        for index in range(1, self._category.count()):
            act = self._category.itemText(index)
            usable = act in available
            reason = (f"No past looping “{act}” {genau_flick_word()} to base a Genau recipe "
                      "on yet" if genau
                      else f"No past “{act}” video to base a recipe on yet")
            model.item(index).setEnabled(usable)
            self._category.setItemData(
                index, "" if usable else reason, Qt.ItemDataRole.ToolTipRole,
            )
            # A grayed-out act must not stay selected under it — the buttons would be
            # live on a pick the lane cannot answer. Dropping to neutral is what the
            # panel already means by "no act chosen".
            if not usable and self._category.currentIndex() == index:
                self._category.setCurrentIndex(0)

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
        self._recent_videos.setVisible(custom)
        self._sync()

    def _on_video_changed(self):
        """A dropped video supersedes a picked act: wipe the dropdown back to "(custom)"."""
        video = self.video_slot.current_id()
        if video:
            lane = self.selected_intent()
            if video != self._dropped.get(lane):
                self._dropped[lane] = video
                self.video_used.emit(lane, video)
            self._category.setCurrentIndex(0)
        self._sync()

    def _recent_rows(self) -> list[RecentVideo]:
        held = self.video_slot.current_id()
        listed = dict.fromkeys(video for video in (held, *self._history(self.selected_intent()))
                               if video)
        return [RecentVideo(video, self._preview(video)[0])
                for video in listed if self.video_slot.accepts(video)]

    def _show_dropped(self):
        lane = self.selected_intent()
        video = self._dropped.get(lane)
        if video and self.video_slot.accepts(video):
            self.video_slot.set_item(video)
        else:
            self._dropped.pop(lane, None)
            self.video_slot.clear()

    def note_folder_generating(self, generating: bool) -> None:
        self._folder_generating = generating
        self._sync()

    def dropped_videos(self) -> dict[str, str]:
        return dict(self._dropped)

    def set_dropped_videos(self, videos: dict[str, str]):
        self._dropped = dict(videos)
        if not self.selected_category():
            self._show_dropped()

    def _sync(self):
        image_id = self.image_slot.current_id()
        video_id = self.video_slot.current_id()
        ready = bool(image_id) and bool(self.selected_category() or video_id)
        can_run = ready and not self._folder_generating
        remakes_its_own = bool(video_id) and self.image_slot.lent_by(video_id) == image_id
        self._generate_btn.setEnabled(can_run)
        self._generate_btn.set_caption(
            RANDOM_SEED_CAPTION if can_run and remakes_its_own else DEFAULT_CAPTION)
        self._open_btn.setEnabled(ready)
        missing = "" if ready else _NEEDS_IMAGE if not image_id else _NEEDS_RECIPE
        self._generate_btn.setToolTip(
            missing or (ALREADY_MAKING_ONE_TIP if self._folder_generating else ""))
        self._open_btn.setToolTip(missing or _EDIT_TIP)

    def _emit(self):
        """Generate: run the chosen recipe on the dropped image now."""
        self._dispatch(edit_first=False)

    def _emit_open(self):
        """“Edit individual…”: hand the recipe to a generate tab to change first."""
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
