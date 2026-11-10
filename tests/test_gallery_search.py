from __future__ import annotations

from contextlib import contextmanager
from typing import NamedTuple

import pytest
from PyQt6.QtCore import QPoint, QPointF, Qt
from PyQt6.QtGui import QWheelEvent
from PyQt6.QtWidgets import QApplication, QWidget

from origenerator import gallery
from origenerator.gui.gallery_pane import SEARCH_DRAW_LIMIT
from origenerator.gui.gallery_search import MIN_CHARS, GallerySearchController
from origenerator.gui.search_expander import SearchExpander


class _Scope(NamedTuple):
    path: str
    ids: set[str] | None


_ALL = _Scope("All", None)


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
    def __init__(self, scope=_ALL, groups=None):
        self.scope = scope
        self.groups = groups or {}
        self.shown = []
        self.headers = []
        self.drawn = 0
        self.handed_back = 0
        self.history_held = 0

    def search_scope(self):
        return self.scope

    def everything_scope(self):
        return _ALL

    def image_config_index(self) -> dict:
        return {}

    def group_for_key(self, key: str):
        return self.groups.get(key)

    def show_search_results(self, tiles, terms):
        self.shown.append((list(tiles), vars(terms)))

    def name_search_on_screen(self, query: str, scope) -> None:
        self.headers.append((query, scope.path))

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
    built = []

    def build(rows=(), host=None, expander=None):
        parent = QWidget()
        qtbot.addWidget(parent)
        found = GallerySearchController(host or FakeHost(), parent=parent, expander=expander)
        found.index.update(list(rows))
        built.append((parent, found))
        return found

    return build


def _type(found, text):
    found.field.setText(text)
    if found._timer.isActive():
        found._timer.stop()
        found._run_pending()


def _let_the_widening_land(qtbot, found):
    with qtbot.waitSignal(found._expander.expanded):
        found._expand_timer.stop()
        found._request_expansion()


_A_FOLDER = _Scope("All > Folder", {"g1"})


def test_search_all_searches_every_item_while_a_folder_is_open(controller):
    host = FakeHost(scope=_A_FOLDER)
    found = controller([_row("g1", "a tabby on a wall"), _row("g2", "a tabby in a box")], host=host)
    _type(found, "tabby")

    found.search_all.click()

    tiles, _terms = host.shown[-1]
    assert {tile.row["prompt_id"] for tile in tiles} == {"g1", "g2"}
    assert host.headers[-1] == ("tabby", "All")


def test_search_all_keeps_searching_every_item_as_the_words_change(controller):
    host = FakeHost(scope=_A_FOLDER)
    found = controller([_row("g1", "a tabby on a wall"), _row("g2", "a tabby in a box")], host=host)
    _type(found, "tabby")
    found.search_all.click()

    _type(found, "tabby in")

    assert host.headers[-1] == ("tabby in", "All")


def test_picking_a_folder_after_search_all_searches_that_folder(controller):
    host = FakeHost(scope=_A_FOLDER)
    found = controller([_row("g1", "a tabby on a wall"), _row("g2", "a tabby in a box")], host=host)
    _type(found, "tabby")
    found.search_all.click()

    found.follow_the_folder()
    found.run()

    assert host.headers[-1] == ("tabby", "All > Folder")


def test_a_search_left_and_started_again_searches_the_open_folder(controller):
    host = FakeHost(scope=_A_FOLDER)
    found = controller([_row("g1", "a tabby on a wall")], host=host)
    _type(found, "tabby")
    found.search_all.click()

    _type(found, "")
    _type(found, "tabby")

    assert host.headers[-1] == ("tabby", "All > Folder")


def test_search_all_is_grayed_until_a_search_can_start(controller):
    found = controller()
    grayed_tip = found.search_all.toolTip()

    _type(found, "ta")
    assert not found.search_all.isEnabled()
    _type(found, "tab")

    assert found.search_all.isEnabled()
    assert found.search_all.toolTip() != grayed_tip
    assert f"{MIN_CHARS} characters" in grayed_tip


def test_the_field_shows_a_search_is_still_going_until_its_widening_lands(controller, qtbot):
    expander = SearchExpander(expand=lambda query: {"kitten": ("tabby",)})
    found = controller([_row("g1", "a tabby on a wall")], expander=expander)

    _type(found, "kitten")
    assert found.field.working()

    _let_the_widening_land(qtbot, found)
    assert not found.field.working()


def test_a_search_for_a_name_alone_has_finished_once_it_is_drawn(controller):
    found = controller([_row("g1", "a tabby on a wall")])

    _type(found, "3FA9C0D2 004")

    assert not found.field.working()


def test_a_search_for_the_start_of_a_name_has_finished_once_it_is_drawn(controller):
    found = controller()
    found.index.update([_row("g1", "a tabby on a wall")], item_name={"g1": "79BB46F1 000"}.get)

    _type(found, "79BB")

    assert not found.field.working()


def test_a_search_for_quoted_words_alone_has_finished_once_it_is_drawn(controller):
    found = controller([_row("g1", "two lamps on a bench")])

    _type(found, '"two lamps"')

    assert not found.field.working()


def test_leaving_a_search_stops_the_circle(controller):
    found = controller([_row("g1", "a tabby on a wall")])
    _type(found, "kitten")

    found.leave()

    assert not found.field.working()


def test_an_answer_for_the_same_words_typed_another_way_ends_the_wait(controller, qtbot):
    expander = SearchExpander(expand=lambda query: {"kitten": ("tabby",)})
    found = controller([_row("g1", "a tabby on a wall")], expander=expander)
    _type(found, "kitten")

    with qtbot.waitSignal(expander.expanded):
        found._request_expansion()
        _type(found, "the kitten")
        found._request_expansion()

    assert not found.field.working()


def test_an_empty_search_says_so_only_once_it_has_finished(controller, qtbot):
    host = FakeHost()
    expander = SearchExpander(expand=lambda query: {})
    found = controller([_row("g1", "a tabby on a wall")], host=host, expander=expander)

    _type(found, "aardvark")
    assert host.shown[-1][1]["still_searching"]

    _let_the_widening_land(qtbot, found)
    assert not host.shown[-1][1]["still_searching"]


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
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)

    found.field.setText("t" * (MIN_CHARS - 1))

    assert not found._timer.isActive()
    assert host.shown == []
    assert found.query == ""


def test_clearing_the_field_is_the_one_way_out(controller):
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
    host = FakeHost()
    found = controller(rows, host=host)

    _type(found, "tabby")

    tiles, _ = host.shown[-1]
    assert {tile.row["prompt_id"] for tile in tiles} == {"g1", "g2"}
    assert all(tile.group is None for tile in tiles)


def test_a_widening_that_lands_for_the_running_query_re_runs_it(controller, qtbot):
    host = FakeHost()
    expander = SearchExpander(expand=lambda query: {"kitten": ("tabby",)})
    found = controller([_row("g1", "a tabby on a wall"), _row("g2", "a hound")],
                       host=host, expander=expander)
    _type(found, "kitten")
    assert host.shown[-1][0] == []

    _let_the_widening_land(qtbot, found)

    assert [tile.row["prompt_id"] for tile in host.shown[-1][0]] == ["g1"]


def test_a_widening_for_a_query_the_user_has_typed_past_is_ignored(controller, qtbot):
    host = FakeHost()
    expander = SearchExpander(expand=lambda query: {"kitten": ("tabby",)})
    found = controller([_row("g1", "a tabby on a wall")], host=host, expander=expander)
    _type(found, "kitten")

    with qtbot.waitSignal(expander.expanded):
        found._request_expansion()
        _type(found, "hound")
        drawn = len(host.shown)

    assert len(host.shown) == drawn


def test_a_folded_band_stays_folded_across_a_redraw(controller):
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)
    _type(found, "tabby")

    host.shown[-1][1]["on_section_toggled"]("SDXL  ·  none", True)
    found.run()

    assert host.shown[-1][1]["collapsed"] == {"SDXL  ·  none"}


def test_a_restored_query_comes_back_without_searching_again(controller):
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host)

    found.restore("tabby")

    assert (found.field.text(), found.query) == ("tabby", "tabby")
    assert not found._timer.isActive()
    assert host.shown == []


def test_the_count_line_says_a_capped_search_is_showing_a_slice(controller):
    host = FakeHost()
    found = controller(
        [_row(f"g{n}", f"a tabby number {n}") for n in range(SEARCH_DRAW_LIMIT + 5)],
        host=host)

    _type(found, "tabby")

    assert f"{SEARCH_DRAW_LIMIT + 5:,} results" in found._count.text()
    assert "add a word" in found._count.text()


def test_leaving_takes_whatever_the_gesture_passes(controller):
    found = controller([_row("g1", "a tabby on a wall")])
    _type(found, "tabby")

    found.leave("opened", 3)

    assert found.query == ""


def test_a_remembered_order_this_version_does_not_offer_is_ignored(controller):
    found = controller()
    before = found.sort()

    found.set_sort("an_order_a_later_version_offered")

    assert found.sort() == before


def test_a_widening_that_found_nothing_leaves_results_already_on_screen(controller, qtbot):
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host,
                       expander=SearchExpander(expand=lambda query: {}))
    _type(found, "tabby")
    drawn = len(host.shown)

    _let_the_widening_land(qtbot, found)

    assert len(host.shown) == drawn


def test_a_widening_that_found_nothing_redraws_an_empty_pane_to_say_so(controller, qtbot):
    host = FakeHost()
    found = controller([_row("g1", "a tabby on a wall")], host=host,
                       expander=SearchExpander(expand=lambda query: {}))
    _type(found, "kitten")
    drawn = len(host.shown)

    _let_the_widening_land(qtbot, found)

    assert len(host.shown) == drawn + 1


def test_the_field_says_what_a_query_typed_in_it_would_search(controller):
    host = FakeHost(scope=_Scope("Landscape  \u203a  Latest", set()))
    found = controller(host=host)

    found.sync_placeholder()

    assert found.field.placeholderText() == "Search Landscape  \u203a  Latest…"


def test_the_sort_menu_names_the_model_lora_order_the_way_the_forms_do(controller):
    found = controller()

    orders = [found._sort_dropdown.itemText(i) for i in range(found._sort_dropdown.count())]

    assert orders == ["Recent", "Model / LoRA"]


def test_the_wheel_over_the_order_is_left_for_the_results_under_it(controller):
    found = controller()
    order = found._sort_dropdown
    turn = QWheelEvent(QPointF(1, 1), QPointF(1, 1), QPoint(0, 0), QPoint(0, -120),
                       Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                       Qt.ScrollPhase.NoScrollPhase, False)

    QApplication.sendEvent(order, turn)

    assert order.currentText() == "Recent", (
        "the order sits over the scrolling results, so a turn of the wheel meant for them "
        "must not change it")
    assert not turn.isAccepted()


def _folder_key(row: dict) -> str:
    return gallery.settings_folder_key(row, {})
