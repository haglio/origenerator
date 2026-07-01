import json

from PyQt6.QtWidgets import QApplication, QLabel, QPushButton

from origenerator.gui.metadata_panel import MetadataPanel


def _row(**overrides):
    row = {
        "status": "completed",
        "source": "generated",
        "seed": 7,
        "created_at": "2026-01-01",
        "positive_prompt": "a fluffy cat",
        "negative_prompt": "blurry",
        "params_json": json.dumps({"steps": 20}),
        "output_files": json.dumps([{"filename": "out.png", "subfolder": ""}]),
    }
    row.update(overrides)
    return row


def _label_texts(panel):
    return [lbl.text() for lbl in panel.findChildren(QLabel)]


def _copy_buttons(panel):
    return panel.findChildren(QPushButton, "copyButton")


def _only_seed_copyable(**overrides):
    """A row whose seed is the single copyable item (empty prompts, no files)."""
    return _row(positive_prompt="", negative_prompt="",
                output_files=json.dumps([]), **overrides)


def test_show_row_renders_every_section_title(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)

    panel.show_row(_row())

    texts = _label_texts(panel)
    for title in ("Details", "Positive Prompt", "Negative Prompt",
                  "Parameters", "Output Files"):
        assert title in texts


def test_show_row_renders_labeled_values_and_prompt_text(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)

    panel.show_row(_row(seed=42, positive_prompt="a fluffy cat"))

    texts = _label_texts(panel)
    assert "Status" in texts and "completed" in texts  # a label: value pair
    assert "42" in texts                                 # the seed value
    assert "a fluffy cat" in texts                       # bare prompt text


def test_copyable_item_renders_a_button_that_copies_its_text(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.show_row(_only_seed_copyable(seed=42))

    [button] = _copy_buttons(panel)  # the seed is the only copyable item here
    button.click()

    assert QApplication.clipboard().text() == "42"


def test_non_copyable_items_render_no_copy_button(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    # No seed, empty prompts, no files: nothing in the row is worth copying.
    panel.show_row(_only_seed_copyable(seed=None))
    assert _copy_buttons(panel) == []


def test_output_file_copy_button_copies_the_bare_filename(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    # A video file shown as "video/…" must copy without that subfolder prefix.
    files = [{"filename": "wan_00001_.mp4", "subfolder": "video"}]
    panel.show_row(_row(seed=None, positive_prompt="", negative_prompt="",
                        output_files=json.dumps(files)))

    [button] = _copy_buttons(panel)  # only the output file is copyable
    button.click()

    assert QApplication.clipboard().text() == "wan_00001_.mp4"


def test_clear_removes_all_rendered_content(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.show_row(_row())
    assert _label_texts(panel)  # populated

    panel.clear()
    assert _label_texts(panel) == []
