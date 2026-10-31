from __future__ import annotations

import re

from PyQt6.QtWidgets import QApplication, QVBoxLayout, QWidget
from shared_ui import folder_path as shared_folder_path
from shared_ui.spacing import GAP_MEDIUM

from origenerator.gui.copy_button import CopyButton
from origenerator.gui.folder_path import FolderPath
from origenerator.gui.gallery_tree import PathStep

_STEPS = [PathStep("Landscape", None), PathStep("All", "all@landscape"),
          PathStep("SDXL T2I", "sdxl@landscape"), PathStep("3A7F2C10", "leaf@landscape")]
_PATH = "Landscape  ›  All  ›  SDXL T2I  ›  3A7F2C10"


def _header(qtbot):
    header = FolderPath()
    qtbot.addWidget(header)
    return header


def _links(header) -> dict[str, str]:
    drawn = header.findChild(shared_folder_path.FolderPath).text()
    return {name: href for href, name in re.findall(r'<a href="([^"]*)"[^>]*>([^<]*)</a>', drawn)}


def test_every_folder_above_the_one_shown_is_a_link_to_it(qtbot):
    header = _header(qtbot)

    header.show_folder(_STEPS)

    assert list(_links(header)) == ["All", "SDXL T2I"]
    assert header.display_text() == _PATH


def test_clicking_a_step_chooses_the_folder_it_names(qtbot):
    header = _header(qtbot)
    header.show_folder(_STEPS)

    with qtbot.waitSignal(header.folder_chosen) as chosen:
        header.findChild(shared_folder_path.FolderPath).linkActivated.emit(_links(header)["All"])

    assert chosen.args == ["all@landscape"]


def test_a_search_links_every_folder_it_looks_in(qtbot):
    header = _header(qtbot)

    header.show_search("Search: “a cat” in ", _STEPS)

    assert list(_links(header)) == ["All", "SDXL T2I", "3A7F2C10"]
    assert header.display_text() == f"Search: “a cat” in {_PATH}"


def test_a_line_that_is_no_folders_path_links_nothing(qtbot):
    header = _header(qtbot)
    header.show_folder(_STEPS)

    header.set_display("2 folders")

    assert _links(header) == {}
    assert header.display_text() == "2 folders"


def test_the_copy_button_copies_the_line_as_it_reads_now(qtbot):
    header = _header(qtbot)
    header.set_display("2 folders")
    header.show_search("Search: “a cat” in ", _STEPS)

    header.findChild(CopyButton).click()

    assert QApplication.clipboard().text() == f"Search: “a cat” in {_PATH}"


def test_the_copy_button_sits_left_of_a_wrapped_path_level_with_its_first_line(qtbot):
    pane = QWidget()
    qtbot.addWidget(pane)
    column = QVBoxLayout(pane)
    column.setContentsMargins(0, 0, 0, 0)
    header = FolderPath()
    column.addWidget(header)
    column.addStretch(1)
    header.show_folder([PathStep("Landscape", None),
                        *(PathStep("SDXL T2I", f"k{i}") for i in range(6))])
    pane.setFixedSize(400, 600)
    pane.show()
    column.activate()
    copy, path = header.findChild(CopyButton).geometry(), header.findChild(shared_folder_path.FolderPath).geometry()

    assert path.left() - copy.right() - 1 == GAP_MEDIUM
    assert copy.top() == path.top()
    assert path.height() > 2 * copy.height()
