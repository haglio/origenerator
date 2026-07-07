import json

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from origenerator.gui.metadata_block import MetadataBlock


def _row(**overrides):
    row = {
        "status": "completed",
        "source": "generated",
        "created_at": "2026-07-01",
        "workflow_name": "sdxl_t2i",
        "params_json": json.dumps({"seed": 7, "positive_prompt": "hi"}),
        "output_files": json.dumps([{"filename": "out.png", "subfolder": "image"}]),
    }
    row.update(overrides)
    return row


@pytest.fixture
def block(qtbot):
    b = MetadataBlock()
    qtbot.addWidget(b)
    return b


def _texts(block):
    """Every label's text, with the on-screen wrapping zero-width spaces removed."""
    return [lbl.text().replace("​", "") for lbl in block.findChildren(QLabel)]


def test_shows_file_created_status_and_source(block):
    block.show_row(_row())
    texts = _texts(block)
    assert "image/out.png" in texts   # the file the tab is looking at — the regression
    assert "2026-07-01" in texts
    assert "completed" in texts
    assert "generated" in texts


def test_copy_button_copies_just_the_filename(block):
    block.show_row(_row())
    copy_btns = [b for b in block.findChildren(QPushButton)
                 if b.objectName() == "copyButton"]
    assert len(copy_btns) == 1   # only the File row is copyable in a normal row
    copy_btns[0].click()
    assert QApplication.clipboard().text() == "out.png"   # not "image/out.png"


def test_show_row_replaces_the_previous_render(block):
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "first.png", "subfolder": ""}])))
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "second.png", "subfolder": ""}])))
    texts = _texts(block)
    assert "second.png" in texts
    assert "first.png" not in texts   # the old container is gone, not stacked
