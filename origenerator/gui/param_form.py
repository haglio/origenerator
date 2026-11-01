from __future__ import annotations

import random
from collections.abc import Callable, Sequence
from pathlib import Path

from PyQt6.QtCore import QEvent, QSize, Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shared_ui.icons import qt_icon
from shared_ui.orientation import orientation_of_size
from shared_ui.spacing import BUTTON_ICON, GAP_MEDIUM, GAP_SMALL
from shared_ui.tick_control import TickControl

from origenerator.base_models import loras_offered_beside
from origenerator.box_breaks import unboxed
from origenerator.config import COMFYUI_INPUT_DIR, OUTPUT_PLACES
from origenerator.gallery.sides import SIDE_LABELS
from origenerator.gui import diff_text, icons, param_sections, tracked_prompt
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.drop_slot import DropSlot
from origenerator.gui.eliding import ElidingButton, ElidingLabel
from origenerator.gui.file_pick import pick_a_file
from origenerator.gui.label_cells import LabelCell, LabelColumn
from origenerator.gui.no_wheel import NoWheelSpinBox
from origenerator.gui.param_fields import NOT_KNOWN, field_kind, grey_out_of_reach, offer_only
from origenerator.gui.param_help import (
    advice_help,
    definition_help,
    option_help,
    param_help,
    with_training_date,
)
from origenerator.gui.preset_combo import PresetComboBox
from origenerator.gui.prompt_boxes import PromptBoxes, set_in_use
from origenerator.gui.request_field import RequestField
from origenerator.gui.scenes_editor import ScenesEditor
from origenerator.gui.stylesheet import CHOSEN
from origenerator.gui.tooltip_shape import shaped
from origenerator.gui.training_controls import TrainingControls
from origenerator.gui.warning_mark import WarningMark
from origenerator.gui.zone_items import FilesOnly
from origenerator.lora_training import TrainingOffer
from origenerator.prompt_tokens import PromptReading
from origenerator.seed_history import SeedHistory
from origenerator.setting_advice import Advice, MissingTriggerWords
from origenerator.speech import CUSTOM_VOICE
from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.derived_size import override_size
from origenerator.workflows.lora_rows import lora_key_of, strength_without_its_lora

_SEED_MAX = (1 << 63) - 1
# The params one scenes editor speaks for: the story (stored as the positive
# prompt), what each scene keeps out (stored as the negative prompt), each
# scene's length, each scene's lines, and the clip's length they add up to.
_SCENE_KEYS = ("positive_prompt", "negative_prompt", "scene_frames", "scene_lines",
               "frame_count")

def _speaks(values) -> bool:
    return any(str(line).strip() for line in values.get("scene_lines") or [])


def _all_speak(values) -> bool:
    lines = values.get("scene_lines") or []
    return bool(lines) and all(str(line).strip() for line in lines)


def _pushes_the_prompt(values) -> bool:
    strengths = [values[key] for key in ("cfg", "cfg_high", "cfg_low") if key in values]
    return not strengths or any(float(strength) != 1.0 for strength in strengths)


STRENGTH_ONE_HELP = ("Prompt Strength is 1, so the Negative Prompt is not used. "
                     "Raise Prompt Strength above 1 to use it.")
BOTH_STRENGTHS_ONE_HELP = ("Both Prompt Strengths are 1, so the Negative Prompt is not used. "
                           "Raise either one above 1 to use it.")
EVERY_SCENE_SPEAKS_HELP = ("Every scene has a line, so the sound is her speaking and this "
                           "prompt is not used. Clear Her Lines on a scene to use it.")


def _strength_one_help(values) -> str:
    return STRENGTH_ONE_HELP if "cfg" in values else BOTH_STRENGTHS_ONE_HELP


_SHOWN_WHILE = {
    "voice": _speaks,
    "voice_sample": lambda values: _speaks(values) and values.get("voice") == CUSTOM_VOICE,
    "voice_sample_text": lambda values: _speaks(values) and values.get("voice") == CUSTOM_VOICE,
    "unet_s2v": _speaks,
}

_SOUND_IN_USE = (lambda values: not _all_speak(values), lambda values: EVERY_SCENE_SPEAKS_HELP)
_IN_USE_WHILE = {
    "negative_prompt": (_pushes_the_prompt, _strength_one_help),
    "audio_prompt": _SOUND_IN_USE,
    "audio_negative_prompt": _SOUND_IN_USE,
}

# The locked-dimension spinners span from a stride floor up past any realistic
# derived or overridden size; 0 is reserved as "no size known yet" (shown as the
# em dash) for a workflow whose input image can't be measured.
_DIMENSION_MAX = 8192
_DIMENSION_STEP = 16
# The unlock toggle's face: a closed padlock while the derived size is locked, an
# open one once the user has unlocked it to override.
_PADLOCK = {False: "lock", True: "unlock"}

class ParamForm(QWidget):
    """The editable settings for one workflow, grouped into collapsible sections.

    A workflow's :meth:`~origenerator.workflows.base.WorkflowTemplate.
    param_definitions` gives the fields; they're laid out by the canonical order
    in :mod:`origenerator.gui.param_sections` — not the workflow's own declaration
    order — so every workflow presents the same kinds of settings in the same
    sections, in the same place. Params a config carries but this workflow lays no
    field for (its hidden VAE/CLIP, an import's extras) round-trip untouched and
    are never shown.

    ``hidden_keys`` are params this form deliberately doesn't present at all —
    no field, and no value absorbed from a loaded config: they
    are pinned at the workflow's own defaults, so what the form emits for them
    is always the same. This is how the enhance params stay off a form whose
    every other setting decides which gallery folder a run lands in. They belong
    to the Enhance subpanel, which applies enhancement as a separate layer — and
    pinning them is what stops a Generate seeded from an old enhanced run coming
    out enhanced again with the subpanel's tick unticked.

    ``pins_reused_seed`` is the workflow's answer to
    :meth:`~origenerator.workflows.base.WorkflowTemplate.pins_reused_seed`:
    whether a seed written in by :meth:`set_values` also clears its Random tick.
    False (video) leaves the tick ticked and a fresh seed in the field, so the
    settings of a clip loaded into a tab don't quietly pin every later run to its
    seed.
    """

    changed = pyqtSignal()          # any field's value changed
    train_requested = pyqtSignal(str)  # a LoRA row's Train was pressed (its key)
    text_fields_changed = pyqtSignal()
    seed_drawn = pyqtSignal(str, object)
    item_activated = pyqtSignal(str)  # a zone's held gallery item was clicked (prompt_id)

    def __init__(
        self,
        param_defs: list[ParamDef],
        parent=None,
        *,
        size_deriver: Callable[[dict], tuple[int, int] | None] | None = None,
        size_source: str = "input_image",
        hidden_keys: tuple[str, ...] = (),
        pins_reused_seed: bool = True,
        heights=None,
        seed_history: SeedHistory | None = None,
        items=None,
        lora_keys: tuple[str, ...] = (),
    ):
        super().__init__(parent)
        self._lora_keys = tuple(lora_keys)
        self._training_controls: dict[str, TrainingControls] = {}
        # Where a dragged prompt height is filed: the window's own set, handed
        # down rather than reached for, so a form can be built at chosen sizes.
        self._heights = heights
        self._seed_history = seed_history
        self._items = items or FilesOnly(places=OUTPUT_PLACES, input_dir=COMFYUI_INPUT_DIR)
        self._item_seeds: dict[str, int] = {}
        self._item_thumbnail: str | None = None
        self._pins_reused_seed = pins_reused_seed
        # Params carried but never shown, pinned at the definitions' own defaults
        # — a loaded config never moves them (see the class docstring).
        self._hidden_keys = frozenset(hidden_keys)
        self._hidden = {
            pd.key: pd.default for pd in param_defs if pd.key in self._hidden_keys
        }
        # When set (an i2v workflow), the output size is derived from the input
        # image: the form shows a locked width/height pair filled from this
        # callable, which the user can unlock to override. ``None`` for a
        # manual-size or size-less workflow, leaving the Dimensions section to the
        # workflow's own width/height params (if any).
        self._size_deriver = size_deriver
        # The field the size is derived from: its edits refresh the pair.
        self._size_source_key = size_source
        # The unlock toggle and hint for the derived-size pair, built only in
        # derived mode. ``None`` otherwise. The toggle floats between the width and
        # height rows like the swap button, so it links the pair without shrinking
        # either field.
        self._unlock_btn: QToolButton | None = None
        self._dimensions_hint: QLabel | None = None
        # Per derived dimension: the editable spinner (in ``_widgets``), the plain
        # value label shown while locked, and the stack that swaps between them.
        self._dim_value_labels: dict[str, QLabel] = {}
        self._dim_stacks: dict[str, QStackedWidget] = {}
        self._widgets: dict[str, QWidget] = {}
        self._randomize_checks: dict[str, TickControl] = {}
        self._browse_buttons: dict[str, QPushButton] = {}
        # Copy-to-clipboard buttons on the fields worth lifting whole — the prompts
        # and the seeds, the read-only inspect pane's copy targets before it merged
        # into this editable form.
        self._copy_buttons: dict[str, CopyButton] = {}
        self._warning_marks: dict[str, WarningMark] = {}
        self._advice: dict[str, Advice | MissingTriggerWords] = {}
        self._labels: dict[str, ElidingLabel] = {}
        self._recommendations: dict[str, str] = {}
        # A single swap-width-and-height button, built only when the workflow has
        # both dimension params (t2i does; i2v derives its size in-graph). None
        # when absent, so callers can tell whether the control exists. It floats as
        # a free child of the Dimensions section, so it folds away with it.
        self._swap_dimensions_btn: QPushButton | None = None
        # Params a config carries but this form has no widget for — the workflow's
        # remaining hidden settings (VAE, CLIP…), or an import's extras. The form
        # round-trips whatever value it was given, so reusing a generation
        # reproduces them, without showing them.
        self._passthrough: dict = {}
        self._sections: dict[str, CollapsibleSection] = {}
        self._request_field: RequestField | None = None
        # The keys occupying each section, in row order.
        self._present_keys: dict[str, list[str]] = {}
        self._shut_down: dict[str, str] = {}
        self._param_defs = [pd for pd in param_defs if pd.key not in self._hidden_keys]
        self._defs = {pd.key: pd for pd in self._param_defs}
        # A workflow that tells a story in scenes hands both prompts, the scene
        # lengths and the lines to one editor (see origenerator.gui.scenes_editor);
        # None for a workflow with one prompt and one length.
        scenes_def = next((pd for pd in self._param_defs if pd.type == ParamType.SCENES), None)
        self._scenes: ScenesEditor | None = None
        self._scenes_row = scenes_def.key if scenes_def is not None else None
        if scenes_def is not None:
            self._scenes = ScenesEditor(
                scenes_def, lambda w, pd=scenes_def: grey_out_of_reach(pd, w), self._shut_down,
                lines=any(pd.key == "scene_lines" for pd in self._param_defs))
            self._scenes.changed.connect(self.changed)
        self._build()
        self._wire_row_rules()
        for pd in self._seed_defs():
            self._draw(pd)
        self.changed.connect(self._describe_seed_fields)
        self._describe_seed_fields()
        self.changed.connect(self._explain_lora_picks)
        self.changed.connect(self._show_the_shape)
        self._show_the_shape()

    def _show_the_shape(self) -> None:
        size = self.output_size()
        if size is None:
            self._sections["Size"].set_mark(None, "")
            return
        orientation = orientation_of_size(*size)
        tip = SIDE_LABELS[orientation]
        if size[0] == size[1]:
            tip = f"Square, so it goes under {tip}"
        self._sections["Size"].set_mark(icons.side_mark(orientation), tip)

    def _wire_row_rules(self):
        self.changed.connect(self._refresh_row_rules)
        self._refresh_row_rules()

    def _refresh_row_rules(self):
        values = {pd.key: self._read_field(pd) for pd in self._param_defs}
        for row, shows in _SHOWN_WHILE.items():
            if row in self._widgets:
                self._set_row_visible(row, shows(values))
        for row in self._widgets:
            if lora_key_of(row) in values:
                self._set_row_visible(row, not strength_without_its_lora(row, values))
        for pd in self._param_defs:
            if pd.beside_model in values:
                offer_only(pd, self._widgets[pd.key],
                           loras_offered_beside(values[pd.beside_model], pd.options))
        for row, (in_use, shut_down_help) in _IN_USE_WHILE.items():
            if row not in self._widgets:
                continue
            if in_use(values):
                self._shut_down.pop(row, None)
            else:
                self._shut_down[row] = shut_down_help(values)
            if self._widgets[row] is not self._scenes:
                self._explain(row)
        if self._scenes is not None:
            self._scenes.reflect_use()

    def _set_row_visible(self, key: str, visible: bool) -> None:
        """Show or hide one row, label and field together."""
        title = param_sections.section_title(key)
        keys = self._present_keys.get(title, [])
        if key in keys:
            self._sections[title].content_form().setRowVisible(keys.index(key), visible)

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(GAP_MEDIUM)

        specs = [(s.title, s.collapsed) for s in param_sections.SECTIONS]
        specs.append((param_sections.OTHER_TITLE, param_sections.OTHER_COLLAPSED))
        for title, collapsed in specs:
            section = CollapsibleSection(title, collapsed=collapsed)
            section.toggled.connect(self._position_dimension_controls)
            section.warning.pressed.connect(
                lambda title=title: self._resolve_warnings(self._present_keys[title]))
            self._sections[title] = section
            self._present_keys[title] = []
            outer.addWidget(section)
            if title == "Prompts" and any(pd.key == "positive_prompt" for pd in self._param_defs):
                outer.addWidget(self._build_request_section())
        outer.addStretch(1)  # collect any slack at the foot, not between sections

        # Fields in canonical order, so the workflow's own declaration order can't
        # reshuffle where a setting lands.
        for pd in sorted(self._param_defs, key=lambda d: param_sections.key_rank(d.key)):
            widget = self._make_widget(pd)
            self._widgets[pd.key] = widget
            if widget is self._scenes:
                if pd.type == ParamType.SCENES:  # the editor's one row, under the scenes' own key
                    self._add_row(pd.key, pd.label, widget)
                continue
            if isinstance(widget, PresetComboBox):
                widget.edited.connect(lambda pd=pd: self._settle(pd))
            self._add_row(pd.key, pd.label, widget, self._make_extras(pd))
        for pd in self._param_defs:
            if pd.rate and self._widgets[pd.key] is not self._scenes:
                # A frame count is made as seconds, so show it as seconds — its
                # widget was left blank until the conversion was available.
                self._write_field(pd, pd.default)
        self._build_swap_button()
        self._build_derived_dimensions()
        self._announce_every_edit()
        self._refresh_section_visibility()

    def _build_request_section(self) -> CollapsibleSection:
        """The words the image on display is asked to change by, right under
        the prompts they rewrite."""
        section = CollapsibleSection("Request")
        self._request_field = RequestField()
        section.content_form().addRow(self._request_field)
        return section

    def request_field(self) -> RequestField | None:
        return self._request_field

    def tells_a_story(self) -> bool:
        return self._scenes is not None

    def set_prompts(self, positive: str, negative: str, *, typed: bool = False) -> None:
        """Write a prompt pair into its fields, as typing it in would."""
        for pd in self._param_defs:
            if pd.key not in ("positive_prompt", "negative_prompt"):
                continue
            said = positive if pd.key == "positive_prompt" else negative
            widget = self._widgets[pd.key]
            if typed and isinstance(widget, PromptBoxes):
                widget.edit(said)
            else:
                self._write_field(pd, said)

    def _announce_every_edit(self):
        for pd in self._param_defs:
            widget = self._widgets[pd.key]
            if widget is self._scenes:
                continue
            edited = self._kind(pd).change_signal(widget)
            if pd.key == self._size_source_key:
                edited.connect(self._update_derived_display)
            edited.connect(self.changed)

    def _add_row(self, key: str, label: str, field: QWidget, extras: Sequence[QWidget] = ()):
        """Insert one row (an input or a read-only value, then its ``extras``)
        into its section at the canonical position among the rows already there,
        its label after the slot its warning mark shows in.

        The row's help (see :mod:`origenerator.gui.param_help`) goes on its label
        as well as its input: the label is what you are looking at when you
        wonder what a setting is, and hovering the word is the natural move.

        The label elides. A phrase like "Enhance Redraw Amount" asks for three
        hundred pixels on one line, and a plain label hands that on as a floor under
        the whole form — which is how a narrow pane ended up scrolling sideways
        instead of squeezing its fields."""
        title = param_sections.section_title(key)
        keys = self._present_keys[title]
        index = self._insert_index(keys, key)
        form = self._sections[title].content_form()
        label_widget = ElidingLabel(label)
        form.insertRow(index, self._label_cell(key, label_widget, form.label_column),
                       self._field_cell(field, extras))
        keys.insert(index, key)
        self._labels[key] = label_widget
        self._explain(key)

    def _explain(self, key: str) -> None:
        help_text, label, widget = self._help(key), self._labels[key], self._widgets.get(key)
        if isinstance(widget, PromptBoxes):
            set_in_use(widget, label, self._shut_down.get(key), help_text)
            return
        label.setToolTip(help_text or label.text())
        if widget is not None and help_text and not isinstance(widget, DropSlot):
            if key in self._lora_keys:
                help_text = with_training_date(help_text, self._read_field(self._defs[key]))
            widget.setToolTip(help_text)  # a zone's tooltip names what it holds

    def _explain_lora_picks(self) -> None:
        for key in self._lora_keys:
            if key in self._labels:
                self._explain(key)

    def _help(self, key: str) -> str:
        pd = self._defs.get(key)
        if pd is None:
            return param_help(key)
        warned_here = [other for other in self._param_defs
                       if other.key != key and self._row_of(other.key) == key]
        return " ".join(filter(None, [
            definition_help(pd, self._recommendations.get(key, "")),
            *(advice_help(other, self._recommendations.get(other.key, ""))
              for other in warned_here)]))

    def show_readings(self, readings: dict[str, PromptReading | None]) -> None:
        for key, widget in self._widgets.items():
            if isinstance(widget, PromptBoxes):
                widget.set_reading(readings.get(key))
        if self._scenes is not None:
            self._scenes.show_readings(readings)

    def explain(self, recommendations: dict[str, str]) -> None:
        self._recommendations = dict(recommendations)
        for key in self._labels:
            self._explain(key)

    @staticmethod
    def _insert_index(present: list[str], key: str) -> int:
        """The row index ``key`` belongs at among ``present`` (kept in canonical
        order): the count of present keys that rank before it."""
        rank = param_sections.key_rank(key)
        return sum(1 for k in present if param_sections.key_rank(k) < rank)

    def _refresh_section_visibility(self):
        """Show a section iff it holds any row; empty ones take no space. Then
        re-place the floating dimension control, since the sections above it may
        have moved."""
        for title, section in self._sections.items():
            section.setVisible(bool(self._present_keys[title]))
        self._position_dimension_controls()

    def _field_cell(self, field: QWidget, extras: Sequence[QWidget]) -> QHBoxLayout:
        """The input, then its trailing controls.

        The copy button leads (just right of the input), then the Random tick
        (seed) or the Browse button (image). Each sits in a shared cell so the
        label column stays aligned across every row. Next to a tall multiline
        prompt the copy button hugs the top corner; next to a single-line seed
        it centers so it lines up with the tick beside it.
        """
        cell = QHBoxLayout()
        cell.setContentsMargins(0, 0, 0, 0)
        cell.addWidget(field, 1)
        multiline = isinstance(field, PromptBoxes)
        for extra in extras:
            if isinstance(extra, CopyButton) and multiline:
                cell.addWidget(extra, 0, Qt.AlignmentFlag.AlignTop)
            else:
                cell.addWidget(extra)
        return cell

    def _make_extras(self, pd: ParamDef) -> list[QWidget]:
        # Copy leads so it reads [field] [copy] [Random]/[Browse].
        kind = self._kind(pd)
        extras: list[QWidget] = []
        if kind.copyable:
            copy = CopyButton(lambda pd=pd: unboxed(str(self._read_field(pd))))
            self._copy_buttons[pd.key] = copy
            extras.append(copy)
        if kind.randomizable:
            cb = TickControl("Random")
            cb.setChecked(True)
            cb.toggled.connect(self.changed)
            cb.clicked.connect(lambda checked, pd=pd: self._on_random_clicked(pd, checked))
            self._widgets[pd.key].activated.connect(lambda _row, cb=cb: cb.setChecked(False))
            self._randomize_checks[pd.key] = cb
            extras.append(cb)
        if kind.browse_filter and not kind.drops:
            # Elides: it is the widest thing on any row, so a plain button would
            # decide how narrow the whole form can be squeezed.
            browse = ElidingButton("Browse...")
            browse.clicked.connect(
                lambda _checked=False, key=pd.key: self._browse_file(key)
            )
            self._browse_buttons[pd.key] = browse
            extras.append(browse)
        if pd.key in self._lora_keys:
            controls = TrainingControls()
            controls.train_requested.connect(lambda key=pd.key: self.train_requested.emit(key))
            self._training_controls[pd.key] = controls
            extras.append(controls)
        return extras

    def offer_training(self, key: str, offer: TrainingOffer | None, running: str | None = None) -> None:
        self._training_controls[key].show_offer(offer, running)

    def _label_cell(self, key: str, label: QWidget, column: LabelColumn) -> LabelCell:
        mark = WarningMark()
        mark.pressed.connect(lambda: self._resolve_warnings([key]))
        self._warning_marks[key] = mark
        return LabelCell(mark, label, column)

    def _resolve_warnings(self, rows: list[str]) -> None:
        for row in rows:
            for key, found in self._advised_at([row]):
                self._take_advice(key, found)

    def _take_advice(self, key: str, found: Advice | MissingTriggerWords) -> None:
        written = found.writes or key
        widget = self._widgets.get(written)
        if isinstance(widget, PromptBoxes):
            widget.rewrite(found.fixed)
            return
        fixed = found.fixed(self._read_field(self._defs[written]))
        if written == "frame_count" and self._scenes is not None:
            self._scenes.set_total_frames(fixed)
        else:
            self._write_field(self._defs[written], fixed)

    def mark_recommended(self, choices: dict[str, tuple[str, ...]]) -> None:
        for key, good in choices.items():
            dropdown = self._widgets.get(key)
            if isinstance(dropdown, QComboBox):
                for index in range(dropdown.count()):
                    option = dropdown.itemText(index)
                    help_text = option_help(key, option) or ""
                    recommended = option in good
                    dropdown.setItemIcon(index, icons.thumbs_up_icon() if recommended
                                         else icons.unmarked_icon())
                    dropdown.setItemData(index, shaped(help_text, lead="Recommended.")
                                         if recommended else help_text or None,
                                         Qt.ItemDataRole.ToolTipRole)

    def set_warnings(self, advice: dict[str, Advice | MissingTriggerWords]) -> None:
        self._advice = {key: found for key, found in advice.items()
                        if self._row_of(key) in self._labels}
        for row, mark in self._warning_marks.items():
            mark.warn(self._warning(row))
        for title, section in self._sections.items():
            section.warning.warn(self._warnings_about(self._present_keys[title]))

    def _row_of(self, key: str) -> str:
        return self._scenes_row if self._scenes is not None and key in _SCENE_KEYS else key

    def _advised_at(self, rows) -> list[tuple[str, Advice | MissingTriggerWords]]:
        advised = {key: found for row in rows for key, found in self._advice.items()
                   if row in self._rows_warning(key, found)}
        return list(advised.items())

    def _rows_warning(self, key: str, found: Advice | MissingTriggerWords) -> set[str]:
        return {self._row_of(shown) for shown in (key, found.writes) if shown}

    def every_warning(self) -> str:
        return self._warnings_about(self._keys_in_order())

    def resolve_every_warning(self) -> None:
        self._resolve_warnings(self._keys_in_order())

    def _keys_in_order(self) -> list[str]:
        return [key for keys in self._present_keys.values() for key in keys]

    def _warning(self, row: str) -> str:
        return "\n".join(found.said for _key, found in self._advised_at([row]))

    def _warnings_about(self, rows: list[str]) -> str:
        return "\n".join(f"{self._labels[self._row_of(key)].text()}: {found.value_shown}. "
                         f"{found.said}" for key, found in self._advised_at(rows))

    def track_prompt_rewrites(self, made_with: dict | None = None) -> None:
        """Mark every prompt on the form as a rewrite of ``made_with``'s text for
        it, a scene's of its own part of the story, or of what it says right now
        where that holds none (:mod:`origenerator.gui.tracked_prompt`).

        Every prompt rather than a named pair: a workflow that grows another one
        (the Foley audio prompts did) is marked the day it lands, for the same
        reason :meth:`text_fields` asks the widgets what they are.
        """
        made_with = made_with or {}
        scenes = (self._scenes.fields_beside_their_texts(made_with)
                  if self._scenes is not None else [])
        for widget, was in scenes:
            tracked_prompt.track(
                widget, was if isinstance(was, str) else diff_text.live_text(widget))
        for key, widget in self._widgets.items():
            if isinstance(widget, PromptBoxes):
                was = made_with.get(key)
                widget.track(was if isinstance(was, str) else widget.value())

    def clear_prompt_rewrites(self) -> None:
        """Stop tracking every field, leaving each an ordinary prompt input."""
        for field in self._scenes.text_fields() if self._scenes is not None else []:
            tracked_prompt.untrack(field)
        for widget in self._widgets.values():
            if isinstance(widget, PromptBoxes):
                widget.untrack()

    def text_fields(self) -> list[QPlainTextEdit]:
        """The form's multiline text inputs — its prompts — in the order they lay
        out down the form.

        Every prompt this app has is a multiline ``str`` field (positive, negative,
        and the Foley audio pair) and nothing else is one, so asking the widgets
        what they are rather than naming keys means a workflow that grows another
        prompt is searchable the day it lands. What Ctrl+F searches.
        """
        scenes = self._scenes.text_fields() if self._scenes is not None else []
        return scenes + [box for widget in self._widgets.values()
                         if isinstance(widget, PromptBoxes) for box in widget.boxes()]

    def drop_slots(self) -> tuple[DropSlot, ...]:
        return tuple(w for w in self._widgets.values() if isinstance(w, DropSlot))

    def _has_param(self, key: str) -> bool:
        return key in self._defs

    def _build_swap_button(self):
        """Add a swap-width-and-height button when the form has both dimensions.

        It floats in a gutter opened to the left of the two labels, midway between
        their rows, so it reads as linking the pair rather than trailing either
        field. As a free child of the Dimensions section's content (not a form
        cell) it folds away with the section and needs manual placement — see
        :meth:`_position_swap_button`. Absent for a workflow that derives its size
        in-graph (i2v) and so has no dimensions to swap.
        """
        if not (self._has_param("width") and self._has_param("height")):
            return
        content = self._sections["Size"].content()
        btn = QPushButton(content)
        btn.setIcon(qt_icon("flip_ends"))
        btn.setToolTip("Swap width and height")
        btn.clicked.connect(self.swap_dimensions)
        btn.adjustSize()
        self._swap_dimensions_btn = btn
        # The section's content lays its rows out on its own resize/show; follow
        # those so the free-floating button tracks them even when it unfolds.
        content.installEventFilter(self)

    def _center_between_dimension_rows(self, btn, top_row, lower_row):
        """Center ``btn`` between the width and height rows, inside a left gutter
        reserved for it so it sits clear of the "Width"/"Height" labels.

        The gutter is the section's left margin, sized to the button here (its
        final width isn't known until its font and stylesheet apply, after
        construction). Squeezing the button into whatever space the labels
        happened to leave is what put it on top of the words. In the Dimensions
        content's coordinates, the button's parent; called on every
        resize/show/toggle since a free child gets no help from the layout, and
        a no-op while the section is folded (the button hides with it).

        ``top_row`` and ``lower_row`` are the two rows to sit between, which
        differ by form: the spinners themselves where the size is typed, and the
        stacks holding a derived size's plain reading where it is not.
        """
        if self._sections["Size"].is_collapsed():
            return
        btn.adjustSize()
        gutter = btn.width() + 10  # room for the button plus a gap to the labels
        form = self._sections["Size"].content_form()
        if form.contentsMargins().left() != gutter:
            # Push the labels over to open the gutter; the relayout re-invokes us
            # with the rows in their new positions.
            form.setContentsMargins(gutter, GAP_SMALL, 0, GAP_SMALL)
            return
        top, lower = top_row.geometry(), lower_row.geometry()
        y = (top.center().y() + lower.center().y()) // 2 - btn.height() // 2
        btn.move(max(0, (gutter - btn.width()) // 2), y)
        btn.raise_()

    def _position_swap_button(self):
        """Place the swap button, which sits between the two spinners a typed
        size is entered in. A no-op on a derived-size form, which has none."""
        if self._swap_dimensions_btn is None:
            return
        self._center_between_dimension_rows(
            self._swap_dimensions_btn,
            self._widgets["width"], self._widgets["height"])

    def eventFilter(self, obj, event):
        # Installed on the Dimensions content: re-place the floating control (swap
        # or unlock) whenever that content relays out (unfolding, or widening).
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._position_dimension_controls()
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_dimension_controls()

    def showEvent(self, event):
        super().showEvent(event)
        self._position_dimension_controls()

    def _position_dimension_controls(self):
        """Re-place whichever free-floating control the Dimensions section carries:
        the swap button (manual-size workflow) or the unlock toggle (derived-size
        workflow). Each no-ops when its control is absent, so this is safe to call
        from every relayout hook regardless of which kind of form this is."""
        self._position_swap_button()
        self._position_unlock_button()

    def swap_dimensions(self):
        """Exchange the width and height field values."""
        width, height = self._widgets["width"], self._widgets["height"]
        w, h = width.value(), height.value()
        width.setValue(h)
        height.setValue(w)

    # --- derived dimensions: the input-image size, shown locked & unlockable ---

    def _build_derived_dimensions(self):
        """For a size-deriving workflow, add a width/height pair to the Dimensions
        section that reads as plain values while locked (like the read-only
        passthrough rows — "864", not an input field) and turns into editable
        spinners when unlocked. A floating padlock toggle, centered between the
        two rows in a reserved left gutter so it clears the labels, does the
        unlocking. A no-op for a workflow that sets its size by hand (its own
        width/height params already fill this section) or has none.
        """
        if self._size_deriver is None:
            return
        for key, label_text in (("width", "Width"), ("height", "Height")):
            spinner = NoWheelSpinBox()
            spinner.setMinimum(0)  # 0 == "size not yet known", shown as the em dash
            spinner.setMaximum(_DIMENSION_MAX)
            spinner.setSingleStep(_DIMENSION_STEP)
            spinner.setSpecialValueText(NOT_KNOWN)
            spinner.valueChanged.connect(self.changed)
            self._widgets[key] = spinner
            value_label = QLabel(NOT_KNOWN)
            value_label.setObjectName("readonlyParamValue")  # match the passthrough rows
            self._dim_value_labels[key] = value_label
            # A stack so locking swaps the plain value for the spinner in place,
            # keeping the row's height and position steady.
            stack = QStackedWidget()
            stack.addWidget(value_label)   # index 0: locked, a plain value
            stack.addWidget(spinner)           # index 1: unlocked, editable
            self._dim_stacks[key] = stack
            self._add_row(key, label_text, stack)
        self._dimensions_hint = QLabel(f"Sized from the {self._size_source()}. Unlock to override.")
        self._dimensions_hint.setObjectName("dimensionsHint")
        self._dimensions_hint.setWordWrap(True)
        self._sections["Size"].content_form().addRow(self._dimensions_hint)
        # A free-floating padlock toggle, parented to the Dimensions content so it
        # folds with the section; placed by :meth:`_position_unlock_button`.
        content = self._sections["Size"].content()
        btn = QToolButton(content)
        btn.setObjectName("dimensionUnlock")
        btn.setProperty(CHOSEN, True)
        btn.setCheckable(True)
        btn.setIcon(qt_icon(_PADLOCK[False]))
        btn.setIconSize(QSize(BUTTON_ICON, BUTTON_ICON))
        btn.setToolTip(self._unlock_tip(unlocked=False))
        btn.toggled.connect(self._on_dimensions_unlock_toggled)
        btn.adjustSize()
        self._unlock_btn = btn
        content.installEventFilter(self)  # follow the section's own relayouts
        self._update_derived_display()

    def _position_unlock_button(self):
        """Place the unlock toggle, which sits between the two rows a derived
        size is read in. A no-op on a manual-size form, which has no toggle."""
        if self._unlock_btn is None:
            return
        self._center_between_dimension_rows(
            self._unlock_btn,
            self._dim_stacks["width"], self._dim_stacks["height"])

    def _dimensions_unlocked(self) -> bool:
        """True when the user has unlocked the derived size to override it."""
        return self._unlock_btn is not None and self._unlock_btn.isChecked()

    def _size_source(self) -> str:
        source = self._defs.get(self._size_source_key)
        return source.label.lower() if source is not None else "image"

    def _unlock_tip(self, unlocked: bool) -> str:
        if unlocked:
            return f"Re-lock to the size derived from the {self._size_source()}"
        return f"Unlock to override the size derived from the {self._size_source()}"

    def _on_dimensions_unlock_toggled(self, unlocked: bool):
        """Flip the padlock and swap each dimension between its plain locked value
        and its editable spinner, re-locking back onto the derived size. Announces
        the change so the panel refreshes with it."""
        self._unlock_btn.setIcon(qt_icon(_PADLOCK[unlocked]))
        self._unlock_btn.setToolTip(self._unlock_tip(unlocked))
        for stack in self._dim_stacks.values():
            stack.setCurrentIndex(1 if unlocked else 0)
        if not unlocked:
            self._update_derived_display()
        self._position_unlock_button()  # the glyph swap can change the button's width
        self.changed.emit()

    def _update_derived_display(self):
        """Fill the locked width/height with the size the current input image
        derives — the plain value label and the spinner under it both, so
        unlocking starts from that value (0 → em dash when none can be measured).
        A no-op while unlocked, so it never clobbers a value the user is editing."""
        if self._size_deriver is None or self._dimensions_unlocked():
            return
        size = self._size_deriver(self.get_values())
        for key, value in zip(("width", "height"), size or (0, 0), strict=True):
            spinner = self._widgets[key]
            blocked = spinner.blockSignals(True)  # a display refresh isn't a user edit
            spinner.setValue(value)
            spinner.blockSignals(blocked)
            self._dim_value_labels[key].setText(str(value) if value else NOT_KNOWN)

    def _override_dimensions(self) -> dict:
        """The explicit width/height to emit — only when the pair is unlocked and
        holds a real size. Locked (the default), the form emits nothing so the
        payload derives the size in the usual way."""
        if not self._dimensions_unlocked():
            return {}
        width = self._widgets["width"].value()
        height = self._widgets["height"].value()
        return {"width": width, "height": height} if width > 0 and height > 0 else {}

    def _apply_dimension_values(self, params: dict):
        """Reflect a loaded config's size in the derived pair: an explicit
        width/height (a saved override) unlocks and shows them; their absence
        re-locks the pair onto the derived size."""
        override = override_size(params)
        self._unlock_btn.setChecked(override is not None)
        if override is not None:
            self._widgets["width"].setValue(override[0])
            self._widgets["height"].setValue(override[1])
        else:
            self._update_derived_display()

    def _browse_file(self, key: str):
        pd = self._defs[key]
        path = pick_a_file(self, pd.label, self._kind(pd).browse_filter,
                           self._initial_browse_path(str(self._read_field(pd)), pd.browse_dir))
        if path:
            self._write_field(pd, path)

    @staticmethod
    def _initial_browse_path(current: str, home: Path | None = None) -> str:
        """Where the file dialog opens: the current value's own location when it
        points at a real file (a full path, or a bare name from ComfyUI's input
        folder), else the field's home folder — the one its ParamDef names, or
        ComfyUI's input folder for a field naming none. A named folder that isn't
        on this machine (a checkout without the library) falls back the same way,
        since a dialog pointed at a missing path opens wherever it likes."""
        if current:
            full = Path(current)
            if full.is_file():
                return str(full)
            in_input = COMFYUI_INPUT_DIR / current
            if in_input.is_file():
                return str(in_input)
        if home is not None and home.is_dir():
            return str(home)
        return str(COMFYUI_INPUT_DIR)

    def _kind(self, pd: ParamDef):
        return field_kind(pd, self._heights, self._seed_history,
                          items=self._items, browse=self._browse_file)

    def _make_widget(self, pd: ParamDef) -> QWidget:
        if self._scenes is not None and pd.key in _SCENE_KEYS:
            return self._scenes
        widget = self._kind(pd).make(pd)
        if isinstance(widget, DropSlot):
            widget.activated.connect(self.item_activated)
        if isinstance(widget, PromptBoxes):
            widget.boxes_changed.connect(self.text_fields_changed)
        return widget

    def definitions(self) -> list[ParamDef]:
        return list(self._param_defs)

    def get_values(self) -> dict:
        return self._collect()

    def folds(self) -> dict[str, bool]:
        return {title: section.is_collapsed() for title, section in self._sections.items()}

    def set_folds(self, saved) -> None:
        for title, collapsed in saved.items():
            if title in self._sections and isinstance(collapsed, bool):
                self._sections[title].set_collapsed(collapsed)

    def seed_is_random(self) -> bool:
        """True if any seed param's Random tick is checked."""
        return any(cb.isChecked() for cb in self._randomize_checks.values())

    def set_seed_random(self, is_random: bool):
        for pd in self._seed_defs():
            tick = self._randomize_checks[pd.key]
            if tick.isChecked() != is_random:
                tick.setChecked(is_random)
                self._follow_random(pd, is_random)

    def put_seeds(self, params: dict, *, is_random: bool) -> None:
        for pd in self._seed_defs():
            if pd.key in params:
                self._randomize_checks[pd.key].setChecked(is_random)
                self._kind(pd).write(pd, self._widgets[pd.key], params[pd.key])

    def item_seeds(self) -> dict[str, int]:
        return dict(self._item_seeds)

    def output_size(self) -> tuple[int, int] | None:
        if self._size_deriver is not None:
            width, height = self._widgets["width"].value(), self._widgets["height"].value()
        else:
            values = self.get_values()
            width, height = values.get("width"), values.get("height")
        return (int(width), int(height)) if width and height else None

    def random_seed_keys(self) -> set[str]:
        return {key for key, tick in self._randomize_checks.items() if tick.isChecked()}

    def _seed_defs(self) -> list[ParamDef]:
        return [pd for pd in self._param_defs if pd.key in self._randomize_checks]

    def show_item(self, params: dict, thumbnail: str | None = None) -> None:
        self._item_seeds = {pd.key: int(params[pd.key]) for pd in self._seed_defs()
                            if params.get(pd.key) not in (None, "")}
        self._item_thumbnail = thumbnail
        self._describe_seed_fields()

    def _describe_seed_fields(self) -> None:
        size = self.output_size()
        for pd in self._seed_defs():
            self._widgets[pd.key].describe(self._item_seeds.get(pd.key), self._item_thumbnail,
                                           size)

    def roll_random_seeds(self) -> None:
        for pd in self._seed_defs():
            if self._randomize_checks[pd.key].isChecked():
                self._draw(pd)

    def _on_random_clicked(self, pd: ParamDef, checked: bool) -> None:
        drawn = self._follow_random(pd, checked)
        if drawn is not None:
            self.seed_drawn.emit(pd.key, drawn)

    def _follow_random(self, pd: ParamDef, is_random: bool) -> int | None:
        if is_random:
            return self._draw(pd)
        if pd.key in self._item_seeds:
            self._kind(pd).write(pd, self._widgets[pd.key], self._item_seeds[pd.key])
        return None

    def _draw(self, pd: ParamDef) -> int:
        seed = random.randint(0, _SEED_MAX)
        self._kind(pd).write(pd, self._widgets[pd.key], seed)
        return seed

    def _read_field(self, pd: ParamDef):
        w = self._widgets[pd.key]
        if w is self._scenes:
            if pd.key == "scene_frames":
                return w.scene_frames()
            if pd.key == "scene_lines":
                return w.lines()
            if pd.key == "frame_count":
                return w.total_frames()
            return w.story(pd.key)
        return self._kind(pd).read(pd, w)

    def _write_field(self, pd: ParamDef, value, *, carried: bool = False) -> None:
        w = self._widgets[pd.key]
        if w is self._scenes:
            if pd.key == "scene_frames":
                w.set_scene_frames(value)
            elif pd.key == "scene_lines":
                w.set_lines(value)
            elif pd.key != "frame_count":
                w.set_story(pd.key, value)
            return
        if carried and isinstance(w, PromptBoxes):
            w.carry(str(value))
            return
        self._kind(pd).write(pd, w, value)
        tick = self._randomize_checks.get(pd.key)
        if tick is not None and self._pins_reused_seed:
            tick.setChecked(False)

    def _settle(self, pd: ParamDef) -> None:
        """Show a field the value it will emit, once an edit of it has ended."""
        self._write_field(pd, self._read_field(pd))

    def _collect(self) -> dict:
        # Start from the params this form carries without showing — the extras it
        # has no field for, then the deliberately hidden ones (both disjoint from
        # the widget keys) — then lay the live field values on top, then any
        # unlocked size override, which is absent (so the payload derives the
        # size) unless the user set one.
        result = dict(self._passthrough)
        result.update(self._hidden)
        for pd in self._param_defs:
            result[pd.key] = self._read_field(pd)
            result.update(dict.fromkeys(pd.also_sets, result[pd.key]))
        result.update(self._override_dimensions())
        return result

    def replace_values(self, params: dict):
        self.set_values({**{pd.key: pd.default for pd in self._param_defs}, **params})

    def set_values(self, params: dict, *, carried: bool = False):
        # Retain any params without a field so they survive the read-back; the rest
        # are applied to their widgets. A hidden key is dropped entirely — never
        # absorbed — so the form keeps emitting the workflow's default for it.
        self._passthrough = {
            k: v for k, v in params.items()
            if k not in self._widgets and k not in self._hidden_keys
        }
        if (self._scenes is not None and "frame_count" in params
                and len(params.get("scene_frames") or []) <= 1):
            # A lone scene is the whole clip and runs for the clip length, which
            # is all that settings from before scenes (or from the overlay) carry.
            params = {**params, "scene_frames": [params["frame_count"]]}
        # The story first: it sets how many scenes there are, and every other
        # per-scene value is laid over the scenes it made.
        for pd in sorted(self._param_defs, key=lambda d: d.key != "positive_prompt"):
            if pd.key in params:
                self._write_field(pd, params[pd.key], carried=carried)
        for pd in self._seed_defs():
            if pd.key in params and self._randomize_checks[pd.key].isChecked():
                self._draw(pd)
        # The derived width/height aren't declared params, so apply them here:
        # a saved override unlocks and shows, its absence re-locks onto the size
        # the just-applied input image derives.
        if self._size_deriver is not None:
            self._apply_dimension_values(params)
