import json

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from origenerator.gui.metadata_block import MetadataBlock


def _row(**overrides):
    """A completed video — the shape whose file this block still carries.

    An image's files are versions of it now, each listed with the enhancement
    level that made it, so an image row renders no block at all."""
    row = {
        "status": "completed",
        "source": "generated",
        "created_at": "2026-07-01",
        "workflow_name": "wan22_i2v",
        "params_json": json.dumps({"seed": 7, "positive_prompt": "hi"}),
        "output_files": json.dumps([{"filename": "out.mp4", "subfolder": "video"}]),
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


def test_shows_file_and_created(block):
    block.show_row(_row())
    texts = _texts(block)
    assert "video/out.mp4" in texts   # the file the tab is looking at — the regression
    assert "2026-07-01" in texts
    assert "completed" not in texts   # Details (status/source) dropped as not useful
    assert "generated" not in texts


def test_copy_button_copies_just_the_filename(block):
    block.show_row(_row())
    copy_btns = [b for b in block.findChildren(QPushButton)
                 if b.objectName() == "copyButton"]
    assert len(copy_btns) == 1   # only the File row is copyable in a normal row
    copy_btns[0].click()
    assert QApplication.clipboard().text() == "out.mp4"   # not "video/out.mp4"


def _reveal_btns(block):
    return [b for b in block.findChildren(QPushButton)
            if b.objectName() == "revealButton"]


def test_file_row_reveals_the_output_file_in_explorer(block, monkeypatch, tmp_path):
    import origenerator.gui.metadata_block as mb
    import origenerator.generation_metadata as gm

    monkeypatch.setattr(gm, "COMFYUI_OUTPUT_DIR", tmp_path)  # reveal points into tmp
    (tmp_path / "out.mp4").write_bytes(b"x")                 # ...at a real file
    revealed = []
    monkeypatch.setattr(mb, "show_in_explorer", lambda p: revealed.append(p))

    block.show_row(_row(output_files=json.dumps(
        [{"filename": "out.mp4", "subfolder": ""}])))
    btns = _reveal_btns(block)
    assert len(btns) == 1                 # only the File row reveals
    btns[0].click()
    assert revealed == [tmp_path / "out.mp4"]


def test_reveal_button_is_disabled_when_the_output_is_gone(block, monkeypatch, tmp_path):
    import origenerator.generation_metadata as gm

    monkeypatch.setattr(gm, "COMFYUI_OUTPUT_DIR", tmp_path)  # nothing created here
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "gone.mp4", "subfolder": ""}])))
    btns = _reveal_btns(block)
    assert len(btns) == 1
    assert btns[0].isEnabled() is False   # greyed out rather than opening the wrong place


def test_show_row_replaces_the_previous_render(block):
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "first.mp4", "subfolder": ""}])))
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "second.mp4", "subfolder": ""}])))
    texts = _texts(block)
    assert "second.mp4" in texts
    assert "first.mp4" not in texts   # the old container is gone, not stacked


def test_an_image_renders_no_block(block):
    # Its files are its versions, listed with the enhancement levels that made
    # them; there is nothing left for this block to repeat.
    block.show_row(_row(workflow_name="sdxl_t2i", output_files=json.dumps(
        [{"filename": "out.png", "subfolder": "image"}])))
    assert _texts(block) == []
