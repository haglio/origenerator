from __future__ import annotations

import threading
from collections import Counter
from types import SimpleNamespace

from origenerator.where_the_time_went import (
    PACKAGE_DIR,
    LooksAtAThread,
    Seconds,
    functions_stood_in,
    read_seconds,
    said_in_one_line,
    spent_between,
)

_WATCHED = 0x1D34
_ANOTHER = 0x2294


def _frame(file: str, function: str, under=None) -> SimpleNamespace:
    return SimpleNamespace(f_code=SimpleNamespace(co_filename=file, co_name=function), f_back=under)


def _stack(innermost_first: list[tuple[str, str]]) -> SimpleNamespace | None:
    frame = None
    for file, function in reversed(innermost_first):
        frame = _frame(file, function, under=frame)
    return frame


_BUILDING_THE_GALLERY = [
    (PACKAGE_DIR + "\\gui\\gallery_view.py", "_build_ui"),
    (PACKAGE_DIR + "\\gui\\core.py", "__init__"),
    ("C:\\made-up\\site-packages\\qt.py", "exec"),
]


def _every_threads_frames() -> dict:
    return {_ANOTHER: _stack([(PACKAGE_DIR + "\\comfyui_client.py", "run")]),
            _WATCHED: _stack(_BUILDING_THE_GALLERY)}


def test_a_look_names_every_function_of_the_app_the_thread_stands_in_innermost_first():
    assert functions_stood_in(_stack(_BUILDING_THE_GALLERY)) == [
        "gallery_view._build_ui", "core.__init__"]


def test_a_thread_that_has_ended_stands_in_nothing():
    assert functions_stood_in(_every_threads_frames().get(0x7777)) == []


def test_a_function_calling_itself_counts_once_a_look():
    walking = [(PACKAGE_DIR + "\\gallery\\tree.py", "walk")] * 2

    assert functions_stood_in(_stack(walking)) == ["tree.walk"]


def test_a_real_look_at_its_own_thread_finds_itself_looking():
    looks = LooksAtAThread(threading.get_ident())

    looks.look()

    assert looks.said_in_one_line() == (
        "1 looks at the thread, and how many found it inside each function: "
        "where_the_time_went.look 1")


def test_the_line_names_the_functions_found_most_often_first():
    line = said_in_one_line(4, Counter({"tree.walk": 1, "gallery_view._build_ui": 3,
                                        "core.__init__": 4}), most=2)

    assert line == ("4 looks at the thread, and how many found it inside each function: "
                    "core.__init__ 4, gallery_view._build_ui 3")


def test_functions_found_as_often_are_named_in_the_order_they_were_first_found():
    line = said_in_one_line(2, Counter({"gallery_view._build_ui": 2, "core.__init__": 2}))

    assert line.endswith(": gallery_view._build_ui 2, core.__init__ 2")


def test_each_look_reads_the_thread_it_was_given():
    looks = LooksAtAThread(_WATCHED, frames=_every_threads_frames)

    looks.look()
    looks.look()

    assert looks.said_in_one_line() == (
        "2 looks at the thread, and how many found it inside each function: "
        "gallery_view._build_ui 2, core.__init__ 2")


def test_it_goes_on_looking_until_the_work_it_watches_is_over():
    looked_twice = threading.Event()
    seen = []

    def frames():
        seen.append(1)
        if len(seen) == 2:
            looked_twice.set()
        return {}

    with LooksAtAThread(_WATCHED, frames=frames, every_s=0.001) as looks:
        assert looked_twice.wait()

    assert looks.said_in_one_line().startswith(f"{len(seen)} looks at the thread")


def test_the_seconds_spent_say_how_long_the_program_had_a_processor_and_how_busy_the_computer_was():
    before = Seconds(wall=100.0, this_program=2.0, computer_busy=1000.0, computer_all=4000.0)
    after = Seconds(wall=108.0, this_program=3.5, computer_busy=1120.0, computer_all=4128.0)

    assert spent_between(before, after) == (
        "8.0 s passed, this program had a processor for 1.5 s of them, "
        "and the computer's processors were 94% busy")


def test_no_time_on_the_computers_clocks_reads_as_no_share_rather_than_dividing_by_nothing():
    at_once = Seconds(wall=1.0, this_program=1.0, computer_busy=5.0, computer_all=9.0)

    assert spent_between(at_once, at_once).endswith("were 0% busy")


def test_the_computers_clocks_never_run_backwards_and_busy_is_part_of_all():
    first, second = read_seconds(), read_seconds()

    assert second.wall >= first.wall
    assert second.computer_all >= first.computer_all
    assert 0 <= second.computer_busy <= second.computer_all
