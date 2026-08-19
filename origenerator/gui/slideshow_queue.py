"""The bottom strip's queue itself, floated into the fullscreen show's corner.

Not a summary of the queue — the queue: :class:`GenerationQueue` as the main
window lays it out, with the running job's live frame filling its bottom-left,
the fat progress bar with the clock written across it, and every waiting job as
a row of its own carrying its Cancel, its picture and its drag to reorder. This
is that widget, parented to the show and given a corner to sit in, so nothing
about what the queue says or does has to be said twice or kept in step.

The show covers the strip, and a show is the worst moment to lose it. It is the
one stretch where the line deliberately stops moving — every video in it is held
until the show closes (:mod:`origenerator.queue_line`) — and it is when the user
keeps *adding* to it, since holding a slide stars it and asks for the better
version of that picture. So the strip comes along, into the one region this view
leaves empty: the console is top-left, the position counter bottom-center, the
neighbor stills up the two side edges.

Three things it does differently from the one in the main window, all of them
about being a floating plate rather than a docked pane:

* It paints its own background. The strip in the main window is transparent and
  shows the pane behind it; over a full-screen picture that would be rows of
  text lying on the media. Here it wears the app's own surface and a hairline
  border, so it reads as the strip lifted onto the show.
* Nothing in it takes the keyboard. Its buttons are still pressable, but a press
  that stole focus would leave the arrows no longer stepping the slides — the
  show is a keyboard view, and its keys must survive a click on a Cancel.
* With nothing in flight it leaves the screen. The docked strip holds its slot
  and says what it is for, because a pane that came and went would shift
  everything above it; a plate over a picture has nothing to hold still for, and
  an empty one is furniture.

It opens about four rows tall — the strip's own height plus the couple of rows
the main window gets by dragging its handle, which is not a gesture there is
anywhere to make here.
"""

from PyQt6.QtWidgets import QWidget
from PyQt6.QtCore import Qt, QRect

from origenerator.gui.generation_queue import GenerationQueue, QueueRow
from origenerator.paths import ensure_shared_ui_on_path

ensure_shared_ui_on_path()
from shared_ui.colors import BG_PRIMARY, BORDER_SUBTLE

# How far the plate floats off the screen's left and bottom edges — the position
# counter's own margin, so the two sit on one baseline across the foot of the
# show rather than at two heights that happen to be close.
MARGIN = 24
# How much of the show's width it takes, and the least it may shrink to: below
# about four hundred the live frame and its bar alone fill the plate and the
# rows have nothing left to be read in.
WIDTH_FRACTION = 0.45
MIN_WIDTH = 400
# The clearance kept from anything it is asked to stay off — the counter, which
# owns the middle of the same edge.
GAP = 12
# How many rows tall it opens: the strip's docked height is about two, and the
# main window's answer to wanting more is a drag of the splitter above it, which
# there is nowhere to do here. The extra height all goes to the line — the live
# frame stops growing at the strip's own height (see ``RunningPreview``).
ROWS = 4


class SlideshowQueue(GenerationQueue):
    """The generation queue, floated over a fullscreen show's bottom-left."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        # The strip is transparent where it is docked, taking the pane's surface
        # behind it; floated over a picture it has to bring its own, or its rows
        # are text lying on the media.
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            f"#generationQueue {{"
            f" background-color: {BG_PRIMARY.name()};"
            f" border: 1px solid {BORDER_SUBTLE.name()};"
            f" border-radius: 6px; }}"
        )
        # Native, because a video surface is a native window on Windows and a
        # plain sibling widget cannot paint over one however it is stacked —
        # which is what made the position counter vanish over a clip until it
        # was made native too.
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.hide()  # nothing in flight yet, and an empty plate would claim there was

    def set_items(self, items, foreign_queued: int = 0):
        """Show the line, or leave the screen when there is none to show."""
        super().set_items(items, foreign_queued)
        self._refuse_the_keyboard()
        self.setVisible(bool(items) or bool(foreign_queued))

    def _refuse_the_keyboard(self):
        """Take no focus, here or on any control inside.

        A Cancel pressed in the main window is welcome to the keyboard; pressed
        here it would take the arrows away from the slides, and the show would
        stop stepping with nothing on screen to say why. The rows are rebuilt
        whenever the set of jobs changes, so this is re-applied with them.
        """
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        for child in self.findChildren(QWidget):
            child.setFocusPolicy(Qt.FocusPolicy.NoFocus)

    def reposition(self, avoid: QRect | None = None) -> None:
        """Put the plate in the host's bottom-left corner.

        ``avoid`` is a rectangle to stay clear of — the position counter, which
        owns the middle of the same edge. The plate gives up width rather than
        move: it is the bottom-left corner's, and a strip that slid up or along
        to dodge a caption would be somewhere different every time the caption's
        text changed length.
        """
        host = self.parentWidget()
        if host is None:
            return
        height = min(max(self.minimumHeight(), ROWS * QueueRow.HEIGHT),
                     max(0, host.height() - 2 * MARGIN))
        room = max(0, host.width() - 2 * MARGIN)
        width = min(max(int(host.width() * WIDTH_FRACTION), min(MIN_WIDTH, room)), room)
        top = max(0, host.height() - height - MARGIN)
        if avoid is not None and not avoid.isEmpty() and avoid.bottom() >= top:
            width = min(width, max(0, avoid.left() - GAP - MARGIN))
        self.setGeometry(MARGIN, top, width, height)
        self.raise_()  # over the media, video surface included
