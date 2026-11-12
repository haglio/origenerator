from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QSplitter, QWidget

_SHOWN_OR_HIDDEN = (QEvent.Type.ShowToParent, QEvent.Type.HideToParent)


class ItemArea(QObject):
    def __init__(self, area: QWidget, sections: tuple[QWidget, ...], splitter: QSplitter,
                 dragged):
        super().__init__(area)
        self._area = area
        self._sections = sections
        self._splitter = splitter
        self._dragged = dragged
        self._sharing = False
        for section in sections:
            section.installEventFilter(self)
        splitter.installEventFilter(self)
        self._follow()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._splitter:
            if event.type() == QEvent.Type.Show:
                QTimer.singleShot(0, self, self._share)
        elif event.type() in _SHOWN_OR_HIDDEN:
            self._follow()
        return False

    def _follow(self) -> None:
        showing = any(not section.isHidden() for section in self._sections)
        appearing = showing and self._area.isHidden()
        self._area.setVisible(showing)
        if appearing:
            QTimer.singleShot(0, self, self._share)

    def _share(self) -> None:
        if self._sharing or self._dragged() or self._area.isHidden():
            return
        whole = sum(self._splitter.sizes())
        if whole:
            self._sharing = True
            try:
                self._splitter.setSizes([whole - whole // 2, whole // 2])
            finally:
                self._sharing = False
