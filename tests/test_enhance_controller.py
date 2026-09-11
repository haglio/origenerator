"""The standalone enhance, driven with no gallery around it.

What the button would run on and why a picture is passed over, what a batch
shares, and where a run in flight shows -- all of it used to be reachable only
by building the app's central widget. Here the surfaces are recorders.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json

import pytest

from origenerator import gallery
from origenerator.gui import enhance_controller as module
from origenerator.gui.enhance_controller import (
    ALREADY_AT_THESE_SETTINGS,
    NO_VIDEO_ENHANCER,
    EnhanceController,
)

ENHANCE = gallery.ENHANCE_WORKFLOW


class FakePanel:
    """The Enhance subpanel reduced to what the controller drives."""

    def __init__(self, on_changed):
        self.on_changed = on_changed
        self.shown = None
        self.applicable = None

    def show_settings(self, settings):
        self.shown = settings

    def set_applicable(self, applicable, why):
        self.applicable = (applicable, why)


class FakeWorkflow:
    name = ENHANCE
    version = "2"

    def seed_keys(self):
        return ("seed",)

    def default_params(self):
        return {}

    def param_definitions(self):
        return []


class FakeJob:
    def __init__(self, prompt_id, *, input_image="one.png", state="running",
                 workflow=None):
        self.prompt_id = prompt_id
        self.params = {"input_image": input_image}
        self.workflow = workflow or FakeWorkflow()
        self.state = state
        self.last_preview = b"frame" if state == "running" else None
        self.last_progress = 0.5
        self.last_pass_progress = 0.5
        self.last_stage = "sampling"
        self.started_at = 1.0


class FakeReroll:
    def __init__(self, jobs=(), launches="run-1"):
        self.all_jobs = list(jobs)
        self.prepared = []
        self.cancelled = []
        self.launches = launches

    def start_prepared(self, key, workflow, params):
        self.prepared.append((key, dict(params)))
        return self.launches

    def cancel_job(self, prompt_id):
        self.cancelled.append(prompt_id)


class FakeDB:
    def __init__(self, rows=()):
        self.rows = {row["prompt_id"]: dict(row) for row in rows}
        self.targets = []

    def get_generation(self, prompt_id):
        return self.rows.get(prompt_id)

    def list_generations(self):
        return [dict(row) for row in self.rows.values()]

    def set_enhance_target(self, prompt_id, target):
        self.targets.append((prompt_id, target))


class FakeBrowser:
    def __init__(self, selected=()):
        self.selected_ids = set(selected)
        self.enhancing = None
        self.corner_refreshes = 0

    def show_enhancing(self, by_prompt):
        self.enhancing = dict(by_prompt)

    def refresh_enhance_corners(self):
        self.corner_refreshes += 1


class FakeShows:
    def __init__(self):
        self.told = None

    def note_enhancing(self, statuses):
        self.told = dict(statuses)


class FakeConfigPanel:
    def __init__(self, row=None):
        self.row = row
        self.pending = "unset"
        self.settings = None

    def displayed_row(self):
        return self.row

    def set_pending_enhancement(self, pending):
        self.pending = pending

    def set_enhance_settings(self, settings):
        self.settings = settings


class FakeTabs:
    def __init__(self, panels=()):
        self.panels = list(panels)

    def config_panels(self):
        return self.panels


class FakeGroup:
    """A settings folder, as the controller reads one."""

    def __init__(self, rows):
        self.rows = list(rows)


class FakeHost:
    def __init__(self, *, picked=(), rows=(), group=None):
        self.picked = list(picked)
        self.rows = list(rows)
        self.group = group
        self.offers = 0

    def selected_prompt_ids(self):
        return self.picked

    def row_for(self, prompt_id):
        return next((r for r in self.rows if r["prompt_id"] == prompt_id), None)

    def image_rows(self):
        return self.rows

    def image_config_index(self):
        return {}

    def current_group(self):
        return self.group

    def typical_run_seconds(self, job):
        return 42.0

    def enhance_offer_changed(self):
        self.offers += 1


def _image(prompt_id="i1", *, files=("one.png",), enhance_of=None):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "sdxl_t2i",
        "status": "completed",
        "media_type": "image",
        "output_files": json.dumps([{"filename": name} for name in files]),
        "params_json": "{}",
        "enhance_of": enhance_of,
    }


def _video(prompt_id="v1"):
    return {
        "prompt_id": prompt_id,
        "workflow_name": "wan22_i2v",
        "status": "completed",
        "media_type": "video",
        "output_files": json.dumps([{"filename": f"{prompt_id}.mp4"}]),
        "params_json": "{}",
    }


@pytest.fixture
def enhance(monkeypatch):
    """A controller whose panel and surfaces are all recorders."""
    monkeypatch.setattr(module, "EnhancePanel", FakePanel)

    def build(host=None, *, db=None, reroll=None, browser=None, shows=None,
              tabs=None):
        host = host or FakeHost()
        return EnhanceController(
            host, db=db or FakeDB(), reroll=reroll or FakeReroll(),
            browser=browser or FakeBrowser(), shows=shows or FakeShows(),
            info_tabs_of=lambda: tabs or FakeTabs()), host
    return build


# --- what the button would run on -------------------------------------------


def test_a_pick_of_images_is_what_the_button_aims_at(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "level_matching_settings",
                        lambda row, settings: None)
    controller, _host = enhance(
        FakeHost(picked=["i1", "i2"]),
        db=FakeDB([_image("i1"), _image("i2")]), browser=FakeBrowser(["i1", "i2"]))

    offer = controller.offer()

    assert offer.available is True
    assert offer.tip.startswith("Enhance 2 items")


def test_a_picked_clip_is_nothing_to_run_rather_than_a_run_that_fails(enhance,
                                                                      monkeypatch):
    # There is no video enhancer, and a picked clip looks no different picked.
    monkeypatch.setattr(module.gallery, "is_enhanceable_row",
                        lambda row: row["media_type"] == "image")
    monkeypatch.setattr(module.gallery, "media_type_of_row",
                        lambda row: row["media_type"])
    controller, _host = enhance(
        FakeHost(picked=["v1"]), db=FakeDB([_video("v1")]), browser=FakeBrowser(["v1"]))

    offer = controller.offer()

    assert offer == (False, NO_VIDEO_ENHANCER)


def test_a_picture_already_made_at_these_settings_says_so_rather_than_no(enhance,
                                                                         monkeypatch):
    # Change any setting and the button comes back, which is what makes it read
    # as "you have this one" rather than as "no".
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "media_type_of_row", lambda row: "image")
    monkeypatch.setattr(module.gallery, "level_matching_settings",
                        lambda row, settings: {"file": "one-enhanced.png"})
    controller, _host = enhance(
        FakeHost(picked=["i1"]), db=FakeDB([_image("i1")]), browser=FakeBrowser(["i1"]))

    assert controller.offer() == (False, ALREADY_AT_THESE_SETTINGS)


def test_a_folder_that_is_not_a_settings_folder_offers_nothing(enhance):
    # The shelves and the workflow folders above a settings one have no single
    # recipe to enhance at.
    controller, _host = enhance(FakeHost(group=FakeGroup([_image("i1")])))

    assert controller.offer() == (False, "Nothing here to enhance")


def test_a_shelf_offers_nothing_to_enhance(enhance):
    controller, _host = enhance(FakeHost(group=None))

    assert controller.offer() == (False, "Nothing here to enhance")


# --- what a launch carries ---------------------------------------------------


def test_a_batch_lands_under_the_folder_its_settings_shape(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png", "seed": 1})
    monkeypatch.setattr(module.gallery, "settings_folder_key",
                        lambda row, index: "image/image_enhance/abc")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    db = FakeDB([_image("i1"), _image("i2")])
    reroll = FakeReroll()
    controller, _host = enhance(db=db, reroll=reroll)

    controller.enhance_items(["i1", "i2"])

    assert [key for key, _params in reroll.prepared] == [
        "image/image_enhance/abc", "image/image_enhance/abc"]
    assert db.targets == [("run-1", "i1"), ("run-1", "i2")]


def test_a_picture_with_no_file_to_enhance_is_skipped_not_launched(enhance,
                                                                   monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: None)
    reroll = FakeReroll()
    controller, _host = enhance(db=FakeDB([_image("i1")]), reroll=reroll)

    controller.enhance_items(["i1"])

    assert reroll.prepared == []


def test_a_launch_the_server_refused_is_logged_rather_than_dropped(enhance,
                                                                   monkeypatch,
                                                                   caplog):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "settings_folder_key", lambda row, index: "k")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    controller, _host = enhance(db=FakeDB([_image("i1")]),
                                reroll=FakeReroll(launches=None))

    with caplog.at_level("WARNING"):
        controller.enhance_items(["i1"])

    assert "could not launch" in caplog.text


def test_the_auto_tick_enhances_what_just_landed(enhance, monkeypatch):
    # With it on the app turns out finished images rather than raw ones, without
    # pressing Enhance All after every run.
    monkeypatch.setattr(module.gallery, "rows_awaiting_enhancement",
                        lambda rows, everything: list(rows))
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "settings_folder_key", lambda row, index: "k")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    reroll = FakeReroll()
    controller, _host = enhance(db=FakeDB([_image("i1")]), reroll=reroll)
    controller.restore_settings(json.dumps({"auto": True}))

    controller.enhance_when_wanted(_image("i1"))

    assert len(reroll.prepared) == 1


def test_with_the_auto_tick_off_a_landing_enhances_nothing(enhance):
    reroll = FakeReroll()
    controller, _host = enhance(reroll=reroll)

    controller.enhance_when_wanted(_image("i1"))

    assert reroll.prepared == []


# --- the settings ------------------------------------------------------------


def test_an_edit_reaches_every_tab_and_re_aims_the_button(enhance):
    # The panel holds the settings and the tabs hold the images, so the card can
    # only know whether it would be a duplicate once the two meet.
    tab = FakeConfigPanel()
    browser = FakeBrowser()
    controller, host = enhance(browser=browser, tabs=FakeTabs([tab]))

    settings = gallery.EnhanceSettings()
    controller.panel.on_changed(settings)

    assert tab.settings is settings
    assert host.offers == 1
    assert browser.corner_refreshes == 1


def test_the_settings_survive_a_restart(enhance):
    controller, _host = enhance()

    controller.restore_settings(json.dumps({"auto": True}))

    assert controller.settings.auto is True
    assert controller.settings_json() == controller.settings.to_json()


def test_the_panel_greys_out_where_nothing_it_says_could_run(enhance, monkeypatch):
    # A video is the one place with no enhancement to configure at all.
    monkeypatch.setattr(module.gallery, "media_type_of_row", lambda row: "video")
    rows = [_video("v1")]
    controller, _host = enhance(FakeHost(picked=["v1"], rows=rows),
                                browser=FakeBrowser(["v1"]))

    controller.sync_panel()

    assert controller.panel.applicable == (False, NO_VIDEO_ENHANCER)


def test_a_mixed_folder_keeps_its_settings_live(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "media_type_of_row",
                        lambda row: row["media_type"])
    rows = [_video("v1"), _image("i1")]
    controller, _host = enhance(FakeHost(picked=["v1", "i1"], rows=rows),
                                browser=FakeBrowser(["v1", "i1"]))

    controller.sync_panel()

    assert controller.panel.applicable == (True, NO_VIDEO_ENHANCER)


# --- a run in flight, and where it shows -------------------------------------


def test_every_live_job_is_searched_not_each_folders_leading_one(enhance,
                                                                 monkeypatch):
    # A batch of enhances goes out whole and its jobs share a settings key, so
    # all but the first would read as not-cooking off the folder-facing view.
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, input_image, row: target == row["prompt_id"])
    jobs = [FakeJob("run-a"), FakeJob("run-b")]
    db = FakeDB([_image("i1"), _image("i2")])
    db.rows["run-a"] = {"prompt_id": "run-a", "enhance_of": "i1"}
    db.rows["run-b"] = {"prompt_id": "run-b", "enhance_of": "i2"}
    controller, _host = enhance(db=db, reroll=FakeReroll(jobs))

    assert controller.run_of(_image("i2")) is not None


def test_a_queued_job_shows_as_queued_rather_than_borrowing_a_picture(enhance,
                                                                      monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    controller, _host = enhance(reroll=FakeReroll([FakeJob("run-a", state="queued")]))

    run = controller.run_of(_image("i1"))

    assert run.status == "queued" and run.frame is None
    assert run.typical_seconds == 42.0


def test_the_tile_the_version_list_and_the_show_all_learn_of_a_run(enhance,
                                                                   monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    monkeypatch.setattr(module.gallery, "describe_enhance_params",
                        lambda params: "upscale x2")
    row = _image("i1")
    tab = FakeConfigPanel(row)
    browser, shows = FakeBrowser(), FakeShows()
    controller, _host = enhance(
        FakeHost(rows=[row]), reroll=FakeReroll([FakeJob("run-a")]),
        browser=browser, shows=shows, tabs=FakeTabs([tab]))

    controller.reconcile()

    assert tab.pending == ("running", b"frame", "upscale x2")
    assert set(browser.enhancing) == {"i1"}
    assert shows.told == {"i1": "running"}


def test_a_run_over_is_nobody_s_enhance_any_more(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    db = FakeDB([_image("i1")])
    db.rows["run-a"] = {"prompt_id": "run-a", "enhance_of": "i1"}
    controller, _host = enhance(db=db, reroll=FakeReroll([FakeJob("run-a")]))
    controller.run_of(_image("i1"))  # reads and keeps the stamp

    controller.forget("run-a")

    assert "run-a" not in controller._targets


# --- stopping one ------------------------------------------------------------


def test_a_delete_takes_the_runs_being_made_of_what_it_deletes(enhance,
                                                               monkeypatch):
    # A video-length wait can sit after an enhance nobody wants any more.
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: row["prompt_id"] == "i1")
    reroll = FakeReroll([FakeJob("run-a")])
    controller, _host = enhance(reroll=reroll)

    controller.cancel_for_delete([_image("i1"), _image("i2")])

    assert reroll.cancelled == ["run-a"]


def test_cancelling_from_a_tile_leaves_the_picture_exactly_as_it_was(enhance,
                                                                     monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    browser = FakeBrowser()
    reroll = FakeReroll([FakeJob("run-a")])
    controller, _host = enhance(reroll=reroll, browser=browser)

    controller.cancel_for([_image("i1")])

    assert reroll.cancelled == ["run-a"]
    assert browser.enhancing == {}  # the scrim comes off in the same breath


def test_cancelling_with_nothing_cooking_redraws_nothing(enhance):
    browser = FakeBrowser()
    controller, _host = enhance(browser=browser)

    controller.cancel_for([_image("i1")])

    assert browser.enhancing is None


# --- said out loud -----------------------------------------------------------


def test_a_spoken_enhance_refuses_a_picture_that_already_has_one(enhance,
                                                                 monkeypatch):
    # Re-enhancing stays a deliberate act made in front of the settings it uses.
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "is_enhanced_row", lambda row: True)
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    assert controller.enhance_it("i1") == (None, "🎤 this one is enhanced already")


def test_a_spoken_enhance_over_a_clip_says_there_is_nothing_to_enhance(enhance,
                                                                       monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: False)
    controller, _host = enhance(db=FakeDB([_video("v1")]))

    assert controller.enhance_it("v1") == (
        None, "🎤 only a finished image can be enhanced")


def test_a_spoken_fix_names_the_parts_it_is_actually_redrawing(enhance,
                                                               monkeypatch):
    # One part with nothing installed to find it is dropped rather than taking
    # the rest of the command down with it.
    class Part:
        def __init__(self, name):
            self.name = name

    hands, teeth = Part("hands"), Part("teeth")
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "fix_params_for",
                        lambda row, parts, settings: {
                            "input_image": "one.png",
                            "enhance_detail_fixes": {"hands": 1}})
    monkeypatch.setattr(module.gallery, "level_matching_params",
                        lambda row, params: None)
    monkeypatch.setattr(module.gallery, "settings_folder_key", lambda row, index: "k")
    monkeypatch.setattr(module.gallery, "describe_enhance_params", lambda p: "fix")
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: False)
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    monkeypatch.setattr(module, "name_parts",
                        lambda parts: ", ".join(p.name for p in parts))
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    prompt_id, message = controller.fix_parts("i1", [hands, teeth])

    assert prompt_id == "i1"
    assert message == "🎤 fixing hands…"


def test_a_fix_with_no_detector_installed_says_which_one(enhance, monkeypatch):
    class Part:
        name = "teeth"

    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "fix_params_for",
                        lambda row, parts, settings: None)
    monkeypatch.setattr(module, "name_parts", lambda parts: "teeth")
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    _prompt_id, message = controller.fix_parts("i1", [Part()])

    assert message == ("🎤 no teeth detector installed "
                       "(ComfyUI models/ultralytics/bbox)")


def test_a_spoken_enhance_over_a_picture_already_cooking_one_is_refused(enhance,
                                                                        monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "is_enhanced_row", lambda row: False)
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    controller, _host = enhance(db=FakeDB([_image("i1")]),
                                reroll=FakeReroll([FakeJob("run-a")]))

    assert controller.enhance_it("i1") == (
        None, "🎤 an enhance of this image is already running")


def test_a_held_slide_asking_for_one_gets_a_yes_or_no(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: False)
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    assert controller.enhance_from_slideshow("i1") is False
