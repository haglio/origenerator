from origenerator.gui.editable_header import EditableHeader


def test_begin_edit_shows_a_prefilled_editor(qtbot):
    header = EditableHeader()
    qtbot.addWidget(header)
    header.set_display("Images › SDXL Text-to-Image")

    header.begin_edit("SDXL Text-to-Image")
    assert header._editing() is True
    assert header._edit.text() == "SDXL Text-to-Image"


def test_finishing_an_edit_emits_the_new_value_and_returns_to_label(qtbot):
    header = EditableHeader()
    qtbot.addWidget(header)
    header.begin_edit("old name")
    header._edit.setText("new name")

    with qtbot.waitSignal(header.edited) as blocker:
        header._edit.editingFinished.emit()

    assert blocker.args == ["new name"]
    assert header._editing() is False


def test_escape_cancels_without_emitting_or_changing_display(qtbot):
    header = EditableHeader()
    qtbot.addWidget(header)
    header.set_display("Videos")
    header.begin_edit("old name")
    header._edit.setText("discarded")

    with qtbot.assertNotEmitted(header.edited):
        header._edit.cancelled.emit()  # what pressing Escape triggers

    assert header._editing() is False
    assert header.display_text() == "Videos"
