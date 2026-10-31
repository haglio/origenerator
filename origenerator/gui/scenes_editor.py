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
lines param, and its cards carry no lines field.

A scene is one thing or the other, and the card says which. The speech model
renders a talking performance and nothing else: measured on his own settings, a
speaking scene moves under half as much as the same scene on the experts, with
the movement at the head, and driving it with the scene rendered properly
(control_video, skeletons or frames) lifts that a little without carrying the
action. So the moment a scene has a line, its two prompts go read-only and
dim -- a field you can type into that changes nothing is the trap this spent a
night in. Clearing the line gives them back.
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
from shared_ui.spacing import GAP_MEDIUM, GAP_SMALL

from origenerator.gui import diff_text, tracked_prompt
from origenerator.gui.eliding import ElidingLabel
from origenerator.gui.icons import tab_close_icon
from origenerator.gui.panes import border_as_a_set
from origenerator.gui.param_help import param_help
from origenerator.gui.preset_combo import PresetComboBox
from origenerator.gui.prompt_field import PromptField, set_in_use
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
# What a prompt's caption gains, and what it says instead of its own help, while
# the scene it belongs to has a line.
SPEAKING_NOTE = " — not used while this scene speaks"
SPEAKING_HELP = ("A scene with a line renders on the speech model, and all that "
                 "happens in it is her speaking — it will not act a prompt out. "
                 "Clear Her Lines to write this scene instead.")
# The prompts a line takes over. Its own field is never one of them.
SPOKEN_OVER = ("positive_prompt", "negative_prompt")

# The texts a scene carries, by the param each is stored as, with the caption
# over its field. The prompts are stored as stories (see the module above); the
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
                 shut_down: dict[str, str], lines: bool = True, parent=None):
        super().__init__(parent)
        self._pd = pd
        self._shut_down = shut_down
        column = QVBoxLayout(self)
        border_as_a_set(self, column)
        column.setSpacing(GAP_SMALL)
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
        self.remove.setIcon(tab_close_icon())
        self.remove.setIconSize(QSize(mark, mark))
        self.remove.setCursor(Qt.CursorShape.PointingHandCursor)
        self.remove.clicked.connect(lambda: self.remove_requested.emit(self))
        header.addWidget(self.remove)
        column.addLayout(header)
        # Captioned, since three fields in a row say nothing about which is which
        # once they hold text; each carries its param's own help.
        self.fields: dict[str, PromptField] = {}
        self.captions: dict[str, ElidingLabel] = {}
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
        if lines:
            self.fields["scene_lines"].setPlaceholderText(LINES_PLACEHOLDER)
            # Every path that fills a line -- typing, loading settings, a voice
            # edit -- ends in textChanged, so the card follows all of them.
            self.fields["scene_lines"].textChanged.connect(self.reflect_use)
        self.reflect_use()
        self.length.editTextChanged.connect(self.changed)
        self.length.edited.connect(self._settle)

    def speaking(self) -> bool:
        """Whether this scene has a line, and so renders as her speaking."""
        field = self.fields.get("scene_lines")
        return field is not None and bool(diff_text.live_text(field).strip())

    def reflect_use(self) -> None:
        speaking = self.speaking()
        for key in SPOKEN_OVER:
            set_in_use(self.fields[key], self.captions[key],
                       SPEAKING_HELP if speaking else self._shut_down.get(key), param_help(key))
            self.captions[key].setText(TEXT_CAPTIONS[key] + (SPEAKING_NOTE if speaking else ""))

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
                 prepare_length: Callable[[PresetComboBox], None], shut_down: dict[str, str],
                 lines: bool = True, parent=None):
        super().__init__(parent)
        self._pd = frames_def
        self._prepare_length = prepare_length
        # Whether the workflow speaks: a card of one that cannot has no lines field.
        self._lines = lines
        self._shut_down = shut_down
        self._scenes: list[_Scene] = []
        column = QVBoxLayout(self)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(GAP_MEDIUM)
        self._cards = QVBoxLayout()
        self._cards.setSpacing(GAP_MEDIUM)
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
        scene = _Scene(self._pd, self._prepare_length, self._shut_down, lines=self._lines)
        if self._scenes:
            scene.fields["negative_prompt"].setPlainText(
                diff_text.live_text(self._scenes[-1].fields["negative_prompt"]))
        scene.set_frames(int(self._pd.default[0]))
        scene.changed.connect(self.changed)
        scene.remove_requested.connect(self.remove_scene)
        self._scenes.append(scene)
        self._cards.addWidget(scene)
        self._renumber()
        self.changed.emit()

    def reflect_use(self) -> None:
        for scene in self._scenes:
            scene.reflect_use()

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

    def fields(self, key: str) -> list[PromptField]:
        """Every scene's field for the text stored as ``key``, in story order."""
        return [scene.fields[key] for scene in self._scenes if key in scene.fields]

    def text_fields(self) -> list[PromptField]:
        """Every field on every card, in reading order: what a find searches."""
        return [field for scene in self._scenes for field in scene.fields.values()]

    def fields_beside_their_texts(self, stored: dict) -> list[tuple[PromptField, str | None]]:
        return [(field, scene_text(scene_prompts(stored[key]), index)
                 if isinstance(stored.get(key), str) else None)
                for index, scene in enumerate(self._scenes)
                for key, field in scene.fields.items()]

    def story(self, key: str) -> str:
        """The one prompt that stores every scene's ``key`` text."""
        return story_of([diff_text.live_text(field) for field in self.fields(key)])

    def set_story(self, key: str, text: str) -> None:
        """Lay a stored prompt out one scene per text. The positive prompt is
        the story, so the count of scenes follows it; a negative with fewer
        texts than scenes carries its last text on through the rest, which is
        what the graph keeps out of them (WorkflowTemplate.scene_prompt_nodes),
        so what the cards show is what renders."""
        texts = scene_prompts(str(text))
        if key == "positive_prompt":
            self._resize_to(len(texts))
        for index, field in enumerate(self.fields(key)):
            tracked_prompt.write(field, scene_text(texts, index))

    def scene_frames(self) -> list[int]:
        return [scene.frames() for scene in self._scenes]

    def set_scene_frames(self, frames) -> None:
        """Each scene's length; a list short of the scenes leaves the rest as
        they are, and one past them is cut to fit."""
        for scene, count in zip(self._scenes, list(frames or []), strict=False):
            scene.set_frames(int(count))

    def lines(self) -> list[str]:
        return [diff_text.live_text(field) for field in self.fields("scene_lines")]

    def set_lines(self, lines) -> None:
        for field, text in zip(self.fields("scene_lines"), list(lines or []), strict=False):
            tracked_prompt.write(field, str(text))

    def total_frames(self) -> int:
        """The clip's length: the scenes end to end, each after the first
        starting on the frame before it."""
        return chained_frames(self.scene_frames())

    def set_total_frames(self, frames: int) -> None:
        self.set_scene_frames(chained_to(int(frames), self.scene_frames(), int(self._pd.min_val)))
