"""Whether a file is there, answered from one listing of its folder for the
length of one look.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import os

from origenerator import one_look
from origenerator.one_look import is_file, looking_once


def _write(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def _counting_listings(monkeypatch) -> list:
    listed = []
    scandir = os.scandir
    monkeypatch.setattr(one_look.os, "scandir",
                        lambda folder: listed.append(str(folder)) or scandir(folder))
    return listed


def test_within_one_look_a_folder_is_listed_once_however_many_of_its_files_are_asked_after(
        tmp_path, monkeypatch):
    for n in range(3):
        _write(tmp_path / f"scene{n}.png")
    listed = _counting_listings(monkeypatch)

    with one_look.one_look():
        found = [is_file(tmp_path / f"scene{n}.png") for n in range(4)]

    assert (found, listed) == ([True, True, True, False], [str(tmp_path)])


def test_a_file_written_after_a_look_is_found_by_the_next_one(tmp_path):
    with one_look.one_look():
        assert not is_file(tmp_path / "late.png")

    _write(tmp_path / "late.png")

    with one_look.one_look():
        assert is_file(tmp_path / "late.png")


def test_a_folder_is_no_file(tmp_path):
    (tmp_path / "inside").mkdir()

    with one_look.one_look():
        assert not is_file(tmp_path / "inside")


def test_a_look_taken_inside_another_lists_nothing_again(tmp_path, monkeypatch):
    _write(tmp_path / "scene.png")
    listed = _counting_listings(monkeypatch)

    @looking_once
    def asked_again():
        return is_file(tmp_path / "scene.png")

    with one_look.one_look():
        assert is_file(tmp_path / "scene.png") and asked_again()

    assert listed == [str(tmp_path)]
