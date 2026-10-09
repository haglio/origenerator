from __future__ import annotations

from PyQt6.QtGui import QColor, QPixmap
from PyQt6.QtWidgets import QFormLayout, QLineEdit

from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.stylesheet import build_stylesheet

_MARK_COLOR = QColor(255, 0, 255)


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
    section = CollapsibleSection("Drawing", collapsed=True)
    qtbot.addWidget(section)
    assert "Drawing" in section._header.text()


def test_header_escapes_an_ampersand_instead_of_making_it_a_mnemonic(qtbot):
    # A raw "&" would be eaten as a QPushButton accelerator, showing "Models  Add-ons".
    section = CollapsibleSection("Models & Add-ons", collapsed=True)
    qtbot.addWidget(section)
    assert "Models && Add-ons" in section._header.text()


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


def _shown_section(qtbot, title: str, width: int) -> CollapsibleSection:
    section = CollapsibleSection(title, collapsed=True)
    section.setStyleSheet(build_stylesheet())
    qtbot.addWidget(section)
    section.resize(width, section.sizeHint().height())
    section.show()
    qtbot.waitExposed(section)
    return section


def _solid_mark(side: int = 12) -> QPixmap:
    mark = QPixmap(side, side)
    mark.fill(_MARK_COLOR)
    return mark


def _drawn_above_the_rule(header) -> list[tuple[int, int]]:
    image = header.grab().toImage()
    background = image.pixelColor(image.width() - 1, 0)
    return [(x, y) for y in range(image.height() - 1) for x in range(image.width())
            if image.pixelColor(x, y) != background]


def _mark_pixels(header) -> list[tuple[int, int]]:
    image = header.grab().toImage()
    return [(x, y) for y in range(image.height()) for x in range(image.width())
            if image.pixelColor(x, y) == _MARK_COLOR]


def test_a_mark_is_drawn_just_after_the_title_and_level_with_it(qtbot):
    section = _shown_section(qtbot, "Size", width=300)
    title = _drawn_above_the_rule(section._header)

    section.set_mark(_solid_mark(), "Portrait")
    mark = _mark_pixels(section._header)

    assert len(mark) == 12 * 12
    title_right = max(x for x, _ in title)
    mark_left = min(x for x, _ in mark)
    assert title_right < mark_left <= title_right + 12
    title_middle = (min(y for _, y in title) + max(y for _, y in title)) / 2
    mark_middle = (min(y for _, y in mark) + max(y for _, y in mark)) / 2
    assert abs(title_middle - mark_middle) <= 2


def test_a_squeezed_header_cuts_its_title_short_and_keeps_its_mark_whole(qtbot):
    section = _shown_section(qtbot, "Enhancement levels", width=300)
    section.set_mark(_solid_mark(), "Portrait")
    section.resize(section.minimumSizeHint().width(), section.height())
    qtbot.wait(10)

    mark = _mark_pixels(section._header)
    title = set(_drawn_above_the_rule(section._header)) - set(mark)
    assert len(mark) == 12 * 12
    assert max(x for x, _ in title) < min(x for x, _ in mark)
