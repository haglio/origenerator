"""The bare spoken vocabulary — a shelf, a button, an order to the slide.

One word is the whole utterance or it is nothing, because everything this
matcher declines is rewritten into a prompt instead: a loose match here would
spend a command on a sentence, and a loose miss would put a command word into
the picture.
"""

import pytest

from origenerator.voice.app_commands import (
    _PHRASES, AppCommand, app_command_bias, match_app_command,
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
            assert word in bias_words


def test_every_command_has_at_least_one_word_that_reaches_it():
    # A command nobody can say is a command that does not exist.
    assert set(_PHRASES.values()) == set(AppCommand)
