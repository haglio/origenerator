from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from PyQt6.QtCore import QSignalBlocker, Qt
from PyQt6.QtWidgets import QComboBox, QLineEdit, QWidget
from shared_ui.tick_control import TickControl

from origenerator.gui.drop_zone import DropZone, ZoneLookups, placeholder_for
from origenerator.gui.file_pick import AUDIO_FILE_FILTER, FILE_FILTERS
from origenerator.gui.no_wheel import NoWheelDoubleSpinBox, NoWheelDropdown, NoWheelSpinBox
from origenerator.gui.param_help import option_help
from origenerator.gui.preset_dropdown import PresetDropdown
from origenerator.gui.prompt_boxes import PromptBoxes
from origenerator.gui.prompt_field import PromptField
from origenerator.gui.seed_dropdown import SeedDropdown
from origenerator.media import MediaType
from origenerator.model_titles import option_title
from origenerator.seed_history import SeedHistory
from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.duration import frames_for_seconds, on_grid, seconds_for_frames

NOT_KNOWN = "—"


@dataclass(frozen=True)
class WorkflowTraits:
    size_deriver: Callable[[dict], tuple[int, int] | None] | None = None
    size_source: str = "input_image"
    hidden_keys: tuple[str, ...] = ()
    pins_reused_seed: bool = True
    lora_keys: tuple[str, ...] = ()
    generates_here: bool = True


@dataclass(frozen=True)
class FormHelpers:
    heights: object = None
    seed_history: SeedHistory | None = None
    items: object = None


NO_TRAITS = WorkflowTraits()
NO_HELPERS = FormHelpers()


class FieldKind(ABC):
    copyable = False
    randomizable = False
    browse_filter: str | None = None
    drops = False

    @abstractmethod
    def make(self, pd: ParamDef) -> QWidget: ...

    @abstractmethod
    def change_signal(self, widget: QWidget): ...

    @abstractmethod
    def read(self, pd: ParamDef, widget: QWidget): ...

    @abstractmethod
    def write(self, pd: ParamDef, widget: QWidget, value) -> None: ...


class _Line(FieldKind):
    def make(self, pd):
        widget = QLineEdit()
        widget.setText(str(pd.default))
        return widget

    def change_signal(self, widget):
        return widget.textChanged

    def read(self, pd, widget):
        return widget.text()

    def write(self, pd, widget, value):
        widget.setText(str(value))


class _Seed(FieldKind):
    copyable = True
    randomizable = True

    def __init__(self, history: SeedHistory | None = None):
        self._history = history or SeedHistory(lambda key: [], lambda item: None)

    def make(self, pd):
        widget = SeedDropdown(lambda: self._history.uses(pd.key), self._history.looping_preview)
        widget.lineEdit().setPlaceholderText("64-bit integer seed")
        self.write(pd, widget, pd.default)
        return widget

    def change_signal(self, widget):
        return widget.editTextChanged

    def read(self, pd, widget):
        if widget.currentText() == NOT_KNOWN:
            return None
        try:
            return int(widget.currentText())
        except ValueError:
            return 0

    def write(self, pd, widget, value):
        widget.setEditText(NOT_KNOWN if value is None else str(int(value)))


class _AudioPath(_Line):
    browse_filter = AUDIO_FILE_FILTER

    def read(self, pd, widget):
        return widget.text().strip()


_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)


class _Drop(FieldKind):
    drops = True

    def __init__(self, kind: MediaType, items, browse: Callable[[str], None]):
        self._kind = kind
        self._items = items
        self._browse = browse
        self.browse_filter = FILE_FILTERS[kind]

    def make(self, pd):
        zone = DropZone(
            self._kind,
            ZoneLookups(
                lambda prompt_id: self._items.lends(prompt_id, self._kind),
                self._items.preview,
                named=self._items.named, name_of=self._items.name_of,
                browse=lambda: self._browse(pd.key), leads_to=self._items.item_of),
            placeholder_for(self._kind))
        self.write(pd, zone, pd.default)
        return zone

    def change_signal(self, widget):
        return widget.changed

    def read(self, pd, widget):
        return widget.current_id() or ""

    def write(self, pd, widget, value):
        held = str(value or "").translate(_INVISIBLE).strip()
        if held == self.read(pd, widget):
            return
        if held:
            widget.set_item(held)
        else:
            widget.clear()


class _Prompt(FieldKind):
    copyable = True

    def __init__(self, heights=None):
        self._heights = heights

    def make(self, pd):
        widget = PromptBoxes(partial(PromptField, pd.key, heights=self._heights))
        widget.set_value(str(pd.default))
        return widget

    def change_signal(self, widget):
        return widget.textChanged

    def read(self, pd, widget):
        return widget.value()

    def write(self, pd, widget, value):
        widget.set_value(str(value))


class _Checkbox(FieldKind):
    def make(self, pd):
        widget = TickControl("")
        widget.setChecked(bool(pd.default))
        return widget

    def change_signal(self, widget):
        return widget.toggled

    def read(self, pd, widget):
        return widget.isChecked()

    def write(self, pd, widget, value):
        widget.setChecked(bool(value))


class _Spinner(FieldKind, ABC):
    def change_signal(self, widget):
        return widget.valueChanged

    def read(self, pd, widget):
        return widget.value()


class _WholeSpinner(_Spinner):
    def make(self, pd):
        widget = NoWheelSpinBox()
        widget.setMinimum(int(pd.min_val or 0))
        widget.setMaximum(int(pd.max_val or 999999))
        widget.setSingleStep(int(pd.step or 1))
        widget.setValue(int(pd.default))
        return widget

    def write(self, pd, widget, value):
        widget.setValue(int(value))


class _DecimalSpinner(_Spinner):
    def make(self, pd):
        widget = NoWheelDoubleSpinBox()
        widget.setMinimum(pd.min_val or 0.0)
        widget.setMaximum(pd.max_val or 999999.0)
        widget.setSingleStep(pd.step or 0.1)
        widget.setDecimals(2)
        widget.setValue(float(pd.default))
        return widget

    def write(self, pd, widget, value):
        widget.setValue(float(value))


class _Presets(FieldKind):
    def make(self, pd):
        widget = PresetDropdown(pd.options, unit=pd.unit)
        grey_out_of_reach(pd, widget)
        if not pd.shown_in_seconds_at:
            widget.set_value(pd.default)
        return widget

    def change_signal(self, widget):
        return widget.editTextChanged

    def read(self, pd, widget):
        shown = widget.value()
        if shown is None and pd.shown_in_seconds_at:
            return pd.default
        return _stored(pd, shown)

    def write(self, pd, widget, value):
        number = clamped_number(pd, value)
        widget.set_value(seconds_for_frames(number, pd.shown_in_seconds_at, pd) if pd.shown_in_seconds_at else number)


class _Choice(FieldKind):
    def make(self, pd):
        widget = NoWheelDropdown()
        _offer_choices(pd, widget, pd.options or [])
        choose_option(widget, str(pd.default))
        return widget

    def change_signal(self, widget):
        return widget.currentIndexChanged

    def read(self, pd, widget):
        return widget.currentData()

    def write(self, pd, widget, value):
        choose_option(widget, str(value))


_KINDS: dict[ParamType, FieldKind] = {
    ParamType.BOOL: _Checkbox(),
    ParamType.STR: _Line(),
    ParamType.INT: _WholeSpinner(),
    ParamType.FLOAT: _DecimalSpinner(),
    ParamType.DROPDOWN: _Choice(),
    ParamType.AUDIO: _AudioPath(),
}
_PROMPT = _Prompt()
_PRESETS = _Presets()


def field_kind(pd: ParamDef, heights=None, seed_history: SeedHistory | None = None, *,
               items=None, browse: Callable[[str], None] | None = None) -> FieldKind:
    if pd.type == ParamType.STR and pd.multiline:
        return _Prompt(heights) if heights is not None else _PROMPT
    if pd.type == ParamType.SEED:
        return _Seed(seed_history)
    if pd.type in (ParamType.IMAGE, ParamType.VIDEO):
        return _Drop(MediaType(pd.type), items, browse)
    if pd.type in (ParamType.INT, ParamType.FLOAT) and pd.options:
        return _PRESETS
    return _KINDS[pd.type]


def offer_options(dropdown: QComboBox, options, tip=lambda _option: None) -> None:
    for option in options:
        dropdown.addItem(option_title(option), option)
        dropdown.setItemData(dropdown.count() - 1, tip(option) or None, Qt.ItemDataRole.ToolTipRole)


def offer_only(pd: ParamDef, dropdown: QComboBox, options: list) -> None:
    held = dropdown.currentData()
    shown = options if held in options else [*options, held]
    if [dropdown.itemData(row) for row in range(dropdown.count())] == shown:
        return
    with QSignalBlocker(dropdown):
        dropdown.clear()
        _offer_choices(pd, dropdown, options)
        choose_option(dropdown, str(held))


def _offer_choices(pd: ParamDef, dropdown: QComboBox, options: list) -> None:
    offer_options(dropdown, options, lambda option: option_help(pd.key, option))


def choose_option(dropdown: QComboBox, value: str):
    if dropdown.findData(value) < 0:
        offer_options(dropdown, [value])
    dropdown.setCurrentIndex(dropdown.findData(value))


def grey_out_of_reach(pd: ParamDef, widget: PresetDropdown) -> None:
    out_of_reach = [v for v in pd.options if _shown(pd, _stored(pd, v)) != v]
    if not out_of_reach:
        return
    ceiling = _shown(pd, _stored(pd, max(out_of_reach)))
    widget.set_unavailable(
        out_of_reach,
        f"More than this workflow makes — {ceiling:g} {pd.unit}".strip(),
    )


def _stored(pd: ParamDef, shown):
    return (frames_for_seconds(shown, pd.shown_in_seconds_at, pd) if pd.shown_in_seconds_at
            else clamped_number(pd, shown))


def _shown(pd: ParamDef, stored):
    return (seconds_for_frames(stored, pd.shown_in_seconds_at, pd) if pd.shown_in_seconds_at
            else clamped_number(pd, stored))


def clamped_number(pd: ParamDef, value):
    if value is None:
        value = pd.default
    if pd.step:
        value = on_grid(value, pd)
    if pd.min_val is not None:
        value = max(pd.min_val, value)
    if pd.max_val is not None:
        value = min(pd.max_val, value)
    return round(value) if pd.type == ParamType.INT else float(value)
