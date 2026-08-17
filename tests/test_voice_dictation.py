"""RequestDictation — collecting "Request … over" out of endpointed utterances.

Every vocabulary here is invented: the point is the markers and the shape of the
sentence between them, never any real prompt text.
"""

from origenerator.voice.dictation import (
    ABANDONED,
    COLLECTING,
    COMPLETED,
    OPENED,
    RequestDictation,
    request_bias,
)


def test_an_utterance_that_does_not_open_with_the_lead_word_is_not_ours():
    dictation = RequestDictation()
    assert dictation.push("a woman in a red coat") is None
    assert not dictation.listening


def test_a_whole_request_in_one_breath_completes_at_once():
    dictation = RequestDictation()

    spoken = dictation.push("Request, no silver earrings, over.")

    assert spoken.state == COMPLETED
    assert spoken.text == "no silver earrings"
    assert not dictation.listening


def test_a_request_spoken_across_pauses_is_collected_whole():
    # The mic endpoints on silence, so a sentence said with pauses arrives in
    # pieces; the request is the join of them, markers stripped.
    dictation = RequestDictation()

    opened = dictation.push("Request.")
    assert opened.state == OPENED and dictation.listening
    middle = dictation.push("no silver earrings")
    done = dictation.push("and more freckles. Over.")

    assert middle.state == COLLECTING
    assert done.state == COMPLETED and not dictation.listening
    assert done.text == "no silver earrings and more freckles"
    assert done.heard == "Request. no silver earrings and more freckles. Over."


def test_every_utterance_of_an_open_request_is_swallowed():
    # Which is what keeps the words of a request out of the prompt steering and
    # away from the "fix …" matcher: nothing in between falls through.
    dictation = RequestDictation()
    dictation.push("Request.")

    assert dictation.push("fix teeth") is not None
    assert dictation.push("a woman in a red coat") is not None


def test_over_only_ends_a_request_as_the_last_word():
    # "over" is an ordinary word mid-sentence and a sign-off at the end of one.
    dictation = RequestDictation()
    dictation.push("Request.")

    carrying_on = dictation.push("a blanket over her legs")
    assert carrying_on.state == COLLECTING

    assert dictation.push("and no hat. Over.").state == COMPLETED


def test_a_mangled_lead_word_still_opens_one():
    # Off a quiet mic the base model lands the shape and misses a letter.
    dictation = RequestDictation()

    assert dictation.push("Requesf, no hat, over.").state == COMPLETED


def test_a_request_that_never_hears_over_is_given_up_on():
    # Otherwise a missed terminator would swallow every later utterance for the
    # rest of the session, with nothing on screen to say why.
    dictation = RequestDictation(max_utterances=3)
    dictation.push("Request.")
    dictation.push("no hat")

    spoken = dictation.push("and more freckles")

    assert spoken.state == ABANDONED
    assert not dictation.listening
    assert dictation.push("a woman in a red coat") is None  # listening no more


def test_reset_drops_a_half_said_request():
    dictation = RequestDictation()
    dictation.push("Request.")

    dictation.reset()

    assert not dictation.listening
    assert dictation.push("no hat") is None


def test_a_request_with_nothing_between_the_markers_still_completes():
    # Empty, so the caller can say it didn't catch a term — rather than the
    # dictation staying open forever on a false start.
    dictation = RequestDictation()

    spoken = dictation.push("Request. Over.")

    assert spoken.state == COMPLETED
    assert spoken.text == ""


def test_the_bias_names_both_markers():
    # Whisper only lands the marker words off a quiet mic when told to expect
    # them, and the whole feature hangs on hearing exactly these two.
    bias = request_bias().lower()
    assert "request" in bias and "over" in bias
