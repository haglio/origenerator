from __future__ import annotations

import pytest

from origenerator.undo_stack import UndoEntry, UndoStack


@pytest.fixture
def stack() -> UndoStack:
    return UndoStack(limit=3)


def _entry(log, label, *, redoable=True, commit=False):
    return UndoEntry(
        label,
        undo=lambda: (log.append(f"undo {label}"), label)[1],
        commit=(lambda: log.append(f"commit {label}")) if commit else None,
        redo=(lambda: log.append(f"redo {label}")) if redoable else None,
    )


def test_an_empty_stack_offers_nothing(stack):
    assert stack.can_undo() is False
    assert stack.undo_label() is None
    assert stack.undo() is None
    assert stack.can_redo() is False
    assert stack.redo_label() is None
    assert stack.redo() is None


def test_undo_walks_back_the_most_recent_step(stack):
    log = []
    stack.push(_entry(log, "first"))
    stack.push(_entry(log, "second"))

    assert stack.undo_label() == "second"
    assert stack.undo() == "second"
    assert log == ["undo second"]
    assert stack.undo_label() == "first"


def test_an_undone_step_moves_to_the_redo_stack(stack):
    log = []
    stack.push(_entry(log, "rename"))

    stack.undo()

    assert stack.can_undo() is False
    assert stack.can_redo() is True
    assert stack.redo_label() == "rename"


def test_a_step_that_cannot_be_re_applied_never_reaches_the_redo_stack(stack):
    log = []
    stack.push(_entry(log, "one-way", redoable=False))

    stack.undo()

    assert stack.can_redo() is False


def test_a_new_step_forks_history_and_the_branch_you_left_is_gone(stack):
    log = []
    stack.push(_entry(log, "first"))
    stack.undo()
    assert stack.can_redo() is True

    stack.push(_entry(log, "second"))

    assert stack.can_redo() is False


def test_the_entry_a_redo_pushes_does_not_clear_the_redos_behind_it(stack):
    log = []

    def re_run_first():
        log.append("redo first")
        stack.push(_entry(log, "first again"))

    stack.push(UndoEntry("first", undo=lambda: None, redo=re_run_first))
    stack.push(_entry(log, "second"))
    stack.undo()
    stack.undo()
    assert [stack.redo_label()] == ["first"]

    stack.redo()

    assert log[-1] == "redo first"
    assert stack.can_redo() is True
    assert stack.redo_label() == "second"


def test_the_oldest_step_falls_off_when_the_limit_is_passed(stack):
    log = []
    for name in ("first", "second", "third", "fourth"):
        stack.push(_entry(log, name, commit=True))

    assert log == ["commit first"]
    assert [entry.label for entry in stack.entries()] == ["second", "third", "fourth"]


def test_a_step_with_nothing_to_commit_falls_off_quietly(stack):
    log = []
    for name in ("first", "second", "third", "fourth"):
        stack.push(_entry(log, name))

    assert log == []


def test_undo_hands_back_whatever_the_step_says_to_navigate_to(stack):
    stack.push(UndoEntry("rename", undo=lambda: None))

    assert stack.undo() is None


def test_a_redone_step_can_be_undone_and_redone_any_number_of_times(stack):
    runs = []

    def do():
        runs.append("done")
        stack.push(UndoEntry("rename", undo=lambda: None, redo=do))

    do()
    for _ in range(3):
        stack.undo()
        assert stack.redo_label() == "rename"
        stack.redo()
        assert stack.undo_label() == "rename"

    assert runs == ["done"] * 4, (
        "a redo runs the original change again rather than inverting the undo: the undo already "
        "spent its trash batches, so the step files fresh ones and a fresh undo entry")
