from PySide6.QtCore import QObject, Signal

from origenerator.gui.shown_job_queue import ShownJobQueue


class Jobs(QObject):
    reordered = Signal()
    queue_order: tuple = ()

    def move(self, *_a):
        pass

    def start_now(self):
        pass


class Starting(QObject):
    changed = Signal()

    def placed_among(self, items, _jobs):
        return items


def shown_job_queue(in_flight, asks_over, **kwargs) -> ShownJobQueue:
    return ShownJobQueue(Jobs(), None, starting=Starting(), in_flight=in_flight,
                         listed=lambda: ([], []), asks_over=asks_over, **kwargs)
