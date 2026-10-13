"""Clicks sent through the window under the pointer, as a mouse sends them: QTest
handed a widget skips whatever lies on top of it, and its double-click is the
double-click event alone, without the press and release a mouse sends first."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget


def _where_the_mouse_lands(widget: QWidget, at: QPoint):
    holder = widget
    while holder.windowHandle() is None:
        holder = holder.parentWidget()
    return holder.windowHandle(), widget.mapTo(holder, at)


def double_click(widget: QWidget, at: QPoint) -> None:
    window, point = _where_the_mouse_lands(widget, at)
    QTest.mouseDClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def click(widget: QWidget, at: QPoint,
          modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    window, point = _where_the_mouse_lands(widget, at)
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, modifiers, point)


def move(widget: QWidget, at: QPoint) -> None:
    window, point = _where_the_mouse_lands(widget, at)
    QTest.mouseMove(window, point)


def press(widget: QWidget, at: QPoint) -> None:
    window, point = _where_the_mouse_lands(widget, at)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def release(widget: QWidget, at: QPoint) -> None:
    window, point = _where_the_mouse_lands(widget, at)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def press_key(widget: QWidget, key: Qt.Key,
              modifiers: Qt.KeyboardModifier = Qt.KeyboardModifier.NoModifier) -> None:
    QTest.keyClick(widget.window().windowHandle(), key, modifiers)


def right_click(widget: QWidget, at: QPoint) -> None:
    window, point = _where_the_mouse_lands(widget, at)
    QTest.mouseClick(window, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier, point)
