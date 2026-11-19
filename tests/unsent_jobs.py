from __future__ import annotations

from origenerator.gui.generation_job import GenerationJob


def _sent_nowhere(_job, send=None, answered=None) -> None:
    if send is not None:
        answered(None)


def leave_every_job_unsent(monkeypatch) -> None:
    monkeypatch.setattr(GenerationJob, "start", _sent_nowhere)
