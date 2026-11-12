from PySide6.QtWidgets import QWidget

from origenerator.gui.widget_size import QWIDGETSIZE_MAX


def test_the_largest_widget_size_is_the_one_qt_gives_a_widget_left_unbounded(qapp):
    widget = QWidget()

    assert (widget.maximumWidth(), widget.maximumHeight()) == (QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
