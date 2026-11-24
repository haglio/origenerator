from __future__ import annotations

import json
from functools import partial

import pytest
from app_support.threading_utils import wait_until

from origenerator.site_chrome import ChromeRefused
from origenerator.site_generation import (
    CHROME_FAILED,
    NEVER_ANSWERED,
    SIGNED_OUT,
    WINDOW_CLOSED,
    Made,
    Site,
    SiteRefused,
    made_on,
)

ADDRESS = "https://example.com/create#ft=made-up"
SCRIPT = "// a made-up fill script"

without_waiting = partial(wait_until, sleep=lambda _seconds: None)


def never(_condition, **_how):
    raise TimeoutError


class FakePage:
    def __init__(self, *, answers=(), signed_out=()):
        self.did: list[tuple[str, str]] = []
        self._answers = list(answers)
        self._signed_out = list(signed_out)
        self.loaded = True

    def go_to(self, address: str) -> None:
        self.did.append(("go to", address))

    def run(self, script: str) -> None:
        self.did.append(("run", script))

    def read(self, expression: str):
        if "about:blank" in expression:
            self.did.append(("left the last page", ""))
            return True
        if "readyState" in expression:
            return self.loaded
        if "funTimeMade" in expression:
            answer = self._answers.pop(0) if self._answers else None
            return json.dumps(answer)
        answer = self._signed_out.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


def test_an_image_is_made_by_filling_the_page_and_reading_what_it_says_it_made():
    page = FakePage(answers=[None, None, {"image": "https://example.com/a.webp", "seed": 123}])

    made = made_on(page, ADDRESS, SCRIPT, until=without_waiting)

    assert made == Made(image="https://example.com/a.webp", seed="123")
    assert page.did == [("go to", "about:blank"), ("left the last page", ""), ("go to", ADDRESS),
                        ("run", SCRIPT)]


def test_a_page_that_says_why_it_made_nothing_is_a_refusal_with_that_reason():
    page = FakePage(answers=[{"refused": SIGNED_OUT}])

    with pytest.raises(SiteRefused) as refused:
        made_on(page, ADDRESS, SCRIPT, until=without_waiting)

    assert refused.value.reason == SIGNED_OUT


def test_a_page_that_never_answers_is_a_refusal():
    with pytest.raises(SiteRefused) as refused:
        made_on(FakePage(), ADDRESS, SCRIPT, until=never)

    assert refused.value.reason == NEVER_ANSWERED


def test_a_chrome_that_fails_mid_way_is_a_refusal():
    page = FakePage()
    page.run = lambda script: (_ for _ in ()).throw(ChromeRefused("gone"))

    with pytest.raises(SiteRefused) as refused:
        made_on(page, ADDRESS, SCRIPT, until=without_waiting)

    assert refused.value.reason == CHROME_FAILED


class FakeChrome:
    def __init__(self, *pages):
        self._pages = list(pages)
        self.opened: list[tuple[str, bool]] = []
        self.closed = 0
        self.open_now = False
        self.window_stays = True

    def open(self, address: str = "about:blank", *, seen: bool = False):
        self.opened.append((address, seen))
        self.open_now = True
        return self._pages.pop(0)

    def is_open(self) -> bool:
        return self.open_now and self.window_stays

    def close(self) -> None:
        self.closed += 1
        self.open_now = False


def _site(chrome):
    return Site(chrome, lambda: SCRIPT, until=without_waiting)


def test_a_site_makes_one_image_after_another_in_the_one_unseen_chrome():
    page = FakePage(answers=[{"image": "https://example.com/a.webp", "seed": 1},
                             {"image": "https://example.com/b.webp", "seed": 2}])
    chrome = FakeChrome(page)
    site = _site(chrome)

    made = [site.make(ADDRESS), site.make(ADDRESS)]

    assert [each.image for each in made] == ["https://example.com/a.webp",
                                             "https://example.com/b.webp"]
    assert chrome.opened == [("about:blank", False)]


def test_a_site_that_asks_for_a_sign_in_shows_its_page_until_signed_in_then_makes_the_image():
    asked = FakePage(answers=[{"refused": SIGNED_OUT}])
    shown = FakePage(signed_out=[None, True, True, False])
    after = FakePage(answers=[{"image": "https://example.com/a.webp", "seed": 7}])
    chrome = FakeChrome(asked, shown, after)

    made = _site(chrome).make(ADDRESS)

    assert made == Made(image="https://example.com/a.webp", seed="7")
    assert chrome.opened == [("about:blank", False), ("https://example.com/create", True),
                              ("about:blank", False)]
    assert shown.did == [("run", SCRIPT)]


def test_a_sign_in_window_closed_before_signing_in_is_a_refusal():
    asked = FakePage(answers=[{"refused": SIGNED_OUT}])
    shown = FakePage(signed_out=[True, OSError("the window is gone")])
    chrome = FakeChrome(asked, shown)

    def close_the_window_after_the_first_look_for_a_sign_in(condition, **how):
        if "interval" in how:
            assert condition() is False
            chrome.window_stays = False
        without_waiting(condition, **how)

    with pytest.raises(SiteRefused) as refused:
        Site(chrome, lambda: SCRIPT,
             until=close_the_window_after_the_first_look_for_a_sign_in).make(ADDRESS)

    assert refused.value.reason == WINDOW_CLOSED


def test_a_page_that_is_between_addresses_while_signing_in_is_looked_at_again():
    asked = FakePage(answers=[{"refused": SIGNED_OUT}])
    shown = FakePage(signed_out=[ChromeRefused("no page yet"), False])
    after = FakePage(answers=[{"image": "https://example.com/a.webp"}])

    assert _site(FakeChrome(asked, shown, after)).make(ADDRESS).image == "https://example.com/a.webp"


def test_any_other_refusal_is_passed_on_and_the_chrome_kept_for_the_next_image():
    chrome = FakeChrome(FakePage(answers=[{"refused": "made-up reason"}]))

    with pytest.raises(SiteRefused) as refused:
        _site(chrome).make(ADDRESS)

    assert refused.value.reason == "made-up reason"
    assert chrome.closed == 0


def test_a_chrome_that_will_not_start_is_a_refusal_and_is_closed():
    chrome = FakeChrome()
    chrome.open = lambda *a, **k: (_ for _ in ()).throw(TimeoutError())

    with pytest.raises(SiteRefused) as refused:
        _site(chrome).make(ADDRESS)

    assert refused.value.reason == CHROME_FAILED
    assert chrome.closed == 1


def test_closing_a_site_closes_its_chrome():
    chrome = FakeChrome(FakePage(answers=[{"image": "https://example.com/a.webp"}]))
    site = _site(chrome)
    site.make(ADDRESS)

    site.close()

    assert chrome.closed == 1
