from __future__ import annotations

from pathlib import Path

import pytest

from origenerator.app_state import AppState


def test_a_state_file_that_was_never_written_reads_at_the_defaults(tmp_path):
    state = AppState(tmp_path / "ui_state.json")
    assert state.get("missing", "fallback") == "fallback"


def test_set_then_save_persists_across_reload(tmp_path):
    path = tmp_path / "ui_state.json"
    state = AppState(path)
    state.set("gallery_folder", ["image", "sdxl_t2i"])
    state.save()

    reloaded = AppState(path)
    assert reloaded.get("gallery_folder") == ["image", "sdxl_t2i"]


def test_a_save_with_nothing_changed_leaves_what_another_window_wrote_alone(tmp_path):
    path = tmp_path / "ui_state.json"
    state = AppState(path)
    state.set("gallery_folder", "image/sdxl_t2i")
    state.save()
    path.write_text('{"gallery_folder": "video/wan22_i2v"}', encoding="utf-8")

    state.save()

    assert AppState(path).get("gallery_folder") == "video/wan22_i2v"


def test_corrupt_file_loads_as_empty(tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text("{not valid json", encoding="utf-8")
    state = AppState(path)
    assert state.get("anything", "default") == "default"


def test_non_object_json_loads_as_empty(tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert AppState(path).get("anything") is None


def test_a_save_leaves_only_the_state_file_in_its_folder(tmp_path):
    path = tmp_path / "ui_state.json"
    state = AppState(path)
    state.set("gallery_folder", "image/sdxl_t2i")

    state.save()

    assert [entry.name for entry in tmp_path.iterdir()] == ["ui_state.json"]


def test_a_save_makes_the_folder_it_goes_in(tmp_path):
    path = tmp_path / "state" / "ui_state.json"
    state = AppState(path)
    state.set("gallery_folder", "image/sdxl_t2i")

    state.save()

    assert AppState(path).get("gallery_folder") == "image/sdxl_t2i"


def test_a_save_cut_off_part_way_leaves_the_last_state_file_whole(tmp_path, monkeypatch):
    path = tmp_path / "ui_state.json"
    state = AppState(path)
    state.set("gallery_folder", "image/sdxl_t2i")
    state.save()
    last_saved = path.read_text(encoding="utf-8")
    write_text = Path.write_text

    def write_half_then_fail(self, text, *args, **kwargs):
        write_text(self, text[: len(text) // 2], *args, **kwargs)
        raise OSError("the disk filled part-way through the write")

    monkeypatch.setattr(Path, "write_text", write_half_then_fail)
    state.set("gallery_folder", "video/wan_i2v")

    with pytest.raises(OSError, match="the disk filled"):
        state.save()

    assert path.read_text(encoding="utf-8") == last_saved, (
        "the state is written to a .tmp file and then put in the real file's place, so a save "
        "cut off part-way leaves the old file whole rather than a cut-off one"
    )
