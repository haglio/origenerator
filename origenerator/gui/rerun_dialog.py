import json
import random

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPlainTextEdit, QLineEdit, QCheckBox, QPushButton,
)

from origenerator.gui.image_picker import ImagePickerDialog

_SEED_MAX = (1 << 63) - 1


class ReRunDialog(QDialog):
    """Edit prompt / seed / input image, then re-run a generation's captured graph.

    Prefilled from the selected row; the chosen overrides are read back via
    :meth:`overrides` and applied to the stored graph by the replay engine.
    """

    def __init__(self, row: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Re-run: {row.get('workflow_name') or 'workflow'}")
        self.setMinimumWidth(460)
        try:
            params = json.loads(row.get("params_json") or "{}")
        except json.JSONDecodeError:
            params = {}

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Positive prompt"))
        self._positive = QPlainTextEdit(row.get("positive_prompt") or "")
        self._positive.setMaximumHeight(90)
        layout.addWidget(self._positive)

        layout.addWidget(QLabel("Negative prompt"))
        self._negative = QPlainTextEdit(row.get("negative_prompt") or "")
        self._negative.setMaximumHeight(60)
        layout.addWidget(self._negative)

        seed_row = QHBoxLayout()
        seed_row.addWidget(QLabel("Seed"))
        seed = row.get("seed")
        self._seed = QLineEdit("" if seed is None else str(seed))
        seed_row.addWidget(self._seed, 1)
        self._random = QCheckBox("Random")
        seed_row.addWidget(self._random)
        layout.addLayout(seed_row)

        image_row = QHBoxLayout()
        image_row.addWidget(QLabel("Input image"))
        self._image = QLineEdit(str(params.get("input_image") or ""))
        image_row.addWidget(self._image, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        image_row.addWidget(browse)
        layout.addLayout(image_row)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        run = QPushButton("Re-run")
        run.setDefault(True)
        run.clicked.connect(self.accept)
        buttons.addWidget(cancel)
        buttons.addWidget(run)
        layout.addLayout(buttons)

    def _browse(self):
        dialog = ImagePickerDialog(self)
        if dialog.exec() and dialog.selected_image():
            self._image.setText(dialog.selected_image())

    def overrides(self) -> dict:
        """Overrides for the replay engine. A blank seed/image means 'leave as-is'."""
        if self._random.isChecked():
            seed = random.randint(0, _SEED_MAX)
        else:
            try:
                seed = int(self._seed.text())
            except ValueError:
                seed = None
        image = self._image.text().strip() or None
        return {
            "positive": self._positive.toPlainText(),
            "negative": self._negative.toPlainText(),
            "seed": seed,
            "input_image": image,
        }
