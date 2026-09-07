"""Back and Forward, driven with no gallery around them.

The trail used to be a list, a boolean and eight methods on a 7,000-line widget,
and every one of these behaviours could only be reached by building one. Here
the host is a handful of recorded calls.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import pytest

from origenerator.gui.gallery_navigation import NavigationController


class FakeSearch:
    """A search reduced to what a history asks of one."""

    def __init__(self, query=""):
        self.query = query
        self.restored = []
        self.runs = 0

    def restore(self, query):
        self.query = query
        self.restored.append(query)

    def run(self):
        self.runs += 1


class FakeHost:
    """A gallery reduced to what a history asks of one."""

    def __init__(self, folders=("workflow/a",)):
        self.folders = set(folders)
        self.folder = None
        self.item = None
        self.visible: set[str] = set()
        self.shown = []          # every folder key show_folder was asked for
        self.went_to = []        # every fallback go_to_generation
        self.revealed = []
        self.cleared = 0
        self.buttons = (False, False)

    # what a stop is made of
    def selected_folder_key(self):
        return self.folder

    def selected_prompt_id(self):
        return self.item

    def pane_holds(self, prompt_id):
        return prompt_id in self.visible

    # how to get somewhere
    def show_folder(self, key):
        self.shown.append(key)
        if key not in self.folders:
            return False
        self.folder = key
        return True

    def go_to_generation(self, prompt_id):
        self.went_to.append(prompt_id)

    def reveal(self, prompt_id):
        self.revealed.append(prompt_id)
        self.item = prompt_id

    def clear_selection(self):
        self.cleared += 1
        self.item = None

    def nav_state_changed(self, can_go_back, can_go_forward):
        self.buttons = (can_go_back, can_go_forward)


@pytest.fixture
def trail():
    def build(host=None, search=None):
        host = host or FakeHost()
        return NavigationController(host, search=search or FakeSearch()), host
    return build


def test_a_gesture_records_where_it_put_the_pane(trail):
    nav, host = trail()
    host.folder = "workflow/a"

    nav.record("g1")

    assert host.buttons == (False, False)   # one stop is nowhere to go back to
    nav.record("g2")
    assert host.buttons == (True, False)


def test_a_move_off_the_record_records_nothing(trail):
    # A rebuild's restore and a Back both re-select something; neither is a place
    # the user went, and a poll would otherwise pile up duplicates.
    nav, host = trail()
    host.folder = "workflow/a"

    with nav.off_the_record():
        nav.record("g1")

    assert host.buttons == (False, False)


def test_off_the_record_restores_rather_than_clears(trail):
    # Nested: an inner move that cleared the flag on the way out would hand the
    # trail back while the outer one was still walking it.
    nav, _host = trail()

    with nav.off_the_record():
        with nav.off_the_record():
            pass
        assert nav.suppressed

    assert not nav.suppressed


def test_nothing_open_is_no_stop_at_all(trail):
    nav, host = trail()
    host.folder = None

    nav.record("g1")

    assert host.buttons == (False, False)


def test_back_re_shows_the_stop_as_it_stood(trail):
    search = FakeSearch()
    nav, host = trail(FakeHost(folders={"workflow/a", "workflow/b"}), search)
    host.folder, host.visible = "workflow/a", {"g1"}
    nav.record("g1")
    host.folder, host.visible = "workflow/b", {"g2"}
    nav.record("g2")

    host.visible = {"g1"}
    nav.go_back()

    assert host.shown[-1] == "workflow/a"
    assert host.revealed == ["g1"]
    assert host.buttons == (False, True)


def test_a_stop_that_picked_nothing_lands_with_nothing_picked(trail):
    # A folder still showing the item Back just left would look like the press
    # had done nothing at all.
    nav, host = trail(FakeHost(folders={"workflow/a", "workflow/b"}))
    host.folder = "workflow/a"
    nav.record()                       # a folder opened, no item picked
    host.folder = "workflow/b"
    nav.record("g2")

    nav.go_back()

    assert host.cleared == 1
    assert host.revealed == []


def test_a_stop_whose_folder_is_gone_falls_back_to_the_item_itself(trail):
    nav, host = trail(FakeHost(folders={"workflow/a", "workflow/b"}))
    host.folder = "workflow/a"
    nav.record("g1")
    host.folder = "workflow/b"
    nav.record("g2")
    host.folders.discard("workflow/a")   # a delete emptied it

    nav.go_back()

    assert host.went_to == ["g1"]


def test_a_stop_that_had_a_query_comes_back_with_it_running(trail):
    search = FakeSearch()
    nav, host = trail(FakeHost(folders={"workflow/a", "workflow/b"}), search)
    host.folder, search.query = "workflow/a", "tabby"
    nav.record()
    host.folder, search.query = "workflow/b", ""
    nav.record()

    nav.go_back()

    assert search.restored[-1] == "tabby"
    assert search.runs == 1


def test_a_search_redrawing_itself_is_not_another_stop(trail):
    # A results pane redraws for reasons that are not navigations — a sort, a
    # widening landing, a generation finishing under a poll.
    search = FakeSearch("tabby")
    nav, host = trail(search=search)
    host.folder = "workflow/a"
    nav.record()
    nav.record()
    nav.record()

    assert host.buttons == (False, False)   # one stop, not three


def test_narrowing_a_query_overwrites_its_stop_rather_than_adding_one(trail):
    search = FakeSearch("tab")
    nav, host = trail(search=search)
    host.folder = "workflow/a"
    nav.record()
    search.query = "tabby"
    nav.record()

    assert host.buttons == (False, False)   # still one stop, now the longer query
    nav.go_back()
    assert host.shown == []                 # nowhere to go back to


def test_picking_a_hit_is_a_step_within_the_results(trail):
    search = FakeSearch("tabby")
    nav, host = trail(search=search)
    host.folder = "workflow/a"
    nav.record()

    nav.record("g1")

    assert host.buttons == (True, False)


def test_the_first_landing_is_seeded_once(trail):
    nav, host = trail()
    host.folder, host.item, host.visible = "workflow/a", "g1", {"g1"}

    nav.seed()
    host.folder = "workflow/b"
    nav.seed()          # already seeded: the second landing is not a stop

    nav.record("g2")
    nav.go_back()
    assert host.shown == ["workflow/a"]


def test_seeding_drops_an_item_the_pane_no_longer_shows(trail):
    nav, host = trail()
    host.folder, host.item, host.visible = "workflow/a", "g1", set()

    nav.seed()
    host.folder = "workflow/b"
    nav.record("g2")
    nav.go_back()

    assert host.revealed == []
