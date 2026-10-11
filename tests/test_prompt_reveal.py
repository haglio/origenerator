from __future__ import annotations

from PyQt6 import sip
from PyQt6.QtCore import QCoreApplication, QEvent
from PyQt6.QtWidgets import QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.prompt_reveal import reveal_prompt


def test_revealing_a_prompt_unfolds_the_section_hiding_it(qtbot):
    # The Foley prompts sit in a section that starts closed, and a match inside a
    # closed section is one the user is told about but can't be shown.
    section = CollapsibleSection("Audio", collapsed=True)
    field = QPlainTextEdit(section.content())
    field.setPlainText("a cat purring")
    qtbot.addWidget(section)
    assert section.is_collapsed()

    reveal_prompt(field)

    assert not section.is_collapsed()


def test_revealing_a_prompt_scrolls_the_form_to_its_field(qtbot):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    host = QWidget()
    column = QVBoxLayout(host)
    filler = QPlainTextEdit("\n" * 200)
    filler.setMinimumHeight(1200)
    column.addWidget(filler)
    target = QPlainTextEdit("a cat")
    column.addWidget(target)
    scroll.setWidget(host)
    scroll.resize(300, 200)
    qtbot.addWidget(scroll)
    scroll.show()
    qtbot.waitExposed(scroll)

    reveal_prompt(target)

    assert scroll.verticalScrollBar().value() > 0


def test_a_field_gone_before_the_second_scroll_leaves_nothing_to_fail(qtbot):
    host = QWidget()
    field = QPlainTextEdit("a cat", host)
    qtbot.addWidget(host)
    reveal_prompt(field)

    field.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert sip.isdeleted(field)

    qtbot.wait(50)
