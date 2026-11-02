from __future__ import annotations

from funestra.file_channel import publish_whole
from funestra.satellite_hud import hud_text

from origenerator.gui.hud_queue import JobQueueFile, QueueFoot
from origenerator.gui.notice_overlay import HEARD_MARK, NOTICE
from origenerator.gui.slideshow_hud import slideshow_hud_model

READER_HOLD_BUDGET_S = 1.0
_RETRY_SPACING_S = 0.005


class OnASessionsFunestra:

    player = None

    def __init__(self, slideshow, side: str, channel, say=None, *, actions) -> None:
        self._slideshow = slideshow
        self._side = side
        self._hud_file = channel.hud_file
        self._say = say
        self._published = ""
        foot = QueueFoot(actions)
        self.queue_foot = foot
        self._set_the_foot = foot.set
        self._press_the_foot = foot.press
        self._foots_section = foot.section
        published = JobQueueFile(channel.hud_file, side)
        self._publish_the_foot = published.of
        self._forget_the_foot = published.forget

    def hud_changed(self) -> None:
        model = slideshow_hud_model(self._side, self._slideshow, hosted=True, own_window=False,
                                    foot=self._publish_the_foot(self._foots_section()))
        text = hud_text(model) if model is not None else ""
        if text != self._published and publish_whole(self._hud_file, text):
            self._published = text

    def flash(self, text: str, *, kind: str = NOTICE, ms: int = 0, mark: str = "") -> None:
        if self._say is not None:
            self._say(text, mark=mark)

    def request_line(self, message: str, request=None, *, working: bool = False,
                     kind: str = NOTICE) -> None:
        self.flash(message, kind=kind, mark=HEARD_MARK)

    def dictating(self, note: str) -> None:
        if note:
            self.flash(note, mark=HEARD_MARK)

    def room_paused(self, paused: bool) -> None:
        pass

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        self._set_the_foot(items, foreign_queued)
        self.hud_changed()

    def press_the_queue(self, verb: str, payload: str) -> None:
        self._press_the_foot(verb, payload)
        self.hud_changed()

    def gone(self) -> None:
        publish_whole(self._hud_file, "",
                      attempts=round(READER_HOLD_BUDGET_S / _RETRY_SPACING_S),
                      delay_s=_RETRY_SPACING_S)
        self._forget_the_foot()

