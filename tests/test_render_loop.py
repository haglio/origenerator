from __future__ import annotations

from origenerator.render_loop import request_threaded_render_loop


def test_the_app_asks_qt_quick_to_draw_on_a_thread_of_its_own():
    environ = {}

    request_threaded_render_loop(environ)

    assert environ["QSG_RENDER_LOOP"] == "threaded"


def test_a_render_loop_already_named_in_the_environment_wins():
    environ = {"QSG_RENDER_LOOP": "basic"}

    request_threaded_render_loop(environ)

    assert environ["QSG_RENDER_LOOP"] == "basic"
