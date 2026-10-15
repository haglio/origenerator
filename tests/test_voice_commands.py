"""What a spoken utterance over a fullscreen picture is taken to mean.

Three commands share one mic, so the matcher has to keep them apart and keep all
of them away from prompt steering — everything it does not match is rewritten
into the prompt instead, which is why a loose match would be worse than a miss.
"""
from __future__ import annotations

from origenerator import gallery
from origenerator.gallery import voice_commands


def test_one_word_past_the_phrase_is_all_a_command_may_carry():
    # A mis-heard "enhance it now please" would fire a generation nobody asked
    # for. This is the pair either side of the line: "it" is the one word a
    # command that takes no argument carries.
    assert voice_commands.match_enhance_command("enhance it") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_enhance_command("enhance it more") is None


def test_a_sentence_merely_mentioning_it_is_not_a_command():
    # Far more likely a prompt edit that names the tool than an order to run it,
    # and the cost of being wrong is a generation nobody asked for.
    assert voice_commands.match_enhance_command("enhance this one later on") is None
    assert voice_commands.match_enhance_command("") is None
    assert voice_commands.match_enhance_command(None) is None


def test_the_three_commands_do_not_shadow_each_other():
    (fix,) = voice_commands.match_command("fix teeth")
    assert fix.name == "teeth"
    assert voice_commands.match_command("animate as video alpha").act == "alpha"
    assert voice_commands.match_command("enhance") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_command("make her hair longer") is None


def test_a_fix_that_names_no_part_falls_through_like_any_other_miss():
    # The empty tuple a partless "fix" comes back as must not reach the mic as a
    # command — everything unmatched is a prompt rewrite, and this is one.
    assert voice_commands.match_command("fix the lighting") is None


def test_the_recognizer_is_asked_to_hear_every_command_about_the_picture():
    heard = voice_commands.command_phrases()
    for phrase in ("enhance", "enhance it", "fix teeth", "fix all",
                   "animate as alpha", "animate as go now alpha"):
        assert phrase in heard
    assert [phrase for phrase in heard if voice_commands.match_command(phrase) is None] == []


def test_the_gallery_facade_exposes_the_one_matcher():
    # What the voice surface is actually given; a verb added to the module has to
    # reach it without the caller changing.
    assert gallery.match_command("enhance") == gallery.ENHANCE_COMMAND
    assert gallery.match_command("animate as video alpha").act == "alpha"
    assert gallery.command_phrases() == voice_commands.command_phrases()


def test_enhance_asks_for_the_better_version_of_what_is_on_screen():
    assert voice_commands.match_enhance_command("enhance") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_enhance_command("Enhance it!") == voice_commands.ENHANCE_COMMAND


def test_a_sentence_that_merely_wants_something_nicer_is_not_the_command():
    # Everything unmatched falls through to a prompt rewrite, and "enhance the
    # lighting" is one of those — a command is the word and nothing more.
    assert voice_commands.match_enhance_command("enhance the lighting on her face") is None
    assert voice_commands.match_enhance_command("make her dress more enhanced") is None
    assert voice_commands.match_enhance_command("") is None
    assert voice_commands.match_enhance_command(None) is None


# --- saying an utterance back in the words it was recognized as --------------


def test_a_mangled_command_is_said_back_in_the_word_the_app_knows_it_by():
    # The whole complaint: a caption printed what the mic heard and then ran the
    # command anyway, so the spelling on screen was the one thing that had not
    # been understood.
    assert voice_commands.recognized_spelling("Enhanced it!") == "enhance it"


def test_every_command_has_its_own_spelling():
    assert voice_commands.recognized_spelling("Enhanced!") == "enhance"
    assert voice_commands.recognized_spelling("six-teeth.") == "fix teeth"


def test_what_is_no_command_is_left_exactly_as_it_was_heard():
    # Everything unmatched is a prompt edit, and a prompt edit that mentions a
    # command word is still the speaker's own sentence.
    assert voice_commands.recognized_spelling("enhance this one later on") is None
    assert voice_commands.recognized_spelling("make her hair longer") is None
    assert voice_commands.recognized_spelling("") is None
    assert voice_commands.recognized_spelling(None) is None


def test_the_spelling_answers_exactly_what_the_matcher_claims():
    # A respelled caption promises the command is about to run, so the two have
    # to agree utterance for utterance.
    for heard in ("enhanced", "animate as alpha", "fix hands and mouth",
                  "fix the lighting", "make her hair longer", ""):
        assert (voice_commands.recognized_spelling(heard) is not None) == (
            bool(voice_commands.match_command(heard)))


def test_the_gallery_facade_exposes_the_spelling_too():
    # The voice surface is given the matcher through the facade and reads the
    # caption's words from the same place.
    assert gallery.recognized_spelling("Enhanced it!") == "enhance it"


def test_the_genau_lane_is_said_in_german_and_nothing_else_is():
    """What lets a mangled hearing of the lane be read once more in German before
    it is doubted; the acts after it are English and must not be."""
    heard = voice_commands.command_phrases()
    naming_the_lane = {phrase for phrase in heard if "go now" in phrase}

    assert naming_the_lane
    assert {voice_commands.said_in(phrase) for phrase in naming_the_lane} == {"de"}
    assert {voice_commands.said_in(phrase)
            for phrase in heard - naming_the_lane} == {None}
