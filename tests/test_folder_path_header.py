from __future__ import annotations

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QFocusEvent
from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget

from origenerator.gui.folder_path_header import FolderPathHeader

_PATH = "Landscape  ›  All  ›  SDXL Text-to-Image  ›  3A7F2C10"


def _header(qtbot, path=_PATH):
    header = FolderPathHeader()
    qtbot.addWidget(header)
    header.set_display(path)
    return header


def test_double_clicking_the_path_asks_for_its_field(qtbot):
    header = _header(qtbot)
    header.show()

    with qtbot.waitSignal(header.edit_requested):
        qtbot.mouseDClick(header, Qt.MouseButton.LeftButton)


def test_the_field_opens_holding_the_whole_path_selected_for_copying(qtbot):
    header = _header(qtbot)

    header.begin_edit(_PATH)

    assert header._editing()
    assert header._edit.selectedText() == _PATH


def test_the_field_is_one_line_as_wide_as_the_path_over_it(qtbot):
    pane = QWidget()
    qtbot.addWidget(pane)
    column = QVBoxLayout(pane)
    column.setContentsMargins(0, 0, 0, 0)
    header = FolderPathHeader()
    header.set_display("Landscape  ›  All  ›  " + "  ›  ".join(["SDXL Text-to-Image"] * 6))
    column.addWidget(header)
    column.addStretch(1)
    pane.setFixedSize(400, 600)
    pane.show()
    one_line = header._edit.sizeHint().height()
    wrapped = header.height()
    assert wrapped > one_line

    header.begin_edit("Landscape  ›  All")
    column.activate()

    assert header._edit.width() == 400
    assert header._edit.height() == one_line

    qtbot.keyClick(header._edit, Qt.Key.Key_Escape)
    column.activate()

    assert header.height() == wrapped


def test_an_empty_field_asks_for_a_path(qtbot):
    header = _header(qtbot, "2 folders")

    header.begin_edit("")

    assert header._edit.placeholderText() == "Paste a folder's path"


def test_enter_goes_to_the_path_in_the_field(qtbot):
    header = _header(qtbot)
    header.begin_edit(_PATH)
    header._edit.setText("Portrait  ›  All")

    with qtbot.waitSignal(header.entered) as blocker:
        qtbot.keyClick(header._edit, Qt.Key.Key_Return)

    assert blocker.args == ["Portrait  ›  All"]
    assert not header._editing()


def test_escape_puts_the_path_back_without_going_anywhere(qtbot):
    header = _header(qtbot)
    header.begin_edit(_PATH)
    header._edit.setText("Portrait  ›  All")

    with qtbot.assertNotEmitted(header.entered):
        qtbot.keyClick(header._edit, Qt.Key.Key_Escape)

    assert not header._editing()
    assert header.display_text() == _PATH


def _focus_leaves(header, reason):
    QApplication.sendEvent(header._edit, QFocusEvent(QEvent.Type.FocusOut, reason))


def test_clicking_elsewhere_puts_the_path_back_without_going_anywhere(qtbot):
    header = _header(qtbot)
    header.begin_edit(_PATH)

    with qtbot.assertNotEmitted(header.entered):
        _focus_leaves(header, Qt.FocusReason.MouseFocusReason)

    assert not header._editing()


def test_the_fields_own_menu_and_other_windows_leave_it_open(qtbot):
    header = _header(qtbot)
    header.begin_edit(_PATH)

    _focus_leaves(header, Qt.FocusReason.PopupFocusReason)
    _focus_leaves(header, Qt.FocusReason.ActiveWindowFocusReason)

    assert header._editing()
    assert header._edit.selectedText() == _PATH
