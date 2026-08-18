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
    # and a couple of renderings ride alongside the sound-alike.
    for heard in ("genau it", "genow it", "ganau", "gunow it"):
        assert voice_commands.match_genau_command(heard) == voice_commands.GENAU_COMMAND


def test_a_sentence_merely_mentioning_it_is_not_a_command():
    # Far more likely a prompt edit that names the tool than an order to run it,
    # and the cost of being wrong is a generation nobody asked for.
    assert voice_commands.match_genau_command("make this one a genau clip later") is None
    assert voice_commands.match_genau_command("genau it as soon as you can") is None
    assert voice_commands.match_genau_command("we should go now and eat") is None
    assert voice_commands.match_genau_command("") is None
    assert voice_commands.match_genau_command(None) is None


def test_the_two_commands_do_not_shadow_each_other():
    fix = voice_commands.match_command("fix teeth")
    assert fix is not None and fix is not voice_commands.GENAU_COMMAND
    assert voice_commands.match_command("genau it") == voice_commands.GENAU_COMMAND
    assert voice_commands.match_command("make her hair longer") is None


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
    assert gallery.command_bias() == voice_commands.command_bias()
