from origenerator.app_state import AppState


def test_get_returns_default_when_file_missing(tmp_path):
    state = AppState(tmp_path / "ui_state.json")
    assert state.get("missing", "fallback") == "fallback"


def test_set_then_save_persists_across_reload(tmp_path):
    path = tmp_path / "ui_state.json"
    state = AppState(path)
    state.set("gallery_folder", ["image", "sdxl_t2i"])
    state.save()

    reloaded = AppState(path)
    assert reloaded.get("gallery_folder") == ["image", "sdxl_t2i"]


def test_corrupt_file_loads_as_empty(tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text("{not valid json", encoding="utf-8")
    state = AppState(path)
    assert state.get("anything", "default") == "default"


def test_non_object_json_loads_as_empty(tmp_path):
    path = tmp_path / "ui_state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    assert AppState(path).get("anything") is None
