from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout

from origenerator.config import PROJECT_DIR
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.fonts import FONT_UI, SIZE_BODY, SIZE_HEADING, make_font


class LoadingScreen(QDialog):
    """Indeterminate splash shown while Origenerator starts up.

    Mirrors ComfyUIApp's launch dialog: an app heading, a status line that the
    boot sequence updates through its phases, and a busy progress bar. The
    caller is responsible for pumping the event loop while the main thread
    works (see ``app.processEvents``) so the sweep keeps animating.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Origenerator")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setFixedWidth(420)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

        icon_path = PROJECT_DIR / "icon.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        heading = QLabel("Loading Origenerator...")
        heading.setFont(make_font(FONT_UI, SIZE_HEADING, bold=True))
        layout.addWidget(heading)

        self._status_label = QLabel("Starting up...")
        self._status_label.setFont(make_font(FONT_UI, SIZE_BODY))
        self._status_label.setWordWrap(True)
        layout.addWidget(self._status_label)

        progress = QProgressBar()
        progress.setRange(0, 0)  # indeterminate "busy" sweep
        progress.setTextVisible(False)
        layout.addWidget(progress)

    def set_status(self, message: str) -> None:
        self._status_label.setText(message)
