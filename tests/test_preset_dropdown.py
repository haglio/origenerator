from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QWidget

from origenerator.gui.preset_dropdown import PresetDropdown
from origenerator.gui.stylesheet import build_stylesheet


def test_presets_are_offered_with_their_unit_and_a_typed_number_reads_back(qtbot):
    dropdown = PresetDropdown([1, 5, 10, 15, 30], unit="s")
    qtbot.addWidget(dropdown)
    assert [dropdown.itemText(i) for i in range(dropdown.count())] == \
        ["1 s", "5 s", "10 s", "15 s", "30 s"]
    dropdown.setCurrentText("7")
    assert dropdown.value() == 7
    dropdown.setCurrentText("2.5 s")
    assert dropdown.value() == 2.5


def test_letters_cannot_be_typed_and_an_empty_field_has_no_value(qtbot):
    dropdown = PresetDropdown([16, 24], unit="fps")
    qtbot.addWidget(dropdown)
    dropdown.setCurrentText("")
    qtbot.keyClicks(dropdown.lineEdit(), "abc")
    assert dropdown.currentText() == ""
    assert dropdown.value() is None


def test_edited_fires_when_typing_ends_and_when_a_preset_is_picked(qtbot):
    dropdown = PresetDropdown([16, 24], unit="fps")
    qtbot.addWidget(dropdown)
    with qtbot.waitExposed(dropdown):
        dropdown.show()
    edits = []
    dropdown.edited.connect(lambda: edits.append(dropdown.value()))

    dropdown.lineEdit().setFocus()
    dropdown.setCurrentText("30")
    qtbot.keyClick(dropdown.lineEdit(), Qt.Key.Key_Return)
    assert edits == [30]

    qtbot.keyClick(dropdown, Qt.Key.Key_Down)   # step onto the next preset
    assert edits == [30, 24]


@pytest.fixture
def _wearing_the_apps_own_chrome():
    """Measure the box dressed the way the app dresses it: the sheet's padding
    comes out of the very field this is about."""
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(prior)


@pytest.mark.usefixtures("_wearing_the_apps_own_chrome")
def test_the_longest_preset_fits_the_field_it_is_shown_in(qtbot):
    """The dropdown is as wide as the longest length it offers, and then some.

    Two pixels short of its widest text, the field scrolled rather than clipped:
    "10 s" was drawn as "0 s", a length the dropdown never offered and the user
    never chose.
    """
    dropdown = PresetDropdown([1, 5, 10, 15, 30, 60], unit="s")
    host = QWidget()
    QHBoxLayout(host).addWidget(dropdown)
    qtbot.addWidget(host)
    host.resize(host.sizeHint())
    with qtbot.waitExposed(host):
        host.show()

    dropdown.set_value(10)
    field = dropdown.lineEdit()
    widest = max(field.fontMetrics().horizontalAdvance(dropdown.itemText(index))
                 for index in range(dropdown.count()))
    # The line edit keeps two pixels either side of the text it draws.
    assert field.width() > widest + 4
