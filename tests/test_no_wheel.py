from __future__ import annotations

from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QComboBox

from origenerator.gui.no_wheel import (
    NoWheelDoubleSpinBox,
    NoWheelDropdown,
    NoWheelSpinBox,
)

# Two model files as a dropdown holds them: long, and alike until near the end.
_MODELS = [
    "split_files/diffusion_models/example_i2v_high_noise_14B_fp8.safetensors",
    "split_files/diffusion_models/example_i2v_low_noise_14B_fp8.safetensors",
]


def _wheel():
    """One downward wheel notch."""
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

    assert w.currentIndex() == 1     # selection unchanged
    assert not event.isAccepted()    # ignored → scrolls the form instead of editing


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


# --- shrinking: a dropdown doesn't set the width of the form it sits in ---------

def test_a_long_item_does_not_hold_the_form_open(qtbot):
    # The failure this exists for: a dropdown's own minimum is its longest item, so a
    # model dropdown put a several-hundred-pixel floor under the settings form and a
    # narrow pane grew a horizontal scroll bar instead of squeezing the field.
    w = NoWheelDropdown()
    w.addItems(_MODELS)
    qtbot.addWidget(w)

    assert w.minimumSizeHint().width() < w.fontMetrics().horizontalAdvance(_MODELS[0]) / 3


def test_a_placeholder_does_not_hold_the_form_open_either(qtbot):
    # Qt widens both hints to hold the placeholder — and keeps that width after a
    # choice is made — so the workflow dropdown propped the pane open at the phrase
    # "Select a workflow…" for the rest of the session.
    bare = NoWheelDropdown()
    bare.addItems(_MODELS)
    qtbot.addWidget(bare)
    w = NoWheelDropdown()
    w.addItems(_MODELS)
    w.setPlaceholderText("Select a workflow…")
    qtbot.addWidget(w)

    assert w.minimumSizeHint().width() == bare.minimumSizeHint().width()


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
    # Only the floor moves. A dropdown laid out at its own hint rather than stretched
    # to fill a row — the sort dropdown over the search results — must still come out
    # wide enough to read, so this can't be done by shrinking what it asks for.
    labels = ["Newest first", "Model + LoRA bands"]
    stock = QComboBox()
    stock.addItems(labels)
    qtbot.addWidget(stock)
    w = NoWheelDropdown()
    w.addItems(labels)
    qtbot.addWidget(w)

    assert w.sizeHint() == stock.sizeHint()
    assert w.display_text(w.sizeHint().width()) == "Newest first"
