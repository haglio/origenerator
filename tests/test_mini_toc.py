from __future__ import annotations

from app_support.threading_utils import wait_until
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QVBoxLayout, QWidget

from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.eliding import ElidingButton
from origenerator.gui.mini_toc import MiniToc, beside_its_mini_toc, line_up, scroll_floor


def _scroll_holding(qtbot, *titles: str) -> tuple[QScrollArea, dict[str, CollapsibleSection]]:
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    host = QWidget()
    column = QVBoxLayout(host)
    sections = {}
    for title in titles:
        section = CollapsibleSection(title)
        section.content_form().addRow(QLabel("a line\n" * 20))
        sections[title] = section
        column.addWidget(section)
    scroll.setWidget(host)
    qtbot.addWidget(scroll)
    return scroll, sections


def _wait(condition) -> None:
    wait_until(condition, pump=QApplication.processEvents)


def _entries(toc: MiniToc) -> list[str]:
    return [entry.display_text(10_000) for entry in toc.findChildren(ElidingButton)]


def test_the_mini_toc_lists_its_panes_sections_under_the_panes_name(qtbot):
    scroll, _sections = _scroll_holding(qtbot, "Prompts & seed", "Size")
    toc = MiniToc("Generation settings", scroll)
    qtbot.addWidget(toc)

    assert toc.heading() == "Generation settings"
    assert _entries(toc) == ["Prompts & seed", "Size"]


def _press(toc: MiniToc, title: str) -> None:
    next(b for b in toc.findChildren(ElidingButton) if b.display_text(10_000) == title).click()


def test_pressing_an_entry_opens_its_section_and_folds_every_other(qtbot):
    scroll, sections = _scroll_holding(qtbot, "Prompts & seed", "Calibration", "Size")
    sections["Calibration"].set_collapsed(True)
    toc = MiniToc("Generation settings", scroll)
    qtbot.addWidget(toc)
    folded = []
    for title, section in sections.items():
        section.toggled.connect(lambda title=title: folded.append(title))

    _press(toc, "Calibration")

    assert {t: s.is_collapsed() for t, s in sections.items()} == {
        "Prompts & seed": True, "Calibration": False, "Size": True}
    assert sorted(folded) == ["Calibration", "Prompts & seed", "Size"]


def test_pressing_an_entry_scrolls_its_section_to_the_top_of_the_pane(qtbot):
    scroll, sections = _scroll_holding(qtbot, "Prompts & seed", "Calibration", "Size", "Video")
    scroll.resize(300, 200)
    scroll.show()
    toc = MiniToc("Generation settings", scroll)
    qtbot.addWidget(toc)

    _press(toc, "Size")

    size = sections["Size"]
    _wait(lambda: scroll.verticalScrollBar().value() == size.y() > 0)


def test_the_entries_follow_the_sections_shown_in_the_order_they_sit(qtbot):
    scroll, sections = _scroll_holding(qtbot, "Prompts & seed", "Size")
    scroll.show()
    toc = MiniToc("Generation settings", scroll)
    qtbot.addWidget(toc)
    request = CollapsibleSection("Request")
    scroll.widget().layout().insertWidget(1, request)
    sections["Size"].hide()

    _wait(lambda: _entries(toc) == ["Prompts & seed", "Request"])


def test_mini_tocs_lined_up_are_all_as_wide_as_the_widest(qtbot):
    narrow_scroll, _ = _scroll_holding(qtbot, "Links")
    wide_scroll, _ = _scroll_holding(qtbot, "Workflow, models & LoRAs")
    narrow, wide = MiniToc("Item info", narrow_scroll), MiniToc("Generation settings", wide_scroll)
    for toc in (narrow, wide):
        qtbot.addWidget(toc)
    alone = wide.sizeHint().width()

    line_up((narrow, wide))

    assert narrow.sizeHint().width() == wide.sizeHint().width() == alone


def _pane_holding(qtbot, heading: str, *titles: str):
    scroll, _sections = _scroll_holding(qtbot, *titles)
    for section in _sections.values():
        section.content_form().addRow(QLabel("x" * 60))
    pane = beside_its_mini_toc(heading, scroll)
    qtbot.addWidget(pane)
    return pane, pane.findChild(MiniToc), scroll


def _room_for_both(toc, scroll) -> int:
    return toc.sizeHint().width() + scroll_floor(scroll)


def test_the_mini_toc_hides_while_its_pane_is_too_narrow_for_it_and_the_settings(qtbot):
    pane, toc, scroll = _pane_holding(qtbot, "Generation settings", "Workflow, models & LoRAs")
    pane.show()
    room = _room_for_both(toc, scroll)

    pane.resize(room - 1, 400)
    _wait(toc.isHidden)
    pane.resize(room + 20, 400)
    _wait(lambda: not toc.isHidden())


def test_mini_tocs_lined_up_hide_together(qtbot):
    wide_pane, wide, wide_scroll = _pane_holding(qtbot, "Generation settings", "Size")
    narrow_pane, narrow, _ = _pane_holding(qtbot, "Item info", "Workflow, models & LoRAs")
    line_up((wide, narrow))
    for pane in (wide_pane, narrow_pane):
        pane.show()
    wide_pane.resize(_room_for_both(wide, wide_scroll) + 20, 400)
    narrow_pane.resize(_room_for_both(wide, wide_scroll) - 1, 400)

    _wait(lambda: wide.isHidden() and narrow.isHidden())
