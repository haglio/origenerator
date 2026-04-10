import random

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QLineEdit, QSpinBox, QDoubleSpinBox,
    QComboBox, QCheckBox, QPushButton,
)
from PyQt6.QtCore import Qt

from origenerator.workflows.base import ParamDef

_SEED_MAX = (1 << 63) - 1


class ParamForm(QWidget):
    def __init__(self, param_defs: list[ParamDef], parent=None):
        super().__init__(parent)
        self._widgets: dict[str, QWidget] = {}
        self._randomize_checks: dict[str, QCheckBox] = {}
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
            row.addWidget(widget, 1)

            if pd.type == "seed":
                cb = QCheckBox("Random")
                cb.setChecked(True)
                self._randomize_checks[pd.key] = cb
                row.addWidget(cb)

            if pd.type == "image":
                browse = QPushButton("Browse...")
                browse.setFixedWidth(80)
                row.addWidget(browse)

            layout.addLayout(row)

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
        if pd.type in ("int", "seed"):
            w = QSpinBox()
            w.setMinimum(int(pd.min_val or 0))
            w.setMaximum(int(pd.max_val or _SEED_MAX) if pd.type == "seed" else int(pd.max_val or 999999))
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
        result = {}
        for pd in self._param_defs:
            w = self._widgets[pd.key]
            if pd.type == "seed":
                cb = self._randomize_checks.get(pd.key)
                if cb and cb.isChecked():
                    result[pd.key] = random.randint(0, _SEED_MAX)
                else:
                    result[pd.key] = w.value()
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
                w.setValue(int(val))
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
