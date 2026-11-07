from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from shared_ui.spacing import GAP_SMALL

from origenerator.gui import icons
from origenerator.gui.copy_button import IconButton
from origenerator.gui.metadata_section import reveal_button
from origenerator.lora_training import TrainingOffer
from origenerator.reveal import open_in_explorer


def _show_offer_on(controls: dict, key: str, offer, running) -> None:
    controls[key].show_offer(offer, running)


def _shown_with_tip(button, shown: bool, tip: str) -> None:
    button.setVisible(shown)
    button.setToolTip(tip)


class TrainingControls(QWidget):
    train_requested = pyqtSignal()
    trash_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_SMALL)
        train = QPushButton()
        trash = IconButton(icons.delete_icon(), "", "deleteButton")
        folder = reveal_button()
        self.train, self.trash, self.folder = train, trash, folder
        self.images = QLabel()
        for widget in (self.train, self.trash, self.images, self.folder):
            row.addWidget(widget)
        self._folder: Path | None = None
        train.clicked.connect(self.train_requested)
        trash.clicked.connect(self.trash_requested)
        folder.clicked.connect(self._open_folder)
        self.hide()

    def show_offer(self, offer: TrainingOffer | None, running: str | None = None) -> None:
        self.setVisible(offer is not None)
        if offer is None:
            return
        self._folder = offer.folder
        self.train.setText(running or offer.label)
        self.train.setEnabled(offer.enabled and running is None)
        self.train.setToolTip(offer.tooltip)
        offers_the_trash = offer.trash_tooltip is not None and running is None
        self.train.setVisible(not offers_the_trash)
        _shown_with_tip(self.trash, offers_the_trash, offer.trash_tooltip or "")
        self.images.setText(f"{offer.images} image{'' if offer.images == 1 else 's'}")
        self.images.setToolTip(str(offer.folder))
        self.folder.setToolTip(f"Open {offer.folder} in Explorer")

    def _open_folder(self) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        open_in_explorer(self._folder)


class TrainingRows:
    def __init__(self):
        self.controls: dict[str, TrainingControls] = {}
        self._train = self._trash = lambda _key: None

    def listen(self, *, train, trash) -> None:
        self._train, self._trash = train, trash

    def controls_for(self, key: str) -> TrainingControls:
        controls = TrainingControls()
        controls.train_requested.connect(lambda: self._train(key))
        controls.trash_requested.connect(lambda: self._trash(key))
        self.controls[key] = controls
        return controls

    def offer(self, key: str, offer: TrainingOffer | None, running: str | None = None) -> None:
        _show_offer_on(self.controls, key, offer, running)
