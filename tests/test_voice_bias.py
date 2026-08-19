"""The initial prompt handed to whisper, and the budget it has to fit in.

Every spoken vocabulary teaches the transcriber its own words up front, and the
four of them are handed over as one string. That string is whisper's
``initial_prompt``, which has a hard ceiling: faster-whisper keeps the LAST
``max_length // 2 - 1`` tokens of it — 223 on every model this app runs — and
drops the rest with no error and no log line. The head is where the fix
vocabulary sits, and the fix vocabulary is the half that most needs the hint
(off a quiet mic "fix teeth" comes back "thick stick" without it), so an
overflow costs exactly the words the bias exists for, silently.

Nothing here can ask whisper how long the string is: the voice extra is
deliberately not installed for the suite (see ``.github/workflows/merge-gate.yml``),
so there is no tokenizer to count with. It counts characters instead, against a
ratio measured on the real tokenizer — the guard is approximate on purpose, and
it is the tripwire rather than the answer: a vocabulary addition that fails here
has not necessarily overflowed, it has spent the margin that says it hasn't.
"""

from origenerator.gallery import voice_commands as gallery
from origenerator.voice.app_commands import app_command_bias
from origenerator.voice.dictation import request_bias
from origenerator.voice.show_commands import show_command_bias

# What faster-whisper keeps of an initial prompt: ``max_length // 2 - 1``, and
# max_length is 448 on tiny through large.
_WHISPER_PROMPT_TOKENS = 223

# Measured against faster-whisper's own tokenizer on this exact bias (2026-08-19):
# 682 characters encoded to 199 tokens, 0.292 tokens per character. Rounded up to
# 0.30 so the estimate errs toward failing early rather than passing an overflow.
_TOKENS_PER_CHAR = 0.30


def assembled_bias() -> str:
    """The one string :class:`~origenerator.gui.gallery_view.GalleryView` builds
    and hands the transcriber, assembled the same way it assembles it."""
    return (f"{gallery.command_bias()} {show_command_bias()} "
            f"{app_command_bias()} {request_bias()}")


def test_every_vocabulary_fits_in_the_prompt_whisper_will_actually_read():
    estimate = len(assembled_bias()) * _TOKENS_PER_CHAR
    assert estimate <= _WHISPER_PROMPT_TOKENS, (
        f"the bias is about {estimate:.0f} tokens against whisper's "
        f"{_WHISPER_PROMPT_TOKENS}-token prompt, and what overflows is dropped "
        "from the FRONT — the fix vocabulary. Say fewer words for it, or "
        "re-measure the ratio above with faster-whisper's tokenizer."
    )


def test_the_bias_carries_the_words_a_transcriber_would_otherwise_miss():
    # The point of spending the budget: the odd words, not the ordinary ones.
    bias = assembled_bias()
    for word in ("genau", "recents", "amp", "cruise", "offset", "slideshow"):
        assert word in bias


def test_the_budget_is_not_spent_on_words_whisper_already_knows():
    # Numbers and connectives ride in the phrases without riding in the bias:
    # whisper has never mis-heard "fifty", and a word listed here is a word not
    # listed for something that would have been mis-heard.
    words = app_command_bias().split()
    for ordinary in ("fifty,", "fifty", "50,", "50", "min,", "max,", "to,", "it,"):
        assert ordinary not in words
