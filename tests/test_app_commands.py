"""The bare spoken vocabulary — a shelf, a button, an order to the slide.

One word is the whole utterance or it is nothing, because everything this
matcher declines is rewritten into a prompt instead: a loose match here would
spend a command on a sentence, and a loose miss would put a command word into
the picture.
"""

import pytest

from origenerator.voice.app_commands import (
    _BIAS_SKIP, _PHRASES, AppCommand, DialSetting, app_command_bias,
    match_app_command,
)


# --- the shelves that lead the tree, each by the name on its row -------------

@pytest.mark.parametrize("said, wanted", [
    ("experiments", AppCommand.EXPERIMENTS),
    ("requests", AppCommand.REQUESTS),
    ("recents", AppCommand.RECENTS),
    ("starred", AppCommand.STARRED),
    ("trash", AppCommand.TRASH),
])
def test_a_shelf_answers_to_its_own_bare_name(said, wanted):
    assert match_app_command(said) is wanted


@pytest.mark.parametrize("said", ["go to experiments", "open experiments",
                                  "show experiments", "experiments shelf"])
def test_a_shelf_also_answers_to_a_sentence_shaped_ask(said):
    assert match_app_command(said) is AppCommand.EXPERIMENTS


def test_the_requests_shelf_answers_only_to_the_plural():
    # "request" is what opens a spoken request, and one word cannot both open a
    # sentence and navigate away from it. The plural is what the row is
    # labeled, so it is the plural that reaches the shelf.
    assert match_app_command("requests") is AppCommand.REQUESTS
    assert match_app_command("request") is None


# --- Fun Time's own words over a show ---------------------------------------

def test_the_words_fun_times_players_answer_to_mean_the_same_here():
    assert match_app_command("weird") is AppCommand.CULL
    assert match_app_command("lock") is AppCommand.LOCK
    assert match_app_command("unlock") is AppCommand.UNLOCK
    assert match_app_command("next") is AppCommand.FORWARD
    assert match_app_command("previous") is AppCommand.BACK
    assert match_app_command("skip") is AppCommand.FORWARD
    assert match_app_command("back") is AppCommand.BACK


def test_the_stroke_knobs_keep_fun_times_phrases():
    assert match_app_command("speed up") is AppCommand.SPEED_UP
    assert match_app_command("slow down") is AppCommand.SPEED_DOWN
    assert match_app_command("amp down") is AppCommand.AMP_DOWN
    assert match_app_command("center up") is AppCommand.CENTER_UP
    assert match_app_command("cruise control") is AppCommand.CRUISE
    assert match_app_command("offset") is AppCommand.OFFSET


def test_cruise_answers_an_explicit_on_and_off_as_well_as_a_flip():
    # Hands-free is reached for without looking at the panel, so a speaker who
    # wants it ON must not have to find out which way it is standing first.
    assert match_app_command("cruise") is AppCommand.CRUISE
    assert match_app_command("cruise on") is AppCommand.CRUISE_ON
    assert match_app_command("cruise off") is AppCommand.CRUISE_OFF


# --- the dials said outright, which is Fun Time's numeric grid ---------------

@pytest.mark.parametrize("said, wanted", [
    ("amp fifty", DialSetting("amp", 50)),
    ("speed thirty", DialSetting("speed", 30)),
    ("center seventy", DialSetting("center", 70)),
    ("speed zero", DialSetting("speed", 0)),
    ("amp one hundred", DialSetting("amp", 100)),
])
def test_a_dial_takes_the_number_said(said, wanted):
    assert match_app_command(said) == wanted


@pytest.mark.parametrize("said, wanted", [
    ("min speed", DialSetting("speed", 0)),
    ("max speed", DialSetting("speed", 100)),
    ("min amp", DialSetting("amp", 0)),
    ("max amp", DialSetting("amp", 100)),
    ("min center", DialSetting("center", 0)),
    ("max center", DialSetting("center", 100)),
])
def test_both_ends_of_a_dial_have_a_name(said, wanted):
    # The far end in one utterance, rather than a number to remember or a dozen
    # nudges to get there.
    assert match_app_command(said) == wanted


@pytest.mark.parametrize("said", ["amp 50", "Amp 50.", "amp fifty"])
def test_a_number_counts_whether_whisper_wrote_it_in_words_or_digits(said):
    # Whisper picks between "fifty" and "50" on its own, so a vocabulary that
    # knows only one of the two hears half of what was said.
    assert match_app_command(said) == DialSetting("amp", 50)


def test_the_nudges_still_outrank_the_grid_they_sit_beside():
    # "speed up" is a nudge and "speed ten" is a setting; neither eats the other.
    assert match_app_command("speed up") is AppCommand.SPEED_UP
    assert match_app_command("speed ten") == DialSetting("speed", 10)


def test_a_two_word_command_is_not_shadowed_by_its_first_word():
    # "next" walks the playlist and "next shape" turns a knob; the whole
    # utterance decides, so the shorter one never eats the longer.
    assert match_app_command("next") is AppCommand.FORWARD
    assert match_app_command("next shape") is AppCommand.NEXT_SHAPE


# --- the bank, and the app-wide switches ------------------------------------

@pytest.mark.parametrize("said, wanted", [
    ("undo", AppCommand.UNDO),
    ("redo", AppCommand.REDO),
    ("star", AppCommand.STAR),
    ("delete", AppCommand.CULL),
    ("group", AppCommand.GROUP),
])
def test_each_bank_button_has_a_word(said, wanted):
    assert match_app_command(said) is wanted


def test_a_switch_takes_a_flip_and_an_explicit_way():
    assert match_app_command("auto") is AppCommand.AUTO
    assert match_app_command("auto on") is AppCommand.AUTO_ON
    assert match_app_command("auto off") is AppCommand.AUTO_OFF
    assert match_app_command("drive off") is AppCommand.DRIVE_OFF
    assert match_app_command("audio on") is AppCommand.AUDIO_ON


def test_the_mic_can_be_shut_by_voice_but_not_opened():
    # A shut recognizer hears nothing, so there is no spoken way back — the same
    # reason Fun Time's mic has "voice off" and no "voice on".
    assert match_app_command("mic off") is AppCommand.MIC_OFF
    assert match_app_command("voice off") is AppCommand.MIC_OFF
    assert match_app_command("mic on") is None


def test_the_enhanced_filter_answers_to_upscales_as_well():
    # "Upscales" is what the enhanced pictures are called at the desk, so the
    # word turns the same switch on; the way back is the same "clear filter".
    for phrase in ("upscales", "upscales only", "filter upscales", "upscaled only"):
        assert match_app_command(phrase) is AppCommand.FILTER_ENHANCED, phrase


def test_the_show_filter_is_said_either_way_round_not_toggled():
    # A speaker mid-show is not looking at the console to see which way it is
    # set, so a single word that flipped it would do the opposite half the time.
    assert match_app_command("filter enhanced") is AppCommand.FILTER_ENHANCED
    assert match_app_command("enhanced only") is AppCommand.FILTER_ENHANCED
    assert match_app_command("clear filter") is AppCommand.FILTER_OFF
    assert match_app_command("no filter") is AppCommand.FILTER_OFF


def test_the_star_button_and_the_starred_shelf_are_different_words():
    assert match_app_command("star") is AppCommand.STAR
    assert match_app_command("starred") is AppCommand.STARRED


# --- what must NOT match: everything else steers a prompt --------------------

def test_whispers_punctuation_and_case_are_ignored():
    assert match_app_command("Weird!") is AppCommand.CULL
    assert match_app_command("  Lock. ") is AppCommand.LOCK


@pytest.mark.parametrize("said", [
    "a lock of hair over her eye",
    "the next one should be brighter",
    "star field behind her",
    "delete the harsh shadow",
    "she is standing on the trash heap",
])
def test_a_sentence_holding_a_command_word_is_a_prompt(said):
    # Every miss here is rewritten into the prompt instead, so the whole
    # utterance has to be the phrase — no leading or trailing words at all.
    assert match_app_command(said) is None


def test_an_empty_utterance_asks_for_nothing():
    assert match_app_command("") is None
    assert match_app_command(None) is None
    assert match_app_command("...") is None


# --- what whisper is told to expect -----------------------------------------

def test_the_bias_carries_every_word_the_vocabulary_uses():
    bias = app_command_bias()
    for word in ("experiments", "requests", "trash", "weird", "lock", "unlock",
                 "undo", "redo", "star", "cruise", "amp", "offset"):
        assert word in bias
    assert bias.endswith(".")


def test_the_bias_follows_the_vocabulary_rather_than_a_second_list():
    # Derived from the phrases, so a command added above reaches whisper with
    # nothing else to keep in step — and off a quiet mic a short imperative
    # whisper was not told to expect comes back as another word entirely.
    bias_words = set(app_command_bias().rstrip(".").split(": ", 1)[1].split(", "))
    for phrase in _PHRASES:
        for word in phrase.split():
            if word not in _BIAS_SKIP:
                assert word in bias_words


def test_the_skipped_words_are_only_ones_whisper_cannot_get_wrong():
    # The prompt has a hard budget (tests/test_voice_bias.py), so it is spent on
    # the odd words. What is skipped has to be genuinely ordinary — a command's
    # own name landing in here would be a command whisper was never told about.
    assert _BIAS_SKIP.isdisjoint(
        {"recents", "starred", "experiments", "requests", "trash", "weird",
         "unlock", "cruise", "offset", "amp", "center", "speed", "shape"}
    )


def test_every_command_has_at_least_one_word_that_reaches_it():
    # A command nobody can say is a command that does not exist.
    assert set(AppCommand) <= set(_PHRASES.values())


def test_every_dial_can_be_sent_to_every_stop_on_the_grid():
    # The grid is uniform on purpose: three dials, the same stops, both ends
    # named. A hole in it is a number that works on one dial and not another.
    reachable = {value for value in _PHRASES.values()
                 if isinstance(value, DialSetting)}
    assert reachable == {
        DialSetting(dial, stop)
        for dial in ("speed", "amp", "center")
        for stop in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
    }
