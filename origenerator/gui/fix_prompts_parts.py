from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import GAP_SMALL

from origenerator.gallery import ENHANCE_WORKFLOW
from origenerator.gui.flow_layout import FlowLayout
from origenerator.gui.no_wheel import NoWheelDoubleSpinBox, NoWheelDropdown
from origenerator.gui.param_fields import choose_option, offer_options
from origenerator.gui.param_help import definition_help
from origenerator.gui.prompt_boxes import PromptBoxes
from origenerator.prompt_tokens import prompt_reading
from origenerator.workflows.lora_rows import lora_strength
from origenerator.workflows.model_files import NO_LORA


def window_column(dialog) -> QVBoxLayout:
    layout = QVBoxLayout(dialog)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(GAP_SMALL)
    layout.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
    heading = QLabel(dialog.windowTitle())
    heading.setStyleSheet("font-weight: bold;")
    layout.addWidget(heading)
    return layout


def prompt_boxes(key: str, text: str) -> PromptBoxes:
    boxes = PromptBoxes(QPlainTextEdit)
    boxes.set_reading(prompt_reading(ENHANCE_WORKFLOW, {}, key))
    boxes.set_value(text)
    return boxes


def _side_by_side(*widgets) -> QWidget:
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(GAP_SMALL)
    for widget in widgets:
        row.addWidget(widget)
    return host


def prompts_side_by_side(prompt_warning, positive, negative) -> QHBoxLayout:
    columns = QHBoxLayout()
    for caption, field in (((prompt_warning, QLabel("Positive Prompt")), positive),
                           ((QLabel("Negative Prompt"),), negative)):
        column = QVBoxLayout()
        column.addWidget(_side_by_side(*caption), 0, Qt.AlignmentFlag.AlignLeft)
        column.addWidget(field, 1)
        columns.addLayout(column)
    return columns


def ok_and_cancel(dialog) -> QDialogButtonBox:
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                               | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    return buttons


def lora_dropdown(loras: list[str], current) -> NoWheelDropdown:
    dropdown = NoWheelDropdown()
    offer_options(dropdown, loras)
    choose_option(dropdown, current or NO_LORA)
    return dropdown


def strength_box(current) -> NoWheelDoubleSpinBox:
    strength = lora_strength("lora_strength", current)
    box = NoWheelDoubleSpinBox()
    box.setRange(strength.min_val, strength.max_val)
    box.setSingleStep(strength.step)
    box.setValue(strength.default)
    box.setToolTip(definition_help(strength))
    return box


def foot_row(lora_warning, lora, strength, training, buttons) -> FlowLayout:
    foot = FlowLayout(spacing=GAP_SMALL)
    for together in ((lora_warning, QLabel("LoRA"), lora), (QLabel("LoRA Strength"), strength)):
        foot.addWidget(_side_by_side(*together))
    foot.addWidget(training)
    foot.add_trailing(buttons)
    return foot
