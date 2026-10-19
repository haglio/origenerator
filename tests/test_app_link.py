"""The link a clicked notification follows, and what following one does.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from origenerator import app_link, config


def test_a_link_names_the_generation_it_opens():
    link = app_link.link_to("7f0c9b2e-1111-4444-8888-aaaabbbbcccc")

    assert link.startswith("origenerator:")
    assert app_link.generation_in(link) == "7f0c9b2e-1111-4444-8888-aaaabbbbcccc"


@pytest.mark.parametrize("link", [
    "",
    "origenerator:",
    "origenerator:go-to",
    "origenerator:go-to?generation=",
    "https://example.test/go-to?generation=alpha-1",
    "origenerator:go-to?folder=alpha-1",
    "origenerator:go-to?generation=../../windows/system32",
    'origenerator:go-to?generation=alpha" & del',
    "origenerator:go-to?generation=" + "a" * 129,
])
def test_a_link_that_asks_for_anything_else_names_nothing(link):
    # The scheme is open to whatever can reach a shell -- a page, another app --
    # so a link is read as one thing only: a generation this gallery may hold.
    assert app_link.generation_in(link) is None


def test_each_checkout_names_a_channel_of_its_own():
    # A suite's copy listens on its own checkout's, never on the one production's
    # clicks arrive on.
    live = app_link.channel_for(Path(r"C:\workspace\origenerator"))
    preview = app_link.channel_for(Path(r"C:\workspace\origenerator\.claude\worktrees\x"))

    assert live != preview
    assert live == app_link.channel_for(Path(r"c:\WORKSPACE\origenerator"))
    assert live.isascii() and " " not in live


def test_the_checkout_it_answers_for_is_the_one_it_was_imported_from():
    assert app_link.CHECKOUT == config.PROJECT_DIR


def test_what_windows_runs_on_a_click_names_the_checkouts_handler_and_its_launcher():
    command = app_link.handler_command(
        checkout=Path(r"C:\workspace\origenerator"),
        interpreter=Path(r"C:\workspace\origenerator\.venv\Scripts\pythonw.exe"))

    assert command == (
        r'"C:\workspace\origenerator\.venv\Scripts\pythonw.exe" '
        r'"C:\workspace\origenerator\tools\open_from_notification.py" '
        r'"launch_origenerator.vbs" "%1"')


def test_a_handler_run_by_windows_is_the_script_the_command_names():
    assert (app_link.CHECKOUT / app_link.HANDLER).is_file()


def test_the_launcher_a_click_starts_is_one_this_checkout_has():
    assert (app_link.CHECKOUT / app_link.LIVE_LAUNCHER).is_file()


def _started(monkeypatch):
    runs = []
    monkeypatch.setattr(app_link.subprocess, "Popen",
                        lambda command, **named: runs.append((command, named)))
    return runs


def _carried(runs):
    return [named["env"][app_link.CARRIED_IN] for _command, named in runs]


def _until(condition, *, within_s=5.0):
    give_up_at = time.monotonic() + within_s
    while not condition():
        assert time.monotonic() < give_up_at, "waited in vain"
        time.sleep(0.01)


def test_with_nothing_listening_the_app_is_started_carrying_the_generation(monkeypatch, tmp_path):
    monkeypatch.setattr(app_link, "hand_over", lambda *a, **k: False)
    monkeypatch.setattr(app_link, "listening", lambda channel: True)
    runs = _started(monkeypatch)

    assert app_link.follow(["launch_origenerator.vbs",
                            app_link.link_to("alpha-1")], checkout=tmp_path) == 0

    command, named = runs[0]
    assert command[0].lower().endswith("wscript.exe")
    assert command[1] == str(tmp_path / "launch_origenerator.vbs")
    assert named["env"][app_link.CARRIED_IN] == "alpha-1"


def test_a_running_app_is_handed_the_generation_rather_than_a_second_copy_started(
        monkeypatch, tmp_path):
    handed = []
    monkeypatch.setattr(app_link, "hand_over",
                        lambda generation, *, channel: handed.append((generation, channel)) is None)
    runs = _started(monkeypatch)

    assert app_link.follow(["launch_origenerator.vbs",
                            app_link.link_to("alpha-1")], checkout=tmp_path) == 0

    assert handed == [("alpha-1", app_link.channel_for(tmp_path))]
    assert runs == []


def test_a_link_to_anything_else_starts_nothing_and_hands_over_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(app_link, "hand_over", lambda *a, **k: pytest.fail("handed over"))
    runs = _started(monkeypatch)

    assert app_link.follow(["launch_origenerator.vbs", "https://example.test/"],
                           checkout=tmp_path) != 0

    assert runs == []


def test_a_handler_called_with_anything_else_does_nothing(monkeypatch, tmp_path):
    # The scheme is open to whatever can reach a shell, and so is the command
    # registered for it.
    monkeypatch.setattr(app_link, "hand_over", lambda *a, **k: pytest.fail("handed over"))
    runs = _started(monkeypatch)

    assert app_link.follow([], checkout=tmp_path) != 0
    assert app_link.follow(["one", "two", "three"], checkout=tmp_path) != 0

    assert runs == []


def test_an_app_too_busy_to_take_a_click_is_not_started_a_second_time(monkeypatch, tmp_path):
    # Every instance of the channel busy means the app is there and answering
    # someone else. A second copy of it started over a click would be worse than
    # the click doing nothing.
    monkeypatch.setattr(app_link, "_BUSY_PATIENCE_S", 0.05)
    monkeypatch.setattr(app_link.os, "open",
                        lambda *a, **k: (_ for _ in ()).throw(PermissionError("busy")))
    runs = _started(monkeypatch)

    assert app_link.follow([app_link.LIVE_LAUNCHER, app_link.link_to("alpha-1")],
                           checkout=tmp_path) == 0

    assert runs == []


def test_a_click_while_another_click_is_starting_the_app_starts_nothing(monkeypatch, tmp_path):
    # Notices clicked one after another faster than the app comes up: the copy
    # the first click started is still on its loading screen, nobody is
    # listening yet, and a second copy started over it could only say that
    # another copy is running.
    monkeypatch.setattr(app_link, "hand_over", lambda *a, **k: False)
    app_is_up = threading.Event()
    monkeypatch.setattr(app_link, "listening", lambda channel: app_is_up.is_set())
    runs = _started(monkeypatch)
    first = threading.Thread(target=app_link.follow,
                             args=([app_link.LIVE_LAUNCHER, app_link.link_to("alpha-1")],),
                             kwargs={"checkout": tmp_path})
    first.start()
    _until(lambda: len(runs) == 1)

    assert app_link.follow([app_link.LIVE_LAUNCHER, app_link.link_to("beta-2")],
                           checkout=tmp_path) == 0

    app_is_up.set()
    first.join(timeout=5)
    assert _carried(runs) == ["alpha-1"]


def test_a_click_whose_app_never_comes_up_leaves_the_next_click_free_to_start_it(
        monkeypatch, tmp_path):
    monkeypatch.setattr(app_link, "hand_over", lambda *a, **k: False)
    monkeypatch.setattr(app_link, "listening", lambda channel: False)
    monkeypatch.setattr(app_link, "TAKING_OVER_WITHIN_S", 0.05)
    runs = _started(monkeypatch)

    app_link.follow([app_link.LIVE_LAUNCHER, app_link.link_to("alpha-1")], checkout=tmp_path)
    app_link.follow([app_link.LIVE_LAUNCHER, app_link.link_to("beta-2")], checkout=tmp_path)

    assert _carried(runs) == ["alpha-1", "beta-2"]


def test_a_click_leaves_a_line_in_the_log_the_launcher_writes(monkeypatch, tmp_path):
    # The one record of a click there can be: nothing else about it is visible,
    # and a click that did nothing is otherwise indistinguishable from one that
    # never happened.
    monkeypatch.setattr(app_link, "hand_over", lambda *a, **k: True)

    app_link.follow(["launch_origenerator.vbs", app_link.link_to("alpha-1")],
                    checkout=tmp_path)

    written = (tmp_path / "state" / "origenerator_launcher.log").read_text(encoding="utf-8")
    assert "alpha-1" in written


def test_a_log_that_cannot_be_written_costs_the_click_nothing(monkeypatch, tmp_path):
    monkeypatch.setattr(app_link, "hand_over", lambda *a, **k: True)
    (tmp_path / "state").write_text("not a directory", encoding="utf-8")

    assert app_link.follow(["launch_origenerator.vbs", app_link.link_to("alpha-1")],
                           checkout=tmp_path) == 0


def test_the_handler_windows_runs_answers_out_of_its_own_checkout(tmp_path):
    # Run by path from wherever Windows happens to be standing, so what decides
    # what a click does has to be this checkout's copy rather than whichever one
    # the venv has installed.
    handler = subprocess.run(
        [sys.executable, str(app_link.CHECKOUT / app_link.HANDLER),
         app_link.LIVE_LAUNCHER, "https://example.test/"],
        cwd=tmp_path, capture_output=True, text=True, timeout=60,
        env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"})

    assert handler.returncode == 2, handler.stderr
    assert handler.stdout == ""
