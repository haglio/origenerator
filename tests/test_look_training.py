from __future__ import annotations

import json
from pathlib import Path

from origenerator import config, look_training, lora_training
from origenerator.lora_training import TrainingState
from origenerator.model_titles import model_title
from origenerator.trigger_words import trigger_words_by_lora
from origenerator.workflows.model_files import NO_LORA

_PICTURES = Path("C:/example/pictures")


def _trainable(monkeypatch, tmp_path, **loras):
    folder = tmp_path / "pictures"
    folder.mkdir(exist_ok=True)
    content = {"trainable_loras": loras or {"Example Look": {
        "pictures": str(folder), "base_model": "example_raw.safetensors",
        "text_encoder": "example_te.safetensors", "vae": "example_vae.safetensors"}}}
    monkeypatch.setattr(look_training, "load_content", lambda: content)
    monkeypatch.setattr(config, "LOOK_TRAINING_DIR", tmp_path / "lora training")
    monkeypatch.setattr(config, "KREA2_TRAINING_PYTHON", tmp_path / "musubi" / "python.exe")
    monkeypatch.setattr(config, "KREA2_TRAINING_SCRIPTS", tmp_path / "musubi")
    return folder


def _installed(installed_models, titled_models, worded_loras, *versions):
    titled_models({Path(name).name: title for name, title in versions})
    worded_loras({Path(versions[-1][0]).name: ["zz"]} if versions else {})
    for name, _title in versions:
        installed_models.add("loras", f"{name}.safetensors", arch="krea2", lora=True)


def test_a_picked_lora_is_trainable_when_its_titles_base_is_one_the_overlay_names(
        monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    _trainable(monkeypatch, tmp_path)
    _installed(installed_models, titled_models, worded_loras,
               ("example_look", "Example Look 1.0"), ("example_style", "Example Style 1.0"))

    assert look_training.trainable_base_of("example_look.safetensors") == "Example Look"
    assert look_training.trainable_base_of("example_style.safetensors") is None
    assert look_training.trainable_base_of(NO_LORA) is None


def test_a_lora_of_another_family_than_the_entrys_base_model_is_no_version_of_it(
        monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    _trainable(monkeypatch, tmp_path)
    installed_models.add("diffusion_models", "example_raw.safetensors", arch="krea2")
    titled_models({"example_look": "Example Look 1.0", "example_look_sdxl": "Example Look 1.1"})
    worded_loras({})
    installed_models.add("loras", "example_look.safetensors", arch="krea2", lora=True)
    installed_models.add("loras", "example_look_sdxl.safetensors", arch="sdxl", lora=True)

    assert look_training.trainable_base_of("example_look.safetensors") == "Example Look"
    assert look_training.trainable_base_of("example_look_sdxl.safetensors") is None
    assert look_training.training_job("Example Look")["output_name"] == "Example Look 1.1"


def test_only_pictures_in_the_folder_are_trained_on_whatever_their_kind(tmp_path):
    for name in ("b.jpg", "a.PNG", "c.webp", "d.avif", "e.gif", "notes.txt", "f.mp4"):
        (tmp_path / name).write_bytes(b"")

    assert [path.name for path in look_training.picture_files(tmp_path)] == [
        "a.PNG", "b.jpg", "c.webp", "d.avif", "e.gif"]
    assert look_training.picture_files(tmp_path / "not made yet") == []


def test_a_look_is_out_of_date_until_a_training_keeps_its_pictures_then_current_until_one_changes(
        monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    folder = _trainable(monkeypatch, tmp_path)
    (folder / "one.jpg").write_bytes(b"one")
    assert look_training.training_state("Example Look") is TrainingState.UNTRAINED

    _installed(installed_models, titled_models, worded_loras, ("example_look", "Example Look 1.0"))
    assert look_training.training_state("Example Look") is TrainingState.OUT_OF_DATE

    record = tmp_path / "lora training" / "Example Look" / "trained.json"
    record.parent.mkdir(parents=True)
    record.write_text(json.dumps({"photo_stamps": look_training.picture_stamps("Example Look")}),
                      encoding="utf-8")
    assert look_training.training_state("Example Look") is TrainingState.CURRENT

    (folder / "one.jpg").write_bytes(b"one, retouched")
    assert look_training.training_state("Example Look") is TrainingState.OUT_OF_DATE


def test_a_training_job_names_the_next_version_its_word_its_pictures_and_its_models(
        monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    folder = _trainable(monkeypatch, tmp_path)
    (folder / "one.jpg").write_bytes(b"one")
    _installed(installed_models, titled_models, worded_loras,
               ("example_look", "Example Look 1.0"), ("looks/example_look_1_1", "Example Look 1.1"))
    models = config.COMFYUI_DIR / "models"

    job = look_training.training_job("Example Look")

    assert job["base"] == "Example Look"
    assert job["pictures_folder"] == str(folder)
    assert list(job["picture_stamps"]) == ["pictures/one.jpg"]
    assert job["output_name"] == "Example Look 1.2"
    assert job["display_name"] == "Example Look 1.2"
    assert job["lora_folder"] == str(models / "loras" / "looks")
    assert job["lora"] == str(Path("looks") / "Example Look 1.2.safetensors")
    assert job["trigger_words"] == ["zz"]
    assert job["base_model"] == str(models / "diffusion_models" / "example_raw.safetensors")
    assert job["text_encoder"] == str(models / "text_encoders" / "example_te.safetensors")
    assert job["vae"] == str(models / "vae" / "example_vae.safetensors")
    assert job["scripts"] == str(tmp_path / "musubi")
    assert (job["steps"], job["save_every"]) == (1500, 25)
    assert job["comfyui"] == f"http://{config.COMFYUI_HOST}:{config.COMFYUI_PORT}"
    assert job["work"] == str(tmp_path / "lora training" / "Example Look")
    assert job["status"] == str(tmp_path / "lora training" / "Example Look" / "status.json")


def test_the_next_version_trains_on_the_word_the_overlay_names_for_it_over_the_newest_versions(
        monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    folder = tmp_path / "pictures"
    folder.mkdir()
    _trainable(monkeypatch, tmp_path, **{"Example Look": {
        "pictures": str(folder), "base_model": "example_raw.safetensors",
        "text_encoder": "example_te.safetensors", "vae": "example_vae.safetensors",
        "trigger_words": ["qq"]}})
    _installed(installed_models, titled_models, worded_loras, ("example_look", "Example Look 1.0"))

    assert look_training.training_job("Example Look")["trigger_words"] == ["qq"]


def test_a_first_version_goes_in_the_loras_folder_itself_with_no_word(
        monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    _trainable(monkeypatch, tmp_path)
    _installed(installed_models, titled_models, worded_loras)

    job = look_training.training_job("Example Look")

    assert job["output_name"] == "Example Look 1.0"
    assert job["lora_folder"] == str(config.COMFYUI_DIR / "models" / "loras")
    assert job["lora"] == "Example Look 1.0.safetensors"
    assert job["trigger_words"] == []


def test_a_training_runs_the_look_trainer_under_musubis_python(monkeypatch, tmp_path):
    _trainable(monkeypatch, tmp_path)
    started = []
    monkeypatch.setattr(lora_training, "start",
                        lambda job, python, trainer, **more: started.append((python, trainer, more)))
    job = {"base": "Example Look", **lora_training.work_files(tmp_path / "work")}

    look_training.start(job)

    assert started == [(tmp_path / "musubi" / "python.exe", look_training.TRAINER, {})]


def test_look_trainings_are_kept_apart_from_the_fixes(monkeypatch, tmp_path):
    _trainable(monkeypatch, tmp_path)
    work = tmp_path / "lora training" / "Example Look"
    work.mkdir(parents=True)
    job = {"base": "Example Look", **lora_training.work_files(work)}
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")

    assert look_training.trainings() == [job]
    assert look_training.running_trainings() == []
    assert look_training.typical_seconds() is None
    look_training.note_duration(3600.0)
    assert look_training.typical_seconds() == 3600.0


def test_taking_a_finished_version_gives_it_its_title_and_its_word(
        monkeypatch, tmp_path, titled_models, worded_loras):
    _trainable(monkeypatch, tmp_path)
    titled_models({"example_look": "Example Look 1.0"})
    worded_loras({"example_look": ["zz"]})
    job = {"base": "Example Look", "output_name": "Example Look 1.1",
           "lora": str(Path("looks") / "Example Look 1.1.safetensors"), "trigger_words": ["zz"]}

    look_training.take(job)

    assert model_title("looks\\Example Look 1.1.safetensors") == "Example Look 1.1"
    assert trigger_words_by_lora() == {"example_look": ["zz"], "Example Look 1.1": ["zz"]}


def test_what_a_trainable_lora_offers_beside_its_dropdown(
        monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    folder = _trainable(monkeypatch, tmp_path)
    for name in ("one.jpg", "two.png", "notes.txt"):
        (folder / name).write_bytes(b"")
    _installed(installed_models, titled_models, worded_loras, ("example_look", "Example Look 1.0"))

    offer = look_training.training_offer("Example Look")

    assert (offer.label, offer.enabled, offer.pictures, offer.folder) == ("Retrain", True, 2, folder)
    assert "Example Look" in offer.tooltip and str(folder) in offer.tooltip
    assert "generations come first" in offer.tooltip
