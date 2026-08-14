"""Every version of one image, as a row of buttons that swap the preview.

An enhancement is a layer, not a replacement: the enhanced file leads the row's
``output_files`` and each earlier one stays listed, so an image can carry several
levels at once — usually one, more when the same image is enhanced again at
different settings to compare them. The preview opens on the most-enhanced
version; this is where the rest are, each button naming the settings that made
it so an experiment can be told from its neighbor.

Hidden entirely for an image with nothing but its original, which is most of
them — the strip appears when there is actually a choice to make.
"""

from PyQt6.QtWidgets import QButtonGroup, QLabel, QPushButton, QVBoxLayout, QWidget
from PyQt6.QtCore import Qt, pyqtSignal

from origenerator.gui.flow_layout import FlowLayout


class EnhanceVersions(QWidget):
    """The levels of one image, newest first, as an exclusive button row.

    ``show_levels`` takes :class:`~origenerator.gallery.enhance.EnhanceLevel`
    objects (as :func:`~origenerator.gallery.enhance.enhance_levels` produces
    them) and selects the first — the most-enhanced version, which is what the
    preview is already showing. Clicking another emits ``level_selected`` with
    its position in that list, for the panel to put in the preview.
    """

    level_selected = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        heading = QLabel("Enhancement levels")
        heading.setStyleSheet("font-weight: 600;")
        box.addWidget(heading)
        self._host = QWidget()
        FlowLayout(self._host, spacing=6)
        box.addWidget(self._host)
        self._box = box
        # Owns the buttons' exclusivity; rebuilt with them so a stale button can
        # never keep the group's checked slot after its widget is gone.
        self._group: QButtonGroup | None = None
        self.hide()

    def show_levels(self, levels: list):
        """Rebuild the row for one image's levels, or hide when it has only its
        original (nothing to choose between)."""
        # Replace the host wholesale — the same delete-and-rebuild idiom the
        # related-media strips use, so no button outlives the row it described.
        self._box.removeWidget(self._host)
        self._host.deleteLater()
        self._host = QWidget()
        flow = FlowLayout(self._host, spacing=6)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for position, level in enumerate(levels):
            button = self._make_button(level, position)
            self._group.addButton(button, position)
            flow.addWidget(button)
        self._box.addWidget(self._host)
        self.setVisible(len(levels) > 1)

    def select(self, position: int) -> None:
        """Light the button for ``position`` without re-emitting the click —
        used when the panel itself changes which version is on screen."""
        if self._group is None:
            return
        button = self._group.button(position)
        if button is not None:
            button.setChecked(True)

    def _make_button(self, level, position: int) -> QPushButton:
        button = QPushButton(level.label)
        button.setCheckable(True)
        button.setChecked(position == 0)  # the preview opens on the newest
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setToolTip(
            f"{level.settings} — {level.file.get('filename', '')}"
            if level.settings else level.file.get("filename", "")
        )
        if level.settings:
            button.setText(f"{level.label}  ·  {level.settings}")
        button.clicked.connect(lambda _checked=False: self.level_selected.emit(position))
        return button
