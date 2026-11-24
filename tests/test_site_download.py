from __future__ import annotations

import urllib.error
from functools import partial

import pytest
from app_support.threading_utils import wait_until

from origenerator.site_download import downloaded

ADDRESS = "https://example.com/made/a"

without_waiting = partial(wait_until, sleep=lambda _seconds: None)


def _refusal(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(ADDRESS, code, "made up", None, None)


def _answering(*answers):
    waiting, asked = list(answers), []

    def fetch(address: str) -> bytes:
        asked.append(address)
        answer = waiting.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    return fetch, asked


def test_an_image_the_site_has_not_put_up_yet_is_asked_for_again_until_it_is_there():
    fetch, asked = _answering(_refusal(404), _refusal(404), b"the image")

    assert downloaded(ADDRESS, fetch=fetch, until=without_waiting) == b"the image"
    assert asked == [ADDRESS] * 3


def test_any_other_refusal_is_not_waited_out():
    fetch, asked = _answering(_refusal(403), b"the image")

    with pytest.raises(urllib.error.HTTPError):
        downloaded(ADDRESS, fetch=fetch, until=without_waiting)
    assert asked == [ADDRESS]


def test_an_image_that_never_appears_stops_being_waited_for():
    def never(_condition, **_how):
        raise TimeoutError

    with pytest.raises(TimeoutError):
        downloaded(ADDRESS, fetch=_answering()[0], until=never)
