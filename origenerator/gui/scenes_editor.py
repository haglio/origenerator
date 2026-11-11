from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QPushButton,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import GAP_MEDIUM, GAP_SMALL

from origenerator.gui import diff_text, tracked_prompt
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.icons import tab_close_icon
from origenerator.gui.panes import border_as_a_set
from origenerator.gui.param_help import param_help
from origenerator.gui.preset_dropdown import PresetDropdown
from origenerator.gui.prompt_boxes import (
    Countdown,
    TidiesOnLeaving,
    count_down,
    mark_problems_in,
    reads_numbers,
    set_in_use,
)
from origenerator.gui.prompt_field import PromptField
from origenerator.gui.prompt_marks import has_unread_emphasis
from origenerator.prompt_checks import tidied, without_emphasis
from origenerator.prompt_tokens import PromptReading
from origenerator.workflows.base import (
    ParamDef,
    chained_frames,
    chained_to,
    scene_prompts,
    scene_text,
    story_of,
)
from origenerator.workflows.duration import frames_for_seconds, seconds_for_frames

LINES_PLACEHOLDER = "What she says in this scene, spoken in the voice set under Audio"
SPEAKING_NOTE = " — not used while this scene speaks"
SPEAKING_HELP = ("A scene with a line renders on the speech model, and all that "
                 "happens in it is her speaking — it will not act a prompt out. "
                 "Clear Her Lines to write this scene instead.")
SPOKEN_OVER = ("positive_prompt", "negative_prompt")

TEXT_CAPTIONS = {
    "positive_prompt": "Positive Prompt",
    "negative_prompt": "Negative Prompt",
    "scene_lines": "Her Lines",
}


class _Scene(QFrame):
    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(self, pd: ParamDef, prepare_length: Callable[[PresetDropdown], None],
                 shut_down: dict[str, str], lines: bool = True, parent=None):
        super().__init__(parent)
        self._pd = pd
        self._shut_down = shut_down
        column = QVBoxLayout(self)
        border_as_a_set(self, column)
        column.setSpacing(GAP_SMALL)
        header = QHBoxLayout()
        self.title = ElidingLabel("")
        self.title.setObjectName("sceneTitle")
        header.addWidget(self.title, 1)
        self.length = PresetDropdown(pd.options, unit=pd.unit)
        self.length.setToolTip(param_help("scene_frames"))
        prepare_length(self.length)
        header.addWidget(self.length)
        self.remove = QToolButton()
        self.remove.setObjectName("sceneRemove")
        mark = self.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
        self.remove.setIcon(tab_close_icon())
        self.remove.setIconSize(QSize(mark, mark))
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.clicked.connect(lambda: self.remove_requested.emit(self))
        header.addWidget(self.remove)
        column.addLayout(header)
        self.fields: dict[str, PromptField] = {}
        self.captions: dict[str, ElidingLabel] = {}
        self._countdowns: dict[str, Countdown] = {}
        self._readings: dict[str, PromptReading | None] = {}
        for key, caption in TEXT_CAPTIONS.items():
            if key == "scene_lines" and not lines:
                continue
            label = ElidingLabel(caption)
            label.setToolTip(param_help(key))
            column.addWidget(label)
            field = PromptField(key)
            field.setToolTip(param_help(key))
            field.textChanged.connect(self.changed)
            column.addWidget(field)
            self.fields[key] = field
            self.captions[key] = label
            if key in SPOKEN_OVER:
                self._countdowns[key] = Countdown()
                column.addWidget(self._countdowns[key])
                field.textChanged.connect(lambda key=key: self._count_down(key))
                TidiesOnLeaving(field, lambda changed, key=key: self._left_a_prompt(key, changed))
        if lines:
            self.fields["scene_lines"].setPlaceholderText(LINES_PLACEHOLDER)
            self.fields["scene_lines"].textChanged.connect(self.reflect_use)
        self.reflect_use()
        self.length.editTextChanged.connect(self.changed)
        self.length.edited.connect(self._settle)

    def show_readings(self, readings: dict[str, PromptReading | None]) -> None:
        self._readings = readings
        for key in self._countdowns:
            self._count_down(key)

    def _count_down(self, key: str) -> None:
        count_down(self._countdowns[key], self.fields[key], self._reading_of(key),
                   in_use=self._in_use(key))
        for each in SPOKEN_OVER:
            self._mark_problems(each)

    def _mark_problems(self, key: str) -> None:
        opposite = next(each for each in SPOKEN_OVER if each != key)
        opposing = diff_text.live_text(self.fields[opposite]) if self._in_use(opposite) else ""
        mark_problems_in([self.fields[key]], self._reading_of(key), in_use=self._in_use(key),
                         opposing=opposing)

    def _reading_of(self, key: str) -> PromptReading | None:
        return self._readings.get(key)

    def _left_a_prompt(self, key: str, changed: bool) -> None:
        field = self.fields[key]
        text = diff_text.live_text(field)
        tidy = tidied(text, reads_numbers=reads_numbers(self._reading_of(key)))
        if changed and tidy != text:
            field.setPlainText(tidy)

    def _in_use(self, key: str) -> bool:
        return not self.speaking() and not self._shut_down.get(key)

    def speaking(self) -> bool:
        field = self.fields.get("scene_lines")
        return (field is not None and not self._shut_down.get("scene_lines")
                and bool(diff_text.live_text(field).strip()))

    def reflect_use(self) -> None:
        if "scene_lines" in self.fields:
            set_in_use(self.fields["scene_lines"], self.captions["scene_lines"],
                       self._shut_down.get("scene_lines"), param_help("scene_lines"))
        speaking = self.speaking()
        for key in SPOKEN_OVER:
            set_in_use(self.fields[key], self.captions[key],
                       SPEAKING_HELP if speaking else self._shut_down.get(key), param_help(key))
            self.captions[key].setText(TEXT_CAPTIONS[key] + (SPEAKING_NOTE if speaking else ""))
            self._count_down(key)

    def frames(self) -> int:
        seconds = self.length.value()
        return (frames_for_seconds(seconds, self._pd.shown_in_seconds_at, self._pd)
                if seconds is not None else int(self._pd.default[0]))

    def set_frames(self, frames: int) -> None:
        self.length.set_value(seconds_for_frames(int(frames), self._pd.shown_in_seconds_at, self._pd))

    def _settle(self) -> None:
        self.set_frames(self.frames())


class ScenesEditor(QWidget):
    changed = pyqtSignal()

    def __init__(self, frames_def: ParamDef,
                 prepare_length: Callable[[PresetDropdown], None], shut_down: dict[str, str],
                 lines: bool = True, parent=None):
        super().__init__(parent)
        self._pd = frames_def
        self._prepare_length = prepare_length
        self._lines = lines
        self._shut_down = shut_down
        self._scenes: list[_Scene] = []
        self._readings: dict[str, PromptReading | None] = {}
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_MEDIUM)
        self._scene_column = QVBoxLayout()
        self._scene_column.setSpacing(GAP_MEDIUM)
        column.addLayout(self._scene_column)
        self._add = QPushButton("Add scene")
        self._add.setToolTip("Another scene, run after this one from its last frame")
        self._add.clicked.connect(self.add_scene)
        column.addWidget(self._add, alignment=Qt.AlignmentFlag.AlignLeft)
        self.add_scene()

    def add_scene(self) -> None:
        scene = _Scene(self._pd, self._prepare_length, self._shut_down, lines=self._lines)
        scene.show_readings(self._readings)
        if self._scenes:
            scene.fields["negative_prompt"].setPlainText(
                diff_text.live_text(self._scenes[-1].fields["negative_prompt"]))
        scene.set_frames(int(self._pd.default[0]))
        scene.changed.connect(self.changed)
        scene.remove_requested.connect(self.remove_scene)
        self._scenes.append(scene)
        self._scene_column.addWidget(scene)
        self._renumber()
        self.changed.emit()

    def reflect_use(self) -> None:
        for scene in self._scenes:
            scene.reflect_use()

    def show_readings(self, readings: dict[str, PromptReading | None]) -> None:
        self._readings = {key: readings.get(key) for key in SPOKEN_OVER}
        for scene in self._scenes:
            scene.show_readings(self._readings)

    def remove_scene(self, which) -> None:
        scene = self._scenes[which] if isinstance(which, int) else which
        if len(self._scenes) == 1 or scene not in self._scenes:
            return
        self._scenes.remove(scene)
        self._scene_column.removeWidget(scene)
        scene.setParent(None)
        scene.deleteLater()
        self._renumber()
        self.changed.emit()

    def _renumber(self) -> None:
        several = len(self._scenes) > 1
        for number, scene in enumerate(self._scenes, start=1):
            scene.title.setText(f"Scene {number}")
            scene.remove.setEnabled(several)
            scene.remove.setToolTip("Remove this scene" if several
                                    else "A story keeps at least one scene")

    def _resize_to(self, count: int) -> None:
        while len(self._scenes) > max(1, count):
            self.remove_scene(len(self._scenes) - 1)
        while len(self._scenes) < count:
            self.add_scene()

    def fields(self, key: str) -> list[PromptField]:
        return [scene.fields[key] for scene in self._scenes if key in scene.fields]

    def text_fields(self) -> list[PromptField]:
        return [field for scene in self._scenes for field in scene.fields.values()]

    def remove_unread_emphasis(self) -> None:
        for field in self.text_fields():
            if has_unread_emphasis(field):
                tracked_prompt.write_undoably(field, without_emphasis(diff_text.live_text(field)))

    def fields_beside_their_texts(self, stored: dict) -> list[tuple[PromptField, str | None]]:
        return [(field, scene_text(scene_prompts(stored[key]), index)
                 if isinstance(stored.get(key), str) else None)
                for index, scene in enumerate(self._scenes)
                for key, field in scene.fields.items()]

    def story(self, key: str) -> str:
        return story_of([diff_text.live_text(field) for field in self.fields(key)])

    def set_story(self, key: str, text: str) -> None:
        texts = scene_prompts(str(text))
        if key == "positive_prompt":
            self._resize_to(len(texts))
        for index, field in enumerate(self.fields(key)):
            tracked_prompt.write(field, scene_text(texts, index))

    def scene_frames(self) -> list[int]:
        return [scene.frames() for scene in self._scenes]

    def set_scene_frames(self, frames) -> None:
        for scene, count in zip(self._scenes, list(frames or []), strict=False):
            scene.set_frames(int(count))

    def lines(self) -> list[str]:
        return [diff_text.live_text(field) for field in self.fields("scene_lines")]

    def set_lines(self, lines) -> None:
        for field, text in zip(self.fields("scene_lines"), list(lines or []), strict=False):
            tracked_prompt.write(field, str(text))

    def total_frames(self) -> int:
        return chained_frames(self.scene_frames())

    def set_total_frames(self, frames: int) -> None:
        self.set_scene_frames(chained_to(int(frames), self.scene_frames(), int(self._pd.min_val)))
