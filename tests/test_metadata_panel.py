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


def _minimal(**overrides):
    """A row pared down so a single copyable item is unambiguous: empty prompts
    (disabled buttons), no parameters, no output files unless overridden."""
    base = dict(positive_prompt="", negative_prompt="",
                params_json=json.dumps({}), output_files=json.dumps([]))
    base.update(overrides)
    return _row(**base)


def _label_texts(panel):
    return [lbl.text() for lbl in panel.findChildren(QLabel)]


def _copy_buttons(panel):
    return panel.findChildren(QPushButton, "copyButton")


def _enabled_copy_buttons(panel):
    return [b for b in _copy_buttons(panel) if b.isEnabled()]


def test_show_row_renders_every_section_title(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)

    panel.show_row(_row())

    texts = _label_texts(panel)
    for title in ("Basic", "Positive Prompt", "Negative Prompt",
                  "Parameters", "Details"):
        assert title in texts


def test_show_row_renders_labeled_values_and_prompt_text(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)

    panel.show_row(_row(positive_prompt="a fluffy cat",
                        params_json=json.dumps({"steps": 20, "seed": 42})))

    texts = _label_texts(panel)
    assert "Status" in texts and "completed" in texts  # a label: value pair
    assert "42" in texts                                 # the seed value (Parameters)
    assert "a fluffy cat" in texts                       # bare prompt text


def test_copy_button_shows_an_icon_not_the_word_copy(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.show_row(_minimal(seed=None, output_files=json.dumps(
        [{"filename": "out.png", "subfolder": ""}])))

    [button] = _enabled_copy_buttons(panel)  # the output file
    assert button.text() == ""            # no "Copy" label
    assert not button.icon().isNull()     # an icon instead


def test_copyable_item_renders_a_button_that_copies_its_text(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.show_row(_minimal(params_json=json.dumps({"seed": 42})))

    [button] = _enabled_copy_buttons(panel)  # the seed is the only copyable item
    button.click()

    assert QApplication.clipboard().text() == "42"


def test_output_file_copy_button_copies_the_bare_filename(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    # A video file shown as "video/…" must copy without that subfolder prefix.
    files = [{"filename": "wan_00001_.mp4", "subfolder": "video"}]
    panel.show_row(_minimal(seed=None, output_files=json.dumps(files)))

    [button] = _enabled_copy_buttons(panel)  # only the output file is copyable
    button.click()

    assert QApplication.clipboard().text() == "wan_00001_.mp4"


def test_empty_prompt_shows_no_placeholder_and_a_disabled_copy(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.show_row(_minimal(positive_prompt="a cat", negative_prompt=""))

    assert "(empty)" not in _label_texts(panel)  # nothing masquerades as the prompt
    disabled = [b for b in _copy_buttons(panel) if not b.isEnabled()]
    assert len(disabled) == 1                    # the empty negative prompt's button


def test_only_copyable_items_get_a_button(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    # Nothing worth copying: empty prompts, no seed/params/files.
    panel.show_row(_minimal(seed=None))

    # Status, Source and Created never offer a copy button; the two empty prompts
    # do, but disabled.
    assert len(_copy_buttons(panel)) == 2
    assert _enabled_copy_buttons(panel) == []


def test_clear_removes_all_rendered_content(qtbot):
    panel = MetadataPanel()
    qtbot.addWidget(panel)
    panel.show_row(_row())
    assert _label_texts(panel)  # populated

    panel.clear()
    assert _label_texts(panel) == []
