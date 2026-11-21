from __future__ import annotations

from dataclasses import replace

from funestra.file_channel import publish_whole
from funestra.messages import MessageWriter
from funestra.modes import MessageLevel
from funestra.satellite_hud import hud_text
from shared_ui.message_shape import ERROR, FAVORITE, HEARD_MARK, INFO, WARNING

from origenerator.gui.hud_queue import JobQueueFile, QueueFoot
from origenerator.gui.slideshow_hud import USUAL_PLACEMENT, HudPlacement, slideshow_hud_model

READER_HOLD_BUDGET_S = 1.0
_RETRY_SPACING_S = 0.005
_LEVELS = {INFO: MessageLevel.NORMAL, WARNING: MessageLevel.WARNING,
           ERROR: MessageLevel.ERROR, FAVORITE: MessageLevel.HIGHLIGHT}


class HudOnFile:
    def __init__(self, hud_file, shape: str, foot: QueueFoot) -> None:
        self._hud_file = hud_file
        self._shape = shape
        self._foot = foot
        self._published = ""
        self._painted = JobQueueFile(hud_file, shape)

    def wear(self, shape: str) -> None:
        if shape != self._shape:
            self._painted.forget()
            self._shape, self._painted = shape, JobQueueFile(self._hud_file, shape)

    def publish(self, slideshow, placement: HudPlacement = USUAL_PLACEMENT, **placed) -> None:
        model = slideshow_hud_model(self._shape, slideshow, placement,
                                    foot=self._painted.of(self._foot.section()))
        if model is not None and placed:
            model = replace(model, **placed)
        text = hud_text(model) if model is not None else ""
        if text != self._published and publish_whole(self._hud_file, text):
            self._published = text

    def blank(self) -> None:
        publish_whole(self._hud_file, "",
                      attempts=round(READER_HOLD_BUDGET_S / _RETRY_SPACING_S),
                      delay_s=_RETRY_SPACING_S)
        self._published = ""
        self._painted.forget()


class OnASessionsFunestra:

    player = None

    def __init__(self, slideshow, shape: str, channel, messages=None, *, actions) -> None:
        self._slideshow = slideshow
        self._messages = messages if messages is not None else MessageWriter(channel.message_file)
        self.queue_foot = QueueFoot(actions)
        self._hud = HudOnFile(channel.hud_file, shape, self.queue_foot)

    def hud_changed(self) -> None:
        self._hud.publish(self._slideshow)

    def flash(self, text: str, *, kind: str = INFO, mark: str = "") -> None:
        self._messages.say(text, level=_LEVELS[kind], mark=mark)

    def request_message(self, message: str, request=None, *, working: bool = False,
                     kind: str = INFO) -> None:
        self.flash(message, kind=kind, mark=HEARD_MARK)

    def dictating(self, note: str) -> None:
        if note:
            self.flash(note, mark=HEARD_MARK)

    def room_paused(self, paused: bool) -> None:
        pass

    def set_queue(self, items, foreign_queued: int = 0) -> None:
        self.queue_foot.set(items, foreign_queued)
        self.hud_changed()

    def press_the_queue(self, verb: str, payload: str) -> None:
        self.queue_foot.press(verb, payload)
        self.hud_changed()

    def gone(self) -> None:
        self._hud.blank()
