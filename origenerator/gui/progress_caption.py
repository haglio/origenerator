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

A job made of several sampler passes gets a second, thinner band along the bar's
foot: the bar itself is the whole run, and the band is the pass being taken
right now (:meth:`origenerator.progress.ProgressTracker.current_pass`). An
enhancement that upscales and then fixes faces and hands is three passes or
more, and with one bar between them the only honest thing a bar can do is
restart per pass — so the run looks like several jobs, and nothing on screen
answers "how far through the whole thing". Split, each reading gets its own
band: the big one only advances, the small one is free to start over as each
fix begins. Runs of a single pass show no band, having nothing to say twice.

A caption too long for the bar elides at its tail rather than being clipped
mid-letter at both ends, which is what centered text in a narrow bar does
otherwise. It is a backstop, not the plan: a surface too narrow for the full
reading asks :func:`origenerator.timing.progress_status_label` for its compact
one instead, and eliding is what happens when even that overruns.
"""

from PyQt6.QtWidgets import (
    QProgressBar, QStyle, QStyleOptionProgressBar, QStylePainter,
)
from PyQt6.QtGui import QFontMetrics, QPainterPath
from PyQt6.QtCore import Qt, QRect, QRectF

from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()

from shared_ui.colors import BG_PRIMARY, TIMELINE_ACTIVE

_TEXT_MARGIN = 6  # breathing room at each end before the caption starts eliding
_BAND_PX = 6      # the current pass's band, along the foot of a 26px bar
_BAND_RADIUS = 3  # the stylesheet's corner radius, so the band's ends match
# The band reads as a groove cut into the bar rather than a second fill of the
# same blue: darkest ground beneath, the palette's lighter blue over it. Same
# blue family as the run's own fill, a shade up, so which is which is legible
# whether the band lies over the filled part of the bar or the empty part.
_BAND_TROUGH = BG_PRIMARY
_BAND_FILL = TIMELINE_ACTIVE


class ProgressCaption(QProgressBar):
    """A determinate-or-indeterminate bar whose caption reads across its face."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("progressCaption")
        self.setTextVisible(True)
        self._caption = ""
        self._pass_progress: tuple[int, int] | None = None

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

    def pass_progress(self) -> tuple[int, int] | None:
        """The ``(done, total)`` the band along the foot is drawing, if any."""
        return self._pass_progress

    def show_progress(self, caption: str, progress: tuple[int, int] | None,
                      pass_progress: tuple[int, int] | None = None):
        """Say ``caption`` over a fill of ``(done, total)`` sampler steps.

        ``progress`` of ``None`` (or a total of zero — a job ComfyUI hasn't
        started, or one before its first step) leaves the bar indeterminate: a
        sweeping bar says "waiting", where a determinate one stuck at 0% says
        "started and going nowhere".

        ``pass_progress`` is the pass running right now, on its own count, drawn
        as the band along the bar's foot. ``None`` — a single-pass run, or one
        with nothing to measure — leaves the bar whole.
        """
        self._caption = caption
        self._pass_progress = pass_progress
        if progress and progress[1] > 0:
            self.setRange(0, progress[1])
            self.setValue(progress[0])
        else:
            self.setRange(0, 0)
        self.update()

    def paintEvent(self, event):
        """Groove and fill, then the current pass's band, then the caption.

        Three layers in that order, because the caption has to be the top one:
        the band is painted over the foot of the bar, which is where a line of
        text keeps its descenders, and a band drawn last strikes the bottom of
        every letter out. So the style is asked for the bar without its label
        (the caption it would draw is taken out of the option), and the writing
        goes on by hand once the band is down.

        The band is painted over the bar rather than laid out beside it, so
        every surface holding one of these keeps the height it already allots:
        the band takes its few pixels out of the fill, and the caption stays
        centered on the bar as a whole.
        """
        painter = QStylePainter(self)
        option = QStyleOptionProgressBar()
        self.initStyleOption(option)
        caption, option.text = option.text, ""
        option.textVisible = False
        painter.drawControl(QStyle.ControlElement.CE_ProgressBar, option)
        self._paint_pass_band(painter)
        if self.isTextVisible() and caption:
            painter.drawItemText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                                 self.palette(), self.isEnabled(), caption,
                                 self.foregroundRole())

    def _paint_pass_band(self, painter):
        """Lay the current pass's band along the foot of the bar, if there is one."""
        if self._pass_progress is None or self.maximum() <= 0:
            return  # nothing to split, or a sweeping bar with no foot to split
        done, total = self._pass_progress
        if total <= 0:
            return
        inner = self.rect().adjusted(1, 1, -1, -1)  # inside the styled border
        if inner.height() <= _BAND_PX or inner.width() <= 0:
            return  # too short to give any of itself away
        painter.save()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(inner), _BAND_RADIUS, _BAND_RADIUS)
        painter.setClipPath(clip)
        band = QRect(inner.x(), inner.bottom() - _BAND_PX + 1,
                     inner.width(), _BAND_PX)
        painter.fillRect(band, _BAND_TROUGH)
        filled = round(band.width() * min(done, total) / total)
        if filled > 0:
            painter.fillRect(QRect(band.x(), band.y(), filled, band.height()),
                             _BAND_FILL)
        painter.restore()
