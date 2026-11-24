from __future__ import annotations

import json
import threading

from PySide6.QtCore import QObject, Signal, Slot

from origenerator.db import NewGeneration
from origenerator.gallery.collection import (
    ENHANCED_KEY,
    ENHANCED_LABEL,
    EXPERIMENTS_LABEL,
    LATEST_KEY,
    POPULATING_KEY,
    POPULATING_LABEL,
)
from origenerator.gallery.shapes import LANDSCAPE
from origenerator.gui.gallery_tree import TREE_KEY_ROLE
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.slideshow_director import _plays_newest_first
from origenerator.item_shape import shaped_key
from tests.gallery_view_support import (
    _SDXL,
    _alls,
    _at,
    _collection,
    _finish_reroll,
    _image_workflow,
    _reroll_client,
    _seeded_db,
)


class _WindowTurn(QObject):
    asked = Signal()

    def __init__(self):
        super().__init__()
        self.taken = threading.Event()
        self.asked.connect(self._take)

    @Slot()
    def _take(self):
        self.taken.set()


def _accepted_only_after_the_window_has_had_a_turn(client):
    turn = _WindowTurn()

    def submit(*_args, **_kwargs):
        turn.taken.clear()
        turn.asked.emit()
        turn.taken.wait()
        return "comfy-X"

    client.submit_job.side_effect = submit


def _two_folders(qtbot, tmp_path):
    db = _seeded_db(tmp_path)
    db.insert_generation(NewGeneration(
        prompt_id="other", workflow_name="sdxl_t2i", workflow_version=_SDXL.version,
        positive_prompt="a dog", negative_prompt="", seed=9,
        params_json=json.dumps(dict(_SDXL.default_params(), seed=9, positive_prompt="a dog")),
        workflow_json="{}",
    ))
    db.update_generation("other", status="completed",
                         output_files=json.dumps([{"filename": "b.png", "subfolder": ""}]))
    client = _reroll_client()
    _accepted_only_after_the_window_has_had_a_turn(client)
    view = GalleryView(db, client=client)
    qtbot.addWidget(view)
    view.refresh()
    settings = _at(_image_workflow(view._tree), 0, 0)
    first, second = (_at(settings, index).data(0, _GROUP_ROLE).key for index in (0, 1))
    return view, first, second


def _open(view, key):
    view._tree.setCurrentItem(view.toc.item_for(key))


def _populate_in(view, key):
    _open(view, key)
    view._toggle_populate(True)


def _open_populating(view):
    view._tree.setCurrentItem(_collection(view, POPULATING_KEY))


def _listed(view) -> list[str]:
    return [row["prompt_id"] for row in view._gallery_pane.collection_rows()]


def test_populate_runs_in_two_folders_at_once(qtbot, tmp_path):
    view, first, second = _two_folders(qtbot, tmp_path)
    _populate_in(view, first)

    _populate_in(view, second)

    assert view._populate.active_keys() == (first, second)


def test_the_switch_says_whether_populate_runs_in_the_folder_it_is_over(qtbot, tmp_path):
    view, first, second = _two_folders(qtbot, tmp_path)
    _populate_in(view, first)

    _open(view, second)

    switch = view._buttons.populate
    assert (switch.isChecked(), switch.isEnabled()) == (False, True), (
        "with Populate able to run in several folders, a press here starts it here, so the "
        "switch shows this folder's Populate and no other's")


def test_turning_the_switch_off_in_one_folder_leaves_populate_running_in_the_other(
        qtbot, tmp_path):
    view, first, second = _two_folders(qtbot, tmp_path)
    _populate_in(view, first)
    _populate_in(view, second)

    view._toggle_populate(False)

    assert view._populate.active_keys() == (first,)


def test_the_populating_folder_sits_between_enhanced_and_experiments(qtbot, tmp_path):
    view, _first, _second = _two_folders(qtbot, tmp_path)

    labels = list(_alls(view._tree))

    at = labels.index(POPULATING_LABEL)
    assert labels[at - 1:at + 2] == [ENHANCED_LABEL, POPULATING_LABEL, EXPERIMENTS_LABEL]


def test_the_populating_folder_holds_what_populate_made_and_is_making(qtbot, tmp_path):
    view, first, _second = _two_folders(qtbot, tmp_path)
    _populate_in(view, first)
    made = view._live_jobs[first]
    _finish_reroll(view, made)
    making = view._live_jobs[first]

    _open_populating(view)

    assert (_listed(view), list(view._gallery_pane._inflight_tiles)) == (
        [made.prompt_id], [making.prompt_id])


def test_an_item_leaves_the_populating_folder_once_its_populate_stops(qtbot, tmp_path):
    view, first, _second = _two_folders(qtbot, tmp_path)
    _populate_in(view, first)
    _finish_reroll(view, view._live_jobs[first])
    _open_populating(view)

    view._populate.stop(first)

    assert (_listed(view), list(view._gallery_pane._inflight_tiles)) == ([], [])


def test_in_the_populating_folder_the_switch_stops_populate_everywhere_then_grays(
        qtbot, tmp_path):
    view, first, second = _two_folders(qtbot, tmp_path)
    _populate_in(view, first)
    _populate_in(view, second)
    _open_populating(view)
    switch = view._buttons.populate
    assert (switch.isChecked(), switch.isEnabled()) == (True, True)

    switch.click()

    assert view._populate.active_keys() == ()
    assert (switch.isChecked(), switch.isEnabled()) == (False, False)


def test_a_slideshow_of_populating_plays_newest_first_as_one_of_latest_does():
    played_newest_first = [_plays_newest_first(shaped_key(key, LANDSCAPE))
                           for key in (LATEST_KEY, POPULATING_KEY, ENHANCED_KEY)]

    assert played_newest_first == [True, True, False]


def test_with_populate_running_elsewhere_the_switchs_tip_takes_you_to_populating(
        qtbot, tmp_path):
    view, first, second = _two_folders(qtbot, tmp_path)
    _populate_in(view, first)
    _open(view, second)
    told = (view._buttons.populate.toolTip(), view._buttons.populate_tip._html)

    view._buttons.populate_tip.link_activated.emit("populate")

    assert (told[0], "Populate is running in another folder" in told[1]) == ("", True)
    assert view.selected_folder_key() == view.toc.collection_item(
        POPULATING_KEY, view.toc.shape_in_view()).data(0, TREE_KEY_ROLE)
