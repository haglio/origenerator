"""The gallery search, driven with no gallery around it.

Which is the point of the extraction: the debounce, the widening, the collapse
onto folders, the count line and the one way out all used to live inside a
7,000-line widget and could only be exercised through it. Here the host is a
handful of recorded calls, so what the search does to its own state is separated
from what a gallery does about it.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import NamedTuple

import pytest
from PyQt6.QtWidgets import QWidget

from origenerator.gui.gallery_search import MIN_CHARS, GallerySearchController


class _Scope(NamedTuple):
    path: str
    ids: set[str] | None


def _row(prompt_id: str, prompt: str, seed: int = 1) -> dict:
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "workflow_version": "v004",
        "status": "completed",
        "media_type": "image",
        "positive_prompt": prompt,
        "negative_prompt": "",
        "params_json": f'{{"positive_prompt": "{prompt}", "seed": {seed}}}',
        "output_files": f'[{{"filename": "{prompt_id}.png"}}]',
    }


class FakeHost:
    """A gallery reduced to what a search asks of one."""

    def __init__(self, scope=_Scope("All", None), groups=None):
        self.scope = scope
        self.groups = groups or {}
        self.shown = []          # every show_search_results call, in order
        self.headers = []        # every header the search wrote
        self.drawn = 0
        self.handed_back = 0
        self.history_held = 0

    def search_scope(self):
        return self.scope

    def image_config_index(self) -> dict:
        return {}

    def group_for_key(self, key: str):
        return self.groups.get(key)

    def show_search_results(self, tiles, **terms):
        self.shown.append((list(tiles), terms))

    def name_search_on_screen(self, query: str, scope: str) -> None:
        self.headers.append((query, scope))

    def search_results_drawn(self) -> None:
        self.drawn += 1

    def hand_pane_back(self) -> None:
        self.handed_back += 1

    @contextmanager
    def suppress_history(self):
        self.history_held += 1
        yield


@pytest.fixture
def controller(qtbot):
    """A controller under a parent this fixture keeps alive: a QObject whose
    parent is collected takes its timers down with it."""
    built = []

    def build(rows=(), host=None):
        parent = QWidget()
        qtbot.addWidget(parent)
        found = GallerySearchController(host or FakeHost(), parent=parent)
        found.index.update(list(rows))
        built.append((parent, found))
        return found

    yield build


def _type(found, text):
    """Type a query and let its debounce fire, as the field's own timer would."""
    found.field.setText(text)
    if found._timer.isActive():
        found._timer.stop()
        found._run_pending()


def test_a_query_reaches_the_pane_as_the_rows_that_matched_it(controller):
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall"), _row("g2", "a hound")],
                       host=host)

    _type(found, "tabby")

    tiles, terms = host.shown[-1]
    assert [tile.row["prompt_id"] for tile in tiles] == ["g1"]
    assert terms["query"] == "tabby"
    assert host.headers[-1] == ("tabby", "All")
    assert host.drawn == 1


def test_nothing_at_all_is_searched_under_the_floor(controller):
    # One or two letters reach a large fraction of any library through stemming
    # alone, so an as-you-type search would answer the first keystroke of every
    # query with most of the gallery.
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)

    found.field.setText("t" * (MIN_CHARS - 1))

    assert not found._timer.isActive()
    assert host.shown == []
    assert found.query == ""


def test_clearing_the_field_is_the_one_way_out(controller):
    # Every gesture that leaves a search goes through the field, so the exit runs
    # once however it was reached -- and `leave` is off the history, because the
    # folder the pane goes back to is a step on the way rather than a stop.
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)
    _type(found, "tabby")

    found.leave()

    assert found.field.text() == ""
    assert found.query == ""
    assert host.handed_back == 1
    assert host.history_held == 1
    assert found.bar.isHidden()


def test_leaving_a_search_that_was_never_running_does_nothing(controller):
    host = FakeHost()
    found = controller(host=host)

    found.leave()

    assert (host.handed_back, host.history_held) == (0, 0)


def test_several_hits_in_one_folder_come_back_as_that_folder(controller):
    # Every row in a settings folder shares a prompt and settings and differs
    # only by seed, so a prompt match hits all of them -- and drawing eight
    # near-copies of one picture buries the other places the query reached.
    rows = [_row("g1", "a tabby on a wall", seed=1),
            _row("g2", "a tabby on a wall", seed=2)]
    host = FakeHost()
    found = controller(rows, host=host)
    key = next(iter({_folder_key(row) for row in rows}))
    host.groups[key] = object()

    _type(found, "tabby")

    tiles, _ = host.shown[-1]
    assert len(tiles) == 1
    assert tiles[0].group is host.groups[key]
    assert {tile["prompt_id"] for tile in tiles[0].rows} == {"g1", "g2"}


def test_a_folder_the_tree_has_no_row_for_falls_back_to_its_own_items(controller):
    rows = [_row("g1", "a tabby on a wall", seed=1),
            _row("g2", "a tabby on a wall", seed=2)]
    host = FakeHost()   # no groups at all
    found = controller(rows, host=host)

    _type(found, "tabby")

    tiles, _ = host.shown[-1]
    assert {tile.row["prompt_id"] for tile in tiles} == {"g1", "g2"}
    assert all(tile.group is None for tile in tiles)


def test_a_widening_that_lands_for_the_running_query_re_runs_it(controller):
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall"), _row("g2", "a hound")],
                       host=host)
    _type(found, "kitten")
    assert host.shown[-1][0] == []            # nothing matches the bare word

    found._expander.expanded.emit("kitten", {"kitten": ("tabby",)})

    assert [tile.row["prompt_id"] for tile in host.shown[-1][0]] == ["g1"]


def test_a_widening_for_a_query_the_user_has_typed_past_is_ignored(controller):
    # A slow answer can land after the user has moved on, and widening results
    # for a query they are no longer running would put items on screen they
    # cannot account for.
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)
    _type(found, "hound")
    drawn = len(host.shown)

    found._expander.expanded.emit("kitten", {"kitten": ("tabby",)})

    assert len(host.shown) == drawn


def test_a_folded_band_stays_folded_across_a_redraw(controller):
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)
    _type(found, "tabby")

    host.shown[-1][1]["on_section_toggled"]("SDXL  ·  none", True)
    found.run()

    assert host.shown[-1][1]["collapsed"] == {"SDXL  ·  none"}


def test_a_restored_query_comes_back_without_searching_again(controller):
    # The typing signals debounce and re-run, which would answer a restore with a
    # search a beat later, over whatever the restore had by then moved on to.
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)

    found.restore("tabby")

    assert (found.field.text(), found.query) == ("tabby", "tabby")
    assert not found._timer.isActive()
    assert host.shown == []


def test_the_count_line_says_a_capped_search_is_showing_a_slice(controller):
    # A capped search that said only "2,000 results" would read as 2,000 tiles
    # you could scroll to.
    from origenerator.gui.browser_pane import SEARCH_DRAW_LIMIT

    host = FakeHost()
    found = controller(
        [_row(f"g{n}", f"a tabby number {n}") for n in range(SEARCH_DRAW_LIMIT + 5)],
        host=host)

    _type(found, "tabby")

    assert f"{SEARCH_DRAW_LIMIT + 5:,} results" in found._count.text()
    assert "add a word" in found._count.text()


def test_the_field_says_what_a_query_typed_in_it_would_search(controller):
    host = FakeHost(scope=_Scope("Landscape  ›  Latest", set()))
    found = controller(host=host)

    found.sync_placeholder()

    assert found.field.placeholderText() == "Search Landscape  ›  Latest…"


def _folder_key(row: dict) -> str:
    from origenerator import gallery
    return gallery.settings_folder_key(row, {})
