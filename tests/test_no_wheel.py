from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QComboBox

from origenerator.gui.no_wheel import (
    NoWheelDoubleSpinBox,
    NoWheelDropdown,
    NoWheelSpinBox,
)

_MODELS = [
    "split_files/diffusion_models/example_i2v_high_noise_14B_fp8.safetensors",
    "split_files/diffusion_models/example_i2v_low_noise_14B_fp8.safetensors",
]


def _wheel():
    return QWheelEvent(
        QPointF(1, 1), QPointF(1, 1), QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_a_dropdown_ignores_the_wheel(qtbot):
    w = NoWheelDropdown()
    w.addItems(["a", "b", "c"])
    w.setCurrentIndex(1)
    qtbot.addWidget(w)
    event = _wheel()

    w.wheelEvent(event)

    assert w.currentIndex() == 1
    assert not event.isAccepted()


def test_a_spinner_ignores_the_wheel(qtbot):
    w = NoWheelSpinBox()
    w.setRange(0, 100)
    w.setValue(5)
    qtbot.addWidget(w)
    event = _wheel()

    w.wheelEvent(event)

    assert w.value() == 5
    assert not event.isAccepted()


def test_a_double_spinner_ignores_the_wheel(qtbot):
    w = NoWheelDoubleSpinBox()
    w.setRange(0.0, 10.0)
    w.setValue(2.5)
    qtbot.addWidget(w)
    event = _wheel()

    w.wheelEvent(event)

    assert w.value() == 2.5
    assert not event.isAccepted()


def test_a_long_item_does_not_hold_the_form_open(qtbot):
    w = NoWheelDropdown()
    w.addItems(_MODELS)
    qtbot.addWidget(w)

    assert w.minimumSizeHint().width() < w.fontMetrics().horizontalAdvance(_MODELS[0]) / 3


def test_a_placeholder_does_not_hold_the_form_open_either(qtbot):
    bare = NoWheelDropdown()
    bare.addItems(_MODELS)
    qtbot.addWidget(bare)
    w = NoWheelDropdown()
    w.addItems(_MODELS)
    w.setPlaceholderText("Select a workflow…")
    qtbot.addWidget(w)

    assert w.minimumSizeHint().width() == bare.minimumSizeHint().width()



def _long_dropdown(qtbot):
    w = NoWheelDropdown()
    w.addItems(_MODELS)
    qtbot.addWidget(w)
    return w


def test_a_dropdowns_floor_grows_with_its_font(qtbot):
    w = _long_dropdown(qtbot)
    floor = w.minimumSizeHint().width()
    font = w.font()
    font.setPointSizeF(font.pointSizeF() * 2)

    w.setFont(font)

    assert w.minimumSizeHint().width() > floor + w.floor_chars * 4, (
        "the floor is the sum Qt makes for a full-length value, so it tracks the font")


def test_a_dropdowns_floor_grows_with_its_stylesheets_padding(qtbot):
    w = _long_dropdown(qtbot)
    floor = w.minimumSizeHint().width()

    w.setStyleSheet("QComboBox { padding-left: 40px; }")

    assert w.minimumSizeHint().width() > floor + 20, (
        "the floor is the sum Qt makes for a full-length value, so it tracks the stylesheet")

def test_a_dropdown_with_nothing_picked_shows_its_placeholder(qtbot):
    w = NoWheelDropdown()
    w.addItems(_MODELS)
    w.setPlaceholderText("Select a workflow…")
    w.setCurrentIndex(-1)
    qtbot.addWidget(w)

    assert w.display_text(1000) == "Select a workflow…"


def test_a_squeezed_value_elides_rather_than_cuts_off(qtbot):
    w = NoWheelDropdown()
    w.addItems(_MODELS)
    w.setCurrentIndex(0)
    qtbot.addWidget(w)
    whole = w.fontMetrics().horizontalAdvance(_MODELS[0])

    assert w.display_text(whole) == _MODELS[0]
    squeezed = w.display_text(whole // 4)
    assert squeezed != _MODELS[0]
    assert squeezed.endswith("…")


def test_it_still_asks_for_its_longest_item(qtbot):
    labels = ["Newest first", "Model + LoRA bands"]
    stock = QComboBox()
    stock.addItems(labels)
    qtbot.addWidget(stock)
    w = NoWheelDropdown()
    w.addItems(labels)
    qtbot.addWidget(w)

    assert w.sizeHint() == stock.sizeHint()
    assert w.display_text(w.sizeHint().width()) == "Newest first"
