from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtWidgets import QMessageBox

from origenerator import look_training
from origenerator.lora_versions import trash_old_version
from origenerator.workflows.model_files import NO_LORA


def trashed(lora: str, parent, *, trash=trash_old_version) -> bool:
    try:
        trash(lora)
    except OSError as refused:
        QMessageBox.warning(parent, "Trash", str(refused))
        return False
    return True


def _offer_each_row(form, workflow, offered: dict, running: dict, every_row: bool) -> None:
    values = form.get_values()
    for key in workflow.lora_keys:
        if not every_row and offered.get(key, NO_LORA) == values.get(key):
            continue
        offered[key] = values.get(key)
        base = look_training.trainable_base_of(values.get(key))
        form.training.offer(
            key, look_training.training_offer(base, values.get(key)) if base else None,
            running.get(base))


def _note_training(running: dict, base: str, text: str | None) -> None:
    if text is None:
        running.pop(base, None)
    else:
        running[base] = text


def _take_off_the_options(form, workflow, lora: str) -> None:
    for definition in form.definitions():
        if definition.key in workflow.lora_keys:
            definition.options = [option for option in definition.options if option != lora]
    form.changed.emit()


def _resolve(form, key: str) -> None:
    form.resolve_warnings([key])


def _listen_to(form, offers, train, trash) -> None:
    form.training.listen(train=train, trash=trash)
    form.changed.connect(offers.offer)


class LoraOffers:
    def __init__(self, form_of: Callable, workflow_of: Callable, *, train, trash):
        self._form_of = form_of
        self._workflow_of = workflow_of
        self._train = train
        self._trash = trash
        self._running: dict[str, str] = {}
        self._offered: dict[str, object] = {}

    def form_replaced(self) -> None:
        self._offered = {}
        _listen_to(self._form_of(), self, self._train, self._trash)

    def offer(self, every_row: bool = False) -> None:
        form, workflow = self._form_of(), self._workflow_of()
        if form is not None and workflow is not None:
            _offer_each_row(form, workflow, self._offered, self._running, every_row)

    def show_training(self, base: str, text: str | None) -> None:
        _note_training(self._running, base, text)
        self.offer(every_row=True)

    def stop_offering(self, lora: str) -> None:
        form, workflow = self._form_of(), self._workflow_of()
        if form is not None and workflow is not None:
            _take_off_the_options(form, workflow, lora)
            self.offer(every_row=True)

    def switch_from_trashed(self, key: str) -> None:
        _resolve(self._form_of(), key)
