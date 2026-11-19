from __future__ import annotations

import threading


class NeverAnswered:
    def __init__(self):
        self.answers = []
        self.threads = []

    def __call__(self, work, done, *, owner):
        self.answers.append(done)
        self.threads.append(thread := threading.Thread(target=work))
        thread.start()

    def answer_late(self):
        for thread in self.threads:
            thread.join()
        for answer in self.answers:
            answer(None)
