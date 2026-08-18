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


def test_the_editor_is_one_line_and_the_width_of_the_name(qtbot):
    # The display can be a path wrapping to several lines; what is being edited
    # is the one folder at the end of it. An editor the size of the whole block
    # reads as though the whole path were up for editing.
    header = EditableHeader()
    qtbot.addWidget(header)
    header.set_display(
        "All  ›  Images  ›  SDXL Text-to-Image  ›  reapony_v80  ›  (no LoRA)  ›  3A7F2C10"
    )
    header.setFixedWidth(200)
    header.show()
    one_line = header._edit.sizeHint().height()
    assert header.heightForWidth(200) > one_line    # the path takes several

    header.begin_edit("3A7F2C10")

    assert header.heightForWidth(200) == header._edit.height() <= one_line
    assert header._edit.width() < 200               # and not the header's full width


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
