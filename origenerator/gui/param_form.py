import random

from PyQt6.QtWidgets import (
    QWidget, QFormLayout, QHBoxLayout,
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.paths import ensure_shared_ui_on_path
from origenerator.gui.image_picker import ImagePickerDialog
from origenerator.workflows.base import ParamDef

ensure_shared_ui_on_path()
from shared_ui.check_box import CheckBox

_SEED_MAX = (1 << 63) - 1


class ParamForm(QWidget):
    changed = pyqtSignal()  # any field's value changed

    def __init__(self, param_defs: list[ParamDef], parent=None):
        super().__init__(parent)
        self._widgets: dict[str, QWidget] = {}
        self._randomize_checks: dict[str, CheckBox] = {}
        self._browse_buttons: dict[str, QPushButton] = {}
        # Params a config carries but this form has no widget for — the workflow's
        # hidden settings (model, LoRA, VAE, sampler…). The form has no field to
        # edit them, but must round-trip whatever value it was given so reusing a
        # generation reproduces its exact LoRA/model rather than the defaults.
        self._passthrough: dict = {}
        self._param_defs = param_defs
        self._build(param_defs)

    def _build(self, defs: list[ParamDef]):
        layout = QFormLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop
        )
        # Let the label column size itself to the widest label (at the app's
        # font) and the inputs take the rest, so no text is clipped.
        layout.setFieldGrowthPolicy(
            QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow
        )

        for pd in defs:
            widget = self._make_widget(pd)
            self._widgets[pd.key] = widget
            self._wire_changed(widget)
            layout.addRow(pd.label, self._field_cell(pd, widget))

    def _field_cell(self, pd: ParamDef, widget: QWidget):
        """The input, optionally paired with a trailing control.

        Seeds carry a Random checkbox and image fields a Browse button; each
        sits to the right of the input in a shared cell so the label column
        stays aligned across every row.
        """
        extra = self._make_extra(pd)
        if extra is None:
            return widget
        cell = QHBoxLayout()
        cell.setContentsMargins(0, 0, 0, 0)
        cell.addWidget(widget, 1)
        cell.addWidget(extra)
        return cell

    def _make_extra(self, pd: ParamDef) -> QWidget | None:
        if pd.type == "seed":
            cb = CheckBox("Random")
            cb.setChecked(True)
            cb.toggled.connect(self.changed)
            self._randomize_checks[pd.key] = cb
            return cb
        if pd.type == "image":
            browse = QPushButton("Browse...")
            browse.clicked.connect(
                lambda _checked=False, key=pd.key: self._browse_image(key)
            )
            self._browse_buttons[pd.key] = browse
            return browse
        return None

    def _browse_image(self, key: str):
        dialog = ImagePickerDialog(self)
        if dialog.exec() and dialog.selected_image():
            self._widgets[key].setText(dialog.selected_image())

    def _wire_changed(self, widget: QWidget):
        """Re-emit ``changed`` whenever this input's value changes."""
        if isinstance(widget, (QPlainTextEdit, QLineEdit)):
            widget.textChanged.connect(self.changed)
        elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            widget.valueChanged.connect(self.changed)
        elif isinstance(widget, QComboBox):
            widget.currentIndexChanged.connect(self.changed)

    def _make_widget(self, pd: ParamDef) -> QWidget:
        if pd.type == "str" and pd.multiline:
            w = QPlainTextEdit()
            w.setPlainText(str(pd.default))
            w.setMaximumHeight(100)
            return w
        if pd.type == "str":
            w = QLineEdit()
            w.setText(str(pd.default))
            return w
        if pd.type == "seed":
            w = QLineEdit()
            w.setText(str(pd.default))
            w.setPlaceholderText("64-bit integer seed")
            return w
        if pd.type == "int":
            w = QSpinBox()
            w.setMinimum(int(pd.min_val or 0))
            w.setMaximum(int(pd.max_val or 999999))
            w.setSingleStep(int(pd.step or 1))
            w.setValue(int(pd.default))
            return w
        if pd.type == "float":
            w = QDoubleSpinBox()
            w.setMinimum(pd.min_val or 0.0)
            w.setMaximum(pd.max_val or 999999.0)
            w.setSingleStep(pd.step or 0.1)
            w.setDecimals(2)
            w.setValue(float(pd.default))
            return w
        if pd.type == "combo":
            w = QComboBox()
            if pd.options:
                w.addItems(pd.options)
            idx = w.findText(str(pd.default))
            if idx >= 0:
                w.setCurrentIndex(idx)
            return w
        if pd.type == "image":
            w = QLineEdit()
            w.setText(str(pd.default))
            return w
        w = QLineEdit()
        w.setText(str(pd.default))
        return w

    def get_values(self) -> dict:
        """Read current values; a seed with its Random box checked is randomized."""
        return self._collect(randomize_seed=True)

    def get_values_static(self) -> dict:
        """Read current values without randomizing; a seed is read from its field.

        Used to snapshot a panel's settings for comparison, where a fresh random
        seed each call would make equality checks meaningless.
        """
        return self._collect(randomize_seed=False)

    def seed_is_random(self) -> bool:
        """True if any seed param's Random box is checked."""
        return any(cb.isChecked() for cb in self._randomize_checks.values())

    def set_seed_random(self, is_random: bool):
        """Set every seed's Random box, e.g. when restoring a saved tab.

        ``set_values`` always unchecks Random (it pins a concrete seed); this
        lets a caller put the box back the way the user had it.
        """
        for cb in self._randomize_checks.values():
            cb.setChecked(is_random)

    def _collect(self, randomize_seed: bool) -> dict:
        # Start from the hidden params (disjoint from the widget keys), then lay
        # the live field values on top.
        result = dict(self._passthrough)
        for pd in self._param_defs:
            w = self._widgets[pd.key]
            if pd.type == "seed":
                cb = self._randomize_checks.get(pd.key)
                if randomize_seed and cb and cb.isChecked():
                    result[pd.key] = random.randint(0, _SEED_MAX)
                else:
                    try:
                        result[pd.key] = int(w.text())
                    except ValueError:
                        result[pd.key] = 0
            elif pd.type == "str" and pd.multiline:
                result[pd.key] = w.toPlainText()
            elif pd.type == "str" or pd.type == "image":
                result[pd.key] = w.text()
            elif pd.type == "int":
                result[pd.key] = w.value()
            elif pd.type == "float":
                result[pd.key] = w.value()
            elif pd.type == "combo":
                result[pd.key] = w.currentText()
        return result

    def set_values(self, params: dict):
        # Retain any params without a field so they survive the read-back; the
        # rest are applied to their widgets below.
        self._passthrough = {k: v for k, v in params.items() if k not in self._widgets}
        for pd in self._param_defs:
            if pd.key not in params:
                continue
            val = params[pd.key]
            w = self._widgets[pd.key]
            if pd.type == "seed":
                w.setText(str(int(val)))
                cb = self._randomize_checks.get(pd.key)
                if cb:
                    cb.setChecked(False)
            elif pd.type == "str" and pd.multiline:
                w.setPlainText(str(val))
            elif pd.type == "str" or pd.type == "image":
                w.setText(str(val))
            elif pd.type == "int":
                w.setValue(int(val))
            elif pd.type == "float":
                w.setValue(float(val))
            elif pd.type == "combo":
                idx = w.findText(str(val))
                if idx >= 0:
                    w.setCurrentIndex(idx)
