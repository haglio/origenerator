"""What a spoken utterance over a fullscreen picture is taken to mean.

Two commands share one mic, so the matcher has to keep them apart and keep both
away from prompt steering — everything it does not match is rewritten into the
prompt instead, which is why a loose match would be worse than a miss.
"""

from origenerator import gallery
from origenerator.gallery import voice_commands


def test_the_sound_alike_fun_time_settled_on_is_what_it_listens_for():
    # No recognizer in this suite hears "genau"; Fun Time uses "go now" for every
    # one of its Genau commands and displays it back as "genau".
    assert voice_commands.match_genau_command("go now") == voice_commands.GENAU_COMMAND
    assert voice_commands.match_genau_command("Go now, it!") == voice_commands.GENAU_COMMAND


def test_the_word_itself_and_its_near_misses_also_count():
    # Whisper is a looser transcriber than Fun Time's vosk grammar, so the spelling
    # and every rendering it has actually come back with ride alongside the
    # sound-alike — each of these was heard off this mic.
    for heard in ("genau it", "genow it", "ganau", "gunow it",
                  "good now it", "can now it", "canow it"):
        assert voice_commands.match_genau_command(heard) == voice_commands.GENAU_COMMAND


def test_the_renderings_that_are_ordinary_english_claim_nothing_longer():
    # "good now" and "can now" are things someone might say to an image
    # generator, so the trailing-word limit is what keeps them commands rather
    # than a claim on a sentence.
    assert voice_commands.match_genau_command("good now make her hair longer") is None
    assert voice_commands.match_genau_command("can now be a windy day") is None


def test_one_word_past_the_phrase_is_all_a_command_may_carry():
    # The two negatives above are four words past the lead, so a limit of three
    # reads the same as a limit of one — and a mis-heard "genau it now please"
    # would fire a generation nobody asked for. This is the pair either side of
    # the line: "it" is the one word these commands take.
    assert voice_commands.match_genau_command("genau it") == voice_commands.GENAU_COMMAND
    assert voice_commands.match_genau_command("genau it now") is None
    assert voice_commands.match_genau_command("good now it") == voice_commands.GENAU_COMMAND
    assert voice_commands.match_genau_command("good now it again") is None
    assert voice_commands.match_enhance_command("enhance it") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_enhance_command("enhance it more") is None


def test_a_sentence_merely_mentioning_it_is_not_a_command():
    # Far more likely a prompt edit that names the tool than an order to run it,
    # and the cost of being wrong is a generation nobody asked for.
    assert voice_commands.match_genau_command("make this one a genau clip later") is None
    assert voice_commands.match_genau_command("genau it as soon as you can") is None
    assert voice_commands.match_genau_command("we should go now and eat") is None
    assert voice_commands.match_genau_command("") is None
    assert voice_commands.match_genau_command(None) is None


def test_the_three_commands_do_not_shadow_each_other():
    (fix,) = voice_commands.match_command("fix teeth")
    assert fix.name == "teeth"
    assert voice_commands.match_command("genau it") == voice_commands.GENAU_COMMAND
    assert voice_commands.match_command("enhance") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_command("make her hair longer") is None


def test_a_fix_that_names_no_part_falls_through_like_any_other_miss():
    # The empty tuple a partless "fix" comes back as must not reach the mic as a
    # command — everything unmatched is a prompt rewrite, and this is one.
    assert voice_commands.match_command("fix the lighting") is None


def test_the_bias_offers_whisper_every_command_word():
    bias = voice_commands.command_bias()
    for phrase in voice_commands.GENAU_PHRASES:
        assert phrase in bias
    assert "fix" in bias      # the older command's vocabulary is still in there
    assert bias.endswith(".")


def test_the_gallery_facade_exposes_the_one_matcher():
    # What the voice surface is actually given; a verb added to the module has to
    # reach it without the caller changing.
    assert gallery.match_command("genau it") == gallery.GENAU_COMMAND
    assert gallery.match_command("enhance") == gallery.ENHANCE_COMMAND
    assert gallery.command_bias() == voice_commands.command_bias()


def test_enhance_asks_for_the_better_version_of_what_is_on_screen():
    assert voice_commands.match_enhance_command("enhance") == voice_commands.ENHANCE_COMMAND
    assert voice_commands.match_enhance_command("Enhance it!") == voice_commands.ENHANCE_COMMAND


def test_whisper_is_offered_the_enhance_word_too():
    # Off a quiet mic a short imperative is mangled unless the transcriber is
    # told to expect it, which is what actually made "fix <part>" land.
    bias = voice_commands.command_bias()
    for phrase in voice_commands.ENHANCE_PHRASES:
        assert phrase in bias


def test_a_sentence_that_merely_wants_something_nicer_is_not_the_command():
    # Everything unmatched falls through to a prompt rewrite, and "enhance the
    # lighting" is one of those — a command is the word and nothing more.
    assert voice_commands.match_enhance_command("enhance the lighting on her face") is None
    assert voice_commands.match_enhance_command("make her dress more enhanced") is None
    assert voice_commands.match_enhance_command("") is None
    assert voice_commands.match_enhance_command(None) is None


# --- saying an utterance back in the words it was recognized as --------------


def test_a_mangled_command_is_said_back_in_the_word_the_app_knows_it_by():
    # The whole complaint: a caption printed "gunow it" and then went and made a
    # Genau clip, so the spelling on screen was the one thing that had not been
    # understood.
    for heard in ("gunow it", "go now it", "genow it", "Genau it!",
                  "Good now it.", "can now it", "canow it"):
        assert voice_commands.recognized_spelling(heard) == "Genau it"
    assert voice_commands.recognized_spelling("ganau") == "Genau"


def test_every_command_has_its_own_spelling():
    assert voice_commands.recognized_spelling("Enhanced!") == "enhance"
    assert voice_commands.recognized_spelling("six-teeth.") == "fix teeth"


def test_what_is_no_command_is_left_exactly_as_it_was_heard():
    # Everything unmatched is a prompt edit, and a prompt edit that mentions a
    # command word is still the speaker's own sentence.
    assert voice_commands.recognized_spelling("make this one a genau clip later") is None
    assert voice_commands.recognized_spelling("make her hair longer") is None
    assert voice_commands.recognized_spelling("") is None
    assert voice_commands.recognized_spelling(None) is None


def test_the_spelling_answers_exactly_what_the_matcher_claims():
    # A respelled caption promises the command is about to run, so the two have
    # to agree utterance for utterance.
    for heard in ("gunow it", "enhanced", "fix hands and mouth", "fix the lighting",
                  "make her hair longer", "we should go now and eat", ""):
        assert (voice_commands.recognized_spelling(heard) is not None) == (
            bool(voice_commands.match_command(heard)))


def test_the_gallery_facade_exposes_the_spelling_too():
    # The voice surface is given the matcher through the facade and reads the
    # caption's words from the same place.
    assert gallery.recognized_spelling("gunow it") == "Genau it"
