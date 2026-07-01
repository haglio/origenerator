from origenerator import config
from origenerator.workflows.model_files import list_model_files


def test_lists_sorted_model_files_from_the_category_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    loras = tmp_path / "models" / "loras"
    loras.mkdir(parents=True)
    (loras / "b.safetensors").touch()
    (loras / "a.safetensors").touch()
    (loras / "notes.txt").touch()   # not a model file — skipped
    (loras / "nested").mkdir()      # a subfolder — skipped
    assert list_model_files("loras", ["fallback.safetensors"]) == [
        "a.safetensors", "b.safetensors",
    ]


def test_falls_back_when_the_category_dir_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)  # no models/loras at all
    assert list_model_files("loras", ["default.safetensors"]) == ["default.safetensors"]


def test_falls_back_when_the_category_dir_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "COMFYUI_DIR", tmp_path)
    (tmp_path / "models" / "loras").mkdir(parents=True)
    assert list_model_files("loras", ["default.safetensors"]) == ["default.safetensors"]
