from __future__ import annotations

import sys

from PySide6.QtWidgets import QMenu

from tests.qt_exec import faking_exec


def test_a_faked_exec_is_what_a_menu_made_by_name_runs(qapp, monkeypatch):
    opened = []
    faking_exec(monkeypatch, QMenu, lambda menu, *_: opened.append(menu))

    menu = sys.modules["PySide6.QtWidgets"].QMenu()
    menu.exec()

    assert opened == [menu]
