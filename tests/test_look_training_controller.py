from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from origenerator import config, look_training, lora_training
from origenerator.gui import look_training_controller as module
from origenerator.gui.look_training_controller import LookTrainingController
from origenerator.model_titles import model_title
from origenerator.trigger_words import trigger_words_by_lora
from tests.test_enhance_controller import FakeSignal


class FakeGenerateTab:
    def __init__(self, lora="example_look.safetensors"):
        self.train_requested = FakeSignal()
        self.lora = lora
        self.shown: list = []
        self.picked: list = []

    def lora_value(self, key):
        return self.lora

    def show_training(self, base, text):
        self.shown.append((base, text))

    def pick_lora(self, key, lora):
        self.picked.append((key, lora))
        return True


_runs: list = []


class FakeTrainingRun:
    def __init__(self, job, queue, kind, *, reveal, parent=None):
        self.job, self.queue, self.kind, self.reveal = job, queue, kind, reveal
        self.progress, self.finished, self.failed = FakeSignal(), FakeSignal(), FakeSignal()
        self.canceled = FakeSignal()
        self.began = False
        self.adopted = None
        _runs.append(self)

    def begin(self):
        self.began = True

    def adopt(self, trainer):
        self.adopted = trainer


@pytest.fixture
def look(monkeypatch, tmp_path, installed_models, titled_models, worded_loras):
    folder = tmp_path / "pictures"
    folder.mkdir()
    monkeypatch.setattr(look_training, "load_content", lambda: {"trainable_loras": {"Example Look": {
        "pictures": str(folder), "base_model": "example_raw.safetensors",
        "text_encoder": "example_te.safetensors", "vae": "example_vae.safetensors"}}})
    monkeypatch.setattr(config, "LOOK_TRAINING_DIR", tmp_path / "lora training")
    monkeypatch.setattr(config, "KREA2_TRAINING_PYTHON", tmp_path / "musubi" / "python.exe")
    monkeypatch.setattr(config, "KREA2_TRAINING_SCRIPTS", tmp_path / "musubi")
    monkeypatch.setattr(module, "TrainingRun", FakeTrainingRun)
    titled_models({"example_look": "Example Look 1.0"})
    worded_loras({"example_look": ["zz"]})
    installed_models.add("loras", "example_look.safetensors", arch="krea2", lora=True)
    _runs.clear()
    return folder


def _controller(tabs, shown=None):
    return LookTrainingController(SimpleNamespace(), tabs=lambda: tabs,
                                  show_tab=([] if shown is None else shown).append, parent=None)


def _told(monkeypatch, kind="information") -> list:
    told = []
    monkeypatch.setattr(module.QMessageBox, kind, lambda parent, title, text: told.append(text))
    return told


def test_train_with_no_training_program_set_up_says_so(look, monkeypatch):
    monkeypatch.setattr(config, "KREA2_TRAINING_PYTHON", None)
    told = _told(monkeypatch)
    tab = FakeGenerateTab()
    controller = _controller([tab])
    controller.wire(tab)

    tab.train_requested.emit("lora")

    assert told == [module.NO_PROGRAM]
    assert _runs == []


def test_train_with_no_pictures_makes_the_folder_and_says_to_put_them_there(look, monkeypatch):
    told = _told(monkeypatch)
    tab = FakeGenerateTab()
    controller = _controller([tab])
    controller.wire(tab)
    look.rmdir()

    tab.train_requested.emit("lora")

    assert look.is_dir()
    assert str(look) in told[0]
    assert "Example Look" in told[0]
    assert _runs == []


def test_train_trains_the_next_version_of_the_picked_lora_and_one_at_a_time(look, monkeypatch):
    (look / "one.jpg").write_bytes(b"")
    tab, other = FakeGenerateTab(), FakeGenerateTab(lora="None")
    controller = _controller([tab, other])
    for each in (tab, other):
        controller.wire(each)

    tab.train_requested.emit("lora")
    tab.train_requested.emit("lora")
    other.train_requested.emit("lora")

    (run,) = _runs
    assert run.began
    assert run.kind is look_training
    assert (run.job["base"], run.job["output_name"]) == ("Example Look", "Example Look 1.1")
    run.progress.emit("Training 10%")
    assert tab.shown == [("Example Look", "Training 10%")]
    assert other.shown == [("Example Look", "Training 10%")]


def test_a_finished_training_gives_the_version_its_title_and_word_and_picks_it_in_the_tab(
        look, monkeypatch):
    (look / "one.jpg").write_bytes(b"")
    tab = FakeGenerateTab()
    controller = _controller([tab])
    controller.wire(tab)
    tab.train_requested.emit("lora")
    (run,) = _runs
    Path(run.job["work"]).mkdir(parents=True)
    Path(run.job["status"]).write_text(json.dumps({"state": "done", "lora": run.job["lora"]}),
                                       encoding="utf-8")

    run.finished.emit(run.job["lora"])

    assert tab.picked == [("lora", "Example Look 1.1.safetensors")]
    assert tab.shown[-1] == ("Example Look", None)
    assert model_title("Example Look 1.1.safetensors") == "Example Look 1.1"
    assert trigger_words_by_lora()["Example Look 1.1"] == ["zz"]
    assert lora_training.untaken_lora(run.job) is None
    tab.train_requested.emit("lora")
    assert len(_runs) == 2


def test_a_failed_training_says_why_and_lets_another_start(look, monkeypatch):
    warned = _told(monkeypatch, "warning")
    (look / "one.jpg").write_bytes(b"")
    tab = FakeGenerateTab()
    controller = _controller([tab])
    controller.wire(tab)
    tab.train_requested.emit("lora")
    (run,) = _runs

    run.failed.emit("The graphics card ran out of memory while training.")

    assert warned == ["The graphics card ran out of memory while training."]
    assert tab.picked == []
    tab.train_requested.emit("lora")
    assert len(_runs) == 2


def test_going_to_a_training_from_the_queue_shows_the_tab_that_asked_for_it(look):
    (look / "one.jpg").write_bytes(b"")
    tab = FakeGenerateTab()
    shown = []
    controller = _controller([tab], shown)
    controller.wire(tab)
    tab.train_requested.emit("lora")
    (run,) = _runs

    run.reveal()

    assert shown == [tab]


def _kept_training(tmp_path, **status) -> dict:
    work = tmp_path / "lora training" / "Example Look"
    work.mkdir(parents=True)
    job = {"base": "Example Look", "output_name": "Example Look 1.1", "display_name": "Example Look 1.1",
           "lora": "Example Look 1.1.safetensors", "trigger_words": ["zz"],
           **lora_training.work_files(work)}
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    if status:
        Path(job["status"]).write_text(json.dumps(status), encoding="utf-8")
    return job


def test_a_training_an_earlier_launch_left_running_is_taken_up(look, tmp_path, monkeypatch):
    _kept_training(tmp_path)
    trainer = SimpleNamespace(running=lambda: True, began=0.0)
    monkeypatch.setattr(lora_training, "trainer_of", lambda job: trainer)
    controller = _controller([])

    controller.take_up_trainings()

    (run,) = _runs
    assert run.adopted is trainer
    assert run.job["base"] == "Example Look"
    run.reveal()


def test_a_version_finished_while_the_app_was_closed_gets_its_title_once(look, tmp_path, monkeypatch):
    _kept_training(tmp_path, state="done", lora="Example Look 1.1.safetensors")
    monkeypatch.setattr(lora_training, "trainer_of",
                        lambda job: SimpleNamespace(running=lambda: False, began=0.0))
    controller = _controller([])

    controller.take_up_trainings()
    controller.take_up_trainings()

    assert model_title("Example Look 1.1.safetensors") == "Example Look 1.1"
    assert _runs == []
