from __future__ import annotations

from origenerator.voice.dictation import (
    ABANDONED,
    COLLECTING,
    COMPLETED,
    OPENED,
    RequestDictation,
    RequestState,
    request_bias,
    request_words,
    words_of,
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


def test_a_state_is_one_of_the_four_named_states_and_not_a_word():
    spoken = RequestDictation().push("Request, no silver earrings, over.")

    assert isinstance(spoken.state, RequestState)
    assert spoken.state != "completed"
    assert spoken.state.listening is False


def test_a_request_spoken_across_pauses_is_collected_whole():
    dictation = RequestDictation()

    opened = dictation.push("Request.")
    assert opened.state == OPENED
    assert dictation.listening
    middle = dictation.push("no silver earrings")
    done = dictation.push("and more freckles. Over.")

    assert middle.state == COLLECTING
    assert done.state == COMPLETED
    assert not dictation.listening
    assert done.text == "no silver earrings and more freckles"
    assert done.heard == "Request. no silver earrings and more freckles. Over."


def test_a_request_keeps_the_time_its_first_step_was_spoken():
    dictation = RequestDictation()

    opened = dictation.push("Request.", spoken_at=10.0)
    middle = dictation.push("no silver earrings", spoken_at=12.0)
    done = dictation.push("Over.", spoken_at=14.0)

    assert (opened.opened_at, middle.opened_at, done.opened_at) == (10.0, 10.0, 10.0)


def test_a_request_said_in_one_breath_keeps_the_time_it_was_spoken():
    done = RequestDictation().push("Request, no hat, over", spoken_at=7.5)

    assert done.state == COMPLETED
    assert done.opened_at == 7.5


def test_every_utterance_of_an_open_request_is_swallowed():
    dictation = RequestDictation()
    dictation.push("Request.")

    assert dictation.push("fix teeth") is not None
    assert dictation.push("a woman in a red coat") is not None


def test_over_only_ends_a_request_as_the_last_word():
    dictation = RequestDictation()
    dictation.push("Request.")

    carrying_on = dictation.push("a blanket over her legs")
    assert carrying_on.state == COLLECTING, (
        "over is radio's own word for it, chosen because nothing in a prompt ends on it by "
        "accident")

    assert dictation.push("and no hat. Over.").state == COMPLETED


def test_a_mangled_lead_word_still_opens_one():
    dictation = RequestDictation()

    spoken = dictation.push("Requesf, no hat, over.")

    assert getattr(spoken, "state", None) == COMPLETED, (
        "\"request\" is distinctive enough that one slip is safe, the same tolerance the fix"
        " commands allow their lead word")


def test_a_request_that_never_hears_over_is_given_up_on():
    dictation = RequestDictation(max_utterances=3)
    dictation.push("Request.")
    dictation.push("no hat")

    spoken = dictation.push("and more freckles")

    assert spoken.state == ABANDONED, (
        "the failure this guards is the over being missed: without a cap the dictation would "
        "swallow every later utterance for the rest of the session, and the user would have no "
        "way to tell why nothing said was landing")
    assert not dictation.listening
    assert dictation.push("a woman in a red coat") is None


def test_the_shipped_limit_gives_up_after_eight_utterances():
    dictation = RequestDictation()
    assert dictation.push("Request.").state == OPENED
    for _ in range(6):
        assert dictation.push("and another clause").state == COLLECTING

    assert dictation.push("and one more").state == ABANDONED, (
        "the limit the app ships with, counted out here: read off the constant, a limit of a hundred "
        "would pass just as well")


def test_reset_drops_a_half_said_request():
    dictation = RequestDictation()
    dictation.push("Request.")

    dictation.reset()

    assert not dictation.listening
    assert dictation.push("no hat") is None


def test_a_request_with_nothing_between_the_markers_still_completes():
    dictation = RequestDictation()

    spoken = dictation.push("Request. Over.")

    assert spoken.state == COMPLETED
    assert spoken.text == ""


def test_what_was_heard_reads_back_as_the_request_alone():
    assert request_words("Request, no silver earrings, over.") == "no silver earrings"
    assert request_words("Request. a red coat. Over.") == "a red coat"


def test_a_record_s_words_are_its_own_else_what_was_heard_between_the_markers():
    assert words_of({"asked": "two women", "heard": ""}) == "two women"
    assert words_of({"asked": None, "heard": "Request, no hat, over."}) == "no hat", (
        "a record from before the words were kept reads them back out of what was heard")
    assert words_of({"asked": None, "heard": ""}) == ""
    assert words_of(None) == ""


def test_the_bias_names_both_markers():
    bias = request_bias().lower()
    assert "request" in bias
    assert "over" in bias
