import random

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QPushButton,
)
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.check_box import CheckBox
from origenerator.gui.image_picker import ImagePickerDialog
from origenerator.workflows.base import ParamDef

_SEED_MAX = (1 << 63) - 1


class ParamForm(QWidget):
    changed = pyqtSignal()  # any field's value changed

    def __init__(self, param_defs: list[ParamDef], parent=None):
        super().__init__(parent)
        self._widgets: dict[str, QWidget] = {}
        self._randomize_checks: dict[str, CheckBox] = {}
        self._browse_buttons: dict[str, QPushButton] = {}
        self._param_defs = param_defs
        self._build(param_defs)

    def _build(self, defs: list[ParamDef]):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        for pd in defs:
            row = QHBoxLayout()
            label = QLabel(pd.label)
            label.setFixedWidth(120)
            label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
            row.addWidget(label)

            widget = self._make_widget(pd)
            self._widgets[pd.key] = widget
            self._wire_changed(widget)
            row.addWidget(widget, 1)

            if pd.type == "seed":
                cb = CheckBox("Random")
                cb.setChecked(True)
                cb.toggled.connect(self.changed)
                self._randomize_checks[pd.key] = cb
                row.addWidget(cb)

            if pd.type == "image":
                browse = QPushButton("Browse...")
                browse.setFixedWidth(80)
                browse.clicked.connect(
                    lambda _checked=False, key=pd.key: self._browse_image(key)
                )
                self._browse_buttons[pd.key] = browse
                row.addWidget(browse)

            layout.addLayout(row)

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
        result = {}
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
