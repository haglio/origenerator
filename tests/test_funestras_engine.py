"""Where this app finds the Funestras' engine."""
from __future__ import annotations

import os

from origenerator import funestras_engine


def test_the_engine_copy_beside_the_checkouts_goes_in_front(monkeypatch, tmp_path):
    """The engine is one file, fetched once for the machine, with a copy beside
    the checkouts. The machine-wide folder has answered nothing at all to this
    app while answering every other process, so the copy beside goes first."""
    beside = tmp_path / "funestra" / "vendor"
    beside.mkdir(parents=True)
    (beside / "libmpv-2.dll").write_bytes(b"")
    monkeypatch.setattr(funestras_engine, "project_dir", lambda name: tmp_path / name)
    monkeypatch.setenv("PATH", r"C:\somewhere\else")

    funestras_engine.offer_the_copy_beside_the_checkouts()

    assert os.environ["PATH"].split(os.pathsep)[0] == str(beside)


def test_no_copy_beside_the_checkouts_leaves_the_path_alone(monkeypatch, tmp_path):
    monkeypatch.setattr(funestras_engine, "project_dir", lambda name: tmp_path / name)
    monkeypatch.setenv("PATH", r"C:\somewhere\else")

    funestras_engine.offer_the_copy_beside_the_checkouts()

    assert os.environ["PATH"] == r"C:\somewhere\else"
