from __future__ import annotations

from contextlib import contextmanager

from origenerator import running_ahead


def recorded_block():
    raised = []

    @contextmanager
    def block():
        raised.append("ahead")
        yield
        raised.append("back")

    return block, raised


def record_the_app_running_ahead(monkeypatch) -> list[str]:
    block, raised = recorded_block()
    monkeypatch.setattr(running_ahead, "_THIS_APP", running_ahead.AheadWhilePlaying(block))
    return raised
