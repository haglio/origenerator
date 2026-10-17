from __future__ import annotations

import _winapi
from pathlib import Path

from origenerator import reveal


def _capture_run(monkeypatch):
    calls = []
    monkeypatch.setattr(reveal.subprocess, "run", lambda *a, **k: calls.append((a, k)))
    return calls


def test_show_in_explorer_selects_the_file(monkeypatch):
    calls = _capture_run(monkeypatch)
    target = Path("C:/Users/Example/Pictures/cat.png")

    reveal.show_in_explorer(target)

    (cmd,), _ = calls[0]
    # Explorer selects (not just opens the folder) with /select, and the file's
    # native path.
    assert cmd == ["explorer", "/select,", str(target)]


def test_show_in_explorer_suppresses_the_console_window(monkeypatch):
    calls = _capture_run(monkeypatch)

    reveal.show_in_explorer(Path("C:/x.png"))

    _, kwargs = calls[0]
    assert kwargs["creationflags"] == reveal._NO_WINDOW


def test_a_file_reached_through_a_folder_link_is_shown_where_it_really_is(monkeypatch, tmp_path):
    calls = _capture_run(monkeypatch)
    pictures = tmp_path / "library" / "images"
    pictures.mkdir(parents=True)
    (pictures / "picture_00001_.png").write_bytes(b"")
    _winapi.CreateJunction(str(pictures), str(tmp_path / "saves"))

    reveal.show_in_explorer(tmp_path / "saves" / "picture_00001_.png")

    (cmd,), _ = calls[0]
    assert cmd == ["explorer", "/select,", str(pictures / "picture_00001_.png")]
