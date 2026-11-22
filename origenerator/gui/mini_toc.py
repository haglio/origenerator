from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, QPoint, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from shared_ui.spacing import GAP_SMALL, MARGIN_STANDARD

from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.eliding import ElidingButton

GENERATION_SETTINGS = "Generation settings"
ITEM_INFO = "Item info"


class MiniToc(QWidget):
    def __init__(self, heading: str, scroll: QScrollArea, parent=None):
        super().__init__(parent)
        self._scroll = scroll
        self._peers: tuple[MiniToc, ...] = (self,)
        self._column = QVBoxLayout(self)
        self._column.setContentsMargins(MARGIN_STANDARD, MARGIN_STANDARD, 0, 0)
        self._column.setSpacing(GAP_SMALL)
        self._heading = QLabel(heading)
        self._heading.setObjectName("miniTocHeading")
        self._column.addWidget(self._heading)
        self._entries: list[ElidingButton] = []
        self._listed: list[CollapsibleSection] = []
        self._column.addStretch(1)
        self._following = QTimer(self, singleShot=True, interval=0)
        self._following.timeout.connect(self.follow_the_sections)
        scroll.widget().installEventFilter(self)
        self.follow_the_sections()

    def heading(self) -> str:
        return self._heading.text()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(max(peer.natural_width() for peer in self._peers))
        return hint

    def natural_width(self) -> int:
        return QWidget.sizeHint(self).width()

    def has_room(self) -> bool:
        pane = self.parentWidget()
        return pane is None or pane.width() >= self.sizeHint().width() + scroll_floor(self._scroll)

    def show_if_there_is_room(self) -> None:
        shown = all(peer.has_room() for peer in self._peers)
        for peer in self._peers:
            if peer.isHidden() == shown:
                peer.setVisible(shown)
                if (pane := peer.parentWidget()) is not None:
                    pane.layout().activate()

    def line_up_with(self, peers: tuple[MiniToc, ...]) -> None:
        self._peers = peers
        self.updateGeometry()

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.LayoutRequest:
            self._following.start()
        return False

    def _shown_sections(self) -> list[CollapsibleSection]:
        host = self._scroll.widget()
        shown = [section for section in host.findChildren(CollapsibleSection)
                 if section.isVisibleTo(host)]
        return sorted(shown, key=lambda section: section.mapTo(host, QPoint()).y())

    def follow_the_sections(self) -> None:
        shown = self._shown_sections()
        if shown == self._listed:
            return
        for entry in self._entries:
            entry.deleteLater()
        self._entries = [self._entry_for(section) for section in shown]
        for entry in self._entries:
            self._column.insertWidget(self._column.count() - 1, entry)
        self._listed = shown
        for peer in self._peers:
            peer.updateGeometry()
        self.show_if_there_is_room()

    def _entry_for(self, section: CollapsibleSection) -> ElidingButton:
        entry = ElidingButton(section.title())
        entry.setObjectName("miniTocEntry")
        entry.setFlat(True)
        entry.setCursor(Qt.CursorShape.PointingHandCursor)
        entry.setToolTip(section.title())
        entry.clicked.connect(lambda _checked=False: self._open_alone(section))
        return entry

    def _open_alone(self, chosen: CollapsibleSection) -> None:
        for section in self._shown_sections():
            section.fold_as_if_pressed(section is not chosen)
        QTimer.singleShot(0, self, lambda: self._bring_to_the_top(chosen))

    def _bring_to_the_top(self, chosen: CollapsibleSection) -> None:
        host = self._scroll.widget()
        QApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
        self._scroll.verticalScrollBar().setValue(chosen.mapTo(host, QPoint()).y())


def line_up(tocs: tuple[MiniToc, ...]) -> None:
    for toc in tocs:
        toc.line_up_with(tocs)


class _PaneWithMiniToc(QWidget):
    def __init__(self, heading: str, scroll: QScrollArea):
        super().__init__()
        self._toc = MiniToc(heading, scroll)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(self._toc)
        row.addWidget(scroll, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._toc.show_if_there_is_room()


def beside_its_mini_toc(heading: str, scroll: QScrollArea) -> QWidget:
    return _PaneWithMiniToc(heading, scroll)


def scroll_floor(scroll: QScrollArea) -> int:
    return (scroll.widget().minimumSizeHint().width()
            + scroll.verticalScrollBar().sizeHint().width()
            + 2 * scroll.frameWidth()
            + 2 * MARGIN_STANDARD)
