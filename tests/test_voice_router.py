"""What is spoken, driven with no gallery around it.

Every path an utterance takes used to be reachable only by building a 7,000-line
widget: the caption's one promise and what takes it down, the bank button a word
presses and what it answers with, the shelf a name stands you in, the dial a
number puts where it says, and a request said over three breaths. Here the bank
is a handful of recorders and the host a handful of recorded calls.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QWidget

from origenerator import gallery
from origenerator.gui import voice_router as module
from origenerator.gui.gallery_tree import RECENTS_KEY
from origenerator.gui.voice_router import VoiceRouter
from origenerator.voice.app_commands import AppCommand, DialSetting
from origenerator.voice.commands import ShelfCommand, ShowControl, SurfaceCommand
from origenerator.voice.dictation import COMPLETED
from origenerator.voice.show_commands import ShowCommand


class FakeSignal:
    def __init__(self):
        self.slots = []

    def connect(self, slot):
        self.slots.append(slot)

    def emit(self, *args):
        for slot in list(self.slots):
            slot(*args)


class FakeListener:
    """A VoiceSteering reduced to what the router asks of one."""

    def __init__(self, **kwargs):
        self.built_with = kwargs
        self.heard = FakeSignal()
        self.edited = FakeSignal()
        self.error = FakeSignal()
        self.request = FakeSignal()
        self.started = False
        self.commands_on = False
        self.stops = 0
        self.bare = None
        self.dictated = None
        self.on_command = None

    def start(self, get_prompts, set_prompts):
        self.started = True
        self.get_prompts = get_prompts
        self.set_prompts = set_prompts

    def stop(self):
        self.started = False
        self.stops += 1

    def start_commands(self, handler):
        self.commands_on = True
        self.on_command = handler

    def stop_commands(self):
        self.commands_on = False

    def bare_command(self, text):
        return self.bare

    def push_dictation(self, text):
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


class FakeShow:
    def __init__(self, target="g1"):
        self.target = target
        self.said = []
        self.runs = []
        self.holds = []
        self.requests = []

    def voice_target(self):
        return self.target

    def note_voice_command(self, message):
        self.said.append(message)

    def note_voice_run(self, prompt_id, message):
        self.runs.append((prompt_id, message))

    def hold_for_request(self, holding, note):
        self.holds.append((holding, note))

    def note_request(self, message, spoken, *, working=False):
        self.requests.append((message, working))


class FakeShows:
    """The shows reduced to what a spoken word asks of them."""

    def __init__(self, showing=None, by_side=None):
        self.showing = showing
        self.by_side = by_side or {}
        self.answers = []
        self.said = []
        self.shelves_played = []
        self.show_commands = []
        self.filters = []
        self.slide_words = []

    def surface_for(self, side):
        return self.by_side.get(side) if side is not None else self.showing

    def answer(self, message):
        self.answers.append(message)

    def note_voice_command(self, message):
        self.said.append(message)

    def play_shelf(self, command):
        self.shelves_played.append(command)

    def run_show_command(self, command, side):
        self.show_commands.append((command, side))

    def filter_enhanced(self, enhanced_only, side):
        self.filters.append((enhanced_only, side))

    def run_on_slide(self, command):
        self.slide_words.append(command)


class FakeMotion:
    def __init__(self):
        self.speed = 40
        self.amplitude = 50
        self.centre = 50
        self.cruising = False
        self.shape_steps = []

    def adjust_speed(self, by):
        self.speed += by

    def adjust_amplitude(self, by):
        self.amplitude += by

    def adjust_center(self, by):
        self.centre += by

    def cycle_shape(self, by):
        self.shape_steps.append(by)

    def toggle_cruise(self):
        self.cruising = not self.cruising

    def set_cruise(self, on):
        self.cruising = on

    def quarter_offset(self):
        pass

    def set_speed(self, value):
        self.speed = value

    def set_amplitude(self, value):
        self.amplitude = value

    def set_center(self, value):
        self.centre = value

    def status_text(self):
        return f"speed {self.speed}, amp {self.amplitude}"


class FakeDB:
    def __init__(self, rows=()):
        self.rows = {row["prompt_id"]: row for row in rows}

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)


class FakeHost:
    """A gallery reduced to what the spoken words ask of one."""

    def __init__(self, *, shelves=("__recents__",), selected=None):
        self.shelves = set(shelves)
        self.selected = selected
        self.prompts = {"folder/a": {"positive": "a doll", "negative": "ugly"}}
        self.steered = []
        self.stood_in = []
        self.enhanced = []
        self.fixed = []
        self.genaued = []
        self.queued = []

    def working_prompts(self, key):
        return self.prompts.get(key, {})

    def steer_prompts(self, key, new_prompts):
        self.steered.append((key, new_prompts))

    def shelf_label(self, key):
        return "Latest" if key == RECENTS_KEY else key.strip("_").title()

    def stand_in_shelf(self, key, side):
        self.stood_in.append((key, side))
        return key in self.shelves

    def selected_generation(self):
        return self.selected

    def enhance_it(self, prompt_id):
        self.enhanced.append(prompt_id)
        return prompt_id, "🎤 enhancing…"

    def fix_parts(self, prompt_id, parts):
        self.fixed.append((prompt_id, parts))
        return prompt_id, "🎤 fixing hands…"

    def genau_it(self, image_id):
        self.genaued.append(image_id)
        return image_id, "🎤 making a clip…"

    def queue_request(self, row, workflow, params, spoken, revision):
        self.queued.append((row["prompt_id"], revision))
        return "🎤 queued it"


class Spoken:
    """One step of a dictated request, as the dictation hands it over."""

    def __init__(self, text="no hat", *, listening=False, state=COMPLETED,
                 heard="Request, no hat, over."):
        self.text = text
        self.listening = listening
        self.state = state
        self.heard = heard


@pytest.fixture
def router(qtbot, monkeypatch):
    """A router under a parent this fixture keeps alive: a QObject whose parent is
    collected takes its timers down with it. Its listener, bank and motion are
    all recorders."""
    monkeypatch.setattr(module, "VoiceSteering", FakeListener)
    built = []

    def build(host=None, *, shows=None, db=None, client=object(), motion=None,
              bank=None, mic_on=True):
        host = host or FakeHost()
        shows = shows or FakeShows()
        parent = QWidget()
        qtbot.addWidget(parent)
        router = VoiceRouter(host, parent=parent, db=db or FakeDB(), shows=shows,
                             client=client, motion=motion)
        built.append((parent, router))
        buttons = dict(bank or {})
        router.bind_the_bank(
            auto=buttons.get("auto", FakeButton(tip="Auto-generate")),
            audio=buttons.get("audio", FakeButton(tip="Audio bed")),
            drive=buttons.get("drive", FakeButton(tip="Drive the OSR2")),
            mic=buttons.get("mic", FakeButton(tip="Listen", checked=mic_on)),
            enhance=buttons.get("enhance",
                                (FakeButton(tip="Enhance 2 images"), lambda: None)),
            actions=buttons.get("actions", {}),
        )
        return router, host, shows

    yield build


def _row(prompt_id="g1", *, workflow_name="sdxl_t2i"):
    return {"prompt_id": prompt_id, "workflow_name": workflow_name, "params": "{}"}


# --- the microphone ---------------------------------------------------------


def test_the_mic_button_is_the_only_thing_that_opens_the_mic(router):
    # It used to come on with the Auto loop and again with a show, which left
    # "start slideshow" unhearable in the one state it is for.
    voice, _host, _shows = router(mic_on=False)

    voice.sync()

    assert voice.listener.commands_on is False
    voice.bind_the_bank(auto=None, audio=None, drive=None,
                        mic=FakeButton(checked=True), enhance=None, actions={})
    voice.sync()
    assert voice.listener.commands_on is True


def test_the_commands_hold_the_mic_open_with_no_loop_to_steer(router):
    voice, _host, _shows = router()

    voice.sync()

    assert voice.listener.commands_on is True
    assert voice.listener.started is False  # nothing to steer is not a second switch


def test_a_loop_gives_the_open_mic_a_prompt_to_steer(router):
    voice, host, _shows = router()

    voice.steer("folder/a")

    assert voice.listener.started is True
    voice.listener.set_prompts({"positive": "a doll, no hat"})
    assert host.steered == [("folder/a", {"positive": "a doll, no hat"})]


def test_the_steered_folder_moving_does_not_re_open_the_listener(router):
    # The steering reads the folder at each utterance, so following it there is
    # a re-point and nothing more.
    voice, _host, _shows = router()
    voice.steer("folder/a")
    stops = voice.listener.stops

    voice.re_home("folder/a", "folder/b")

    assert voice.steering == "folder/b"
    assert voice.listener.stops == stops


def test_a_folder_that_was_not_the_steered_one_moving_changes_nothing(router):
    voice, _host, _shows = router()
    voice.steer("folder/a")

    voice.re_home("folder/z", "folder/b")

    assert voice.steering == "folder/a"


# --- the caption ------------------------------------------------------------


def test_a_flashed_line_goes_back_to_the_idle_caption(router):
    voice, _host, _shows = router()
    voice.sync()

    voice.say("🎤 audio on")
    assert voice.status.text() == "🎤 audio on"

    voice._revert()
    assert voice.status.text() == "🎤 Listening…"


def test_a_flash_over_a_promise_goes_back_to_the_promise(router):
    # "Listening…" over an app still working out a request reads as a request
    # that was dropped.
    voice, _host, _shows = router()
    voice.sync()
    voice._answer_request(None, "🎤 working out “no hat”…", Spoken(listening=False),
                          working=True)

    voice.say("🎤 heard: “something else”")
    voice._revert()

    assert voice.status.text() == "🎤 working out “no hat”…"


def test_only_that_requests_own_answer_takes_its_promise_down(router):
    voice, _host, _shows = router()
    voice.sync()
    mine = Spoken("no hat")
    voice._answer_request(None, "🎤 working out “no hat”…", mine, working=True)

    voice._answer_request(None, "🎤 something about another one", Spoken("no shoes"))
    assert voice._working_status == "🎤 working out “no hat”…"

    voice._answer_request(None, "🎤 no hat — generating", mine)
    assert voice._working_status == ""


def test_what_was_heard_reaches_the_caption_and_the_shows_corner(router):
    # Different screens: someone watching a slideshow can see nothing of this
    # window at all.
    show = FakeShow()
    voice, _host, shows = router(shows=FakeShows(showing=show))

    voice.listener.heard.emit("start slideshow")

    assert voice.status.text().startswith("🎤 heard:")
    assert len(shows.said) == 1


def test_a_transcription_with_no_letters_in_it_says_nothing(router):
    voice, _host, shows = router()

    voice.listener.heard.emit("...")

    assert voice.status.text() == ""
    assert shows.said == []


# --- where one word lands ---------------------------------------------------


def test_a_shelf_name_stands_you_in_that_shelf(router):
    voice, host, shows = router()

    voice.on_command(AppCommand.RECENTS)

    assert host.stood_in == [(RECENTS_KEY, None)]
    assert shows.answers == ["🎤 Latest"]


def test_a_shelf_the_tree_has_not_got_says_so_rather_than_doing_nothing(router):
    voice, _host, shows = router(FakeHost(shelves=()))

    voice.on_command(AppCommand.RECENTS)

    assert shows.answers == ["🎤 no Latest shelf yet"]


def test_a_named_side_picks_that_sides_copy_of_the_shelf(router):
    voice, host, _shows = router()

    voice.on_command(SurfaceCommand(AppCommand.RECENTS, "portrait"))

    assert host.stood_in == [(RECENTS_KEY, "portrait")]


def test_a_spoken_switch_flips_the_bank_switch_itself(router):
    # A spoken switch is the same event as a clicked one, so the bank lights the
    # same way and nothing has to be kept in step.
    audio = FakeButton(tip="Audio bed")
    voice, _host, shows = router(bank={"audio": audio})

    voice.on_command(AppCommand.AUDIO_ON)

    assert audio.set_to == [True]
    assert shows.answers == ["🎤 the audio bed on"]


def test_a_switch_this_window_does_not_have_says_the_session_owns_it(router):
    voice, _host, shows = router(bank={"audio": None})

    voice.on_command(AppCommand.AUDIO)

    assert shows.answers == ["🎤 the audio bed is the session's here"]


def test_a_switch_that_cannot_be_flipped_here_says_so(router):
    voice, _host, shows = router(
        bank={"drive": FakeButton(tip="Drive", enabled=False)})

    voice.on_command(AppCommand.DRIVE_ON)

    assert shows.answers == ["🎤 the OSR2 can't be switched here"]


def test_a_dial_word_turns_the_motion_the_way_its_key_does(router):
    motion = FakeMotion()
    voice, _host, shows = router(motion=motion)

    voice.on_command(AppCommand.SPEED_UP)

    assert motion.speed == 45
    assert shows.answers == ["🎤 speed 45, amp 50"]


def test_a_spoken_number_puts_a_dial_where_it_says(router):
    # The nudges are for a motion that is nearly right; this is for one that is
    # not, and the dial does its own clamping.
    motion = FakeMotion()
    voice, _host, _shows = router(motion=motion)

    voice.on_command(DialSetting("amp", 70))

    assert motion.amplitude == 70


def test_a_bank_word_presses_its_button_and_answers_in_its_own_words(router):
    # Its tip already says what it will do to what is in front of you, which is
    # what a speaker who is not looking at the bank needs told back.
    pressed = []
    undo = FakeButton(tip="Undo: delete of 2 items")
    voice, _host, shows = router(
        bank={"actions": {AppCommand.UNDO: (undo, lambda: pressed.append(1))}})

    voice.on_command(AppCommand.UNDO)

    assert pressed == [1]
    assert shows.answers == ["🎤 Undo: delete of 2 items"]


def test_a_bank_word_whose_button_is_dead_says_why(router):
    voice, _host, shows = router(
        bank={"actions": {AppCommand.GROUP: (FakeButton(tip="Group", enabled=False),
                                             lambda: None)}})

    voice.on_command(AppCommand.GROUP)

    assert shows.answers == ["🎤 pick some folders first"]


def test_a_slideshows_word_with_none_up_says_it_is_a_slideshows(router):
    voice, _host, shows = router()

    voice.on_command(AppCommand.LOCK)

    assert shows.answers == [f"🎤 {AppCommand.LOCK.value} is a slideshow's — none is up"]


def test_a_transport_word_goes_to_the_slide_while_a_show_is_up(router):
    voice, _host, shows = router(shows=FakeShows(showing=FakeShow()))

    voice.on_command(AppCommand.FORWARD)

    assert shows.slide_words == [AppCommand.FORWARD]


def test_undo_stays_the_gallerys_even_under_a_show(router):
    # Undoing a cull you regret is exactly a thing to do mid-show.
    pressed = []
    voice, _host, shows = router(
        shows=FakeShows(showing=FakeShow()),
        bank={"actions": {AppCommand.UNDO: (FakeButton(tip="Undo"),
                                            lambda: pressed.append(1))}})

    voice.on_command(AppCommand.UNDO)

    assert pressed == [1]
    assert shows.slide_words == []


def test_a_shelf_to_play_and_a_show_command_go_to_the_shows(router):
    voice, _host, shows = router()

    voice.on_command(ShelfCommand(RECENTS_KEY, "portrait"))
    voice.on_command(ShowControl(ShowCommand.STOP, "landscape"))

    assert len(shows.shelves_played) == 1
    assert shows.show_commands == [(ShowCommand.STOP, "landscape")]


def test_a_filter_word_narrows_the_show_rather_than_the_gallery(router):
    voice, _host, shows = router()

    voice.on_command(AppCommand.FILTER_ENHANCED)

    assert shows.filters == [(True, None)]


def test_a_matched_kind_nobody_wired_through_is_logged_not_dropped(router, caplog):
    voice, _host, _shows = router()

    with caplog.at_level("WARNING"):
        voice.on_command(object())

    assert "no arm for a matched" in caplog.text


# --- orders about the picture on screen -------------------------------------


def test_an_order_about_the_picture_goes_to_the_slide_filling_the_screen(router):
    show = FakeShow(target="g7")
    voice, host, _shows = router(shows=FakeShows(showing=show))

    voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND, None))

    assert host.enhanced == ["g7"]
    assert show.runs == [("g7", "🎤 enhancing…")]


def test_enhance_with_no_show_up_falls_to_the_bank_button_of_that_name(router):
    # A refusal there would be a dead end where there is a perfectly good thing
    # to do.
    pressed = []
    voice, host, shows = router(
        bank={"enhance": (FakeButton(tip="Enhance 2 images"),
                          lambda: pressed.append(1))})

    voice.on_command(SurfaceCommand(gallery.ENHANCE_COMMAND, None))

    assert pressed == [1]
    assert host.enhanced == []
    assert shows.answers == ["🎤 Enhance 2 images"]


def test_a_clip_asked_for_with_no_picture_on_screen_says_so(router):
    voice, host, _shows = router()

    voice.on_command(SurfaceCommand(gallery.GENAU_COMMAND, None))

    assert host.genaued == []
    assert voice.status.text() == "🎤 a Genau clip needs a picture on screen"


# --- a request said over several breaths ------------------------------------


def test_an_opening_request_holds_the_show_and_says_so(router):
    show = FakeShow()
    voice, _host, _shows = router(shows=FakeShows(showing=show))

    voice.on_spoken_request(Spoken("no hat", listening=True))

    assert show.holds == [(True, "🎤 Request: no hat…")]


def test_the_target_is_taken_at_the_opening_step_and_kept(router):
    # A show holds still for the sentence, but the words take seconds and the
    # item on screen when they end is not necessarily the one they were about.
    show = FakeShow(target="g1")
    voice, _host, _shows = router(shows=FakeShows(showing=show),
                                  db=FakeDB([_row("g1")]))
    begun = []
    # The working-out itself goes to a pool thread, whose answer would land
    # whenever it landed; what this is about is which picture it is begun on.
    voice._begin_request = lambda prompt_id, spoken, side=None: begun.append(prompt_id)
    voice.on_spoken_request(Spoken("no hat", listening=True))
    show.target = "g2"

    voice.on_spoken_request(Spoken("no hat"))

    assert begun == ["g1"]
    assert voice._request_target is None


def test_a_request_with_no_show_up_is_about_the_picked_generation(router):
    voice, _host, _shows = router(FakeHost(selected="g5"))

    voice.on_spoken_request(Spoken("no hat", listening=True))

    assert voice._request_target == "g5"


def test_a_request_whose_terminator_never_came_is_dropped_and_says_so(router):
    voice, _host, _shows = router()
    voice.on_spoken_request(Spoken("no hat", listening=True))

    voice.on_spoken_request(Spoken("no hat", state="never got there"))

    assert voice.status.text() == "🎤 request dropped — never heard “over”"


def test_a_request_over_nothing_is_answered_rather_than_queued(router):
    voice, host, _shows = router(db=FakeDB())

    voice._begin_request(None, Spoken("no hat"))

    assert host.queued == []
    assert voice.status.text() == "🎤 nothing on screen to request a change to"


def test_a_recipe_this_app_cannot_rebuild_is_answered_here(router):
    voice, host, _shows = router(db=FakeDB([_row("g1", workflow_name="a_stranger")]))

    voice._begin_request("g1", Spoken("no hat"))

    assert host.queued == []
    assert voice.status.text() == (
        "🎤 this one can't be re-made, so there's nothing to revise")


def test_a_revision_that_changed_nothing_says_so_rather_than_generating(router):
    class Revision:
        changed = False
        term = "hat"

    voice, host, _shows = router()

    voice._on_revised((_row("g1"), object(), {}, Spoken("no hat"), None), Revision())

    assert host.queued == []
    assert voice.status.text() == "🎤 “hat” is already how you asked for it"


def test_a_revision_nobody_could_read_says_so(router):
    voice, host, _shows = router()

    voice._on_revised((_row("g1"), object(), {}, Spoken("no hat"), None), None)

    assert host.queued == []
    assert voice.status.text() == "🎤 didn't catch what to change in “no hat”"


def test_a_real_revision_is_queued_and_answered_where_it_was_said(router):
    class Revision:
        changed = True
        term = "hat"

    show = FakeShow()
    voice, host, _shows = router(shows=FakeShows(by_side={"portrait": show}))

    voice._on_revised(
        (_row("g1"), object(), {}, Spoken("no hat"), "portrait"), Revision())

    assert [pid for pid, _rev in host.queued] == ["g1"]
    assert show.requests[-1] == ("🎤 queued it", False)


# --- words the hosting session heard ----------------------------------------


def test_a_whole_utterance_command_from_the_session_outranks_the_rest(router):
    voice, _host, shows = router()
    voice.listener.bare = AppCommand.RECENTS

    assert voice.run_spoken_command("recents") is True
    assert shows.answers == ["🎤 Latest"]


def test_a_requests_own_words_from_the_session_go_to_the_dictation(router):
    voice, _host, _shows = router()
    voice.listener.dictated = Spoken("no hat", listening=True)

    assert voice.run_spoken_command("portrait request no hat") is True
    assert voice.status.text() == "🎤 Request: no hat…"


def test_words_that_match_nothing_here_are_handed_back_as_not_ours(router):
    voice, _host, _shows = router()

    assert voice.run_spoken_command("put the kettle on") is False
