from PyQt6.QtWidgets import QPlainTextEdit, QScrollArea, QVBoxLayout, QWidget

from origenerator.gui.collapsible_section import CollapsibleSection
from origenerator.gui.prompt_find import _CURRENT_BG, PromptFind


def _fields(qtbot, *texts):
    """Loose prompt fields holding ``texts``, in the order a form would lay them."""
    host = QWidget()
    box = QVBoxLayout(host)
    made = []
    for text in texts:
        field = QPlainTextEdit()
        field.setPlainText(text)
        box.addWidget(field)
        made.append(field)
    qtbot.addWidget(host)
    return host, made


def _standing_on(*fields):
    """The field carrying the current match's amber -- how the user sees which
    of the results the find is standing on. ``_paint`` re-lays every field's
    highlights on each step, so exactly one of them can carry it."""
    for field in fields:
        for selection in field.extraSelections():
            if selection.format.background().color() == _CURRENT_BG:
                return field
    return None



def test_a_search_counts_every_match_across_the_fields(qtbot):
    _host, (positive, negative) = _fields(qtbot, "a cat and a cat", "no cat")
    find = PromptFind()
    find.set_fields([positive, negative])

    assert find.search("cat") == 3
    assert find.position() == 1
    assert _standing_on(positive, negative) is positive


def test_matching_is_case_insensitive_and_non_overlapping(qtbot):
    _host, (field,) = _fields(qtbot, "Cat CAT cat")
    find = PromptFind()
    find.set_fields([field])

    assert find.search("cat") == 3
    # "aaa" holds one "aa", not two: a match consumes the text it covers, so the
    # highlights can't paint over each other.
    field.setPlainText("aaa")
    assert find.search("aa") == 1


def test_a_search_finds_a_word_past_any_headline_of_the_prompt(qtbot):
    # The whole point: a folder label is a 60-character headline of the prompt, so
    # a word further in is reachable only by searching the field itself.
    tail = "a cat asleep on a windowsill in the late afternoon sun, watching beetles"
    _host, (field,) = _fields(qtbot, tail)
    find = PromptFind()
    find.set_fields([field])

    assert find.search("beetles") == 1


def test_stepping_walks_forward_and_wraps_both_ways(qtbot):
    _host, (positive, negative) = _fields(qtbot, "a cat", "no cat")
    find = PromptFind()
    find.set_fields([positive, negative])
    find.search("cat")

    fields = (positive, negative)
    find.step(1)
    assert (find.position(), _standing_on(*fields)) == (2, negative)
    find.step(1)
    assert (find.position(), _standing_on(*fields)) == (1, positive)  # wrapped on
    find.step(-1)
    assert (find.position(), _standing_on(*fields)) == (2, negative)  # and back


def test_the_cursor_lands_on_the_current_match_without_selecting_it(qtbot):
    # Qt paints a real selection over an extra selection, in whatever color the
    # palette gives it — so selecting the match would hide the highlight that says
    # which match is current. The cursor goes there; the paint does the telling.
    _host, (field,) = _fields(qtbot, "a cat on a mat")
    find = PromptFind()
    find.set_fields([field])

    find.search("mat")

    assert field.textCursor().position() == len("a cat on a ")
    assert field.textCursor().selectedText() == ""


def test_every_match_is_painted_and_the_current_one_differently(qtbot):
    _host, (field,) = _fields(qtbot, "a cat and a cat")
    find = PromptFind()
    find.set_fields([field])

    find.search("cat")

    selections = field.extraSelections()
    assert len(selections) == 2
    first, second = (s.format.background().color() for s in selections)
    assert first != second  # where you're standing reads apart from where you're not


def test_the_current_highlight_moves_with_the_step(qtbot):
    _host, (field,) = _fields(qtbot, "a cat and a cat")
    find = PromptFind()
    find.set_fields([field])
    find.search("cat")
    before = [s.format.background().color().name() for s in field.extraSelections()]

    find.step(1)

    after = [s.format.background().color().name() for s in field.extraSelections()]
    assert after == list(reversed(before))  # the marker moved on; the set didn't change


def test_clearing_leaves_no_paint_behind(qtbot):
    _host, (field,) = _fields(qtbot, "a cat")
    find = PromptFind()
    find.set_fields([field])
    find.search("cat")
    assert field.extraSelections()

    find.clear()

    assert not field.extraSelections()
    assert find.count() == 0 and find.position() == 0


def test_retargeting_drops_the_previous_fields_highlights(qtbot):
    _host, (old, new) = _fields(qtbot, "a cat", "another cat")
    find = PromptFind()
    find.set_fields([old])
    find.search("cat")
    assert old.extraSelections()

    find.set_fields([new])

    assert not old.extraSelections()  # a tab switched away from stops being marked


def test_refreshing_keeps_your_place_while_the_prompt_is_edited(qtbot):
    _host, (field,) = _fields(qtbot, "cat cat cat")
    find = PromptFind()
    find.set_fields([field])
    find.search("cat")
    find.step(1)
    assert find.position() == 2

    field.setPlainText("cat cat cat and cat")
    assert find.refresh() == 4
    assert find.position() == 2  # still where the user was, not snapped to the first


def test_refreshing_past_the_end_clamps_rather_than_losing_the_place(qtbot):
    _host, (field,) = _fields(qtbot, "cat cat cat")
    find = PromptFind()
    find.set_fields([field])
    find.search("cat")
    find.step(1)
    find.step(1)
    assert find.position() == 3

    field.setPlainText("cat")

    assert find.refresh() == 1
    assert find.position() == 1


def test_an_empty_query_matches_nothing(qtbot):
    _host, (field,) = _fields(qtbot, "a cat")
    find = PromptFind()
    find.set_fields([field])

    assert find.search("") == 0
    assert not field.extraSelections()


def test_landing_on_a_match_unfolds_the_section_hiding_it(qtbot):
    # The Foley prompts sit in a section that starts closed, and a match inside a
    # closed section is one the user is told about but can't be shown.
    section = CollapsibleSection("Audio", collapsed=True)
    field = QPlainTextEdit(section.content())
    field.setPlainText("a cat purring")
    qtbot.addWidget(section)
    assert section.is_collapsed()

    find = PromptFind()
    find.set_fields([field])
    find.search("purring")

    assert not section.is_collapsed()


def test_landing_on_a_match_scrolls_the_form_to_its_field(qtbot):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    host = QWidget()
    box = QVBoxLayout(host)
    filler = QPlainTextEdit("\n" * 200)   # push the target far below the fold
    filler.setMinimumHeight(1200)
    box.addWidget(filler)
    target = QPlainTextEdit("a cat")
    box.addWidget(target)
    scroll.setWidget(host)
    scroll.resize(300, 200)
    qtbot.addWidget(scroll)
    scroll.show()
    qtbot.waitExposed(scroll)

    find = PromptFind()
    find.set_fields([target])
    find.search("cat")

    assert scroll.verticalScrollBar().value() > 0  # the match was brought into view
