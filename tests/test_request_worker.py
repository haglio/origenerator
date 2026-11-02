from __future__ import annotations

import logging

from PyQt6 import sip
from PyQt6.QtWidgets import QWidget

from origenerator.gui.request_worker import ReviseTask, RevisionWorker


def test_the_revision_comes_back_with_the_callers_context(qtbot):
    worker = RevisionWorker(lambda pos, neg, req, **_told: f"{pos}|{neg}|{req}")
    seen = []
    worker.revised.connect(lambda ctx, rev: seen.append((ctx, rev)))

    worker.revise("ctx", "a woman", "blurry", "no hat")

    assert seen == [("ctx", "a woman|blurry|no hat")]


def test_a_failure_answers_with_nothing_rather_than_raising(qtbot):
    def boom(pos, neg, req, **_told):
        raise RuntimeError("no LLM server")

    worker = RevisionWorker(boom)
    seen = []
    worker.revised.connect(lambda ctx, rev: seen.append(rev))

    worker.revise("ctx", "a woman", "", "no hat")

    assert seen == [None]


def test_a_failure_is_logged_without_the_request_or_either_prompt(qtbot, caplog):
    def boom(pos, neg, req, **_told):
        raise ValueError(f"cannot read {pos!r} or {neg!r} for {req!r}")

    worker = RevisionWorker(boom)

    with caplog.at_level(logging.INFO, logger="origenerator.gui.request_worker"):
        worker.revise("ctx", "gamma form, an example lantern", "example flaws to avoid",
                      "no example lantern")

    assert caplog.messages == ["Could not work out a request (ValueError)"]


def test_the_task_runs_one_revision(qtbot):
    worker = RevisionWorker(lambda pos, neg, req, **_told: req.upper())
    seen = []
    worker.revised.connect(lambda ctx, rev: seen.append(rev))

    ReviseTask(worker, "ctx", "a woman", "", "no hat", in_scenes=False).run()

    assert seen == ["NO HAT"]


def test_the_task_tells_the_revision_whether_the_prompt_tells_a_story(qtbot):
    worker = RevisionWorker(lambda pos, neg, req, *, in_scenes: in_scenes)
    seen = []
    worker.revised.connect(lambda ctx, rev: seen.append(rev))

    ReviseTask(worker, "ctx", "a woman", "", "no hat", in_scenes=True).run()

    assert seen == [True]


def test_a_window_closed_mid_request_takes_its_answer_with_it(qtbot):
    parent = QWidget()
    worker = RevisionWorker(lambda pos, neg, req, **_told: req.upper(), parent=parent)
    task = ReviseTask(worker, "ctx", "a woman", "", "no hat", in_scenes=False)
    parent.deleteLater()
    sip.delete(parent)

    task.run()
