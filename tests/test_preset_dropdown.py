from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QWidget

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

    qtbot.keyClick(dropdown, Qt.Key.Key_Down)
    assert edits == [30, 24]


@pytest.fixture
def _wearing_the_apps_own_chrome():
    app = QApplication.instance()
    prior = app.styleSheet()
    app.setStyleSheet(build_stylesheet())
    yield
    app.setStyleSheet(prior)


@pytest.mark.usefixtures("_wearing_the_apps_own_chrome")
def test_the_longest_preset_fits_the_field_it_is_shown_in(qtbot):
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
    assert field.width() > widest + 4, (
        "measured dressed the way the app dresses it: the stylesheet's padding comes out of the "
        "very field this is about")


def test_presets_made_unavailable_stay_listed_but_cannot_be_picked_and_say_why_on_hover(qtbot):
    dropdown = PresetDropdown([16, 24, 32], unit="fps")
    qtbot.addWidget(dropdown)

    dropdown.set_unavailable([24], "example reason")

    items = [dropdown.model().item(i) for i in range(dropdown.count())]
    assert [(item.text(), item.isEnabled()) for item in items] == [
        ("16 fps", True), ("24 fps", False), ("32 fps", True)], (
        "a preset the model cannot produce is worse than a missing one: chosen, it silently "
        "becomes a different setting; it is grayed rather than dropped so the list reads as the "
        "same list at every workflow, with the ones out of reach visibly out of reach")
    assert items[1].toolTip() == "example reason"

