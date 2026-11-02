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
from shared_ui.spacing import BUTTON_GAP, BUTTON_GROUP_GAP, GAP_SMALL

from origenerator import animation_paths
from origenerator.action_settings import GENAU, VIDEO, as_sentence, no_past_video
from origenerator.content import genau_flick_word
from origenerator.gui.action_dropdown import ACTION_LABEL
from origenerator.gui.drop_zone import DROP_A_VIDEO, DROP_AN_IMAGE, DropZone, DropZones
from origenerator.gui.eliding import open_the_list_in_full
from origenerator.gui.generate_button import (
    DEFAULT_CAPTION,
    RANDOM_SEED_CAPTION,
    GenerateButton,
)
from origenerator.gui.inflight import ALREADY_MAKING_ONE_TIP
from origenerator.gui.recent_videos import RecentVideo, RecentVideos
from origenerator.media import MediaType

_NEUTRAL_LABEL = "(custom)"
_NEEDS_IMAGE = "Nothing to start from — drop an image first"
_NEEDS_ACTION_OR_VIDEO = "Pick an action or drop a video first"
_EDIT_TIP = "Load this combination into a generate tab to edit before running it."


def _text_inset(dropdown: QComboBox) -> int:
    opt = QStyleOptionComboBox()
    dropdown.initStyleOption(opt)
    field = dropdown.style().subControlRect(
        QStyle.ComplexControl.CC_ComboBox, opt,
        QStyle.SubControl.SC_ComboBoxEditField, dropdown)
    return field.x() + 1  # the style insets the text a pixel before drawing it


def _keep_its_room_when_hidden(widget: QWidget) -> None:
    room = widget.sizePolicy()
    room.setRetainSizeWhenHidden(True)
    widget.setSizePolicy(room)


@dataclass(frozen=True)
class CombineRequest:
    image_id: str
    video_id: str = ""
    category: str = ""
    intent: str = VIDEO
    edit_first: bool = False


class Combine(QWidget):
    combine_requested = pyqtSignal(object)
    animation_settings_requested = pyqtSignal()
    intent_changed = pyqtSignal(str)
    item_activated = pyqtSignal(str)
    video_used = pyqtSignal(str, str)

    def __init__(
        self,
        image_lent_by: Callable[[str], str | None],
        video_lent_by: Callable[[str], str | None],
        preview: Callable[[str], tuple[str | None, str | None]],
        history: Callable[[str], list[str]],
        parent=None,
        *,
        named: Callable[[str], str | None] = lambda name: None,
        name_of: Callable[[str], str] = lambda held: "",
        browse_image: Callable[[], None] | None = None,
        leads_to: Callable[[str], str | None] = lambda held: held,
    ):
        super().__init__(parent)
        self._preview = preview
        self._history = history
        self.image_zone = DropZone(MediaType.IMAGE, image_lent_by, preview, DROP_AN_IMAGE,
                                   named=named, name_of=name_of, browse=browse_image,
                                   leads_to=leads_to)
        self.video_zone = DropZone(MediaType.VIDEO, video_lent_by, preview, DROP_A_VIDEO,
                                   grayscale=True, named=named, name_of=name_of,
                                   leads_to=leads_to)
        _keep_its_room_when_hidden(self.video_zone)
        self._between = DropZones((self.image_zone, self.video_zone))
        self._between.setFixedHeight(BUTTON_GAP + BUTTON_GROUP_GAP)
        self.image_zone.changed.connect(self._sync)
        self.video_zone.changed.connect(self._on_video_changed)
        self.image_zone.activated.connect(self.item_activated)
        self.video_zone.activated.connect(self.item_activated)
        self._dropped: dict[str, str] = {}
        self._folder_generating = False
        self._recent_videos = RecentVideos(self._recent_rows,
                                           lambda video: self._preview(video)[1])
        self._recent_videos.picked.connect(self.video_zone.set_item)
        _keep_its_room_when_hidden(self._recent_videos)

        self._category = QComboBox()
        self._list_the_actions(VIDEO)
        open_the_list_in_full(self._category)
        self._category.setToolTip(
            "Pick an action and Generate — the app reuses a fitting past video's settings "
            "on the dropped image. Or pick (custom) and drop a specific video instead."
        )
        self._category.currentIndexChanged.connect(self._on_category_changed)

        self._action_part = QWidget()
        action_column = QVBoxLayout(self._action_part)
        action_column.setContentsMargins(0, 0, 0, 0)
        action_column.setSpacing(0)
        action_column.addWidget(self._category)
        named = QLabel(ACTION_LABEL)
        named.setIndent(_text_inset(self._category))
        action_column.addWidget(named)
        action_column.addSpacing(BUTTON_GAP)
        action_column.addWidget(self._recent_videos)
        action_column.addStretch(1)

        self._video_part = QWidget()
        video_row = QHBoxLayout(self._video_part)
        video_row.setContentsMargins(0, 0, 0, 0)
        video_row.setSpacing(BUTTON_GAP)
        video_row.addWidget(self._action_part, 1)
        video_row.addWidget(self.video_zone, 1)

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
        intent_row.setSpacing(BUTTON_GROUP_GAP)
        intent_row.addWidget(self._video_radio)
        intent_row.addWidget(self._genau_radio)
        intent_row.addStretch(1)

        self._generate_btn = GenerateButton()
        self._generate_btn.clicked.connect(self._emit)
        self._open_btn = QPushButton("Edit individual…")
        self._open_btn.clicked.connect(self._emit_open)
        self._defaults_btn = QPushButton("Edit default…")
        self._defaults_btn.setToolTip(
            "Settle what each animation runs: an action, in a lane, from each kind "
            "of image")
        self._defaults_btn.clicked.connect(self.animation_settings_requested)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, GAP_SMALL, 0, 0)
        layout.setSpacing(BUTTON_GAP)
        heading = QLabel("Combine")
        heading.setObjectName("combineHeading")
        heading.setToolTip(
            "Re-run a video's settings on the dropped image: pick an action, or drop a video."
        )
        layout.addWidget(heading)
        parted = QVBoxLayout()
        parted.setSpacing(0)
        parted.addWidget(self.image_zone)
        parted.addWidget(self._between)
        parted.addWidget(self._video_part)
        layout.addLayout(parted)
        layout.addWidget(self._intent_part)
        layout.addWidget(self._generate_btn)
        layout.addWidget(self._open_btn)
        layout.addWidget(self._defaults_btn)
        self._sync()

    def selected_intent(self) -> str:
        return GENAU if self._genau_radio.isChecked() else VIDEO

    def set_intent(self, intent: str):
        self._genau_radio.setChecked(intent == GENAU)
        self._video_radio.setChecked(intent != GENAU)

    def _on_intent_changed(self, _button, checked: bool):
        # buttonToggled fires twice for one click, off for the old radio and on for the new.
        if checked:
            self._list_the_actions(self.selected_intent())
            if not self.selected_category():
                self._show_dropped()
            self.intent_changed.emit(self.selected_intent())

    def _list_the_actions(self, lane: str) -> None:
        picked = self.selected_category() if self._category.count() else ""
        self._category.clear()
        self._category.addItem(_NEUTRAL_LABEL)
        self._category.addItems(animation_paths.actions(lane))
        self.set_category(picked)

    def selected_category(self) -> str:
        index = self._category.currentIndex()
        return self._category.currentText() if index >= 1 else ""

    def set_category(self, category: str):
        index = self._category.findText(category)
        usable = index >= 1 and self._category.model().item(index).isEnabled()
        self._category.setCurrentIndex(index if usable else 0)

    def set_available_categories(self, available: Collection[str]):
        lane = self.selected_intent()
        model = self._category.model()
        for index in range(1, self._category.count()):
            action = self._category.itemText(index)
            usable = action in available
            reason = as_sentence(no_past_video(action, lane))
            model.item(index).setEnabled(usable)
            self._category.setItemData(
                index, "" if usable else reason, Qt.ItemDataRole.ToolTipRole,
            )
            if not usable and self._category.currentIndex() == index:
                self._category.setCurrentIndex(0)

    def _on_category_changed(self):
        custom = not self.selected_category()
        if custom:
            self._show_dropped()
        else:
            self.video_zone.clear()
        self.video_zone.setVisible(custom)
        self._recent_videos.setVisible(custom)
        self._sync()

    def _on_video_changed(self):
        video = self.video_zone.current_id()
        if video:
            lane = self.selected_intent()
            if video != self._dropped.get(lane):
                self._dropped[lane] = video
                self.video_used.emit(lane, video)
            self._category.setCurrentIndex(0)
        self._sync()

    def _recent_rows(self) -> list[RecentVideo]:
        held = self.video_zone.current_id()
        return sorted(self._history(self.selected_intent()), key=lambda video: video.item != held)

    def _show_dropped(self):
        lane = self.selected_intent()
        video = self._dropped.get(lane)
        if video and self.video_zone.accepts(video):
            self.video_zone.set_item(video)
        else:
            self._dropped.pop(lane, None)
            self.video_zone.clear()

    def note_folder_generating(self, generating: bool) -> None:
        self._folder_generating = generating
        self._sync()

    def dropped_videos(self) -> dict[str, str]:
        return dict(self._dropped)

    def reread_names(self) -> None:
        self.image_zone.reread_name()
        self.video_zone.reread_name()

    def set_dropped_videos(self, videos: dict[str, str]):
        self._dropped = dict(videos)
        if not self.selected_category():
            self._show_dropped()

    def _sync(self):
        image_id = self.image_zone.current_id()
        video_id = self.video_zone.current_id()
        ready = bool(image_id) and bool(self.selected_category() or video_id)
        can_run = ready and not self._folder_generating
        remakes_its_own = bool(video_id) and self.image_zone.lent_by(video_id) == image_id
        self._generate_btn.setEnabled(can_run)
        self._generate_btn.set_caption(
            RANDOM_SEED_CAPTION if can_run and remakes_its_own else DEFAULT_CAPTION)
        self._open_btn.setEnabled(ready)
        missing = "" if ready else _NEEDS_IMAGE if not image_id else _NEEDS_ACTION_OR_VIDEO
        self._generate_btn.setToolTip(
            missing or (ALREADY_MAKING_ONE_TIP if self._folder_generating else ""))
        self._open_btn.setToolTip(missing or _EDIT_TIP)

    def _emit(self):
        self._dispatch(edit_first=False)

    def _emit_open(self):
        self._dispatch(edit_first=True)

    def _dispatch(self, *, edit_first: bool):
        image_id = self.image_zone.current_id()
        category = self.selected_category()
        video_id = "" if category else (self.video_zone.current_id() or "")
        if not image_id or not (category or video_id):
            return
        self.combine_requested.emit(CombineRequest(
            image_id=image_id, video_id=video_id, category=category,
            intent=self.selected_intent(), edit_first=edit_first))
