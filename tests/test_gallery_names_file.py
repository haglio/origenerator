from __future__ import annotations

import json
import os

from origenerator import gallery_names_file


def test_the_names_are_written_where_fun_time_reads_them(tmp_path):
    path = tmp_path / "gallery_names.json"

    gallery_names_file.publish({"wan_loop_00042_": "3FA9C0D2 004"}, path=path)

    assert json.loads(path.read_text(encoding="utf-8")) == {"wan_loop_00042_": "3FA9C0D2 004"}


def test_names_that_have_not_changed_are_not_written_again(tmp_path):
    path = tmp_path / "gallery_names.json"
    gallery_names_file.publish({"wan_loop_00042_": "3FA9C0D2 004"}, path=path)
    os.utime(path, ns=(0, 0))

    gallery_names_file.publish({"wan_loop_00042_": "3FA9C0D2 004"}, path=path)

    assert path.stat().st_mtime_ns == 0
