"""A progress bar that carries its own caption, read on top of the fill.

Every surface that reports a run in flight — the bottom strip's queue, the
Recents shelf's cards, a folder's re-roll tile — says two things at once: how
far along it is, and how long that has taken. Those used to be laid out
separately (a line of text above a bar, or a percentage in a caption with no bar
at all), which spent two rows on one reading and left each surface free to
invent its own arrangement.

Here they are one widget: the numbers sit *on* the bar they measure. The fill is
the app's flat blue behind the writing rather than a wash over it — a
translucent fill tints the letters as it passes under them, which is the one
place the text has to stay legible.

A caption too long for the bar elides at its tail rather than being clipped
mid-letter at both ends, which is what centered text in a narrow bar does
otherwise. It is a backstop, not the plan: a surface too narrow for the full
reading asks :func:`origenerator.timing.progress_status_label` for its compact
one instead, and eliding is what happens when even that overruns.
"""

from PyQt6.QtWidgets import QProgressBar
from PyQt6.QtGui import QFontMetrics
from PyQt6.QtCore import Qt

_TEXT_MARGIN = 6  # breathing room at each end before the caption starts eliding


class ProgressCaption(QProgressBar):
    """A determinate-or-indeterminate bar whose caption reads across its face."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("progressCaption")
        self.setTextVisible(True)
        self._caption = ""

    def text(self) -> str:
        """The label the style paints over the bar.

        Overridden rather than set through ``setFormat``: a bar with no total to
        count against (a job still queued) is indeterminate, and Qt's own
        ``text()`` returns nothing there — which would drop the caption exactly
        when it is the only thing the surface has to say.
        """
        room = max(0, self.width() - _TEXT_MARGIN)
        return QFontMetrics(self.font()).elidedText(
            self._caption, Qt.TextElideMode.ElideRight, room
        )

    def caption(self) -> str:
        """The full caption, before any eliding to fit the bar."""
        return self._caption

    def show_progress(self, caption: str, progress: tuple[int, int] | None):
        """Say ``caption`` over a fill of ``(done, total)`` sampler steps.

        ``progress`` of ``None`` (or a total of zero — a job ComfyUI hasn't
        started, or one before its first step) leaves the bar indeterminate: a
        sweeping bar says "waiting", where a determinate one stuck at 0% says
        "started and going nowhere".
        """
        self._caption = caption
        if progress and progress[1] > 0:
            self.setRange(0, progress[1])
            self.setValue(progress[0])
        else:
            self.setRange(0, 0)
        self.update()
