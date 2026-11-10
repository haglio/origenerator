from __future__ import annotations

import pytest

from origenerator.gallery.collection import FAVORITES_KEY
from origenerator.voice.app_commands import (
    _PHRASES,
    AppCommand,
    BarSetting,
    _say,
    match_app_command,
    phrases_heard_only_outright,
    spoken_phrases,
)
from origenerator.voice.commands import CollectionCommand, match_voice_command


@pytest.mark.parametrize(("said", "wanted"), [
    ("experiments", AppCommand.EXPERIMENTS),
    ("recents", AppCommand.LATEST),
])
def test_a_collection_answers_to_its_own_bare_name(said, wanted):
    assert match_app_command(said) is wanted


@pytest.mark.parametrize("said", ["go to experiments", "open experiments",
                                  "show experiments", "experiments collection"])
def test_a_collection_also_answers_to_a_sentence_shaped_ask(said):
    assert match_app_command(said) is AppCommand.EXPERIMENTS


def test_the_words_fun_times_funestras_answer_to_mean_the_same_here():
    assert match_app_command("trash") is AppCommand.CULL
    assert match_app_command("lock") is AppCommand.LOCK
    assert match_app_command("unlock") is AppCommand.UNLOCK
    assert match_app_command("next") is AppCommand.FORWARD
    assert match_app_command("previous") is AppCommand.BACK
    assert match_app_command("skip") is AppCommand.FORWARD
    assert match_app_command("back") is AppCommand.BACK


def test_the_motion_bars_keep_fun_times_phrases():
    assert match_app_command("speed up") is AppCommand.SPEED_UP
    assert match_app_command("slow down") is AppCommand.SPEED_DOWN
    assert match_app_command("amp down") is AppCommand.AMP_DOWN
    assert match_app_command("center up") is AppCommand.CENTER_UP


def test_human_inspired_motion_answers_a_flip_and_an_explicit_on_and_off():
    assert match_app_command("human inspired") is AppCommand.LEARNED
    assert match_app_command("human inspired on") is AppCommand.LEARNED_ON
    assert match_app_command("human inspired off") is AppCommand.LEARNED_OFF


@pytest.mark.parametrize("said", ["cruise", "cruise control", "cruise on", "cruise off"])
def test_cruise_control_is_no_word_here(said):
    assert match_app_command(said) is None


@pytest.mark.parametrize(("said", "wanted"), [
    ("amp fifty", BarSetting("amp", 50)),
    ("speed thirty", BarSetting("speed", 30)),
    ("center seventy", BarSetting("center", 70)),
    ("speed zero", BarSetting("speed", 0)),
    ("amp one hundred", BarSetting("amp", 100)),
])
def test_a_bar_takes_the_number_said(said, wanted):
    assert match_app_command(said) == wanted, (
        "the nudges walk a bar five at a time, and from the far end arriving takes a dozen "
        "utterances, so a bar also takes the number said plainly")


@pytest.mark.parametrize(("said", "wanted"), [
    ("min speed", BarSetting("speed", 0)),
    ("max speed", BarSetting("speed", 100)),
    ("min amp", BarSetting("amp", 0)),
    ("max amp", BarSetting("amp", 100)),
    ("min center", BarSetting("center", 0)),
    ("max center", BarSetting("center", 100)),
])
def test_both_ends_of_a_bar_have_a_name(said, wanted):
    assert match_app_command(said) == wanted


@pytest.mark.parametrize("said", ["amp 50", "Amp 50.", "amp fifty"])
def test_a_number_counts_whether_whisper_wrote_it_in_words_or_digits(said):
    assert match_app_command(said) == BarSetting("amp", 50)


def test_the_nudges_still_outrank_the_grid_they_sit_beside():
    assert match_app_command("speed up") is AppCommand.SPEED_UP
    assert match_app_command("speed ten") == BarSetting("speed", 10)


def test_a_two_word_command_is_not_shadowed_by_its_first_word():
    assert match_app_command("next") is AppCommand.FORWARD
    assert match_app_command("next shape") is AppCommand.NEXT_SHAPE


@pytest.mark.parametrize(("said", "wanted"), [
    ("undo", AppCommand.UNDO),
    ("redo", AppCommand.REDO),
    ("favorite", AppCommand.FAVORITE),
    ("favorite it", AppCommand.FAVORITE),
    ("favorite this", AppCommand.FAVORITE),
    ("delete", AppCommand.CULL),
    ("group", AppCommand.GROUP),
])
def test_each_bank_button_has_a_word(said, wanted):
    assert match_app_command(said) is wanted


def test_a_switch_takes_a_flip_and_an_explicit_way():
    assert match_app_command("populate") is AppCommand.POPULATE
    assert match_app_command("populate on") is AppCommand.POPULATE_ON, (
        "a speaker who knows which way they want it never has to look first")
    assert match_app_command("populate off") is AppCommand.POPULATE_OFF
    assert match_app_command("drive off") is AppCommand.DRIVE_OFF
    assert match_app_command("radio on") is AppCommand.RADIO_ON


@pytest.mark.parametrize("said", [
    "OSR2 off", "OSR 2 off", "O.S.R. 2 off", "OSR two off", "O S R two off",
])
def test_the_osr2_is_let_go_of_in_fun_times_words(said):
    assert match_app_command(said) is AppCommand.DRIVE_OFF


@pytest.mark.parametrize(("said", "command"), [
    ("OSR2 control off", AppCommand.DRIVE_OFF), ("OSR two control off", AppCommand.DRIVE_OFF),
    ("OSR2 control on", AppCommand.DRIVE_ON), ("O S R two control on", AppCommand.DRIVE_ON),
])
def test_osr2_control_is_the_switch_by_the_name_its_label_gives_it(said, command):
    assert match_app_command(said) is command


def test_the_mic_can_be_shut_by_voice_but_not_opened():
    assert match_app_command("mic off") is AppCommand.MIC_OFF
    assert match_app_command("voice off") is AppCommand.MIC_OFF
    assert match_app_command("mic on") is None


def test_the_enhanced_filter_answers_to_upscales_as_well():
    for phrase in ("upscales", "upscales only", "filter upscales", "upscaled only"):
        assert match_app_command(phrase) is AppCommand.FILTER_ENHANCED, phrase


def test_the_slideshow_filter_is_said_either_way_round_not_toggled():
    assert match_app_command("filter enhanced") is AppCommand.FILTER_ENHANCED, (
        "a speaker in a slideshow is not looking at the HUD to see which way it is set, and a "
        "phrase that turned the filter off half the time is one nobody could rely on")
    assert match_app_command("enhanced only") is AppCommand.FILTER_ENHANCED
    assert match_app_command("clear filter") is AppCommand.FILTER_OFF
    assert match_app_command("no filter") is AppCommand.FILTER_OFF


def test_original_only_and_enhanced_and_original_are_said_as_fun_time_says_them():
    assert match_app_command("original only") is AppCommand.FILTER_ORIGINALS
    assert match_app_command("enhanced and original") is AppCommand.ENHANCED_AND_ORIGINAL
    assert match_app_command("original and enhanced") is AppCommand.ENHANCED_AND_ORIGINAL


def test_marking_a_favorite_and_standing_in_the_favorites_collection_are_different_words():
    assert match_app_command("favorite") is AppCommand.FAVORITE
    assert match_app_command("go to favorites") is AppCommand.FAVORITES
    assert match_app_command("favorites collection") is AppCommand.FAVORITES


def test_favorites_on_its_own_is_left_to_the_order_that_plays_the_collection():
    assert match_app_command("favorites") is None
    assert match_voice_command("favorites") == CollectionCommand(FAVORITES_KEY, None)


def test_whispers_punctuation_and_case_are_ignored():
    assert match_app_command("Trash!") is AppCommand.CULL
    assert match_app_command("  Lock. ") is AppCommand.LOCK


@pytest.mark.parametrize("said", [
    "a lock of hair over her eye",
    "the next one should be brighter",
    "star field around her",
    "delete the harsh shadow",
    "she is standing on the trash heap",
])
def test_a_sentence_holding_a_command_word_is_no_command(said):
    assert match_app_command(said) is None


def test_an_empty_utterance_asks_for_nothing():
    assert match_app_command("") is None
    assert match_app_command(None) is None
    assert match_app_command("...") is None


def test_the_recognizer_is_asked_to_hear_every_way_a_command_is_said_in_words():
    heard = spoken_phrases()
    for phrase in ("experiments", "go to experiments", "trash", "favorite it", "go to favorites",
                   "populate on",
                   "mic off", "o s r two off", "clear filter", "slow down",
                   "human inspired off", "amp fifty", "center one hundred", "max speed"):
        assert phrase in heard


def test_taking_an_item_away_and_shutting_the_mic_are_heard_only_when_said_outright():
    assert phrases_heard_only_outright() == {
        "mic off", "voice off", "trash", "delete", "delete it"}, (
        "a near miss is never repaired into these two: the switch with no spoken way back, and "
        "the word that takes an item away")


def test_a_number_in_digits_is_how_whisper_writes_it_not_something_to_listen_for():
    assert not [phrase for phrase in spoken_phrases() if any(c.isdigit() for c in phrase)]


def test_every_phrase_the_recognizer_is_asked_to_hear_is_a_command():
    assert {phrase for phrase in spoken_phrases() if match_app_command(phrase) is None} == set()
    assert {match_app_command(phrase) for phrase in spoken_phrases()} == set(_PHRASES.values())


def test_every_command_has_at_least_one_word_that_reaches_it():
    assert set(AppCommand) <= set(_PHRASES.values())


def test_every_bar_can_be_sent_to_every_stop_on_the_grid():
    reachable = {value for value in _PHRASES.values()
                 if isinstance(value, BarSetting)}
    assert reachable == {
        BarSetting(bar, stop)
        for bar in ("speed", "amp", "center")
        for stop in (0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100)
    }, (
        "tens only: a bar is a feel rather than a figure, and nobody says amp fifty five")


def test_a_phrase_cannot_mean_two_things():
    said = {}
    _say(AppCommand.BACK, "step out", said=said)

    with pytest.raises(RuntimeError):
        _say(AppCommand.FORWARD, "step out", said=said)


def test_two_equal_bar_settings_built_apart_agree_rather_than_collide():
    said = {}
    _say(BarSetting("speed", 0), "speed zero", said=said)

    _say(BarSetting("speed", 0), "speed zero", said=said)
