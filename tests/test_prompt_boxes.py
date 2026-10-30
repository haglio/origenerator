from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt
from shared_ui.colors import AMBER, RED, TEXT_MUTED

from origenerator.gui.param_form import ParamForm
from origenerator.gui.prompt_boxes import Countdown, PromptBoxes
from origenerator.prompt_tokens import CUT_OFF, READ_IN_PIECES, READ_WHOLE
from origenerator.workflows import WORKFLOW_REGISTRY
from tests.text_readers import word_reading


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


@pytest.fixture
def prompt(qtbot):
    widget = PromptBoxes("positive_prompt")
    qtbot.addWidget(widget)
    widget.set_reading(word_reading(75, READ_IN_PIECES))
    return widget


def test_a_box_with_more_than_15_tokens_to_spare_shows_no_countdown(prompt):
    prompt.set_value(_words(59))

    assert _shown(prompt) == []


def test_a_box_counts_down_its_last_15_tokens_in_amber(prompt):
    prompt.set_value(_words(60))
    assert _shown(prompt) == [("15 left", AMBER.name())]

    prompt.set_value(_words(75))
    assert _shown(prompt) == [("0 left", AMBER.name())]


def test_the_countdown_follows_the_typing(prompt):
    prompt.set_value(_words(70))

    prompt.boxes()[0].setPlainText(_words(50))

    assert _shown(prompt) == []


def test_a_prompt_read_whole_counts_down_to_what_its_reader_reads_well_and_on_below_zero_in_red(
        prompt):
    prompt.set_reading(word_reading(511, READ_WHOLE))

    prompt.set_value(_words(500))
    assert _shown(prompt) == [("11 left", AMBER.name())]

    prompt.set_value(_words(514))
    assert _shown(prompt) == [("-3 left", RED.name())]


def test_a_sound_prompt_counts_down_to_where_its_reader_stops_and_grays_past_it(qtbot):
    sound = PromptBoxes("audio_prompt")
    qtbot.addWidget(sound)
    sound.set_reading(word_reading(76, CUT_OFF))

    sound.set_value(_words(79))

    assert _shown(sound) == [("-3 left", RED.name())]
    (box,) = sound.boxes()
    layout = box.document().firstBlock().layout()
    assert [(span.start, span.format.foreground().color().name()) for span in layout.formats()] == [
        (len(_words(76)) + 1, TEXT_MUTED.name())]


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


def test_each_scenes_prompts_count_down_too(qtbot):
    form = ParamForm(WORKFLOW_REGISTRY["wan22_i2v"].param_definitions())
    qtbot.addWidget(form)
    form.show_readings({"positive_prompt": word_reading(511, READ_WHOLE),
                        "negative_prompt": word_reading(511, READ_WHOLE)})
    editor = form._scenes

    editor.fields("positive_prompt")[0].setPlainText(_words(500))

    assert _shown(editor) == [("11 left", AMBER.name())]
