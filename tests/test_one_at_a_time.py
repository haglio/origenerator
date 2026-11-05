from __future__ import annotations

import uuid

from origenerator.one_at_a_time import Turn


def _name() -> str:
    return f"Local\\Origenerator.test.{uuid.uuid4().hex}"


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def test_a_turn_nobody_holds_is_taken_at_once():
    clock = _Clock()

    with Turn(_name(), sleep=clock.sleep, clock=clock).taken() as mine:
        assert mine is True

    assert clock.slept == []


def test_a_turn_is_free_again_once_its_taker_is_done():
    name = _name()
    with Turn(name).taken():
        pass

    with Turn(name, wait_s=0).taken() as mine:
        assert mine is True


def test_a_second_taker_waits_until_the_first_is_done():
    name, clock = _name(), _Clock()
    first = Turn(name).taken()
    first.__enter__()

    def the_first_finishes(seconds: float) -> None:
        clock.sleep(seconds)
        if len(clock.slept) == 3:
            first.__exit__(None, None, None)

    with Turn(name, sleep=the_first_finishes, clock=clock).taken() as mine:
        assert mine is True

    assert len(clock.slept) == 3


def test_a_taker_gives_up_once_it_has_waited_as_long_as_it_was_given():
    name, clock = _name(), _Clock()

    with Turn(name).taken(), \
            Turn(name, wait_s=2.0, sleep=clock.sleep, clock=clock).taken() as mine:
        assert mine is False

    assert clock.now >= 2.0


def test_a_taker_that_gave_up_leaves_the_turn_with_whoever_holds_it():
    name = _name()

    with Turn(name).taken():
        with Turn(name, wait_s=0).taken():
            pass
        with Turn(name, wait_s=0).taken() as mine:
            assert mine is False
