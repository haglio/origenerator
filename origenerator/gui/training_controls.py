from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget
from shared_ui.spacing import GAP_SMALL

from origenerator.gui.basic_section import reveal_button
from origenerator.lora_training import TrainingOffer
from origenerator.reveal import open_in_explorer


class TrainingControls(QWidget):
    train_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(GAP_SMALL)
        self.train = QPushButton()
        self.pictures = QLabel()
        self.folder = reveal_button()
        for widget in (self.train, self.pictures, self.folder):
            row.addWidget(widget)
        self._folder: Path | None = None
        self.train.clicked.connect(self.train_requested)
        self.folder.clicked.connect(self._open_folder)
        self.hide()

    def show_offer(self, offer: TrainingOffer | None, running: str | None = None) -> None:
        self.setVisible(offer is not None)
        if offer is None:
            return
        self._folder = offer.folder
        self.train.setText(running or offer.label)
        self.train.setEnabled(offer.enabled and running is None)
        self.train.setToolTip(offer.tooltip)
        self.pictures.setText(f"{offer.pictures} {offer.counted}{'' if offer.pictures == 1 else 's'}")
        self.pictures.setToolTip(str(offer.folder))
        self.folder.setToolTip(f"Open {offer.folder} in Explorer")

    def _open_folder(self) -> None:
        self._folder.mkdir(parents=True, exist_ok=True)
        open_in_explorer(self._folder)
