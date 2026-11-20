from __future__ import annotations

import json
import os

from app_support.file_channel import read_whole, write_whole
from app_support.threading_utils import wait_until
from PySide6.QtWidgets import QApplication

from origenerator.gallery_names_file import NamesFile
from origenerator.gui.published_names import PublishedNames

_NAMES = {"wan_loop_00042_": "3FA9C0D2 004"}


def test_the_names_are_written_where_fun_time_reads_them(tmp_path):
    path = tmp_path / "gallery_names.json"

    NamesFile(path).publish(_NAMES)

    assert json.loads(path.read_text(encoding="utf-8")) == _NAMES


def test_names_already_in_the_file_when_the_app_opens_are_not_written_again(tmp_path):
    path = tmp_path / "gallery_names.json"
    NamesFile(path).publish(_NAMES)
    os.utime(path, ns=(0, 0))

    NamesFile(path).publish(_NAMES)

    assert path.stat().st_mtime_ns == 0


def test_rebuilds_with_no_name_changed_neither_read_nor_write_the_file(tmp_path):
    path = tmp_path / "gallery_names.json"
    touched = []

    def read(at):
        touched.append("read")
        return read_whole(at)

    def write(at, text):
        touched.append("write")
        write_whole(at, text)

    names_file = NamesFile(path, read=read, write=write)
    for _rebuild in range(4):
        names_file.publish(dict(_NAMES))

    assert touched == ["read", "write"]


class _HeldWork:
    def __init__(self):
        self.waiting = []

    def run(self, work, done, *, owner):
        self.waiting.append((work, done))

    def finish_one(self):
        work, done = self.waiting.pop(0)
        done(work())


class _Kept:
    def __init__(self):
        self.published = []

    def publish(self, names):
        self.published.append(names)


def test_the_window_hands_the_names_over_and_writes_nothing_itself(qtbot):
    kept, held = _Kept(), _HeldWork()
    names = PublishedNames(kept, run=held.run)

    names.publish(_NAMES)

    assert (kept.published, len(held.waiting)) == ([], 1)


def test_names_handed_over_while_a_write_is_out_wait_and_only_the_newest_is_written(qtbot):
    kept, held = _Kept(), _HeldWork()
    names = PublishedNames(kept, run=held.run)
    names.publish({"a_": "first"})
    names.publish({"a_": "second"})
    names.publish({"a_": "third"})

    while held.waiting:
        held.finish_one()

    assert kept.published == [{"a_": "first"}, {"a_": "third"}], (
        "one write at a time, so an older list can never land on top of a newer one")


def test_the_names_reach_the_file_from_another_thread(qtbot, tmp_path):
    path = tmp_path / "gallery_names.json"

    PublishedNames(NamesFile(path)).publish(_NAMES)

    wait_until(path.exists, pump=QApplication.processEvents)
    assert json.loads(path.read_text(encoding="utf-8")) == _NAMES
