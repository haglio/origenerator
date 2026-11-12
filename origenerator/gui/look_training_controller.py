from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import QMessageBox

from origenerator import config, look_training, lora_training
from origenerator.gui.lora_offers import trashed
from origenerator.gui.training_run import TrainingRun


class LookTrainingController:
    def __init__(self, jobs, *, info_tabs_of: Callable[[], object], parent, trash=trashed):
        self._trash_version = trash
        self._jobs = jobs
        self._info_tabs_of = info_tabs_of
        self._parent = parent
        self._training: TrainingRun | None = None

    def wire(self, tab) -> None:
        tab.train_requested.connect(lambda key, tab=tab: self._train(tab, key))
        tab.trash_requested.connect(lambda key, tab=tab: self._trash(tab, key))

    def _trash(self, tab, key: str) -> None:
        lora = tab.lora_value(key)
        if not self._trash_version(lora, self._parent):
            return
        for each in self._info_tabs_of().generate_tabs():
            each.lora_offers.stop_offering(lora)
        tab.lora_offers.switch_from_trashed(key)

    def _train(self, tab, key: str) -> None:
        base = look_training.trainable_base_of(tab.lora_value(key))
        if self._training is not None or base is None:
            return
        folder = look_training.images_folder(base)
        refusal = lora_training.why_it_cannot_train(
            (config.KREA2_TRAINING_PYTHON, config.KREA2_TRAINING_SCRIPTS),
            ("krea2_training_python", "krea2_training_scripts"), base,
            folder, bool(lora_training.image_files(folder)))
        if refusal is not None:
            QMessageBox.information(self._parent, "Train", refusal)
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
            reveal=lambda: self._info_tabs_of().setCurrentWidget(tab) if tab is not None else None,
            parent=self._parent)
        self._training.progress.connect(lambda text: self._show(job["base"], text))
        self._training.finished.connect(lambda lora: self._ended(job, lora, tab, key))
        self._training.failed.connect(lambda why: self._ended(job, None, tab, key, why))
        self._training.canceled.connect(lambda: self._ended(job, None, tab, key))
        return self._training

    def _show(self, base: str, text: str | None) -> None:
        for tab in self._info_tabs_of().generate_tabs():
            tab.lora_offers.show_training(base, text)

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
