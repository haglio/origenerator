from __future__ import annotations

import threading
from collections import Counter

from origenerator.where_the_time_went import (
    PACKAGE_DIR,
    LooksAtAThread,
    every_threads_stack,
    functions_stood_in,
    said_in_one_line,
)

_WATCHED = 0x1D34
_ANOTHER = 0x2294


def _stacks(*, watched_frames: list[tuple[str, str]]) -> str:
    def frames(found):
        return "".join(f'  File "{file}", line 7 in {function}\n' for file, function in found)

    return (f"Thread 0x{_ANOTHER:08x} [ComfyUIClient] (most recent call first):\n"
            + frames([(PACKAGE_DIR + "\\comfyui_client.py", "run")])
            + "\n"
            + f"Thread 0x{_WATCHED:08x} (most recent call first):\n"
            + frames(watched_frames)
            + "\n"
            + "Current thread 0x00000042 [where-the-time-went] (most recent call first):\n"
            + frames([(PACKAGE_DIR + "\\where_the_time_went.py", "look")]))


_BUILDING_THE_GALLERY = [
    (PACKAGE_DIR + "\\gui\\gallery_view.py", "_build_ui"),
    (PACKAGE_DIR + "\\gui\\core.py", "__init__"),
    ("C:\\made-up\\site-packages\\qt.py", "exec"),
]


def test_a_look_names_every_function_of_the_app_the_thread_stands_in():
    stacks = _stacks(watched_frames=_BUILDING_THE_GALLERY)

    assert functions_stood_in(stacks, _WATCHED) == {"core.__init__", "gallery_view._build_ui"}


def test_a_thread_that_has_ended_stands_in_nothing():
    assert functions_stood_in(_stacks(watched_frames=_BUILDING_THE_GALLERY), 0x7777) == set()


def test_a_function_calling_itself_counts_once_a_look():
    walking = [(PACKAGE_DIR + "\\gallery\\tree.py", "walk")] * 2

    assert functions_stood_in(_stacks(watched_frames=walking), _WATCHED) == {"tree.walk"}


def test_the_stacks_it_reads_name_the_thread_that_asked():
    stacks = every_threads_stack()

    assert functions_stood_in(stacks, threading.get_ident()) == {
        "where_the_time_went.every_threads_stack"}


def test_the_line_names_the_functions_found_most_often_first():
    line = said_in_one_line(4, Counter({"tree.walk": 1, "gallery_view._build_ui": 3,
                                        "core.__init__": 4}), most=2)

    assert line == ("4 looks at the thread, and how many found it inside each function: "
                    "core.__init__ 4, gallery_view._build_ui 3")


def test_functions_found_as_often_are_named_in_the_order_of_their_names():
    line = said_in_one_line(2, Counter({"gallery_view._build_ui": 2, "core.__init__": 2}))

    assert line.endswith(": core.__init__ 2, gallery_view._build_ui 2")


def test_each_look_reads_the_thread_it_was_given():
    looks = LooksAtAThread(_WATCHED,
                           stacks=lambda: _stacks(watched_frames=_BUILDING_THE_GALLERY))

    looks.look()
    looks.look()

    assert looks.said_in_one_line() == (
        "2 looks at the thread, and how many found it inside each function: "
        "core.__init__ 2, gallery_view._build_ui 2")


def test_it_goes_on_looking_until_the_work_it_watches_is_over():
    looked_twice = threading.Event()
    seen = []

    def stacks():
        seen.append(1)
        if len(seen) == 2:
            looked_twice.set()
        return ""

    with LooksAtAThread(_WATCHED, stacks=stacks, every_s=0.001) as looks:
        assert looked_twice.wait(10)

    assert looks.said_in_one_line().startswith(f"{len(seen)} looks at the thread")
