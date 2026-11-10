from __future__ import annotations

import json

import pytest
from PyQt6.QtWidgets import QApplication, QLabel, QPushButton
from shared_ui.colors import TEXT_MUTED

import origenerator.gui.metadata_section as metadata_section_module
from origenerator import config
from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.metadata_section import MetadataSection
from origenerator.output_places import OutputPlaces
from origenerator.provenance import BASIS, WORKFLOW, WORKFLOW_VERSION
from tests import gestures

_LEAD_VIDEO = {"filename": "lead.mp4", "subfolder": "video"}


def _row(**overrides):
    row = {
        "status": "completed",
        "source": "generated",
        "created_at": "2026-07-01",
        "workflow_name": "wan22_i2v",
        "params_json": json.dumps({"seed": 7, "positive_prompt": "hi"}),
        "output_files": json.dumps([{"filename": "out.mp4", "subfolder": "video"}]),
    }
    row.update(overrides)
    if row["workflow_name"] == "wan22_i2v":
        row["output_files"] = json.dumps([_LEAD_VIDEO, *json.loads(row["output_files"])])
    return row


@pytest.fixture
def block(qtbot):
    b = MetadataSection()
    qtbot.addWidget(b)
    return b


def _texts(block):
    return [lbl.text().replace("\u200b", "") for lbl in block.findChildren(QLabel)]


def test_a_folded_block_stays_folded_for_the_next_item_shown(qtbot, block):
    block.show_row(_row())
    block.resize(400, 300)
    with qtbot.waitExposed(block):
        block.show()
    header = block.findChild(CollapsibleSection)._header
    gestures.click(header, header.rect().center())

    block.show_row(_row(created_at="2026-07-02"))

    assert block.findChild(CollapsibleSection).is_collapsed()


def test_a_fold_put_back_after_a_restart_folds_the_block_shown_and_the_next(block):
    block.show_row(_row())

    block.set_folded(True)
    folded_now = block.findChild(CollapsibleSection).is_collapsed()
    block.show_row(_row(created_at="2026-07-02"))

    assert (folded_now, block.findChild(CollapsibleSection).is_collapsed()) == (True, True)


def test_shows_file_and_created(block):
    block.show_row(_row())
    texts = _texts(block)
    assert "video/out.mp4" in texts
    assert "2026-07-01" in texts
    assert "completed" not in texts
    assert "generated" not in texts


def test_a_long_unbroken_value_is_given_places_to_wrap(block):
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "wan22_i2v_00042_.mp4", "subfolder": "video/loops"}])))

    raw = [text for text in (lbl.text() for lbl in block.findChildren(QLabel))
           if "wan22" in text]

    zwsp = "\u200b"
    assert raw == [f"video/{zwsp}loops/{zwsp}wan22_{zwsp}i2v_{zwsp}00042_{zwsp}.{zwsp}mp4"]


def test_the_name_lines_copy_button_copies_the_items_name(block):
    block.show_row(_row(), name="AB12CD34 007")
    name_copy, _file_copy = [b for b in block.findChildren(QPushButton)
                             if b.objectName() == "copyButton"]

    name_copy.click()

    assert ("AB12CD34 007" in _texts(block),
            QApplication.clipboard().text()) == (True, "AB12CD34 007")


def test_the_name_it_already_shows_leaves_the_block_alone(block):
    block.show_row(_row(), name="AB12CD34 007")
    section = block.findChild(CollapsibleSection)
    labels = block.findChildren(QLabel)

    block.show_name("AB12CD34 007")

    assert block.findChild(CollapsibleSection) is section
    assert block.findChildren(QLabel) == labels, (
        "the name is asked again after every redraw of the gallery, while it may be text the user "
        "is selecting")


def test_copy_button_copies_just_the_filename(block):
    block.show_row(_row())
    copy_btns = [b for b in block.findChildren(QPushButton)
                 if b.objectName() == "copyButton"]
    assert len(copy_btns) == 1
    copy_btns[0].click()
    assert QApplication.clipboard().text() == "out.mp4"


def _reveal_btns(block):
    return [b for b in block.findChildren(QPushButton)
            if b.objectName() == "revealButton"]


def test_file_row_reveals_the_output_file_in_explorer(block, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    (tmp_path / "out.mp4").write_bytes(b"x")
    revealed = []
    monkeypatch.setattr(metadata_section_module, "show_in_explorer", revealed.append)

    block.show_row(_row(output_files=json.dumps(
        [{"filename": "out.mp4", "subfolder": ""}])))
    btns = _reveal_btns(block)
    assert len(btns) == 1
    btns[0].click()
    assert revealed == [tmp_path / "out.mp4"]


def test_reveal_button_is_disabled_when_the_output_is_gone(block, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUT_PLACES", OutputPlaces.in_one_folder(tmp_path))
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "gone.mp4", "subfolder": ""}])))
    btns = _reveal_btns(block)
    assert len(btns) == 1
    assert btns[0].isEnabled() is False


def test_show_row_replaces_the_previous_render(block):
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "first.mp4", "subfolder": ""}])))
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "second.mp4", "subfolder": ""}])))
    texts = _texts(block)
    assert "second.mp4" in texts
    assert "first.mp4" not in texts


def test_an_image_renders_no_facts(block):
    shown = block.show_row(_row(workflow_name="sdxl_t2i", output_files=json.dumps(
        [{"filename": "out.png", "subfolder": "image"}])))
    assert (shown, [text for text in _texts(block) if text]) == (False, [])


def test_an_image_with_a_recorded_workflow_version_shows_that_line(block):
    shown = block.show_row(_row(
        workflow_name="sdxl_t2i",
        output_files=json.dumps([{"filename": "out.png", "subfolder": "image"}]),
        provenance=json.dumps({WORKFLOW: "sdxl_t2i", WORKFLOW_VERSION: "v004",
                               "app_commit": None, "app_dirty": None,
                               BASIS: "recorded"})))

    assert (shown, "Workflow version" in _texts(block), "v004" in _texts(block)) == (
        True, True, True)


def test_the_reveal_button_does_not_hold_the_pane_open(block):
    block.show_row(_row(output_files=json.dumps(
        [{"filename": "out.mp4", "subfolder": ""}])))
    btn, = _reveal_btns(block)

    whole = btn.fontMetrics().horizontalAdvance("Show in Explorer")
    assert btn.minimumSizeHint().width() < whole
    assert btn.display_text(whole // 3).endswith("…")


def test_a_facts_value_is_plain_text_in_the_muted_gray_typical_time_wears(block):
    block.show_row(_row(), name="AB12CD34 007")

    (value,) = [label for label in block.findChildren(QLabel)
                if label.text().replace("\u200b", "") == "AB12CD34 007"]

    assert TEXT_MUTED.name() in value.styleSheet()
