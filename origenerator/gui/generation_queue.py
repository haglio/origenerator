"""The generation queue, as one strip along the foot of the gallery's own panes.

Two halves, each answering one question. On the left, *what is being made*: the
live frame of the job ComfyUI is rendering, filling the strip's height out of its
bottom-left corner, and beside it a column no wider than a bar needs to be — the
job's reading, "45% · 1:30 elapsed · ~10:34 left", written across the fat progress
bar it measures. That frame opens the folder its run will land in, the way the
row of the same job on the right does: it is a picture of a job, and a picture of
a job goes where the job goes. A job ComfyUI hasn't started has no reading to
write and that bar only sweeps, so where another app's work is what it is stuck
behind, the line under the bar says so: a bar sweeping with nothing said about it
is exactly the thing a user is owed an explanation for. Whatever is true of the
shared *server* is this half's to say — a row on the right is about one job of
ours and nothing else. With nothing of ours in flight the same half says what
that server is busy with instead, and offers a Clear for it.
On the right, taking the rest of the strip, *what is queued*: every in-flight job
as a row of its own — the one being made at the top — each led by a Cancel, each
opening its folder on a click or a double-click, and each draggable to a new
place in the line. A row says what the job will cost and what kind of thing it
is, and nothing else ("~2 min · I2V · dancing · Auto · Request"): a line of
waiting work is read to find out how long the wait is, and the
workflow-and-prompt name that used to be here is the same on every row of a
folder being re-rolled. Beside that, a picture — the frame an image-to-video
animates, the gray clip a dropped-video combine takes its settings from, or a
four-up of the folder the run will land in — because the one picture a queued
job cannot show is its own.
Only the top row is fixed: nothing can be moved in front of what is already
rendering.
With nothing queued at all, the strip says so in dim letters across the middle of
the whole of itself, rather than sitting blank: the left half has no frame, no
bar and (barring another app's backlog to report) nothing to say, so it stands
down and the line takes the strip's whole width to be centered in.

It opens one progress bar tall — about two rows, the rest a scroll away — and its
top edge is a splitter handle, so a long queue can be dragged open to as many rows
as it's worth giving up. The extra height all goes to the line: the thumbnail
never grows past the strip's opening height, so a queue dragged tall is a queue
you can read rather than one enormous frame.

It's fed the in-flight view-models the Recents shelf uses
(:class:`origenerator.gui.inflight.InFlightItem`), leading job first, refreshed on
every poll so the frame and progress stay live; a refresh updates rows in place,
so a drag is never yanked out from under the user. Reordering is asked for, not
done here: :attr:`reorder_requested` carries the order the rows were dropped into,
and whoever owns the jobs re-lines the queue.

A row the queue is deliberately holding — a video, while a slideshow plays — says
so in place of its caption, and with nothing of ours running the left half says it
for the whole line. A queue that has stopped moving with the GPU idle is exactly
the thing a user goes hunting for an explanation of.
"""

import time

from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
    QScrollArea, QApplication, QFrame, QSizePolicy,
)
from PyQt6.QtGui import QPixmap, QDrag, QPainter, QPen, QColor
from PyQt6.QtCore import Qt, QMimeData, QSize, QTimer, pyqtSignal

from origenerator.gui.inflight import (
    InFlightItem, discard_run_text, discard_run_tooltip, foreign_queue_text,
    held_row_text, queue_held_text, queue_lead_text, queue_lead_tooltip,
    queue_wait_text, starting_row_text,
)
from origenerator.gui.progress_caption import ProgressCaption
from origenerator.gui.queue_thumbs import QueueThumbs
from origenerator.paths import ensure_shared_ui_on_path
from origenerator.timing import progress_status_label

ensure_shared_ui_on_path()
from shared_ui.colors import BORDER_SUBTLE, BLUE

# The strip's opening height, its floor, and so the widest the live thumbnail
# ever gets: it takes the bottom-left corner whole, being the one thing here worth
# looking at (the full-size preview is still one click away). The strip never
# opens taller than this however long the line gets, so the panes above it don't
# move on their own — only on a drag of the handle at its top edge.
_STRIP_HEIGHT = 88
# The bar the clock is written across, sized off the line it carries — "45% ·
# 12:30 elapsed · ~16:02 left" runs about 270px at the app's own font, and a bar
# narrower than its caption elides the countdown away. The queue's names are
# long, so the rest of the strip still goes to the line.
_BAR_WIDTH = 290
_BAR_HEIGHT = 26  # a line of that font, with room to read as a bar around it
# How often the running half re-reads the clock. Its own timer rather than the
# gallery's 1.5s poll, which would make a seconds count skip every other tick.
_TICK_MS = 1000
# Marks a drag as one of our own rows, so a thumbnail dragged from the gallery
# (which carries its own type) can't be dropped into the queue as a reorder.
QUEUE_ROW_MIME = "application/x-origenerator-queue-row"


class OpensAFolder:
    """Going from a job to where its result will land: a press and its release,
    or a double-click.

    Both halves of the strip stand for a job you can go to — the live frame of
    the one being made, and the rows of the ones waiting — so both answer the
    same two gestures, written once here.

    The double-click is answered outright rather than through the release that
    trails it. Qt hands the second press of a double over as a double-click
    event, not as a press, so a surface without this reaches the folder only if a
    further release arrives — one event too many to rest on for what is, to
    anyone reading a listing, the obvious way to open a row.

    A subclass says what is under the cursor through :meth:`folder_of`. The
    pending press is :attr:`_press_at`, left where a subclass can call the
    gesture off: the queue's rows clear it once a press has travelled far enough
    to be a drag, and the row then reorders rather than opening anything.
    """

    _press_at = None  # where a left press landed, until it clicks or turns into a drag

    def folder_of(self, position):
        """How to reach the folder of whatever sits at ``position``, or ``None``
        where nothing there goes anywhere."""
        raise NotImplementedError

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = event.position().toPoint()

    def mouseReleaseEvent(self, event):
        if self._press_at is not None:
            self._open_folder(self._press_at)
        self._press_at = None

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_at = None  # answered here, not again on the release
            self._open_folder(event.position().toPoint())

    def _open_folder(self, position):
        reveal = self.folder_of(position)
        if reveal is not None:
            reveal()


class RunningPreview(OpensAFolder, QWidget):
    """What is being made: its live frame, and beside it a fat bar with the clock
    written across it — and, under the bar, what is holding the whole line up.

    That second line is the strip's one place for a fact about the shared server
    rather than about a job: another app's backlog, or a hold of this queue's own.
    While the head of the line is stuck behind another app's work its bar has no
    reading to write and only sweeps, and the line under it is the explanation
    that sweeping is owed.

    The frame goes where the row of the same job goes — a click or a double-click
    on it opens the folder the run will land in (:class:`OpensAFolder`). Only the
    frame: the bar beside it is a reading of this job rather than a picture of it,
    and the note under that bar is about the shared server, so neither is
    something to click through to a folder.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.key = None
        self._item = None
        self._press_at = None

        layout = QHBoxLayout(self)
        # No margins: the frame is meant to reach the strip's edges, and the
        # column beside it centers itself in the same height.
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self._frame = QLabel()
        self._frame.setFixedSize(_STRIP_HEIGHT, _STRIP_HEIGHT)  # kept square: resizeEvent
        self._frame.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Pinned to the bottom, so it still sits in the strip's corner once the
        # strip is dragged taller than the square it stops growing at.
        layout.addWidget(self._frame, 0, Qt.AlignmentFlag.AlignBottom)

        column = QVBoxLayout()
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(3)
        column.addStretch(1)
        # How far along the run is, how long it has been going and how much longer
        # it has — written across the bar those numbers measure, so the reading and
        # the thing read are one object rather than a line of text with a separate
        # stripe under it. The same line, in the same words, as the browser pane's
        # in-flight cards carry.
        self._progress = ProgressCaption()
        self._progress.setFixedHeight(_BAR_HEIGHT)
        self._progress.setFixedWidth(_BAR_WIDTH)
        column.addWidget(self._progress)
        # What the shared server is doing to us: the backlog our job is stuck
        # behind, under its own sweeping bar — or, with nothing of ours in flight
        # at all, what that server is busy with instead, in the bar's own place.
        # Plain text either way, being about the server rather than about a run of
        # ours that a bar could be measuring. It wraps rather than eliding: the
        # width here is the bar's, chosen for a line of readings that is shorter
        # than a sentence, and a truncated explanation explains nothing.
        self._caption = QLabel()
        self._caption.setObjectName("estimateLabel")  # muted secondary text
        self._caption.setWordWrap(True)
        self._caption.setFixedWidth(_BAR_WIDTH)  # a long line wraps, not widens
        column.addWidget(self._caption)
        column.addStretch(1)
        layout.addLayout(column)

        # Its own clock rather than the gallery's poll, so the count advances a
        # second at a time whether or not a refresh has landed.
        self._tick = QTimer(self)
        self._tick.setInterval(_TICK_MS)
        self._tick.timeout.connect(self._render_timing)

        self.show_item(None)

    def show_foreign(self, text: str):
        """Say what the shared server is holding us up with — under our own job's
        bar while it is stuck behind that work, or in the bar's own slot while
        nothing of ours is in flight at all.

        Hidden with nothing to say, so a job of ours actually being made keeps the
        slot for its bar alone; an empty half keeps it up regardless, holding the
        space its bar has stood down from.
        """
        self._caption.setText(text)
        self._caption.setVisible(bool(text) or self._item is None)

    def status_text(self) -> str:
        """Whatever this half is saying about the head of the line: what the shared
        server is holding it up with, if anything is, else its bar's own reading —
        and, with nothing of ours in flight, that note about the server alone."""
        return self._caption.text() or (
            self._progress.caption() if self._item is not None else ""
        )

    def folder_of(self, position):
        """Where the running job will land — for a press on its frame alone."""
        if self._item is None or not self._frame.geometry().contains(position):
            return None
        return self._item.reveal

    def show_item(self, item):
        """Render ``item``, or blank the half (keeping its space) when nothing runs."""
        self.key = item.key if item is not None else None
        self._item = item
        if item is None:
            self._frame.unsetCursor()  # nothing to go to, so nothing to invite a click
            self._frame.clear()
            self._progress.hide()
            self._caption.show()
            self._tick.stop()
            return
        # The hand rides on the frame rather than on the half, so it appears over
        # the one thing here that goes anywhere.
        self._frame.setCursor(Qt.CursorShape.PointingHandCursor)
        # A job of ours takes the slot back for its own bar — except while another
        # app's work is what is holding it up, which is the one thing that bar
        # cannot say for itself, and the reason it is sweeping rather than filling.
        self.show_foreign(queue_wait_text(item.foreign_ahead) or "")
        self._progress.show()
        self._render_frame(item.frame)
        self._render_timing()
        self._tick.start()

    def _render_timing(self):
        """How far along the running job is, how long it has been going and how
        much longer it has — written across its bar.

        Read off the clock rather than off the feed. A job ComfyUI hasn't started
        has no elapsed time to report and the line stays empty — what its bar is
        sweeping behind is said under the bar (:meth:`show_foreign`), not on it,
        being about the server rather than a run of ours that a bar could measure.
        A job with no step counts to show leaves the bar indeterminate rather than
        parked at 0%.
        """
        if self._item is None:
            return
        started = self._item.started_at
        elapsed = None if started is None else max(0.0, time.time() - started)
        self._progress.show_progress(
            progress_status_label(elapsed, self._item.progress,
                                  self._item.typical_seconds),
            self._item.progress if self._item.status == "running" else None,
            self._item.pass_progress if self._item.status == "running" else None,
        )

    def _render_frame(self, frame):
        side = self._frame.width()
        pixmap = QPixmap()
        if frame and pixmap.loadFromData(frame) and not pixmap.isNull():
            self._frame.setPixmap(pixmap.scaled(
                side, side, Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))
        else:
            self._frame.clear()  # no frame yet — a blank square, not a stale one

    def resizeEvent(self, event):
        """Keep the frame the largest square the strip's height leaves room for.

        Taken off the height rather than a size of its own, so the thumbnail is
        always as big as the corner it sits in: a strip laid out any other height
        grows it to match instead of stranding it in an empty square. Only up to
        the strip's opening height, though — a queue dragged open is being opened
        to read the line, and every pixel past that goes to the rows.
        """
        super().resizeEvent(event)
        side = min(self.height(), _STRIP_HEIGHT)
        if side != self._frame.width():
            self._frame.setFixedSize(side, side)
            self._render_frame(None if self._item is None else self._item.frame)


class QueueRow(OpensAFolder, QWidget):
    """One job in the line: what it costs, what it is, what it is made from, and
    the button that throws it away.

    Read left to right: the button, then the job's picture, then what it is —
    ``"~2 min · I2V · dancing · Auto"`` (:func:`inflight.queue_lead_text`). That
    line is the whole of what the row says about the job. The workflow-and-prompt
    name a Generate tab is titled with used to be here and is not: it answers
    "which recipe", and every row of a folder being re-rolled carries the same
    one, so a strip of eight said one thing eight times and none of them said
    which was the ten-minute one. It is still a hover away.

    The picture is second because that is where it lines up into a column and
    where the eye lands: the frame an image-to-video animates (with the gray
    recipe video beside it, where one was dropped), or four out of the folder the
    run will land in (:mod:`origenerator.gui.queue_thumbs`).

    Only a wait worth explaining puts more text on the row, and only one this job
    is in on its own — a video the queue is holding for a slideshow, or a press of
    Generate not yet submitted — and that note takes the rest of the width, after
    everything the row always says. A wait behind another app is not one of them:
    that is the whole line's, and is said once, under the bar in the left half —
    the bar it is holding up, and the thing it is there to explain.

    The picture block is one width whether it holds one picture or four, so the
    line of text behind it starts at the same place on every row.

    The button reads "Cancel", or "Next seed" for a job whose folder is
    auto-generating — where the press discards the seed and the loop starts
    another (:func:`inflight.discard_run_text`).

    A press-and-release opens the job's folder, and so does a double-click
    (:class:`OpensAFolder`); a press that travels starts a drag instead, which
    the strip turns into a reorder. The row being made is the head of the line
    and does not move.
    """

    HEIGHT = 34  # about two of these fit beside the progress bar
    # The side of one cell of the picture block: the row's height less its
    # margins, so the pictures are as big as a row that still reads as a row can
    # make them. The block itself is four of these across.
    THUMB = HEIGHT - 6

    def __init__(self, item, *, movable=True, parent=None):
        super().__init__(parent)
        self.key = item.key
        self.movable = movable
        self._press_at = None
        self.setObjectName("queueRow")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setProperty("dragging", False)
        self.setFixedHeight(self.HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 3, 6, 3)
        layout.setSpacing(6)
        # It leads the row: a button anywhere behind a line that can elide was
        # pushed out of sight at the right-hand end.
        self._cancel = QPushButton()
        self._cancel.setObjectName("queueCancelBtn")
        self._cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel.setFixedHeight(self.HEIGHT - 12)
        self._cancel.clicked.connect(self._on_cancel)
        layout.addWidget(self._cancel)
        # Straight after the button, so the blocks stack into a column at the
        # near edge of the line rather than out at the far end of the text.
        self._thumbs = QueueThumbs(self.THUMB)
        layout.addWidget(self._thumbs)
        # What the row says about the job, in the type the rows always used —
        # this is the row's text now, not an annotation on some other text.
        self._lead = QLabel()
        self._lead.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._lead)
        # Only a wait needs explaining, so most rows leave this empty. It asks
        # for no width of its own and is elided into whatever is left
        # (:meth:`_render_note`): a label that demands its full text instead can
        # widen the row past the strip and carry everything behind it off the
        # end — the disappearance the button was moved to the front to escape.
        self._note = QLabel()
        self._note.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._note.setSizePolicy(QSizePolicy.Policy.Ignored,
                                 QSizePolicy.Policy.Preferred)
        layout.addWidget(self._note, 1)

        self.update_item(item)

    def lead(self) -> str:
        """What the row says about the job: its price, its kind, and who asked."""
        return self._lead.text()

    def note(self) -> str:
        """The wait this row is explaining, before any elision — ``""`` if none."""
        return self._note_text

    def thumbs(self) -> QueueThumbs:
        return self._thumbs

    def update_item(self, item):
        """Re-render this row in place — a queued→running flip, a fresh estimate,
        or an Auto toggle that changed what the button gets you."""
        self._item = item
        self._lead.setText(queue_lead_text(item))
        # The name the row no longer spends its width on, plus what the shorthand
        # in front of it means. The recipe is worth an answer, just not the row.
        self._lead.setToolTip(f"{item.caption}\n\n{queue_lead_tooltip(item)}")
        # Two waits are worth explaining in a row's own width, both of them this
        # job's alone: the stretch before a pressed Generate is a job at all, and
        # one this queue is imposing (a video, while a slideshow plays). The
        # user's own place in the line is the line itself and needs no words, and
        # a wait behind another app is about the server, not this job — the left
        # half says that one, under the bar that wait is holding up.
        self._note_text = (
            starting_row_text(item.starting) or held_row_text(item.held) or ""
        )
        self._render_note()
        self._cancel.setText(discard_run_text(item.auto_generating))
        self._cancel.setToolTip(discard_run_tooltip(item.auto_generating))
        self._cancel.setVisible(item.cancel is not None)
        self._render_thumbs(item)

    def _render_note(self):
        """Fit the wait note to the width the row has left for it.

        Elided rather than clipped: clipped, the last word is cut mid-letter and
        reads as something that failed to draw, where an ellipsis says outright
        that there is more.
        """
        self._note.setText(self._note.fontMetrics().elidedText(
            self._note_text, Qt.TextElideMode.ElideRight, self._note.width()
        ))
        self._note.setToolTip(self._note_text)

    def resizeEvent(self, event):
        """Re-fit the note — the strip's width follows the window's."""
        super().resizeEvent(event)
        self._render_note()

    def _render_thumbs(self, item):
        """The row's picture: what the job is made from, else what its folder holds.

        The start frame wins whenever there is one, being about *this* run rather
        than about where it will land — and being the only thing separating two
        i2v rows off one recipe. A combine handed a dropped video draws that video
        beside it, in gray. A run with neither, or one whose pictures aren't on
        disk yet, falls back to the folder view; a folder with nothing in it yet
        leaves the block off the row rather than draw an empty grid.
        """
        if ((item.source_image or item.recipe_thumbnail)
                and self._thumbs.show_source(item.source_image, item.recipe_thumbnail)):
            return
        if item.folder_thumbnails:
            self._thumbs.show_folder(item.folder_thumbnails)
            return
        self._thumbs.clear_block()

    def set_dragging(self, dragging: bool):
        """Dim this row while it is the one being dragged, so the gesture reads."""
        self.setProperty("dragging", dragging)
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_cancel(self):
        if self._item.cancel is not None:
            self._item.cancel()

    def folder_of(self, position):
        """Where this job will land — the whole row goes there, wherever it was
        pressed, the Cancel in front of it being a button of its own."""
        return self._item.reveal

    def mouseMoveEvent(self, event):
        """A press that travels far enough becomes a drag, carrying this row's id."""
        if self._press_at is None or not self.movable:
            return
        travelled = (event.position().toPoint() - self._press_at).manhattanLength()
        if travelled < QApplication.startDragDistance():
            return
        self._press_at = None  # this gesture is a drag now, not a pending click
        mime = QMimeData()
        mime.setData(QUEUE_ROW_MIME, self.key.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(self.grab())
        self.set_dragging(True)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.set_dragging(False)


class GenerationQueue(QWidget):
    """The live preview and its bar on the left, the whole line on the right."""

    reorder_requested = pyqtSignal(list)  # prompt ids, in the order they were dropped into
    clear_queue_requested = pyqtSignal()  # wipe another app's work off ComfyUI

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("generationQueue")
        self.setAcceptDrops(True)  # a row dropped anywhere on the strip reorders it
        # A floor, not a fixed height: the strip opens one bar tall and grows only
        # when its splitter handle is dragged, so the panes above never move on
        # their own however long the line gets.
        self.setMinimumHeight(_STRIP_HEIGHT)
        self._items: list = []
        self._drop_at: int | None = None  # where a drag in progress would land

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # An explicit hairline rather than a stylesheet border: the app paints
        # every plain widget one flat color, and a border drawn under a child's
        # own background disappears into it. This one is a widget of its own, so
        # it is there whatever is laid out beneath it.
        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background-color: {BORDER_SUBTLE.name()};")
        outer.addWidget(rule)

        layout = QHBoxLayout()
        # Flush at the left and both ends, so the live frame fills the strip's
        # bottom-left corner; only the far right is held off the window edge.
        layout.setContentsMargins(0, 0, 4, 0)
        layout.setSpacing(8)
        outer.addLayout(layout, 1)
        self._running = RunningPreview()
        layout.addWidget(self._running)
        # Only ever offered for another app's work — the user's own queue is what
        # he asked for, and every row of it carries its own Cancel already.
        self._clear = QPushButton("Clear")
        self._clear.setCursor(Qt.CursorShape.PointingHandCursor)
        self._clear.clicked.connect(self.clear_queue_requested)
        self._clear.hide()
        layout.addWidget(self._clear)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Takes whatever height the strip has and asks for none of its own: a
        # twelve-job line must not make the strip open twelve rows tall, and a
        # strip dragged open must hand every extra pixel to these rows.
        self._scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
        self._host = QWidget()
        self._rows_box = QVBoxLayout(self._host)
        self._rows_box.setContentsMargins(0, 0, 0, 0)
        self._rows_box.setSpacing(0)
        self._rows_box.addStretch(1)  # rows stack from the top
        # What the empty line is for. The strip holds its space whether or not
        # anything is queued, so this side spends most of its life with nothing
        # in it, and a blank half of a laid-out strip reads as something that
        # failed to draw. It sits between two stretches, so it centers in the
        # space it is explaining while nothing is listed, and the rows still
        # stack from the top once it has given way to them.
        self._hint = QLabel("(queued jobs show up here)")
        self._hint.setObjectName("estimateLabel")  # muted secondary text
        self._rows_box.addWidget(self._hint, 0, Qt.AlignmentFlag.AlignHCenter)
        self._rows_box.addStretch(1)
        self._scroll.setWidget(self._host)
        layout.addWidget(self._scroll, 1)  # the line takes the rest of the strip

        self.set_items([])

    # --- what the strip is showing -----------------------------------------

    def running_preview(self) -> RunningPreview:
        """The live half. Its ``key`` is ``None`` when nothing is being made."""
        return self._running

    def sizeHint(self) -> QSize:
        """One progress bar tall, whatever is or isn't in it.

        Read off the strip's own opening height rather than added up from its
        children, whose number changes: an idle strip, whose live half has stood
        down to leave the hint the full width, asks for exactly the room a busy
        one does, so the splitter above it doesn't shift as the queue drains.
        """
        return QSize(super().sizeHint().width(), _STRIP_HEIGHT + 1)  # and its rule

    def rows(self) -> list[QueueRow]:
        """Every job in the line, top to bottom — the one being made first.

        Jobs only: the hint that fills an empty line shares the same box, and it
        is no row — nothing may be dropped in front of it, reordered against it,
        or throw it away with the others on a rebuild.
        """
        return [self._rows_box.itemAt(i).widget()
                for i in range(self._rows_box.count())
                if isinstance(self._rows_box.itemAt(i).widget(), QueueRow)]

    def keys(self) -> list[str]:
        return [row.key for row in self.rows()]

    def set_items(self, items: list, foreign_queued: int = 0):
        """Show ``items`` — every in-flight generation, the one being made first.

        The first drives the live half unless the queue is holding it back: a job
        that cannot start has no frame and no clock, so the half stays free to say
        why instead of showing an empty square over an unmoving bar. Rows already
        listed are refreshed in place; only a change to the *set* of jobs (or
        their order) rebuilds the list, so a poll landing mid-drag doesn't yank the
        row out from under the gesture.

        ``foreign_queued`` is how much of ComfyUI's queue belongs to another app.
        It puts Clear up whenever there is any, and with nothing of ours running
        it is what the free half says — the point being to see that backlog before
        a Generate goes in behind it — after the queue's own hold, which is nearer
        to hand and is ended by closing the show.
        """
        leader = items[0] if items and not items[0].held else None
        self._running.show_item(leader)
        self._clear.setVisible(bool(foreign_queued))
        self._clear.setToolTip(
            f"Drop the {foreign_queued} job{'' if foreign_queued == 1 else 's'}"
            " another app has queued on ComfyUI"
        )
        free_half = ""
        if leader is None:
            free_half = (queue_held_text(sum(1 for item in items if item.held))
                         or foreign_queue_text(foreign_queued) or "")
            self._running.show_foreign(free_half)
        # Nothing of ours in flight at all: the line has no rows to show, so it
        # says what it is for instead. The left half stands down with it unless
        # it has something to report — with no frame, no bar and nothing to say
        # about another app it is an empty third of the strip, and the hint would
        # be centered in the sliver beside it rather than in the strip itself.
        self._hint.setVisible(not items)
        self._running.setVisible(bool(items) or bool(free_half))
        if self.keys() != [item.key for item in items]:
            self._rebuild(items)
            return
        self._items = list(items)
        for row, item in zip(self.rows(), items):
            row.update_item(item)

    def _rebuild(self, items: list):
        self._items = list(items)
        for row in self.rows():
            self._rows_box.removeWidget(row)
            row.deleteLater()
        for index, item in enumerate(items):
            # What ComfyUI is already rendering cannot be moved, and nothing can
            # be dropped in front of it. Everything else is only waiting — held
            # or not — and its place is the user's to change.
            self._rows_box.insertWidget(
                index, QueueRow(item, movable=item.status != "running")
            )
        # The scroll area would otherwise squeeze the whole line into its own
        # height, stacking the rows on top of each other instead of scrolling.
        self._host.setMinimumHeight(len(items) * QueueRow.HEIGHT)

    # --- moving a job up or down the line -----------------------------------

    def move_row(self, source: int, target: int):
        """Lift the row at ``source`` out and drop it back in at ``target``.

        Re-lists them there and then — the queue's agreement only shows up on a
        later poll, and a row that springs back reads as a failure — then asks for
        that order through :attr:`reorder_requested`. Neither end may be a job
        already being rendered: those keep the front of the line. A move that
        changes nothing asks for nothing.
        """
        order = [item.key for item in self._items]
        first = self._first_movable()
        if not first <= source < len(order) or not first <= target < len(order):
            return
        moved = list(self._items)
        moved.insert(target, moved.pop(source))
        if [item.key for item in moved] == order:
            return
        self._rebuild(moved)
        self.reorder_requested.emit(self.keys())

    # --- accepting a dragged row --------------------------------------------

    def _carried_key(self, event) -> str | None:
        """The row id a drag carries, if it is one of ours and still in the line."""
        if not event.mimeData().hasFormat(QUEUE_ROW_MIME):
            return None
        key = bytes(event.mimeData().data(QUEUE_ROW_MIME)).decode()
        return key if key in [item.key for item in self._items] else None

    def dragEnterEvent(self, event):
        if self._carried_key(event) is not None:
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        """Track where the dragged row would land, and mark it."""
        if self._carried_key(event) is None:
            return
        self._show_drop_mark(self._drop_index(event.position().toPoint()))
        event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._show_drop_mark(None)
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        """Land a dragged row wherever in the line it was let go."""
        key = self._carried_key(event)
        self._show_drop_mark(None)
        if key is None:
            return
        source = [item.key for item in self._items].index(key)
        target = self._drop_index(event.position().toPoint())
        # The insertion point was read with the dragged row still in place, so a
        # drop below it names a slot one further along than it will end up in.
        self.move_row(source, target - 1 if target > source else target)
        event.acceptProposedAction()

    def _show_drop_mark(self, index: int | None):
        """Draw (or clear) the line showing where a drop would insert."""
        if index != self._drop_at:
            self._drop_at = index
            self.update()

    def _first_movable(self) -> int:
        """The first slot a row may be moved to or from — past whatever is already
        being rendered, which nothing can be put in front of."""
        for index, item in enumerate(self._items):
            if item.status != "running":
                return index
        return len(self._items)

    def _drop_index(self, point) -> int:
        """Which slot a drop at ``point`` (in this widget's coordinates) lands in:
        above the row whose top half it fell on, else at the end of the line. Never
        in front of a row already being rendered."""
        for index, row in enumerate(self.rows()):
            middle = row.mapTo(self, row.rect().center())
            if point.y() < middle.y():
                return max(self._first_movable(), index)
        return len(self.rows())

    def paintEvent(self, event):
        """Paint the insertion mark over the line while a row is being dragged."""
        super().paintEvent(event)
        if self._drop_at is None:
            return
        rows = self.rows()
        if not rows:
            return
        row = rows[min(self._drop_at, len(rows) - 1)]
        top_left = row.mapTo(self, row.rect().topLeft())
        y = top_left.y() if self._drop_at < len(rows) else top_left.y() + row.height()
        painter = QPainter(self)
        painter.setPen(QPen(QColor(BLUE), 2))
        painter.drawLine(top_left.x(), y, top_left.x() + row.width(), y)
        painter.end()
