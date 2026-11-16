from __future__ import annotations

import json

from origenerator import branch_session, gallery
from origenerator.db import NewGeneration
from origenerator.gallery.collection import FAVORITES_KEY
from origenerator.gui.gallery_view import GalleryView
from tests.gallery_view_support import (
    _at,
    _children_by_prompt,
    _enhanceable_db,
    _image,
    _image_workflow,
    _key,
    _reroll_client,
    _select_first_leaf,
    _set_enhance,
)
from tests.real_db import database_of, put_rows


def _view_of(qtbot, *rows):
    return _view_of_db(qtbot, database_of(list(rows)))


def _view_of_db(qtbot, db):
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    return view


def _leaf_of(view, prompt: str) -> str:
    return _key(_children_by_prompt(_at(_image_workflow(view._tree), 0, 0))[prompt])


def _starred(view, *prompt_ids) -> list[bool]:
    return [bool(view._db.get_generation(pid).get("starred")) for pid in prompt_ids]


def test_favoriting_a_leaf_folder_stars_every_item_in_it(qtbot):
    view = _view_of(qtbot, _image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1),
                    _image("i3", "a cat", 50, 2))

    view.toc_editing.toggle_favorite(_leaf_of(view, "a cat"))

    assert _starred(view, "i1", "i3", "i2") == [True, True, False]


def test_an_item_that_arrives_in_a_favorited_leaf_folder_is_starred(qtbot):
    view = _view_of(qtbot, _image("i1", "a cat", 50, 1))
    view.toc_editing.toggle_favorite(_leaf_of(view, "a cat"))

    put_rows(view._db, [_image("i2", "a cat", 50, 2)])
    view.refresh()

    assert _starred(view, "i2") == [True]


def test_an_item_unstarred_after_its_folder_starred_it_stays_unstarred(qtbot):
    view = _view_of(qtbot, _image("i1", "a cat", 50, 1))
    view.toc_editing.toggle_favorite(_leaf_of(view, "a cat"))

    view.set_items_favorite(["i1"], False)
    put_rows(view._db, [_image("i2", "a cat", 50, 2)])
    view.refresh()

    assert _starred(view, "i1", "i2") == [False, True]


def test_unfavoriting_a_leaf_folder_leaves_its_items_stars_and_stars_no_more(qtbot):
    view = _view_of(qtbot, _image("i1", "a cat", 50, 1))
    leaf = _leaf_of(view, "a cat")
    view.toc_editing.toggle_favorite(leaf)

    view.toc_editing.toggle_favorite(leaf)
    put_rows(view._db, [_image("i2", "a cat", 50, 2)])
    view.refresh()

    assert _starred(view, "i1", "i2") == [True, False]


def test_a_folder_with_folders_inside_takes_no_favorite(qtbot):
    view = _view_of(qtbot, _image("i1", "a cat", 50, 1))
    workflow = _key(_image_workflow(view._tree))

    view.toc_editing.toggle_favorite(workflow)

    assert not view.group_for_key(workflow).favorite
    assert _starred(view, "i1") == [False]


def _enhancing_view(qtbot, tmp_path, count=1):
    db = _enhanceable_db(tmp_path, count=count)
    view = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(view)
    view.refresh()
    _set_enhance(view, auto=False)
    return view, db, _select_first_leaf(view)


def _enhancing(view) -> list[str]:
    return sorted(job.params["input_image"] for job in view._jobs.all_jobs)


def _an_image_arrives(db, prompt_id: str, seed: int) -> None:
    db.insert_generation(NewGeneration(
        prompt_id=prompt_id, workflow_name="sdxl_t2i",
        workflow_version=db.get_generation("g0")["workflow_version"],
        positive_prompt="a cat", seed=seed,
        params_json=json.dumps({"positive_prompt": "a cat", "steps": 30, "seed": seed}),
        workflow_json="{}"))
    db.update_generation(prompt_id, status="completed", output_files=json.dumps(
        [{"filename": f"sdxl_t2i_{prompt_id}.png", "subfolder": "image", "type": "output"}]))


def test_enhance_switched_on_enhances_each_image_that_arrives_after(qtbot, tmp_path):
    view, db, _leaf = _enhancing_view(qtbot, tmp_path)
    view._buttons.enhance.click()
    assert _enhancing(view) == ["image/sdxl_t2i_g0.png [output]"]

    _an_image_arrives(db, "g9", 9)
    view.refresh()

    assert _enhancing(view) == ["image/sdxl_t2i_g0.png [output]",
                                "image/sdxl_t2i_g9.png [output]"]


def test_enhance_switched_off_enhances_nothing_more_and_keeps_what_it_started(qtbot, tmp_path):
    view, db, _leaf = _enhancing_view(qtbot, tmp_path)
    view._buttons.enhance.click()

    view._buttons.enhance.click()
    _an_image_arrives(db, "g9", 9)
    view.refresh()

    assert _enhancing(view) == ["image/sdxl_t2i_g0.png [output]"]
    assert not view._buttons.enhance.isChecked()


def test_enhance_stays_switched_on_for_its_folder_after_a_restart(qtbot, tmp_path):
    view, db, key = _enhancing_view(qtbot, tmp_path)
    view._buttons.enhance.click()

    again = GalleryView(db, client=_reroll_client())
    qtbot.addWidget(again)
    again.refresh()
    again._tree.setCurrentItem(again.toc.item_for(key))

    assert again._buttons.enhance.isChecked()
    assert again._buttons.enhance.toolTip().startswith("Stop enhancing new images in")


def test_a_folder_with_folders_inside_dropped_onto_favorites_takes_no_favorite(qtbot):
    view = _view_of(qtbot, _image("i1", "a cat", 50, 1))
    workflow = _key(_image_workflow(view._tree))
    leaf = _leaf_of(view, "a cat")

    view.toc_editing.dropped(FAVORITES_KEY, [workflow, leaf])

    assert (view.group_for_key(workflow).favorite, view.group_for_key(leaf).favorite) == (
        False, True)


def _a_folder_starred_before_folders_starred_their_items(monkeypatch, preview: bool):
    monkeypatch.setenv(branch_session.ENV_FLAG, "1" if preview else "0")
    db = database_of([_image("i1", "a cat", 50, 1), _image("i2", "a dog", 50, 1)])
    key = gallery.settings_folder_key(db.get_generation("i1"))
    db.set_folder_favorite(key, True)
    return db


def test_production_stars_the_items_of_a_folder_starred_before_folders_starred_them(
        qtbot, monkeypatch):
    db = _a_folder_starred_before_folders_starred_their_items(monkeypatch, preview=False)

    view = _view_of_db(qtbot, db)

    assert _starred(view, "i1", "i2") == [True, False]


def test_a_preview_leaves_the_items_of_a_folder_starred_before_to_production(
        qtbot, monkeypatch):
    db = _a_folder_starred_before_folders_starred_their_items(monkeypatch, preview=True)

    view = _view_of_db(qtbot, db)

    assert _starred(view, "i1", "i2") == [False, False]
