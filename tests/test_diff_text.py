from __future__ import annotations

from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import GREEN, RED

from origenerator.gui import diff_text
from origenerator.prompt_diff import ADDED, REMOVED, SAME


def test_a_field_with_no_diff_reads_as_itself(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("a woman, freckles")

    assert diff_text.live_text(edit) == "a woman, freckles"


def test_what_arrived_is_lit_on_the_family_s_green():
    assert diff_text.added_format().background().color() == GREEN


def test_what_went_is_struck_through_in_red_so_it_reads_as_no_longer_asked_for():
    fmt = diff_text.removed_format()

    assert fmt.fontStrikeOut()
    assert fmt.foreground().color() == RED


def _edit_showing_a_diff(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("a cat dog on a couch")
    diff_text.hold_value(edit, "a dog on a couch")
    return edit


def test_while_a_diff_is_up_the_field_is_worth_the_prompt_that_would_generate(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    assert edit.toPlainText() == "a cat dog on a couch"
    assert diff_text.live_text(edit) == "a dog on a couch"


def test_holding_nothing_returns_the_field_to_its_own_text(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    diff_text.hold_value(edit, None)

    assert diff_text.live_text(edit) == "a cat dog on a couch"


def test_clearing_a_diff_collapses_the_document_to_the_prompt_it_stands_for(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    diff_text.clear_diff(edit)

    assert edit.toPlainText() == "a dog on a couch"
    assert diff_text.live_text(edit) == "a dog on a couch"


def test_forgetting_a_diff_leaves_the_text_as_it_is(qtbot):
    edit = _edit_showing_a_diff(qtbot)

    diff_text.forget(edit)

    assert edit.toPlainText() == "a cat dog on a couch"
    assert diff_text.live_text(edit) == "a cat dog on a couch"


def test_each_kind_of_change_has_the_one_format_the_fields_and_the_tooltip_share():
    assert diff_text.format_for(ADDED).background().color() == GREEN
    assert diff_text.format_for(REMOVED).fontStrikeOut()
    assert diff_text.format_for(SAME) == diff_text.format_for("anything else")


def _struck_and_lit(html: str) -> tuple[str, str]:
    document = QTextDocument()
    document.setHtml(html)
    cursor = QTextCursor(document)
    struck = lit = ""
    for position in range(len(document.toPlainText())):
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        if cursor.charFormat().fontStrikeOut():
            struck += cursor.selectedText()
        elif cursor.charFormat().background().color() == GREEN:
            lit += cursor.selectedText()
    return struck.strip(), lit.strip()


def request_change_html(*prompts, settings=()) -> str:
    document = QTextDocument()
    diff_text.write_request_change(QTextCursor(document), *prompts, settings=settings)
    return document.toHtml()


def test_a_requests_change_renders_both_prompts_whole_with_what_went_struck_and_what_came_lit():
    html = request_change_html("a woman, a hat, beach", "blurry", "a woman, beach",
                               "blurry, hat")

    document = QTextDocument()
    document.setHtml(html)
    text = document.toPlainText()
    assert text.index("Positive Prompt") < text.index("a woman") < text.index("Negative Prompt")
    struck, lit = _struck_and_lit(html)
    assert "a hat" in struck
    assert "hat" in lit


def test_a_change_to_the_positive_prompt_alone_renders_only_that_prompt():
    html = request_change_html("a woman", "", "two women", "")

    document = QTextDocument()
    document.setHtml(html)
    assert "Negative Prompt" not in document.toPlainText()


def test_a_requests_setting_changes_show_under_the_prompts_label_before_and_after():
    html = request_change_html("a cat", "", "a cat", "",
                               settings=[("Width", "1024", "1216")])

    document = QTextDocument()
    document.setHtml(html)
    text = document.toPlainText()
    assert text.index("Positive Prompt") < text.index("Settings") < text.index("Width")
    struck, lit = _struck_and_lit(html)
    assert struck == "1024"
    assert lit == "1216"


def test_each_of_a_requests_setting_changes_has_a_line_of_its_own():
    document = QTextDocument()
    document.setHtml(request_change_html(
        "a cat", "", "a cat", "", settings=[("Width", "1024", "1216"), ("Height", "1024", "832")]))

    assert "Width: 1024 1216" in document.toPlainText().split("\n")
    assert "Height: 1024 832" in document.toPlainText().split("\n")
