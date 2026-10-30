"""Handing the graphics card from ComfyUI to the local model."""
from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from origenerator import graphics_card


class _Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class _ComfyUI:
    def __init__(self, queues, *, fails=False):
        self.queues = list(queues)
        self.fails = fails
        self.let_go = 0

    def fetch_queue(self):
        if self.fails:
            raise OSError("not running")
        return self.queues.pop(0) if len(self.queues) > 1 else self.queues[0]

    def free_memory(self):
        self.let_go += 1


def _wait(comfyui, *, memory=lambda: (14000, 16303), deadline_s=600.0):
    clock = _Clock()
    got_it = graphics_card.wait_for_the_card(comfyui, memory=memory, clock=clock,
                                             sleep=clock.sleep, deadline_s=deadline_s)
    return got_it, clock


def test_comfyui_is_waited_for_then_asked_to_let_go_of_its_models():
    comfyui = _ComfyUI([{"a"}, {"a"}, set()])

    got_it, clock = _wait(comfyui)

    assert got_it is True
    assert comfyui.let_go == 1
    assert clock.now > 0  # it waited for the two polls that found ComfyUI busy


def test_a_comfyui_that_never_finishes_within_the_deadline_is_given_up_on():
    comfyui = _ComfyUI([{"a"}])

    got_it, clock = _wait(comfyui, deadline_s=60.0)

    assert got_it is False
    assert comfyui.let_go == 0
    assert clock.now >= 60.0


def test_a_comfyui_that_cannot_be_asked_counts_as_idle_and_is_not_asked_to_let_go():
    comfyui = _ComfyUI([set()], fails=True)

    got_it, _clock = _wait(comfyui)

    assert got_it is True
    assert comfyui.let_go == 0


def test_the_wait_goes_on_until_the_card_has_room_for_the_model():
    readings = [(6000, 16303), (6500, 16303), (12000, 16303)]
    got_it, clock = _wait(_ComfyUI([set()]), memory=lambda: readings.pop(0))

    assert got_it is True
    assert readings == []  # it read the card until the room was there


def test_a_card_that_never_makes_room_is_still_tried():
    # ComfyUI let go and nothing else is asking for the card: the model loads
    # with whatever is free rather than never answering at all.
    got_it, _clock = _wait(_ComfyUI([set()]), memory=lambda: (6000, 16303))

    assert got_it is True


def test_without_nvidia_smi_the_card_is_taken_on_trust():
    got_it, _clock = _wait(_ComfyUI([set()]), memory=lambda: None)

    assert got_it is True


def test_the_cards_free_and_total_memory_are_read_from_nvidia_smi():
    with patch.object(graphics_card.subprocess, "run",
                      return_value=SimpleNamespace(stdout="14842, 16303\n")) as run:
        assert graphics_card.card_memory_mib() == (14842, 16303)

    assert run.call_args.kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_a_missing_nvidia_smi_reads_as_no_reading():
    with patch.object(graphics_card.subprocess, "run", side_effect=OSError("no such program")):
        assert graphics_card.card_memory_mib() is None
