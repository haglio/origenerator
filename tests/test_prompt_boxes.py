from __future__ import annotations

from functools import partial

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QTextCursor
from PyQt6.QtWidgets import QApplication
from shared_ui.colors import AMBER, BG_PRIMARY, RED, TEXT_MUTED
from shared_ui.fonts import FONT_UI, SIZE_BODY
from shared_ui.spacing import GAP_SMALL

from origenerator import config
from origenerator.box_breaks import BOX_BREAK
from origenerator.gui import diff_text
from origenerator.gui.param_form import ParamForm
from origenerator.gui.param_help import MORE_THAN_ONE_BOX
from origenerator.gui.prompt_boxes import Countdown, PromptBoxes, set_in_use
from origenerator.gui.prompt_field import PromptField, PromptHeights
from origenerator.prompt_tokens import CUT_OFF, READ_IN_PIECES, READ_WHOLE, prompt_reading
from origenerator.workflows import WORKFLOW_REGISTRY
from origenerator.workflows.base import ParamDef, story_of
from tests.text_readers import clip_reader, word_reading


def _prompt_fields(key: str, heights: PromptHeights | None = None) -> PromptBoxes:
    return PromptBoxes(partial(PromptField, key, heights=heights))


def _words(count: int) -> str:
    return " ".join(["cat"] * count)


def _shown(widget) -> list[tuple[str, str]]:
    shown = []
    for countdown in widget.findChildren(Countdown):
        if not countdown.isHidden():
            countdown.ensurePolished()
            color = countdown.palette().color(countdown.foregroundRole())
            shown.append((countdown.text(), color.name()))
    return shown


def _marks(field) -> list[tuple[str, str]]:
    cursor = QTextCursor(field.document())
    runs = []
    for position in range(len(field.toPlainText())):
        cursor.setPosition(position)
        cursor.setPosition(position + 1, QTextCursor.MoveMode.KeepAnchor)
        fmt = cursor.charFormat()
        mark = ("struck" if fmt.fontStrikeOut()
                else "lit" if fmt.background().style() != Qt.BrushStyle.NoBrush else "plain")
        if runs and runs[-1][1] == mark:
            runs[-1] = (runs[-1][0] + cursor.selectedText(), mark)
        else:
            runs.append((cursor.selectedText(), mark))
    return runs


@pytest.fixture
def prompt(qtbot):
    widget = _prompt_fields("positive_prompt")
    qtbot.addWidget(widget)
    widget.set_reading(word_reading(75, READ_IN_PIECES))
    return widget


def test_a_box_with_more_than_15_tokens_to_spare_shows_no_countdown(prompt):
    prompt.set_value(_words(59))

    assert _shown(prompt) == []


def test_a_box_counts_down_its_last_15_tokens_in_yellow(prompt):
    prompt.set_value(_words(60))
    assert _shown(prompt) == [("15 left", AMBER.name())]

    prompt.set_value(_words(75))
    assert _shown(prompt) == [("0 left", AMBER.name())]


def test_the_countdown_follows_the_typing(prompt):
    prompt.set_value(_words(70))

    prompt.boxes()[0].setPlainText(_words(50))

    assert _shown(prompt) == []


def test_a_prompt_read_whole_counts_down_to_what_its_reader_reads_well_then_how_far_over_in_red(
        prompt):
    prompt.set_reading(word_reading(511, READ_WHOLE))

    prompt.set_value(_words(500))
    assert _shown(prompt) == [("11 left", AMBER.name())]

    prompt.set_value(_words(514))
    assert _shown(prompt) == [("3 over", RED.name())]


def _past_the_limit(box) -> list[tuple[str, str, str]]:
    text = box.toPlainText()
    return [(text[span.start:span.start + span.length], span.format.background().color().name(),
             span.format.foreground().color().name())
            for span in box.document().firstBlock().layout().formats()]


def test_the_words_past_what_a_prompt_read_whole_reads_well_are_highlighted_in_yellow(qtbot):
    prompt = _prompt_fields("positive_prompt")
    qtbot.addWidget(prompt)
    prompt.set_reading(word_reading(3, READ_WHOLE))

    prompt.set_value("a b c d e")

    (box,) = prompt.boxes()
    assert _past_the_limit(box) == [("d e", AMBER.name(), BG_PRIMARY.name())]


def test_on_a_tab_showing_an_item_only_the_prompts_own_words_past_the_limit_are_yellow(qtbot):
    prompt = _prompt_fields("positive_prompt")
    qtbot.addWidget(prompt)
    prompt.set_reading(word_reading(3, READ_WHOLE))
    prompt.set_value("a b c d")

    prompt.track("a x b c d y")

    (box,) = prompt.boxes()
    assert box.toPlainText() == "a x b c d y"
    assert [text for text, _ground, _ink in _past_the_limit(box)] == ["d"]


def test_a_sound_prompt_counts_down_to_where_its_reader_stops_and_grays_past_it_on_yellow(qtbot):
    sound = _prompt_fields("audio_prompt")
    qtbot.addWidget(sound)
    sound.set_reading(word_reading(76, CUT_OFF))

    sound.set_value(_words(79))

    assert _shown(sound) == [("3 over", RED.name())]
    (box,) = sound.boxes()
    assert _past_the_limit(box) == [(_words(3), AMBER.name(), TEXT_MUTED.name())]


def test_a_prompt_whose_reader_is_not_installed_counts_nothing(prompt):
    prompt.set_value(_words(74))
    prompt.set_reading(None)

    assert _shown(prompt) == []


def test_the_countdown_sits_under_its_box_at_its_right_edge(prompt):
    prompt.set_value(_words(70))
    prompt.resize(400, 300)
    prompt.layout().activate()

    (box,), (countdown,) = prompt.boxes(), prompt.findChildren(Countdown)
    assert countdown.geometry().top() > box.geometry().bottom()
    assert countdown.geometry().right() == box.geometry().right()
    assert countdown.alignment() & Qt.AlignmentFlag.AlignRight


def test_the_countdown_is_lettered_at_shared_uis_body_size(prompt):
    prompt.set_value(_words(70))

    (countdown,) = prompt.findChildren(Countdown)
    assert (countdown.font().family(), countdown.font().pointSize()) == (FONT_UI, SIZE_BODY)


def test_each_scene_counts_down_its_own_prompts(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)
    form.show_readings({"positive_prompt": word_reading(511, READ_WHOLE),
                        "negative_prompt": word_reading(511, READ_WHOLE)})

    form.set_values({"positive_prompt": story_of([_words(5), _words(500)])})

    assert [_shown(scene) for scene in form._scenes._scenes] == [
        [], [("11 left", AMBER.name())]]


@pytest.fixture
def typed_into(qtbot):
    widget = _prompt_fields("positive_prompt")
    qtbot.addWidget(widget)
    widget.set_reading(word_reading(3, READ_IN_PIECES))
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


def _texts(widget) -> list[str]:
    return [diff_text.live_text(box) for box in widget.boxes()]


def _settled(qtbot, widget) -> None:
    qtbot.waitUntil(lambda: not widget._reflow.isActive(), timeout=5000)


def _type(qtbot, widget, box: int, at: int, keys: str) -> None:
    field = widget.boxes()[box]
    field.setFocus()
    cursor = field.textCursor()
    cursor.setPosition(at)
    field.setTextCursor(cursor)
    qtbot.keyClicks(field, keys)
    _settled(qtbot, widget)


def _caret(widget) -> tuple[int, int]:
    (box,) = [index for index, field in enumerate(widget.boxes()) if field.hasFocus()]
    return box, widget.boxes()[box].textCursor().position()


def test_a_word_typed_past_a_boxs_end_moves_whole_into_a_new_box_and_the_caret_goes_with_it(
        qtbot, typed_into):
    typed_into.set_value("a b c")

    _type(qtbot, typed_into, 0, 5, " d")
    assert (_texts(typed_into), _caret(typed_into)) == (["a b c", "d"], (1, 1))

    qtbot.keyClicks(typed_into.boxes()[1], "d")
    assert _texts(typed_into) == ["a b c", "dd"]


def test_words_typed_in_cascade_on_through_the_boxes(qtbot, typed_into):
    typed_into.set_value(f"a b c{BOX_BREAK}d e f")

    _type(qtbot, typed_into, 0, 0, "x ")

    assert _texts(typed_into) == ["x a b", "c d e", "f"]
    assert typed_into.value() == f"x a b{BOX_BREAK}c d e{BOX_BREAK}f"


def test_with_room_whole_words_flow_back_up_and_a_box_left_empty_disappears(qtbot, typed_into):
    typed_into.set_value(f"a b c{BOX_BREAK}d")

    _type(qtbot, typed_into, 0, 5, "\b\b")

    assert _texts(typed_into) == ["a b d"]


def test_one_box_always_stays(qtbot, typed_into):
    typed_into.set_value("a b c")
    field = typed_into.boxes()[0]
    field.setFocus()
    field.selectAll()

    qtbot.keyClick(field, Qt.Key.Key_Delete)
    _settled(qtbot, typed_into)

    assert _texts(typed_into) == [""]


def test_a_box_emptied_by_hand_disappears_and_the_caret_ends_the_box_before(qtbot, typed_into):
    typed_into.set_value(f"a b c{BOX_BREAK}d{BOX_BREAK}e f g")
    field = typed_into.boxes()[1]
    field.setFocus()
    field.selectAll()

    qtbot.keyClick(field, Qt.Key.Key_Delete)
    _settled(qtbot, typed_into)

    assert (_texts(typed_into), _caret(typed_into)) == (["a b c", "e f g"], (0, 5))


def test_dictation_into_a_box_flows_like_typing(qtbot, typed_into):
    typed_into.set_value("a b")
    field = typed_into.boxes()[0]
    field.setFocus()
    field.moveCursor(QTextCursor.MoveOperation.End)

    field.insertPlainText(" c d e f")
    _settled(qtbot, typed_into)

    assert _texts(typed_into) == ["a b c", "d e f"]


def test_undo_takes_back_a_burst_of_typing_over_the_whole_column(qtbot, typed_into):
    typed_into.set_value("a b c")
    _type(qtbot, typed_into, 0, 5, " d e")
    assert _texts(typed_into) == ["a b c", "d e"]

    qtbot.keyClick(typed_into.boxes()[1], Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert _texts(typed_into) == ["a b c"]

    qtbot.keyClick(typed_into.boxes()[0], Qt.Key.Key_Y, Qt.KeyboardModifier.ControlModifier)
    assert _texts(typed_into) == ["a b c", "d e"]


def test_a_prompt_pasted_with_its_box_breaks_keeps_its_boxes(qtbot, typed_into):
    field = typed_into.boxes()[0]
    field.setFocus()

    field.insertPlainText(f"a b c{BOX_BREAK}d")
    _settled(qtbot, typed_into)

    assert _texts(typed_into) == ["a b c", "d"]


def test_a_prompt_read_whole_never_gets_a_second_box(qtbot, typed_into):
    typed_into.set_reading(word_reading(3, READ_WHOLE))

    _type(qtbot, typed_into, 0, 0, "a b c d")

    assert _texts(typed_into) == ["a b c d"]
    assert _shown(typed_into) == [("1 over", RED.name())]


def test_a_boxed_prompt_carried_to_a_prompt_read_whole_is_read_whole_each_break_a_space(
        qtbot, typed_into):
    typed_into.set_reading(word_reading(3, READ_WHOLE))

    typed_into.set_value(f"a b{BOX_BREAK}c")
    assert (_texts(typed_into), typed_into.value()) == (["a b c"], "a b c")

    _type(qtbot, typed_into, 0, 5, " d")
    assert typed_into.value() == "a b c d"


def test_marks_against_a_tabs_item_read_the_boxes_as_one_prompt(qtbot, typed_into):
    typed_into.set_value(f"a b c{BOX_BREAK}d")
    typed_into.track("a b c d")
    assert [_marks(box) for box in typed_into.boxes()] == [[("a b c", "plain")], [("d", "plain")]]

    _type(qtbot, typed_into, 0, 0, "x ")

    assert _texts(typed_into) == ["x a b", "c d"]
    assert [_marks(box) for box in typed_into.boxes()] == [
        [("x ", "lit"), ("a b", "plain")], [("c d", "plain")]]


def test_a_word_taken_out_is_struck_through_in_its_box(qtbot, typed_into):
    typed_into.set_value("a b c")
    typed_into.track("a b c")

    _type(qtbot, typed_into, 0, 3, "\b\b")
    qtbot.waitUntil(lambda: ("b ", "struck") in _marks(typed_into.boxes()[0]), timeout=5000)

    assert typed_into.value() == "a c"


def test_untracking_takes_every_boxs_marks_off(qtbot, typed_into):
    typed_into.set_value(f"a b c{BOX_BREAK}d")
    typed_into.track("a b c e")

    typed_into.untrack()

    assert [_marks(box) for box in typed_into.boxes()] == [[("a b c", "plain")], [("d", "plain")]]


def test_every_box_shares_the_prompts_dragged_height_a_small_gap_apart(qtbot):
    heights = PromptHeights()
    heights.set_height("positive_prompt", 180)
    widget = _prompt_fields("positive_prompt", heights)
    qtbot.addWidget(widget)
    widget.set_value(f"a{BOX_BREAK}b")
    widget.resize(400, 600)
    widget.layout().activate()

    first, second = widget.boxes()
    assert first.height() == second.height() == 180
    assert second.geometry().top() - first.geometry().bottom() - 1 == GAP_SMALL


def _form_with_a_prompt(qtbot) -> ParamForm:
    form = ParamForm([ParamDef("positive_prompt", "Positive Prompt", "str", "", multiline=True)])
    qtbot.addWidget(form)
    form.show_readings({"positive_prompt": word_reading(3, READ_IN_PIECES)})
    return form


def test_find_searches_every_box_and_hears_when_one_comes_or_goes(qtbot):
    form = _form_with_a_prompt(qtbot)

    with qtbot.waitSignal(form.text_fields_changed):
        form.set_values({"positive_prompt": f"a b c{BOX_BREAK}d"})

    assert form.text_fields() == form._widgets["positive_prompt"].boxes()
    assert len(form.text_fields()) == 2


def test_the_copy_button_copies_plain_text_that_pastes_back_into_boxes_of_whole_words(qtbot):
    QApplication.clipboard().clear()
    form = _form_with_a_prompt(qtbot)
    form.set_values({"positive_prompt": f"a b c{BOX_BREAK}d"})

    form._copy_buttons["positive_prompt"].click()
    assert QApplication.clipboard().text() == "a b c d"

    pasted_into = _form_with_a_prompt(qtbot)
    pasted_into._widgets["positive_prompt"].boxes()[0].paste()
    qtbot.waitUntil(lambda: pasted_into.get_values()["positive_prompt"] == f"a b c{BOX_BREAK}d",
                    timeout=5000)


def test_a_prompt_not_in_use_hides_its_countdown_and_shows_it_again_once_used(qtbot):
    form = _form_with_a_prompt(qtbot)
    prompt = form._widgets["positive_prompt"]
    form.set_values({"positive_prompt": "a b"})

    set_in_use(prompt, form._labels["positive_prompt"], "not used", "")
    assert _shown(prompt) == []

    set_in_use(prompt, form._labels["positive_prompt"], None, "")
    assert _shown(prompt) == [("1 left", AMBER.name())]


def test_a_prompt_not_in_use_hides_its_yellow_and_shows_it_again_once_used(qtbot):
    prompt = _prompt_fields("positive_prompt")
    qtbot.addWidget(prompt)
    prompt.set_reading(word_reading(3, READ_WHOLE))
    prompt.set_value("a b c d")
    (box,) = prompt.boxes()

    prompt.set_in_use(False, "not used")
    assert _past_the_limit(box) == []

    prompt.set_in_use(True, "")
    assert _past_the_limit(box) == [("d", AMBER.name(), BG_PRIMARY.name())]


def test_a_scene_that_speaks_hides_its_prompts_countdowns(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)
    form.show_readings({"positive_prompt": word_reading(511, READ_WHOLE),
                        "negative_prompt": word_reading(511, READ_WHOLE)})
    form.set_values({"positive_prompt": _words(500)})

    form._scenes.fields("scene_lines")[0].setPlainText("hello")

    assert _shown(form._scenes) == []


def test_a_prompt_not_in_use_grays_every_box_and_every_box_it_gains(qtbot):
    form = _form_with_a_prompt(qtbot)
    prompt = form._widgets["positive_prompt"]
    set_in_use(prompt, form._labels["positive_prompt"], "not used", "")

    form.set_values({"positive_prompt": f"a b c{BOX_BREAK}d"})

    assert [(box.property("inert"), box.isReadOnly(), box.toolTip())
            for box in prompt.boxes()] == [(True, True, "not used")] * 2


def test_a_prompt_of_more_than_one_box_says_in_every_box_what_a_second_box_means(qtbot):
    form = _form_with_a_prompt(qtbot)
    prompt = form._widgets["positive_prompt"]
    set_in_use(prompt, form._labels["positive_prompt"], None, "help")

    form.set_values({"positive_prompt": f"a b c{BOX_BREAK}d"})
    assert [box.toolTip() for box in prompt.boxes()] == [f"help\n\n{MORE_THAN_ONE_BOX}"] * 2

    form.set_values({"positive_prompt": "a b"})
    assert [box.toolTip() for box in prompt.boxes()] == ["help"]


@pytest.fixture
def made_before_the_boxes(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path / "ComfyUI")
    clip_reader(tmp_path / "ComfyUI")
    widget = _prompt_fields("positive_prompt")
    qtbot.addWidget(widget)
    widget.set_reading(prompt_reading("sdxl_t2i", {}, "positive_prompt"))
    with qtbot.waitExposed(widget):
        widget.show()
    return widget


_CUT_IN_HALF = f"{_words(74)} dog"


def test_a_prompt_made_before_the_boxes_opens_cut_where_sdxl_cut_it(made_before_the_boxes):
    made_before_the_boxes.set_value(_CUT_IN_HALF)

    assert _texts(made_before_the_boxes) == [f"{_words(74)} d", "og"]
    assert made_before_the_boxes.value() == _CUT_IN_HALF
    assert _shown(made_before_the_boxes) == [("0 left", AMBER.name())]


def test_a_prompt_made_before_the_boxes_is_no_change_to_itself(made_before_the_boxes):
    made_before_the_boxes.set_value(_CUT_IN_HALF)

    made_before_the_boxes.track(_CUT_IN_HALF)

    assert [_marks(box) for box in made_before_the_boxes.boxes()] == [
        [(f"{_words(74)} d", "plain")], [("og", "plain")]]


def test_the_first_edit_stores_each_box_as_shown_and_flows_from_the_box_edited_on(
        qtbot, made_before_the_boxes):
    made_before_the_boxes.set_value(_CUT_IN_HALF)

    _type(qtbot, made_before_the_boxes, 1, 2, " cat")

    assert _texts(made_before_the_boxes) == [f"{_words(74)} d", "og cat"]
    assert made_before_the_boxes.value() == f"{_words(74)} d{BOX_BREAK}og cat"


def test_undoing_the_first_edit_reads_back_as_it_was_stored(qtbot, made_before_the_boxes):
    made_before_the_boxes.set_value(_CUT_IN_HALF)
    _type(qtbot, made_before_the_boxes, 1, 2, " cat")

    qtbot.keyClick(made_before_the_boxes.boxes()[1], Qt.Key.Key_Z,
                   Qt.KeyboardModifier.ControlModifier)

    assert made_before_the_boxes.value() == _CUT_IN_HALF


def test_a_prompt_written_for_him_flows_into_boxes_of_whole_words(qtbot, typed_into):
    typed_into.set_value("a b")

    typed_into.edit("x y a b c")

    assert _texts(typed_into) == ["x y a", "b c"]
    assert typed_into.value() == f"x y a{BOX_BREAK}b c"


def test_a_prompt_written_for_him_is_one_step_of_undo(qtbot, typed_into):
    typed_into.set_value("a b")
    typed_into.edit("x y a b c")

    qtbot.keyClick(typed_into.boxes()[0], Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert typed_into.value() == "a b"


def test_a_prompt_written_for_him_into_a_prompt_read_whole_stays_one_box(typed_into):
    typed_into.set_reading(word_reading(3, READ_WHOLE))

    typed_into.edit("x y a b c")

    assert _texts(typed_into) == ["x y a b c"]
