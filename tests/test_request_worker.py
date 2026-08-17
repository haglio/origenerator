"""RevisionWorker — working out a request off the UI thread.

The apply callable is injected, so the flow runs inline with no model and no
server; what is under test is that a result comes back with its context and that
a failure is answered rather than raised.
"""

from origenerator.gui.request_worker import ReviseTask, RevisionWorker


def test_the_revision_comes_back_with_the_callers_context(qtbot):
    worker = RevisionWorker(lambda pos, neg, req: f"{pos}|{neg}|{req}")
    seen = []
    worker.revised.connect(lambda ctx, rev: seen.append((ctx, rev)))

    worker.revise("ctx", "a woman", "blurry", "no hat")

    assert seen == [("ctx", "a woman|blurry|no hat")]


def test_a_failure_answers_with_nothing_rather_than_raising(qtbot):
    # A model that is down is the ordinary case here, not an error: the request
    # is still applied, just by the words alone.
    def boom(pos, neg, req):
        raise RuntimeError("no LLM server")

    worker = RevisionWorker(boom)
    seen = []
    worker.revised.connect(lambda ctx, rev: seen.append(rev))

    worker.revise("ctx", "a woman", "", "no hat")

    assert seen == [None]


def test_the_task_runs_one_revision(qtbot):
    worker = RevisionWorker(lambda pos, neg, req: req.upper())
    seen = []
    worker.revised.connect(lambda ctx, rev: seen.append(rev))

    ReviseTask(worker, "ctx", "a woman", "", "no hat").run()

    assert seen == ["NO HAT"]
