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


def _pick_act(panel, act):
    """Choose an act in the dropdown, as a click on its row would; "" is the
    neutral "-" and so is an act the list does not carry."""
    index = panel._category.findText(act)
    panel._category.setCurrentIndex(index if index >= 1 else 0)


def _pick_lane(panel, intent):
    """Click the lane's radio; the group's exclusivity releases the other."""
    radio = (panel._genau_radio if intent == recipe_match.GENAU
             else panel._players_radio)
    radio.setChecked(True)



def test_only_the_video_slot_is_drained_of_color(qtbot):
    # The video is here for its settings — never for what it looks like — while
    # the image is the very thing being animated.
    panel = _panel(qtbot)

    assert panel.video_slot._grayscale
    assert not panel.image_slot._grayscale


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
    _pick_act(panel, "delta")
    opened = []
    panel.open_category_requested.connect(lambda i, c, n: opened.append((i, c, n)))

    panel._open_btn.click()

    assert opened == [("img1", "delta", recipe_match.PLAYERS)]


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

    _pick_act(panel, "alpha")
    assert panel._generate_btn.isEnabled()      # a category is a recipe — no video needed

    _pick_act(panel, "")                       # back to neutral
    assert not panel._generate_btn.isEnabled()


def test_picking_an_act_clears_the_dropped_video_without_collapsing(qtbot):
    panel = _panel(qtbot)
    panel.video_slot.set_item("vid1")

    _pick_act(panel, "alpha")

    assert panel.video_slot.current_id() is None  # the act supersedes it, so the video is dropped
    assert not panel.video_slot.isHidden()         # but the slot stays put — the area doesn't collapse


def test_dropping_a_video_resets_the_dropdown_to_neutral(qtbot):
    panel = _panel(qtbot)
    _pick_act(panel, "delta")

    panel.video_slot.set_item("vid1")

    assert panel.selected_category() == ""          # a dropped video wipes the act back to "-"
    assert panel.video_slot.current_id() == "vid1"  # ...and the video is what's kept


def test_picking_an_act_relabels_the_video_drop_zone(qtbot):
    panel = _panel(qtbot)
    assert panel.video_slot._label.text() == "Drop an I2V video"  # neutral prompt

    _pick_act(panel, "gamma")
    assert panel.video_slot._label.text() == "use custom action from video"  # act active: the override hint

    _pick_act(panel, "")
    assert panel.video_slot._label.text() == "Drop an I2V video"  # neutral again


def test_generate_emits_the_picked_act(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    _pick_act(panel, "delta")
    cats = []
    panel.category_requested.connect(lambda i, c, n: cats.append((i, c, n)))

    panel._generate_btn.click()

    assert cats == [("img1", "delta", recipe_match.PLAYERS)]


def test_clearing_a_slot_disables_generate_again(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    assert panel._generate_btn.isEnabled()

    panel.image_slot.clear()

    assert not panel._generate_btn.isEnabled()


# --- the players/Genau radio: what the result is for --------------------------


def test_the_lane_defaults_to_players(qtbot):
    # The long-standing behavior of this panel, and by far the more common ask, so
    # the Genau clip is the deliberate detour rather than the default.
    panel = _panel(qtbot)
    assert panel.selected_intent() == recipe_match.PLAYERS
    assert panel._players_radio.isChecked()
    assert not panel._genau_radio.isChecked()


def test_the_radio_sits_below_the_dropdown_it_changes(qtbot):
    panel = _panel(qtbot)
    layout = panel.layout()
    order = [layout.itemAt(i).widget() for i in range(layout.count())]
    assert order.index(panel._intent_part) == order.index(panel._video_part) + 1


def test_generate_carries_the_chosen_lane(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    _pick_act(panel, "delta")
    _pick_lane(panel, recipe_match.GENAU)
    cats = []
    panel.category_requested.connect(lambda i, c, n: cats.append((i, c, n)))

    panel._generate_btn.click()

    assert cats == [("img1", "delta", recipe_match.GENAU)]


def test_switching_the_lane_announces_it_once(qtbot):
    # buttonToggled fires for both radios on one click — the off edge and the on
    # edge — and the view answers each by re-greying the whole act list.
    panel = _panel(qtbot)
    heard = []
    panel.intent_changed.connect(heard.append)

    _pick_lane(panel, recipe_match.GENAU)
    assert heard == [recipe_match.GENAU]

    _pick_lane(panel, recipe_match.PLAYERS)
    assert heard == [recipe_match.GENAU, recipe_match.PLAYERS]


def test_a_greyed_act_explains_itself_in_the_lanes_own_terms(qtbot):
    panel = _panel(qtbot)
    _pick_lane(panel, recipe_match.GENAU)
    panel.set_available_categories({"beta"})

    reason = panel._category.itemData(panel._category.findText("gamma"), TOOLTIP)
    # An act the players' lane answers happily can still have no loop behind it, so
    # the greyed-out reason has to name which lane it is talking about.
    assert "looping" in reason.lower()


def test_an_act_the_new_lane_cannot_answer_is_not_left_selected(qtbot):
    # Otherwise Generate stays lit on a pick the lane has no recipe for, and the
    # click can only end in "no recipe yet".
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    _pick_act(panel, "gamma")
    assert panel._generate_btn.isEnabled()

    panel.set_available_categories({"beta"})  # gamma just went unanswerable

    assert panel.selected_category() == ""
    assert not panel._generate_btn.isEnabled()
