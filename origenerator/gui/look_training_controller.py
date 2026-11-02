from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QMessageBox

from origenerator import config, look_training, lora_training
from origenerator.gui.training_run import TrainingRun

NO_PROGRAM = ("No training program is set up: content.local.json names no "
              "krea2_training_python and krea2_training_scripts.")


class LookTrainingController:
    def __init__(self, jobs, *, tabs: Callable[[], list], show_tab: Callable[[object], None],
                 parent):
        self._jobs = jobs
        self._tabs = tabs
        self._show_tab = show_tab
        self._parent = parent
        self._training: TrainingRun | None = None

    def wire(self, tab) -> None:
        tab.train_requested.connect(lambda key, tab=tab: self._train(tab, key))

    def _train(self, tab, key: str) -> None:
        base = look_training.trainable_base_of(tab.lora_value(key))
        if self._training is not None or base is None:
            return
        if config.KREA2_TRAINING_PYTHON is None or config.KREA2_TRAINING_SCRIPTS is None:
            QMessageBox.information(self._parent, "Train", NO_PROGRAM)
            return
        folder = look_training.pictures_folder(base)
        folder.mkdir(parents=True, exist_ok=True)
        if not look_training.picture_files(folder):
            QMessageBox.information(self._parent, "Train",
                                    f"Put pictures of {base} in {folder}, then press Train again.")
            return
        self._watch(look_training.training_job(base), tab, key).begin()

    def take_up_trainings(self) -> None:
        lora_training.take_up(look_training, adopt=self._adopt, take=self._take)

    def _adopt(self, job: dict, trainer) -> None:
        if self._training is None:
            self._watch(job).adopt(trainer)

    def _watch(self, job: dict, tab=None, key: str | None = None) -> TrainingRun:
        self._training = TrainingRun(
            job, self._jobs, look_training,
            reveal=lambda: self._show_tab(tab) if tab is not None else None,
            parent=self._parent)
        self._training.progress.connect(lambda text: self._show(job["base"], text))
        self._training.finished.connect(lambda lora: self._ended(job, lora, tab, key))
        self._training.failed.connect(lambda why: self._ended(job, None, tab, key, why))
        self._training.canceled.connect(lambda: self._ended(job, None, tab, key))
        return self._training

    def _show(self, base: str, text: str | None) -> None:
        for tab in self._tabs():
            tab.show_training(base, text)

    def _ended(self, job: dict, lora: str | None, tab, key, why: str = "") -> None:
        self._training = None
        self._show(job["base"], None)
        if lora:
            self._take(job, lora, tab, key)
        elif why:
            QMessageBox.warning(self._parent, "Train", why)

    def _take(self, job: dict, lora: str, tab=None, key: str | None = None) -> None:
        look_training.take(job)
        trainer = lora_training.trainer_of(job)
        if trainer is not None:
            look_training.note_duration(lora_training.time_taken(job, trainer))
        lora_training.mark_taken(job)
        if tab is not None:
            tab.pick_lora(key, lora)
