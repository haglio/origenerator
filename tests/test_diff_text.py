"""diff_text — what a prompt field is worth while it shows a change."""
from __future__ import annotations

from PyQt6.QtGui import QTextCursor, QTextDocument
from PyQt6.QtWidgets import QPlainTextEdit
from shared_ui.colors import GREEN

from origenerator.gui import diff_text
from origenerator.prompt_diff import ADDED, REMOVED, SAME


def test_a_field_with_no_diff_reads_as_itself(qtbot):
    edit = QPlainTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("a woman, freckles")

    assert diff_text.live_text(edit) == "a woman, freckles"


def test_what_arrived_is_lit_on_the_family_s_green():
    assert diff_text.added_format().background().color() == GREEN


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


def test_a_requests_change_renders_both_prompts_whole_with_what_went_struck_and_what_came_lit():
    html = diff_text.request_change_html("a woman, a hat, beach", "blurry", "a woman, beach",
                                         "blurry, hat")

    document = QTextDocument()
    document.setHtml(html)
    text = document.toPlainText()
    assert text.index("Positive Prompt") < text.index("a woman") < text.index("Negative Prompt")
    struck, lit = _struck_and_lit(html)
    assert "a hat" in struck and "hat" in lit


def test_a_change_to_the_positive_prompt_alone_renders_only_that_prompt():
    html = diff_text.request_change_html("a woman", "", "two women", "")

    document = QTextDocument()
    document.setHtml(html)
    assert "Negative Prompt" not in document.toPlainText()


def test_a_requests_setting_changes_show_under_the_prompts_label_before_and_after():
    html = diff_text.request_change_html("a cat", "", "a cat", "",
                                         settings=[("Width", "1024", "1216")])

    document = QTextDocument()
    document.setHtml(html)
    text = document.toPlainText()
    assert text.index("Positive Prompt") < text.index("Settings") < text.index("Width")
    struck, lit = _struck_and_lit(html)
    assert struck == "1024" and lit == "1216"

