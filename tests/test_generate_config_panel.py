import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PyQt6.QtCore import QPoint, QSize, Qt
from PyQt6.QtGui import QPixmap

from origenerator import evolver_export, gallery
from origenerator.comfyui_client import ComfyUIClient
from origenerator.config import EVOLVER_INBOX_DIR, EVOLVER_SOURCE, GENAU_SOURCE
from origenerator.db import Database
from origenerator.generation_config import ConfigSnapshot
from origenerator.gui import export_lane as export_lane_module
from origenerator.gui import folder_request as folder_request_module
from origenerator.gui import generate_config_panel as gcp_module
from origenerator.gui import related_media as related_media_module
from origenerator.gui import corner_controls, icons
from origenerator.gui.animated_strip import _VideoTile
from origenerator.gui.generate_config_panel import GenerateConfigPanel
from origenerator.workflows import WORKFLOW_REGISTRY


@pytest.fixture
def blank_panel(qtbot, tmp_path):
    """A panel as it opens: the picker on its placeholder, nothing chosen yet."""
    db = Database(tmp_path / "test.db")
    p = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(p)
    return p


@pytest.fixture
def panel(blank_panel):
    """A panel with its workflow answered — the state most of these tests are
    about, where there is a form below the picker to poke at."""
    blank_panel._workflow_combo.setCurrentIndex(_combo_index(blank_panel, "sdxl_t2i"))
    return blank_panel


def _combo_index(panel, key):
    for i in range(panel._workflow_combo.count()):
        if panel._workflow_combo.itemData(i) == key:
            return i
    raise AssertionError(f"workflow {key} not in combo")


def _lane_button(panel, name="Evolver"):
    """The button this panel wears for the named export lane."""
    return panel._lanes[name].button


def _is_descendant(widget, ancestor) -> bool:
    node = widget.parent()
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent()
    return False


# --- layout: one preview-over-form column ----------------------------------

def test_the_panel_is_one_column_with_no_side_pane(panel):
    # The tab is a single column now — no splitter, no second pane beside it.
    from PyQt6.QtWidgets import QSplitter
    assert panel.findChildren(QSplitter) == []


def test_preview_leads_the_column_over_the_form_and_generate(panel):
    # Preview-over-form: the preview sits on top of the settings, with the
    # Generate button under them, all in the panel's own column.
    column = panel.layout()
    assert column.indexOf(panel._preview) == 0
    assert column.indexOf(panel._preview) < column.indexOf(panel._scroll)
    assert _is_descendant(panel._generate_btn, panel)


def test_a_narrow_pane_squeezes_the_fields_instead_of_scrolling_sideways(panel):
    """The settings scroll never grows a horizontal bar: squeezed, the form gives
    up width — the pickers elide, the labels wrap, a row drops its field onto its
    own line — rather than push the whole column out of view sideways.

    The failure this exists for: a model picker asked for its longest file name,
    a section header for its whole title and the workflow picker for its
    placeholder, so the pane could not be narrowed without a sideways scroll.
    """
    from PyQt6.QtWidgets import QApplication

    for section in panel._param_form._sections.values():
        section.set_collapsed(False)   # every field on show: the widest the form gets
    panel.show()

    for width in (600, 420, 300):
        panel.resize(width, 800)
        QApplication.processEvents()
        assert not panel._scroll.horizontalScrollBar().isVisible(), f"at {width}px"


def test_nothing_in_the_form_is_laid_out_past_the_column_it_sits_in(blank_panel):
    """Squeezed, the settings shorten — none of them runs off the side.

    The failure this exists for: QFormLayout's WrapLongRows lays a wrapped label
    out at its own full-line size hint without clamping it to the row, so a label
    like "Noise Seed (Stage 1)" ran 50px past the edge of the column it was in.
    Nothing on screen said what had been cut: not an ellipsis, and not the scroll
    bar, which stayed away because the layout's stated minimum still fit.
    """
    from PyQt6.QtWidgets import QApplication

    panel = blank_panel
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    for section in panel._param_form._sections.values():
        section.set_collapsed(False)
    panel.show()

    host = panel._scroll.widget()
    for width in (600, 420, 320, 260, 240):
        panel.resize(width, 800)
        QApplication.processEvents()
        over = []

        def walk(widget):
            if not widget.isVisible():
                return
            right = widget.mapTo(host, widget.rect().topRight()).x()
            if right >= host.width():
                over.append((type(widget).__name__,
                             getattr(widget, "text", lambda: "")(),
                             right - host.width()))
            for child in widget.children():
                if child.isWidgetType():
                    walk(child)

        walk(host)
        assert not over, f"at {width}px: {over[:3]}"


def test_the_pane_will_not_be_squeezed_narrower_than_its_settings(blank_panel):
    """Its floor is what its contents need, so the scroll bar never has to appear.

    Squeezing a form and scrolling it sideways is a bad trade for the drag it
    allows, so the pane refuses to go there at all: the floor is read live off the
    scroll's contents, which is why it rises when a wider workflow is chosen.
    """
    from PyQt6.QtWidgets import QApplication

    panel = blank_panel
    blank_floor = panel._contents_floor()
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))
    for section in panel._param_form._sections.values():
        section.set_collapsed(False)
    panel.show()
    QApplication.processEvents()

    # A wider workflow is a wider floor: it is read off the contents, not fixed.
    assert panel._contents_floor() > blank_floor
    floor = panel.minimumSizeHint().width()
    assert floor >= panel._contents_floor()

    panel.resize(floor, 800)
    QApplication.processEvents()
    assert not panel._scroll.horizontalScrollBar().isVisible()
    assert panel._scroll.viewport().width() >= panel._scroll.widget().minimumSizeHint().width()


def test_the_button_bank_wraps_rather_than_squeezing_its_labels(panel):
    """Narrowed, the buttons drop onto further lines, each still at its full width.

    The failure this exists for: a row layout squeezed them past their minimum and
    clipped what was left, so the bank read "o fo", "to E", "to G", "anc", "ner".
    """
    from PyQt6.QtWidgets import QApplication

    buttons = [*(lane.button for lane in panel._lanes.values()),
               panel._cancel_btn, panel._generate_btn]
    for button in buttons:
        button.show()          # the busiest the bank ever is: every button on
    panel.show()

    panel.resize(340, 800)
    QApplication.processEvents()

    for button in buttons:
        assert button.width() == button.sizeHint().width(), button.text()
    assert len({button.y() for button in buttons}) > 1        # it wrapped
    # ...and every line still ends in the corner the bank sits in.
    lines = {}
    for button in buttons:
        lines[button.y()] = max(lines.get(button.y(), 0), button.x() + button.width())
    assert len(set(lines.values())) == 1


def test_the_pane_keeps_a_margin_round_its_contents(panel):
    # Nothing sits flush against the tab's edge — not the preview at the top, not
    # the settings down either side, not the button bank at the bottom.
    from origenerator.gui.generate_config_panel import _PANE_MARGIN

    panel.show()
    panel.resize(700, 800)

    top_left = panel._preview.mapTo(panel, panel._preview.rect().topLeft())
    assert top_left.x() == _PANE_MARGIN
    assert top_left.y() == _PANE_MARGIN
    scroll_right = panel._scroll.mapTo(panel, panel._scroll.rect().topRight()).x()
    assert panel.width() - scroll_right - 1 == _PANE_MARGIN
    generate = panel._generate_btn
    bottom = generate.mapTo(panel, generate.rect().bottomLeft()).y()
    assert panel.height() - bottom - 1 == _PANE_MARGIN


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
    for widget in (panel._metadata_block, panel._related._source_tile,
                   panel._related._animated_strip, panel._param_form):
        assert _is_descendant(widget, panel._scroll)


def test_file_info_above_form_related_media_below(panel):
    # File/Created sits above the form; the source-image tile and animated-in strip
    # sit below it, at the bottom of the scroll just above the buttons.
    body = panel._scroll.widget().layout()
    form_at = body.indexOf(panel._form_host)
    assert body.indexOf(panel._metadata_block) < form_at
    # The two links are one widget under the form now, carrying both.
    assert body.indexOf(panel._related) > form_at
    links = panel._related.layout()
    assert links.indexOf(panel._related._source_tile) \
        < links.indexOf(panel._related._animated_strip)


def test_evolver_shares_the_button_bank_with_generate_and_cancel(panel):
    # One button bank: Send-to-Evolver isn't a stray footer button — it sits in the
    # same row as Cancel and Generate.
    bank = _layout_containing(panel.layout(), panel._generate_btn)
    assert bank is not None
    assert bank.indexOf(_lane_button(panel)) != -1
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


# --- Cancel the in-flight run from the tab -----------------------------------

def test_cancel_button_sits_beside_generate_hidden_until_generating(panel):
    # A Cancel shares the Generate button's row so the run a tab launched can be
    # stopped from the tab, not only the folder's tile. It's hidden until the
    # gallery marks the tab generating.
    from PyQt6.QtWidgets import QPushButton
    assert isinstance(panel._cancel_btn, QPushButton)
    assert _is_descendant(panel._cancel_btn, panel)  # in the tab's own column
    assert panel._cancel_btn.parent() is panel._generate_btn.parent()  # same button row host
    assert panel._cancel_btn.isHidden()


def test_set_generating_offers_cancel_beside_a_still_pressable_generate(panel):
    # While the tab's run is in flight the gallery marks it generating: Cancel
    # appears, and Generate stays pressable — ComfyUI takes a queue, so another
    # press asks for another job rather than relaunching over the first.
    panel.set_generating(True)
    assert panel._cancel_btn.isHidden() is False
    assert panel._generate_btn.isEnabled() is True
    panel.set_generating(False)
    assert panel._cancel_btn.isHidden() is True
    assert panel._generate_btn.isEnabled() is True


def test_the_discard_button_says_next_seed_while_the_folder_auto_generates(panel):
    # Same button, honest label: with the folder looping, the press discards this
    # seed and the loop starts another — nothing stops.
    panel.set_generating(True, auto_generating=True)
    assert panel._cancel_btn.text() == "Next seed"

    panel.set_generating(True)  # Auto switched off mid-run: a plain cancel
    assert panel._cancel_btn.text() == "Cancel"


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


# --- the resting state: a whole form, waiting on a workflow -----------------

def test_a_fresh_panel_picks_no_workflow(blank_panel):
    # The pane's resting tab asks which workflow to run rather than presenting
    # whichever is registered first as a choice already made.
    assert blank_panel._workflow_combo.currentIndex() == -1
    assert blank_panel._workflow_combo.currentData() is None
    assert blank_panel._workflow_combo.placeholderText()


def test_a_fresh_panel_lays_out_nothing_the_workflow_decides(blank_panel):
    # Which params exist is the workflow's answer, and so is its typical time —
    # neither can be shown before the picker is answered.
    assert blank_panel._param_form is None
    assert blank_panel._estimate_label.isHidden()


def test_a_fresh_panel_cannot_generate(blank_panel):
    # Greyed rather than silently inert: there is no graph to submit.
    assert blank_panel._generate_btn.isEnabled() is False


def test_picking_a_workflow_fills_in_everything_below(blank_panel):
    blank_panel._workflow_combo.setCurrentIndex(_combo_index(blank_panel, "sdxl_t2i"))
    assert blank_panel._param_form is not None
    assert not blank_panel._estimate_label.isHidden()
    assert blank_panel._generate_btn.isEnabled() is True


def test_a_fresh_panel_is_blank_and_a_used_one_is_not(blank_panel):
    # What load_selection reads to decide whether a tab is free to be clicked into.
    assert blank_panel.is_blank() is True
    blank_panel._workflow_combo.setCurrentIndex(_combo_index(blank_panel, "sdxl_t2i"))
    assert blank_panel.is_blank() is False


def test_a_fresh_panel_shows_the_previews_placeholder_not_a_black_pane(blank_panel):
    # Nothing has been generated with settings that don't exist yet, so the
    # preview rests on its own "nothing selected" placeholder.
    assert blank_panel._displayed_row is None


def test_a_fresh_panel_names_itself_for_what_it_is(blank_panel):
    # "unknown" would read as a workflow the app failed to recognize, rather than
    # a question nobody has answered yet.
    assert blank_panel.title() == "New generation"


def test_generate_on_a_workflowless_panel_asks_for_nothing(blank_panel):
    fired = []
    blank_panel.generate_requested.connect(lambda *a: fired.append(a))
    blank_panel._on_generate()
    assert fired == []


# --- title and mark ---------------------------------------------------------

def _folder_name(panel):
    """The name the gallery folder this config maps to wears in the tree."""
    return gallery.config_folder_name(*panel.settings_key(),
                                      panel._db.folder_meta_map())


def test_a_config_with_no_result_is_named_by_its_folder(panel):
    # Nothing has been generated with these settings, so there is no item to name
    # the tab: it wears the name of the folder its output would land in — the
    # same short code the tree shows over there.
    assert panel.title() == _folder_name(panel)
    assert panel.title() != "New generation"


def test_a_folder_the_user_named_gives_the_tab_that_name(panel):
    from origenerator.gallery.keys import settings_key
    panel._db.rename_folder(settings_key("image", *panel.settings_key()), "Wizards")

    assert panel.title() == "Wizards"


def test_a_displayed_item_names_the_tab_by_its_file(panel, tmp_path):
    row = _image_row(panel._db, filename="sdxl_img1.png")
    panel._preview.show_media = MagicMock()

    panel.show_saved_generation(row, [row])

    assert panel.title() == "sdxl_img1.png"


def test_title_changed_when_the_shown_item_changes(panel):
    row = _image_row(panel._db, filename="sdxl_img1.png")
    panel._preview.show_media = MagicMock()
    titles = []
    panel.title_changed.connect(titles.append)

    panel.show_saved_generation(row, [row])

    assert titles and titles[-1] == "sdxl_img1.png"


def test_the_mark_is_the_shown_items_own_thumbnail(panel, tmp_path):
    pixmap = QPixmap(4, 4)
    pixmap.fill(Qt.GlobalColor.red)
    thumb = tmp_path / "thumb.png"
    pixmap.save(str(thumb))
    row = dict(_image_row(panel._db), thumbnail_path=str(thumb))
    panel._preview.show_media = MagicMock()

    panel.show_saved_generation(row, [row])

    # The item's own picture, at its own size — not one of the drawn glyphs.
    assert panel.tab_icon().availableSizes() == [QSize(4, 4)]


def test_the_mark_falls_back_to_what_the_config_makes(panel):
    # No result yet, so no thumbnail: the plain photo/play mark says which kind
    # of thing this tab would produce.
    assert panel.tab_icon().cacheKey() == icons.media_type_icon("image").cacheKey()


def test_a_tab_with_no_workflow_yet_wears_no_mark(blank_panel):
    assert blank_panel.tab_icon().isNull()


# --- estimate label ---------------------------------------------------------

class SpyDB:
    """A minimal stand-in returning canned recent durations and no rows.

    ``list_generations`` returns ``[]`` (the strip and recent-preview stay empty,
    which these duration tests don't inspect), ``folder_meta_map`` no names (the
    tab falls back to its folder's code), and ``recent_durations`` feeds the
    estimate label.
    """

    def __init__(self, durations=None):
        self._durations = durations or []

    def recent_durations(self, workflow_name, limit=10):
        return list(self._durations)

    def list_generations(self):
        return []

    def folder_meta_map(self):
        return {}


def _spy_panel(qtbot, db):
    panel = GenerateConfigPanel(ComfyUIClient(), db)
    qtbot.addWidget(panel)
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "sdxl_t2i"))
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
    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "sdxl_t2i"))
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
    assert panel._versions.isHidden()
    assert panel._related._animated_strip.isHidden()
    assert panel._related._source_tile.isHidden()
    assert _lane_button(panel).isHidden()


def _enhanced_image_row(db, prompt_id="img1"):
    """An image that has been enhanced once: the enhanced file leads, the
    original stays listed, and the level's settings are recorded."""
    _image_row(db, prompt_id)
    return _fold_enhancement(db, prompt_id)


def _fold_enhancement(db, prompt_id="img1"):
    """Fold an enhancement onto an image already recorded — what the gallery does
    to the row when a standalone enhance lands: the enhanced file leads, the
    original stays listed behind it, and the level's settings are recorded."""
    db.update_generation(
        prompt_id,
        output_files=json.dumps([
            {"filename": "image_enhance_00001_.png", "subfolder": "image"},
            {"filename": "sdxl_img1.png", "subfolder": "image"},
        ]),
        original_files=json.dumps([{"filename": "sdxl_img1.png", "subfolder": "image"}]),
        enhance_history=json.dumps([
            {"filename": "image_enhance_00001_.png",
             "params": {"enhance_scale": 2.0, "enhance_steps": 20,
                        "enhance_denoise": 0.15}},
        ]),
    )
    return db.get_generation(prompt_id)


def _level_rows(panel):
    from origenerator.gui.enhance_versions import _LevelRow
    return panel._versions._host.findChildren(_LevelRow)


def _row_texts(row):
    """Every label on one level's row, minus the wrapping zero-widths."""
    from PyQt6.QtWidgets import QLabel
    return [lbl.text().replace("​", "") for lbl in row.findChildren(QLabel)]


def test_an_unenhanced_image_still_shows_its_original_and_the_add_card(saved_panel):
    # This is where an image's versions live, so it has to be somewhere you can
    # already see before the first enhancement makes a second one — not least
    # because the enhance you just launched replaces the list's only other
    # content while it runs.
    from origenerator.gui.enhance_versions import _AddRow

    panel, db = saved_panel
    image = _image_row(db, "img1")
    panel.show_saved_generation(image, [image])
    assert not panel._versions.isHidden()
    (row,) = _level_rows(panel)
    assert "Original" in _row_texts(row)
    assert panel._versions._host.findChildren(_AddRow)


def test_a_video_has_no_version_strip(saved_panel):
    # The enhancer takes images; a video has no versions and no row to press.
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    panel.show_saved_generation(video, [])
    assert panel._versions.isHidden()


def test_an_enhanced_image_lists_its_levels_newest_first(saved_panel):
    panel, db = saved_panel
    image = _enhanced_image_row(db)
    panel.show_saved_generation(image, [image])

    assert not panel._versions.isHidden()
    rows = _level_rows(panel)
    first = " / ".join(t for t in _row_texts(rows[0]) if t and t != "—")
    assert first.startswith("Enhance 1")
    assert "2x" in first and "20 steps" in first and "0.15 denoise" in first
    assert "Original" in _row_texts(rows[1])


def test_each_level_carries_its_own_file_row(saved_panel):
    # The file information is per enhancement, so it sits with the level that
    # made it — the same File row a metadata block renders, copy button and all,
    # rather than a pooled block at the top labeled with a level's name.
    from PyQt6.QtWidgets import QPushButton

    panel, db = saved_panel
    image = _enhanced_image_row(db)
    panel.show_saved_generation(image, [image])

    rows = _level_rows(panel)
    assert "image/image_enhance_00001_.png" in _row_texts(rows[0])
    assert "image/sdxl_img1.png" in _row_texts(rows[1])
    for row in rows:
        names = {b.objectName() for b in row.findChildren(QPushButton)}
        assert "copyButton" in names and "revealButton" in names
        assert "Created" in _row_texts(row)
    # ...and the block at the top has nothing left to repeat.
    assert panel._metadata_block.isHidden()


def test_an_enhancement_in_flight_shows_in_the_strip(saved_panel):
    from origenerator.gui.enhance_versions import _PendingRow

    panel, db = saved_panel
    image = _image_row(db, "img1")      # never enhanced: no levels of its own
    panel.show_saved_generation(image, [image])
    assert not panel._versions._host.findChildren(_PendingRow)

    panel.set_pending_enhancement(("running", None, "2x · 20 steps · 0.15 denoise"))

    assert not panel._versions.isHidden()
    assert panel._versions._host.findChildren(_PendingRow)
    # The original stays beside it — the base render is out and worth looking at
    # while its enhancement is made, which is the point of generating it first.
    assert _level_rows(panel)

    panel.set_pending_enhancement(None)
    assert not panel._versions._host.findChildren(_PendingRow)


def test_a_running_enhancement_streams_into_the_preview(saved_panel, tmp_path,
                                                        monkeypatch):
    # The pane at the top of the tab is where this app shows what is being made,
    # and an enhancement of the image on display is being made — it used to be
    # the one surface that sat on the old picture while the little row streamed.
    from origenerator.gui import generate_config_panel as module

    panel, db = saved_panel
    output_dir = tmp_path / "out"
    (output_dir / "image").mkdir(parents=True)
    (output_dir / "image" / "sdxl_img1.png").write_bytes(b"x")
    monkeypatch.setattr(module, "COMFYUI_OUTPUT_DIR", output_dir)

    image = _image_row(db, "img1")
    panel.show_saved_generation(image, [image])
    panel._preview.show_frame = MagicMock()
    panel._preview.show_media.reset_mock()

    panel.set_pending_enhancement(("running", b"\x89PNG-ish", "2x"))
    panel._preview.show_frame.assert_called_once_with(b"\x89PNG-ish", keep_notice=True)

    # ...and when the run ends the pane goes back to the image itself.
    panel.set_pending_enhancement(None)
    panel._preview.show_media.assert_called_once_with(
        output_dir / "image" / "sdxl_img1.png", "image"
    )


def test_picked_levels_are_deleted_by_filename(saved_panel):
    # Positions belong to the widget that produced them; the gallery does the
    # deleting and has to be told which files.
    panel, db = saved_panel
    image = _enhanced_image_row(db)
    panel.show_saved_generation(image, [image])
    asked = []
    panel.levels_delete_requested.connect(lambda pid, names: asked.append((pid, names)))

    panel._versions.delete_requested.emit([0])

    assert asked == [("img1", ["image_enhance_00001_.png"])]


def test_picking_a_level_swaps_the_preview_without_changing_the_selection(saved_panel,
                                                                          tmp_path,
                                                                          monkeypatch):
    # The levels are versions of one image, not separate generations: picking
    # one is a look, so the row on display, its form and its footer all stay put.
    from origenerator.gui import generate_config_panel as module

    panel, db = saved_panel
    output_dir = tmp_path / "out"
    (output_dir / "image").mkdir(parents=True)
    for name in ("image_enhance_00001_.png", "sdxl_img1.png"):
        (output_dir / "image" / name).write_bytes(b"x")
    monkeypatch.setattr(module, "COMFYUI_OUTPUT_DIR", output_dir)

    image = _enhanced_image_row(db)
    panel.show_saved_generation(image, [image])
    panel._preview.show_media.reset_mock()

    panel._show_level(1)   # the original

    panel._preview.show_media.assert_called_once_with(
        output_dir / "image" / "sdxl_img1.png", "image"
    )
    assert panel._displayed_row["prompt_id"] == "img1"


def test_the_preview_carries_the_shown_generations_corner_controls(saved_panel):
    # The acts on a generation belong on its picture, not in a bank under the
    # settings — the same three corners a gallery thumbnail of it wears.
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")

    panel.show_saved_generation(image, [image])

    assert panel._preview._actions_id == "img1"


def test_a_preview_corner_relays_the_act_with_the_id_it_is_about(saved_panel):
    panel, _db = saved_panel
    got = []
    panel.item_action_requested.connect(lambda pid, action: got.append((pid, action)))

    panel._preview.action_triggered.emit("img1", corner_controls.STAR)

    assert got == [("img1", corner_controls.STAR)]


def test_right_clicking_the_preview_asks_for_the_generations_menu(saved_panel):
    panel, _db = saved_panel
    got = []
    panel.context_menu_requested.connect(lambda pid, pos: got.append(pid))

    panel._preview.context_requested.emit("img1", QPoint(4, 4))

    assert got == ["img1"]


def test_a_deleted_images_version_says_how_long_it_has_been_in_the_trash(saved_panel):
    panel, db = saved_panel
    image = dict(_image_row(db, "img1"), days_in_trash=2)

    panel.show_saved_generation(image, [image])

    files = [text for text in _version_texts(panel) if "sdxl_img1.png" in text]
    assert files and all(text.startswith("(2 days in trash)") for text in files)


def _version_texts(panel):
    """Every label in the panel's version list, minus the wrapping zero-widths."""
    from PyQt6.QtWidgets import QLabel
    return [lbl.text().replace("​", "")
            for lbl in panel._versions.findChildren(QLabel)]


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


def test_the_tab_watches_no_run_of_its_own(panel):
    # Generate submits and is done with it. It used to fill with the tracked run's
    # steps, which took a third telling of one run — differently worded from the
    # strip's queue and the shelf's card — and wired the control that starts work
    # to the state of work already going.
    panel.set_generating(True)
    assert panel._generate_btn.text() == "Generate"
    assert not hasattr(panel, "_on_progress")
    assert not hasattr(panel, "_generating_prompt_id")


def test_showing_a_generation_reveals_its_file_and_created(saved_panel):
    panel, db = saved_panel
    video = _video_row(db, "vid1")

    panel.show_saved_generation(video, [])

    assert not panel._metadata_block.isHidden()
    texts = _metadata_texts(panel)
    assert "video/vid1.mp4" in texts         # the filename — the reported regression
    assert "completed" not in texts         # Details (status/source) dropped as not useful
    assert "generated" not in texts


def test_autoshowing_a_recent_result_hides_the_metadata_footer(saved_panel, monkeypatch):
    # An idle autoshow is a peek, not an explicit selection: it must not leave a
    # prior selection's metadata (a different file's name) stranded on screen.
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    panel.show_saved_generation(image, [image])
    assert not panel._versions.isHidden()   # where an image's file facts live

    monkeypatch.setattr(panel, "_recent_matching_row", lambda: None)
    panel.show_recent_preview()

    assert panel._metadata_block.isHidden()
    assert panel._versions.isHidden()
    assert panel._related._source_tile.isHidden()
    assert _lane_button(panel).isHidden()


def test_showing_an_image_lists_the_videos_it_was_animated_into(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(related_media_module, "animated_preview_path", lambda r, o, t: None)
    image_rows = [image]

    panel.show_saved_generation(image, image_rows)

    assert not panel._related._animated_strip.isHidden()
    assert len(panel._related._animated_strip.findChildren(_VideoTile)) == 1
    assert panel._related._source_tile.isHidden()   # an image has no source-image tile
    assert _lane_button(panel).isHidden()   # Evolver is for videos
    assert panel._displayed_row is image


def test_showing_an_image_footer_tile_click_emits_animated_activated(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(related_media_module, "animated_preview_path", lambda r, o, t: None)
    panel.show_saved_generation(image, [image])
    got = []
    panel.animated_activated.connect(got.append)

    panel._related._animated_strip.video_activated.emit("vid1")

    assert got == ["vid1"]


def test_showing_a_video_reveals_evolver_and_source_tile(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [image])

    assert not _lane_button(panel).isHidden()   # a video with a file → sendable
    assert not panel._related._source_tile.isHidden()   # its start frame is a known generation
    assert panel._related._source_tile._prompt_id == "img1"   # the tile points at that image
    assert panel._related._source_tile._filename.toolTip() == "sdxl_img1.png"  # names its file (caption may elide)
    assert panel._related._animated_strip.isHidden()    # a video isn't animated into anything


def test_video_source_tile_click_emits_source_activated(saved_panel, monkeypatch):
    panel, db = saved_panel
    image = _image_row(db, "img1", filename="sdxl_img1.png")
    video = _video_row(db, "vid1", input_image="sdxl_img1.png")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    panel.show_saved_generation(video, [image])
    got = []
    panel.source_activated.connect(got.append)

    panel._related._source_tile.activated.emit("img1")   # what a click on the tile does

    assert got == ["img1"]


def test_video_without_a_known_source_hides_the_link(saved_panel, monkeypatch):
    panel, db = saved_panel
    video = _video_row(db, "vid1", input_image="hand_placed.png")  # not a generation
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert panel._related._source_tile.isHidden()
    assert not _lane_button(panel).isHidden()  # still a sendable video


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
    monkeypatch.setattr(related_media_module, "animated_preview_path", lambda r, o, t: None)
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
    assert panel._displayed_row is image     # the finished output is on display
    assert not panel._versions.isHidden()    # with its footer


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
    assert not _lane_button(panel).isHidden()               # footer still applies
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


def test_folding_a_form_section_does_not_open_a_gap_below_it(saved_panel):
    # A stretch between the form and the sections under it grew by exactly what
    # each fold saved, so the closer the form got the further away they went.
    panel, db = saved_panel
    panel.show_saved_generation(_enhanced_image_row(db), [])
    panel.resize(480, 900)
    panel.show()

    def gap():
        form = panel._form_host
        return panel._versions.mapTo(panel, panel._versions.rect().topLeft()).y() \
            - (form.mapTo(panel, form.rect().topLeft()).y() + form.height())

    before = gap()
    for section in panel._param_form._sections.values():
        section.set_collapsed(True)
    panel._param_form.adjustSize()
    panel.layout().activate()

    assert gap() == before   # the column closed up; the space did not move down


# --- the Genau lane: send a clip, or make one from an image -------------------


def test_send_to_genau_shares_the_one_button_bank(panel):
    bank = _layout_containing(panel.layout(), panel._generate_btn)
    assert bank.indexOf(_lane_button(panel, "Genau")) != -1


def test_the_two_lanes_are_sent_independently(saved_panel, monkeypatch):
    # Sending a video to Evolver must not read as having sent it to Genau: they are
    # different errands with different destinations.
    panel, db = saved_panel
    video = _video_row(db, "vid1")
    db.mark_evolver_exported("vid1")
    video = db.get_generation("vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))

    panel.show_saved_generation(video, [])

    assert _lane_button(panel).text() == "Sent to Evolver ✓"
    assert _lane_button(panel, "Genau").text() == "Send to Genau"
    assert _lane_button(panel, "Genau").isEnabled()


# --- the modified notice: the preview no longer answers the form -------------

def _notice(panel):
    """What the preview is saying over its picture, or "" when it says nothing."""
    return "" if panel._preview._notice.isHidden() else panel._preview._notice.text()


def _set_prompt(panel, text):
    panel._param_form._widgets["positive_prompt"].setPlainText(text)


def test_a_browsed_generation_arrives_unmarked(saved_panel):
    # The form was just seeded from this row, so the picture is exactly what
    # these settings make: nothing to warn about.
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    panel.show_saved_generation(image, [image])
    assert _notice(panel) == ""


def test_editing_a_setting_marks_the_picture_as_not_generated_yet(saved_panel):
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    panel.show_saved_generation(image, [image])

    _set_prompt(panel, "a dog")

    assert _notice(panel) == "(not yet generated with modifications)"


def test_putting_the_setting_back_clears_the_mark(saved_panel):
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    panel.show_saved_generation(image, [image])
    _set_prompt(panel, "a dog")

    _set_prompt(panel, "a cat")

    assert _notice(panel) == ""


def test_re_rolling_the_seed_marks_it_too(saved_panel):
    # Same prompt, but the run would draw a different seed — so the picture on
    # screen is not what Generate would make either.
    panel, db = saved_panel
    image = _image_row(db, "img1")
    panel.show_saved_generation(image, [image])

    panel._param_form.set_seed_random(True)

    assert _notice(panel) == "(not yet generated with modifications)"


def test_a_tab_with_nothing_on_display_is_never_marked(panel):
    # No picture, nothing to be modified away from — a fresh tab's form is
    # edited constantly and must not carry a warning about an empty pane.
    _set_prompt(panel, "a dog")
    assert panel._displayed_row is None
    assert _notice(panel) == ""


def test_the_idle_autoshow_is_marked_once_the_form_moves_off_it(
    saved_panel, monkeypatch, tmp_path
):
    # The pane's resting picture is this config's newest result, so it stops
    # matching the moment the settings do.
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    ipath = tmp_path / "sdxl_img1.png"
    ipath.write_bytes(b"p")
    monkeypatch.setattr(panel, "_recent_matching_row", lambda: image)
    monkeypatch.setattr(gcp_module, "resolve_preview", lambda row, out: (ipath, "image"))

    panel.show_recent_preview()
    assert panel._displayed_row is not None and _notice(panel) == ""

    _set_prompt(panel, "a dog")

    assert _notice(panel) == "(not yet generated with modifications)"


def test_switching_workflow_leaves_no_stale_mark(saved_panel):
    # The new workflow re-shows its own newest result (or nothing), so the mark
    # doesn't carry over from the settings that were replaced wholesale.
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    panel.show_saved_generation(image, [image])
    _set_prompt(panel, "a dog")

    panel._workflow_combo.setCurrentIndex(_combo_index(panel, "wan22_i2v"))

    assert _notice(panel) == ""


def _frame_bytes(tmp_path, size: int = 8) -> bytes:
    """One encoded preview frame, as ComfyUI streams them over the websocket.
    ``size`` only varies the picture, so two calls make two distinct frames."""
    path = tmp_path / f"frame{size}.png"
    pixmap = QPixmap(size, 6)
    pixmap.fill()
    pixmap.save(str(path), "PNG")
    return path.read_bytes()


def test_an_enhancement_streaming_in_leaves_the_mark_standing(saved_panel, tmp_path):
    # An enhancement is not a run of these settings — it is the coming state of
    # the very picture they are being edited away from — so the mark holds over
    # its frames, message and dim together. Clearing it per frame left the two
    # trading places several times a second while the form was typed in.
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    panel.show_saved_generation(image, [image])
    _set_prompt(panel, "a dog")

    panel.set_pending_enhancement(("running", _frame_bytes(tmp_path), "2x"))

    assert _notice(panel) == "(not yet generated with modifications)"
    assert not panel._preview._notice_dim.isHidden()

    # ...and it goes on standing as the run streams, rather than blinking off
    # with every frame that arrives.
    panel.set_pending_enhancement(("running", _frame_bytes(tmp_path, 10), "2x"))

    assert _notice(panel) == "(not yet generated with modifications)"


def test_the_enhancement_landing_leaves_the_mark_standing(saved_panel, tmp_path,
                                                          monkeypatch):
    # The enhancement folds into the row the tab is showing — the image gains a
    # version, and nothing about the settings moves. So the edits made while it
    # cooked are still edits, and the mark saying so stays up rather than being
    # wiped by the picture arriving. Re-taking the mark here read those very
    # edits as the new baseline.
    panel, db = saved_panel
    output_dir = tmp_path / "out"
    (output_dir / "image").mkdir(parents=True)
    for name in ("sdxl_img1.png", "image_enhance_00001_.png"):
        (output_dir / "image" / name).write_bytes(b"x")
    monkeypatch.setattr(gcp_module, "COMFYUI_OUTPUT_DIR", output_dir)

    image = _image_row(db, "img1", prompt="a cat")
    panel.show_saved_generation(image, [image])
    _set_prompt(panel, "a dog")
    panel.set_pending_enhancement(("running", _frame_bytes(tmp_path), "2x"))

    enhanced = _fold_enhancement(db, "img1")
    panel.refresh_displayed(enhanced, [enhanced])
    panel.set_pending_enhancement(None)  # the run is over; the pane goes back

    assert _notice(panel) == "(not yet generated with modifications)"


def test_a_live_frame_clears_the_mark_it_answers(saved_panel):
    # Pressing Generate on modified settings streams the run into this pane; the
    # frames are the answer, so the warning about the old picture goes with them.
    panel, db = saved_panel
    image = _image_row(db, "img1", prompt="a cat")
    panel.show_saved_generation(image, [image])
    _set_prompt(panel, "a dog")

    panel._preview.show_message("Waiting for preview…", live=True)

    assert _notice(panel) == ""


# --- Generate says when it will draw a fresh seed ---------------------------

def _completed_generation(db, workflow_name, params):
    """Record ``params`` as a finished generation of ``workflow_name``, output and
    all — the past run a matching config would reproduce."""
    db.insert_generation(
        prompt_id="done", workflow_name=workflow_name,
        workflow_version=WORKFLOW_REGISTRY[workflow_name].version,
        positive_prompt=params.get("positive_prompt", ""), negative_prompt="",
        seed=params.get("seed"), params_json=json.dumps(params), workflow_json="{}",
    )
    db.update_generation("done", status="completed", output_files=json.dumps(
        [{"filename": "sdxl_t2i_done.png", "subfolder": "image"}]))


def test_generate_says_it_will_draw_a_random_seed_over_a_finished_run(panel, qtbot):
    # Generating settings already generated, seed and all, would only re-create
    # that same file — so the press draws a fresh seed instead, and the button says
    # so before it's pressed rather than a dialog asking after it.
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    params = dict(wf.default_params(), positive_prompt="a cat", seed=42)
    _completed_generation(panel._db, "sdxl_t2i", params)

    panel.prefill("sdxl_t2i", params)

    qtbot.waitUntil(lambda: panel._generate_btn.text() == "Generate with Random seed")
    assert "already been generated" in panel._generate_btn.toolTip()  # and why


def test_editing_the_settings_takes_the_random_seed_caption_back_off(panel, qtbot):
    # The caption follows the form: edit anything and these are no longer the
    # settings already generated, so the button goes back to a plain Generate —
    # a promise of a fresh seed it would no longer keep.
    wf = WORKFLOW_REGISTRY["sdxl_t2i"]
    params = dict(wf.default_params(), positive_prompt="a cat", seed=42)
    _completed_generation(panel._db, "sdxl_t2i", params)
    panel.prefill("sdxl_t2i", params)
    qtbot.waitUntil(lambda: panel._generate_btn.text() == "Generate with Random seed")

    panel._param_form.set_values({"positive_prompt": "a dog"})

    qtbot.waitUntil(lambda: panel._generate_btn.text() == "Generate")
    assert panel._generate_btn.toolTip() == ""


# --- asking for changes to a whole folder ------------------------------------

_FOLDER_KEY = "image/sdxl_t2i/abcdef123456"
_FOLDER_LABEL = "AB12CD34"


def _folder_params(prompt="a cat on a couch"):
    return dict(WORKFLOW_REGISTRY["sdxl_t2i"].default_params(),
                positive_prompt=prompt, negative_prompt="blurry", seed=7)


def _images(tmp_path, count):
    from PIL import Image
    paths = []
    for n in range(count):
        path = tmp_path / f"folder_{n}.png"
        Image.new("RGB", (12, 9), (30 * n, 90, 140)).save(path)
        paths.append(str(path))
    return paths


@pytest.fixture
def requesting(blank_panel, tmp_path):
    """A tab opened on a three-image folder's prompt, ready to be rewritten."""
    blank_panel.open_folder_request(_FOLDER_KEY, _FOLDER_LABEL, "sdxl_t2i",
                                    _folder_params(), _images(tmp_path, 3))
    return blank_panel


def _positive_field(panel):
    return panel._param_form._widgets["positive_prompt"]


def _request(count=3, label=_FOLDER_LABEL, opened_on=None):
    return folder_request_module.FolderRequest(
        folder_key=_FOLDER_KEY, label=label, count=count,
        opened_on=opened_on or ConfigSnapshot("sdxl_t2i", _folder_params(), False))


def test_a_request_names_itself_after_the_folder_it_asks_about():
    assert _request().title() == f"Request {_FOLDER_LABEL}"


def test_a_request_counts_its_runs_in_the_hover_rather_than_on_the_button():
    # The button asks for one thing — this folder, said the way it now reads —
    # so how many runs that costs is a hover away.
    assert _request(count=3).caption() == "Request changes"
    assert "all 3 images" in _request(count=3).tooltip()


def test_a_one_image_folder_gets_wording_of_its_own():
    # Not the plural switched off, which read "Run all 1 image ... each with its
    # own seed" on a folder holding one.
    tooltip = _request(count=1).tooltip()
    assert "one image" in tooltip
    assert "1 image" not in tooltip


def test_a_request_knows_whether_anything_has_actually_been_rewritten():
    # Unchanged, the press would run every seed in the folder to re-create the
    # folder, which is the one thing the tab must never do by accident.
    opened_on = ConfigSnapshot("sdxl_t2i", _folder_params(), False)
    request = _request(opened_on=opened_on)

    assert request.is_unchanged(ConfigSnapshot("sdxl_t2i", _folder_params(), False))
    assert not request.is_unchanged(
        ConfigSnapshot("sdxl_t2i", _folder_params(prompt="a dog on a couch"), False))


def test_a_request_cannot_be_edited_after_the_tab_opens_on_it():
    # What the tab opened on is how a press tells a rewrite from a re-run; a
    # request that could be edited could quietly agree with whatever was typed.
    from dataclasses import FrozenInstanceError

    with pytest.raises(FrozenInstanceError):
        _request().count = 9


def test_a_request_tab_shows_the_whole_folder_in_its_preview(requesting):
    # Every image the press will re-run, tiled — not the newest one of them,
    # which would say the edit was about that image.
    preview = requesting._preview
    assert preview._stack.currentWidget() is preview._sheet
    assert preview._sheet.count() == 3


def test_the_press_asks_for_changes_and_counts_them_in_the_hover(requesting):
    # The button asks for one thing — this folder, said the way it now reads —
    # so how many runs that costs is a hover away rather than on its face.
    assert requesting._generate_btn.text() == "Request changes"
    assert "all 3 images" in requesting._generate_btn.toolTip()


def test_every_prompt_is_marked_against_what_it_says_now(requesting):
    from origenerator.gui.tracked_prompt import _Tracker
    fields = requesting._param_form.text_fields()
    # Every one of them carries a tracker, each rewriting from its own text --
    # a prompt is not a change to itself, so nothing is marked until one is typed in.
    assert all(w.findChildren(_Tracker) for w in fields)
    assert {w.toPlainText() for w in fields} == {"a cat on a couch", "blurry"}


def test_the_tab_is_named_after_the_folder_it_asks_about(requesting):
    assert requesting.title() == f"Request {_FOLDER_LABEL}"


def test_a_request_tab_holds_no_generation_of_its_own(requesting):
    # It is about a folder, so there is no file on display and nothing for the
    # "not yet generated with modifications" notice to be measured against.
    assert requesting.displayed_row() is None
    assert requesting._displayed_config is None


def test_generate_asks_for_the_folder_rather_than_these_settings(requesting, qtbot):
    _positive_field(requesting).setPlainText("a dog on a couch")

    with qtbot.waitSignal(requesting.changes_requested) as caught:
        requesting._generate_btn.click()

    folder_key, workflow_name, params = caught.args
    assert folder_key == _FOLDER_KEY
    assert workflow_name == "sdxl_t2i"
    assert params["positive_prompt"] == "a dog on a couch"


def test_a_request_that_asked_for_nothing_says_so_instead_of_re_running_the_folder(
        requesting, qtbot):
    # Unchanged, the press would run every seed in the folder to re-create the
    # folder — so it asks for the rewrite instead of filling the queue.
    fired = []
    requesting.changes_requested.connect(lambda *a: fired.append(a))

    requesting._generate_btn.click()

    assert fired == []
    assert requesting._generate_btn.text() == "Rewrite the prompt first"


def test_showing_a_generation_ends_the_request(requesting, tmp_path):
    row = {"prompt_id": "p1", "workflow_name": "sdxl_t2i",
           "params_json": json.dumps(_folder_params()), "output_files": "[]"}

    requesting.show_saved_generation(row, [])

    from origenerator.gui.tracked_prompt import _Tracker
    assert not any(w.findChildren(_Tracker)
                   for w in requesting._param_form.text_fields())
    assert requesting._generate_btn.text() == "Generate"


def test_ending_the_request_gives_the_prompts_their_undo_back(requesting):
    # Undo is off while a field is tracked, since the document is rewritten under
    # the typist; a field left behind must not keep that.
    assert not _positive_field(requesting).isUndoRedoEnabled()

    requesting._end_folder_request()

    assert _positive_field(requesting).isUndoRedoEnabled()


def test_picking_another_workflow_ends_the_request(requesting):
    requesting._workflow_combo.setCurrentIndex(_combo_index(requesting, "wan22_i2v"))

    assert requesting._generate_btn.text() == "Generate"


def test_a_landed_run_does_not_take_the_wall_of_images_away(requesting):
    # The batch lands an image at a time; each one would otherwise swap the
    # folder for whichever finished last.
    row = {"prompt_id": "p1", "workflow_name": "sdxl_t2i",
           "params_json": json.dumps(_folder_params()), "output_files": "[]"}

    requesting.show_completed_result(row, [])

    assert requesting.displayed_row() is None
    assert requesting._preview._stack.currentWidget() is requesting._preview._sheet


# --- the two export lanes as one errand with a table of differences ----------
#
# Send-to-Evolver and Send-to-Genau were four methods that were two methods
# copied: same visibility rule, same read of the persisted flag, same
# try/except/warn, same re-read of the row afterwards, differing only in the
# inbox sub-folder, the column, the words and the noun. These run over whatever
# lanes the panel has, so a third one is a data entry and is covered the day it
# is added rather than the day someone writes its tests.


def _lanes():
    return list(export_lane_module.EXPORT_LANES)


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_fresh_tab_offers_no_lane_at_all(saved_panel, lane):
    panel, _db = saved_panel
    assert panel._lanes[lane.name].button.isHidden()


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_offers_itself_for_a_video_and_not_for_an_image(saved_panel,
                                                               monkeypatch, lane):
    panel, db = saved_panel
    button = panel._lanes[lane.name].button

    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    panel.show_saved_generation(_video_row(db, "vid1"), [])
    assert not button.isHidden()

    image = _image_row(db, "img1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/img1.png"), "image"))
    panel.show_saved_generation(image, [image])
    assert button.isHidden()


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_copies_the_clip_into_its_own_folder_and_remembers_the_send(
        saved_panel, monkeypatch, lane):
    panel, db = saved_panel
    button = panel._lanes[lane.name].button
    video_path = Path("C:/out/vid1.mp4")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (video_path, "video"))
    export = MagicMock(return_value=EVOLVER_INBOX_DIR / lane.source / "vid1.mp4")
    monkeypatch.setattr(evolver_export, "export_video", export)

    panel.show_saved_generation(_video_row(db, "vid1"), [])
    panel._on_send(panel._lanes[lane.name])

    # The same inbox Evolver watches, under the name that says where the result
    # belongs — the destination is the whole of what makes a lane a lane.
    export.assert_called_once_with(video_path, EVOLVER_INBOX_DIR / lane.source)
    assert panel._displayed_row[lane.flag]
    assert button.text() == f"Sent to {lane.name} ✓"
    assert button.isEnabled() is False


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_does_not_send_the_same_clip_twice(saved_panel, monkeypatch, lane):
    # Re-checked against the persisted flag rather than the button's disabled
    # state, so a stale press cannot repeat the handoff.
    panel, db = saved_panel
    _video_row(db, "vid1")
    lane.mark(db, "vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    export = MagicMock()
    monkeypatch.setattr(evolver_export, "export_video", export)

    panel.show_saved_generation(db.get_generation("vid1"), [])
    assert panel._lanes[lane.name].button.text() == f"Sent to {lane.name} ✓"
    panel._on_send(panel._lanes[lane.name])

    export.assert_not_called()


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_refuses_a_send_the_row_records_even_with_its_button_still_live(
        saved_panel, monkeypatch, lane):
    # The guard is the persisted column, not the button's disabled state. A
    # button is only as fresh as the last time the footer was drawn; the column
    # is what survives a restart. Where the two disagree the column wins, or a
    # stale press repeats a handoff another app has already been given.
    panel, db = saved_panel
    _video_row(db, "vid1")
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    export = MagicMock()
    monkeypatch.setattr(evolver_export, "export_video", export)
    panel.show_saved_generation(db.get_generation("vid1"), [])
    assert panel._lanes[lane.name].button.isEnabled()   # drawn before the send

    lane.mark(db, "vid1")
    panel._displayed_row = db.get_generation("vid1")    # …and the row moved under it
    panel._on_send(panel._lanes[lane.name])

    export.assert_not_called()


@pytest.mark.parametrize("lane", _lanes(), ids=lambda lane: lane.name)
def test_a_lane_says_so_loudly_when_the_copy_fails(saved_panel, monkeypatch, lane):
    # The copy lands in another app's inbox with no other visible result here, so
    # a failure that only reached the log would look exactly like a success.
    panel, db = saved_panel
    monkeypatch.setattr(gcp_module, "resolve_preview",
                        lambda row, out: (Path("C:/out/vid1.mp4"), "video"))
    monkeypatch.setattr(evolver_export, "export_video",
                        MagicMock(side_effect=OSError("inbox unreachable")))
    warn = MagicMock()
    monkeypatch.setattr(gcp_module.QMessageBox, "warning", warn)

    panel.show_saved_generation(_video_row(db, "vid1"), [])
    panel._on_send(panel._lanes[lane.name])  # must not raise

    warn.assert_called_once()
    assert warn.call_args.args[1] == f"Send to {lane.name} failed"
    assert not panel._displayed_row[lane.flag]


def test_every_lane_is_told_apart_by_its_folder_its_column_and_its_stamp():
    # Held as an equality per field: two lanes sharing any of these three would
    # be one lane wearing two buttons, and each is a name outside this repo —
    # Evolver keys on the folder, and the two columns are persisted.
    lanes = _lanes()
    assert len({lane.source for lane in lanes}) == len(lanes)
    assert len({lane.flag for lane in lanes}) == len(lanes)
    assert [lane.source for lane in lanes] == [EVOLVER_SOURCE, GENAU_SOURCE]


def test_every_lane_stamps_a_column_the_database_actually_writes(saved_panel):
    # The stamp and the column are two halves of one fact and are spelled apart,
    # so a lane could mark one and read the other and simply never look sent.
    panel, db = saved_panel
    _video_row(db, "vid1")

    for lane in _lanes():
        lane.mark(db, "vid1")
        assert db.get_generation("vid1")[lane.flag]
