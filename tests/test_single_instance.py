from __future__ import annotations

import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from origenerator.single_instance import Copies

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def claims():
    held = []
    yield held
    for claim in filter(None, held):
        claim.let_go()


def test_a_second_claim_on_one_library_is_refused(tmp_path, claims):
    claims.append(Copies(tmp_path / "state").claim_the_library())

    assert claims[0]
    assert Copies(tmp_path / "state").claim_the_library() is None


def test_one_library_is_one_however_its_folder_is_spelled(tmp_path, claims):
    folder = tmp_path / "state"
    claims.append(Copies(folder).claim_the_library())

    assert Copies(Path(str(folder).upper().replace("\\", "/"))).claim_the_library() is None


def test_another_library_is_claimed_beside_it(tmp_path, claims):
    claims.append(Copies(tmp_path / "one" / "state").claim_the_library())
    claims.append(Copies(tmp_path / "two" / "state").claim_the_library())

    assert all(claims)


def test_a_library_let_go_of_is_free_for_the_next_copy(tmp_path, claims):
    Copies(tmp_path / "state").claim_the_library().let_go()

    claims.append(Copies(tmp_path / "state").claim_the_library())

    assert claims[0]


class _AnAppQuitting:
    def __init__(self):
        self.aboutToQuit = self
        self._steps = []

    def connect(self, step):
        self._steps.append(step)

    def quit(self):
        for step in self._steps:
            step()


def _a_copy_closing(copies):
    claim = copies.claim_the_library()
    app = _AnAppQuitting()
    claim.closes_with(app)
    app.quit()
    return claim


def test_the_log_says_when_a_copy_began_to_close_and_when_it_let_go_of_the_library(
        tmp_path, caplog):
    with caplog.at_level(logging.INFO, logger="origenerator.single_instance"):
        _a_copy_closing(Copies(tmp_path / "state")).let_go()

    assert [record.getMessage() for record in caplog.records] == [
        "Closing: a launch now waits for this copy to let go of the library",
        "Let go of the library",
    ]


def test_a_launch_behind_a_closing_copy_takes_the_library_as_soon_as_it_is_let_go(
        tmp_path, claims):
    copies = Copies(tmp_path / "state")
    closing = _a_copy_closing(copies)
    looks = []

    def a_look_later(seconds):
        looks.append(seconds)
        if len(looks) == 3:
            closing.let_go()

    claims.append(copies.claim_the_library_once_the_closing_one_lets_go(sleep=a_look_later))

    assert claims[0]
    assert looks == [0.1, 0.1, 0.1]


def test_a_launch_that_looks_just_as_the_closing_copy_lets_go_still_takes_the_library(
        tmp_path, claims):
    copies = Copies(tmp_path / "state")
    closing = _a_copy_closing(copies)
    look = copies.claim_the_library

    def a_look_the_closing_copy_lets_go_right_after():
        claim = look()
        closing.let_go()
        return claim

    copies.claim_the_library = a_look_the_closing_copy_lets_go_right_after

    claims.append(copies.claim_the_library_once_the_closing_one_lets_go(
        sleep=lambda seconds: None))

    assert claims[0]


def test_a_launch_stops_waiting_once_a_copy_that_is_not_closing_holds_the_library(
        tmp_path, claims):
    copies = Copies(tmp_path / "state")
    closing = _a_copy_closing(copies)

    def another_launch_gets_there_first(seconds):
        closing.let_go()
        claims.append(copies.claim_the_library())

    assert copies.claim_the_library_once_the_closing_one_lets_go(
        sleep=another_launch_gets_there_first) is None
    assert claims[0]


def test_a_launch_gives_up_on_a_copy_still_closing_a_minute_later(tmp_path):
    copies = Copies(tmp_path / "state")
    closing = _a_copy_closing(copies)
    now = [0.0]

    def each_look_takes_six_seconds(seconds):
        now[0] += 6

    try:
        assert copies.claim_the_library_once_the_closing_one_lets_go(
            sleep=each_look_takes_six_seconds, clock=lambda: now[0]) is None
        assert 60 <= now[0] < 61
    finally:
        closing.let_go()


def test_a_copy_quitting_says_it_is_closing_until_it_lets_go_while_its_process_lives_on(
        tmp_path, claims):
    copies = Copies(tmp_path / "state")
    copy = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import sys
            sys.path.insert(0, {str(REPO_ROOT)!r})
            from PyQt6.QtCore import QTimer
            from PyQt6.QtWidgets import QApplication
            from origenerator.single_instance import Copies
            app = QApplication(sys.argv[:1])
            claim = Copies({str(tmp_path / "state")!r}).claim_the_library()
            claim.closes_with(app)
            def the_rest_of_its_teardown():
                print("tearing down", flush=True)
                sys.stdin.readline()
            app.aboutToQuit.connect(the_rest_of_its_teardown)
            QTimer.singleShot(0, app.quit)
            app.exec()
            claim.let_go()
            print("let go", flush=True)
            sys.stdin.readline()
        """)],
        cwd=REPO_ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        assert copy.stdout.readline() == "tearing down\n"
        assert copies.one_is_closing()
        assert copies.claim_the_library() is None

        copy.stdin.write("\n")
        copy.stdin.flush()
        assert copy.stdout.readline() == "let go\n"
        assert not copies.one_is_closing()
        claims.append(copies.claim_the_library())
        assert claims[0]
    finally:
        copy.communicate("\n\n", timeout=60)
