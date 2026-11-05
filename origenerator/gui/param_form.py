from __future__ import annotations

import random
from collections.abc import Sequence
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
from shared_ui.orientation import orientation_of_size as shape_of_size
from shared_ui.spacing import BUTTON_ICON, GAP_MEDIUM, GAP_SMALL
from shared_ui.tick_control import TickControl

from origenerator.base_models import loras_offered_beside
from origenerator.box_breaks import unboxed
from origenerator.config import COMFYUI_INPUT_DIR, OUTPUT_PLACES
from origenerator.gallery.shapes import SHAPE_LABELS
from origenerator.gui import diff_text, icons, param_sections, tracked_prompt
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.copy_button import CopyButton
from origenerator.gui.drop_zone import DropZone
from origenerator.gui.eliding import ElidingButton, ElidingLabel
from origenerator.gui.file_pick import pick_a_file
from origenerator.gui.label_cells import LabelCell, LabelColumn
from origenerator.gui.no_wheel import NoWheelSpinBox
from origenerator.gui.param_fields import (
    NO_HELPERS,
    NO_TRAITS,
    NOT_KNOWN,
    FormHelpers,
    WorkflowTraits,
    field_kind,
    grey_out_of_reach,
    offer_only,
)
from origenerator.gui.param_help import (
    advice_help,
    definition_help,
    option_help,
    param_help,
    with_training_date,
)
from origenerator.gui.preset_dropdown import PresetDropdown
from origenerator.gui.prompt_boxes import PromptBoxes, set_in_use
from origenerator.gui.request_exchange import RequestExchange
from origenerator.gui.scenes_editor import ScenesEditor
from origenerator.gui.stylesheet import CHOSEN
from origenerator.gui.tooltip_shape import shaped
from origenerator.gui.training_controls import TrainingRows
from origenerator.gui.warning_mark import WarningMark
from origenerator.gui.zone_items import FilesOnly
from origenerator.prompt_tokens import PromptReading
from origenerator.setting_advice import Advice, MissingTriggerWords
from origenerator.speech import CUSTOM_VOICE
from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.derived_size import override_size
from origenerator.workflows.lora_rows import lora_key_of, strength_without_its_lora

_SEED_MAX = (1 << 63) - 1
_OPPOSING_PROMPTS = (("positive_prompt", "negative_prompt"),
                     ("audio_prompt", "audio_negative_prompt"))
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

_DIMENSION_MAX = 8192
_DIMENSION_STEP = 16
_PADLOCK = {False: "lock", True: "unlock"}

class ParamForm(QWidget):
    changed = pyqtSignal()
    text_fields_changed = pyqtSignal()
    seed_drawn = pyqtSignal(str, object)
    item_activated = pyqtSignal(str)

    def __init__(
        self,
        param_defs: list[ParamDef],
        traits: WorkflowTraits = NO_TRAITS,
        helpers: FormHelpers = NO_HELPERS,
        parent=None,
    ):
        super().__init__(parent)
        self._lora_keys = tuple(traits.lora_keys)
        self.training = TrainingRows()
        self._heights = helpers.heights
        self._seed_history = helpers.seed_history
        self._items = helpers.items or FilesOnly(
            places=OUTPUT_PLACES, input_dir=COMFYUI_INPUT_DIR)
        self._item_seeds: dict[str, int] = {}
        self._item_thumbnail: str | None = None
        self._pins_reused_seed = traits.pins_reused_seed
        self._hidden_keys = frozenset(traits.hidden_keys)
        self._hidden = {
            pd.key: pd.default for pd in param_defs if pd.key in self._hidden_keys
        }
        self._size_deriver = traits.size_deriver
        self._size_source_key = traits.size_source
        self._unlock_btn: QToolButton | None = None
        self._dimensions_hint: QLabel | None = None
        self._dim_value_labels: dict[str, QLabel] = {}
        self._dim_stacks: dict[str, QStackedWidget] = {}
        self._widgets: dict[str, QWidget] = {}
        self._randomize_checks: dict[str, TickControl] = {}
        self._browse_buttons: dict[str, QPushButton] = {}
        self._copy_buttons: dict[str, CopyButton] = {}
        self._warning_marks: dict[str, WarningMark] = {}
        self._advice: dict[str, Advice | MissingTriggerWords] = {}
        self._labels: dict[str, ElidingLabel] = {}
        self._recommendations: dict[str, str] = {}
        self._swap_dimensions_btn: QPushButton | None = None
        self._passthrough: dict = {}
        self._sections: dict[str, CollapsibleSection] = {}
        self._request_exchange: RequestExchange | None = None
        self._present_keys: dict[str, list[str]] = {}
        self._shut_down: dict[str, str] = {}
        self._param_defs = [pd for pd in param_defs if pd.key not in self._hidden_keys]
        self._defs = {pd.key: pd for pd in self._param_defs}
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
        shape = shape_of_size(*size)
        tip = SHAPE_LABELS[shape]
        if size[0] == size[1]:
            tip = f"Square, so it goes under {tip}"
        self._sections["Size"].set_mark(icons.shape_mark(shape), tip)

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
            if (pd.key in self._lora_keys and pd.options) or pd.beside_model in values:
                offer_only(pd, self._widgets[pd.key],
                           loras_offered_beside(values[pd.beside_model], pd.options)
                           if pd.beside_model in values else pd.options)
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
                lambda title=title: self.resolve_warnings(self._present_keys[title]))
            self._sections[title] = section
            self._present_keys[title] = []
            outer.addWidget(section)
            if title == "Prompts" and any(pd.key == "positive_prompt" for pd in self._param_defs):
                outer.addWidget(self._build_request_section())
        outer.addStretch(1)

        for pd in sorted(self._param_defs, key=lambda d: param_sections.key_rank(d.key)):
            widget = self._make_widget(pd)
            self._widgets[pd.key] = widget
            if widget is self._scenes:
                if pd.type == ParamType.SCENES:
                    self._add_row(pd.key, pd.label, widget)
                continue
            if isinstance(widget, PresetDropdown):
                widget.edited.connect(lambda pd=pd: self._settle(pd))
            self._add_row(pd.key, pd.label, widget, self._make_extras(pd))
        for pd in self._param_defs:
            if pd.rate and self._widgets[pd.key] is not self._scenes:
                self._write_field(pd, pd.default)
        self._build_swap_button()
        self._build_derived_dimensions()
        self._announce_every_edit()
        self._oppose_the_prompts()
        self._refresh_section_visibility()

    def _build_request_section(self) -> CollapsibleSection:
        section = CollapsibleSection("Request")
        self._request_exchange = RequestExchange()
        section.content_form().addRow(self._request_exchange)
        return section

    def request_exchange(self) -> RequestExchange | None:
        return self._request_exchange

    def tells_a_story(self) -> bool:
        return self._scenes is not None

    def set_prompts(self, positive: str, negative: str, *, typed: bool = False) -> None:
        for pd in self._param_defs:
            if pd.key not in ("positive_prompt", "negative_prompt"):
                continue
            said = positive if pd.key == "positive_prompt" else negative
            widget = self._widgets[pd.key]
            if typed and isinstance(widget, PromptBoxes):
                widget.edit(said)
            else:
                self._write_field(pd, said)

    def _oppose_the_prompts(self):
        for positive, negative in _OPPOSING_PROMPTS:
            boxes = self._widgets.get(positive), self._widgets.get(negative)
            if all(isinstance(each, PromptBoxes) for each in boxes):
                boxes[0].opposes(boxes[1])

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
        if widget is not None and help_text and not isinstance(widget, DropZone):
            if key in self._lora_keys:
                help_text = with_training_date(help_text, self._read_field(self._defs[key]))
            widget.setToolTip(help_text)

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
        rank = param_sections.key_rank(key)
        return sum(1 for k in present if param_sections.key_rank(k) < rank)

    def _refresh_section_visibility(self):
        for title, section in self._sections.items():
            section.setVisible(bool(self._present_keys[title]))
        self._position_dimension_controls()

    def _field_cell(self, field: QWidget, extras: Sequence[QWidget]) -> QHBoxLayout:
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
            browse = ElidingButton("Browse...")
            browse.clicked.connect(
                lambda _checked=False, key=pd.key: self._browse_file(key)
            )
            self._browse_buttons[pd.key] = browse
            extras.append(browse)
        if pd.key in self._lora_keys:
            extras.append(self.training.controls_for(pd.key))
        return extras

    def _label_cell(self, key: str, label: QWidget, column: LabelColumn) -> LabelCell:
        mark = WarningMark()
        mark.pressed.connect(lambda: self.resolve_warnings([key]))
        self._warning_marks[key] = mark
        return LabelCell(mark, label, column)

    def resolve_warnings(self, rows: list[str]) -> None:
        for row in rows:
            for key, found in self._advised_at([row]):
                self._take_advice(key, found)

    def _take_advice(self, key: str, found: Advice | MissingTriggerWords) -> None:
        written = found.writes or key
        widget = self._widgets.get(written)
        if isinstance(widget, PromptBoxes):
            widget.rewrite(found.fixed)
        else:
            fixed = found.fixed(self._read_field(self._defs[written]))
            if written == "frame_count" and self._scenes is not None:
                self._scenes.set_total_frames(fixed)
            else:
                self._write_field(self._defs[written], fixed)
        if found.follow_up is not None:
            self._take_advice(key, found.follow_up)

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
        self.resolve_warnings(self._keys_in_order())

    def _keys_in_order(self) -> list[str]:
        return [key for keys in self._present_keys.values() for key in keys]

    def _warning(self, row: str) -> str:
        return "\n".join(found.said for _key, found in self._advised_at([row]))

    def _warnings_about(self, rows: list[str]) -> str:
        return "\n".join(f"{self._labels[self._row_of(key)].text()}: {found.value_shown}. "
                         f"{found.said}" for key, found in self._advised_at(rows))

    def track_prompt_rewrites(self, made_with: dict) -> None:
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
        for field in self._scenes.text_fields() if self._scenes is not None else []:
            tracked_prompt.untrack(field)
        for widget in self._widgets.values():
            if isinstance(widget, PromptBoxes):
                widget.untrack()

    def text_fields(self) -> list[QPlainTextEdit]:
        scenes = self._scenes.text_fields() if self._scenes is not None else []
        return scenes + [box for widget in self._widgets.values()
                         if isinstance(widget, PromptBoxes) for box in widget.boxes()]

    def remove_unread_emphasis(self) -> None:
        for widget in self._widgets.values():
            if isinstance(widget, PromptBoxes):
                widget.remove_unread_emphasis()
        if self._scenes is not None:
            self._scenes.remove_unread_emphasis()

    def drop_zones(self) -> tuple[DropZone, ...]:
        return tuple(w for w in self._widgets.values() if isinstance(w, DropZone))

    def _has_param(self, key: str) -> bool:
        return key in self._defs

    def _build_swap_button(self):
        if not (self._has_param("width") and self._has_param("height")):
            return
        content = self._sections["Size"].content()
        btn = QPushButton(content)
        btn.setIcon(qt_icon("flip_ends"))
        btn.setToolTip("Swap width and height")
        btn.clicked.connect(self.swap_dimensions)
        btn.adjustSize()
        self._swap_dimensions_btn = btn
        content.installEventFilter(self)

    def _center_between_dimension_rows(self, btn, top_row, lower_row):
        if self._sections["Size"].is_collapsed():
            return
        btn.adjustSize()
        margin = btn.width() + 10
        form = self._sections["Size"].content_form()
        if form.contentsMargins().left() != margin:
            form.setContentsMargins(margin, GAP_SMALL, 0, GAP_SMALL)
            return
        top, lower = top_row.geometry(), lower_row.geometry()
        y = (top.center().y() + lower.center().y()) // 2 - btn.height() // 2
        btn.move(max(0, (margin - btn.width()) // 2), y)
        btn.raise_()

    def _position_swap_button(self):
        if self._swap_dimensions_btn is None:
            return
        self._center_between_dimension_rows(
            self._swap_dimensions_btn,
            self._widgets["width"], self._widgets["height"])

    def eventFilter(self, obj, event):
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
        self._position_swap_button()
        self._position_unlock_button()

    def swap_dimensions(self):
        width, height = self._widgets["width"], self._widgets["height"]
        w, h = width.value(), height.value()
        width.setValue(h)
        height.setValue(w)

    def _build_derived_dimensions(self):
        if self._size_deriver is None:
            return
        for key, label_text in (("width", "Width"), ("height", "Height")):
            spinner = NoWheelSpinBox()
            spinner.setMinimum(0)
            spinner.setMaximum(_DIMENSION_MAX)
            spinner.setSingleStep(_DIMENSION_STEP)
            spinner.setSpecialValueText(NOT_KNOWN)
            spinner.valueChanged.connect(self.changed)
            self._widgets[key] = spinner
            value_label = QLabel(NOT_KNOWN)
            value_label.setObjectName("readonlyParamValue")
            self._dim_value_labels[key] = value_label
            stack = QStackedWidget()
            stack.addWidget(value_label)
            stack.addWidget(spinner)
            self._dim_stacks[key] = stack
            self._add_row(key, label_text, stack)
        self._dimensions_hint = QLabel(f"Sized from the {self._size_source()}. Unlock to override.")
        self._dimensions_hint.setObjectName("dimensionsHint")
        self._dimensions_hint.setWordWrap(True)
        self._sections["Size"].content_form().addRow(self._dimensions_hint)
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
        content.installEventFilter(self)
        self._update_derived_display()

    def _position_unlock_button(self):
        if self._unlock_btn is None:
            return
        self._center_between_dimension_rows(
            self._unlock_btn,
            self._dim_stacks["width"], self._dim_stacks["height"])

    def _dimensions_unlocked(self) -> bool:
        return self._unlock_btn is not None and self._unlock_btn.isChecked()

    def _size_source(self) -> str:
        source = self._defs.get(self._size_source_key)
        return source.label.lower() if source is not None else "image"

    def _unlock_tip(self, unlocked: bool) -> str:
        if unlocked:
            return f"Re-lock to the size derived from the {self._size_source()}"
        return f"Unlock to override the size derived from the {self._size_source()}"

    def _on_dimensions_unlock_toggled(self, unlocked: bool):
        self._unlock_btn.setIcon(qt_icon(_PADLOCK[unlocked]))
        self._unlock_btn.setToolTip(self._unlock_tip(unlocked))
        for stack in self._dim_stacks.values():
            stack.setCurrentIndex(1 if unlocked else 0)
        if not unlocked:
            self._update_derived_display()
        self._position_unlock_button()
        self.changed.emit()

    def _update_derived_display(self):
        if self._size_deriver is None or self._dimensions_unlocked():
            return
        size = self._size_deriver(self.get_values())
        for key, value in zip(("width", "height"), size or (0, 0), strict=True):
            spinner = self._widgets[key]
            blocked = spinner.blockSignals(True)
            spinner.setValue(value)
            spinner.blockSignals(blocked)
            self._dim_value_labels[key].setText(str(value) if value else NOT_KNOWN)

    def _override_dimensions(self) -> dict:
        if not self._dimensions_unlocked():
            return {}
        width = self._widgets["width"].value()
        height = self._widgets["height"].value()
        return {"width": width, "height": height} if width > 0 and height > 0 else {}

    def _apply_dimension_values(self, params: dict):
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
        if isinstance(widget, DropZone):
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
        return any(cb.isChecked() for cb in self._randomize_checks.values())

    def set_seed_random(self, is_random: bool):
        for pd in self._seed_defs():
            checkbox = self._randomize_checks[pd.key]
            if checkbox.isChecked() != is_random:
                checkbox.setChecked(is_random)
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
        return {key for key, checkbox in self._randomize_checks.items() if checkbox.isChecked()}

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
        checkbox = self._randomize_checks.get(pd.key)
        if checkbox is not None and self._pins_reused_seed:
            checkbox.setChecked(False)

    def _settle(self, pd: ParamDef) -> None:
        self._write_field(pd, self._read_field(pd))

    def _collect(self) -> dict:
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
        self._passthrough = {
            k: v for k, v in params.items()
            if k not in self._widgets and k not in self._hidden_keys
        }
        if (self._scenes is not None and "frame_count" in params
                and len(params.get("scene_frames") or []) <= 1):
            params = {**params, "scene_frames": [params["frame_count"]]}
        for pd in sorted(self._param_defs, key=lambda d: d.key != "positive_prompt"):
            if pd.key in params:
                self._write_field(pd, params[pd.key], carried=carried)
        for pd in self._seed_defs():
            if pd.key in params and self._randomize_checks[pd.key].isChecked():
                self._draw(pd)
        if self._size_deriver is not None:
            self._apply_dimension_values(params)
