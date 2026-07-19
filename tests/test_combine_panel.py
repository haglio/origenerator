"""CombinePanel: two drop slots + a Generate button for the image+video combine."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout

from origenerator import recipe_match
from origenerator.gui.combine_panel import CombinePanel

TOOLTIP = Qt.ItemDataRole.ToolTipRole


def _panel(qtbot):
    panel = CombinePanel(
        image_accepts=lambda pid: pid.startswith("img"),
        video_accepts=lambda pid: pid.startswith("vid"),
        preview=lambda pid: (None, None),
    )
    qtbot.addWidget(panel)
    return panel


def test_generate_is_disabled_until_both_slots_are_filled(qtbot):
    panel = _panel(qtbot)
    assert not panel._generate_btn.isEnabled()

    panel.image_slot.set_item("img1")
    assert not panel._generate_btn.isEnabled()  # the video slot is still empty

    panel.video_slot.set_item("vid1")
    assert panel._generate_btn.isEnabled()       # both filled: ready


def test_clicking_generate_emits_the_two_ids(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    got = []
    panel.generate_requested.connect(lambda i, v: got.append((i, v)))

    panel._generate_btn.click()

    assert got == [("img1", "vid1")]


def test_open_in_generator_button_tracks_the_same_enablement_as_generate(qtbot):
    # "Open in generator" needs the same ingredients as Generate — a source image
    # and a recipe — so it lights and dims in lockstep with the Generate button.
    panel = _panel(qtbot)
    assert not panel._open_btn.isEnabled()

    panel.image_slot.set_item("img1")
    assert not panel._open_btn.isEnabled()  # image alone, no recipe yet

    panel.video_slot.set_item("vid1")
    assert panel._open_btn.isEnabled()       # both filled: ready to open


def test_clicking_open_emits_the_dropped_recipe_for_the_generator(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    opened = []
    panel.open_requested.connect(lambda i, v: opened.append((i, v)))

    panel._open_btn.click()

    assert opened == [("img1", "vid1")]  # same pair Generate would, but bound for the generator


def test_clicking_open_with_a_picked_act_emits_the_category(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.set_category("delta")
    opened = []
    panel.open_category_requested.connect(lambda i, c: opened.append((i, c)))

    panel._open_btn.click()

    assert opened == [("img1", "delta")]


def test_show_drop_candidates_lights_only_the_matching_slot(qtbot):
    panel = _panel(qtbot)  # image slot accepts img*, video slot accepts vid*

    panel.show_drop_candidates("img7")
    assert panel.image_slot._label.property("dragActive") is True
    assert panel.video_slot._label.property("dragActive") is False

    panel.show_drop_candidates("vid7")  # a video now: the other slot lights instead
    assert panel.image_slot._label.property("dragActive") is False
    assert panel.video_slot._label.property("dragActive") is True

    panel.clear_drop_candidates()
    assert panel.image_slot._label.property("dragActive") is False
    assert panel.video_slot._label.property("dragActive") is False


def test_neutral_option_is_a_dash_leading_the_acts(qtbot):
    panel = _panel(qtbot)
    assert panel.selected_category() == ""  # neutral by default
    items = [panel._category.itemText(i) for i in range(panel._category.count())]
    assert items[0] == "-"                              # the neutral choice is a dash, not a prompt
    assert items[1:] == list(recipe_match.CATEGORIES)   # the six acts follow it


def _enabled(panel, text) -> bool:
    return panel._category.model().item(panel._category.findText(text)).isEnabled()


def test_acts_with_no_video_to_mine_are_greyed_out(qtbot):
    panel = _panel(qtbot)

    panel.set_available_categories({"beta", "epsilon"})

    assert _enabled(panel, "beta") and _enabled(panel, "epsilon")
    assert not _enabled(panel, "gamma")  # nothing in the gallery to build a recipe from
    assert not _enabled(panel, "dancing")
    assert _enabled(panel, "-")            # the neutral option always stays pickable


def test_an_act_becomes_pickable_once_a_video_of_it_exists(qtbot):
    panel = _panel(qtbot)
    panel.set_available_categories(set())
    assert not _enabled(panel, "dancing")

    panel.set_available_categories({"dancing"})  # the user just made one

    assert _enabled(panel, "dancing")


def test_a_greyed_act_explains_itself(qtbot):
    panel = _panel(qtbot)
    panel.set_available_categories({"beta"})
    index = panel._category.findText("gamma")
    assert "no past" in panel._category.itemData(index, TOOLTIP).lower()
    assert not panel._category.itemData(panel._category.findText("beta"), TOOLTIP)


def test_dropdown_sits_beside_the_video_slot_in_one_part(qtbot):
    panel = _panel(qtbot)
    # The dropdown configures the *video* recipe, so it shares one container with the
    # video slot — laid out side by side, not stacked, and not a peer of the image.
    assert panel._category.parent() is panel.video_slot.parent()
    assert panel.image_slot.parent() is not panel.video_slot.parent()
    assert isinstance(panel._category.parent().layout(), QHBoxLayout)


def test_a_picked_category_enables_generate_with_only_an_image(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    assert not panel._generate_btn.isEnabled()  # image alone, no recipe chosen yet

    panel.set_category("alpha")
    assert panel._generate_btn.isEnabled()      # a category is a recipe — no video needed

    panel.set_category("")                       # back to neutral
    assert not panel._generate_btn.isEnabled()


def test_picking_an_act_clears_the_dropped_video_without_collapsing(qtbot):
    panel = _panel(qtbot)
    panel.video_slot.set_item("vid1")

    panel.set_category("alpha")

    assert panel.video_slot.current_id() is None  # the act supersedes it, so the video is dropped
    assert not panel.video_slot.isHidden()         # but the slot stays put — the area doesn't collapse


def test_dropping_a_video_resets_the_dropdown_to_neutral(qtbot):
    panel = _panel(qtbot)
    panel.set_category("delta")

    panel.video_slot.set_item("vid1")

    assert panel.selected_category() == ""          # a dropped video wipes the act back to "-"
    assert panel.video_slot.current_id() == "vid1"  # ...and the video is what's kept


def test_picking_an_act_relabels_the_video_drop_zone(qtbot):
    panel = _panel(qtbot)
    assert panel.video_slot._label.text() == "Drop an I2V video"  # neutral prompt

    panel.set_category("gamma")
    assert panel.video_slot._label.text() == "use custom action from video"  # act active: the override hint

    panel.set_category("")
    assert panel.video_slot._label.text() == "Drop an I2V video"  # neutral again


def test_generate_emits_the_picked_act(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.set_category("delta")
    cats = []
    panel.category_requested.connect(lambda i, c: cats.append((i, c)))

    panel._generate_btn.click()

    assert cats == [("img1", "delta")]


def test_clearing_a_slot_disables_generate_again(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    assert panel._generate_btn.isEnabled()

    panel.image_slot.clear()

    assert not panel._generate_btn.isEnabled()
