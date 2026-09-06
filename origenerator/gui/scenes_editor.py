"""The scenes of a story, one card each: what it shows, what it keeps out,
what she says, and how long it runs.

A clip longer than one segment is rendered as segments chained from each
other's last frame (:meth:`~origenerator.workflows.base.WorkflowTemplate.
chain_segments`), so a story can change what happens as it goes: each scene is
its own texts, run for its own length, started on the frame before it. This is
the form's face for that. Underneath, the scenes' prompts are stored as the one
positive prompt and their negatives as the one negative prompt, each with a
scene break between the texts (:func:`~origenerator.workflows.base.story_of`),
so everything that reads, searches or rewrites a prompt keeps working on one
string; their lengths are ``scene_frames`` and their lines ``scene_lines``, one
per scene.

The lines are spoken: a scene with one renders on the speech model, her lips
on the words, in the voice the Audio section sets (see
:mod:`origenerator.speech`). A workflow that cannot speak -- the loop -- has no
lines param, and its cards carry no lines box.
"""

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

from origenerator.gui import diff_text
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.icons import tab_close_icon
from origenerator.gui.param_help import param_help
from origenerator.gui.preset_combo import PresetComboBox
from origenerator.gui.prompt_box import PromptBox
from origenerator.workflows.base import ParamDef, chained_frames, scene_prompts, story_of
from origenerator.workflows.duration import frames_for_seconds, seconds_for_frames

LINES_PLACEHOLDER = "What she says in this scene, spoken in the voice set under Audio"

# The texts a scene carries, by the param each is stored as, with the caption
# over its box. The prompts are stored as stories (see the module above); the
# lines as a list, one per scene.
TEXT_CAPTIONS = {
    "positive_prompt": "Positive Prompt",
    "negative_prompt": "Negative Prompt",
    "scene_lines": "Her Lines",
}


class _Scene(QFrame):
    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(self, pd: ParamDef, prepare_length: Callable[[PresetComboBox], None],
                 lines: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("sceneCard")
        self._pd = pd
        column = QVBoxLayout(self)
        column.setContentsMargins(6, 4, 6, 6)
        column.setSpacing(4)
        # Kept narrow: this row sits beside the form's label column, so it is
        # the row that would push the pane's floor past its cap (see
        # GenerateConfigPanel.minimumSizeHint). The title gives way first, and
        # the x is the flat mark the tabs wear rather than a dressed button --
        # the same act, and a third of the width.
        header = QHBoxLayout()
        self.title = ElidingLabel("")
        self.title.setObjectName("sceneTitle")
        header.addWidget(self.title, 1)
        self.length = PresetComboBox(pd.options, unit=pd.unit)
        self.length.setToolTip(param_help("scene_frames"))
        prepare_length(self.length)
        header.addWidget(self.length)
        self.remove = QToolButton()
        self.remove.setObjectName("sceneRemove")
        mark = self.style().pixelMetric(QStyle.PixelMetric.PM_TabCloseIndicatorWidth)
        self.remove.setIcon(tab_close_icon(self))
        self.remove.setIconSize(QSize(mark, mark))
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.clicked.connect(lambda: self.remove_requested.emit(self))
        header.addWidget(self.remove)
        column.addLayout(header)
        # Captioned, since three boxes in a row say nothing about which is which
        # once they hold text; each carries its param's own help.
        self.boxes: dict[str, PromptBox] = {}
        for key, caption in TEXT_CAPTIONS.items():
            if key == "scene_lines" and not lines:
                continue
            label = ElidingLabel(caption)
            label.setToolTip(param_help(key))
            column.addWidget(label)
            box = PromptBox(key)
            box.setToolTip(param_help(key))
            box.textChanged.connect(self.changed)
            column.addWidget(box)
            self.boxes[key] = box
        if lines:
            self.boxes["scene_lines"].setPlaceholderText(LINES_PLACEHOLDER)
        self.length.editTextChanged.connect(self.changed)
        self.length.edited.connect(self._settle)

    def frames(self) -> int:
        seconds = self.length.value()
        return (frames_for_seconds(seconds, self._pd.rate, self._pd)
                if seconds is not None else int(self._pd.default[0]))

    def set_frames(self, frames: int) -> None:
        self.length.set_value(seconds_for_frames(int(frames), self._pd.rate, self._pd))

    def _settle(self) -> None:
        """Show the length it will run for, once an edit of it has ended."""
        self.set_frames(self.frames())


class ScenesEditor(QWidget):
    """One card per scene, and a button for the next one."""

    changed = pyqtSignal()

    def __init__(self, frames_def: ParamDef,
                 prepare_length: Callable[[PresetComboBox], None], lines: bool = True,
                 parent=None):
        super().__init__(parent)
        self._pd = frames_def
        self._prepare_length = prepare_length
        # Whether the workflow speaks: a card of one that cannot has no lines box.
        self._lines = lines
        self._scenes: list[_Scene] = []
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self._cards = QVBoxLayout()
        self._cards.setSpacing(6)
        column.addLayout(self._cards)
        self._add = QPushButton("Add scene")
        self._add.setToolTip("Another scene, run after this one from its last frame")
        self._add.clicked.connect(self.add_scene)
        column.addWidget(self._add, alignment=Qt.AlignmentFlag.AlignLeft)
        self.add_scene()

    # --- the scenes ------------------------------------------------------------

    def add_scene(self) -> None:
        """Another scene after the last, at the workflow's default length. It
        starts out keeping out what the scene before it keeps out: a negative
        mostly holds across a story, so blank would mean typing it again."""
        scene = _Scene(self._pd, self._prepare_length, lines=self._lines)
        if self._scenes:
            scene.boxes["negative_prompt"].setPlainText(
                diff_text.live_text(self._scenes[-1].boxes["negative_prompt"]))
        scene.set_frames(int(self._pd.default[0]))
        scene.changed.connect(self.changed)
        scene.remove_requested.connect(self.remove_scene)
        self._scenes.append(scene)
        self._cards.addWidget(scene)
        self._renumber()
        self.changed.emit()

    def remove_scene(self, which) -> None:
        """Take a scene out, by index or by card; the last one stays."""
        scene = self._scenes[which] if isinstance(which, int) else which
        if len(self._scenes) == 1 or scene not in self._scenes:
            return
        self._scenes.remove(scene)
        self._cards.removeWidget(scene)
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
        """Exactly ``count`` scenes: extras dropped from the end, missing ones
        added at the workflow's default length."""
        while len(self._scenes) > max(1, count):
            self.remove_scene(len(self._scenes) - 1)
        while len(self._scenes) < count:
            self.add_scene()

    # --- what the form reads and writes ----------------------------------------

    def boxes(self, key: str) -> list[PromptBox]:
        """Every scene's box for the text stored as ``key``, in story order."""
        return [scene.boxes[key] for scene in self._scenes if key in scene.boxes]

    def text_boxes(self) -> list[PromptBox]:
        """Every box on every card, in reading order: what a find searches."""
        return [box for scene in self._scenes for box in scene.boxes.values()]

    def story(self, key: str) -> str:
        """The one prompt that stores every scene's ``key`` text."""
        return story_of([diff_text.live_text(box) for box in self.boxes(key)])

    def set_story(self, key: str, text: str) -> None:
        """Lay a stored prompt out one scene per text. The positive prompt is
        the story, so the count of scenes follows it; a negative with fewer
        texts than scenes carries its last text on through the rest, which is
        what the graph keeps out of them (WorkflowTemplate.scene_prompt_nodes),
        so what the cards show is what renders."""
        texts = scene_prompts(str(text))
        if key == "positive_prompt":
            self._resize_to(len(texts))
        for index, box in enumerate(self.boxes(key)):
            diff_text.forget(box)
            box.setPlainText(texts[min(index, len(texts) - 1)])

    def scene_frames(self) -> list[int]:
        return [scene.frames() for scene in self._scenes]

    def set_scene_frames(self, frames) -> None:
        """Each scene's length; a list short of the scenes leaves the rest as
        they are, and one past them is cut to fit."""
        for scene, count in zip(self._scenes, list(frames or [])):
            scene.set_frames(int(count))

    def lines(self) -> list[str]:
        return [diff_text.live_text(box) for box in self.boxes("scene_lines")]

    def set_lines(self, lines) -> None:
        for box, text in zip(self.boxes("scene_lines"), list(lines or [])):
            box.setPlainText(str(text))

    def total_frames(self) -> int:
        """The clip's length: the scenes end to end, each after the first
        starting on the frame before it."""
        return chained_frames(self.scene_frames())
