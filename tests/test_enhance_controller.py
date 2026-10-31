"""The standalone enhance, driven with no gallery around it.

What the button would run on and why an image is passed over, what a batch
shares, and where a run in flight shows -- all of it used to be reachable only
by building the app's central widget. Here the surfaces are recorders.

Fixture values are fabricated throughout (see CLAUDE.md).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from origenerator import config, gallery
from origenerator.enhance_presets import Preset
from origenerator.gui import enhance_controller as module
from origenerator.gui.enhance_controller import (
    ALREADY_AT_THESE_SETTINGS,
    NO_VIDEO_ENHANCER,
    EnhanceController,
    Offer,
)
from origenerator.gui.notice_overlay import ERROR, NOTICE, WARNING
from origenerator.workflows import detail_parts
from origenerator.workflows.detail_parts import DetailPart

ENHANCE = gallery.ENHANCE_WORKFLOW


class FakeSignal:
    def __init__(self):
        self._slots = []

    def connect(self, slot):
        self._slots.append(slot)

    def emit(self, *args):
        for slot in self._slots:
            slot(*args)


class FakePanel:
    """The Enhance subpanel reduced to what the controller drives."""

    def __init__(self, on_changed):
        self.on_changed = on_changed
        self.enhance_requested = FakeSignal()
        self.fix_training_requested = FakeSignal()
        self.preset_saved = FakeSignal()
        self.preset_renamed = FakeSignal()
        self.presets = None
        self.training: dict = {}
        self.used: list = []
        self.shown = None
        self.applicable = None
        self.offer = None

    def show_settings(self, settings):
        self.shown = settings

    def show_presets(self, presets):
        self.presets = list(presets)

    def set_applicable(self, applicable, why):
        self.applicable = (applicable, why)

    def show_offer(self, available, tip):
        self.offer = (available, tip)

    def show_fix_training(self, name, text):
        self.training[name] = text

    def use_fix_lora(self, name, lora):
        self.used.append((name, lora))

    def open_fix_prompts(self, name):
        self.opened = name


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
        self.asks = []
        self.cancelled = []
        self.launches = launches
        self.first = set()

    def put_first(self, prompt_ids):
        self.first = set(prompt_ids)

    def start_prepared(self, key, workflow, params):
        (launched,) = self.start_batch(key, workflow, [params])
        return launched

    def start_batch(self, key, workflow, batch, *, source="generated"):
        self.asks.append((key, len(batch)))
        self.prepared.extend((key, dict(params)) for params in batch)
        if self.launches:
            self.all_jobs.extend(
                FakeJob(self.launches, input_image=params.get("input_image"), state="queued")
                for params in batch)
        return [self.launches for _params in batch]

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

    def rows_made_by(self, workflow_name):
        return [dict(row) for row in self.rows.values() if row["workflow_name"] == workflow_name]

    def set_enhance_target(self, prompt_id, target):
        self.targets.append((prompt_id, target))


class FakeBrowser:
    def __init__(self, selected=()):
        self.selected_ids = set(selected)
        self.enhancing = None
        self.corner_refreshes = 0

    def show_enhancing(self, by_prompt):
        self.enhancing = dict(by_prompt)

    def refresh_corners(self):
        self.corner_refreshes += 1


class FakeSlideshows:
    def __init__(self, locked=()):
        self.told = None
        self.frames = None
        self.locked = set(locked)

    def locked_prompt_ids(self):
        return self.locked

    def note_enhancing(self, statuses, frames=None):
        self.told = dict(statuses)
        self.frames = dict(frames or {})


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

    def build(host=None, *, db=None, jobs=None, browser=None, slideshows=None,
              tabs=None):
        host = host or FakeHost()
        return EnhanceController(
            host, db=db or FakeDB(), jobs=jobs or FakeReroll(),
            browser=browser or FakeBrowser(), slideshows=slideshows or FakeSlideshows(),
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
    assert offer.tip == "Enhance 2 items (upscale + light redraw)"


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


def test_an_image_already_made_at_these_settings_says_so_rather_than_no(enhance,
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
    # The collections and the workflow folders above a settings one have no single
    # set of settings to enhance at.
    controller, _host = enhance(FakeHost(group=FakeGroup([_image("i1")])))

    assert controller.offer() == (False, "Nothing here to enhance")


def test_a_collection_offers_nothing_to_enhance(enhance):
    controller, _host = enhance(FakeHost(group=None))

    assert controller.offer() == (False, "Nothing here to enhance")


def test_a_whole_folder_offer_says_what_the_enhance_does_in_plain_words(enhance,
                                                                       monkeypatch):
    monkeypatch.setattr(module.gallery, "rows_awaiting_enhancement",
                        lambda rows, everything: list(rows))
    folder = gallery.SettingsGroup("k", "S", [_image("i1"), _image("i2")])
    controller, _host = enhance(FakeHost(group=folder))

    assert controller.offer() == (
        True, "Enhance 2 not-yet-enhanced images in this folder (upscale + light redraw)")


def test_a_folders_offer_reads_what_the_enhance_runs_made_never_the_whole_library(enhance):
    class CountsTheWholeLibrary(FakeDB):
        reads = 0

        def list_generations(self):
            self.reads += 1
            return super().list_generations()

    in_flight = {**_image("e1"), "workflow_name": ENHANCE, "enhance_of": "i2"}
    folder = gallery.SettingsGroup("k", "S", [_image("i1"), _image("i2")])
    db = CountsTheWholeLibrary([_image("i1"), _image("i2"), in_flight])
    controller, _host = enhance(FakeHost(group=folder), db=db)
    read_while_building = db.reads

    offer = controller.offer()

    assert (offer, db.reads) == (
        (True, "Enhance 1 not-yet-enhanced image in this folder (upscale + light redraw)"),
        read_while_building)


# --- what a launch carries ---------------------------------------------------


def test_a_batch_lands_under_the_folder_its_settings_shape(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png", "seed": 1})
    monkeypatch.setattr(module.gallery, "settings_folder_key",
                        lambda row, index: "image/image_enhance/abc")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    db = FakeDB([_image("i1"), _image("i2")])
    jobs = FakeReroll()
    controller, _host = enhance(db=db, jobs=jobs)

    controller.enhance_items(["i1", "i2"])

    assert [key for key, _params in jobs.prepared] == [
        "image/image_enhance/abc", "image/image_enhance/abc"]
    assert db.targets == [("run-1", "i1"), ("run-1", "i2")]


def test_a_batch_is_asked_for_once_per_folder_it_lands_in(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": f"{row['prompt_id']}.png"})
    monkeypatch.setattr(module.gallery, "settings_folder_key",
                        lambda row, index: "here" if "i3" not in row["params_json"] else "there")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    jobs = FakeReroll()
    controller, _host = enhance(db=FakeDB([_image("i1"), _image("i2"), _image("i3")]),
                                jobs=jobs)

    controller.enhance_items(["i1", "i2", "i3"])

    assert jobs.asks == [("here", 2), ("there", 1)]


def test_an_image_with_no_file_to_enhance_is_skipped_not_launched(enhance,
                                                                  monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: None)
    jobs = FakeReroll()
    controller, _host = enhance(db=FakeDB([_image("i1")]), jobs=jobs)

    controller.enhance_items(["i1"])

    assert jobs.prepared == []


def test_a_launch_the_server_refused_is_logged_rather_than_dropped(enhance,
                                                                   monkeypatch,
                                                                   caplog):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "settings_folder_key", lambda row, index: "k")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    controller, _host = enhance(db=FakeDB([_image("i1")]),
                                jobs=FakeReroll(launches=None))

    with caplog.at_level("WARNING"):
        controller.enhance_items(["i1"])

    assert "could not launch" in caplog.text


def test_an_image_already_holding_an_enhancement_at_these_settings_is_not_enhanced_again(
        enhance, monkeypatch):
    params = {"input_image": "one.png"}
    monkeypatch.setattr(module.gallery, "enhance_params_for", lambda row, settings: params)
    asked = []
    monkeypatch.setattr(module.gallery, "level_matching_params",
                        lambda row, wanted: asked.append((row["prompt_id"], wanted)) or 0)
    jobs = FakeReroll()
    controller, _host = enhance(db=FakeDB([_image("i1")]), jobs=jobs)

    controller.enhance_items(["i1"])

    assert jobs.prepared == []
    assert asked == [("i1", params)]


def test_an_image_with_an_enhancement_at_these_settings_on_its_way_is_not_enhanced_again(
        enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    jobs = FakeReroll(jobs=[FakeJob("run-0", input_image="one.png", state="queued")])
    controller, _host = enhance(db=FakeDB([_image("i1")]), jobs=jobs)

    controller.enhance_items(["i1"])

    assert jobs.prepared == []


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
    jobs = FakeReroll()
    controller, _host = enhance(db=FakeDB([_image("i1")]), jobs=jobs)
    controller.restore_settings(json.dumps({"auto": True}))

    controller.enhance_when_wanted(_image("i1"))

    assert len(jobs.prepared) == 1


def test_pressing_the_panels_enhance_enhances_what_the_bank_button_would(enhance,
                                                                         monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "level_matching_settings",
                        lambda row, settings: None)
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "settings_folder_key", lambda row, index: "k")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    jobs = FakeReroll()
    controller, _host = enhance(FakeHost(picked=["i1"]), db=FakeDB([_image("i1")]),
                                browser=FakeBrowser(["i1"]), jobs=jobs)

    controller.panel.enhance_requested.emit()

    assert [params for _key, params in jobs.prepared] == [{"input_image": "one.png"}]


def test_with_the_auto_tick_off_a_landing_enhances_nothing(enhance):
    jobs = FakeReroll()
    controller, _host = enhance(jobs=jobs)

    controller.enhance_when_wanted(_image("i1"))

    assert jobs.prepared == []


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


def test_the_panel_lists_the_presets_a_library_starts_with(enhance):
    enhanced = dict(_image("i1"), params_json=json.dumps({"enhance": True, "enhance_steps": 30}))

    controller, _host = enhance(db=FakeDB([enhanced]))

    assert [preset.name for preset in controller.panel.presets] == ["2x · 30 steps · 0.15 redraw"]


def _edited(enhance_steps):
    return gallery.EnhanceSettings(params={**gallery.default_enhance_params(),
                                           "enhance_steps": enhance_steps})


def test_a_preset_named_on_the_panel_holds_the_settings_on_it_and_is_listed_last(enhance):
    controller, _host = enhance()
    controller.panel.on_changed(_edited(44))

    controller.panel.preset_saved.emit("Crisp")

    assert controller.panel.presets == [Preset("Crisp", _edited(44).params)]


def test_a_preset_renamed_on_the_panel_keeps_its_settings_under_the_new_name(enhance):
    controller, _host = enhance()
    controller.panel.on_changed(_edited(44))
    controller.panel.preset_saved.emit("Crisp")

    controller.panel.preset_renamed.emit(0, "Bright")

    assert controller.panel.presets == [Preset("Bright", _edited(44).params)]


def test_the_panel_greys_out_where_nothing_it_says_could_run(enhance, monkeypatch):
    # A video is the one place with no enhancement to configure at all.
    monkeypatch.setattr(module.gallery, "media_type_of_row", lambda row: "video")
    rows = [_video("v1")]
    controller, _host = enhance(FakeHost(picked=["v1"], rows=rows),
                                browser=FakeBrowser(["v1"]))

    controller.sync_panel(Offer(False, NO_VIDEO_ENHANCER))

    assert controller.panel.applicable == (False, NO_VIDEO_ENHANCER)


def test_a_mixed_folder_keeps_its_settings_live(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "media_type_of_row",
                        lambda row: row["media_type"])
    rows = [_video("v1"), _image("i1")]
    controller, _host = enhance(FakeHost(picked=["v1", "i1"], rows=rows),
                                browser=FakeBrowser(["v1", "i1"]))

    controller.sync_panel(Offer(True, "Enhance 1 item"))

    assert controller.panel.applicable == (True, NO_VIDEO_ENHANCER)


def test_the_panels_enhance_button_is_aimed_with_the_offer_the_bank_button_is(enhance):
    controller, _host = enhance()

    controller.sync_panel(Offer(False, "Nothing here to enhance"))

    assert controller.panel.offer == (False, "Nothing here to enhance")


# --- a run in flight, and where it shows -------------------------------------


def test_every_live_job_is_searched_not_each_folders_leading_one(enhance,
                                                                 monkeypatch):
    # A batch of enhances goes out whole and its jobs share a settings key, so
    # all but the first would read as not in flight off the folder-facing view.
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, input_image, row: target == row["prompt_id"])
    jobs = [FakeJob("run-a"), FakeJob("run-b")]
    db = FakeDB([_image("i1"), _image("i2")])
    db.rows["run-a"] = {"prompt_id": "run-a", "enhance_of": "i1"}
    db.rows["run-b"] = {"prompt_id": "run-b", "enhance_of": "i2"}
    controller, _host = enhance(db=db, jobs=FakeReroll(jobs))

    assert controller.run_of(_image("i2")) is not None


def test_a_queued_job_shows_as_queued_rather_than_borrowing_a_frame(enhance,
                                                                    monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    controller, _host = enhance(jobs=FakeReroll([FakeJob("run-a", state="queued")]))

    run = controller.run_of(_image("i1"))

    assert run.status == "queued"
    assert run.frame is None
    assert run.typical_seconds == 42.0


def test_the_tile_the_version_list_and_the_slideshow_all_learn_of_a_run(enhance,
                                                                        monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    monkeypatch.setattr(module.gallery, "describe_enhance_params",
                        lambda params: "upscale x2")
    row = _image("i1")
    tab = FakeConfigPanel(row)
    browser, slideshows = FakeBrowser(), FakeSlideshows()
    controller, _host = enhance(
        FakeHost(rows=[row]), jobs=FakeReroll([FakeJob("run-a")]),
        browser=browser, slideshows=slideshows, tabs=FakeTabs([tab]))

    controller.reconcile()

    assert tab.pending == ("running", b"frame", "upscale x2")
    assert set(browser.enhancing) == {"i1"}
    assert slideshows.told == {"i1": "running"}
    assert slideshows.frames == {"i1": b"frame"}


def test_a_run_over_is_nobody_s_enhance_any_more(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    db = FakeDB([_image("i1")])
    db.rows["run-a"] = {"prompt_id": "run-a", "enhance_of": "i1"}
    controller, _host = enhance(db=db, jobs=FakeReroll([FakeJob("run-a")]))
    controller.run_of(_image("i1"))  # reads and keeps the stamp

    controller.forget("run-a")

    assert "run-a" not in controller._targets


# --- stopping one ------------------------------------------------------------


def test_a_delete_takes_the_runs_being_made_of_what_it_deletes(enhance,
                                                               monkeypatch):
    # A video-length wait can sit after an enhance nobody wants any more.
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: row["prompt_id"] == "i1")
    jobs = FakeReroll([FakeJob("run-a")])
    controller, _host = enhance(jobs=jobs)

    controller.cancel_for_delete([_image("i1"), _image("i2")])

    assert jobs.cancelled == ["run-a"]


def test_cancelling_from_a_tile_leaves_the_image_exactly_as_it_was(enhance,
                                                                   monkeypatch):
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    browser = FakeBrowser()
    jobs = FakeReroll([FakeJob("run-a")])
    controller, _host = enhance(jobs=jobs, browser=browser)

    controller.cancel_for([_image("i1")])

    assert jobs.cancelled == ["run-a"]
    assert browser.enhancing == {}  # the scrim comes off in the same breath


def test_cancelling_with_nothing_in_flight_redraws_nothing(enhance):
    browser = FakeBrowser()
    controller, _host = enhance(browser=browser)

    controller.cancel_for([_image("i1")])

    assert browser.enhancing is None


# --- said out loud -----------------------------------------------------------


def test_a_spoken_enhance_refuses_an_image_that_already_has_one(enhance,
                                                                monkeypatch):
    # Re-enhancing stays a deliberate act made in front of the settings it uses.
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "is_enhanced_row", lambda row: True)
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    assert controller.enhance_it("i1") == (None, "this one is enhanced already", WARNING)


def test_a_spoken_enhance_over_a_clip_says_there_is_nothing_to_enhance(enhance,
                                                                       monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: False)
    controller, _host = enhance(db=FakeDB([_video("v1")]))

    assert controller.enhance_it("v1") == (
        None, "only a finished image can be enhanced", WARNING)


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

    prompt_id, message, kind = controller.fix_parts("i1", [hands, teeth])

    assert prompt_id == "i1"
    assert message == "fixing hands…"
    assert kind == NOTICE


def test_a_fix_already_as_hard_as_it_goes_says_so(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "fix_params_for",
                        lambda row, parts, settings: {"enhance_detail_fixes": {"hands": 1.0}})
    monkeypatch.setattr(module.gallery, "level_matching_params", lambda row, params: 0)
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    assert controller.fix_parts("i1", [DetailPart("hands", ("hands",), ("hands",))]) == (
        None, "hands already fixed as hard as a fix goes", WARNING)


@pytest.mark.parametrize("part, folder", [
    (DetailPart("teeth", ("teeth",), ("teeth",)), "bbox"),
    (DetailPart("skin", ("skin",), ("skin",), outline=True), "segm"),
])
def test_a_fix_with_no_detector_installed_says_which_one(enhance, monkeypatch, part, folder):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "fix_params_for",
                        lambda row, parts, settings: None)
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    _prompt_id, message, kind = controller.fix_parts("i1", [part])

    assert message == (f"no {part.name} detector installed "
                       f"(ComfyUI models/ultralytics/{folder})")
    assert kind == WARNING


def test_a_spoken_enhance_over_an_image_that_has_one_in_flight_is_refused(enhance,
                                                                        monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "is_enhanced_row", lambda row: False)
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "enhance_run_targets_row",
                        lambda target, image, row: True)
    controller, _host = enhance(db=FakeDB([_image("i1")]),
                                jobs=FakeReroll([FakeJob("run-a")]))

    assert controller.enhance_it("i1") == (
        None, "an enhance of this image is already running", WARNING)


def test_a_spoken_enhance_that_cannot_launch_says_so_as_an_error(enhance, monkeypatch):
    # Nothing was refused: the run was wanted and its submit failed, so it reads
    # red rather than the yellow of an image with nothing to do.
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "is_enhanced_row", lambda row: False)
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "describe_enhance_params", lambda p: "enhance")
    controller, _host = enhance(db=FakeDB([_image("i1")]))
    monkeypatch.setattr(controller, "_launch", lambda row, params: False)

    assert controller.enhance_it("i1") == (
        None, "couldn't launch the enhance — see the log", ERROR)


def test_a_locked_slide_asking_for_one_gets_a_yes_or_no(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: False)
    controller, _host = enhance(db=FakeDB([_image("i1")]))

    assert controller.enhance_from_slideshow("i1") is False


def test_a_lock_puts_the_enhancement_of_the_locked_image_first(enhance, monkeypatch):
    monkeypatch.setattr(module.gallery, "is_enhanceable_row", lambda row: True)
    monkeypatch.setattr(module.gallery, "is_enhanced_row", lambda row: False)
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    db = FakeDB([_image("i1"), _image("i2")])
    db.rows["run-a"] = {"prompt_id": "run-a", "enhance_of": "i1"}
    db.rows["run-b"] = {"prompt_id": "run-b", "enhance_of": "i2"}
    jobs = FakeReroll([FakeJob("run-b", state="queued"), FakeJob("run-a", state="queued")])
    controller, _host = enhance(FakeHost(rows=[_image("i1"), _image("i2")]), db=db,
                                jobs=jobs, slideshows=FakeSlideshows(locked={"i1"}))

    assert controller.enhance_from_slideshow("i1") is False
    assert jobs.first == {"run-a"}


def test_an_enhancement_launched_for_what_a_slideshow_is_locked_on_is_put_first(enhance,
                                                                                monkeypatch):
    # The Auto switch enhancing an image a slideshow stayed locked on while it was
    # made, or a batch that takes in the locked one.
    monkeypatch.setattr(module.gallery, "enhance_params_for",
                        lambda row, settings: {"input_image": "one.png"})
    monkeypatch.setattr(module.gallery, "settings_folder_key", lambda row, index: "k")
    monkeypatch.setitem(module.WORKFLOW_REGISTRY, ENHANCE, FakeWorkflow())
    monkeypatch.setattr(module, "randomize_seeds", lambda params, keys: params)
    jobs = FakeReroll()
    controller, _host = enhance(FakeHost(rows=[_image("i1")]), db=FakeDB([_image("i1")]),
                                jobs=jobs, slideshows=FakeSlideshows(locked={"i1"}))

    controller.enhance_items(["i1"])

    assert jobs.first == {"run-1"}


# --- training a fix's LoRA -----------------------------------------------------


_training_runs: list = []


class FakeTrainingRun:
    def __init__(self, job, queue, kind, *, reveal, parent=None):
        self.job, self.queue, self.kind, self.reveal = job, queue, kind, reveal
        self.progress, self.finished, self.failed = FakeSignal(), FakeSignal(), FakeSignal()
        self.canceled = FakeSignal()
        self.began = False
        self.adopted = None
        _training_runs.append(self)

    def begin(self):
        self.began = True

    def adopt(self, trainer):
        self.adopted = trainer


@pytest.fixture
def photos(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FIX_PHOTOS_DIR", tmp_path)
    monkeypatch.setattr(config, "FIX_TRAINING_DIR", tmp_path / "fix training")
    monkeypatch.setattr(config, "LORA_TRAINING_PYTHON", tmp_path / "python.exe")
    monkeypatch.setattr(config, "LORA_TRAINING_SCRIPTS", tmp_path / "sd-scripts")
    monkeypatch.setattr(detail_parts, "list_detector_files", lambda: ["hand_yolov8s.pt"])
    monkeypatch.setattr(module, "TrainingRun", FakeTrainingRun)
    _training_runs.clear()
    return tmp_path


def test_train_with_no_photos_makes_the_fixs_folder_and_says_to_put_them_there(
        enhance, photos, monkeypatch):
    told = []
    monkeypatch.setattr(module.QMessageBox, "information",
                        lambda parent, title, text: told.append(text))
    controller, _host = enhance()

    controller.panel.fix_training_requested.emit("hands")

    assert (photos / "hands").is_dir()
    assert str(photos / "hands") in told[0]
    assert _training_runs == []


def test_train_with_photos_in_the_shared_folder_alone_trains_that_fix(enhance, photos):
    (photos / "shared").mkdir()
    (photos / "shared" / "everyone.jpg").write_bytes(b"")
    controller, _host = enhance()

    controller.panel.fix_training_requested.emit("hands")

    (run,) = _training_runs
    assert run.job["photos"] == [str(photos / "shared" / "everyone.jpg")]


def test_train_with_photos_trains_that_fix_for_the_enhancements_model(enhance, photos):
    (photos / "hands").mkdir()
    (photos / "hands" / "one.jpg").write_bytes(b"")
    controller, _host = enhance()
    controller.restore_settings(json.dumps({"params": {"checkpoint": "sample_xl.safetensors"}}))

    controller.panel.fix_training_requested.emit("hands")

    (run,) = _training_runs
    assert run.began
    assert run.job["part"] == "hands"
    assert run.job["base_model"].endswith("sample_xl.safetensors")


def test_a_finished_training_puts_its_lora_on_that_fix(enhance, photos):
    (photos / "hands").mkdir()
    (photos / "hands" / "one.jpg").write_bytes(b"")
    controller, _host = enhance()
    controller.panel.fix_training_requested.emit("hands")
    (run,) = _training_runs

    run.progress.emit("Training 40%")
    assert controller.panel.training["hands"] == "Training 40%"
    Path(run.job["work"]).mkdir(parents=True)
    Path(run.job["status"]).write_text(json.dumps(
        {"state": "done", "lora": "fixes\\hands 2026-10-19 0130.safetensors"}), encoding="utf-8")
    run.finished.emit("fixes\\hands 2026-10-19 0130.safetensors")

    assert controller.panel.used == [("hands", "fixes\\hands 2026-10-19 0130.safetensors")]
    assert controller.panel.training["hands"] is None
    assert module.lora_training.untaken_lora(run.job) is None


def test_a_canceled_training_puts_train_back_says_nothing_and_lets_another_start(
        enhance, photos, monkeypatch):
    told = []
    monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: told.append(args))
    (photos / "hands").mkdir()
    (photos / "hands" / "one.jpg").write_bytes(b"")
    controller, _host = enhance()
    controller.panel.fix_training_requested.emit("hands")
    (run,) = _training_runs

    run.canceled.emit()
    controller.panel.fix_training_requested.emit("hands")

    assert controller.panel.training["hands"] is None
    assert told == []
    assert len(_training_runs) == 2


def test_going_to_a_training_from_the_queue_opens_its_fixs_prompts(enhance, photos):
    (photos / "hands").mkdir()
    (photos / "hands" / "one.jpg").write_bytes(b"")
    controller, _host = enhance()
    controller.panel.fix_training_requested.emit("hands")
    (run,) = _training_runs

    run.reveal()

    assert controller.panel.opened == "hands"


class _KeptTrainer:
    def __init__(self, alive):
        self.alive = alive
        self.began = 0.0

    def running(self):
        return self.alive

    def stop(self):
        self.alive = False


def _kept_training(photos, part="hands", automatic=False, **status) -> dict:
    work = photos / "fix training" / part
    work.mkdir(parents=True)
    job = {"part": part, "display_name": f"{part.capitalize()} fix 1.0", "work": str(work),
           "status": str(work / "status.json"), "job_file": str(work / "job.json"),
           "process": str(work / "process.json"), "automatic": automatic}
    Path(job["job_file"]).write_text(json.dumps(job), encoding="utf-8")
    if status:
        Path(job["status"]).write_text(json.dumps(status), encoding="utf-8")
    return job


def test_a_training_an_earlier_launch_left_running_is_taken_up_and_holds_the_line(
        enhance, photos, monkeypatch):
    _kept_training(photos)
    trainer = _KeptTrainer(alive=True)
    monkeypatch.setattr(module.lora_training, "trainer_of", lambda job: trainer)
    controller, _host = enhance()

    controller.take_up_trainings()

    (run,) = _training_runs
    assert run.adopted is trainer
    assert run.job["part"] == "hands"


def test_a_training_evolver_started_while_the_app_was_closed_stops_as_it_opens(
        enhance, photos, monkeypatch):
    _kept_training(photos, automatic=True)
    trainer = _KeptTrainer(alive=True)
    monkeypatch.setattr(module.lora_training, "trainer_of", lambda job: trainer)
    controller, _host = enhance()

    controller.take_up_trainings()

    assert not trainer.running()
    assert _training_runs == []


def test_a_lora_a_training_made_while_the_app_was_closed_goes_on_its_fix_once(
        enhance, photos, monkeypatch):
    _kept_training(photos, state="done", lora="fixes\\hands 2026-10-21 1500.safetensors")
    monkeypatch.setattr(module.lora_training, "trainer_of", lambda job: _KeptTrainer(alive=False))
    controller, _host = enhance()

    controller.take_up_trainings()
    controller.take_up_trainings()

    assert controller.panel.used == [("hands", "fixes\\hands 2026-10-21 1500.safetensors")]
    assert _training_runs == []


def test_a_training_that_ended_while_the_app_was_closed_still_counts_toward_the_next_countdown(
        enhance, photos, monkeypatch):
    job = _kept_training(photos, state="done", lora="fixes\\hands 2026-10-21 1500.safetensors")
    ended = Path(job["status"]).stat().st_mtime
    monkeypatch.setattr(module.lora_training, "trainer_of",
                        lambda kept: SimpleNamespace(running=lambda: False, began=ended - 2580.0))
    controller, _host = enhance()

    controller.take_up_trainings()

    assert module.fix_training.typical_seconds() == pytest.approx(2580.0)


def test_a_lora_from_a_training_before_its_program_was_recorded_is_left_where_it_was_put(
        enhance, photos, monkeypatch):
    _kept_training(photos, state="done", lora="fixes\\hands 2026-10-19 1444.safetensors")
    monkeypatch.setattr(module.lora_training, "trainer_of", lambda job: None)
    controller, _host = enhance()

    controller.take_up_trainings()

    assert controller.panel.used == []
