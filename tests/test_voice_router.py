from __future__ import annotations

import logging

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget

from origenerator import gallery
from origenerator.action_settings import GENAU, VIDEO
from origenerator.animate_command import AnimateRequest
from origenerator.gallery.collection import LATEST_KEY
from origenerator.gallery.voice_commands import said_in
from origenerator.gui import voice_router as module
from origenerator.gui.gallery_pane_buttons import GROUP_TIP
from origenerator.gui.message import ERROR, INFO, WARNING
from origenerator.gui.starting_rows import StartingRows
from origenerator.gui.voice_router import VoiceRouter, VoiceSources, VoiceSwitches
from origenerator.setter_voice import setter_phrases
from origenerator.voice.app_commands import (
    AppCommand,
    BarSetting,
    phrases_heard_only_outright,
)
from origenerator.voice.commands import (
    CollectionCommand,
    SlideshowControl,
    SurfaceCommand,
    shaped_app_command,
    spoken_phrases,
)
from origenerator.voice.dictation import COMPLETED
from origenerator.voice.slideshow_commands import SlideshowCommand
from tests.marked_words import words

_A_CLIENT = object()


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeListener:
    def __init__(self, **kwargs):
        self.built_with = kwargs
        self.heard = FakeSignal()
        self.error = FakeSignal()
        self.request = FakeSignal()
        self.commands_on = False
        self.closed = False
        self.bare = None
        self.dictated = None
        self.dictated_at = []
        self.on_command = None

    def start_commands(self, handler):
        self.commands_on = True
        self.on_command = handler

    def stop_commands(self):
        self.commands_on = False

    def close(self):
        self.stop_commands()
        self.closed = True

    def bare_command(self, text):
        return self.bare

    def push_dictation(self, text, spoken_at=None):
        self.dictated_at.append(spoken_at)
        return self.dictated


class FakeButton:
    def __init__(self, *, tip="", checked=False, enabled=True, hidden=False):
        self._tip = tip
        self._checked = checked
        self._enabled = enabled
        self._hidden = hidden
        self.set_to = []

    def toolTip(self):
        return self._tip

    def isChecked(self):
        return self._checked

    def isEnabled(self):
        return self._enabled

    def isHidden(self):
        return self._hidden

    def setChecked(self, on):
        self._checked = on
        self.set_to.append(on)


class FakeSlideshow:
    def __init__(self, target="g1", said_over=None):
        self.target = target
        self.said_over = said_over or {}
        self.went_back_for = []
        self.said = []
        self.runs = []
        self.pauses = []
        self.requests = []

    def back_to_what_was_said_over(self, said_at):
        self.went_back_for.append(said_at)
        return self.said_over.get(said_at, self.target)

    def note_voice_command(self, message, *, kind=INFO):
        self.said.append(message)

    def note_voice_run(self, prompt_id, message, *, kind):
        self.runs.append((prompt_id, message, kind))

    def pause_for_request(self, paused, note):
        self.pauses.append((paused, note))

    def note_request(self, message, spoken, *, working=False, kind=INFO):
        self.requests.append((message, working, kind))


class FakeSlideshows:
    def __init__(self, showing=None, by_shape=None):
        self.showing = showing
        self.by_shape = by_shape or {}
        self.answers = []
        self.answer_kinds = []
        self.said = []
        self.kinds = []
        self.collections_played = []
        self.slideshow_commands = []
        self.filters = []
        self.slide_words = []

    def surface_for(self, shape):
        return self.by_shape.get(shape) if shape is not None else self.showing

    def answer(self, message, *, kind=INFO):
        self.answers.append(message)
        self.answer_kinds.append(kind)

    def note_voice_command(self, message, *, kind):
        self.said.append(message)
        self.kinds.append(kind)

    def play_collection(self, command):
        self.collections_played.append(command)

    def run_slideshow_command(self, command, shape):
        self.slideshow_commands.append((command, shape))

    def filter_enhanced(self, shape):
        self.filters.append(("enhanced only", shape))

    def filter_originals(self, shape):
        self.filters.append(("original only", shape))

    def show_enhanced_and_original(self, shape):
        self.filters.append(("enhanced and original", shape))

    def clear_action_filter(self, shape):
        self.filters.append(("action filter off", shape))

    def run_on_slide(self, command, said_at=None):
        self.slide_words.append((command, said_at))


class FakeMotion:
    def __init__(self):
        self.speed = 40
        self.amplitude = 50
        self.center = 50
        self.learned = False
        self.shape_steps = []

    def adjust_speed(self, by):
        self.speed += by

    def adjust_amplitude(self, by):
        self.amplitude += by

    def adjust_center(self, by):
        self.center += by

    def cycle_shape(self, by):
        self.shape_steps.append(by)

    def toggle_learned(self):
        self.learned = not self.learned

    def set_learned(self, on):
        self.learned = on

    def set_speed(self, value):
        self.speed = value

    def set_amplitude(self, value):
        self.amplitude = value

    def set_center(self, value):
        self.center = value

    def status_text(self):
        return f"speed {self.speed}, amp {self.amplitude}"


class FakeDB:
    def __init__(self, rows=()):
        self.rows = {row["prompt_id"]: row for row in rows}

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)


class FakeHost:
    def __init__(self, *, collections=("__recents__",), selected=None):
        self.collections = set(collections)
        self.selected = selected
        self.stood_in = []
        self.enhanced = []
        self.fixed = []
        self.animated = []
        self.queued = []

    def collection_label(self, key):
        return "Latest" if key == LATEST_KEY else key.strip("_").title()

    def stand_in_collection(self, key, shape):
        self.stood_in.append((key, shape))
        return key in self.collections

    def selected_generation(self):
        return self.selected

    def enhance_it(self, prompt_id):
        self.enhanced.append(prompt_id)
        return prompt_id, "enhancing…", INFO

    def fix_parts(self, prompt_id, parts):
        self.fixed.append((prompt_id, parts))
        return prompt_id, "fixing hands…", INFO

    def animate_it(self, image_id, asked):
        self.animated.append((image_id, asked))
        return image_id, f"animating as “{asked.action}”…", INFO

    def queue_request(self, row, workflow, params, spoken, revision):
        self.queued.append((row["prompt_id"], revision))
        return "queued it", INFO


class FakeAnswerer:

    def __init__(self):
        self.asked = []
        self.then = None

    def ask(self, about, pair, words, *, owner, then, **told):
        self.asked.append((about, *pair, words))
        self.then = then


class Spoken:
    def __init__(self, text="no hat", *, listening=False, state=COMPLETED,
                 heard="Request, no hat, over.", opened_at=None):
        self.text = text
        self.listening = listening
        self.state = state
        self.heard = heard
        self.opened_at = opened_at


@pytest.fixture
def starting(qtbot):
    return StartingRows()


@pytest.fixture
def router(qtbot, monkeypatch, starting):
    monkeypatch.setattr(module, "CommandAndRequestListener", FakeListener)
    # Once Python collects a QObject's parent, PyQt deletes the QObject with it, timers and all.
    built = []

    def build(host=None, *, slideshows=None, db=None, buttons=None, setters=None, **parts):
        host = host or FakeHost()
        slideshows = slideshows or FakeSlideshows()
        parent = QWidget()
        qtbot.addWidget(parent)
        router = VoiceRouter(
            host, VoiceSources(db=db or FakeDB(), slideshows=slideshows,
                               client=parts.get("client", _A_CLIENT), starting=starting,
                               requests=parts.get("requests") or FakeAnswerer(),
                               setters=setters),
            parent=parent, motion=parts.get("motion"))
        built.append((parent, router))
        buttons = dict(buttons or {})
        router.bind_the_buttons(
            VoiceSwitches(
                populate=buttons.get("populate", FakeButton(tip="Populate")),
                radio=buttons.get("radio", FakeButton(tip="Origenerator Radio")),
                drive=buttons.get("drive", FakeButton(tip="Drive the OSR2")),
                mic=buttons.get("mic", FakeButton(tip="Listen", checked=True))),
            enhance=buttons.get("enhance",
                                (FakeButton(tip="Enhance 2 images"), lambda: None)),
            actions=buttons.get("actions", {}),
        )
        return router, host, slideshows

    return build


def _row(prompt_id="g1", *, workflow_name="sdxl_t2i"):
    return {"prompt_id": prompt_id, "workflow_name": workflow_name, "params": "{}"}



def test_the_microphone_is_given_the_whole_vocabulary_to_listen_for(router):
    voice, _host, _slideshows = router()

    built_with = voice.listener.built_with
    phrases = built_with["phrases"]
    assert phrases.heard == spoken_phrases() | setter_phrases()
    assert phrases.never_repaired == phrases_heard_only_outright()
    assert phrases.said_in is said_in
    assert "transcribe_bias" not in built_with


class FakeSetters:
    def __init__(self, knows=()):
        self.known = set(knows)
        self.heard = []

    def knows(self, text):
        return text in self.known

    def hear(self, text):
        if text not in self.known:
            return False
        self.heard.append(text)
        return True


def test_a_word_the_setter_tool_in_front_knows_goes_to_it_before_any_command(router):
    setters = FakeSetters(knows={"trash"})
    voice, _host, slideshows = router(setters=setters)
    matched = voice.listener.built_with["bare_matcher"]("trash")

    voice.on_command(matched)

    assert (setters.heard, slideshows.slide_words) == (["trash"], [])


def test_a_word_the_setter_tool_does_not_know_is_matched_as_before(router):
    voice, _host, _slideshows = router(setters=FakeSetters())

    assert voice.listener.built_with["bare_matcher"]("go to recents") == shaped_app_command(
        "go to recents")


def test_words_from_the_session_reach_the_setter_tool_in_front_first(router):
    setters = FakeSetters(knows={"undo"})
    voice, _host, slideshows = router(setters=setters)

    assert voice.run_spoken_command("undo") is True
    assert (setters.heard, slideshows.slide_words) == (["undo"], [])


def test_the_mic_button_is_the_only_thing_that_opens_the_mic(router):
    voice, _host, _slideshows = router(buttons={"mic": FakeButton(tip="Listen", checked=False)})

    voice.sync()

    assert voice.listener.commands_on is False
    voice.bind_the_buttons(
        VoiceSwitches(populate=None, radio=None, drive=None, mic=FakeButton(checked=True)),
        enhance=None, actions={})
    voice.sync()
    assert voice.listener.commands_on is True



def test_closing_shuts_the_mic_and_waits_for_the_microphone_to_close(router):
    voice, _host, _slideshows = router(buttons={"mic": FakeButton(checked=True)})
    voice.sync()

    voice.close()

    assert voice.listener.commands_on is False
    assert voice.listener.closed is True
    assert voice.status.isHidden()


def test_a_flashed_line_goes_back_to_the_idle_caption(router):
    voice, _host, _slideshows = router()
    voice.sync()

    voice.say("radio on")
    assert words(voice.status) == "radio on"

    voice._revert()
    assert words(voice.status) == "Listening…"


def test_a_line_said_with_no_mark_is_shown_as_it_is(router):
    voice, _host, _slideshows = router()

    voice.say("Locked", mark="")

    assert (voice.status.textFormat(), voice.status.text()) == (Qt.TextFormat.PlainText, "Locked")


def test_a_flash_over_a_promise_goes_back_to_the_promise(router):
    voice, _host, _slideshows = router()
    voice.sync()
    voice._answer_request(None, "working out “no hat”…", Spoken(listening=False),
                          working=True)

    voice.say("heard: “something else”")
    voice._revert()

    assert words(voice.status) == "working out “no hat”…", (
        "whatever flashed over the promise, the promise is still the truest thing this pane has "
        "to say, and Listening over an app in the middle of a request reads as a request that "
        "was dropped")


def test_only_that_requests_own_answer_takes_its_promise_down(router):
    voice, _host, _slideshows = router()
    voice.sync()
    mine = Spoken("no hat")
    voice._answer_request(None, "working out “no hat”…", mine, working=True)

    voice._answer_request(None, "something about another one", Spoken("no shoes"))
    assert voice._working_status == "working out “no hat”…"

    voice._answer_request(None, "no hat — generating", mine)
    assert voice._working_status == ""


def test_what_was_heard_reaches_the_caption_and_the_center_top_of_the_slideshow(router):
    slideshow = FakeSlideshow()
    voice, _host, slideshows = router(slideshows=FakeSlideshows(showing=slideshow))

    voice.listener.heard.emit("start slideshow")

    assert words(voice.status).startswith("heard:")
    assert len(slideshows.said) == 1


def test_words_that_are_no_command_show_for_a_moment_and_are_logged_nowhere(router, caplog):
    voice, _host, slideshows = router(slideshows=FakeSlideshows(showing=FakeSlideshow()))
    voice.sync()

    with caplog.at_level(logging.DEBUG):
        voice.listener.heard.emit("put the kettle on")

    assert words(voice.status) == "heard: “put the kettle on”"
    assert slideshows.said == ["heard: “put the kettle on”"]
    assert voice._flash_timer.isActive()
    assert caplog.messages == []


def test_a_transcription_with_no_letters_in_it_says_nothing(router):
    voice, _host, slideshows = router()

    voice.listener.heard.emit("...")

    assert words(voice.status) == ""
    assert slideshows.said == []



def test_a_collection_name_stands_you_in_that_collection(router):
    voice, host, slideshows = router()

    voice.on_command(AppCommand.LATEST)

    assert host.stood_in == [(LATEST_KEY, None)]
    assert slideshows.answers == ["Latest"]


def test_a_collection_the_tree_has_not_got_says_so_rather_than_doing_nothing(router):
    voice, _host, slideshows = router(FakeHost(collections=()))

    voice.on_command(AppCommand.LATEST)

    assert slideshows.answers == ["no Latest collection yet"]
    assert slideshows.answer_kinds == [WARNING]


def test_a_named_side_picks_that_sides_copy_of_the_collection(router):
    voice, host, _slideshows = router()

    voice.on_command(SurfaceCommand(AppCommand.LATEST, "portrait"))

    assert host.stood_in == [(LATEST_KEY, "portrait")]


def test_a_spoken_switch_flips_the_bank_switch_itself(router):
    radio = FakeButton(tip="Origenerator Radio")
    voice, _host, slideshows = router(buttons={"radio": radio})

    voice.on_command(AppCommand.RADIO_ON)

    assert radio.set_to == [True]
    assert slideshows.answers == ["Origenerator Radio on"]


def test_a_switch_this_window_does_not_have_says_the_session_owns_it(router):
    voice, _host, slideshows = router(buttons={"radio": None})

    voice.on_command(AppCommand.RADIO)

    assert slideshows.answers == ["Origenerator Radio is the session's here"]
    assert slideshows.answer_kinds == [WARNING]


def test_a_switch_that_cannot_be_flipped_here_says_so(router):
    voice, _host, slideshows = router(
        buttons={"drive": FakeButton(tip="Drive", enabled=False)})

    voice.on_command(AppCommand.DRIVE_ON)

    assert slideshows.answers == ["OSR2 can't be switched here"]
    assert slideshows.answer_kinds == [WARNING]


def test_a_bar_word_moves_its_bar_the_way_its_key_does(router):
    motion = FakeMotion()
    voice, _host, slideshows = router(motion=motion)

    voice.on_command(AppCommand.SPEED_UP)

    assert motion.speed == 45
    assert slideshows.answers == ["speed 45, amp 50"]


def test_a_spoken_number_puts_a_bar_where_it_says(router):
    motion = FakeMotion()
    voice, _host, _slideshows = router(motion=motion)

    voice.on_command(BarSetting("amp", 70))

    assert motion.amplitude == 70


def test_a_router_taken_into_a_session_leaves_the_motion_to_the_session(router):
    motion = FakeMotion()
    voice, _host, slideshows = router(motion=motion)

    voice.become_hosted()
    voice.on_command(AppCommand.SPEED_UP)
    voice.on_command(BarSetting("amp", 70))

    assert (motion.speed, motion.amplitude) == (40, 50)
    assert slideshows.answers == ["the motion is the session's here"] * 2
    assert slideshows.answer_kinds == [WARNING] * 2


def test_a_router_handed_back_from_a_session_holds_the_motion_and_switches_again(router):
    motion = FakeMotion()
    radio = FakeButton(tip="Origenerator Radio")
    voice, _host, _slideshows = router(motion=motion, buttons={"radio": radio})
    voice.become_hosted()

    voice.become_standalone(motion, radio=radio, drive=FakeButton(), mic=FakeButton(checked=True))
    voice.on_command(AppCommand.SPEED_UP)
    voice.on_command(AppCommand.RADIO_ON)

    assert motion.speed == 45
    assert radio.set_to == [True]


def test_a_bank_word_presses_its_button_and_answers_in_its_own_words(router):
    pressed = []
    undo = FakeButton(tip="Undo: delete of 2 items")
    voice, _host, slideshows = router(
        buttons={"actions": {AppCommand.UNDO: (undo, lambda: pressed.append(1))}})

    voice.on_command(AppCommand.UNDO)

    assert pressed == [1]
    assert slideshows.answers == ["Undo: delete of 2 items"]
    assert slideshows.answer_kinds == [INFO]


def test_a_bank_word_whose_button_is_dead_says_why(router):
    voice, _host, slideshows = router(
        buttons={"actions": {AppCommand.GROUP: (
            FakeButton(tip=GROUP_TIP, enabled=False), lambda: None)}})

    voice.on_command(AppCommand.GROUP)

    assert slideshows.answers == ["pick some folders first"], (
        "Group's tooltip explains the button rather than refusing it, so read back it would not "
        "say why the button cannot run")
    assert slideshows.answer_kinds == [WARNING]


def test_a_slideshows_word_with_none_up_says_it_is_a_slideshows(router):
    voice, _host, slideshows = router()

    voice.on_command(AppCommand.LOCK)

    assert slideshows.answers == ["No slideshow to lock"]
    assert slideshows.answer_kinds == [WARNING]


def test_a_transport_word_goes_to_the_slide_while_a_slideshow_is_up(router):
    voice, _host, slideshows = router(slideshows=FakeSlideshows(showing=FakeSlideshow()))

    voice.on_command(AppCommand.FORWARD)

    assert slideshows.slide_words == [(AppCommand.FORWARD, None)]


def test_a_word_about_the_slide_goes_with_when_it_was_said(router):
    voice, _host, slideshows = router(slideshows=FakeSlideshows(showing=FakeSlideshow()))

    voice.on_command(AppCommand.LOCK, said_at=7.5)

    assert slideshows.slide_words == [(AppCommand.LOCK, 7.5)]


def test_undo_stays_the_gallerys_even_under_a_slideshow(router):
    pressed = []
    voice, _host, slideshows = router(
        slideshows=FakeSlideshows(showing=FakeSlideshow()),
        buttons={"actions": {AppCommand.UNDO: (FakeButton(tip="Undo"),
                                            lambda: pressed.append(1))}})

    voice.on_command(AppCommand.UNDO)

    assert pressed == [1], (
        "undoing a cull that is regretted is exactly a thing to do in the middle of a slideshow")
    assert slideshows.slide_words == []


def test_a_collection_to_play_and_a_slideshow_command_go_to_the_slideshows(router):
    voice, _host, slideshows = router()

    voice.on_command(CollectionCommand(LATEST_KEY, "portrait"))
    voice.on_command(SlideshowControl(SlideshowCommand.STOP, "landscape"))

    assert len(slideshows.collections_played) == 1
    assert slideshows.slideshow_commands == [(SlideshowCommand.STOP, "landscape")]


def test_a_filter_word_narrows_the_slideshow_rather_than_the_gallery(router):
    voice, _host, slideshows = router()

    voice.on_command(AppCommand.FILTER_ENHANCED)

    assert slideshows.filters == [("enhanced only", None)]


def test_original_only_and_enhanced_and_original_reach_the_side_they_are_said_of(router):
    voice, _host, slideshows = router()

    voice.on_command(SurfaceCommand(AppCommand.FILTER_ORIGINALS, "portrait"))
    voice.on_command(SurfaceCommand(AppCommand.ENHANCED_AND_ORIGINAL, "landscape"))

    assert slideshows.filters == [("original only", "portrait"),
                                  ("enhanced and original", "landscape")]


def test_no_filter_said_of_a_side_lifts_only_that_sides_action_filter(router):
    voice, _host, slideshows = router()

    voice.on_command(SurfaceCommand(AppCommand.FILTER_OFF, "portrait"))

    assert slideshows.filters == [("action filter off", "portrait")]


def test_a_matched_kind_nobody_wired_through_is_logged_not_dropped(router, caplog):
    voice, _host, _slideshows = router()

    with caplog.at_level("WARNING"):
        voice.on_command(object())

    assert "no arm for a matched" in caplog.text



def test_enhanced_only_heard_by_the_session_narrows_the_slideshow_and_enhances_nothing(router):
    slideshows = FakeSlideshows(showing=FakeSlideshow(target="g7"))
    voice, host, _slideshows = router(slideshows=slideshows)
    voice.listener.bare = voice.listener.built_with["bare_matcher"]("enhanced only")

    assert voice.run_spoken_command("enhanced only") is True

    assert (host.enhanced, slideshows.filters) == ([], [("enhanced only", None)]), (
        "the words are asked as a command of their own before the looser matcher, which reads "
        "enhanced only as enhance with a word after it and spends a generation on it")


def test_an_order_about_the_image_goes_to_the_slide_filling_the_screen(router):
    slideshow = FakeSlideshow(target="g7")
    voice, host, _slideshows = router(slideshows=FakeSlideshows(showing=slideshow))

    voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND, None))

    assert host.enhanced == ["g7"]
    assert slideshow.runs == [("g7", "enhancing…", INFO)]


def test_an_order_said_over_an_image_since_left_is_about_that_image_put_back(router):
    slideshow = FakeSlideshow(target="g7", said_over={7.5: "g6"})
    voice, host, _slideshows = router(slideshows=FakeSlideshows(showing=slideshow))

    voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND, None), said_at=7.5)

    assert host.enhanced == ["g6"]
    assert slideshow.went_back_for == [7.5]


def test_enhance_with_no_slideshow_up_falls_to_the_bank_button_of_that_name(router):
    pressed = []
    voice, host, slideshows = router(
        buttons={"enhance": (FakeButton(tip="Enhance 2 images"),
                          lambda: pressed.append(1))})

    voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND, None))

    assert pressed == [1]
    assert host.enhanced == []
    assert slideshows.answers == ["Enhance 2 images"]


def test_an_animation_goes_to_the_image_on_screen_with_the_lane_and_action_said(router):
    slideshow = FakeSlideshow(target="g7")
    voice, host, _slideshows = router(slideshows=FakeSlideshows(showing=slideshow))
    asked = AnimateRequest(GENAU, "alpha")

    voice.on_command(SurfaceCommand(asked, None))

    assert host.animated == [("g7", asked)]
    assert slideshow.runs == [("g7", "animating as “alpha”…", INFO)]


def test_an_animation_asked_for_with_no_image_on_screen_says_so(router):
    voice, host, _slideshows = router()

    voice.on_command(SurfaceCommand(AnimateRequest(VIDEO, "alpha"), None))

    assert host.animated == []
    assert words(voice.status) == "an animation needs an image on screen", (
        "a line of its own rather than the action's name: the command is a record rather than a "
        "word, and every action names itself differently")



def test_an_opening_request_pauses_the_slideshow_and_says_so(router):
    slideshow = FakeSlideshow()
    voice, _host, _slideshows = router(slideshows=FakeSlideshows(showing=slideshow))

    voice.on_spoken_request(Spoken("no hat", listening=True))

    assert slideshow.pauses == [(True, "Request: no hat… — say “over” to submit")]


def test_an_open_request_reminds_the_speaker_that_over_submits_it(router):
    voice, _host, _slideshows = router()

    voice.on_spoken_request(Spoken("no hat", listening=True))

    assert words(voice.status).endswith("say “over” to submit")


def test_the_target_is_taken_at_the_opening_step_and_kept(router):
    slideshow = FakeSlideshow(target="g1")
    voice, _host, _slideshows = router(slideshows=FakeSlideshows(showing=slideshow),
                                       db=FakeDB([_row("g1")]))
    begun = []
    voice._begin_request = lambda prompt_id, spoken, shape=None: begun.append(prompt_id)
    voice.on_spoken_request(Spoken("no hat", listening=True))
    slideshow.target = "g2"

    voice.on_spoken_request(Spoken("no hat"))

    assert begun == ["g1"], (
        "the working-out itself goes to a pool thread, whose answer would land whenever it landed; "
        "what this is about is which image it is begun on")
    assert voice._request_target is None


def test_a_request_is_about_the_image_it_was_opened_over_and_puts_it_back(router):
    slideshow = FakeSlideshow(target="g2", said_over={7.5: "g1"})
    voice, _host, _slideshows = router(slideshows=FakeSlideshows(showing=slideshow),
                                       db=FakeDB([_row("g1"), _row("g2")]))
    begun = []
    voice._begin_request = lambda prompt_id, spoken, shape=None: begun.append(prompt_id)

    voice.on_spoken_request(Spoken("no hat", opened_at=7.5))

    assert begun == ["g1"]
    assert slideshow.went_back_for == [7.5]


def test_words_in_a_request_are_a_request_even_when_they_name_a_fix(router):
    slideshow = FakeSlideshow(target="g1")
    voice, host, _slideshows = router(slideshows=FakeSlideshows(showing=slideshow),
                                      db=FakeDB([_row("g1")]))
    begun = []
    voice._begin_request = lambda prompt_id, spoken, shape=None: begun.append(prompt_id)
    voice.on_spoken_request(Spoken("fix hands", listening=True))

    voice.on_spoken_request(Spoken("fix hands", heard="Request, fix hands, over."))

    assert begun == ["g1"]
    assert host.fixed == []


def test_a_request_with_no_slideshow_up_is_about_the_picked_generation(router):
    voice, _host, _slideshows = router(FakeHost(selected="g5"))

    voice.on_spoken_request(Spoken("no hat", listening=True))

    assert voice._request_target == "g5"


def test_a_request_whose_terminator_never_came_is_dropped_and_says_so(router):
    voice, _host, _slideshows = router()
    voice.on_spoken_request(Spoken("no hat", listening=True))

    voice.on_spoken_request(Spoken("no hat", state="never got there"))

    assert words(voice.status) == "request dropped — never heard “over”"


def test_a_request_over_nothing_is_answered_rather_than_queued(router):
    voice, host, _slideshows = router(db=FakeDB())

    voice._begin_request(None, Spoken("no hat"))

    assert host.queued == []
    assert words(voice.status) == "nothing on screen to request a change to"


def test_a_video_this_app_cannot_rebuild_is_answered_here(router):
    voice, host, _slideshows = router(db=FakeDB([_row("g1", workflow_name="a_stranger")]))

    voice._begin_request("g1", Spoken("no hat"))

    assert host.queued == []
    assert words(voice.status) == (
        "this one can't be re-made, so there's nothing to revise")


def test_a_request_being_worked_out_stands_in_the_job_queue_at_once(router, starting):
    voice, _host, _slideshows = router(db=FakeDB([_row("g1")]))

    voice._begin_request("g1", Spoken("no hat"))

    (standing,) = starting.rows()
    assert standing.requested
    assert standing.starting


def test_a_requests_row_in_the_job_queue_goes_whatever_its_answer(router, starting):
    voice, _host, _slideshows = router(db=FakeDB([_row("g1")]))
    voice._begin_request("g1", Spoken("no hat"))
    (standing,) = starting.rows()

    voice._on_revised((_row("g1"), object(), {}, Spoken("no hat"), None, standing.key), None)

    assert starting.rows() == []


def test_a_finished_request_is_asked_of_the_model_about_the_image_it_was_said_over(router):
    requests = FakeAnswerer()
    voice, _host, _slideshows = router(db=FakeDB([_row("g1")]), requests=requests)

    voice._begin_request("g1", Spoken("no hat"))

    ((about, _positive, _negative, asked),) = requests.asked
    assert (about, asked) == ("g1", "no hat")
    assert "working out" in words(voice.status)


def test_a_revision_that_changed_nothing_says_so_rather_than_generating(router):
    class Revision:
        changed = False
        term = "hat"
        answer = ""

    voice, host, _slideshows = router()

    voice._on_revised((_row("g1"), object(), {}, Spoken("no hat"), None, None), Revision())

    assert host.queued == []
    assert words(voice.status) == "“hat” is already how you asked for it"


def test_a_revision_that_changed_nothing_but_was_answered_says_the_models_sentence(router):
    class Revision:
        changed = False
        term = "freckles"
        answer = "The freckles are already there."

    voice, host, _slideshows = router()

    voice._on_revised((_row("g1"), object(), {}, Spoken("more freckles"), None, None), Revision())

    assert host.queued == []
    assert words(voice.status) == "The freckles are already there."


def test_a_revision_nobody_could_read_says_so(router):
    voice, host, _slideshows = router()

    voice._on_revised((_row("g1"), object(), {}, Spoken("no hat"), None, None), None)

    assert host.queued == []
    assert words(voice.status) == "didn't catch what to change in “no hat”"


def test_a_real_revision_is_queued_and_answered_where_it_was_said(router):
    class Revision:
        changed = True
        term = "hat"

    slideshow = FakeSlideshow()
    voice, host, _slideshows = router(slideshows=FakeSlideshows(by_shape={"portrait": slideshow}))

    voice._on_revised(
        (_row("g1"), object(), {}, Spoken("no hat"), "portrait", None), Revision())

    assert [pid for pid, _rev in host.queued] == ["g1"]
    assert slideshow.requests[-1] == ("queued it", False, INFO)


def test_a_request_with_nothing_to_act_on_is_answered_as_a_warning(router):
    slideshow = FakeSlideshow()
    voice, host, _slideshows = router(slideshows=FakeSlideshows(by_shape={"portrait": slideshow}))

    voice._on_revised((_row("g1"), object(), {}, Spoken("no hat"), "portrait", None), None)

    assert host.queued == []
    assert slideshow.requests[-1] == (
        "didn't catch what to change in “no hat”", False, WARNING)


def test_a_microphone_that_fails_says_so_as_an_error(router):
    voice, _host, slideshows = router()

    voice.listener.error.emit("mic unavailable")

    assert slideshows.said == ["mic unavailable"]
    assert slideshows.kinds == [ERROR]


def test_what_the_listener_answers_with_is_left_to_the_listener_to_log(router, caplog):
    voice, _host, _slideshows = router()

    with caplog.at_level(logging.DEBUG):
        voice.listener.error.emit("Didn't catch that.")

    assert caplog.messages == []



def test_a_whole_utterance_command_from_the_session_outranks_the_rest(router):
    voice, _host, slideshows = router()
    voice.listener.bare = AppCommand.LATEST

    assert voice.run_spoken_command("recents") is True
    assert slideshows.answers == ["Latest"]


def test_the_sessions_words_go_to_an_open_request_before_any_command(router):
    voice, _host, slideshows = router()
    voice.listener.bare = AppCommand.LATEST
    voice.listener.dictated = Spoken("recents", listening=True)

    assert voice.run_spoken_command("portrait recents") is True
    assert slideshows.answers == []
    assert words(voice.status) == "Request: recents… — say “over” to submit"


def test_a_requests_own_words_from_the_session_go_to_the_dictation(router):
    voice, _host, _slideshows = router()
    voice.listener.dictated = Spoken("no hat", listening=True)

    assert voice.run_spoken_command("portrait request no hat") is True
    assert words(voice.status) == "Request: no hat… — say “over” to submit"


def test_the_sessions_words_reach_the_dictation_with_when_they_were_said(router):
    voice, _host, _slideshows = router()
    voice.listener.dictated = Spoken("no hat", listening=True)

    voice.run_spoken_command("portrait request no hat", said_at=7.5)

    assert voice.listener.dictated_at == [7.5]


def test_words_that_match_nothing_here_are_handed_back_and_logged_only_by_count(
        router, caplog):
    voice, _host, _slideshows = router()

    with caplog.at_level(logging.DEBUG):
        assert voice.run_spoken_command("put the kettle on") is False

    assert caplog.messages == ["Voice (from the session): a 4-word utterance matched no command"]


def test_a_requests_answer_on_the_caption_stays_up_long_enough_to_be_read(router):
    voice, _host, _slideshows = router()
    long_answer = ("Moved her to a tropical beach at golden hour, the way your beach prompts "
                   "usually have it, and kept the pose and the lighting as they were.")

    voice._answer_request(None, "Request submitted", Spoken("no hat"))
    short = voice._flash_timer.interval()
    voice._answer_request(None, long_answer, Spoken("a beach"))

    assert voice._flash_timer.interval() > short
