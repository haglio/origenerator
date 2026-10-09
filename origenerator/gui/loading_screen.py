from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QDialog, QLabel, QProgressBar, QVBoxLayout
from shared_ui.fonts import FONT_UI, SIZE_BODY, SIZE_HEADING, SIZE_SMALL, make_font

CANCEL_HINT = "Press Esc to cancel opening Origenerator"
CANCELING = "Canceling..."


class LoadingScreen(QDialog):
    canceled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Origenerator Loading")
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setFixedWidth(420)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint
        )

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

        self._hint_label = QLabel(CANCEL_HINT)
        self._hint_label.setObjectName("estimateLabel")
        self._hint_label.setFont(make_font(FONT_UI, SIZE_SMALL))
        layout.addWidget(self._hint_label)

        self._canceling = False

    def set_status(self, message: str) -> None:
        if not self._canceling:
            self._status_label.setText(message)

    def reject(self) -> None:
        self._canceling = True
        self._status_label.setText(CANCELING)
        self._hint_label.clear()
        self.canceled.emit()


class LoadingCanceled(BaseException):
    pass


class Loading:
    def __init__(self, app, logger, screen: LoadingScreen | None = None):
        self._app = app
        self._logger = logger
        self._screen = screen
        self._canceled = False
        if screen is not None:
            screen.canceled.connect(self._cancel)

    def _cancel(self) -> None:
        self._canceled = True

    def say(self, step: str) -> None:
        if self._screen is None:
            self._logger.info("Boot: %s", step)
        else:
            self._screen.set_status(step)
        self.stop_if_canceled()

    def stop_if_canceled(self) -> None:
        self._app.processEvents()
        if self._canceled:
            raise LoadingCanceled

    def done(self) -> None:
        """Lets the screen's closing settle: Windows hands activation on from a
        closing window to whatever is next in the Z-order, and unpumped that
        lands after the window's own request for the foreground and undoes it."""
        if self._screen is not None:
            self._screen.accept()
            self._app.processEvents()
