from __future__ import annotations

from origenerator.gui.request_promise import RequestPromise


def test_a_promise_is_kept_by_the_answer_to_its_own_request():
    promise = RequestPromise()
    asked = object()
    promise.make("Working it out…", asked)

    assert promise.keep(asked) == "Working it out…"
    assert promise.note == ""


def test_an_answer_to_another_request_leaves_the_promise_standing():
    promise = RequestPromise()
    asked = object()
    promise.make("Working it out…", asked)

    assert promise.keep(object()) == ""
    assert promise.note == "Working it out…"


def test_nothing_is_promised_until_a_request_is_being_worked_out():
    assert RequestPromise().note == ""
