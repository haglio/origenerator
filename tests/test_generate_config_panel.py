import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from origenerator import evolver_export, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import EVOLVER_INBOX_DIR, EVOLVER_SOURCE
from origenerator.db import Database
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui.animated_strip import _VideoTile
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.workflows import WORKFLOW_REGISTRY


@pytest.fixture
def panel(qtbot, tmp_path):
    db = Database(tmp_path / "test.db")
    p = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(p)
    return p


def _combo_index(panel, key):
    for i in range(panel._workflow_combo.count()):
        if panel._workflow_combo.itemData(i) == key:
            return i
    raise AssertionError(f"workflow {key} not in combo")


def _is_descendant(widget, ancestor) -> bool:
    node = widget.parent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent()
    return False


# --- layout: preview-over-form beside a slim history strip -----------------

def test_panel_lays_out_two_resizable_panes(panel):
    from PyQt6.QtWidgets import QSplitter
    assert isinstance(panel._panes, QSplitter)
    assert panel._panes.count() == 2


def test_thumbnail_history_is_the_right_pane(panel):
    from origenerator.gui.thumbnail_strip import ThumbnailStrip
    right = panel._panes.widget(1)
    assert right is panel._strip
    assert isinstance(right, ThumbnailStrip)


def test_preview_over_form_share_the_main_pane(panel):
    # Preview-over-form: the preview sits on top of the settings in the left "main"
    # pane, with the status bar and the Generate button under it — beside the slim
    # history strip. The preview is no longer its own splitter pane.
    main = panel._panes.widget(0)
    assert _is_descendant(panel._preview, main)
    assert _is_descendant(panel._generate_btn, main)
    assert panel._preview is not main  # nested inside the pane, not the pane itself


def _layout_containing(root, widget):
    """DFS a layout tree for the layout directly holding ``widget``."""
    for i in range(root.count()):
        item = root.itemAt(i)
        if item.widget() is widget:
            return root
        sub = item.layout()
        if sub is not None and (found := _layout_containing(sub, widget)) is not None:
            return found
    return None


def test_info_and_form_share_one_scroll(panel):
    # The read-only info and the editable form live in one scroll, so they move
    # together — not the form boxed in its own cramped scroll while the info sits in
    # a separate static footer.
    for widget in (panel._metadata_block, panel._source_tile,
                   panel._animated_strip, panel._param_form):
        assert _is_descendant(widget, panel._scroll)


def test_file_info_above_form_related_media_below(panel):
    # File/Created sits above the form; the source-image tile and animated-in strip
    # sit below it, at the bottom of the scroll just above the buttons.
    body = panel._scroll.widget().layout()
    form_at = body.indexOf(panel._form_host)
    assert body.indexOf(panel._metadata_block) < form_at
    assert body.indexOf(panel._source_tile) > form_at
    assert body.indexOf(panel._animated_strip) > form_at


def test_evolver_shares_the_button_bank_with_generate_and_cancel(panel):
    # One button bank: Send-to-Evolver isn't a stray footer button — it sits in the
    # same row as Cancel and Generate.
    main = panel._panes.widget(0)
    bank = _layout_containing(main.layout(), panel._generate_btn)
    assert bank is not None
    assert bank.indexOf(panel._folder_btn) != -1
    assert bank.indexOf(panel._evolver_btn) != -1
    assert bank.indexOf(panel._cancel_btn) != -1


def test_switching_workflow_detaches_the_old_form_at_once(panel):
    # Changing workflow must remove the previous form from the host immediately, not
    # leave it parented (and painting) under the new form until deleteLater runs.
    from origenerator.gui.param_form import ParamForm
    old_form = panel._param_form
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))

    assert panel._param_form is not old_form   # a new form is installed
    assert old_form.parent() is None           # the old one is detached at once
    live = [f for f in panel._form_host.findChildren(ParamForm)
            if f.parent() is panel._form_host]
    assert live == [panel._param_form]         # exactly one form in the host


def test_switching_workflow_carries_over_the_users_edits(panel):
    # Changing workflow must not wipe what the user already set up: any value
    # they EDITED away from the departing workflow's defaults carries into the
    # new form wherever the new workflow shares the param. Values still at the
    # old defaults don't leak — flf2v's 4-step lightning default must not
    # follow the user into a workflow tuned for 20.
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_flf2v_loop"))
    panel._param_form.set_values({
        "positive_prompt": "slow beta",
        "input_image": "start.png",
        "audio_prompt": "wet stroking",
        "steps": 7,  # an edit — flf2v's default is 4
    })

    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan21_ati_i2v"))

    values = panel._param_form.get_values_static()
    assert values["positive_prompt"] == "slow beta"
    assert values["input_image"] == "start.png"
    assert values["audio_prompt"] == "wet stroking"
    assert values["steps"] == 7
    ati_defaults = WORKFLOW_REGISTRY["wan21_ati_i2v"].default_params()
    assert values["cfg"] == ati_defaults["cfg"]        # flf2v's 1.0 didn't leak
    assert values["stroke_hz"] == ati_defaults["stroke_hz"]


def test_i2v_workflow_form_gets_the_derived_size_deriver(panel):
    # Selecting an i2v workflow hands its form the size deriver, so the Dimensions
    # section shows the input-image size in a locked, unlockable field.
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    form = panel._param_form
    assert form._size_deriver is not None
    assert "width" in form._present_keys["Dimensions"]
    assert form._dim_stacks["width"].currentIndex() == 0   # locked: a plain value, not a box
    assert form._unlock_btn is not None


def test_i2v_form_shows_the_measured_size_of_a_real_input_image(panel, tmp_path, monkeypatch):
    # End to end: the panel hands the real derived_display_size to the form, which
    # measures the picked image and shows its scaled size in the locked field.
    import origenerator.workflows.derived_size as ds
    from PIL import Image
    from origenerator.workflows.derived_size import scale_to_total_pixels

    monkeypatch.setattr(ds, "COMFYUI_INPUT_DIR", tmp_path)
    Image.new("RGB", (1920, 1080), (128, 128, 128)).save(tmp_path / "wide.png")

    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    panel._param_form._widgets["input_image"].setText("wide.png")

    width, height = scale_to_total_pixels(1920, 1080)
    assert panel._param_form._dim_value_labels["width"].text() == str(width)
    assert panel._param_form._dim_value_labels["height"].text() == str(height)


def test_manual_size_workflow_form_has_no_deriver(panel):
    # A text-to-image workflow sizes by hand, so its form gets no deriver and keeps
    # its own editable width/height (and the swap button), nothing to unlock.
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "sdxl_t2i"))
    form = panel._param_form
    assert form._size_deriver is None
    assert form._unlock_btn is None


# --- a read-only gallery (no client) ----------------------------------------

def test_tolerates_a_missing_client(qtbot, tmp_path):
    # A read-only gallery has no ComfyUI client. The panel still builds — the form
    # shows for inspection — but Generate is disabled and no signals are wired.
    p = GenerateConfigPanel(None, Database(tmp_path / "t.db"))
    qtbot.addWidget(p)
    assert p._generate_btn.isEnabled() is False
    p._on_generate()                      # no-op, no crash
    p.teardown()                          # never connected, so a no-op too


# --- Cancel the in-flight run from the tab -----------------------------------

def test_cancel_button_sits_beside_generate_hidden_until_generating(panel):
    # A Cancel shares the Generate button's row so the run a tab launched can be
    # stopped from the tab, not only the folder's tile. It's hidden until the
    # gallery marks the tab generating.
    from PyQt6.QtWidgets import QPushButton
    assert isinstance(panel._cancel_btn, QPushButton)
    assert _is_descendant(panel._cancel_btn, panel._panes.widget(0))  # the main pane
    assert panel._cancel_btn.parent() is panel._generate_btn.parent()  # same button row host
    assert panel._cancel_btn.isHidden()


def test_set_generating_swaps_generate_for_cancel(panel):
    # While the tab's run is in flight the gallery marks it generating: Cancel
    # appears and Generate greys out (no relaunching over a running slot).
    panel.set_generating(True)
    assert panel._cancel_btn.isHidden() is False
    assert panel._generate_btn.isEnabled() is False
    panel.set_generating(False)
    assert panel._cancel_btn.isHidden() is True
    assert panel._generate_btn.isEnabled() is True


def test_set_generating_false_keeps_generate_disabled_without_a_client(qtbot, tmp_path):
    # A read-only tab (no client) can never launch, so clearing the generating flag
    # must not re-enable Generate.
    p = GenerateConfigPanel(None, Database(tmp_path / "t.db"))
    qtbot.addWidget(p)
    p.set_generating(False)
    assert p._generate_btn.isEnabled() is False


def test_cancel_button_click_emits_cancel_requested(panel):
    # The tab doesn't cancel the job itself (the gallery owns it) — it relays the
    # click, which the gallery turns into the folder's re-roll cancel.
    got = []
    panel.cancel_requested.connect(lambda: got.append(True))
    panel.set_generating(True)
    panel._cancel_btn.click()
    assert got == [True]


def test_use_random_seed_switches_the_seed_to_random(panel):
    # After the user accepts "use a random seed", the choice sticks on the tab: the
    # seed switches to Random, so a later Generate draws a fresh seed rather than
    # reproducing the pinned one and re-asking.
    panel.prefill("sdxl_t2i", {"seed": 99})
    assert panel._param_form.seed_is_random() is False
    panel.use_random_seed()
    assert panel._param_form.seed_is_random() is True


# --- Generate emits a request; the gallery runs it as a re-roll --------------

def test_generate_emits_generate_requested_with_workflow_and_params(panel):
    # Clicking Generate no longer runs its own job — it asks the gallery to, by
    # emitting the workflow and the form's values (which the gallery launches as a
    # re-roll of the config's folder). Nothing is submitted or recorded here.
    panel._param_form.set_values({"positive_prompt": "a wizard", "seed": 42})
    requested = []
    panel.generate_requested.connect(lambda wf, params: requested.append((wf, params)))

    panel._on_generate()

    assert len(requested) == 1
    workflow_name, params = requested[0]
    assert workflow_name == "sdxl_t2i"
    assert params["positive_prompt"] == "a wizard"
    assert params["seed"] == 42
    assert panel._db.list_generations() == []       # the panel submits nothing itself


def test_generate_randomizes_a_random_seed_before_emitting(panel):
    # A Random seed is re-rolled by the form's get_values, so the params carried to
    # the gallery already hold a concrete fresh seed (never the literal field text).
    panel._param_form.set_values({"positive_prompt": "a cat"})  # leaves Random checked
    assert panel._param_form.seed_is_random() is True
    requested = []
    panel.generate_requested.connect(lambda wf, params: requested.append(params))

    panel._on_generate()

    assert isinstance(requested[0]["seed"], int)  # a real seed, drawn for this run


def test_generate_blocks_when_input_image_missing(qtbot, tmp_path):
    client = MagicMock()
    panel = GenerateConfigPanel(client, Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    requested = []
    panel.generate_requested.connect(lambda wf, params: requested.append(wf))

    panel._on_generate()

    assert requested == []                            # nothing asked of the gallery
    assert "image" in panel._generate_btn.text().lower()  # the guard flashes on the button
    assert panel._db.list_generations() == []         # nothing recorded


# --- show the newest matching generation instead of the blank placeholder -----

def test_workflow_picker_hides_machinery_workflows(qtbot, tmp_path):
    # The standalone image enhancer is launched by the gallery's enhance
    # buttons, not picked by hand: it stays out of the dropdown. Reusing one of
    # its rows still lands on its form — the entry is added on demand.
    panel = GenerateConfigPanel(ComfyUIClient(), Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    combo = panel._workflow_combo
    keys = {combo.itemData(i) for i in range(combo.count())}
    assert "image_enhance" not in keys
    assert "sdxl_t2i" in keys

    panel.prefill("image_enhance", WORKFLOW_REGISTRY["image_enhance"].default_params())
    assert combo.currentData() == "image_enhance"


def _wiz_params():
    return dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(), positive_prompt="a wizard")


# Rows a live config tab should match carry the workflow's current version, as a
# run made by this app would — the settings signature folds the version in, so a
# stale one would split the row from the tab's folder.
_SDXL_VERSION = WORKFLOW_REGISTRY["sdxl_t2i"].version


def test_recent_matching_row_finds_only_the_folders_own(qtbot, tmp_path):
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="wiz", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    )
    db.insert_generation(  # a different prompt → a different settings folder
        prompt_id="drg", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a dragon",
        params_json=json.dumps(dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                                    positive_prompt="a dragon")),
        workflow_json="{}",
    )
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    panel.prefill("sdxl_t2i", _wiz_params())
    assert panel._recent_matching_row()["prompt_id"] == "wiz"  # the dragon isn't in this folder


def test_prefill_shows_the_recent_match_in_the_preview(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    )
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: ("wiz.png", "image"))
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    shown = []
    monkeypatch.setattr(panel._preview, "show_media", lambda path, mt: shown.append((path, mt)))

    panel.prefill("sdxl_t2i", _wiz_params())

    assert shown[-1] == ("wiz.png", "image")


def test_idle_panel_with_no_matching_generation_stays_blank(qtbot, tmp_path):
    # Nothing generated with these settings yet → the placeholder, no crash.
    panel = GenerateConfigPanel(ComfyUIClient(), Database(tmp_path / "t.db"))
    qtbot.addWidget(panel)
    panel.show_recent_preview()
    assert panel._preview._media is None  # a placeholder, not a resolved file
    assert panel._preview._draggable_id is None  # nothing shown, nothing to drag


def test_autoshowing_a_recent_result_arms_the_preview_drag(qtbot, tmp_path, monkeypatch):
    db = Database(tmp_path / "t.db")
    db.insert_generation(
        prompt_id="g1", workflow_name="sdxl_t2i", workflow_version=_SDXL_VERSION,
        positive_prompt="a wizard", params_json=json.dumps(_wiz_params()), workflow_json="{}",
    )
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: ("wiz.png", "image"))
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    monkeypatch.setattr(panel._preview, "show_media", lambda path, mt: None)

    panel.prefill("sdxl_t2i", _wiz_params())  # autoshows the folder's newest result

    assert panel._preview._draggable_id == "g1"  # its preview can be dragged onto combine


# --- config snapshot / prefill / restore ------------------------------------

def test_current_config_does_not_randomize_and_reports_random_flag(panel):
    snap1 = panel.current_config()
    snap2 = panel.current_config()
    assert snap1.workflow_name == "sdxl_t2i"
    assert snap1.seed_is_random is True  # fresh panel: Random box checked
    assert snap1.params["seed"] == snap2.params["seed"]  # not re-randomized

    panel.prefill("sdxl_t2i", {"seed": 99})
    snap3 = panel.current_config()
    assert snap3.seed_is_random is False
    assert snap3.params["seed"] == 99


def test_prefill_selects_workflow_and_sets_values(panel):
    panel.prefill("wan22_i2v", {"positive_prompt": "a fox"})
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"


def test_restore_config_reapplies_workflow_params_and_random_seed(panel):
    snap = ConfigSnapshot("wan22_i2v", {"positive_prompt": "a fox"}, seed_is_random=True)
    panel.restore_config(snap)
    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "a fox"
    # A tab that was on Random comes back random, not frozen on a stale seed.
    assert panel._param_form.seed_is_random() is True


def test_restore_config_pins_concrete_seed_when_not_random(panel):
    panel.restore_config(ConfigSnapshot("sdxl_t2i", {"seed": 99}, seed_is_random=False))
    snap = panel.current_config()
    assert snap.seed_is_random is False
    assert snap.params["seed"] == 99


# --- title ------------------------------------------------------------------

def test_title_is_workflow_name_for_blank_config(panel):
    assert panel.title() == "SDXL Text-to-Image"


def test_title_leads_with_model_then_prompt(panel):
    panel.prefill("sdxl_t2i", {"positive_prompt": "a cat in a hat"})
    assert panel.title() == "SDXL Text-to-Image › a cat in a hat"


def test_title_changed_emitted_when_prompt_edited(panel):
    titles = []
    panel.title_changed.connect(titles.append)
    panel.prefill("sdxl_t2i", {"positive_prompt": "a fox"})
    assert titles and titles[-1] == "SDXL Text-to-Image › a fox"


def test_custom_title_overrides_and_sticks(panel):
    panel.set_custom_title("My experiments")
    assert panel.title() == "My experiments"
    panel.prefill("sdxl_t2i", {"positive_prompt": "a fox"})
    assert panel.title() == "My experiments"  # rename survives config changes


# --- estimate label ---------------------------------------------------------

class SpyDB:
    """A minimal stand-in returning canned recent durations and no rows.

    ``list_generations`` returns ``[]`` (the strip and recent-preview stay empty,
    which these duration tests don't inspect) and ``recent_durations`` feeds the
    estimate label.
    """

    def __init__(self, durations=None):
        self._durations = durations or []

    def recent_durations(self, workflow_name, limit=10):
        return list(self._durations)

    def list_generations(self):
        return []


def _spy_panel(qtbot, db):
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    return panel


def test_estimate_label_reflects_recent_durations(qtbot):
    panel = _spy_panel(qtbot, SpyDB(durations=[700.0, 724.0, 800.0]))
    assert panel._estimate_label.text() == "Typical time: ~12 min (based on 3 runs)"


def test_estimate_label_when_no_history(qtbot):
    panel = _spy_panel(qtbot, SpyDB(durations=[]))
    assert panel._estimate_label.text() == "Typical time: No timing data yet"


# --- settings key -----------------------------------------------------------

def test_settings_key_matches_a_stored_generation_of_the_same_settings(panel):
    full = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params())
    full["positive_prompt"] = "a cat"
    panel.prefill("sdxl_t2i", full)
    workflow, signature = panel.settings_key()
    assert workflow == "sdxl_t2i"
    # The same params at any seed share the signature; a different setting splits it.
    assert signature == gallery.settings_signature("sdxl_t2i", json.dumps({**full, "seed": 999}))
    assert signature != gallery.settings_signature("sdxl_t2i", json.dumps({**full, "steps": 7}))


# --- displaying a saved generation: the footer folded in from the inspect pane ---

def _image_row(db, prompt_id="img1", prompt="a cat", filename="sdxl_img1.png"):
    """A completed SDXL image whose output file an i2v can name as its source."""
    params = dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                  positive_prompt=prompt, seed=1)
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="sdxl_t2i", workflow_version="v002",
        positive_prompt=prompt, seed=1,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": filename, "subfolder": "image"}]))
    return db.get_generation(prompt_id)


def _video_row(db, prompt_id="vid1", input_image=None):
    """A completed WAN i2v video, optionally built on a named source image."""
    params = {"positive_prompt": "dance", "seed": 5}
    if input_image is not None:
        params["input_image"] = input_image
    db.insert_generation(
        prompt_id=prompt_id, workflow_name="wan22_i2v", workflow_version="v002",
        positive_prompt="dance", seed=5,
        params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation(prompt_id, status="completed",
                         output_files=json.dumps([{"filename": f"{prompt_id}.mp4", "subfolder": "video"}]))
    return db.get_generation(prompt_id)


@pytest.fixture
def saved_panel(qtbot, tmp_path):
    """A panel over a DB with an image and the video animated from it."""
    db = Database(tmp_path / "t.db")
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    panel._preview.show_media = MagicMock()  # don't start real WMF playback
    return panel, db


def _metadata_texts(panel):
    """Every label in the panel's metadata block, minus the wrapping zero-widths."""
    from PyQt6.QtWidgets import QLabel
    return [lbl.text().replace("​", "")
            for lbl in panel._metadata_block.findChildren(QLabel)]


def test_a_fresh_tab_shows_no_footer(saved_panel):
    panel, _db = saved_panel
    assert panel._displayed_row is None
    assert panel._metadata_block.isHidden()
    assert panel._animated_strip.isHidden()
    assert panel._source_tile.isHidden()
    assert panel._folder_btn.isHidden()
    assert panel._evolver_btn.isHidden()


def test_go_to_folder_shows_for_a_saved_generation_and_emits_its_id(saved_panel):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    panel.show_saved_generation(image, [image])
    assert not panel._folder_btn.isHidden()   # any saved gen has a folder to open
    got = []
    panel.containing_folder_requested.connect(got.append)

    panel._folder_btn.click()

    assert got == ["img1"]


def test_showing_a_saved_generation_arms_the_preview_drag(saved_panel, monkeypatch):
    panel, db = saved_panel
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: ("img1.png", "image"))
    image = _image_row(db, "img1")

    panel.show_saved_generation(image, [image])

    assert panel._preview._draggable_id == "img1"  # drag its preview onto combine


def test_a_generation_with_no_file_leaves_the_preview_undraggable(saved_panel, monkeypatch):
    panel, db = saved_panel
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: None)  # file gone
    image = _image_row(db, "img1")

    panel.show_saved_generation(image, [image])

    assert panel._preview._draggable_id is None  # nothing on screen to drag


def test_panel_forwards_the_preview_drag_signals(panel):
    started, ended = [], []
    panel.preview_drag_started.connect(started.append)
    panel.preview_drag_ended.connect(lambda: ended.append(True))

    panel._preview.drag_started.emit("gen9")
    panel._preview.drag_ended.emit()

    assert started == ["gen9"]  # relayed for the view to light the combine slot
    assert ended == [True]


def test_generate_button_fills_with_run_progress_only_while_generating(panel):
    panel.set_generating(True)
    panel._on_progress("pid", "9", 3, 12)
    assert panel._generate_btn._fraction == 0.25   # the run's step progress

    panel.set_generating(False)                    # run ended: back to the idle button
    panel._on_progress("pid", "9", 9, 12)               # a stray later event is ignored
    assert panel._generate_btn._fraction is None


def test_set_generating_true_again_keeps_the_fill(panel):
    # The gallery re-asserts the generating state on every rebuild, so re-marking an
    # already-running tab must NOT snap its filling button back to empty — otherwise
    # a reconnected run's bar would reset to 0 on each poll instead of advancing.
    panel.set_generating(True)
    panel._on_progress("pid", "9", 6, 12)               # filled to halfway
    assert panel._generate_btn._fraction == 0.5

    panel.set_generating(True)                     # redundant re-assert on a rebuild
    assert panel._generate_btn._fraction == 0.5    # still halfway, not reset to 0


def test_generate_button_ignores_another_jobs_progress(panel):
    # The client's progress is multiplexed across every job on the server; while a
    # background experiment executes, its steps must not fill this tab's button —
    # only the tracked run's own progress counts once the tab knows its prompt id.
    panel.set_generating(True, prompt_id="mine")

    panel._on_progress("experiment", "9", 6, 12)        # someone else's run
    assert panel._generate_btn._fraction == 0.0    # untouched (progress mode starts at 0)

    panel._on_progress("mine", "9", 3, 12)              # this tab's own run
    assert panel._generate_btn._fraction == 0.25


def test_reasserting_generating_retargets_the_tracked_prompt(panel):
    # A chained i2v swaps to a new prompt mid-flight (image stage, then video
    # stage) without leaving the generating state; the re-assert must adopt the
    # new prompt id so the second stage's progress still drives the button.
    panel.set_generating(True, prompt_id="image-stage")
    panel._on_progress("image-stage", "9", 6, 12)
    assert panel._generate_btn._fraction == 0.5

    panel.set_generating(True, prompt_id="video-stage")  # stage swap, still generating
    panel._on_progress("image-stage", "9", 9, 12)       # stale stage: ignored now
    assert panel._generate_btn._fraction == 0.5
    panel._on_progress("video-stage", "9", 3, 12)
    assert panel._generate_btn._fraction == 0.25


def test_showing_a_generation_reveals_its_file_and_created(saved_panel):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")

    panel.show_saved_generation(image, [image])

    assert not panel._metadata_block.isHidden()
    texts = _metadata_texts(panel)
    assert "image/sdxl_img1.png" in texts   # the filename — the reported regression
    assert "completed" not in texts         # Details (status/source) dropped as not useful
    assert "generated" not in texts


def test_autoshowing_a_recent_result_hides_the_metadata_footer(saved_panel, monkeypatch):
    # An idle autoshow is a peek, not an explicit selection: it must not leave a
    # prior selection's metadata (a different file's name) stranded on screen.
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    panel.show_saved_generation(image, [image])
    assert not panel._metadata_block.isHidden()

    monkeypatch.setattr(panel, "_recent_matching_row", lambda: None)
    panel.show_recent_preview()

    assert panel._metadata_block.isHidden()
    assert panel._source_tile.isHidden()
    assert panel._evolver_btn.isHidden()


def test_showing_an_image_lists_the_videos_it_was_animated_into(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "animated_preview_path", lambda r, o, t: None)
    image_rows = [image]

    panel.show_saved_generation(image, image_rows)

    assert not panel._animated_strip.isHidden()
    assert len(panel._animated_strip.findChildren(_VideoTile)) == 1
    assert panel._source_tile.isHidden()   # an image has no source-image tile
    assert panel._evolver_btn.isHidden()   # Evolver is for videos
    assert panel._displayed_row is image


def test_showing_an_image_footer_tile_click_emits_animated_activated(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "animated_preview_path", lambda r, o, t: None)
    panel.show_saved_generation(image, [image])
    got = []
    panel.animated_activated.connect(got.append)

    panel._animated_strip.video_activated.emit("vid1")

    assert got == ["vid1"]


def test_showing_a_video_reveals_evolver_and_source_tile(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [image])

    assert not panel._evolver_btn.isHidden()   # a video with a file → sendable
    assert not panel._source_tile.isHidden()   # its start frame is a known generation
    assert panel._source_tile._prompt_id == "img1"   # the tile points at that image
    assert panel._source_tile._filename.toolTip() == "sdxl_img1.png"  # names its file (caption may elide)
    assert panel._animated_strip.isHidden()    # a video isn't animated into anything


def test_video_source_tile_click_emits_source_activated(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    panel.show_saved_generation(video, [image])
    got = []
    panel.source_activated.connect(got.append)

    panel._source_tile.activated.emit("img1")   # what a click on the tile does

    assert got == ["img1"]


def test_video_without_a_known_source_hides_the_link(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand_placed.png")  # not a generation
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert panel._source_tile.isHidden()
    assert not panel._evolver_btn.isHidden()  # still a sendable video


def _script_beside(video_path):
    from origenerator.funscript import (
        funscript_path_for, synthesize_actions, write_funscript,
    )
    actions = synthesize_actions(2.0, hz=1.0, loop=False)
    write_funscript(funscript_path_for(video_path), actions)
    return actions


def test_osr2_drive_target_gives_path_player_and_actions_for_a_scripted_video(
    saved_panel, monkeypatch, tmp_path
):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    actions = _script_beside(vpath)
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))
    panel.show_saved_generation(video, [])

    # The global driver (owned by the view) asks the front panel what to drive.
    assert panel.osr2_drive_target() == (vpath, panel._preview.player(), actions)


def test_osr2_drive_target_is_none_for_a_video_without_a_funscript(saved_panel, monkeypatch, tmp_path):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")  # no .funscript beside it
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))
    panel.show_saved_generation(video, [])

    assert panel.osr2_drive_target() is None


def test_osr2_drive_target_is_none_for_an_image(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="i.png")
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (Path("C:/i.png"), "image"))
    monkeypatch.setattr(gcp_module, "animated_preview_path", lambda r, o, t: None)
    panel.show_saved_generation(image, [image])

    assert panel.osr2_drive_target() is None


def test_osr2_drive_target_follows_an_idle_autoshow_not_just_a_selection(
    saved_panel, monkeypatch, tmp_path
):
    # A tab auto-showing its newest result (show_recent_preview) — not an explicit
    # browsed selection — must still arm the drive: the scripted video is right there
    # on screen, so the OSR2 follows it. This closed the "the strip shows a script
    # but nothing drives" gap.
    panel, db = saved_panel
    vpath = tmp_path / "auto.mp4"
    vpath.write_bytes(b"v")
    actions = _script_beside(vpath)
    monkeypatch.setattr(panel, "_recent_matching_row",
                        lambda: {"prompt_id": "v", "workflow_name": "wan22_i2v"})
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))

    panel.show_recent_preview()  # the idle-autoshow path, not show_saved_generation

    assert panel.osr2_drive_target() == (vpath, panel._preview.player(), actions)


def test_showing_a_generation_emits_displayed_changed(saved_panel, monkeypatch, tmp_path):
    # The view reconciles the global driver whenever the front tab's video changes.
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand.png")
    vpath = tmp_path / "vid1.mp4"
    vpath.write_bytes(b"v")
    _script_beside(vpath)
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (vpath, "video"))
    fired = []
    panel.displayed_changed.connect(lambda: fired.append(True))

    panel.show_saved_generation(video, [])
    assert fired == [True]


def test_showing_a_video_seeds_the_form_with_its_params(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert panel._workflow_combo.currentData() == "wan22_i2v"
    assert panel._param_form.get_values_static()["positive_prompt"] == "dance"


def test_completed_result_shows_output_and_footer_without_touching_the_form(saved_panel):
    # The reported bug: while a Generate runs the user keeps typing the next
    # prompt; when the run finishes, its result must land in the tab — output in
    # the preview, footer revealed — WITHOUT re-seeding the form. The tab already
    # holds the settings that produced the result, so re-seeding only clobbers the
    # in-progress edit (here "a wizard mid-edit" would snap back to the row's "a cat").
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat", filename="sdxl_img1.png")
    panel._param_form.set_values({"positive_prompt": "a wizard mid-edit"})

    panel.show_completed_result(image, [image])

    assert panel._param_form.get_values_static()["positive_prompt"] == "a wizard mid-edit"
    assert panel._displayed_row is image          # the finished output is on display
    assert not panel._metadata_block.isHidden()   # with its footer


def test_showing_an_unregistered_generation_still_shows_preview_and_footer(saved_panel, monkeypatch):
    panel, db = saved_panel
    db.insert_generation(
        prompt_id="u1", workflow_name="unknown", workflow_version="imported",
        params_json=json.dumps({"steps": 20}), workflow_json="{}",
    )
    db.update_generation("u1", status="completed",
                         output_files=json.dumps([{"filename": "u1.mp4", "subfolder": "video"}]))
    row = db.get_generation("u1")
    before = panel._param_form.get_values_static()
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda r, out: (Path("C:/out/u1.mp4"), "video"))

    panel.show_saved_generation(row, [])

    assert panel._param_form.get_values_static() == before  # form left as-is
    assert not panel._evolver_btn.isHidden()                # footer still applies
    assert panel._displayed_row is row


def test_showing_a_saved_generation_shows_its_preview_over_the_autoshow(saved_panel, monkeypatch):
    # The form's recent-preview autoshow must not override the selection's output:
    # show_media's last call is the selection, not the folder's newest match.
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert panel._preview.show_media.call_args.args == (Path("C:/out/vid1.mp4"), "video")


def test_send_to_evolver_copies_the_displayed_video(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    video_path = Path("C:/out/vid1.mp4")
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (video_path, "video"))
    export = MagicMock(return_value=EVOLVER_INBOX_DIR / EVOLVER_SOURCE / "vid1.mp4")
    monkeypatch.setattr(evolver_export, "export_video", export)

    panel.show_saved_generation(video, [])
    panel._on_send_to_evolver()

    export.assert_called_once_with(video_path, EVOLVER_INBOX_DIR / EVOLVER_SOURCE)
    assert panel._displayed_row["evolver_exported_at"]
    assert panel._evolver_btn.text() == "Sent to Evolver ✓"
    assert panel._evolver_btn.isEnabled() is False


def test_send_to_evolver_does_not_re_export_an_already_sent_video(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    db.mark_evolver_exported("vid1")
    video = db.get_generation("vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    export = MagicMock()
    monkeypatch.setattr(evolver_export, "export_video", export)

    panel.show_saved_generation(video, [])
    assert panel._evolver_btn.text() == "Sent to Evolver ✓"
    panel._on_send_to_evolver()

    export.assert_not_called()


def test_send_to_evolver_warns_and_survives_a_failed_copy(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    monkeypatch.setattr(evolver_export, "export_video",
                        MagicMock(side_effect=OSError("inbox unreachable")))
    warn = MagicMock()
    monkeypatch.setattr(gcp_module.QMessageBox, "warning", warn)

    panel.show_saved_generation(video, [])
    panel._on_send_to_evolver()  # must not raise

    warn.assert_called_once()
