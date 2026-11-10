from __future__ import annotations

from origenerator import gallery
from origenerator.gallery import voice_commands


def test_one_word_past_the_phrase_is_all_a_command_may_carry():
    assert voice_commands.match_enhance_command("enhance it") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_enhance_command("enhance it more") is None


def test_a_sentence_merely_mentioning_it_is_not_a_command():
    assert voice_commands.match_enhance_command("enhance this one later on") is None, (
        "a loose match is worse than a miss here: a sentence that only mentions the command "
        "would start a generation nobody asked for")
    assert voice_commands.match_enhance_command("") is None
    assert voice_commands.match_enhance_command(None) is None


def test_the_three_commands_do_not_shadow_each_other():
    (fix,) = voice_commands.match_command("fix teeth")
    assert fix.name == "teeth"
    assert voice_commands.match_command("animate as video alpha").action == "alpha"
    assert voice_commands.match_command("enhance") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_command("make her hair longer") is None


def test_a_fix_that_names_no_part_falls_through_like_any_other_miss():
    assert voice_commands.match_command("fix the lighting") is None


def test_the_recognizer_is_asked_to_hear_every_command_about_the_image():
    heard = voice_commands.command_phrases()
    for phrase in ("enhance", "enhance it", "fix teeth", "fix all",
                   "animate as alpha", "animate as go now alpha"):
        assert phrase in heard
    assert [phrase for phrase in heard if voice_commands.match_command(phrase) is None] == []


def test_the_gallery_facade_exposes_the_one_matcher():
    assert gallery.match_command("enhance") == gallery.ENHANCE_COMMAND
    assert gallery.match_command("animate as video alpha").action == "alpha"
    assert gallery.command_phrases() == voice_commands.command_phrases()


def test_enhance_asks_for_the_better_version_of_what_is_on_screen():
    assert voice_commands.match_enhance_command("enhance") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_enhance_command("Enhance it!") == voice_commands.ENHANCE_COMMAND


def test_a_sentence_that_merely_wants_something_nicer_is_not_the_command():
    assert voice_commands.match_enhance_command("enhance the lighting on her face") is None
    assert voice_commands.match_enhance_command("make her dress more enhanced") is None
    assert voice_commands.match_enhance_command("") is None
    assert voice_commands.match_enhance_command(None) is None



def test_a_mangled_command_is_said_back_in_the_word_the_app_knows_it_by():
    assert voice_commands.recognized_spelling("Enhanced it!") == "enhance it", (
        "the recognizer offers the past tense about as readily off a quiet mic, so it is taken "
        "for the command; nothing looser is, since a sentence may well open with the word")


def test_every_command_has_its_own_spelling():
    assert voice_commands.recognized_spelling("Enhanced!") == "enhance"
    assert voice_commands.recognized_spelling("six-teeth.") == "fix teeth"


def test_what_is_no_command_is_left_exactly_as_it_was_heard():
    assert voice_commands.recognized_spelling("enhance this one later on") is None
    assert voice_commands.recognized_spelling("make her hair longer") is None
    assert voice_commands.recognized_spelling("") is None
    assert voice_commands.recognized_spelling(None) is None


def test_the_spelling_answers_exactly_what_the_matcher_claims():
    for heard in ("enhanced", "animate as alpha", "fix hands and mouth",
                  "fix the lighting", "make her hair longer", ""):
        assert (voice_commands.recognized_spelling(heard) is not None) == (
            bool(voice_commands.match_command(heard)))


def test_the_gallery_facade_exposes_the_spelling_too():
    assert gallery.recognized_spelling("Enhanced it!") == "enhance it"


def test_the_genau_lane_is_said_in_german_and_nothing_else_is():
    heard = voice_commands.command_phrases()
    naming_the_lane = {phrase for phrase in heard if "go now" in phrase}

    assert naming_the_lane
    assert {voice_commands.said_in(phrase) for phrase in naming_the_lane} == {"de"}
    assert {voice_commands.said_in(phrase)
            for phrase in heard - naming_the_lane} == {None}
