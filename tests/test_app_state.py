from __future__ import annotations

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
