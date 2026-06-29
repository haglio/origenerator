import json

from PyQt6.QtWidgets import QLabel

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


def test_clear_removes_all_rendered_content(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.show_row(_row())
    assert _label_texts(panel)  # populated

    panel.clear()
    assert _label_texts(panel) == []
