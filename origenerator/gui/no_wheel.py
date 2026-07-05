"""Form widgets that don't hijack the mouse wheel.

A QComboBox / QSpinBox / QDoubleSpinBox changes its value on a wheel scroll, so
scrolling a settings form accidentally edits whatever field the cursor happens to
be over. These subclasses ignore the wheel event, so it scrolls the enclosing form
instead of changing the field's value.
"""

from PyQt6.QtWidgets import QComboBox, QDoubleSpinBox, QSpinBox


class NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()  # let the form scroll; don't change the selection


class NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()
