from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QLineEdit,
    QPlainTextEdit,
    QTextEdit,
    QWidget,
)

_TEXT_FIELDS = (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox)
_THE_SLIDESHOWS_KEYS = frozenset({Qt.Key.Key_Up, Qt.Key.Key_Down, Qt.Key.Key_Left, Qt.Key.Key_Right,
                                  Qt.Key.Key_W, Qt.Key.Key_A, Qt.Key.Key_S, Qt.Key.Key_D, Qt.Key.Key_E})


@dataclass(frozen=True)
class Presses:
    delete: Callable[[], None]
    copy_names: Callable[[], None]
    undo: Callable[[], None]
    redo: Callable[[], None]
    open_find: Callable[[], None]
    pause_or_play: Callable[[], None]
    motion_key: Callable[[int], bool]
    slideshows_key: Callable[[QEvent], bool]


class AppKeys(QObject):
    def __init__(self, screen: QWidget, *, find_bar, generate_pane: QWidget, presses: Presses,
                 standalone: Callable[[], bool]) -> None:
        super().__init__(screen)
        self._screen = screen
        self._find_bar = find_bar
        self._generate_pane = generate_pane
        self._presses = presses
        self._standalone = standalone

    def intercept(self, intercepting: bool) -> None:
        """Take (or hand back) every key the application delivers; Qt installs a filter already on its list once."""
        app = QApplication.instance()
        if app is None:
            return
        if intercepting:
            # Qt's scroll area keeps a clicked thumbnail's key press from the view, so neither keyPressEvent nor a shortcut delivers it.
            app.installEventFilter(self)
        else:
            app.removeEventFilter(self)

    def eventFilter(self, obj, event):  # noqa: N802 -- Qt's name
        if event.type() == QEvent.Type.KeyPress:
            if ((event.key() == Qt.Key.Key_Escape and self.handle_escape(event.modifiers()))
                    or self._hands_the_slideshow_its_key(event)):
                return True
            if (event.key() == Qt.Key.Key_Escape and self._find_bar.isVisible()
                    and not self.other_window_owns_keys()):
                self._find_bar.close_find()
                return True
            if (event.key() == Qt.Key.Key_F
                    and event.modifiers() & Qt.KeyboardModifier.ControlModifier
                    and self._screen.isVisible() and not self.other_window_owns_keys()):
                self._presses.open_find()
                return True
            if self.gallery_owns_keys() and (press := self._press_for_the_gallery(event)):
                press()
                return True
            if (self.gallery_owns_keys(even_from_the_generate_pane=True)
                    and not event.modifiers() & ~Qt.KeyboardModifier.KeypadModifier
                    and self._presses.motion_key(event.key())):
                return True
        # Qt hands an application-wide filter events for objects being destroyed;
        # the base class's answer for one dereferences a freed C++ pointer and aborts.
        return False

    def _hands_the_slideshow_its_key(self, event) -> bool:
        return (event.key() in _THE_SLIDESHOWS_KEYS and self._screen.isVisible()
                and not self.other_window_owns_keys()
                and not isinstance(QApplication.focusWidget(), _TEXT_FIELDS)
                and self._presses.slideshows_key(event))

    def _press_for_the_gallery(self, event):
        control = event.modifiers() & Qt.KeyboardModifier.ControlModifier
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Insert):
            return self._presses.delete
        if event.key() == Qt.Key.Key_C and control:
            return self._presses.copy_names
        if event.key() == Qt.Key.Key_Z and control:
            shifted = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            return self._presses.redo if shifted else self._presses.undo
        return None

    def handle_escape(self, modifiers) -> bool:
        if self.other_window_owns_keys():
            return False
        if self._escape_cancels_something():
            return False
        if modifiers & Qt.KeyboardModifier.ShiftModifier and self._standalone():
            return False
        self._presses.pause_or_play()
        return True

    def _escape_cancels_something(self) -> bool:
        if self._find_bar.isVisible():
            return True
        return isinstance(QApplication.focusWidget(), _TEXT_FIELDS)

    def other_window_owns_keys(self) -> bool:
        if QApplication.activeModalWidget() or QApplication.activePopupWidget():
            return True
        active = QApplication.activeWindow()
        return active is not None and active is not self._screen.window()

    def gallery_owns_keys(self, *, even_from_the_generate_pane: bool = False) -> bool:
        if not self._screen.isVisible() or self.other_window_owns_keys():
            return False
        focus = QApplication.focusWidget()
        if isinstance(focus, _TEXT_FIELDS):
            return False
        return even_from_the_generate_pane or not (
            focus is not None and self._generate_pane.isAncestorOf(focus))
