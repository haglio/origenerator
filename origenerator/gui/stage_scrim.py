"""The dimming banner a tile wears while something is being made of it.

Three surfaces say the same thing about a picture that isn't finished — the
Recents shelf's in-flight cards, a folder's re-roll tile, and a finished
thumbnail whose enhancement is cooking — and they say it the same way: the
message sits *over* the picture, dimmed, rather than replacing it.

That is the whole point of the scrim. Whatever is under it is worth looking at
— a live frame off ComfyUI, or the base render an enhancement is being made
from — and a stage message that took the picture's place hid the one thing the
user opened the pane for. The dimming is what keeps the message readable over
an arbitrary frame while leaving the frame legible underneath.
"""

from PyQt6.QtWidgets import QLabel
from PyQt6.QtCore import Qt

# Dark enough to read white letters against any frame, light enough to leave the
# frame itself visible — which is the reason the scrim exists rather than a
# placeholder that replaces the picture.
_SCRIM_CSS = (
    "background-color: rgba(0, 0, 0, 0.45); color: white;"
    " font-weight: 600; border-radius: 3px;"
)


class StageScrim(QLabel):
    """A dimming overlay carrying one line about what is being made."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setWordWrap(True)  # the queue-wait line is a sentence, not a word
        self.setStyleSheet(_SCRIM_CSS)
        # Clicks belong to the tile underneath — the scrim is a caption, not a lid.
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.hide()

    def cover(self, widget: QLabel, message: str | None, *, inset: int = 0):
        """Lay the scrim over ``widget`` reading ``message``, or take it away.

        Re-read from the covered widget every time rather than positioned once:
        the picture it covers is laid out after the tile is built, and a scrim
        placed before that sits in the tile's top-left corner instead of over
        the frame.

        ``inset`` holds the scrim off a border the covered widget draws itself —
        an in-flight card's blue "being made" edge says something the scrim has no
        business painting over.
        """
        self.setGeometry(widget.geometry().adjusted(inset, inset, -inset, -inset))
        self.setText(message or "")
        self.setVisible(bool(message))
        if message:
            self.raise_()
