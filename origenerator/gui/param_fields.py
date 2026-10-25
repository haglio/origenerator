"""Each kind of setting a workflow declares, as the settings form edits it: the
field it gets, how that field is read and written, and what sits beside it.

What a field reads back is what a generation's ``params_json`` stores, so a
kind's ``read`` is a contract, not only a display.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QLineEdit, QWidget
from shared_ui.tick_control import TickControl

from origenerator.gui import diff_text
from origenerator.gui.drop_slot import DropSlot, placeholder_for
from origenerator.gui.file_pick import AUDIO_FILE_FILTER, FILE_FILTERS
from origenerator.gui.no_wheel import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox
from origenerator.gui.param_help import option_help
from origenerator.gui.preset_combo import PresetComboBox
from origenerator.gui.prompt_field import PromptField
from origenerator.gui.seed_combo import SeedComboBox
from origenerator.media import MediaType
from origenerator.model_titles import option_title
from origenerator.seed_history import SeedHistory
from origenerator.workflows.base import ParamDef, ParamType
from origenerator.workflows.duration import frames_for_seconds, on_grid, seconds_for_frames

NOT_KNOWN = "—"


class FieldKind(ABC):
    copyable = False
    randomizable = False
    browse_filter: str | None = None
    drops = False  # a zone an item is dropped on, which browses from its own menu

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
        widget = SeedComboBox(lambda: self._history.uses(pd.key), self._history.looping_preview)
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


# The zero-width characters the metadata block wraps a displayed path with.
_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)


class _Drop(FieldKind):
    """An image or video input: a zone, read back as the reference the graph loads."""

    drops = True

    def __init__(self, kind: MediaType, items, browse: Callable[[str], None]):
        self._kind = kind
        self._items = items
        self._browse = browse
        self.browse_filter = FILE_FILTERS[kind]

    def make(self, pd):
        zone = DropSlot(
            self._kind, lambda prompt_id: self._items.lends(prompt_id, self._kind),
            self._items.preview, placeholder_for(self._kind),
            named=self._items.named, name_of=self._items.name_of,
            browse=lambda: self._browse(pd.key))
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
        widget = PromptField(pd.key, heights=self._heights)
        widget.setPlainText(str(pd.default))
        return widget

    def change_signal(self, widget):
        return widget.textChanged

    def read(self, pd, widget):
        # Never the raw document: while a request's change is marked in the
        # field, that document also holds the words the change took out.
        return diff_text.live_text(widget)

    def write(self, pd, widget, value):
        diff_text.forget(widget)
        widget.setPlainText(str(value))


class _Tick(FieldKind):
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
    """A number offered as common values that still takes a typed one; a frame
    count among them is shown, and edited, as seconds at its ``rate``."""

    def make(self, pd):
        widget = PresetComboBox(pd.options, unit=pd.unit)
        grey_out_of_reach(pd, widget)
        if not pd.rate:
            widget.set_value(pd.default)
        return widget

    def change_signal(self, widget):
        return widget.editTextChanged

    def read(self, pd, widget):
        shown = widget.value()
        if shown is None and pd.rate:
            return pd.default
        return _stored(pd, shown)

    def write(self, pd, widget, value):
        number = clamped_number(pd, value)
        widget.set_value(seconds_for_frames(number, pd.rate, pd) if pd.rate else number)


class _Choice(FieldKind):
    def make(self, pd):
        widget = NoWheelComboBox()
        offer_options(widget, pd.options or [], lambda option: option_help(pd.key, option))
        choose_option(widget, str(pd.default))
        return widget

    def change_signal(self, widget):
        return widget.currentIndexChanged

    def read(self, pd, widget):
        return widget.currentData()

    def write(self, pd, widget, value):
        choose_option(widget, str(value))


_KINDS: dict[ParamType, FieldKind] = {
    ParamType.BOOL: _Tick(),
    ParamType.STR: _Line(),
    ParamType.INT: _WholeSpinner(),
    ParamType.FLOAT: _DecimalSpinner(),
    ParamType.COMBO: _Choice(),
    ParamType.AUDIO: _AudioPath(),
}
_PROMPT = _Prompt()
_PRESETS = _Presets()


def field_kind(pd: ParamDef, heights=None, seed_history: SeedHistory | None = None, *,
               items=None, browse: Callable[[str], None] | None = None) -> FieldKind:
    """The kind of field ``pd`` is edited in. ``heights`` is the set a prompt's
    dragged height is filed in, ``items`` how a zone reads what it holds and
    ``browse`` what its menu's Browse does, all the form's to supply."""
    if pd.type == ParamType.STR and pd.multiline:
        return _Prompt(heights) if heights is not None else _PROMPT
    if pd.type == ParamType.SEED:
        return _Seed(seed_history)
    if pd.type in (ParamType.IMAGE, ParamType.VIDEO):
        return _Drop(MediaType(pd.type), items, browse)
    if pd.type in (ParamType.INT, ParamType.FLOAT) and pd.options:
        return _PRESETS
    return _KINDS[pd.type]


def offer_options(combo: QComboBox, options, tip=lambda _option: None) -> None:
    for option in options:
        combo.addItem(option_title(option), option)
        combo.setItemData(combo.count() - 1, tip(option) or None, Qt.ItemDataRole.ToolTipRole)


def choose_option(combo: QComboBox, value: str):
    """Show ``value`` in ``combo``, offering it as a new option if it isn't one.

    A workflow default or a reused choice (e.g. a LoRA whose file is gone) may
    not be among the scanned options; adding it keeps the combo faithful to the
    value it was given instead of snapping to whatever sorts first.
    """
    if combo.findData(value) < 0:
        offer_options(combo, [value])
    combo.setCurrentIndex(combo.findData(value))


def grey_out_of_reach(pd: ParamDef, widget: PresetComboBox) -> None:
    """Disable the presets this workflow can't actually produce.

    Out of reach means the value doesn't survive the round trip the field
    itself makes — offered, stored, and read back, it comes out as something
    else. That covers a rate past the writer's ceiling on the same rule.
    """
    out_of_reach = [v for v in pd.options if _shown(pd, _stored(pd, v)) != v]
    if not out_of_reach:
        return
    # Any out-of-reach value stands in for "past the end": stored, it lands
    # on the largest the workflow does take, which is the number to name.
    ceiling = _shown(pd, _stored(pd, max(out_of_reach)))
    widget.set_unavailable(
        out_of_reach,
        f"More than this workflow makes — {ceiling:g} {pd.unit}".strip(),
    )


def _stored(pd: ParamDef, shown):
    return (frames_for_seconds(shown, pd.rate, pd) if pd.rate
            else clamped_number(pd, shown))


def _shown(pd: ParamDef, stored):
    return (seconds_for_frames(stored, pd.rate, pd) if pd.rate
            else clamped_number(pd, stored))


def clamped_number(pd: ParamDef, value):
    """``value`` on ``pd``'s grid and within its range, as its type; the
    default when there is no value (an emptied field).

    A preset dropdown's grid is what the model can actually take — 4k+1
    frames, whole multiples of the native frame rate — so a number typed
    between two steps settles onto the nearer one rather than being handed
    to a graph that would round it out of sight
    (:func:`~origenerator.workflows.duration.on_grid`).
    """
    if value is None:
        value = pd.default
    if pd.step:
        value = on_grid(value, pd)
    if pd.min_val is not None:
        value = max(pd.min_val, value)
    if pd.max_val is not None:
        value = min(pd.max_val, value)
    return int(round(value)) if pd.type == ParamType.INT else float(value)
