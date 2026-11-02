from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.gui import media_overlay
from origenerator.gui.media_overlay import float_over_media, raise_over_media


def test_raising_an_overlay_restacks_its_own_window_even_when_qt_already_counts_it_on_top(
        qtbot, monkeypatch):
    raised = []
    monkeypatch.setattr(media_overlay, "raise_window_without_activating", raised.append)
    host = QWidget()
    qtbot.addWidget(host)
    QLabel("under it", host)
    overlay = QLabel("over it", host)
    float_over_media(overlay)
    host.show()
    assert host.children()[-1] is overlay

    raise_over_media(overlay)

    assert raised == [int(overlay.winId())]


def test_a_caption_floated_over_media_lets_the_mouse_through_to_what_is_under_it(qtbot):
    caption = QLabel("caption")
    qtbot.addWidget(caption)

    float_over_media(caption)

    assert caption.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert caption.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)


def test_a_control_floated_over_media_keeps_the_mouse_for_itself(qtbot):
    control = QLabel("control")
    qtbot.addWidget(control)

    float_over_media(control, click_through=False)

    assert not control.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert control.testAttribute(Qt.WidgetAttribute.WA_NativeWindow)
