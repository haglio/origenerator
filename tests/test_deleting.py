from PySide6.QtWidgets import QMessageBox, QWidget
from shared_ui.testing import questions_answered

from origenerator.gui.deleting import asked_to_delete


def test_a_delete_is_asked_with_yes_as_the_default(qtbot, monkeypatch):
    over = QWidget()
    qtbot.addWidget(over)

    asked = questions_answered(monkeypatch, QMessageBox.StandardButton.Yes)

    deleted = asked_to_delete(over, "Delete “Alpha” and its 2 items?")

    [box] = asked
    assert deleted
    assert (box.title, box.text) == ("Delete", "Delete “Alpha” and its 2 items?")
    assert box.default == QMessageBox.StandardButton.Yes
