from __future__ import annotations

from PyQt6.QtCore import QEvent, QPointF, Qt
from PyQt6.QtGui import QEnterEvent
from PyQt6.QtWidgets import QApplication, QPushButton

from origenerator.gui.link_tip import LinkTip, link


def _watched(qtbot, html="hello <a href=\"go\">there</a>"):
    button = QPushButton("watch me")
    qtbot.addWidget(button)
    button.show()
    tip = LinkTip(button)
    tip.set_html(html)
    return button, tip


def _enter(widget):
    point = QPointF(1.0, 1.0)
    # Qt's event filters only see what is dispatched through the application, as the pointer's own events are.
    QApplication.sendEvent(widget, QEnterEvent(point, point, widget.mapToGlobal(point)))


def _leave(widget):
    QApplication.sendEvent(widget, QEvent(QEvent.Type.Leave))


def test_hovering_shows_the_tip_after_a_pause(qtbot):
    button, tip = _watched(qtbot)

    _enter(button)

    assert tip._appear.isActive()
    assert not tip._popup.isVisible()
    tip._appear.timeout.emit()
    assert tip._popup.isVisible()
    assert "there" in tip._popup.label.text()


def test_the_tip_can_be_clicked_into(qtbot):
    button, tip = _watched(qtbot)
    _enter(button)
    tip._appear.timeout.emit()

    assert not tip._popup.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), (
        "Qt's own tooltip is transparent to the mouse and vanishes as the pointer moves toward it, so "
        "a link inside one can be drawn but never followed")
    flags = tip._popup.label.textInteractionFlags()
    assert flags == Qt.TextInteractionFlag.LinksAccessibleByMouse, (
        "links only: selecting the text would swallow the click that follows one")


def test_following_a_link_reports_its_href_and_closes_the_tip(qtbot):
    button, tip = _watched(qtbot)
    _enter(button)
    tip._appear.timeout.emit()
    followed = []
    tip.link_activated.connect(followed.append)

    tip._popup.label.linkActivated.emit("go")

    assert followed == ["go"]
    assert not tip._popup.isVisible()


def test_the_tip_lingers_on_the_way_out_so_the_link_is_reachable(qtbot):
    button, tip = _watched(qtbot)
    _enter(button)
    tip._appear.timeout.emit()

    _leave(button)

    assert tip._popup.isVisible()
    assert tip._hide.isActive()
    tip._popup.entered.emit()
    assert not tip._hide.isActive()


def test_leaving_the_tip_closes_it(qtbot):
    button, tip = _watched(qtbot)
    _enter(button)
    tip._appear.timeout.emit()
    tip._popup.entered.emit()

    tip._popup.left.emit()

    assert tip._hide.isActive()
    tip._hide.timeout.emit()
    assert not tip._popup.isVisible()


def test_clicking_the_watched_widget_closes_the_tip(qtbot):
    button, tip = _watched(qtbot)
    _enter(button)
    tip._appear.timeout.emit()

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert not tip._popup.isVisible(), (
        "the click has done whatever the tip was offering to explain, and what it says next is "
        "decided by the click's own outcome")


def test_taking_the_text_away_closes_an_open_tip(qtbot):
    button, tip = _watched(qtbot)
    _enter(button)
    tip._appear.timeout.emit()

    tip.set_html("")

    assert not tip._popup.isVisible(), (
        "the reason it was worth clicking into has ended, and a stale offer to go somewhere is worse "
        "than none")


def test_a_widget_with_nothing_to_say_shows_no_tip(qtbot):
    button, tip = _watched(qtbot, html="")

    _enter(button)

    assert not tip._appear.isActive()
    assert not tip._popup.isVisible()


def test_a_links_color_is_set_so_it_reads_as_a_link(qtbot):
    assert 'href="go"' in link("go", "Go to it")
    assert "color:" in link("go", "Go to it"), (
        "Qt's default link color is the desktop's, which on this app's dark surfaces can come out all "
        "but unreadable, and a link nobody sees is the same as no link")
