from PyQt6.QtCore import Qt

from origenerator.gui.preset_combo import PresetComboBox


def test_presets_are_offered_with_their_unit_and_a_typed_number_reads_back(qtbot):
    combo = PresetComboBox([1, 5, 10, 15, 30], unit="s")
    qtbot.addWidget(combo)
    assert [combo.itemText(i) for i in range(combo.count())] == \
        ["1 s", "5 s", "10 s", "15 s", "30 s"]
    combo.setCurrentText("7")
    assert combo.value() == 7
    combo.setCurrentText("2.5 s")
    assert combo.value() == 2.5


def test_letters_cannot_be_typed_and_an_empty_field_has_no_value(qtbot):
    combo = PresetComboBox([16, 24], unit="fps")
    qtbot.addWidget(combo)
    combo.setCurrentText("")
    qtbot.keyClicks(combo.lineEdit(), "abc")
    assert combo.currentText() == ""
    assert combo.value() is None


def test_edited_fires_when_typing_ends_and_when_a_preset_is_picked(qtbot):
    combo = PresetComboBox([16, 24], unit="fps")
    qtbot.addWidget(combo)
    combo.show()
    qtbot.waitExposed(combo)
    edits = []
    combo.edited.connect(lambda: edits.append(combo.value()))

    combo.lineEdit().setFocus()
    combo.setCurrentText("30")
    qtbot.keyClick(combo.lineEdit(), Qt.Key.Key_Return)
    assert edits == [30]

    qtbot.keyClick(combo, Qt.Key.Key_Down)   # step onto the next preset
    assert edits == [30, 24]
