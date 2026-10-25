"""The window for settling an animation's settings.

Acts, states and prompts are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest
from PIL import Image
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMovie
from PyQt6.QtWidgets import (
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStyle,
    QStyleOptionButton,
)

from origenerator.act_settings import VIDEO
from origenerator.animation_check_session import AnimationCheckSession
from origenerator.gui.animation_check_window import (
    ACCEPT,
    BACK,
    BLANK,
    COUNTED,
    FORWARD,
    FROM_THE_ACTS_OWN,
    HEADING,
    IMAGE,
    NEGATIVE,
    NO_SAMPLE,
    POSITIVE,
    REJECT,
    SAID,
    SAMPLE,
    SUBMIT,
    AnimationCheckWindow,
)
from origenerator.gui.stylesheet import COMMITS, build_stylesheet

_ORDER = [(VIDEO, "alpha", "state one"), (VIDEO, "beta", "state two")]


class _Store:
    def __init__(self):
        self.accepted = {}

    def remember(self, lane, act, state, *, workflow, params):
        self.accepted[(lane, act, state)] = (workflow, dict(params))

    def accepted_paths(self):
        return set(self.accepted)

    def assigned(self, lane, act, state):
        held = self.accepted.get((lane, act, state))
        return None if held is None else {"workflow": held[0], "params": held[1]}


def _clip(prompt_id="clip", positive="a scene", negative="flaws"):
    return {
        "prompt_id": prompt_id, "workflow_name": "wan22_i2v",
        "positive_prompt": positive, "negative_prompt": negative,
        "params_json": json.dumps({"steps": 8}),
    }


def middle(widget) -> int:
    """Where a widget's vertical center sits, so a row can be told from a column."""
    return widget.y() + widget.height() // 2


def _press(made, name) -> QPushButton:
    return made.findChild(QPushButton, name)


def _box(made, name) -> QPlainTextEdit:
    return made.findChild(QPlainTextEdit, name)


def _said(made, name) -> str:
    return made.findChild(QLabel, name).text()


@pytest.fixture
def window(qtbot, tmp_path):
    submitted = []

    def build(samples=None, store=None, look=None, pinned=None):
        store = store or _Store()
        session = AnimationCheckSession(_ORDER, samples or {}, store, pinned=pinned)
        made = AnimationCheckWindow(
            session, look or (lambda row: (None, None)),
            lambda row, positive, negative: submitted.append(
                (row["prompt_id"], positive, negative)) or "Queued it.")
        qtbot.addWidget(made)
        return made, store, submitted

    return build


def test_the_heading_names_the_lane_the_act_and_the_state_it_starts_from(window):
    made, _store, _sent = window({(VIDEO, "alpha", "state one"): [_clip()]})

    assert "alpha" in _said(made, HEADING)
    assert "state one" in _said(made, HEADING)
    assert _said(made, COUNTED).startswith("1 of 2")


def test_the_samples_prompts_are_what_the_boxes_open_on(window):
    made, _store, _sent = window({(VIDEO, "alpha", "state one"):
                                  [_clip(positive="a scene", negative="flaws")]})

    assert _box(made, POSITIVE).toPlainText() == "a scene"
    assert _box(made, NEGATIVE).toPlainText() == "flaws"


def test_an_animation_nothing_was_ever_made_for_says_so(window):
    made, _store, _sent = window({})

    assert NO_SAMPLE in [label.text() for label in made.findChildren(QLabel)]


def test_accepting_takes_the_prompts_as_they_now_read(window):
    made, store, _sent = window({(VIDEO, "alpha", "state one"): [_clip()]})
    _box(made, POSITIVE).setPlainText("a better scene")

    _press(made, ACCEPT).click()

    workflow, params = store.accepted[(VIDEO, "alpha", "state one")]
    assert workflow == "wan22_i2v"
    assert params["positive_prompt"] == "a better scene"
    assert params["steps"] == 8
    assert _said(made, HEADING).startswith("Kino · beta")


def test_making_one_with_the_edited_prompts_leaves_the_animation_where_it_is(window):
    made, _store, sent = window({(VIDEO, "alpha", "state one"): [_clip("c1")]})
    _box(made, POSITIVE).setPlainText("a different scene")

    _press(made, SUBMIT).click()

    assert sent == [("c1", "a different scene", "flaws")]
    assert _said(made, SAID) == "Queued it."
    assert _said(made, COUNTED).startswith("1 of 2")


def test_making_one_where_there_is_no_example_cannot_be_asked_for(window):
    made, _store, sent = window({})

    assert not _press(made, SUBMIT).isEnabled()
    assert sent == []


def test_rejecting_an_example_brings_up_the_next_one(window):
    made, _store, _sent = window({(VIDEO, "alpha", "state one"): [
        _clip("c1", positive="the first"), _clip("c2", positive="the second")]})

    _press(made, REJECT).click()

    assert _box(made, POSITIVE).toPlainText() == "the second"
    assert _said(made, COUNTED).startswith("1 of 2")


def test_the_arrows_step_through_the_animations(window):
    made, _store, _sent = window({})

    _press(made, FORWARD).click()
    assert _said(made, HEADING).startswith("Kino · beta")

    _press(made, BACK).click()
    assert _said(made, HEADING).startswith("Kino · alpha")


def test_the_count_says_how_many_have_had_their_settings_taken(window):
    store = _Store()
    store.remember(VIDEO, "beta", "state two", workflow="wan22_i2v", params={})
    made, _store, _sent = window({}, store)

    assert _said(made, COUNTED).endswith("1 done")


def test_the_pair_is_shown_at_the_size_the_window_gives_them(window, tmp_path):
    still = tmp_path / "still.png"
    Image.new("RGB", (400, 600), "gray").save(still)
    made, _store, _sent = window({(VIDEO, "alpha", "state one"): [_clip()]},
                                 look=lambda row: (str(still), None))

    shown = made.findChild(QLabel, IMAGE).pixmap()

    assert not shown.isNull()
    assert shown.height() <= 600


# --- what each answer is called, and when it can be pressed -------------------


def test_the_lane_in_the_heading_is_the_word_the_app_shows(window):
    made, _store, _sent = window({_ORDER[0]: [_clip()]})

    assert _said(made, HEADING).startswith("Kino · alpha")


def test_the_count_says_what_it_is_counting(window):
    made, _store, _sent = window({})

    assert "93" not in _said(made, COUNTED)  # the fixture has two, not his 93
    assert "animation" in made.findChild(QLabel, COUNTED).toolTip()


def test_taking_the_settings_is_the_one_blue_answer(window):
    made, _store, _sent = window({_ORDER[0]: [_clip()]})

    assert _press(made, ACCEPT).text() == "Assign these settings"
    assert _press(made, ACCEPT).property(COMMITS) is True


def test_making_another_sample_waits_for_a_prompt_to_be_edited(window):
    made, _store, _sent = window({_ORDER[0]: [_clip()]})

    assert _press(made, SUBMIT).text() == "Generate new sample with current settings"
    assert not _press(made, SUBMIT).isEnabled()

    _box(made, POSITIVE).setPlainText("a different scene")

    assert _press(made, SUBMIT).isEnabled()


def test_the_next_sample_can_only_be_asked_for_while_there_is_one(window):
    made, _store, _sent = window({_ORDER[0]: [_clip("one"), _clip("two")]})

    assert _press(made, REJECT).text() == "View next preexisting sample from library"
    assert _press(made, REJECT).isEnabled()

    _press(made, REJECT).click()

    assert not _press(made, REJECT).isEnabled()


def test_an_animation_with_no_sample_says_so_across_the_whole_width(window):
    """Sharing the row with the sample's half it read as a caption on the
    image, off to the left of the window rather than centered in it."""
    made, _store, _sent = window({})
    made.show()
    made.layout().activate()
    blank = made.findChild(QLabel, BLANK)

    assert blank.text() == NO_SAMPLE
    assert blank.width() > made.width() // 2
    assert blank.alignment() & Qt.AlignmentFlag.AlignHCenter


def test_the_arrows_sit_either_side_of_the_count(window):
    """A plain step through the line, where "Leave for later" used to send one to
    the back of it; he asked for the arrows and for that sending to go."""
    made, _store, _sent = window({})
    made.show()
    made.layout().activate()
    counted = made.findChild(QLabel, COUNTED)
    back, forward = _press(made, BACK), _press(made, FORWARD)

    assert (back.text(), forward.text()) == ("<", ">")
    assert back.x() < counted.x() < forward.x()
    assert {middle(back), middle(counted), middle(forward)} == {middle(counted)}


def _loop(path):
    frames = [Image.new("RGB", (40, 30), "gray") for _ in range(2)]
    frames[0].save(path, save_all=True, append_images=frames[1:], loop=0,
                   duration=80)
    return str(path)


def test_a_step_puts_the_new_sample_in_place_of_the_one_before(window, tmp_path):
    """Each step made a clip of its own and left the one before it on the label,
    running, so his window stacked them up instead of replacing them."""
    made, _store, _sent = window(
        {path: [_clip()] for path in _ORDER},
        look=lambda row: (None, _loop(tmp_path / "loop.webp")))
    made.show()

    _press(made, FORWARD).click()

    shown = made.findChild(QLabel, SAMPLE)
    assert len(shown.findChildren(QMovie)) == 1
    assert shown.movie() is not None


def test_the_arrows_are_wide_enough_to_draw_their_glyph(window):
    """Fixed at one character's width they came up blank: every button in the
    family spends sixteen pixels on padding either side, which left the glyph
    less than nothing and Qt drew none of it."""
    made, _store, _sent = window({})
    made.setStyleSheet(build_stylesheet())
    made.show()
    made.layout().activate()

    for name in (BACK, FORWARD):
        step = _press(made, name)
        option = QStyleOptionButton()
        step.initStyleOption(option)
        room = step.style().subElementRect(
            QStyle.SubElement.SE_PushButtonContents, option, step)
        assert room.width() >= step.fontMetrics().horizontalAdvance(step.text())


def test_an_animation_nobody_kept_a_video_of_starts_from_the_acts_own_prompts(window):
    """His ask: the act's own settings are a starting position where there is
    nothing kept to copy, so the animation can still be answered."""
    made, _store, _sent = window({}, pinned=lambda act, lane: {
        "workflow": "wan22_i2v", "params": {"positive_prompt": "the act's own",
                                            "negative_prompt": "its flaws"}})

    assert _box(made, POSITIVE).toPlainText() == "the act's own"
    assert _box(made, NEGATIVE).toPlainText() == "its flaws"
    assert made.findChild(QLabel, BLANK).text() == FROM_THE_ACTS_OWN


def test_an_animation_with_neither_says_there_is_nothing_to_go_by(window):
    made, _store, _sent = window({})

    assert _box(made, POSITIVE).toPlainText() == ""
    assert made.findChild(QLabel, BLANK).text() == NO_SAMPLE
