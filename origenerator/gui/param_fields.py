"""Each kind of setting a workflow declares, as the settings form edits it: the
field it gets, how that field is read and written, and what sits beside it.

What a field reads back is what a generation's ``params_json`` stores, so a
kind's ``read`` is a contract, not only a display.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from PyQt6.QtWidgets import QComboBox, QLineEdit, QWidget

from origenerator.gui import diff_text
from origenerator.gui.no_wheel import NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox
from origenerator.gui.preset_combo import PresetComboBox
from origenerator.gui.prompt_field import PromptField
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.workflows.base import ParamDef
from origenerator.workflows.duration import frames_for_seconds, on_grid, seconds_for_frames

ensure_shared_ui_on_path()
from shared_ui.tick_control import TickControl

# Zero-width spaces / joiners / BOM that can ride invisibly on a pasted path.
# The metadata block inserts zero-width spaces into displayed paths for on-screen
# wrapping, so text copied from there carries them; none belongs in a real path.
# U+200B ZWSP, U+200C ZWNJ, U+200D ZWJ, U+2060 word-joiner, U+FEFF BOM.
_INVISIBLE = dict.fromkeys((0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF), None)


class FieldKind(ABC):
    copyable = False
    randomizable = False
    browse_filter: str | None = None

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


class _Seed(_Line):
    copyable = True
    randomizable = True

    def make(self, pd):
        widget = super().make(pd)
        widget.setPlaceholderText("64-bit integer seed")
        return widget

    def read(self, pd, widget):
        try:
            return int(widget.text())
        except ValueError:
            return 0

    def write(self, pd, widget, value):
        widget.setText(str(int(value)))


class _ImagePath(_Line):
    browse_filter = "Images (*.png *.jpg *.jpeg *.webp);;All Files (*)"

    def read(self, pd, widget):
        # A LoadImage path resolves only without the invisible wrapping above.
        return widget.text().translate(_INVISIBLE).strip()


class _AudioPath(_Line):
    browse_filter = "Audio (*.wav *.mp3 *.flac *.m4a *.ogg);;All Files (*)"

    def read(self, pd, widget):
        return widget.text().strip()


class _Prompt(FieldKind):
    copyable = True

    def make(self, pd):
        widget = PromptField(pd.key)
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
        if pd.options:
            widget.addItems(pd.options)
        _select_combo_value(widget, str(pd.default))
        return widget

    def change_signal(self, widget):
        return widget.currentIndexChanged

    def read(self, pd, widget):
        return widget.currentText()

    def write(self, pd, widget, value):
        _select_combo_value(widget, str(value))


_KINDS: dict[str, FieldKind] = {
    "bool": _Tick(),
    "str": _Line(),
    "seed": _Seed(),
    "int": _WholeSpinner(),
    "float": _DecimalSpinner(),
    "combo": _Choice(),
    "image": _ImagePath(),
    "audio": _AudioPath(),
}
_PROMPT = _Prompt()
_PRESETS = _Presets()


def field_kind(pd: ParamDef) -> FieldKind:
    if pd.type == "str" and pd.multiline:
        return _PROMPT
    if pd.type in ("int", "float") and pd.options:
        return _PRESETS
    return _KINDS[pd.type]


def _select_combo_value(combo: QComboBox, value: str):
    """Show ``value`` in ``combo``, offering it as a new option if it isn't one.

    A workflow default or a reused choice (e.g. a LoRA whose file is gone) may
    not be among the scanned options; adding it keeps the combo faithful to the
    value it was given instead of snapping to whatever sorts first.
    """
    idx = combo.findText(value)
    if idx < 0:
        combo.addItem(value)
        idx = combo.findText(value)
    combo.setCurrentIndex(idx)


def grey_out_of_reach(pd: ParamDef, widget: PresetComboBox) -> None:
    """Disable the presets this workflow can't actually produce.

    The Duration dropdown offers the same lengths to every video workflow,
    and every video model stops well short of the longest of them — 15 s and
    30 s are out of reach everywhere, and 10 s on the two workflows that
    render fewer frames. Picked, such a preset just becomes the longest clip
    the model does render, so the number chosen isn't the number given; the
    list says which those are instead of quietly substituting.

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
    return int(round(value)) if pd.type == "int" else float(value)
