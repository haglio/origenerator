from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtWidgets import (
    QSplitter,
    QTabWidget,
)

from origenerator import (
    gallery,
)
from origenerator.comfyui_client import ComfyUIClient
from origenerator.db import Database, NewGeneration
from origenerator.gui import generate_tab as generate_tab_module
from origenerator.gui.gallery_view import _GROUP_ROLE, GalleryView
from origenerator.gui.generate_tab import GenerateTab
from origenerator.gui.source_tile import SourceTile
from origenerator.gui.viewport import Viewport
from tests.comfyui_folders import SUITE_FOLDERS
from tests.gallery_view_support import (
    _SDXL,
    FakeDB,
    _image,
    _image_workflow,
    _png_bytes,
    _row,
    _shape,
    _video_workflow,
    _viewport_of,
)

pytestmark = pytest.mark.usefixtures("_stub_preview_resolution")


def _animations(view):
    return view._generate_pane.current_generate_tab()._related._animations


def test_selecting_an_image_lists_the_videos_it_was_animated_into(qtbot):
    image = _image("img1", "a cat", 50, 1)
    video = _row("vid1", "wan22_i2v",
                 {"positive_prompt": "dance", "input_image": "sdxl_t2i_img1.png"},
                 "wan22_i2v_vid1.mp4")
    view = GalleryView(FakeDB([image, video]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("img1")
    assert not _animations(view).isHidden()
    assert len(_animations(view).findChildren(SourceTile)) == 1

    _animations(view).activated.emit("vid1")
    assert view._selected["prompt_id"] == "vid1"


def test_animation_strip_is_hidden_for_a_video_or_an_unanimated_image(qtbot):
    image = _image("img1", "a cat", 50, 1)
    lonely = _image("img2", "a dog", 50, 2)
    video = _row("vid1", "wan22_i2v",
                 {"input_image": "sdxl_t2i_img1.png"}, "wan22_i2v_vid1.mp4")
    view = GalleryView(FakeDB([image, lonely, video]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    for tab in view._generate_pane.generate_tabs():
        tab._viewport.show_media = MagicMock()

    view._on_thumbnail_clicked("vid1")
    assert _animations(view).isHidden()

    view._on_thumbnail_clicked("img2")
    assert _animations(view).isHidden()
    assert _animations(view).findChildren(SourceTile) == []


def test_clicking_thumbnail_shows_resolved_preview(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _viewport_of(view).show_media = MagicMock()
    resolved = (Path("C:/out/sdxl_t2i_i1.png"), "image")
    monkeypatch.setattr(generate_tab_module, "resolve_preview", MagicMock(return_value=resolved))

    view._on_thumbnail_clicked("i1")

    assert _viewport_of(view).show_media.call_args.args == (resolved[0], "image", "i1")


def test_clicking_thumbnail_without_media_clears_preview(qtbot, monkeypatch):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()
    _viewport_of(view).clear = MagicMock()
    _viewport_of(view).show_media = MagicMock()
    monkeypatch.setattr(generate_tab_module, "resolve_preview", MagicMock(return_value=None))

    view._on_thumbnail_clicked("i1")

    assert _viewport_of(view).clear.called
    _viewport_of(view).show_media.assert_not_called()


def test_gallery_creates_a_viewport(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert isinstance(_viewport_of(view), Viewport)


def test_gallery_panes_sit_in_a_draggable_splitter(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)

    for splitter in (view._arrangement.panes, view._arrangement.folder_panes, view._arrangement.left_column):
        assert isinstance(splitter, QSplitter)
        assert not splitter.childrenCollapsible()
    assert view._arrangement.folder_panes.count() == 2
    assert view._arrangement.folder_panes.widget(0).isAncestorOf(view._tree)
    assert view._arrangement.folder_panes.widget(1).isAncestorOf(view._scroll)
    assert view._arrangement.left_column.count() == 2
    assert view._arrangement.left_column.widget(0) is view._arrangement.folder_panes
    assert view._arrangement.left_column.widget(1) is view._queue
    assert view._arrangement.panes.count() == 2
    assert view._arrangement.panes.widget(0) is view._arrangement.left_column
    assert view._arrangement.panes.widget(1).isAncestorOf(_viewport_of(view))
    assert not view._arrangement.panes.widget(1).isAncestorOf(view._queue)


def test_the_generate_panes_floor_is_the_tab_it_holds(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    tab = view._generate_pane.current_generate_tab()
    assert view._arrangement.panes.widget(1).minimumWidth() == 0
    assert view._arrangement.panes.widget(1).minimumSizeHint().width() >= tab.minimumSizeHint().width()
    assert tab.minimumSizeHint().width() == tab._contents_floor()


def test_the_generate_pane_is_a_tab_widget_of_editable_generate_tabs(qtbot):
    view = GalleryView(FakeDB([]))
    qtbot.addWidget(view)
    assert isinstance(view._generate_pane, QTabWidget)
    assert view._arrangement.panes.widget(1).isAncestorOf(view._generate_pane)
    assert isinstance(view._generate_pane.widget(0), GenerateTab)
    assert view._generate_pane.widget(0).isAncestorOf(_viewport_of(view))


def test_selecting_a_thumbnail_loads_it_into_the_front_tab(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("i1")

    tab = view._generate_pane.current_generate_tab()
    assert tab is view._generate_pane.currentWidget()
    assert tab._displayed_row["prompt_id"] == "i1"


def test_a_rebuilds_reselection_leaves_the_active_tab_alone(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["i1"])
    editing = view._generate_pane._add_subtab()
    editing._viewport.show_media = MagicMock()
    count = view._generate_pane.count()

    view._reselect_generation("i1")

    assert view._selected_row["prompt_id"] == "i1"
    assert view._generate_pane.currentWidget() is editing
    assert view._generate_pane.count() == count
    assert editing._displayed_row is None
    editing._viewport.show_media.assert_not_called()


def _current_form(view):
    return view._generate_pane.current_generate_tab()._param_form


def test_selecting_a_thumbnail_loads_its_params_into_the_form(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    params = dict(_SDXL.default_params(), positive_prompt="a wizard", seed=123)
    db.insert_generation(NewGeneration(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a wizard", seed=123,
        params_json=json.dumps(params), workflow_json="{}",
    ))
    view = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()

    view._on_thumbnail_clicked("g1")

    values = _current_form(view).get_values()
    assert values["positive_prompt"] == "a wizard"
    assert values["seed"] == 123


def test_a_rebuilds_reselection_does_not_reload_the_form(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    params = dict(_SDXL.default_params(), positive_prompt="a wizard")
    db.insert_generation(NewGeneration(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a wizard", params_json=json.dumps(params), workflow_json="{}",
    ))
    view = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    view._tree.setCurrentItem(view._leaf_by_id["g1"])
    view._on_thumbnail_clicked("g1")
    _current_form(view).set_values({"positive_prompt": "my edit"})

    view.refresh()

    assert _current_form(view).get_values()["positive_prompt"] == "my edit"


def test_selecting_an_unregistered_thumbnail_leaves_no_settings_from_before(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="reg", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a cat", params_json=json.dumps(dict(_SDXL.default_params())),
        workflow_json="{}",
    ))
    db.insert_generation(NewGeneration(
        prompt_id="unreg", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    ))
    view = GalleryView(db, client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("reg")

    view._on_thumbnail_clicked("unreg")

    tab = view._generate_pane.current_generate_tab()
    assert tab._displayed_row["prompt_id"] == "unreg"
    assert tab._workflow_dropdown.currentIndex() == -1
    assert tab._param_form is None


def test_a_restored_selection_leaves_the_resting_tab_empty(qtbot, monkeypatch):
    monkeypatch.setattr(gallery, "resolve_preview",
                        lambda row, places: (Path("C:/out/sdxl_t2i_i2.png"), "image"))
    rows = [_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)]
    db = FakeDB(rows)
    probe = GalleryView(db)
    qtbot.addWidget(probe)
    probe.refresh()
    probe._tree.setCurrentItem(probe._leaf_by_id["i1"])
    folder_key = probe.selected_folder()

    view = GalleryView(db)
    qtbot.addWidget(view)
    _viewport_of(view).show_media = MagicMock()
    view.select_folder(folder_key)
    view.select_generation("i2")
    view.refresh()

    assert view.selected_generation() == "i2"
    tab = view._generate_pane.current_generate_tab()
    assert tab.is_blank()
    tab._viewport.show_media.assert_not_called()


def _make_db(tmp_path):
    db = Database(tmp_path / "test.db")
    db.insert_generation(NewGeneration(
        prompt_id="p1",
        workflow_name="sdxl_t2i",
        workflow_version="v002",
        positive_prompt="a cat",
        negative_prompt="blurry",
        seed=7,
        params_json=json.dumps({"steps": 20}),
        workflow_json="{}",
    ))
    return db


def test_clicking_a_thumbnail_seeds_the_tab_with_its_parameters(qtbot, tmp_path):
    db = _make_db(tmp_path)
    view = GalleryView(db)
    qtbot.addWidget(view)

    view._on_thumbnail_clicked("p1")

    tab = view._generate_pane.current_generate_tab()
    assert tab._workflow_dropdown.currentData() == "sdxl_t2i"
    values = tab._param_form.get_values()
    assert (values["steps"], values["positive_prompt"], values["negative_prompt"],
            values["seed"]) == (20, "a cat", "blurry", 7)


def test_double_clicking_a_thumbnail_pins_the_tab_it_opened(qtbot, tmp_path):
    db = _make_db(tmp_path)
    view = GalleryView(db)
    qtbot.addWidget(view)
    view._on_thumbnail_clicked("p1")
    assert view._generate_pane._preview_tab is view._generate_pane.current_generate_tab()

    view._gallery_pane._thumbnail_double_clicked("p1")

    tab = view._generate_pane.current_generate_tab()
    assert tab.displayed_row()["prompt_id"] == "p1"
    assert view._generate_pane._preview_tab is None


def test_browsing_item_after_item_costs_one_tab(qtbot, tmp_path):
    db = _make_db(tmp_path)
    for i, prompt in enumerate(["a dog", "a heron", "a fox"], start=2):
        db.insert_generation(NewGeneration(
            prompt_id=f"p{i}", workflow_name="sdxl_t2i", workflow_version="v002",
            positive_prompt=prompt, seed=i, params_json=json.dumps({"steps": 20}),
            workflow_json="{}",
        ))
    view = GalleryView(db)
    qtbot.addWidget(view)

    for i in range(1, 5):
        view._on_thumbnail_clicked(f"p{i}")

    assert view._generate_pane.count() == 1


def test_a_double_click_then_a_click_leaves_two_tabs(qtbot, tmp_path):
    db = _make_db(tmp_path)
    db.insert_generation(NewGeneration(
        prompt_id="p2", workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt="a dog", seed=8, params_json=json.dumps({"steps": 20}),
        workflow_json="{}",
    ))
    view = GalleryView(db)
    qtbot.addWidget(view)

    view._gallery_pane._thumbnail_double_clicked("p1")
    view._on_thumbnail_clicked("p2")

    assert view._generate_pane.count() == 2
    kept = view._generate_pane.widget(0)
    assert kept.displayed_row()["prompt_id"] == "p1"


def test_double_clicking_an_unregistered_thumbnail_still_pins_its_tab(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(NewGeneration(
        prompt_id="unreg", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    ))
    view = GalleryView(db)
    qtbot.addWidget(view)

    view._gallery_pane._thumbnail_double_clicked("unreg")

    assert view._generate_pane._preview_tab is None


def test_selecting_generation_shows_typical_time_in_the_loaded_tab(qtbot):
    rows = [
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=700.0),
        _row("v2", "wan22_i2v", {"seed": 2}, "wan22_i2v_2.mp4", duration_seconds=724.0),
        _row("v3", "wan22_i2v", {"seed": 3}, "wan22_i2v_3.mp4", duration_seconds=800.0),
    ]
    view = GalleryView(FakeDB(rows), client=ComfyUIClient(folders=SUITE_FOLDERS))
    qtbot.addWidget(view)
    view.refresh()
    for tab in view._generate_pane.generate_tabs():
        tab._viewport.show_media = MagicMock()

    view._on_thumbnail_clicked("v1")
    estimate = view._generate_pane.current_generate_tab()._estimate_label
    assert estimate.text() == "~12 min (based on 3 runs)"


def test_selecting_a_folder_shows_average_time_across_its_items(qtbot):
    rows = [
        _row("v1", "wan22_i2v", {"seed": 1}, "wan22_i2v_1.mp4", duration_seconds=700.0),
        _row("v2", "wan22_i2v", {"seed": 2}, "wan22_i2v_2.mp4", duration_seconds=724.0),
        _row("v3", "wan22_i2v", {"seed": 3}, "wan22_i2v_3.mp4", duration_seconds=800.0),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _video_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
    assert view._avg_label.text() == "Average time: ~12 min (across 3 runs)"


def test_folder_without_timed_items_shows_no_average(qtbot):
    view = GalleryView(FakeDB([_image("i1", "a cat", 50, 1)]))
    qtbot.addWidget(view)
    view.refresh()

    workflow = _image_workflow(view._tree)
    view._tree.setCurrentItem(workflow)
    assert view._avg_label.text() == ""


def _find_settings_node(view, predicate):
    def walk(item):
        group = item.data(0, _GROUP_ROLE)
        if isinstance(group, gallery.SettingsGroup) and predicate(group):
            return item
        for i in range(item.childCount()):
            hit = walk(item.child(i))
            if hit is not None:
                return hit
        return None
    half = _shape(view._tree)
    for i in range(half.topLevelItemCount()):
        hit = walk(half.topLevelItem(i))
        if hit is not None:
            return hit
    return None


def test_untimed_prompt_folder_falls_back_to_workflow_time(qtbot):
    rows = [
        _row("v_untimed", "wan22_i2v", {"steps": 30, "seed": 2}, "wan22_i2v_2.mp4"),
        _row("v_timed", "wan22_i2v", {"steps": 20, "seed": 1}, "wan22_i2v_1.mp4",
             duration_seconds=1390.0),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    node = _find_settings_node(
        view, lambda g: all(r.get("duration_seconds") is None for r in g.rows)
    )
    assert node is not None
    view._tree.setCurrentItem(node)
    assert view._avg_label.text() == "Average time: ~23 min (across 1 run)"


def test_timed_prompt_folder_uses_its_own_average_not_the_workflow(qtbot):
    rows = [
        _row("v_slow", "wan22_i2v", {"steps": 30, "seed": 9}, "wan22_i2v_9.mp4",
             duration_seconds=1390.0),
        _row("v1", "wan22_i2v", {"steps": 20, "seed": 1}, "wan22_i2v_1.mp4",
             duration_seconds=60.0),
        _row("v2", "wan22_i2v", {"steps": 20, "seed": 2}, "wan22_i2v_2.mp4",
             duration_seconds=80.0),
    ]
    view = GalleryView(FakeDB(rows))
    qtbot.addWidget(view)
    view.refresh()

    node = _find_settings_node(view, lambda g: {r["prompt_id"] for r in g.rows} == {"v1", "v2"})
    assert node is not None
    view._tree.setCurrentItem(node)
    assert view._avg_label.text() == "Average time: ~1 min (across 2 runs)"


def test_a_rebuild_takes_an_item_that_has_gone_off_the_tab_showing_it(qtbot, tmp_path):
    db = FakeDB([_image("i1", "a cat", 50, 1), _image("i2", "a cat", 50, 2)])
    view = GalleryView(db)
    qtbot.addWidget(view)
    view.refresh()
    view._on_thumbnail_clicked("i2")
    tab = view._generate_pane.current_generate_tab()
    gone = tmp_path / "gone.png"
    gone.write_bytes(_png_bytes())
    tab._viewport.show_image(gone)

    db.delete_generation("i2")
    view.refresh()

    assert not tab._viewport.is_showing_any([gone])
