from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QWidget

from origenerator.gui.toc_editing import FOLDER_ACTIONS, AroundAnEdit, TocEditing
from tests.gallery_view_support import _menu_offering
from tests.test_gallery_tree import _gathered_tree, _image


class RenameTheFolder:
    def __init__(self):
        self.asked_of = []

    def offer(self, menu, asked, editing):
        return {menu.addAction("Rename…"): lambda: self.asked_of.append(asked.group.label)}


def _nothing(*_given):
    return None


def _editing(qtbot, rows, **parts):
    pane, toc, model = _gathered_tree(qtbot, rows, lambda _model: ())
    over = QWidget()
    qtbot.addWidget(over)
    editing = TocEditing(
        pane, toc, edits=None, library=SimpleNamespace(customs_by_shape={}),
        folder_switches=None, asks_over=over,
        screen=AroundAnEdit(refresh=_nothing, re_aim_every_button=_nothing, delete_rows=_nothing,
                            current_group=_nothing, showing_search=lambda: False,
                            draw_folder_favorite=_nothing),
        **parts)
    return editing, model


def test_a_new_action_on_a_folder_is_one_class_handed_to_the_tocs_editing(qtbot, monkeypatch):
    renaming = RenameTheFolder()
    editing, model = _editing(qtbot, [_image("a", "a red fox")],
                              folder_actions=(*FOLDER_ACTIONS, renaming))
    [workflow] = model
    raised = _menu_offering(monkeypatch, pick="Rename")

    editing.folder_context_menu(workflow.key, QPoint())

    assert raised[0][-1] == "Rename…"
    assert renaming.asked_of == [workflow.label]
