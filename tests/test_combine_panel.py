"""CombinePanel: two drop slots + a Generate button for the image+video combine."""

from origenerator import recipe_match
from origenerator.gui.combine_panel import CombinePanel


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


def test_video_part_offers_every_category_blank_by_default(qtbot):
    panel = _panel(qtbot)
    assert panel.selected_category() == ""  # nothing pre-selected
    items = [panel._category.itemText(i) for i in range(panel._category.count())]
    assert items == list(recipe_match.CATEGORIES)


def test_a_picked_category_enables_generate_with_only_an_image(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    assert not panel._generate_btn.isEnabled()  # image alone, no recipe chosen yet

    panel.set_category("gamma")
    assert panel._generate_btn.isEnabled()      # a category is a recipe — no video needed

    panel.set_category("")                       # back to blank
    assert not panel._generate_btn.isEnabled()


def test_generate_emits_category_and_it_wins_over_a_dropped_video(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")   # a video is also sitting there
    panel.set_category("redacted")
    cats, vids = [], []
    panel.category_requested.connect(lambda i, c: cats.append((i, c)))
    panel.generate_requested.connect(lambda i, v: vids.append((i, v)))

    panel._generate_btn.click()

    assert cats == [("img1", "redacted")]  # the picked act takes precedence
    assert vids == []                     # the dropped video is not used


def test_clearing_a_slot_disables_generate_again(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    assert panel._generate_btn.isEnabled()

    panel.image_slot.clear()

    assert not panel._generate_btn.isEnabled()
