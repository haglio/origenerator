from __future__ import annotations

from origenerator.gui.library_redraws import LibraryRedraws


class _Library:
    def __init__(self):
        self.version = 1
        self.reads_begun: list[int] = []
        self.drawn: list[int] = []
        self.asked_to_draw: list[tuple[int, bool]] = []
        self.prepared: list[bool] = []
        self._held: list = []
        self.drawn_version = 0

    def off_thread(self, work, done):
        self._held.append((work, done))

    def read(self, *, even_unmoved: bool):
        self.prepared.append(even_unmoved)

        def work():
            self.reads_begun.append(self.version)
            return self.version
        return work

    def draw(self, read, *, even_unmoved: bool) -> bool:
        self.asked_to_draw.append((read, even_unmoved))
        if even_unmoved:
            self.drawn.append(read)
            self.drawn_version += 1
        return even_unmoved

    def land_the_next_read(self):
        work, done = self._held.pop(0)
        done(work())

    def redraws(self) -> LibraryRedraws:
        return LibraryRedraws(version=lambda: self.version, read=self.read, draw=self.draw,
                              drawn_version=lambda: self.drawn_version,
                              off_thread=self.off_thread)


def test_two_redraws_asked_with_no_change_between_them_read_and_draw_once():
    library = _Library()
    redraws = library.redraws()
    after = []

    redraws.ask(lambda drew: after.append(("first", drew)))
    redraws.ask(lambda drew: after.append(("second", drew)))
    library.land_the_next_read()

    assert library.reads_begun == [1]
    assert library.drawn == [1]
    assert after == [("first", True), ("second", True)]


def test_a_redraw_asked_after_a_change_waits_for_a_read_begun_after_it():
    library = _Library()
    redraws = library.redraws()
    after = []

    redraws.ask(lambda drew: after.append("first"))
    library.version = 2
    redraws.ask(lambda drew: after.append("second"))
    library.land_the_next_read()
    assert after == []
    library.land_the_next_read()

    assert len(library.reads_begun) == 2
    assert library.drawn == [2]
    assert after == ["first", "second"]


def test_redraws_asked_only_if_the_library_moved_read_it_without_working_it_out():
    library = _Library()
    redraws = library.redraws()
    after = []

    redraws.ask(after.append, even_unmoved=False)
    redraws.ask(after.append, even_unmoved=False)
    library.land_the_next_read()

    assert library.prepared == [False]
    assert library.asked_to_draw == [(1, False)]
    assert after == [False, False]


def test_one_redraw_asked_even_if_unmoved_works_out_and_draws_for_all():
    library = _Library()
    redraws = library.redraws()
    after = []

    redraws.ask(after.append, even_unmoved=False)
    library.version = 2
    redraws.ask(after.append)
    library.land_the_next_read()
    library.land_the_next_read()

    assert library.prepared == [False, True]
    assert library.asked_to_draw == [(2, True)]
    assert after == [True, True]


def test_a_read_another_draw_overtook_is_read_again_rather_than_drawn_over_it():
    library = _Library()
    redraws = library.redraws()
    after = []

    redraws.ask(after.append)
    library.version = 2
    library.drawn_version += 1
    library.land_the_next_read()
    assert library.drawn == []
    library.land_the_next_read()

    assert library.drawn == [2]
    assert after == [True]
