from PyQt6.QtWidgets import QLineEdit, QFormLayout

from origenerator.gui.collapsible_section import CollapsibleSection


def test_starts_expanded_shows_its_content(qtbot):
    section = CollapsibleSection("Prompts", collapsed=False)
    qtbot.addWidget(section)
    assert section.is_collapsed() is False
    assert section.content().isHidden() is False


def test_starts_collapsed_hides_its_content(qtbot):
    section = CollapsibleSection("Sampling", collapsed=True)
    qtbot.addWidget(section)
    assert section.is_collapsed() is True
    assert section.content().isHidden() is True


def test_header_shows_the_title(qtbot):
    section = CollapsibleSection("Sampling", collapsed=True)
    qtbot.addWidget(section)
    assert "Sampling" in section._header.text()


def test_header_escapes_an_ampersand_instead_of_making_it_a_mnemonic(qtbot):
    # A raw "&" would be eaten as a QPushButton accelerator, showing "Model  LoRA".
    section = CollapsibleSection("Model & LoRA", collapsed=True)
    qtbot.addWidget(section)
    assert "Model && LoRA" in section._header.text()


def test_clicking_the_header_toggles_and_emits(qtbot):
    section = CollapsibleSection("Sampling", collapsed=True)
    qtbot.addWidget(section)
    fired = []
    section.toggled.connect(lambda: fired.append(True))

    section._header.click()
    assert section.is_collapsed() is False
    assert section.content().isHidden() is False

    section._header.click()
    assert section.is_collapsed() is True
    assert section.content().isHidden() is True
    assert fired == [True, True]


def test_set_collapsed_drives_content_visibility_without_emitting(qtbot):
    # Programmatic collapse (restoring a default) must not masquerade as a user
    # toggle — nothing downstream should treat it as an interaction.
    section = CollapsibleSection("Frames", collapsed=False)
    qtbot.addWidget(section)
    fired = []
    section.toggled.connect(lambda: fired.append(True))

    section.set_collapsed(True)
    assert section.content().isHidden() is True
    assert fired == []


def test_rows_added_to_the_content_form_live_under_the_section(qtbot):
    section = CollapsibleSection("Prompts", collapsed=False)
    qtbot.addWidget(section)
    field = QLineEdit()
    section.content_form().addRow("Positive Prompt", field)

    assert isinstance(section.content_form(), QFormLayout)
    assert section.content_form().rowCount() == 1
    assert field.parent() is section.content()


def test_a_long_title_does_not_hold_the_form_open(qtbot):
    # A header names the rows below it; it has no business deciding how narrow the
    # pane can be squeezed. Its title elides instead — without this, "Enhancement
    # levels" alone was enough to put a horizontal scroll bar under the form.
    title = "Enhancement levels"
    section = CollapsibleSection(title, collapsed=True)
    qtbot.addWidget(section)

    whole = section._header.fontMetrics().horizontalAdvance(title)
    assert section.minimumSizeHint().width() < whole
    assert section._header.display_text(whole // 3).endswith("…")
