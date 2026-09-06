"""The scenes of a story, one prompt box and one length each.

A clip longer than one segment is rendered as segments chained from each
other's last frame (:meth:`~origenerator.workflows.base.WorkflowTemplate.
chain_segments`), so a story can change what happens as it goes: each scene is
its own text, run for its own length, started on the frame before it. This is
the form's face for that. Underneath, the scenes' texts are stored as the one
positive prompt with a scene break between them (:func:`~origenerator.workflows.
base.story_of`), so everything that reads, searches or rewrites a prompt keeps
working on one string, and their lengths as ``scene_frames``, one per scene.

Each scene also carries a box for her lines. Nothing hears them yet -- no voice
is wired in -- and the box says so; they are saved with the recipe for the day
one is.
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
from origenerator.gui.preset_combo import PresetComboBox
from origenerator.gui.prompt_box import PromptBox
from origenerator.workflows.base import ParamDef, chained_frames, scene_prompts, story_of
from origenerator.workflows.duration import frames_for_seconds, seconds_for_frames

LINES_PLACEHOLDER = "Her lines — saved with the recipe, not voiced yet"


class _Scene(QFrame):
    changed = pyqtSignal()
    remove_requested = pyqtSignal(object)

    def __init__(self, pd: ParamDef, prepare_length: Callable[[PresetComboBox], None],
                 parent=None):
        super().__init__(parent)
        self._pd = pd
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 6)
        column.setSpacing(4)
        # Kept narrow: this row sits beside the form's label column, so it is
        # the row that would push the pane's floor past its cap (see
        # GenerateConfigPanel.minimumSizeHint). The title gives way first, and
        # the ✕ is the flat mark the tabs wear rather than a dressed button --
        # the same act, and a third of the width.
        header = QHBoxLayout()
        self.title = ElidingLabel("")
        self.title.setObjectName("sceneTitle")
        header.addWidget(self.title, 1)
        self.length = PresetComboBox(pd.options, unit=pd.unit)
        self.length.setToolTip("How long this scene runs")
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
        self.prompt = PromptBox("positive_prompt")
        column.addWidget(self.prompt)
        self.lines = PromptBox("scene_lines")
        self.lines.setPlaceholderText(LINES_PLACEHOLDER)
        self.lines.setToolTip(LINES_PLACEHOLDER)
        column.addWidget(self.lines)
        self.prompt.textChanged.connect(self.changed)
        self.lines.textChanged.connect(self.changed)
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
                 prepare_length: Callable[[PresetComboBox], None], parent=None):
        super().__init__(parent)
        self._pd = frames_def
        self._prepare_length = prepare_length
        self._scenes: list[_Scene] = []
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        self._cards = QVBoxLayout()
        self._cards.setSpacing(6)
        column.addLayout(self._cards)
        self._add = QPushButton("Add scene")
        self._add.setToolTip("Another scene, run after this one from its last frame")
        self._add.clicked.connect(lambda: self.add_scene())
        column.addWidget(self._add, alignment=Qt.AlignmentFlag.AlignLeft)
        self.add_scene(frames=int(self._pd.default[0]))

    # --- the scenes ------------------------------------------------------------

    def add_scene(self, prompt: str = "", frames: int | None = None, lines: str = "") -> None:
        scene = _Scene(self._pd, self._prepare_length)
        scene.prompt.setPlainText(prompt)
        scene.lines.setPlainText(lines)
        scene.set_frames(int(self._pd.default[0]) if frames is None else frames)
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

    def scene_boxes(self) -> list[PromptBox]:
        return [scene.prompt for scene in self._scenes]

    def story(self) -> str:
        return story_of([diff_text.live_text(scene.prompt) for scene in self._scenes])

    def set_story(self, text: str) -> None:
        """Lay the story out one scene per text; the count of scenes follows it."""
        texts = scene_prompts(str(text))
        self._resize_to(len(texts))
        for scene, scene_text in zip(self._scenes, texts):
            diff_text.forget(scene.prompt)
            scene.prompt.setPlainText(scene_text)

    def scene_frames(self) -> list[int]:
        return [scene.frames() for scene in self._scenes]

    def set_scene_frames(self, frames) -> None:
        """Each scene's length; a list short of the scenes leaves the rest as
        they are, and one past them is cut to fit."""
        for scene, count in zip(self._scenes, list(frames or [])):
            scene.set_frames(int(count))

    def lines(self) -> list[str]:
        return [diff_text.live_text(scene.lines) for scene in self._scenes]

    def set_lines(self, lines) -> None:
        for scene, text in zip(self._scenes, list(lines or [])):
            scene.lines.setPlainText(str(text))

    def total_frames(self) -> int:
        """The clip's length: the scenes end to end, each after the first
        starting on the frame before it."""
        return chained_frames(self.scene_frames())
