"""CombinePanel: two drop slots + a Generate button for the image+video combine."""

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


def test_clearing_a_slot_disables_generate_again(qtbot):
    panel = _panel(qtbot)
    panel.image_slot.set_item("img1")
    panel.video_slot.set_item("vid1")
    assert panel._generate_btn.isEnabled()

    panel.image_slot.clear()

    assert not panel._generate_btn.isEnabled()
