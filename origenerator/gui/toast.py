"""What a show has to say, in the toast Fun Time says it in.

Fun Time flashes its notices — "Clip saved", "No other seeds", "Next seed" — at
the top center of the player they are about, in one shape everywhere: the panel
gray, a hairline of the text's own color, a bold heading face, rounded corners
(``fun_time.notice_overlay.NoticeOverlay``). This is that toast, worn by
Origenerator's own notices: the request being spoken, the enhancement cooking,
which version of a picture is on screen. They used to be a dark plate of body
text down at the bottom of the show — a second dialect for the same job, said in
the same room, on a surface that already wears the players' own HUD.

Matched through the tokens rather than by eye. The color and the face come out
of :mod:`shared_ui`, which is where Fun Time takes them from too, so a palette
change moves both at once instead of leaving one of them behind. Only the
geometry is spelled out here, because that is all Fun Time's own overlay spells
out: the padding, the corner radius, and the gap from the top edge.

A child of the surface rather than a window of its own — Fun Time's is a
top-level because it flashes over a *foreign* player's window, and here the
surface it belongs to is ours.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel, QWidget

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BG_SECONDARY, TEXT_PRIMARY
from shared_ui.fonts import FONT_UI, SIZE_HEADING, make_font

# The gap from the top edge of the surface, matching
# ``fun_time.notice_overlay.NOTICE_TOP_MARGIN`` — the two land on the same line
# when a Fun Time player and a show are side by side.
TOP_MARGIN = 28


class Toast(QLabel):
    """One line, centered across the top of the surface it belongs to."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setStyleSheet(
            f"background-color: {BG_SECONDARY.name()};"
            f" color: {TEXT_PRIMARY.name()};"
            f" border: 1px solid {TEXT_PRIMARY.name()};"
            " padding: 8px 16px; border-radius: 4px;"
        )
        self.setFont(make_font(FONT_UI, SIZE_HEADING, bold=True))
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # A video surface is a native window on Windows, and a plain sibling
        # widget cannot paint over one however it is stacked — which is why the
        # position plate and the HUD map are native too. Native itself, this
        # stacks against the media by Z-order like any other window.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.hide()

    def say(self, text: str) -> None:
        """Put *text* up, and keep it up until something says otherwise."""
        self.setText(text)
        self.show()
        self.reposition()

    def reposition(self) -> None:
        host = self.parentWidget()
        self.adjustSize()
        x = (host.width() - self.width()) // 2
        self.move(max(0, x), TOP_MARGIN)
        self.raise_()  # over the media, video surface included
