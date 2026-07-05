from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent

from origenerator.gui.no_wheel import (
    NoWheelComboBox, NoWheelDoubleSpinBox, NoWheelSpinBox,
)


def _wheel():
    """One downward wheel notch."""
    return QWheelEvent(
        QPointF(1, 1), QPointF(1, 1), QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )


def test_combo_box_ignores_the_wheel(qtbot):
    w = NoWheelComboBox()
    w.addItems(["a", "b", "c"])
    w.setCurrentIndex(1)
    qtbot.addWidget(w)
    event = _wheel()

    w.wheelEvent(event)

    assert w.currentIndex() == 1     # selection unchanged
    assert not event.isAccepted()    # ignored → scrolls the form instead of editing


def test_spin_box_ignores_the_wheel(qtbot):
    w = NoWheelSpinBox()
    w.setRange(0, 100)
    w.setValue(5)
    qtbot.addWidget(w)
    event = _wheel()

    w.wheelEvent(event)

    assert w.value() == 5
    assert not event.isAccepted()


def test_double_spin_box_ignores_the_wheel(qtbot):
    w = NoWheelDoubleSpinBox()
    w.setRange(0.0, 10.0)
    w.setValue(2.5)
    qtbot.addWidget(w)
    event = _wheel()

    w.wheelEvent(event)

    assert w.value() == 2.5
    assert not event.isAccepted()
